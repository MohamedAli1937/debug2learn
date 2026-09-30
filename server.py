from __future__ import annotations

import sys
import traceback
from pathlib import Path

# Ensure debug2learn is importable
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.agents.decoder import DecoderAgent
from backend.agents.explorer import ExplorerAgent
from backend.agents.librarian import LibrarianAgent
from backend.agents.master import MasterAgent
from backend.agents.solver import SolverAgent
from backend.agents.tracker import TrackerAgent
from backend.config.settings import load_config
from backend.core.models import SessionPhase, ValidationState
from backend.core.state import StateManager
from backend.repository import RepositoryError, acquire_repository

# ── App Setup ────────────────────────────────────────────────
app = FastAPI(title="Debugging Jungle", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://mohamedali1937.github.io",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-Memory Session State ─────────────────────────────────
# Single-user MVP: one active session at a time
_session: dict = {
    "active": False,
    "config": None,
    "state_mgr": None,
    "decoder": None,
    "explorer": None,
    "solver": None,
    "tracker": None,
    "librarian": None,
    "master": None,
    "request_ctx": None,
    "project_ctx": None,
    "plan": None,
    "relevant_code": {},
    "files_to_track": [],
    "hint_counter": 0,
    "target_project": None,
    "temp_repo": None,
}


def _reset_session():
    """Reset the global session state."""
    temp_repo = _session.get("temp_repo")
    if temp_repo:
        temp_repo.cleanup()
    _session.update(
        {
            "active": False,
            "config": None,
            "state_mgr": None,
            "decoder": None,
            "explorer": None,
            "solver": None,
            "tracker": None,
            "librarian": None,
            "master": None,
            "request_ctx": None,
            "project_ctx": None,
            "plan": None,
            "relevant_code": {},
            "files_to_track": [],
            "hint_counter": 0,
            "target_project": None,
            "temp_repo": None,
        }
    )


def _require_session():
    """Raise if no active session."""
    if not _session["active"]:
        raise HTTPException(
            status_code=400, detail="No active debugging session. Start one first."
        )


# ── Request / Response Models ────────────────────────────────


class StartRequest(BaseModel):
    project_url: str | None = None
    bug_report: str | None = None
    project_path: str | None = None
    bug_description: str | None = None


class AskRequest(BaseModel):
    question: str


class TestRequest(BaseModel):
    test_output: str


class AgentMessage(BaseModel):
    agent: str
    emoji: str
    animal: str
    message: str
    message_type: str = "info"  # info, success, warning, error, hint, master, plan


# ── Serve Frontend ───────────────────────────────────────────

FRONTEND_DIR = PROJECT_ROOT / "frontend"


@app.get("/")
async def serve_frontend():
    """Serve the main frontend page."""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "Debugging Jungle API is running. Frontend not found."}


# Mount static assets if they exist
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

ASSETS_DIR = PROJECT_ROOT / "assets"
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


# ── API Endpoints ────────────────────────────────────────────


