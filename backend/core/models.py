"""
Core data models for Debug2Learn.

These Pydantic models define the structured data contracts between agents.
All inter-agent communication uses these models rather than raw text.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Language(str, Enum):
    """Supported programming languages."""

    PYTHON = "python"
    UNKNOWN = "unknown"


class ChangeType(str, Enum):
    """Types of file/symbol changes detected by the Checker."""

    FILE_ADDED = "file_added"
    FILE_DELETED = "file_deleted"
    FILE_RENAMED = "file_renamed"
    FILE_MODIFIED = "file_modified"
    FUNCTION_ADDED = "function_added"
    FUNCTION_DELETED = "function_deleted"
    FUNCTION_MODIFIED = "function_modified"
    CLASS_ADDED = "class_added"
    CLASS_DELETED = "class_deleted"
    CLASS_MODIFIED = "class_modified"
    IMPORT_ADDED = "import_added"
    IMPORT_REMOVED = "import_removed"
    CONFIG_CHANGED = "config_changed"
    TEST_CHANGED = "test_changed"


class HintLevel(str, Enum):
    """Progressive hint levels from vague to very specific."""

    CONCEPTUAL = "conceptual"
    DIRECTIONAL = "directional"
    SPECIFIC = "specific"
    VERY_SPECIFIC = "very_specific"


class TestStatus(str, Enum):
    """Test execution result status."""

    __test__ = False
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


class ValidationState(str, Enum):
    """States in the fix-validation workflow."""

    NONE = "NONE"
    CHANGE_DETECTED = "CHANGE_DETECTED"
    CHANGE_RELEVANT = "CHANGE_RELEVANT"
    AWAITING_TEST_VALIDATION = "AWAITING_TEST_VALIDATION"
    TEST_FAILED = "TEST_FAILED"
    TEST_PASSED = "TEST_PASSED"
    QUEST_COMPLETED = "QUEST_COMPLETED"


class SessionPhase(str, Enum):
    """Current phase of the debugging session."""

    UNINITIALIZED = "uninitialized"
    PROJECT_ANALYZED = "project_analyzed"
    PROBLEM_DESCRIBED = "problem_described"
    PLAN_CREATED = "plan_created"
    TEACHING = "teaching"
    AWAITING_CHANGES = "awaiting_changes"
    CHANGE_DETECTED = "change_detected"
    CHANGE_RELEVANT = "change_relevant"
    AWAITING_TEST_VALIDATION = "awaiting_test_validation"
    TEST_FAILED = "test_failed"
    TEST_PASSED = "test_passed"
    QUEST_COMPLETED = "quest_completed"
    EVALUATING_CHANGES = "evaluating_changes"
    TESTING = "testing"
    COMPLETED = "completed"


class FunctionInfo(BaseModel):
    """Information about a function/method in the project."""

    name: str
    file_path: str
    line_start: int = 0
    line_end: int = 0
    parameters: list[str] = Field(default_factory=list)
    decorators: list[str] = Field(default_factory=list)
    docstring: str = ""
    is_method: bool = False
    class_name: str | None = None
    body_hash: str = ""


class ClassInfo(BaseModel):
    """Information about a class in the project."""

    name: str
    file_path: str
    line_start: int = 0
    line_end: int = 0
    bases: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    docstring: str = ""


class ImportInfo(BaseModel):
    """Information about an import statement."""

    module: str
    names: list[str] = Field(default_factory=list)
    is_from_import: bool = False
    alias: str | None = None


class FileContext(BaseModel):
    """Analyzed context for a single file."""

    path: str
    relative_path: str
    language: Language = Language.PYTHON
    size_bytes: int = 0
    purpose: str = ""
    functions: list[FunctionInfo] = Field(default_factory=list)
    classes: list[ClassInfo] = Field(default_factory=list)
    imports: list[ImportInfo] = Field(default_factory=list)
    is_test_file: bool = False
    is_entry_point: bool = False


class ProjectContext(BaseModel):
    """
    Complete project understanding — the persistent knowledge base.

    Built by the Project Analyzer during init, incrementally updated
    by the Checker after developer changes.
    """

    project_path: str
    project_name: str = ""
    language: Language = Language.PYTHON
    description: str = ""

    # Structure
    files: dict[str, FileContext] = Field(default_factory=dict)
    entry_points: list[str] = Field(default_factory=list)
    test_files: list[str] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)
    test_to_source_mapping: dict[str, str] = Field(default_factory=dict)
    function_to_file: dict[str, str] = Field(default_factory=dict)

    # Dependencies
    dependencies: list[str] = Field(default_factory=list)
    framework: str = ""

    # Architecture summary (AI-generated)
    architecture_summary: str = ""
    component_relationships: list[str] = Field(default_factory=list)

    # Metadata
    total_files: int = 0
    total_functions: int = 0
    total_classes: int = 0
    analyzed_at: datetime = Field(default_factory=datetime.now)
    last_updated: datetime = Field(default_factory=datetime.now)

    # Git info
    git_initialized: bool = False
    current_branch: str = ""
    last_commit_hash: str = ""


class Change(BaseModel):
    """A single detected change in the project."""

    file_path: str
    change_type: ChangeType
    symbol: str = ""
    old_code: str = ""
    new_code: str = ""
    diff: str = ""
    line_start: int = 0
    line_end: int = 0
    description: str = ""


class ChangeSet(BaseModel):
    """Collection of all changes detected since last check."""

    changes: list[Change] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    detected_at: datetime = Field(default_factory=datetime.now)
    git_diff_raw: str = ""

    @property
    def has_changes(self) -> bool:
        return len(self.changes) > 0

    @property
    def summary(self) -> str:
        """Short summary of changes."""
        if not self.changes:
            return "No changes detected."
        parts = []
        for change in self.changes:
            parts.append(
                f"  {change.change_type.value}: {change.symbol or change.file_path}"
            )
        return "\n".join(parts)


class RequestContext(BaseModel):
    """Structured representation of the developer's debugging request."""

    raw_input: str
    intent: str = ""
    symptom: str = ""
    target_function: str = ""
    expected_value: str = ""
    actual_value: str = ""
    failure_location: str = ""
    root_cause_file: str = ""
    expected_behavior: str = ""
    observed_behavior: str = ""
    domain: str = ""
    possible_components: list[str] = Field(default_factory=list)
    relevant_files: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    error_messages: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class DebuggingStep(BaseModel):
    """A single step in the debugging plan."""

    step_number: int
    title: str
    description: str
    target_file: str = ""
    target_symbol: str = ""
    concept: str = ""
    expected_observation: str = ""
    completed: bool = False
    developer_answer: str = ""


