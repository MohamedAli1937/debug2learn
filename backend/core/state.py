"""
In-memory State Manager for Debug2Learn MVP.

Maintains the active debugging session state in memory.
No database or complex persistence required.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from backend.core.models import (
    DebuggingPlan,
    Hint,
    LearningResource,
    ProjectContext,
    RequestContext,
    SessionPhase,
    SessionState,
    TeacherMessage,
    TestRunResult,
    ValidationState,
)


class StateManager:
    """
    Lightweight in-memory session state manager.
    """

    def __init__(self, session_id: str | None = None):
        self.state = SessionState(
            session_id=session_id or str(uuid.uuid4())[:8],
            phase=SessionPhase.UNINITIALIZED,
            started_at=datetime.now(),
            last_activity=datetime.now(),
        )

    @property
    def session_id(self) -> str:
        return self.state.session_id

    @property
    def phase(self) -> SessionPhase:
        return self.state.phase

    @property
    def validation_state(self) -> ValidationState:
        return self.state.validation_state

    def set_phase(self, phase: SessionPhase) -> None:
        self.state.phase = phase
        self.state.last_activity = datetime.now()

    def set_validation_state(self, val_state: ValidationState) -> None:
        self.state.validation_state = val_state
        self.state.last_activity = datetime.now()

    def record_test_result(self, result: TestRunResult, passed: bool) -> None:
        """Record test validation results and update session phase and validation state."""
        self.state.latest_test_result = result
        self.state.test_history.append(result)
        self.state.progress.tests_run += 1
        self.state.last_activity = datetime.now()
        if passed:
            self.set_validation_state(ValidationState.TEST_PASSED)
            self.set_phase(SessionPhase.TEST_PASSED)
        else:
            self.set_validation_state(ValidationState.TEST_FAILED)
            self.set_phase(SessionPhase.TEST_FAILED)

    def complete_quest(self) -> None:
        """Mark quest as fully completed after test validation."""
        self.set_validation_state(ValidationState.QUEST_COMPLETED)
        self.set_phase(SessionPhase.QUEST_COMPLETED)

    def set_project_context(self, context: ProjectContext) -> None:
        self.state.project_context = context
        self.set_phase(SessionPhase.PROJECT_ANALYZED)

    def set_request_context(self, context: RequestContext) -> None:
        self.state.request_context = context
        self.set_phase(SessionPhase.PROBLEM_DESCRIBED)

    def set_debugging_plan(self, plan: DebuggingPlan) -> None:
        self.state.debugging_plan = plan
        self.set_phase(SessionPhase.PLAN_CREATED)

    def add_hint(self, hint: Hint) -> None:
        self.state.hints_given.append(hint)
        self.state.progress.hints_used += 1
        self.state.current_hint_level = hint.level
        self.state.last_activity = datetime.now()

    def add_resources(self, resources: list[LearningResource]) -> None:
        self.state.resources.extend(resources)
        self.state.last_activity = datetime.now()

    def add_message(
        self, role: str, content: str, message_type: str = "text"
    ) -> TeacherMessage:
        msg = TeacherMessage(
            role=role,
            content=content,
            message_type=message_type,
            timestamp=datetime.now(),
        )
        self.state.conversation.append(msg)
        self.state.last_activity = datetime.now()
        return msg

    def advance_step(self) -> bool:
        """Advance to the next step in the debugging plan."""
        plan = self.state.debugging_plan
        if not plan:
            return False

        if plan.current_step < len(plan.steps):
            plan.steps[plan.current_step].completed = True
            plan.current_step += 1
            if plan.is_complete:
                self.set_phase(SessionPhase.COMPLETED)
            return True
        return False

    def reset(self) -> None:
        """Reset state to a fresh session."""
        self.state = SessionState(
            session_id=str(uuid.uuid4())[:8],
            phase=SessionPhase.UNINITIALIZED,
            started_at=datetime.now(),
            last_activity=datetime.now(),
        )
