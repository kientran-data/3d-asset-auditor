"""Phase 4 domain models, enums, and data containers."""
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


class AssessmentDecision(Enum):
    """Orchestration-level decision for an asset."""
    SKIP = "SKIP"
    NEEDS_ASSESSMENT = "NEEDS_ASSESSMENT"
    BLOCKED = "BLOCKED"


class AssessmentPipelineStatus(Enum):
    """Pipeline status stored on assets.assessment_status."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    STALE = "STALE"


class ReadinessStatus(Enum):
    """Business readiness result stored on asset_assessments.readiness_status."""
    READY = "READY"
    READY_WITH_WARNINGS = "READY_WITH_WARNINGS"
    NEEDS_FIX = "NEEDS_FIX"
    NOT_SELLABLE = "NOT_SELLABLE"


class Severity(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKER = "BLOCKER"


class Disposition(Enum):
    NONE = "NONE"
    NEEDS_FIX = "NEEDS_FIX"
    NOT_SELLABLE = "NOT_SELLABLE"


class EvaluationOutcome(Enum):
    """Result of a single rule evaluator."""
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PASS = "PASS"
    TRIGGERED = "TRIGGERED"


class RunStatus(Enum):
    """Status for assessment_runs batch orchestration."""
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    FAILED = "FAILED"


class ExecutionStatus(Enum):
    """Status for individual assessment_run_items."""
    NOT_RUN = "NOT_RUN"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    INPUT_CHANGED = "INPUT_CHANGED"


@dataclass
class Lineage:
    """Frozen upstream dependency snapshot for an asset."""
    asset_id: str
    source_fingerprint: str
    source_file_size_bytes: int
    source_modified_time_ns: int
    basic_analysis_run_id: Optional[str]
    deep_analysis_run_id: Optional[str]
    preview_id: Optional[str]
    render_run_id: Optional[str] = None


@dataclass
class RuleEvaluation:
    """Result returned by an individual rule evaluator.

    Evaluators return factual observations only.
    Severity and disposition come from the ruleset config.
    """
    outcome: EvaluationOutcome
    observed_value: Optional[Dict[str, Any]] = None
    expected_value: Optional[Dict[str, Any]] = None
    message_context: Optional[str] = None
    subject_type: Optional[str] = None
    subject_key: Optional[str] = None


@dataclass
class StagedIssue:
    """An issue staged in memory before persistence."""
    rule_code: str
    severity: str
    disposition: str
    category: str
    message: str
    observed_value: Optional[Dict[str, Any]] = None
    expected_value: Optional[Dict[str, Any]] = None
    subject_type: Optional[str] = None
    subject_key: Optional[str] = None


@dataclass
class AssessmentResult:
    """Complete result of assessing one asset."""
    readiness_status: str
    issues: List[StagedIssue] = field(default_factory=list)
    rule_outcomes: Dict[str, str] = field(default_factory=dict)
