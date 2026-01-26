# src/assistant/core/reasoning_engine.py
"""
Architectural Reasoning Engine - High-level thinking and orchestration.
The "brain" that enables building from inside the repo.
"""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import logging

from assistant.core.reasoning_models import *
from assistant.core.snapshot_loader import SnapshotLoader
from assistant.api.client import DeepSeekClient
from assistant.core.context_manager import ContextManager
from assistant.core.file_loader import FileLoader

logger = logging.getLogger(__name__)


class StateAnalyzer:
    """Analyzes current architectural state from snapshot artifacts."""

    def __init__(self, snapshot_loader: SnapshotLoader):
        self.snapshot_loader = snapshot_loader

    async def analyze_snapshot(self, snapshot_dir: str) -> CurrentStateAnalysis:
        """Comprehensively analyze snapshot to understand current architecture."""
        logger.info(f"Analyzing snapshot: {snapshot_dir}")

        # Load snapshot artifacts
        artifacts = self.snapshot_loader.load_snapshot(snapshot_dir)

        # Extract architectural summary
        arch_summary = artifacts.get('loaded_artifacts', {}).get('architecture_summary', {})
        arch_context = arch_summary.get('architecture_context', {})

        # Analyze components
        components = self._extract_components(arch_context)

        # Identify gaps for assistant workflows
        gaps = self._identify_assistant_gaps(artifacts, components)

        # Assess risks
        risks = self._assess_architectural_risks(arch_context)

        return CurrentStateAnalysis(
            snapshot_dir=snapshot_dir,
            timestamp=datetime.now(),
            overview=arch_context.get('overview', ''),
            components=components,
            patterns=arch_context.get('patterns', []),
            tech_stack=arch_context.get('tech_stack', []),
            strengths=self._identify_strengths(arch_context),
            weaknesses=self._identify_weaknesses(arch_context),
            gaps_for_assistant=gaps,
            risks=risks
        )

    def _extract_components(self, arch_context: Dict) -> Dict[str, ArchitecturalComponent]:
        """Extract architectural components from context."""
        components = {}

        key_modules = arch_context.get('key_modules', [])
        for i, module in enumerate(key_modules):
            if isinstance(module, dict):
                name = module.get('name', f'module_{i}')
                components[name] = ArchitecturalComponent(
                    name=name,
                    purpose=module.get('description', '') or module.get('purpose', ''),
                    files=module.get('files', []),
                    dependencies=module.get('dependencies', []),
                    patterns=module.get('patterns', []),
                    interfaces=module.get('interfaces', {})
                )

        return components

    def _identify_assistant_gaps(self, artifacts: Dict, components: Dict) -> List[str]:
        """Identify what assistant needs but doesn't get from current artifacts."""
        gaps = []

        # Check for missing artifact types that would help assistant
        loaded_artifacts = artifacts.get('loaded_artifacts', {})

        if 'change_impact_analysis' not in loaded_artifacts:
            gaps.append("Missing change impact analysis")

        if 'code_templates' not in loaded_artifacts:
            gaps.append("Missing code generation templates")

        if 'api_contracts' not in loaded_artifacts:
            gaps.append("Missing detailed API contracts")

        # Check component completeness for assistant
        for comp_name, component in components.items():
            if not component.interfaces:
                gaps.append(f"Component {comp_name} lacks interface definitions")
            if len(component.files) == 0:
                gaps.append(f"Component {comp_name} has no files listed")

        return gaps

    def _assess_architectural_risks(self, arch_context: Dict) -> List[Dict[str, Any]]:
        """Assess architectural risks."""
        risks = []

        # Check for tight coupling
        if arch_context.get('coupling_level') == 'high':
            risks.append({
                "type": "coupling",
                "level": "high",
                "description": "High coupling between components",
                "impact": "Changes may have widespread effects"
            })

        # Check for complexity
        if len(arch_context.get('key_modules', [])) > 10:
            risks.append({
                "type": "complexity",
                "level": "medium",
                "description": "Many components increase complexity",
                "impact": "Harder to understand and modify"
            })

        return risks