@app.post("/api/start")
async def start_session(req: StartRequest):
    """
    Start a new debugging session.
    Runs the full pipeline: Decoder → Explorer → Solver → Librarian → Tracker → Master.
    Returns the sequence of agent messages for the frontend to animate.
    """
    _reset_session()
    messages: list[dict] = []

    try:
        if req.project_url:
            temp_repo, target_project = acquire_repository(req.project_url)
            _session["temp_repo"] = temp_repo
            config = load_config()
            config.project_path = target_project
        elif req.project_path:
            target_project = Path(req.project_path).resolve()
            if not target_project.exists():
                raise HTTPException(
                    status_code=400, detail=f"Directory not found: {target_project}"
                )
            config = load_config(target_project)
        else:
            raise HTTPException(
                status_code=400, detail="A public GitHub project_url is required."
            )

        state_mgr = StateManager()
        _session["config"] = config
        _session["state_mgr"] = state_mgr
        _session["target_project"] = target_project

        bug_input = (req.bug_report or req.bug_description or "").strip()
        if not bug_input:
            bug_input = 'count_pending returns 1 instead of 2. It should count tasks that are NOT marked as completed with "[x]".'

        # 1. 🦎 Decoder (Chameleon)
        messages.append(
            {
                "agent": "Decoder",
                "emoji": "🔐",
                "animal": "🦎",
                "message": "Analyzing bug report and extracting signals...",
                "message_type": "action",
            }
        )
        decoder = DecoderAgent(config)
        request_ctx = decoder.decode(bug_input)
        state_mgr.set_request_context(request_ctx)
        _session["decoder"] = decoder
        _session["request_ctx"] = request_ctx

        symptom_msg = f"**Detected issue:** {request_ctx.symptom}"
        if request_ctx.target_function:
            symptom_msg += f"\n**Target function:** `{request_ctx.target_function}`"
        if request_ctx.expected_value and request_ctx.actual_value:
            symptom_msg += f"\n**Expected:** {request_ctx.expected_value} | **Observed:** {request_ctx.actual_value}"

        messages.append(
            {
                "agent": "Decoder",
                "emoji": "🔐",
                "animal": "🦎",
                "message": symptom_msg,
                "message_type": "success",
            }
        )

        # 2. 🦜 Explorer (Toucan)
        messages.append(
            {
                "agent": "Explorer",
                "emoji": "🧭",
                "animal": "🦜",
                "message": f"Exploring files in `{target_project.name}`...",
                "message_type": "action",
            }
        )
        explorer = ExplorerAgent(config)
        project_ctx = explorer.explore(
            target_project, relevant_files_hint=request_ctx.relevant_files
        )
        if not project_ctx.source_files and not project_ctx.test_files:
            raise RepositoryError(
                "Repository contains no supported source or test files."
            )
        state_mgr.set_project_context(project_ctx)
        _session["explorer"] = explorer
        _session["project_ctx"] = project_ctx

        # Resolve relationships
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

        # Collect relevant code
        relevant_code: dict[str, str] = {}
        for rel_path in request_ctx.relevant_files:
            full_p = target_project / rel_path
            if full_p.exists() and full_p.is_file():
                relevant_code[rel_path] = full_p.read_text(
                    encoding="utf-8", errors="replace"
                )

        if not relevant_code and project_ctx.files:
            for sk in list(project_ctx.files.keys())[:3]:
                full_p = target_project / sk
                if full_p.exists() and full_p.is_file():
                    relevant_code[sk] = full_p.read_text(
                        encoding="utf-8", errors="replace"
                    )
                    request_ctx.relevant_files.append(sk)

        _session["relevant_code"] = relevant_code

        explorer_msg = f"Mapped **{project_ctx.total_files} files** ({len(project_ctx.source_files)} source, {len(project_ctx.test_files)} tests)."
        if request_ctx.failure_location:
            explorer_msg += f"\n**Failure detection:** `{request_ctx.failure_location}`"
        if request_ctx.root_cause_file:
            explorer_msg += f"\n**Suspected source:** `{request_ctx.root_cause_file}`"

        messages.append(
            {
                "agent": "Explorer",
                "emoji": "🧭",
                "animal": "🦜",
                "message": explorer_msg,
                "message_type": "success",
            }
        )

        # 3. 🦉 Solver (Owl)
        messages.append(
            {
                "agent": "Solver",
                "emoji": "🧩",
                "animal": "🦉",
                "message": "Synthesizing hypothesis, isolating root cause & designing pedagogical plan...",
                "message_type": "action",
            }
        )
        solver = SolverAgent(config)
        plan = solver.create_plan(project_ctx, request_ctx, relevant_code)
        state_mgr.set_debugging_plan(plan)
        _session["solver"] = solver
        _session["plan"] = plan

        plan_msg = f"**Hypothesis:** {plan.hypothesis}\n"
        plan_msg += f"**Root Cause:** `{plan.root_cause_location}`\n"
        if plan.failure_location:
            plan_msg += f"**Failure Detected By:** `{plan.failure_location}`\n"
        plan_msg += f"**Concept:** {plan.concept}\n"
        plan_msg += f"**Confidence:** {int(plan.confidence * 100)}%\n"
        plan_msg += f"**Quest Steps:** {len(plan.steps)}"

        messages.append(
            {
                "agent": "Solver",
                "emoji": "🧩",
                "animal": "🦉",
                "message": plan_msg,
                "message_type": "plan",
            }
        )

        # 4. 🐘 Librarian (Elephant)
        messages.append(
            {
                "agent": "Librarian",
                "emoji": "📚",
                "animal": "🐘",
                "message": "Curating concept resources and documentation...",
                "message_type": "action",
            }
        )
        librarian = LibrarianAgent(config)
        resources = librarian.find_resources(request_ctx, plan)
        state_mgr.add_resources(resources)
        _session["librarian"] = librarian

        resource_titles = [r.title for r in resources[:3]]
        messages.append(
            {
                "agent": "Librarian",
                "emoji": "📚",
                "animal": "🐘",
                "message": f"Found **{len(resources)} resources** for you:\n"
                + "\n".join(f"- {t}" for t in resource_titles),
                "message_type": "success",
            }
        )

        # 5. 🐆 Tracker (Panther)
        messages.append(
            {
                "agent": "Tracker",
                "emoji": "🎯",
                "animal": "🐆",
                "message": "Taking baseline snapshots of relevant source and test files...",
                "message_type": "action",
            }
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
        _session["tracker"] = tracker
        _session["files_to_track"] = files_to_track

        messages.append(
            {
                "agent": "Tracker",
                "emoji": "🎯",
                "animal": "🐆",
                "message": f"Baseline established for **{len(files_to_track)} files** ({', '.join(files_to_track)}). Tracking active modifications.",
                "message_type": "success",
            }
        )

        # 6. 🦁 Master (Lion)
        master = MasterAgent(config)
        welcome_msg = master.generate_initial_guidance(request_ctx, plan)
        if welcome_msg.startswith(
            "Groq is unavailable because its API quota has been reached"
        ):
            _reset_session()
            return {
                "success": False,
                "messages": [
                    {
                        "agent": "System",
                        "emoji": "⚠️",
                        "animal": "",
                        "message": welcome_msg,
                        "message_type": "error",
                    }
                ],
                "quest_steps": [],
                "session_phase": "uninitialized",
                "validation_state": "NONE",
            }
        state_mgr.add_message("master", welcome_msg, "initial_briefing")
        _session["master"] = master

        messages.append(
            {
                "agent": "Master",
                "emoji": "👑",
                "animal": "🦁",
                "message": welcome_msg,
                "message_type": "master",
            }
        )

        _session["active"] = True

        # Build quest steps for frontend
        quest_steps = []
        for step in plan.steps:
            quest_steps.append(
                {
                    "step_number": step.step_number,
                    "title": step.title,
                    "description": step.description,
                    "target_file": step.target_file,
                    "target_symbol": step.target_symbol,
                    "concept": step.concept,
                    "expected_observation": step.expected_observation,
                    "completed": step.completed,
                }
            )

        return {
            "success": True,
            "messages": messages,
            "quest_steps": quest_steps,
            "session_phase": state_mgr.phase.value,
            "validation_state": state_mgr.validation_state.value,
        }

    except RepositoryError as exc:
        _reset_session()
        return {
            "success": False,
            "error": "Unable to access the GitHub repository.",
            "detail": str(exc),
            "messages": [
                {
                    "agent": "System",
                    "emoji": "⚠️",
                    "animal": "",
                    "message": f"**Repository error:** {exc}",
                    "message_type": "error",
                }
            ],
            "quest_steps": [],
            "session_phase": "uninitialized",
            "validation_state": "NONE",
        }
    except HTTPException:
        _reset_session()
        raise
    except Exception as e:
        _reset_session()
        return {
            "success": False,
            "messages": [
                {
                    "agent": "System",
                    "emoji": "❌",
                    "animal": "",
                    "message": f"Failed to start session: {e!s}\n\n```\n{traceback.format_exc()}\n```",
                    "message_type": "error",
                }
            ],
            "quest_steps": [],
            "session_phase": "uninitialized",
            "validation_state": "NONE",
        }


@app.post("/api/hint")
async def get_hint():
    """Get the next progressive hint from the Master (Lion)."""
    state_mgr = _session["state_mgr"]
    if state_mgr.validation_state in (
        ValidationState.QUEST_COMPLETED,
        ValidationState.TEST_PASSED,
    ) or state_mgr.phase in (
        SessionPhase.QUEST_COMPLETED,
        SessionPhase.TEST_PASSED,
        SessionPhase.COMPLETED,
    ):
        return {
            "agent": "Master",
            "emoji": "👑",
            "animal": "🦁",
            "message": "🏆 Quest is already completed! Use **🔄 New Quest** above to start a new quest.",
            "message_type": "quest_complete",
            "hint_level": "Completed",
            "hint_count": _session["hint_counter"],
        }

    plan = _session["plan"]
    master = _session["master"]
    request_ctx = _session["request_ctx"]
    relevant_code = _session["relevant_code"]

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
        _session["hint_counter"],
        code_sample,
        plan=plan,
        request_context=request_ctx,
    )
    _session["state_mgr"].add_hint(hint)
    _session["hint_counter"] += 1

    level_labels = {
        "conceptual": "Level 1: Nudge",
        "directional": "Level 2: Clue",
        "specific": "Level 3: Direct Clue",
        "very_specific": "Level 3: Direct Clue",
    }

    return {
        "agent": "Master",
        "emoji": "👑",
        "animal": "🦁",
        "message": hint.content,
        "message_type": "hint",
        "hint_level": level_labels.get(hint.level.value, "Hint"),
        "hint_count": _session["hint_counter"],
    }


