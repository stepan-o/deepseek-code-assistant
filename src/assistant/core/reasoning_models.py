# src/assistant/core/reasoning_models.py
"""
Data models for Architectural Reasoning Engine.

All sync - no async needed for data structures. These are the foundational
data models that represent the state, plans, and results of architectural
reasoning sessions.

Designed for JSON serialization with to_dict()/from_dict() methods.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union, Set
from enum import Enum
from datetime import datetime
from pathlib import Path
import json
import uuid


# ============================================================================
# ENUMS
# ============================================================================

class ImplementationStatus(str, Enum):
    """Status of implementation work."""
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    GENERATED = "generated"  # Code generated but not applied
    APPLIED = "applied"      # Code applied to files
    VALIDATED = "validated"  # Passed validation
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class RiskLevel(str, Enum):
    """Risk level for implementation tasks."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ValidationLevel(str, Enum):
    """Level of validation performed."""
    BASIC = "basic"       # Syntax/schema validation
    STRUCTURAL = "structural"  # Architecture/pattern validation
    COMPREHENSIVE = "comprehensive"  # Full LLM-assisted validation


class ComponentType(str, Enum):
    """Type of architectural component."""
    MODULE = "module"
    SERVICE = "service"
    LIBRARY = "library"
    DATABASE = "database"
    API = "api"
    UI = "ui"
    UTILITY = "utility"
    TEST = "test"
    CONFIG = "config"
    UNKNOWN = "unknown"


class LearningCategory(str, Enum):
    """Category of learning point."""
    ARCHITECTURE = "architecture"
    CODE_PATTERN = "code_pattern"
    VALIDATION = "validation"
    CONSTRAINT = "constraint"
    BEST_PRACTICE = "best_practice"
    MISTAKE = "mistake"
    SUCCESS = "success"


# ============================================================================
# CORE DATA MODELS
# ============================================================================

@dataclass
class CodeLocation:
    """Represents a specific location in code."""
    file_path: str
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    column_start: Optional[int] = None
    column_end: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'file_path': self.file_path,
            'line_start': self.line_start,
            'line_end': self.line_end,
            'column_start': self.column_start,
            'column_end': self.column_end
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CodeLocation':
        """Create from dictionary."""
        return cls(
            file_path=data['file_path'],
            line_start=data.get('line_start'),
            line_end=data.get('line_end'),
            column_start=data.get('column_start'),
            column_end=data.get('column_end')
        )


@dataclass
class InterfaceDefinition:
    """Definition of a component interface (API contract)."""
    name: str
    description: str
    methods: List[Dict[str, Any]]
    inputs: List[Dict[str, Any]]
    outputs: List[Dict[str, Any]]
    errors: List[Dict[str, Any]]
    examples: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'name': self.name,
            'description': self.description,
            'methods': self.methods,
            'inputs': self.inputs,
            'outputs': self.outputs,
            'errors': self.errors,
            'examples': self.examples
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'InterfaceDefinition':
        """Create from dictionary."""
        return cls(
            name=data['name'],
            description=data['description'],
            methods=data['methods'],
            inputs=data['inputs'],
            outputs=data['outputs'],
            errors=data['errors'],
            examples=data.get('examples', [])
        )


