"""
End-to-End Tests for Debug2Learn on the todo_demo bug scenario.

Validates the 6 requirements:
1. '[x]' is preserved by Decoder without sanitization.
2. Solver distinguishes test failure location from root-cause location.
3. Solver identifies 'todo.py -> count_pending()' as the root cause.
4. Master generates contextual progressive hints (Nudge -> Clue -> Direct Clue).
5. Librarian returns relevant concept resources (list comprehension / filtering / boolean negation).
6. Tracker detects function modification when condition logic is changed.
"""

import pytest

from backend.agents.decoder import DecoderAgent
from backend.agents.explorer import ExplorerAgent
from backend.agents.librarian import LibrarianAgent
from backend.agents.master import MasterAgent
from backend.agents.solver import SolverAgent
from backend.agents.tracker import TrackerAgent
from backend.config.settings import AppConfig
from backend.core.models import (
    HintLevel,
    ProjectContext,
    RequestContext,
    SessionPhase,
    ValidationState,
)


@pytest.fixture
def config():
    return AppConfig()


@pytest.fixture
def todo_project(tmp_path):
    """Create the todo_demo project structure."""
    todo_code = """def add_task(tasks, task):
    if task.strip() == "":
        return tasks
    tasks.append(task)
    return tasks


def remove_task(tasks, task):
    if task in tasks:
        tasks.remove(task)
    return tasks


def count_pending(tasks):
    return len([task for task in tasks if task.startswith("[x]")])
"""
    test_todo_code = """from todo import add_task, remove_task, count_pending


def test_add_task():
    tasks = []
    add_task(tasks, "Learn Python")
    assert tasks == ["Learn Python"]


def test_remove_task():
    tasks = ["Learn Python", "Build AI"]
    remove_task(tasks, "Learn Python")
    assert tasks == ["Build AI"]


def test_count_pending():
    tasks = ["Learn Python", "[x] Build AI", "Study"]
    assert count_pending(tasks) == 2
"""
    (tmp_path / "todo.py").write_text(todo_code)
    (tmp_path / "test_todo.py").write_text(test_todo_code)
    return tmp_path


def test_decoder_preserves_x_and_extracts_signals(config):
    """1. Verify '[x]' is preserved by Decoder and signals are extracted."""
    decoder = DecoderAgent(config)
    bug_desc = 'count_pending returns 1 instead of 2. It should count tasks that are NOT marked as completed with "[x]".'

    ctx = decoder.decode(bug_desc)

    # Must preserve '[x]' literal
    assert "[x]" in ctx.raw_input
    assert "[x]" in ctx.symptom
    assert ctx.symptom != ""
    assert ctx.target_function == "count_pending"
    assert ctx.actual_value == "1"
    assert ctx.expected_value == "2"
    assert "filtering" in ctx.domain or "boolean" in ctx.domain or "logic" in ctx.domain


def test_explorer_understands_test_vs_source_relationship(config, todo_project):
    """Verify Explorer maps test_todo.py to todo.py and knows functions."""
    explorer = ExplorerAgent(config)
    p_ctx = explorer.explore(todo_project)

    assert "test_todo.py" in p_ctx.test_files
    assert "todo.py" in p_ctx.source_files
    assert p_ctx.test_to_source_mapping.get("test_todo.py") == "todo.py"
    assert p_ctx.function_to_file.get("count_pending") == "todo.py"

    rel = explorer.resolve_relationships(p_ctx, ["test_todo.py"], "count_pending")
    assert rel["failure_detection_file"] == "test_todo.py"
    assert rel["root_cause_file"] == "todo.py"
    assert "todo.py" in rel["relevant_files"]
    assert "test_todo.py" in rel["relevant_files"]


def test_solver_distinguishes_failure_from_root_cause(config, todo_project):
    """2 & 3. Verify Solver distinguishes test location from root-cause location and identifies todo.py -> count_pending()."""
    explorer = ExplorerAgent(config)
    p_ctx = explorer.explore(todo_project)

    decoder = DecoderAgent(config)
    bug_report = 'FAILED test_todo.py::test_count_pending\ncount_pending returns 1 instead of 2. It should count tasks that are NOT marked as completed with "[x]".'
    r_ctx = decoder.decode(bug_report, p_ctx)

    relevant_code = {
        "todo.py": (todo_project / "todo.py").read_text(),
        "test_todo.py": (todo_project / "test_todo.py").read_text(),
    }

    solver = SolverAgent(config)
    plan = solver.create_plan(p_ctx, r_ctx, relevant_code)

    # Must distinguish test/failure location from root-cause location
    assert "test_todo.py" in plan.failure_location
    assert "todo.py" in plan.root_cause_location
    assert "count_pending" in plan.root_cause_location
    assert "test_todo.py" not in plan.root_cause_location

    # Must reason about actual implementation rather than just parroting symptom
    assert "count_pending" in plan.hypothesis
    assert "[x]" in plan.hypothesis or "[x]" in plan.relevant_logic
    assert plan.confidence >= 0.8
    assert len(plan.steps) >= 2


