"""
Tests for in-memory StateManager.
"""

import pytest

from debug2learn.core.models import (
    DebuggingPlan,
    DebuggingStep,
    Hint,
    HintLevel,
    LearningResource,
    RequestContext,
    SessionPhase,
)
from debug2learn.core.state import StateManager


def test_state_manager_init():
    sm = StateManager()
    assert sm.phase == SessionPhase.UNINITIALIZED
    assert sm.session_id is not None
    assert len(sm.session_id) > 0


def test_state_manager_advance_steps():
    sm = StateManager()
    plan = DebuggingPlan(
        hypothesis="Bug in math logic",
        steps=[
            DebuggingStep(step_number=1, title="Step 1", description="Inspect"),
            DebuggingStep(step_number=2, title="Step 2", description="Fix"),
        ],
    )
    sm.set_debugging_plan(plan)
    assert sm.phase == SessionPhase.PLAN_CREATED
    assert plan.current_step == 0

    assert sm.advance_step() is True
    assert plan.current_step == 1
    assert plan.steps[0].completed is True

    assert sm.advance_step() is True
    assert plan.current_step == 2
    assert sm.phase == SessionPhase.COMPLETED

    # Advancing when complete returns False
    assert sm.advance_step() is False


def test_state_manager_hints_and_messages():
    sm = StateManager()
    hint = Hint(
        level=HintLevel.CONCEPTUAL,
        content="Consider zero division",
        step_number=1,
    )
    sm.add_hint(hint)
    assert len(sm.state.hints_given) == 1
    assert sm.state.progress.hints_used == 1
    assert sm.state.current_hint_level == HintLevel.CONCEPTUAL

    msg = sm.add_message("master", "Think about inputs", "question")
    assert msg.role == "master"
    assert len(sm.state.conversation) == 1