@app.post("/api/check")
async def check_changes():
    """Tracker detects changes, Solver evaluates them."""
    _require_session()
    tracker = _session["tracker"]
    solver = _session["solver"]
    plan = _session["plan"]
    request_ctx = _session["request_ctx"]
    state_mgr = _session["state_mgr"]
    files_to_track = _session["files_to_track"]

    messages = []

    messages.append(
        {
            "agent": "Tracker",
            "emoji": "🎯",
            "animal": "🐆",
            "message": "Scanning relevant files for developer changes...",
            "message_type": "action",
        }
    )

    changeset = tracker.track_changes(files_to_track)

    if not changeset.has_changes:
        messages.append(
            {
                "agent": "Tracker",
                "emoji": "🎯",
                "animal": "🐆",
                "message": "No changes detected in relevant files yet. Edit the file, save it, then run check!",
                "message_type": "warning",
            }
        )
        return {
            "messages": messages,
            "has_changes": False,
            "validation_state": state_mgr.validation_state.value,
        }

    # Show changes
    change_summary = "\n".join(
        f"- `{c.file_path}`: {c.change_type.value} ({c.symbol or c.description})"
        for c in changeset.changes
    )
    messages.append(
        {
            "agent": "Tracker",
            "emoji": "🎯",
            "animal": "🐆",
            "message": f"**Changes detected:**\n{change_summary}",
            "message_type": "success",
        }
    )

    if changeset.git_diff_raw:
        messages.append(
            {
                "agent": "Tracker",
                "emoji": "🎯",
                "animal": "🐆",
                "message": f"```diff\n{changeset.git_diff_raw[:2000]}\n```",
                "message_type": "diff",
            }
        )

    # Get changed code
    changed_code = {}
    for f in changeset.files_changed:
        changed_code[f] = tracker.get_file_content(f)

    # Solver + Master evaluate
    eval_result = solver.evaluate_changes(plan, changeset, request_ctx, changed_code)
    feedback = eval_result.get("feedback", "Changes analyzed!")

    messages.append(
        {
            "agent": "Master",
            "emoji": "👑",
            "animal": "🦁",
            "message": feedback,
            "message_type": "master",
        }
    )

    # Update state
    if eval_result.get("ready_for_test", False):
        state_mgr.set_validation_state(ValidationState.AWAITING_TEST_VALIDATION)
        state_mgr.set_phase(SessionPhase.AWAITING_TEST_VALIDATION)
        test_cmd = eval_result.get("test_command", "pytest")
        messages.append(
            {
                "agent": "Solver",
                "emoji": "🧩",
                "animal": "🦉",
                "message": f"**State:** Awaiting Test Validation\n\nRun tests locally: `{test_cmd}`\nThen paste the output using the test command.",
                "message_type": "info",
            }
        )
    elif eval_result.get("is_relevant", False):
        state_mgr.set_validation_state(ValidationState.CHANGE_RELEVANT)
        state_mgr.set_phase(SessionPhase.CHANGE_RELEVANT)
    else:
        state_mgr.set_validation_state(ValidationState.CHANGE_DETECTED)
        state_mgr.set_phase(SessionPhase.CHANGE_DETECTED)

    return {
        "messages": messages,
        "has_changes": True,
        "validation_state": state_mgr.validation_state.value,
        "ready_for_test": eval_result.get("ready_for_test", False),
    }