@dataclass
class ArchitecturalComponent:
    """A component in the current architecture."""
    name: str
    type: ComponentType
    purpose: str
    description: str = ""
    files: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    patterns: List[str] = field(default_factory=list)
    interfaces: Dict[str, InterfaceDefinition] = field(default_factory=dict)
    key_functions: List[str] = field(default_factory=list)
    complexity_score: float = 0.0  # 0-1 scale
    stability_score: float = 0.0   # 0-1 scale
    test_coverage: Optional[float] = None  # 0-100 percentage
    documentation_status: str = "unknown"  # "none", "partial", "complete"
    ownership: Optional[str] = None
    created_at: Optional[datetime] = None
    last_modified: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'name': self.name,
            'type': self.type.value,
            'purpose': self.purpose,
            'description': self.description,
            'files': self.files,
            'dependencies': self.dependencies,
            'patterns': self.patterns,
            'interfaces': {k: v.to_dict() for k, v in self.interfaces.items()},
            'key_functions': self.key_functions,
            'complexity_score': self.complexity_score,
            'stability_score': self.stability_score,
            'test_coverage': self.test_coverage,
            'documentation_status': self.documentation_status,
            'ownership': self.ownership,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_modified': self.last_modified.isoformat() if self.last_modified else None
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ArchitecturalComponent':
        """Create from dictionary."""
        interfaces = {}
        if 'interfaces' in data and isinstance(data['interfaces'], dict):
            interfaces = {
                k: InterfaceDefinition.from_dict(v)
                for k, v in data['interfaces'].items()
            }

        return cls(
            name=data['name'],
            type=ComponentType(data.get('type', 'unknown')),
            purpose=data['purpose'],
            description=data.get('description', ''),
            files=data.get('files', []),
            dependencies=data.get('dependencies', []),
            patterns=data.get('patterns', []),
            interfaces=interfaces,
            key_functions=data.get('key_functions', []),
            complexity_score=data.get('complexity_score', 0.0),
            stability_score=data.get('stability_score', 0.0),
            test_coverage=data.get('test_coverage'),
            documentation_status=data.get('documentation_status', 'unknown'),
            ownership=data.get('ownership'),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else None,
            last_modified=datetime.fromisoformat(data['last_modified']) if data.get('last_modified') else None
        )


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
    key_decisions: List[Dict[str, Any]] = field(default_factory=list)
    architectural_guiding_principles: List[str] = field(default_factory=list)
    known_constraints: List[Dict[str, Any]] = field(default_factory=list)
    analysis_confidence: float = 1.0  # 0-1 scale
    data_source: str = "snapshot_artifacts"
    component_count: int = field(init=False)
    file_count: int = 0
    total_lines_of_code: int = 0

    def __post_init__(self):
        self.component_count = len(self.components)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'snapshot_dir': self.snapshot_dir,
            'timestamp': self.timestamp.isoformat(),
            'overview': self.overview,
            'components': {k: v.to_dict() for k, v in self.components.items()},
            'patterns': self.patterns,
            'tech_stack': self.tech_stack,
            'strengths': self.strengths,
            'weaknesses': self.weaknesses,
            'gaps_for_assistant': self.gaps_for_assistant,
            'risks': self.risks,
            'key_decisions': self.key_decisions,
            'architectural_guiding_principles': self.architectural_guiding_principles,
            'known_constraints': self.known_constraints,
            'analysis_confidence': self.analysis_confidence,
            'data_source': self.data_source,
            'component_count': self.component_count,
            'file_count': self.file_count,
            'total_lines_of_code': self.total_lines_of_code
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CurrentStateAnalysis':
        """Create from dictionary."""
        components = {}
        if 'components' in data and isinstance(data['components'], dict):
            components = {
                k: ArchitecturalComponent.from_dict(v)
                for k, v in data['components'].items()
            }

        return cls(
            snapshot_dir=data['snapshot_dir'],
            timestamp=datetime.fromisoformat(data['timestamp']),
            overview=data['overview'],
            components=components,
            patterns=data.get('patterns', []),
            tech_stack=data.get('tech_stack', []),
            strengths=data.get('strengths', []),
            weaknesses=data.get('weaknesses', []),
            gaps_for_assistant=data.get('gaps_for_assistant', []),
            risks=data.get('risks', []),
            key_decisions=data.get('key_decisions', []),
            architectural_guiding_principles=data.get('architectural_guiding_principles', []),
            known_constraints=data.get('known_constraints', []),
            analysis_confidence=data.get('analysis_confidence', 1.0),
            data_source=data.get('data_source', 'snapshot_artifacts'),
            file_count=data.get('file_count', 0),
            total_lines_of_code=data.get('total_lines_of_code', 0)
        )


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
    user_feedback: Optional[str] = None
    assumptions: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    dependencies_on_external_factors: List[str] = field(default_factory=list)
    priority: str = "medium"  # low, medium, high, critical
    estimated_effort: str = "unknown"  # small, medium, large, x-large
    confidence_score: float = 0.8  # 0-1 scale

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'id': self.id,
            'requirements': self.requirements,
            'architectural_approach': self.architectural_approach,
            'chosen_approach_reasoning': self.chosen_approach_reasoning,
            'rejected_approaches': self.rejected_approaches,
            'acceptance_criteria': self.acceptance_criteria,
            'architectural_constraints': self.architectural_constraints,
            'success_metrics': self.success_metrics,
            'risks_mitigated': self.risks_mitigated,
            'created_at': self.created_at.isoformat(),
            'user_feedback': self.user_feedback,
            'assumptions': self.assumptions,
            'open_questions': self.open_questions,
            'dependencies_on_external_factors': self.dependencies_on_external_factors,
            'priority': self.priority,
            'estimated_effort': self.estimated_effort,
            'confidence_score': self.confidence_score
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SolutionVision':
        """Create from dictionary."""
        return cls(
            id=data['id'],
            requirements=data['requirements'],
            architectural_approach=data['architectural_approach'],
            chosen_approach_reasoning=data['chosen_approach_reasoning'],
            rejected_approaches=data.get('rejected_approaches', []),
            acceptance_criteria=data.get('acceptance_criteria', []),
            architectural_constraints=data.get('architectural_constraints', []),
            success_metrics=data.get('success_metrics', {}),
            risks_mitigated=data.get('risks_mitigated', []),
            created_at=datetime.fromisoformat(data['created_at']),
            user_feedback=data.get('user_feedback'),
            assumptions=data.get('assumptions', []),
            open_questions=data.get('open_questions', []),
            dependencies_on_external_factors=data.get('dependencies_on_external_factors', []),
            priority=data.get('priority', 'medium'),
            estimated_effort=data.get('estimated_effort', 'unknown'),
            confidence_score=data.get('confidence_score', 0.8)
        )


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
    created_at: datetime = field(default_factory=datetime.now)
    estimated_timeline: Optional[str] = None
    phase_breakdown: List[Dict[str, Any]] = field(default_factory=list)
    milestones: List[Dict[str, Any]] = field(default_factory=list)
    validation_checkpoints: List[Dict[str, Any]] = field(default_factory=list)
    risk_mitigation_strategies: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'vision_id': self.vision_id,
            'affected_components': self.affected_components,
            'new_components': self.new_components,
            'modified_components': self.modified_components,
            'interfaces_to_change': self.interfaces_to_change,
            'execution_sequence': self.execution_sequence,
            'dependencies': self.dependencies,
            'rollback_plan': self.rollback_plan,
            'created_at': self.created_at.isoformat(),
            'estimated_timeline': self.estimated_timeline,
            'phase_breakdown': self.phase_breakdown,
            'milestones': self.milestones,
            'validation_checkpoints': self.validation_checkpoints,
            'risk_mitigation_strategies': self.risk_mitigation_strategies
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ImplementationStrategy':
        """Create from dictionary."""
        return cls(
            vision_id=data['vision_id'],
            affected_components=data['affected_components'],
            new_components=data['new_components'],
            modified_components=data['modified_components'],
            interfaces_to_change=data['interfaces_to_change'],
            execution_sequence=data['execution_sequence'],
            dependencies=data['dependencies'],
            rollback_plan=data['rollback_plan'],
            created_at=datetime.fromisoformat(data['created_at']),
            estimated_timeline=data.get('estimated_timeline'),
            phase_breakdown=data.get('phase_breakdown', []),
            milestones=data.get('milestones', []),
            validation_checkpoints=data.get('validation_checkpoints', []),
            risk_mitigation_strategies=data.get('risk_mitigation_strategies', [])
        )


