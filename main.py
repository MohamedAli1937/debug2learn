"""
🎮 Debug2Learn — AI Debugging Tutor (MVP Interactive Game Loop).

Run this script to start an interactive debugging session:
    python main.py

The 6 Game Companions:
    🧭 Explorer   - Explores & maps relevant project files, tests, and source implementations
    🔐 Decoder    - Decodes bug reports without stripping code tokens like '[x]'
    🧩 Solver     - Diagnoses root causes (distinguishing failure detection from root cause)
    🎯 Tracker    - Tracks developer modifications in relevant files
    📚 Librarian  - Recommends targeted documentation & concept guides
    👑 Master     - Socratic mentor guiding you with hints & questions
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to sys.path so debug2learn is importable
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.decoder import DecoderAgent
from backend.agents.explorer import ExplorerAgent
from backend.agents.librarian import LibrarianAgent
from backend.agents.master import MasterAgent
from backend.agents.solver import SolverAgent
from backend.agents.tracker import TrackerAgent
from backend.config.settings import load_config
from backend.core.models import SessionPhase, ValidationState
from backend.core.state import StateManager
from backend.utils.display import (
    console,
    print_agent_action,
    print_banner,
    print_changes,
    print_diff,
    print_error,
    print_hint,
    print_info,
    print_master,
    print_plan_overview,
    print_resources,
    print_success,
    print_test_summary,
    print_warning,
    prompt_input,
)


def run_interactive_session():
    """Main interactive debugging session loop."""
    print_banner()

    config = load_config()
    state_mgr = StateManager()

    console.print("\n[bold cyan]Step 1: Setup Target Project[/bold cyan]")
    default_path = str(PROJECT_ROOT)
    proj_input = console.input(
        f"  Enter project path [dim](default: {default_path})[/dim]: "
    ).strip()
    target_project = Path(proj_input) if proj_input else PROJECT_ROOT
    if not target_project.exists():
        print_error(f"Directory not found: {target_project}")
        return

    console.print(
        "\n[bold cyan]Step 2: Describe the Bug or Paste Traceback[/bold cyan]"
    )
    console.print(
        "  [dim]Example: 'count_pending returns 1 instead of 2. It should count tasks that are NOT marked as completed with \"[x]\".'[/dim]"
    )
    bug_input = console.input("  Bug description / error: ").strip()
    if not bug_input:
        print_warning("No bug description provided. Using sample demonstration bug.")
        bug_input = 'count_pending returns 1 instead of 2. It should count tasks that are NOT marked as completed with "[x]".'

    # 1. 🔐 Decoder decodes the bug report
    print_agent_action(
        "Decoder",
        "🔐",
        "Analyzing bug report and extracting signals without sanitizing tokens...",
        "yellow",
    )
    decoder = DecoderAgent(config)
    request_ctx = decoder.decode(bug_input)
    state_mgr.set_request_context(request_ctx)
    print_success(f"Detected issue: [bold]{request_ctx.symptom}[/bold]")
    if request_ctx.target_function:
        print_info(f"Target function: {request_ctx.target_function}")
    if request_ctx.expected_value and request_ctx.actual_value:
        print_info(
            f"Expected: {request_ctx.expected_value} | Observed: {request_ctx.actual_value}"
        )

    # 2. 🧭 Explorer explores relevant project files and maps test/source relationships
    print_agent_action(
        "Explorer", "🧭", f"Exploring files in {target_project.name}...", "cyan"
    )
    explorer = ExplorerAgent(config)
    project_ctx = explorer.explore(
        target_project, relevant_files_hint=request_ctx.relevant_files
    )
    state_mgr.set_project_context(project_ctx)
    print_success(
        f"Mapped {project_ctx.total_files} files ({len(project_ctx.source_files)} source, {len(project_ctx.test_files)} tests)."
    )

    # Resolve relationships between tests and source implementation
    rel_info = explorer.resolve_relationships(
        project_ctx,
        request_ctx.relevant_files,
        request_ctx.target_function,
    )
    if rel_info["failure_detection_file"] and not request_ctx.failure_location:
        request_ctx.failure_location = rel_info["failure_detection_file"]
    if rel_info["root_cause_file"] and not request_ctx.root_cause_file:
        request_ctx.root_cause_file = rel_info["root_cause_file"]

    for rf in rel_info["relevant_files"]:
        if rf not in request_ctx.relevant_files:
            request_ctx.relevant_files.append(rf)

    # Collect relevant code snippets from both implementation and test files
    relevant_code: dict[str, str] = {}
    for rel_path in request_ctx.relevant_files:
        full_p = target_project / rel_path
        if full_p.exists() and full_p.is_file():
            relevant_code[rel_path] = full_p.read_text(
                encoding="utf-8", errors="replace"
            )

    # If no files matched, include top source and test files
    if not relevant_code and project_ctx.files:
        for sk in list(project_ctx.files.keys())[:3]:
            full_p = target_project / sk
            if full_p.exists() and full_p.is_file():
                relevant_code[sk] = full_p.read_text(encoding="utf-8", errors="replace")
                request_ctx.relevant_files.append(sk)

    if request_ctx.failure_location:
        print_info(f"Failure detection: {request_ctx.failure_location}")
    if request_ctx.root_cause_file:
        print_info(f"Suspected source: {request_ctx.root_cause_file}")

    # 3. 🧩 Solver creates the debugging plan
    print_agent_action(
        "Solver",
        "🧩",
        "Synthesizing hypothesis, isolating root cause & designing pedagogical plan...",
        "magenta",
    )
    solver = SolverAgent(config)
    plan = solver.create_plan(project_ctx, request_ctx, relevant_code)
    state_mgr.set_debugging_plan(plan)
    print_plan_overview(plan)

    # 4. 📚 Librarian finds learning resources
    print_agent_action(
        "Librarian",
        "📚",
        "Curating concept resources (filtering, list comprehensions, boolean logic)...",
        "blue",
    )
    librarian = LibrarianAgent(config)
    resources = librarian.find_resources(request_ctx, plan)
    state_mgr.add_resources(resources)

    # 5. 🎯 Tracker snapshots the target files
    print_agent_action(
        "Tracker",
        "🎯",
        "Taking baseline snapshots of relevant source and test files...",
        "green",
    )

    files_to_track = list(request_ctx.relevant_files)
    if plan.root_cause_location:
        rc_file = plan.root_cause_location.split("->")[0].split(" ")[0].strip()
        if (
            rc_file
            and (target_project / rc_file).exists()
            and rc_file not in files_to_track
        ):
            files_to_track.append(rc_file)
    if plan.failure_location:
        fl_file = plan.failure_location.split("::")[0].strip()
        if (
            fl_file
            and (target_project / fl_file).exists()
            and fl_file not in files_to_track
        ):
            files_to_track.append(fl_file)
    for sf in project_ctx.source_files:
        if sf not in files_to_track:
            files_to_track.append(sf)
    for tf in project_ctx.test_files:
        if tf not in files_to_track:
            files_to_track.append(tf)

    for f in files_to_track:
        if f not in request_ctx.relevant_files:
            request_ctx.relevant_files.append(f)

    tracker = TrackerAgent(config, target_project)
    tracker.snapshot_relevant_files(files_to_track)
    print_success(
        f"Baseline established for {len(files_to_track)} files ({', '.join(files_to_track)}). Tracking active modifications."
    )

    # 6. 👑 Master gives initial Socratic briefing
    master = MasterAgent(config)
    welcome_msg = master.generate_initial_guidance(request_ctx, plan)
    state_mgr.add_message("master", welcome_msg, "initial_briefing")
    print_master(welcome_msg)

    # 7. Interactive Game Loop
    hint_counter = 0
    console.print("\n" + "=" * 60)
    console.print("[bold yellow]🎮 DEBUGGING QUEST ACTIVE[/bold yellow]")
    console.print("Commands:")
    console.print(
        "  [bold cyan]hint[/bold cyan]            - Request next progressive hint from 👑 Master (Nudge ➔ Clue ➔ Direct Clue)"
    )
    console.print(
        "  [bold cyan]check[/bold cyan]           - 🎯 Tracker analyzes code changes & checks against diagnosed root cause"
    )
    console.print(
        "  [bold cyan]test <output>[/bold cyan]   - 🧪 Validate fix with local test runner results (e.g. 'test 3 passed' or 'pytest')"
    )
    console.print("  [bold cyan]plan[/bold cyan]            - Show current quest steps")
    console.print(
        "  [bold cyan]resources[/bold cyan]       - 📚 Show Librarian's curated reading list"
    )
    console.print("  [bold cyan]ask <msg>[/bold cyan]       - Ask 👑 Master a question")
    console.print("  [bold cyan]quit[/bold cyan]            - Finish quest")
    console.print("=" * 60)

    while True:
        try:
            user_input = prompt_input("Command or Question").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\nSession paused. Keep practicing!")
            break

        if not user_input:
            continue

        cmd = user_input.lower().strip()

        if cmd in ("exit", "quit", "q"):
            console.print(
                "\n[bold green]🎉 Great debugging session! Keep learning by doing.[/bold green]"
            )
            break

        elif cmd in ("help", "?"):
            console.print("  [bold]Available Commands:[/bold]")
            console.print(
                "  • [cyan]hint[/cyan]: Progressive hints (Level 1 Nudge -> Level 2 Clue -> Level 3 Direct Clue)"
            )
            console.print(
                "  • [cyan]check[/cyan]: Detects your edits in relevant files & checks against diagnosed root cause"
            )
            console.print(
                "  • [cyan]test <output>[/cyan] or [cyan]pytest[/cyan]: Validates bug fix with local test runner output"
            )
            console.print(
                "  • [cyan]plan[/cyan]: Review the debugging plan steps and diagnosed root cause"
            )
            console.print(
                "  • [cyan]resources[/cyan]: View documentation recommendations"
            )
            console.print(
                "  • [cyan]ask <text>[/cyan] or any question: Chat with 👑 Master"
            )
            console.print("  • [cyan]quit[/cyan]: Exit")

        elif cmd in ("plan", "p"):
            print_plan_overview(state_mgr.state.debugging_plan)

        elif cmd in ("resources", "docs", "r"):
            print_resources(state_mgr.state.resources)

        elif cmd in ("hint", "h"):
            current_step = (
                plan.steps[plan.current_step]
                if plan.current_step < len(plan.steps)
                else plan.steps[-1]
            )
            code_sample = ""
            if current_step.target_file and current_step.target_file in relevant_code:
                code_sample = relevant_code[current_step.target_file]
            elif (
                plan.root_cause_location
                and plan.root_cause_location.split(" ")[0] in relevant_code
            ):
                code_sample = relevant_code[plan.root_cause_location.split(" ")[0]]

            hint = master.get_progressive_hint(
                current_step,
                hint_counter,
                code_sample,
                plan=plan,
                request_context=request_ctx,
            )
            state_mgr.add_hint(hint)
            hint_counter += 1
            print_hint(hint.content, level=hint.level.value)

        elif cmd in ("check", "c"):
            print_agent_action(
                "Tracker",
                "🎯",
                "Scanning relevant files for developer changes...",
                "green",
            )
            changeset = tracker.track_changes(files_to_track)

            if not changeset.has_changes:
                print_warning(
                    "No changes detected in relevant files yet. Edit the file, save it, then run 'check'!"
                )
                continue

            print_changes(changeset.changes)
            if changeset.git_diff_raw:
                print_diff(changeset.git_diff_raw)

            # Update changed code
            changed_code = {}
            for f in changeset.files_changed:
                changed_code[f] = tracker.get_file_content(f)

            # 🧩 Solver & 👑 Master evaluate the change
            eval_result = solver.evaluate_changes(
                plan, changeset, request_ctx, changed_code
            )
            feedback = eval_result.get("feedback", "Changes analyzed!")
            print_master(f"🎯 **Tracker Report & Master Feedback**:\n\n{feedback}")

            # Transition validation states
            if eval_result.get("ready_for_test", False):
                state_mgr.set_validation_state(ValidationState.AWAITING_TEST_VALIDATION)
                state_mgr.set_phase(SessionPhase.AWAITING_TEST_VALIDATION)
                test_cmd = eval_result.get("test_command", "pytest")
                print_info(
                    f"State: [bold yellow]{ValidationState.AWAITING_TEST_VALIDATION.value}[/bold yellow]"
                )
                print_info(f"Run tests locally: [bold cyan]{test_cmd}[/bold cyan]")
                print_info(
                    "Paste test output: [bold cyan]test <output>[/bold cyan] or [bold cyan]pytest <output>[/bold cyan]"
                )
            elif eval_result.get("is_relevant", False):
                state_mgr.set_validation_state(ValidationState.CHANGE_RELEVANT)
                state_mgr.set_phase(SessionPhase.CHANGE_RELEVANT)
                print_info(
                    f"State: [bold yellow]{ValidationState.CHANGE_RELEVANT.value}[/bold yellow]"
                )
            else:
                state_mgr.set_validation_state(ValidationState.CHANGE_DETECTED)
                state_mgr.set_phase(SessionPhase.CHANGE_DETECTED)
                print_info(
                    f"State: [bold yellow]{ValidationState.CHANGE_DETECTED.value}[/bold yellow]"
                )

        elif (
            cmd == "test"
            or cmd == "pytest"
            or cmd.startswith("test ")
            or cmd.startswith("pytest ")
        ):
            # Extract test output
            if cmd in ("test", "pytest"):
                test_output_text = prompt_input(
                    "Paste test output (e.g. '3 passed' or full test output)"
                ).strip()
            elif cmd.startswith("test "):
                test_output_text = user_input[5:].strip()
            elif cmd.startswith("pytest "):
                test_output_text = user_input[7:].strip()
            else:
                test_output_text = ""

            if not test_output_text:
                print_warning(
                    "No test output provided. Run `pytest` locally and paste the output!"
                )
                continue

            print_agent_action(
                "Solver",
                "🧩",
                "Evaluating test results against diagnosed bug...",
                "magenta",
            )
            test_eval = solver.evaluate_test_output(test_output_text, plan, request_ctx)
            print_test_summary(test_eval["test_result"])

            if test_eval["passed"]:
                state_mgr.record_test_result(test_eval["test_result"], passed=True)
                advanced = state_mgr.advance_step()
                state_mgr.complete_quest()
                print_master(test_eval["feedback"])
                print_success(
                    f"State: [bold green]{ValidationState.TEST_PASSED.value}[/bold green] ➔ [bold green]{ValidationState.QUEST_COMPLETED.value}[/bold green]"
                )
                print_success("🏆 Quest Completed! Outstanding debugging!")
                hint_counter = 0
            else:
                state_mgr.record_test_result(test_eval["test_result"], passed=False)
                print_master(test_eval["feedback"])
                print_warning(
                    f"State: [bold red]{ValidationState.TEST_FAILED.value}[/bold red]"
                )
                print_warning(
                    "Bug not yet confirmed fixed. Check your implementation and run 'check' again."
                )

        else:
            # Question for Master
            q_text = user_input
            if q_text.lower().startswith("ask "):
                q_text = q_text[4:].strip()

            state_mgr.add_message("developer", q_text)
            current_code = ""
            target_f = (
                plan.root_cause_location.split(" ")[0]
                if plan.root_cause_location
                else (
                    request_ctx.relevant_files[0] if request_ctx.relevant_files else ""
                )
            )
            if target_f:
                current_code = tracker.get_file_content(target_f)

            answer = master.answer_developer_question(
                q_text, state_mgr.state, current_code
            )
            state_mgr.add_message("master", answer)
            print_master(answer)


if __name__ == "__main__":
    run_interactive_session()