@app.post("/api/test")
async def validate_test(req: TestRequest):
    """Validate test output provided by the developer."""
    _require_session()
    solver = _session["solver"]
    plan = _session["plan"]
    request_ctx = _session["request_ctx"]
    state_mgr = _session["state_mgr"]

    messages = []

    test_output_text = req.test_output.strip()
    if not test_output_text:
        return {
            "messages": [
                {
                    "agent": "Solver",
                    "emoji": "🧩",
                    "animal": "🦉",
                    "message": "No test output provided. Run `pytest` locally and paste the output!",
                    "message_type": "warning",
                }
            ],
            "passed": False,
            "validation_state": state_mgr.validation_state.value,
        }

    messages.append(
        {
            "agent": "Solver",
            "emoji": "🧩",
            "animal": "🦉",
            "message": "Evaluating test results against diagnosed bug...",
            "message_type": "action",
        }
    )

    test_eval = solver.evaluate_test_output(test_output_text, plan, request_ctx)
    test_result = test_eval["test_result"]

    # Test summary
    if test_eval["passed"]:
        state_mgr.record_test_result(test_result, passed=True)
        state_mgr.advance_step()
        state_mgr.complete_quest()
        if _session.get("temp_repo"):
            _session["temp_repo"].cleanup()
            _session["temp_repo"] = None

        messages.append(
            {
                "agent": "Master",
                "emoji": "👑",
                "animal": "🦁",
                "message": (
                    "🎉 Excellent! Your tests passed.\n\n"
                    "You identified the root cause, fixed the code yourself,\n"
                    "and proved that your solution works.\n\n"
                    "+100 XP\n"
                    "🏆 Quest Complete!"
                ),
                "message_type": "master",
            }
        )
        messages.append(
            {
                "agent": "System",
                "emoji": "🏆",
                "animal": "🌴",
                "message": (
                    "🎉 **QUEST COMPLETE**\n\n"
                    "- Root cause identified ✓\n"
                    "- Relevant fix detected ✓\n"
                    "- Tests passed ✓\n\n"
                    "**+100 XP**"
                ),
                "message_type": "quest_complete",
            }
        )
    else:
        state_mgr.record_test_result(test_result, passed=False)
        messages.append(
            {
                "agent": "Master",
                "emoji": "👑",
                "animal": "🦁",
                "message": test_eval["feedback"],
                "message_type": "master",
            }
        )
        messages.append(
            {
                "agent": "Solver",
                "emoji": "🧩",
                "animal": "🦉",
                "message": f"Bug not yet confirmed fixed. ({test_result.failed} failed, {test_result.passed} passed). Check your implementation and run `check` again.",
                "message_type": "warning",
            }
        )

    dur_sec = test_result.duration_ms / 1000.0 if test_result.duration_ms > 0 else 0.01
    duration_str = f"{dur_sec:.2f}s"

    return {
        "messages": messages,
        "passed": test_eval["passed"],
        "validation_state": state_mgr.validation_state.value,
        "test_summary": {
            "total": test_result.total,
            "passed": test_result.passed,
            "failed": test_result.failed,
            "errors": test_result.errors,
            "skipped": test_result.skipped,
            "duration": duration_str,
            "raw_output": test_output_text,
        },
    }