@dataclass
class CodeChange:
    """Represents a specific code change."""
    id: str
    description: str
    change_type: str  # "add", "modify", "delete", "refactor"
    file_path: str
    old_content: Optional[str] = None
    new_content: Optional[str] = None
    diff: Optional[str] = None
    location: Optional[CodeLocation] = None
    reason: Optional[str] = None
    generated_by: str = "assistant"
    validation_status: str = "pending"
    applied: bool = False
    applied_at: Optional[datetime] = None
    rollback_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'id': self.id,
            'description': self.description,
            'change_type': self.change_type,
            'file_path': self.file_path,
            'old_content': self.old_content,
            'new_content': self.new_content,
            'diff': self.diff,
            'location': self.location.to_dict() if self.location else None,
            'reason': self.reason,
            'generated_by': self.generated_by,
            'validation_status': self.validation_status,
            'applied': self.applied,
            'applied_at': self.applied_at.isoformat() if self.applied_at else None,
            'rollback_path': self.rollback_path
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CodeChange':
        """Create from dictionary."""
        location = None
        if data.get('location'):
            location = CodeLocation.from_dict(data['location'])

        return cls(
            id=data['id'],
            description=data['description'],
            change_type=data['change_type'],
            file_path=data['file_path'],
            old_content=data.get('old_content'),
            new_content=data.get('new_content'),
            diff=data.get('diff'),
            location=location,
            reason=data.get('reason'),
            generated_by=data.get('generated_by', 'assistant'),
            validation_status=data.get('validation_status', 'pending'),
            applied=data.get('applied', False),
            applied_at=datetime.fromisoformat(data['applied_at']) if data.get('applied_at') else None,
            rollback_path=data.get('rollback_path')
        )