def test_master_generates_contextual_progressive_hints(config, todo_project):
    """4. Master generates progressive hints based on Solver plan."""
    explorer = ExplorerAgent(config)
    p_ctx = explorer.explore(todo_project)

    decoder = DecoderAgent(config)
    bug_report = 'count_pending returns 1 instead of 2. It should count tasks that are NOT marked as completed with "[x]".'
    r_ctx = decoder.decode(bug_report, p_ctx)

    relevant_code = {
        "todo.py": (todo_project / "todo.py").read_text(),
        "test_todo.py": (todo_project / "test_todo.py").read_text(),
    }

    solver = SolverAgent(config)
    plan = solver.create_plan(p_ctx, r_ctx, relevant_code)

    master = MasterAgent(config)
    step1 = plan.steps[0]

    # Level 1: Nudge
    h1 = master.get_progressive_hint(
        step1, 0, relevant_code["todo.py"], plan=plan, request_context=r_ctx
    )
    assert h1.level == HintLevel.CONCEPTUAL
    assert (
        "[x]" in h1.content
        or "status" in h1.content.lower()
        or "pending" in h1.content.lower()
    )

    # Level 2: Clue
    h2 = master.get_progressive_hint(
        step1, 1, relevant_code["todo.py"], plan=plan, request_context=r_ctx
    )
    assert h2.level == HintLevel.DIRECTIONAL
    assert (
        "completed" in h2.content.lower()
        or "pending" in h2.content.lower()
        or "include" in h2.content.lower()
    )

    # Level 3: Direct Clue
    h3 = master.get_progressive_hint(
        step1, 2, relevant_code["todo.py"], plan=plan, request_context=r_ctx
    )
    assert h3.level == HintLevel.SPECIFIC
    assert (
        "not" in h3.content.lower()
        or "condition" in h3.content.lower()
        or "startswith" in h3.content.lower()
    )

    # Verify that the direct code solution is NEVER given away
    for h in (h1, h2, h3):
        assert "not task.startswith('[x]')" not in h.content
        assert 'not task.startswith("[x]")' not in h.content


def test_librarian_returns_relevant_resources(config):
    """5. Librarian returns resources on filtering/list comprehensions/boolean negation and avoids generic exception guides."""
    librarian = LibrarianAgent(config)
    r_ctx = RequestContext(
        raw_input='count_pending returns 1 instead of 2. It should count tasks that are NOT marked as completed with "[x]".',
        symptom="count_pending returns 1 instead of 2",
        domain="filtering / boolean conditions",
    )

    resources = librarian.find_resources(r_ctx)
    assert len(resources) >= 2

    # Should contain list comprehension and/or boolean operations
    titles = [r.title for r in resources]
    assert any("List Comprehension" in t for t in titles)
    assert any("Boolean" in t for t in titles)

    # Should NOT contain generic "Errors and Exceptions" since no exception was raised
    assert not any("Errors and Exceptions" in t for t in titles)