class DebuggingPlan(BaseModel):
    """Complete debugging plan created by the Solver."""

    hypothesis: str
    confidence: float = 0.0  # 0.0-1.0
    evidence: list[str] = Field(default_factory=list)
    bug_location: str = ""
    failure_location: str = ""
    root_cause_location: str = ""
    relevant_logic: str = ""
    concept: str = ""
    steps: list[DebuggingStep] = Field(default_factory=list)
    current_step: int = 0
    relevant_code_snippets: dict[str, str] = Field(default_factory=dict)
    test_command: str = "pytest"

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def is_complete(self) -> bool:
        return self.current_step >= self.total_steps


class Hint(BaseModel):
    """A progressive hint for the developer."""

    level: HintLevel
    content: str
    step_number: int
    concept: str = ""


class LearningResource(BaseModel):
    """A learning resource recommended by the Resource Agent."""

    title: str
    url: str = ""
    resource_type: str = ""
    relevance: str = ""
    concept: str = ""


class SingleTestResult(BaseModel):
    """Result of a single test case."""

    name: str
    status: TestStatus
    duration_ms: float = 0.0
    error_message: str = ""
    stack_trace: str = ""


class TestRunResult(BaseModel):
    """Complete test run results."""

    __test__ = False
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_ms: float = 0.0
    test_results: list[SingleTestResult] = Field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    timed_out: bool = False

    @property
    def all_passed(self) -> bool:
        return self.failed == 0 and self.errors == 0 and self.total > 0


class TeacherMessage(BaseModel):
    """A message in the Teacher conversation."""

    role: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    message_type: str = "text"


class LearningProgress(BaseModel):
    """Tracks what the developer has learned during the session."""

    concepts_introduced: list[str] = Field(default_factory=list)
    concepts_understood: list[str] = Field(default_factory=list)
    questions_asked: int = 0
    questions_correct: int = 0
    hints_used: int = 0
    max_hint_level: HintLevel = HintLevel.CONCEPTUAL
    changes_made: int = 0
    tests_run: int = 0


class SessionState(BaseModel):
    """
    Complete state of a debugging session.

    This is the central state object persisted to disk and shared
    between all CLI commands within a session.
    """

    session_id: str = ""
    phase: SessionPhase = SessionPhase.UNINITIALIZED
    started_at: datetime = Field(default_factory=datetime.now)
    last_activity: datetime = Field(default_factory=datetime.now)

    # Core data
    project_context: ProjectContext | None = None
    request_context: RequestContext | None = None
    debugging_plan: DebuggingPlan | None = None

    # Change tracking
    change_history: list[ChangeSet] = Field(default_factory=list)
    last_known_commit: str = ""

    # Teaching
    conversation: list[TeacherMessage] = Field(default_factory=list)
    hints_given: list[Hint] = Field(default_factory=list)
    current_hint_level: HintLevel = HintLevel.CONCEPTUAL

    # Resources
    resources: list[LearningResource] = Field(default_factory=list)

    # Test results & validation
    test_history: list[TestRunResult] = Field(default_factory=list)
    latest_test_result: TestRunResult | None = None
    validation_state: ValidationState = ValidationState.NONE

    # Learning
    progress: LearningProgress = Field(default_factory=LearningProgress)

    def add_teacher_message(self, content: str, message_type: str = "text"):
        """Add a teacher message to the conversation."""
        self.conversation.append(
            TeacherMessage(
                role="teacher",
                content=content,
                message_type=message_type,
            )
        )
        self.last_activity = datetime.now()

    def add_developer_message(self, content: str):
        """Add a developer message to the conversation."""
        self.conversation.append(
            TeacherMessage(
                role="developer",
                content=content,
            )
        )
        self.last_activity = datetime.now()