@app.post("/api/ask")
async def ask_question(req: AskRequest):
    """Ask the Master a question."""
    _require_session()
    master = _session["master"]
    plan = _session["plan"]
    request_ctx = _session["request_ctx"]
    state_mgr = _session["state_mgr"]
    tracker = _session["tracker"]

    # If quest is already completed, do not re-ask debugging questions
    if state_mgr.validation_state in (
        ValidationState.QUEST_COMPLETED,
        ValidationState.TEST_PASSED,
    ) or state_mgr.phase in (
        SessionPhase.QUEST_COMPLETED,
        SessionPhase.TEST_PASSED,
        SessionPhase.COMPLETED,
    ):
        return {
            "agent": "Master",
            "emoji": "👑",
            "animal": "🦁",
            "message": (
                "🎉 Excellent! Your tests passed.\n\n"
                "You identified the root cause, fixed the code yourself,\n"
                "and proved that your solution works.\n\n"
                "+100 XP\n"
                "🏆 Quest Complete!"
            ),
            "message_type": "quest_complete",
            "completed": True,
        }

    q_text = req.question.strip()
    if not q_text:
        return {
            "agent": "Master",
            "emoji": "👑",
            "animal": "🦁",
            "message": "Please ask a question!",
            "message_type": "warning",
        }

    state_mgr.add_message("developer", q_text)

    current_code = ""
    target_f = (
        plan.root_cause_location.split(" ")[0]
        if plan.root_cause_location
        else (request_ctx.relevant_files[0] if request_ctx.relevant_files else "")
    )
    if target_f:
        current_code = tracker.get_file_content(target_f)

    answer = master.answer_developer_question(q_text, state_mgr.state, current_code)
    state_mgr.add_message("master", answer)

    return {
        "agent": "Master",
        "emoji": "👑",
        "animal": "🦁",
        "message": answer,
        "message_type": "master",
    }