def test_tracker_detects_function_modification_without_git(config, todo_project):
    """Verify Tracker detects change inside count_pending body without Git on both files."""
    tracker = TrackerAgent(config, todo_project)
    # Explicitly ensure Git is unavailable to test in-memory baseline path
    tracker.git_analyzer._available = False
    assert not tracker.git_analyzer.is_available

    # 1. Snapshot both suspected source and test files before edits
    tracker.snapshot_relevant_files(["todo.py", "test_todo.py"])
    assert "todo.py" in tracker._file_snapshots
    assert "test_todo.py" in tracker._file_snapshots

    # No changes initially
    cs_init = tracker.track_changes()
    assert not cs_init.has_changes

    # 2. Modify the condition in todo.py
    todo_file = todo_project / "todo.py"
    fixed_code = """def add_task(tasks, task):
    if task.strip() == "":
        return tasks
    tasks.append(task)
    return tasks


def remove_task(tasks, task):
    if task in tasks:
        tasks.remove(task)
    return tasks


def count_pending(tasks):
    return len([task for task in tasks if not task.startswith("[x]")])
"""
    todo_file.write_text(fixed_code)

    # 3. Call track_changes - should detect todo.py change without Git
    cs = tracker.track_changes(["todo.py", "test_todo.py"])
    assert cs.has_changes
    assert "todo.py" in cs.files_changed
    assert "test_todo.py" not in cs.files_changed

    # 4. Check function symbol was identified via AST
    func_symbols = [c.symbol for c in cs.changes if c.symbol]
    assert "count_pending" in func_symbols

    # 5. Verify Solver evaluates the change as addressing the diagnosed issue
    # IMPORTANT: Does NOT immediately say "bug fixed" or advance_step! Enters AWAITING_TEST_VALIDATION
    solver = SolverAgent(config)
    p_ctx = ProjectContext(project_path=str(todo_project), project_name="todo_demo")
    r_ctx = RequestContext(
        raw_input='count_pending returns 1 instead of 2. It should count tasks that are NOT marked as completed with "[x]".',
        symptom="count_pending returns 1 instead of 2",
        target_function="count_pending",
        relevant_files=["todo.py", "test_todo.py"],
    )
    plan = solver.create_plan(p_ctx, r_ctx, {"todo.py": fixed_code})
    eval_res = solver.evaluate_changes(plan, cs, r_ctx, {"todo.py": fixed_code})
    assert eval_res["is_relevant"] is True
    assert eval_res["ready_for_test"] is True
    assert eval_res["advance_step"] is False  # NOT marked fixed yet!
    assert eval_res["state"] == ValidationState.AWAITING_TEST_VALIDATION
    assert eval_res["test_command"] == "pytest"
    assert "pytest" in eval_res["feedback"]

    # 6. Verify unrelated file changes are marked not relevant (CHANGE_DETECTED)
    unrelated_file = todo_project / "unrelated.py"
    unrelated_file.write_text("x = 1\n")
    tracker.snapshot_relevant_files(["unrelated.py"])
    unrelated_file.write_text("x = 2\n")
    cs_unrelated = tracker.track_changes(["unrelated.py"])
    eval_unrelated = solver.evaluate_changes(
        plan, cs_unrelated, r_ctx, {"unrelated.py": "x = 2\n"}
    )
    assert eval_unrelated["is_relevant"] is False
    assert eval_unrelated["state"] == ValidationState.CHANGE_DETECTED


