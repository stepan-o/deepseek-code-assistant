# src/assistant/core/reasoning_models.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union
from enum import Enum
from datetime import datetime
from pathlib import Path


class ImplementationStatus(Enum):
    """Status of implementation work."""
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    GENERATED = "generated"  # Code generated but not applied
    APPLIED = "applied"      # Code applied to files
    VALIDATED = "validated"  # Passed validation
    FAILED = "failed"
    BLOCKED = "blocked"


class RiskLevel(Enum):
    """Risk level for implementation tasks."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ArchitecturalComponent:
    """A component in the current architecture."""
    name: str
    purpose: str
    files: List[str]
    dependencies: List[str]
    patterns: List[str]
    interfaces: Dict[str, Any]  # API contracts, etc.


@dataclass
class CurrentStateAnalysis:
    """Analysis of current architectural state from snapshot."""
    snapshot_dir: str
    timestamp: datetime
    overview: str
    components: Dict[str, ArchitecturalComponent]  # name -> component
    patterns: List[str]
    tech_stack: List[str]
    strengths: List[str]
    weaknesses: List[str]
    gaps_for_assistant: List[str]  # What assistant needs but doesn't have
    risks: List[Dict[str, Any]]


@dataclass
class SolutionVision:
    """High-level solution vision aligned with architecture."""
    id: str
    requirements: str
    architectural_approach: str
    chosen_approach_reasoning: str
    rejected_approaches: List[Dict[str, str]]  # approach + why rejected
    acceptance_criteria: List[str]
    architectural_constraints: List[str]
    success_metrics: Dict[str, Any]
    risks_mitigated: List[str]
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class ImplementationStrategy:
    """Strategy for implementing the vision."""
    vision_id: str
    affected_components: List[str]
    new_components: List[str]  # Components to be created
    modified_components: List[str]  # Components to be modified
    interfaces_to_change: List[Dict[str, Any]]
    execution_sequence: List[str]  # Order of component implementation
    dependencies: Dict[str, List[str]]  # component -> dependencies
    rollback_plan: str  # How to undo if things go wrong


@dataclass
class WorkChunk:
    """A concrete, executable unit of work."""
    id: str
    description: str
    component: str  # Which architectural component this affects
    files_affected: List[str]
    requirements: str  # Detailed requirements for code generation
    acceptance_criteria: List[str]
    validation_method: str  # "test", "manual_review", "architecture_check"
    dependencies: List[str]  # Other chunk IDs this depends on
    risks: List[Dict[str, Any]]
    estimated_complexity: str  # "simple", "moderate", "complex"
    status: ImplementationStatus = ImplementationStatus.PLANNED
    generated_code: Optional[str] = None
    applied_changes: Optional[Dict[str, Any]] = None  # What was actually applied
    validation_results: Optional[Dict[str, Any]] = None
    feedback: List[Dict[str, Any]] = field(default_factory=list)  # User/auto feedback


@dataclass
class ImplementationSession:
    """Tracks an entire implementation session."""
    session_id: str
    vision: SolutionVision
    strategy: ImplementationStrategy
    work_chunks: Dict[str, WorkChunk]  # chunk_id -> WorkChunk
    current_state: CurrentStateAnalysis
    iteration: int = 1
    status: str = "planning"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    user_feedback_history: List[Dict[str, Any]] = field(default_factory=list)
    decisions_log: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ValidationReport:
    """Report from validating implementation against vision."""
    vision_id: str
    criteria_met: List[str]
    criteria_failed: List[Dict[str, str]]  # criterion + reason
    architectural_integrity: Dict[str, Any]  # Integrity checks
    new_risks_introduced: List[Dict[str, Any]]
    recommendations: List[str]
    overall_status: str  # "passed", "failed", "partial"
    chunk_id: Optional[str] = None  # If validating specific chunk


@dataclass
class IterationPlan:
    """Plan for next iteration based on feedback."""
    session_id: str
    iteration: int
    issues_to_address: List[Dict[str, Any]]
    chunks_to_redo: List[str]
    chunks_to_modify: List[Dict[str, Any]]  # chunk_id + modifications
    new_chunks_needed: List[Dict[str, Any]]
    approach_adjustments: List[str]
    estimated_effort: str  # "minor", "moderate", "significant"