class VisionCreator:
    """Creates solution visions aligned with architecture."""

    def __init__(self, deepseek_client: DeepSeekClient):
        self.client = deepseek_client

    async def create_vision(self,
                            requirements: str,
                            current_state: CurrentStateAnalysis,
                            user_feedback: Optional[str] = None) -> SolutionVision:
        """Create a solution vision through architectural reasoning."""

        # Build comprehensive prompt for architectural reasoning
        prompt = self._build_vision_prompt(requirements, current_state, user_feedback)

        # Get architectural reasoning from LLM
        messages = [
            {"role": "system", "content": self._get_architect_role_prompt()},
            {"role": "user", "content": prompt}
        ]

        response = ""
        async for chunk in self.client.chat_completion(messages=messages, stream=True, max_tokens=3000):
            response += chunk

        # Parse the structured response
        vision = self._parse_vision_response(response, requirements, current_state)

        return vision

    def _build_vision_prompt(self, requirements: str, current_state: CurrentStateAnalysis, user_feedback: Optional[str]) -> str:
        """Build prompt for architectural vision creation."""
        prompt = f"""
# ARCHITECTURAL VISION CREATION

## CURRENT ARCHITECTURE
{current_state.overview}

Key Components:
{self._format_components(current_state.components)}

Strengths: {', '.join(current_state.strengths)}
Weaknesses: {', '.join(current_state.weaknesses)}
Patterns: {', '.join(current_state.patterns)}

## REQUIREMENTS
{requirements}

{f"## USER FEEDBACK\n{user_feedback}" if user_feedback else ""}

## TASK
Create a solution vision that:
1. Addresses the requirements
2. Respects and builds upon the current architecture
3. Leverages existing patterns and strengths
4. Mitigates or works around weaknesses
5. Maintains or improves architectural integrity

Please provide:
1. **Architectural Approach**: High-level approach
2. **Alternative Approaches Considered**: What else was considered and why rejected
3. **Acceptance Criteria**: Clear criteria for success
4. **Architectural Constraints**: What must be preserved
5. **Risks Mitigated**: How this approach addresses risks
"""
        return prompt

    def _parse_vision_response(self, response: str, requirements: str, current_state: CurrentStateAnalysis) -> SolutionVision:
        """Parse LLM response into structured SolutionVision."""
        # This is simplified - in reality would need more sophisticated parsing
        # For now, create basic vision

        return SolutionVision(
            id=f"vision_{uuid.uuid4().hex[:8]}",
            requirements=requirements,
            architectural_approach=response[:500],  # Extract first part as approach
            chosen_approach_reasoning="Aligned with existing patterns and constraints",
            rejected_approaches=[],  # Would parse from response
            acceptance_criteria=[
                "Implementation meets requirements",
                "Maintains architectural integrity",
                "No new critical risks introduced"
            ],
            architectural_constraints=[
                "Must maintain existing interfaces",
                "Cannot break existing functionality"
            ],
            success_metrics={
                "requirements_met": True,
                "architecture_preserved": True,
                "code_quality_maintained": True
            },
            risks_mitigated=["High coupling", "Complexity"]
        )


class StrategyPlanner:
    """Creates implementation strategies from visions."""

    async def create_strategy(self, vision: SolutionVision, current_state: CurrentStateAnalysis) -> ImplementationStrategy:
        """Create detailed implementation strategy."""

        # Analyze which components are affected
        affected = self._identify_affected_components(vision, current_state)

        # Determine what needs to be created vs modified
        new_components, modified_components = self._categorize_changes(affected, current_state)

        # Determine execution sequence
        sequence = self._determine_execution_sequence(new_components, modified_components, current_state)

        # Identify dependencies
        dependencies = self._identify_dependencies(affected, current_state)

        return ImplementationStrategy(
            vision_id=vision.id,
            affected_components=affected,
            new_components=new_components,
            modified_components=modified_components,
            interfaces_to_change=self._identify_interface_changes(vision, current_state),
            execution_sequence=sequence,
            dependencies=dependencies,
            rollback_plan="Revert changes in reverse order of application"
        )


