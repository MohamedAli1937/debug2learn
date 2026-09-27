"""
Tests for core data models.

Validates Pydantic model serialization, defaults, and computed properties.
"""

import json
from datetime import datetime

import pytest

from debug2learn.core.models import (
    Change,
    ChangeSet,
    ChangeType,
    DebuggingPlan,
    DebuggingStep,
    FileContext,
    FunctionInfo,
    HintLevel,
    Language,
    ProjectContext,
    RequestContext,
    SessionPhase,
    SessionState,
    TestRunResult,
    TestStatus,
)


class TestProjectContext:
    """Tests for ProjectContext model."""

    def test_create_empty(self):
        ctx = ProjectContext(project_path="/tmp/test")
        assert ctx.project_path == "/tmp/test"
        assert ctx.total_files == 0
        assert ctx.language == Language.PYTHON

    def test_serialization(self):
        ctx = ProjectContext(
            project_path="/tmp/test",
            project_name="test-project",
            total_files=5,
            total_functions=10,
        )
        json_str = ctx.model_dump_json()
        loaded = ProjectContext.model_validate_json(json_str)
        assert loaded.project_name == "test-project"
        assert loaded.total_files == 5


class TestChangeSet:
    """Tests for ChangeSet model."""

    def test_empty_changeset(self):
        cs = ChangeSet()
        assert cs.has_changes is False
        assert cs.summary == "No changes detected."

    def test_with_changes(self):
        cs = ChangeSet(changes=[
            Change(
                file_path="auth.py",
                change_type=ChangeType.FUNCTION_ADDED,
                symbol="validate_token",
            )
        ])
        assert cs.has_changes is True
        assert "function_added" in cs.summary
        assert "validate_token" in cs.summary


class TestDebuggingPlan:
    """Tests for DebuggingPlan model."""

    def test_empty_plan(self):
        plan = DebuggingPlan(hypothesis="test")
        assert plan.total_steps == 0
        assert plan.is_complete is True  # No steps = complete

    def test_with_steps(self):
        plan = DebuggingPlan(
            hypothesis="bug in auth",
            steps=[
                DebuggingStep(step_number=1, title="Step 1", description="Do this"),
                DebuggingStep(step_number=2, title="Step 2", description="Do that"),
            ],
        )
        assert plan.total_steps == 2
        assert plan.is_complete is False

    def test_advancement(self):
        plan = DebuggingPlan(
            hypothesis="bug",
            steps=[DebuggingStep(step_number=1, title="Step 1", description="Do")],
            current_step=0,
        )
        assert not plan.is_complete
        plan.current_step = 1
        assert plan.is_complete


class TestSessionState:
    """Tests for SessionState model."""

    def test_create_default(self):
        state = SessionState()
        assert state.phase == SessionPhase.UNINITIALIZED
        assert len(state.conversation) == 0

    def test_add_messages(self):
        state = SessionState()
        state.add_teacher_message("Hello!", "text")
        state.add_developer_message("Hi")

        assert len(state.conversation) == 2
        assert state.conversation[0].role == "teacher"
        assert state.conversation[1].role == "developer"

    def test_serialization_roundtrip(self):
        state = SessionState(session_id="test-123")
        state.add_teacher_message("Question?", "question")

        json_str = state.model_dump_json()
        loaded = SessionState.model_validate_json(json_str)

        assert loaded.session_id == "test-123"
        assert len(loaded.conversation) == 1


class TestTestRunResult:
    """Tests for TestRunResult model."""

    def test_all_passed(self):
        result = TestRunResult(total=5, passed=5, failed=0, errors=0)
        assert result.all_passed is True

    def test_not_all_passed(self):
        result = TestRunResult(total=5, passed=4, failed=1, errors=0)
        assert result.all_passed is False

    def test_no_tests(self):
        result = TestRunResult(total=0)
        assert result.all_passed is False


class TestRequestContext:
    """Tests for RequestContext model."""

    def test_create(self):
        ctx = RequestContext(
            raw_input="My login fails",
            intent="debug_auth",
            symptom="401 error",
        )
        assert ctx.raw_input == "My login fails"
        assert ctx.intent == "debug_auth"
