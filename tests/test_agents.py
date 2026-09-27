"""
Tests for Debug2Learn Game Agents.
Validates Explorer, Decoder, Solver, Tracker, Librarian, and Master.
"""

from pathlib import Path

import pytest

from debug2learn.agents.decoder import DecoderAgent
from debug2learn.agents.explorer import ExplorerAgent
from debug2learn.agents.librarian import LibrarianAgent
from debug2learn.agents.master import MasterAgent
from debug2learn.agents.solver import SolverAgent
from debug2learn.agents.tracker import TrackerAgent
from debug2learn.config.settings import AppConfig
from debug2learn.core.models import (
    DebuggingPlan,
    DebuggingStep,
    HintLevel,
    ProjectContext,
    RequestContext,
    SessionState,
)


@pytest.fixture
def config():
    return AppConfig()


def test_decoder_deterministic_extraction(config):
    agent = DecoderAgent(config)
    sample_traceback = """
    Traceback (most recent call last):
      File "calculator.py", line 42, in add
        return a + b
    TypeError: unsupported operand type(s) for +: 'int' and 'str'
    """
    ctx = agent.decode(sample_traceback)
    assert isinstance(ctx, RequestContext)
    assert any("calculator.py" in f for f in ctx.relevant_files)
    assert any("TypeError" in err for err in ctx.error_messages)


def test_explorer_scan(config, tmp_path):
    (tmp_path / "app.py").write_text("def run():\n    return 42\n")
    agent = ExplorerAgent(config)
    ctx = agent.explore(tmp_path)
    assert isinstance(ctx, ProjectContext)
    assert "app.py" in ctx.files
    assert ctx.total_functions == 1


def test_solver_fallback_plan(config):
    agent = SolverAgent(config)
    p_ctx = ProjectContext(project_path=".", project_name="demo")
    r_ctx = RequestContext(
        raw_input="KeyError: 'user_id'",
        symptom="KeyError: 'user_id'",
        relevant_files=["auth.py"],
    )
    plan = agent.create_plan(p_ctx, r_ctx, {"auth.py": "def auth(d): return d['user_id']"})
    assert isinstance(plan, DebuggingPlan)
    assert len(plan.steps) >= 1
    assert plan.steps[0].target_file == "auth.py"


def test_librarian_resources(config):
    agent = LibrarianAgent(config)
    r_ctx = RequestContext(
        raw_input="TypeError in math",
        symptom="TypeError: int and str",
        domain="types",
    )
    resources = agent.find_resources(r_ctx)
    assert len(resources) >= 1
    assert any("Type" in r.title for r in resources)


def test_tracker_detects_changes(config, tmp_path):
    target_file = tmp_path / "target.py"
    target_file.write_text("def calculate():\n    return 10\n")

    tracker = TrackerAgent(config, tmp_path)
    tracker.snapshot_relevant_files(["target.py"])

    # No changes initially
    cs1 = tracker.track_changes(["target.py"])
    assert not cs1.has_changes

    # Modify file
    target_file.write_text("def calculate():\n    return 20\n")
    cs2 = tracker.track_changes(["target.py"])
    assert cs2.has_changes
    assert "target.py" in cs2.files_changed


def test_master_progressive_hints(config):
    agent = MasterAgent(config)
    step = DebuggingStep(
        step_number=1,
        title="Check variable types",
        description="Verify inputs",
        target_file="math.py",
        expected_observation="One input is a string",
    )

    h1 = agent.get_progressive_hint(step, 0)
    assert h1.level == HintLevel.CONCEPTUAL

    h2 = agent.get_progressive_hint(step, 1)
    assert h2.level == HintLevel.DIRECTIONAL

    h3 = agent.get_progressive_hint(step, 2)
    assert h3.level == HintLevel.SPECIFIC


def test_decoder_parse_test_output(config):
    decoder = DecoderAgent(config)

    # 1. Pytest passing output
    out1 = "= 3 passed in 0.05s ="
    res1 = decoder.parse_test_output(out1)
    assert res1.all_passed is True
    assert res1.passed == 3
    assert res1.failed == 0

    # 2. Pytest failing output
    out2 = """
FAILED test_todo.py::test_count_pending - assert 3 == 2
= 1 failed, 2 passed in 0.05s =
"""
    res2 = decoder.parse_test_output(out2)
    assert res2.all_passed is False
    assert res2.passed == 2
    assert res2.failed == 1
    assert len(res2.test_results) >= 1

    # 3. Simple text
    out3 = "3 passed"
    res3 = decoder.parse_test_output(out3)
    assert res3.all_passed is True
    assert res3.passed == 3