class WorkChunker:
    """Breaks strategies into executable work chunks."""

    def chunk_strategy(self, strategy: ImplementationStrategy, current_state: CurrentStateAnalysis) -> Dict[str, WorkChunk]:
        """Break strategy into concrete work chunks."""
        chunks = {}

        # Create chunks for new components
        for component_name in strategy.new_components:
            chunk_id = f"new_{component_name}_{uuid.uuid4().hex[:4]}"
            chunks[chunk_id] = self._create_component_chunk(
                chunk_id, component_name, "create", strategy, current_state
            )

        # Create chunks for modified components
        for component_name in strategy.modified_components:
            chunk_id = f"modify_{component_name}_{uuid.uuid4().hex[:4]}"
            chunks[chunk_id] = self._create_component_chunk(
                chunk_id, component_name, "modify", strategy, current_state
            )

        # Update dependencies between chunks
        self._update_chunk_dependencies(chunks, strategy)

        return chunks


class ImplementationOrchestrator:
    """Orchestrates execution of work chunks."""

    def __init__(self, programmatic_api, file_operator, change_tracker):
        self.api = programmatic_api
        self.file_operator = file_operator
        self.tracker = change_tracker

    async def execute_chunk(self, chunk: WorkChunk, session: ImplementationSession) -> WorkChunk:
        """Execute a single work chunk."""
        logger.info(f"Executing chunk: {chunk.id}")

        # Update status
        chunk.status = ImplementationStatus.IN_PROGRESS

        try:
            # Generate code using programmatic API
            generated = await self.api.generate_code_for_chunk(chunk, session.current_state)
            chunk.generated_code = generated

            # Validate against architecture
            validation = await self.validate_chunk(chunk, session)

            if validation["is_valid"]:
                # Apply changes
                applied = await self.file_operator.apply_changes(generated)
                chunk.applied_changes = applied
                chunk.status = ImplementationStatus.APPLIED

                # Run validations
                chunk.validation_results = await self.run_validations(chunk)

                if chunk.validation_results.get("passed", False):
                    chunk.status = ImplementationStatus.VALIDATED
                else:
                    chunk.status = ImplementationStatus.FAILED
            else:
                chunk.status = ImplementationStatus.FAILED
                chunk.feedback.append({
                    "type": "validation_failed",
                    "details": validation["issues"]
                })

        except Exception as e:
            logger.error(f"Failed to execute chunk {chunk.id}: {e}")
            chunk.status = ImplementationStatus.FAILED
            chunk.feedback.append({
                "type": "execution_error",
                "error": str(e)
            })

        # Track in change tracker
        await self.tracker.record_chunk_execution(chunk)

        return chunk


class ValidationEngine:
    """Validates implementations against visions."""

    async def validate_chunk(self, chunk: WorkChunk, session: ImplementationSession) -> ValidationReport:
        """Validate a work chunk against acceptance criteria."""
        report = ValidationReport(
            vision_id=session.vision.id,
            chunk_id=chunk.id,
            criteria_met=[],
            criteria_failed=[],
            architectural_integrity={},
            new_risks_introduced=[],
            recommendations=[],
            overall_status="pending"
        )

        # Check each acceptance criterion
        for criterion in chunk.acceptance_criteria:
            if self._check_criterion(criterion, chunk):
                report.criteria_met.append(criterion)
            else:
                report.criteria_failed.append({
                    "criterion": criterion,
                    "reason": "Not met"
                })

        # Check architectural integrity
        report.architectural_integrity = await self._check_architectural_integrity(chunk, session)

        # Assess new risks
        report.new_risks_introduced = self._assess_new_risks(chunk, session)

        # Determine overall status
        if len(report.criteria_failed) == 0 and report.architectural_integrity.get("is_intact", True):
            report.overall_status = "passed"
        else:
            report.overall_status = "failed"

        return report