def test_fix_validation_workflow_states(config, todo_project):
    """
    Validates the complete 6-state fix validation workflow:
    A. CHANGE_DETECTED
    B. CHANGE_RELEVANT
    C. AWAITING_TEST_VALIDATION
    D. TEST_FAILED
    E. TEST_PASSED
    F. QUEST_COMPLETED
    """
    from backend.core.state import StateManager

    state_mgr = StateManager()
    solver = SolverAgent(config)
    tracker = TrackerAgent(config, todo_project)
    tracker.git_analyzer._available = False
    tracker.snapshot_relevant_files(["todo.py", "test_todo.py"])

    p_ctx = ProjectContext(project_path=str(todo_project), project_name="todo_demo")
    r_ctx = RequestContext(
        raw_input='count_pending returns 1 instead of 2. It should count tasks that are NOT marked as completed with "[x]".',
        symptom="count_pending returns 1 instead of 2",
        target_function="count_pending",
        relevant_files=["todo.py", "test_todo.py"],
    )
    plan = solver.create_plan(
        p_ctx, r_ctx, {"todo.py": (todo_project / "todo.py").read_text()}
    )
    state_mgr.set_debugging_plan(plan)

    # ── State A: CHANGE_DETECTED (Unrelated file edited) ──
    unrelated_file = todo_project / "other.py"
    unrelated_file.write_text("a = 10\n")
    tracker.snapshot_relevant_files(["other.py"])
    unrelated_file.write_text("a = 20\n")
    cs_unrelated = tracker.track_changes(["other.py"])
    eval_unrel = solver.evaluate_changes(
        plan, cs_unrelated, r_ctx, {"other.py": "a = 20\n"}
    )
    assert eval_unrel["state"] == ValidationState.CHANGE_DETECTED
    assert eval_unrel["is_relevant"] is False
    assert eval_unrel["ready_for_test"] is False

    # ── State B: CHANGE_RELEVANT (Suspected function edited, but root cause not solved) ──
    partial_code = """def count_pending(tasks):
    # Added comment but logic still unchanged
    return len([task for task in tasks if task.startswith("[x]")])
"""
    (todo_project / "todo.py").write_text(partial_code)
    cs_partial = tracker.track_changes(["todo.py"])
    eval_partial = solver.evaluate_changes(
        plan, cs_partial, r_ctx, {"todo.py": partial_code}
    )
    assert eval_partial["state"] == ValidationState.CHANGE_RELEVANT
    assert eval_partial["is_relevant"] is True
    assert eval_partial["ready_for_test"] is False
    assert eval_partial["advance_step"] is False

    # ── State C: AWAITING_TEST_VALIDATION ──
    # Tricky case: developer modified code with 'not task.startswith("[x]")' but added '+ 1'
    # Looks superficially like it addresses root cause, but is NOT verified!
    subtly_broken_code = """def count_pending(tasks):
    return len([task for task in tasks if not task.startswith("[x]")]) + 1
"""
    (todo_project / "todo.py").write_text(subtly_broken_code)
    cs_broken = tracker.track_changes(["todo.py"])
    eval_broken = solver.evaluate_changes(
        plan, cs_broken, r_ctx, {"todo.py": subtly_broken_code}
    )
    assert eval_broken["state"] == ValidationState.AWAITING_TEST_VALIDATION
    assert eval_broken["ready_for_test"] is True
    assert eval_broken["advance_step"] is False  # DO NOT declare victory!
    state_mgr.set_validation_state(ValidationState.AWAITING_TEST_VALIDATION)
    assert state_mgr.validation_state == ValidationState.AWAITING_TEST_VALIDATION

    # ── State D: TEST_FAILED (Tests run locally, pasted result shows failure) ──
    # Developer runs `pytest` and pastes failing output:
    pasted_fail_output = """
=================================== FAILURES ===================================
______________________________ test_count_pending ______________________________
    def test_count_pending():
        tasks = ["Learn Python", "[x] Build AI", "Study"]
>       assert count_pending(tasks) == 2
E       assert 3 == 2

test_todo.py:18: AssertionError
=========================== short test summary info ===========================
FAILED test_todo.py::test_count_pending - assert 3 == 2
========================= 1 failed, 2 passed in 0.04s =========================
"""
    test_eval_fail = solver.evaluate_test_output(pasted_fail_output, plan, r_ctx)
    assert test_eval_fail["passed"] is False
    assert test_eval_fail["state"] == ValidationState.TEST_FAILED
    assert test_eval_fail["advance_step"] is False
    assert test_eval_fail["test_result"].failed == 1
    assert test_eval_fail["test_result"].passed == 2
    state_mgr.record_test_result(test_eval_fail["test_result"], passed=False)
    assert state_mgr.validation_state == ValidationState.TEST_FAILED
    assert state_mgr.phase == SessionPhase.TEST_FAILED

    # ── State E & F: TEST_PASSED ➔ QUEST_COMPLETED ──
    # Developer fixes the code correctly:
    correct_code = """def count_pending(tasks):
    return len([task for task in tasks if not task.startswith("[x]")])
"""
    (todo_project / "todo.py").write_text(correct_code)
    cs_correct = tracker.track_changes(["todo.py"])
    eval_correct = solver.evaluate_changes(
        plan, cs_correct, r_ctx, {"todo.py": correct_code}
    )
    assert eval_correct["ready_for_test"] is True
    assert eval_correct["advance_step"] is False

    # Developer runs `pytest` locally and pastes passing output:
    pasted_pass_output = """
============================= test session starts =============================
collected 3 items

test_todo.py ...                                                         [100%]

============================== 3 passed in 0.02s ==============================
"""
    test_eval_pass = solver.evaluate_test_output(pasted_pass_output, plan, r_ctx)
    assert test_eval_pass["passed"] is True
    assert test_eval_pass["state"] == ValidationState.TEST_PASSED
    assert test_eval_pass["advance_step"] is True
    assert test_eval_pass["test_result"].passed == 3
    assert test_eval_pass["test_result"].failed == 0

    state_mgr.record_test_result(test_eval_pass["test_result"], passed=True)
    assert state_mgr.validation_state == ValidationState.TEST_PASSED
    assert state_mgr.phase == SessionPhase.TEST_PASSED

    state_mgr.advance_step()
    state_mgr.complete_quest()
    assert state_mgr.validation_state == ValidationState.QUEST_COMPLETED
    assert state_mgr.phase == SessionPhase.QUEST_COMPLETED