@dataclass
class WorkChunk:
    """A concrete, executable unit of work."""
    id: str
    description: str
    component: str  # Which architectural component this affects
    files_affected: List[str]
    requirements: str  # Detailed requirements for code generation
    acceptance_criteria: List[str]
    validation_method: str  # "test", "manual_review", "architecture_check", "llm_review"
    dependencies: List[str]  # Other chunk IDs this depends on
    risks: List[Dict[str, Any]]
    estimated_complexity: str  # "simple", "moderate", "complex"
    status: ImplementationStatus = ImplementationStatus.PLANNED
    generated_code: Optional[str] = None
    applied_changes: List[CodeChange] = field(default_factory=list)
    validation_results: Optional[Dict[str, Any]] = None
    feedback: List[Dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    estimated_duration_minutes: Optional[int] = None
    actual_duration_minutes: Optional[int] = None
    assigned_to: Optional[str] = None  # Could be "assistant", "user", specific tool
    retry_count: int = 0
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'id': self.id,
            'description': self.description,
            'component': self.component,
            'files_affected': self.files_affected,
            'requirements': self.requirements,
            'acceptance_criteria': self.acceptance_criteria,
            'validation_method': self.validation_method,
            'dependencies': self.dependencies,
            'risks': self.risks,
            'estimated_complexity': self.estimated_complexity,
            'status': self.status.value,
            'generated_code': self.generated_code,
            'applied_changes': [c.to_dict() for c in self.applied_changes],
            'validation_results': self.validation_results,
            'feedback': self.feedback,
            'created_at': self.created_at.isoformat(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'estimated_duration_minutes': self.estimated_duration_minutes,
            'actual_duration_minutes': self.actual_duration_minutes,
            'assigned_to': self.assigned_to,
            'retry_count': self.retry_count,
            'error_message': self.error_message
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WorkChunk':
        """Create from dictionary."""
        applied_changes = []
        if 'applied_changes' in data and isinstance(data['applied_changes'], list):
            applied_changes = [
                CodeChange.from_dict(c) for c in data['applied_changes']
            ]

        return cls(
            id=data['id'],
            description=data['description'],
            component=data['component'],
            files_affected=data['files_affected'],
            requirements=data['requirements'],
            acceptance_criteria=data['acceptance_criteria'],
            validation_method=data['validation_method'],
            dependencies=data['dependencies'],
            risks=data['risks'],
            estimated_complexity=data['estimated_complexity'],
            status=ImplementationStatus(data.get('status', 'planned')),
            generated_code=data.get('generated_code'),
            applied_changes=applied_changes,
            validation_results=data.get('validation_results'),
            feedback=data.get('feedback', []),
            created_at=datetime.fromisoformat(data['created_at']),
            started_at=datetime.fromisoformat(data['started_at']) if data.get('started_at') else None,
            completed_at=datetime.fromisoformat(data['completed_at']) if data.get('completed_at') else None,
            estimated_duration_minutes=data.get('estimated_duration_minutes'),
            actual_duration_minutes=data.get('actual_duration_minutes'),
            assigned_to=data.get('assigned_to'),
            retry_count=data.get('retry_count', 0),
            error_message=data.get('error_message')
        )


@dataclass
class ImplementationSession:
    """Tracks an entire implementation session."""
    session_id: str
    vision: SolutionVision
    strategy: ImplementationStrategy
    work_chunks: Dict[str, WorkChunk]  # chunk_id -> WorkChunk
    current_state: CurrentStateAnalysis
    iteration: int = 1
    status: str = "planning"  # planning, vision_created, executing, validating, completed, failed
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    user_feedback_history: List[Dict[str, Any]] = field(default_factory=list)
    decisions_log: List[Dict[str, Any]] = field(default_factory=list)
    validation_history: List[Dict[str, Any]] = field(default_factory=list)
    applied_learnings: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    parent_session_id: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    priority: str = "normal"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'session_id': self.session_id,
            'vision': self.vision.to_dict(),
            'strategy': self.strategy.to_dict(),
            'work_chunks': {k: v.to_dict() for k, v in self.work_chunks.items()},
            'current_state': self.current_state.to_dict(),
            'iteration': self.iteration,
            'status': self.status,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'user_feedback_history': self.user_feedback_history,
            'decisions_log': self.decisions_log,
            'validation_history': self.validation_history,
            'applied_learnings': self.applied_learnings,
            'metadata': self.metadata,
            'parent_session_id': self.parent_session_id,
            'tags': self.tags,
            'priority': self.priority
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ImplementationSession':
        """Create from dictionary."""
        work_chunks = {}
        if 'work_chunks' in data and isinstance(data['work_chunks'], dict):
            work_chunks = {
                k: WorkChunk.from_dict(v)
                for k, v in data['work_chunks'].items()
            }

        return cls(
            session_id=data['session_id'],
            vision=SolutionVision.from_dict(data['vision']),
            strategy=ImplementationStrategy.from_dict(data['strategy']),
            work_chunks=work_chunks,
            current_state=CurrentStateAnalysis.from_dict(data['current_state']),
            iteration=data.get('iteration', 1),
            status=data.get('status', 'planning'),
            created_at=datetime.fromisoformat(data['created_at']),
            updated_at=datetime.fromisoformat(data['updated_at']),
            user_feedback_history=data.get('user_feedback_history', []),
            decisions_log=data.get('decisions_log', []),
            validation_history=data.get('validation_history', []),
            applied_learnings=data.get('applied_learnings', []),
            metadata=data.get('metadata', {}),
            parent_session_id=data.get('parent_session_id'),
            tags=data.get('tags', []),
            priority=data.get('priority', 'normal')
        )


@dataclass
class ValidationResult:
    """Result of validating code against criteria."""
    validation_id: str
    work_chunk_id: Optional[str] = None
    session_id: Optional[str] = None
    validation_level: ValidationLevel = ValidationLevel.BASIC
    criteria_checked: List[str] = field(default_factory=list)
    passed_criteria: List[str] = field(default_factory=list)
    failed_criteria: List[Dict[str, Any]] = field(default_factory=list)  # criterion + reason
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    issues_found: List[Dict[str, Any]] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    architectural_integrity_check: Dict[str, Any] = field(default_factory=dict)
    new_risks_identified: List[Dict[str, Any]] = field(default_factory=list)
    overall_status: str = "pending"  # passed, failed, partial, warning
    confidence_score: float = 0.0  # 0-1 scale
    validation_time_seconds: Optional[float] = None
    validator_used: str = "focused_validator"
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'validation_id': self.validation_id,
            'work_chunk_id': self.work_chunk_id,
            'session_id': self.session_id,
            'validation_level': self.validation_level.value,
            'criteria_checked': self.criteria_checked,
            'passed_criteria': self.passed_criteria,
            'failed_criteria': self.failed_criteria,
            'warnings': self.warnings,
            'issues_found': self.issues_found,
            'suggestions': self.suggestions,
            'architectural_integrity_check': self.architectural_integrity_check,
            'new_risks_identified': self.new_risks_identified,
            'overall_status': self.overall_status,
            'confidence_score': self.confidence_score,
            'validation_time_seconds': self.validation_time_seconds,
            'validator_used': self.validator_used,
            'created_at': self.created_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ValidationResult':
        """Create from dictionary."""
        return cls(
            validation_id=data['validation_id'],
            work_chunk_id=data.get('work_chunk_id'),
            session_id=data.get('session_id'),
            validation_level=ValidationLevel(data.get('validation_level', 'basic')),
            criteria_checked=data.get('criteria_checked', []),
            passed_criteria=data.get('passed_criteria', []),
            failed_criteria=data.get('failed_criteria', []),
            warnings=data.get('warnings', []),
            issues_found=data.get('issues_found', []),
            suggestions=data.get('suggestions', []),
            architectural_integrity_check=data.get('architectural_integrity_check', {}),
            new_risks_identified=data.get('new_risks_identified', []),
            overall_status=data.get('overall_status', 'pending'),
            confidence_score=data.get('confidence_score', 0.0),
            validation_time_seconds=data.get('validation_time_seconds'),
            validator_used=data.get('validator_used', 'focused_validator'),
            created_at=datetime.fromisoformat(data['created_at'])
        )


@dataclass
class LearningPoint:
    """A captured learning from implementation sessions."""
    id: str
    category: LearningCategory
    title: str
    description: str
    source_session_id: str
    source_chunk_id: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    pattern_recognized: Optional[str] = None
    constraint_discovered: Optional[str] = None
    best_practice_identified: Optional[str] = None
    mistake_to_avoid: Optional[str] = None
    success_to_repeat: Optional[str] = None
    application_conditions: List[str] = field(default_factory=list)
    confidence_score: float = 0.8  # 0-1 scale
    times_applied: int = 0
    times_successful: int = 0
    relevance_keywords: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_applied: Optional[datetime] = None
    tags: List[str] = field(default_factory=list)
    archived: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'id': self.id,
            'category': self.category.value,
            'title': self.title,
            'description': self.description,
            'source_session_id': self.source_session_id,
            'source_chunk_id': self.source_chunk_id,
            'context': self.context,
            'pattern_recognized': self.pattern_recognized,
            'constraint_discovered': self.constraint_discovered,
            'best_practice_identified': self.best_practice_identified,
            'mistake_to_avoid': self.mistake_to_avoid,
            'success_to_repeat': self.success_to_repeat,
            'application_conditions': self.application_conditions,
            'confidence_score': self.confidence_score,
            'times_applied': self.times_applied,
            'times_successful': self.times_successful,
            'relevance_keywords': self.relevance_keywords,
            'created_at': self.created_at.isoformat(),
            'last_applied': self.last_applied.isoformat() if self.last_applied else None,
            'tags': self.tags,
            'archived': self.archived
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LearningPoint':
        """Create from dictionary."""
        return cls(
            id=data['id'],
            category=LearningCategory(data['category']),
            title=data['title'],
            description=data['description'],
            source_session_id=data['source_session_id'],
            source_chunk_id=data.get('source_chunk_id'),
            context=data.get('context', {}),
            pattern_recognized=data.get('pattern_recognized'),
            constraint_discovered=data.get('constraint_discovered'),
            best_practice_identified=data.get('best_practice_identified'),
            mistake_to_avoid=data.get('mistake_to_avoid'),
            success_to_repeat=data.get('success_to_repeat'),
            application_conditions=data.get('application_conditions', []),
            confidence_score=data.get('confidence_score', 0.8),
            times_applied=data.get('times_applied', 0),
            times_successful=data.get('times_successful', 0),
            relevance_keywords=data.get('relevance_keywords', []),
            created_at=datetime.fromisoformat(data['created_at']),
            last_applied=datetime.fromisoformat(data['last_applied']) if data.get('last_applied') else None,
            tags=data.get('tags', []),
            archived=data.get('archived', False)
        )


@dataclass
class IterationPlan:
    """Plan for next iteration based on feedback."""
    session_id: str
    iteration: int
    issues_to_address: List[Dict[str, Any]]
    chunks_to_redo: List[str]  # chunk IDs
    chunks_to_modify: List[Dict[str, Any]]  # chunk_id + modifications
    new_chunks_needed: List[Dict[str, Any]]
    approach_adjustments: List[str]
    estimated_effort: str  # "minor", "moderate", "significant"
    learnings_applied: List[Dict[str, Any]] = field(default_factory=list)
    root_cause_analysis: Optional[str] = None
    prevention_strategies: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'session_id': self.session_id,
            'iteration': self.iteration,
            'issues_to_address': self.issues_to_address,
            'chunks_to_redo': self.chunks_to_redo,
            'chunks_to_modify': self.chunks_to_modify,
            'new_chunks_needed': self.new_chunks_needed,
            'approach_adjustments': self.approach_adjustments,
            'estimated_effort': self.estimated_effort,
            'learnings_applied': self.learnings_applied,
            'root_cause_analysis': self.root_cause_analysis,
            'prevention_strategies': self.prevention_strategies,
            'created_at': self.created_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IterationPlan':
        """Create from dictionary."""
        return cls(
            session_id=data['session_id'],
            iteration=data['iteration'],
            issues_to_address=data['issues_to_address'],
            chunks_to_redo=data['chunks_to_redo'],
            chunks_to_modify=data['chunks_to_modify'],
            new_chunks_needed=data['new_chunks_needed'],
            approach_adjustments=data['approach_adjustments'],
            estimated_effort=data['estimated_effort'],
            learnings_applied=data.get('learnings_applied', []),
            root_cause_analysis=data.get('root_cause_analysis'),
            prevention_strategies=data.get('prevention_strategies', []),
            created_at=datetime.fromisoformat(data['created_at'])
        )


# ============================================================================
# UTILITY FUNCTIONS FOR SERIALIZATION
# ============================================================================

class EnhancedJSONEncoder(json.JSONEncoder):
    """Enhanced JSON encoder that handles enums, dates, and dataclasses."""

    def default(self, obj):
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, (ArchitecturalComponent, CurrentStateAnalysis, SolutionVision,
                            ImplementationStrategy, WorkChunk, ImplementationSession,
                            ValidationResult, LearningPoint, IterationPlan, CodeChange,
                            InterfaceDefinition, CodeLocation)):
            return obj.to_dict()
        if hasattr(obj, 'to_dict'):
            return obj.to_dict()
        if hasattr(obj, '__dict__'):
            return obj.__dict__
        return super().default(obj)


def save_model_to_json(model: Any, filepath: Path) -> None:
    """Save any model to JSON file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(model, f, cls=EnhancedJSONEncoder, indent=2)


def load_model_from_json(filepath: Path, model_class: Any) -> Any:
    """Load a model from JSON file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if hasattr(model_class, 'from_dict'):
        return model_class.from_dict(data)
    return data


# ============================================================================
# FACTORY FUNCTIONS FOR COMMON CREATIONS
# ============================================================================

def create_work_chunk(
        description: str,
        component: str,
        files_affected: List[str],
        requirements: str,
        acceptance_criteria: List[str],
        validation_method: str = "llm_review",
        dependencies: Optional[List[str]] = None,
        risks: Optional[List[Dict[str, Any]]] = None,
        estimated_complexity: str = "moderate"
) -> WorkChunk:
    """Factory function to create a WorkChunk with proper defaults."""
    return WorkChunk(
        id=f"chunk_{uuid.uuid4().hex[:8]}",
        description=description,
        component=component,
        files_affected=files_affected,
        requirements=requirements,
        acceptance_criteria=acceptance_criteria,
        validation_method=validation_method,
        dependencies=dependencies or [],
        risks=risks or [],
        estimated_complexity=estimated_complexity
    )


def create_solution_vision(
        requirements: str,
        architectural_approach: str,
        chosen_approach_reasoning: str,
        acceptance_criteria: List[str],
        architectural_constraints: List[str]
) -> SolutionVision:
    """Factory function to create a SolutionVision."""
    return SolutionVision(
        id=f"vision_{uuid.uuid4().hex[:8]}",
        requirements=requirements,
        architectural_approach=architectural_approach,
        chosen_approach_reasoning=chosen_approach_reasoning,
        rejected_approaches=[],
        acceptance_criteria=acceptance_criteria,
        architectural_constraints=architectural_constraints,
        success_metrics={},
        risks_mitigated=[]
    )


def create_learning_point(
        category: LearningCategory,
        title: str,
        description: str,
        source_session_id: str,
        context: Dict[str, Any],
        **kwargs
) -> LearningPoint:
    """Factory function to create a LearningPoint."""
    return LearningPoint(
        id=f"learning_{uuid.uuid4().hex[:8]}",
        category=category,
        title=title,
        description=description,
        source_session_id=source_session_id,
        context=context,
        **kwargs
    )