# MAIN ENGINE CLASS
class ArchitecturalReasoningEngine:
    """Main engine orchestrating the entire reasoning process."""

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.client = None
        self.state_analyzer = None
        self.vision_creator = None
        self.strategy_planner = None
        self.work_chunker = None
        self.orchestrator = None
        self.validator = None

        # Session management
        self.active_sessions: Dict[str, ImplementationSession] = {}

    async def initialize(self):
        """Initialize all components."""
        self.client = DeepSeekClient(self.config_path)

        # Initialize components
        self.state_analyzer = StateAnalyzer(SnapshotLoader())
        self.vision_creator = VisionCreator(self.client)
        self.strategy_planner = StrategyPlanner()
        self.work_chunker = WorkChunker()

        # Note: Orchestrator and Validator need their dependencies
        # Will be initialized when needed

    async def start_implementation_session(self,
                                           requirements: str,
                                           snapshot_dir: str,
                                           session_id: Optional[str] = None) -> ImplementationSession:
        """Start a new implementation session."""
        if not session_id:
            session_id = f"session_{uuid.uuid4().hex[:8]}"

        logger.info(f"Starting implementation session: {session_id}")

        # 1. Analyze current state
        current_state = await self.state_analyzer.analyze_snapshot(snapshot_dir)

        # 2. Create solution vision
        vision = await self.vision_creator.create_vision(requirements, current_state)

        # 3. Create implementation strategy
        strategy = await self.strategy_planner.create_strategy(vision, current_state)

        # 4. Break into work chunks
        work_chunks = self.work_chunker.chunk_strategy(strategy, current_state)

        # Create session
        session = ImplementationSession(
            session_id=session_id,
            vision=vision,
            strategy=strategy,
            work_chunks=work_chunks,
            current_state=current_state,
            status="planned"
        )

        self.active_sessions[session_id] = session
        return session

    async def execute_session(self, session_id: str) -> ImplementationSession:
        """Execute an implementation session."""
        session = self.active_sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        session.status = "executing"
        session.updated_at = datetime.now()

        # Get execution order from strategy
        execution_order = self._determine_chunk_execution_order(session)

        # Execute chunks in order
        for chunk_id in execution_order:
            chunk = session.work_chunks[chunk_id]

            # Check dependencies are satisfied
            if not self._check_dependencies_satisfied(chunk, session):
                chunk.status = ImplementationStatus.BLOCKED
                continue

            # Execute chunk
            updated_chunk = await self.orchestrator.execute_chunk(chunk, session)
            session.work_chunks[chunk_id] = updated_chunk

            # If chunk failed, we may need to adjust strategy
            if updated_chunk.status == ImplementationStatus.FAILED:
                session.status = "needs_review"
                break

        # Update session status
        if all(chunk.status == ImplementationStatus.VALIDATED for chunk in session.work_chunks.values()):
            session.status = "completed"
        elif any(chunk.status == ImplementationStatus.FAILED for chunk in session.work_chunks.values()):
            session.status = "failed"

        session.updated_at = datetime.now()
        return session

    async def validate_session(self, session_id: str) -> ValidationReport:
        """Validate completed session against original vision."""
        session = self.active_sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # Collect all chunk validations
        chunk_reports = []
        for chunk in session.work_chunks.values():
            report = await self.validator.validate_chunk(chunk, session)
            chunk_reports.append(report)

        # Create overall validation report
        overall_report = ValidationReport(
            vision_id=session.vision.id,
            criteria_met=[],
            criteria_failed=[],
            architectural_integrity={},
            new_risks_introduced=[],
            recommendations=[],
            overall_status="pending"
        )

        # Aggregate results
        for report in chunk_reports:
            overall_report.criteria_met.extend(report.criteria_met)
            overall_report.criteria_failed.extend(report.criteria_failed)
            overall_report.new_risks_introduced.extend(report.new_risks_introduced)
            overall_report.recommendations.extend(report.recommendations)

        # Determine overall status
        if all(r.overall_status == "passed" for r in chunk_reports):
            overall_report.overall_status = "passed"
        else:
            overall_report.overall_status = "failed"

        return overall_report

    async def handle_iteration(self, session_id: str, feedback: Dict[str, Any]) -> IterationPlan:
        """Handle feedback and create iteration plan."""
        session = self.active_sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # Record feedback
        session.user_feedback_history.append({
            "timestamp": datetime.now(),
            "feedback": feedback,
            "iteration": session.iteration
        })

        # Analyze what needs to change
        issues = self._analyze_issues_from_feedback(feedback, session)

        # Plan next iteration
        iteration_plan = IterationPlan(
            session_id=session_id,
            iteration=session.iteration + 1,
            issues_to_address=issues,
            chunks_to_redo=self._identify_chunks_to_redo(session, issues),
            chunks_to_modify=self._identify_chunks_to_modify(session, issues),
            new_chunks_needed=self._identify_new_chunks_needed(session, issues),
            approach_adjustments=self._determine_approach_adjustments(session, issues),
            estimated_effort="moderate"  # Would calculate based on changes
        )

        return iteration_plan