@app.get("/api/plan")
async def get_plan():
    """Get the current debugging plan."""
    _require_session()
    plan = _session["plan"]

    steps = []
    for step in plan.steps:
        steps.append(
            {
                "step_number": step.step_number,
                "title": step.title,
                "description": step.description,
                "target_file": step.target_file,
                "target_symbol": step.target_symbol,
                "concept": step.concept,
                "expected_observation": step.expected_observation,
                "completed": step.completed,
            }
        )

    return {
        "hypothesis": plan.hypothesis,
        "confidence": plan.confidence,
        "root_cause_location": plan.root_cause_location,
        "failure_location": plan.failure_location,
        "relevant_logic": plan.relevant_logic,
        "concept": plan.concept,
        "steps": steps,
        "current_step": plan.current_step,
    }


@app.get("/api/resources")
async def get_resources():
    """Get learning resources from the Librarian."""
    _require_session()
    state_mgr = _session["state_mgr"]

    resources = []
    for r in state_mgr.state.resources:
        resources.append(
            {
                "title": r.title,
                "url": r.url,
                "resource_type": r.resource_type,
                "relevance": r.relevance,
                "concept": r.concept,
            }
        )

    return {"resources": resources}


@app.get("/api/status")
async def get_status():
    """Get the current session status."""
    if not _session["active"]:
        return {
            "active": False,
            "session_phase": "uninitialized",
            "validation_state": "NONE",
        }

    state_mgr = _session["state_mgr"]
    return {
        "active": True,
        "session_phase": state_mgr.phase.value,
        "validation_state": state_mgr.validation_state.value,
        "hint_count": _session["hint_counter"],
    }


# ── Run with uvicorn ─────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
