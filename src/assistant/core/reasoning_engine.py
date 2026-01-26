# src/assistant/core/reasoning_engine.py
"""
Architectural Reasoning Engine - High-level thinking and orchestration.
The "brain" that enables building from inside the repo.

SYNC for local operations (file I/O, model creation, analysis)
ASYNC for API calls (DeepSeek API, network operations)
"""

import asyncio
import json
import uuid
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set
from datetime import datetime
from dataclasses import asdict

from assistant.core.reasoning_models import *
from assistant.core.snapshot_loader import SnapshotLoader
from assistant.api.client import DeepSeekClient
from assistant.core.context_manager import ContextManager
from assistant.core.file_loader import FileLoader
from assistant.core.learning_engine import LearningEngine
from assistant.core.focused_validator import FocusedValidator
from assistant.core.programmatic_api import ProgrammaticOrchestrator

logger = logging.getLogger(__name__)


# ============================================================================
# STATE ANALYZER (SYNC)
# ============================================================================

class StateAnalyzer:
    """Analyzes current architectural state from snapshot artifacts. SYNC."""

    def __init__(self, snapshot_loader: SnapshotLoader, file_loader: FileLoader):
        self.snapshot_loader = snapshot_loader
        self.file_loader = file_loader

    def analyze_snapshot(self, snapshot_dir: str) -> CurrentStateAnalysis:
        """
        Comprehensively analyze snapshot to understand current architecture.
        SYNC operation - no API calls.
        """
        logger.info(f"Analyzing snapshot: {snapshot_dir}")

        # Load snapshot artifacts
        artifacts = self.snapshot_loader.load_snapshot(snapshot_dir)

        # Extract architectural summary
        arch_summary = artifacts.get('loaded_artifacts', {}).get('architecture_summary', {})
        arch_context = arch_summary.get('architecture_context', {})

        # Extract repository info from repo_index
        repo_index = artifacts.get('loaded_artifacts', {}).get('repo_index', {})

        # Analyze components
        components = self._extract_components(arch_context, snapshot_dir)

        # Analyze patterns and tech stack
        patterns = self._extract_patterns(arch_context)
        tech_stack = self._extract_tech_stack(arch_context)

        # Identify gaps for assistant workflows
        gaps = self._identify_assistant_gaps(artifacts, components)

        # Assess risks
        risks = self._assess_architectural_risks(arch_context, components)

        # Calculate file and line counts
        file_count, total_lines = self._calculate_repo_metrics(repo_index, snapshot_dir)

        # Create analysis
        analysis = CurrentStateAnalysis(
            snapshot_dir=snapshot_dir,
            timestamp=datetime.now(),
            overview=arch_context.get('overview', 'No overview available'),
            components=components,
            patterns=patterns,
            tech_stack=tech_stack,
            strengths=self._identify_strengths(arch_context, components),
            weaknesses=self._identify_weaknesses(arch_context, components),
            gaps_for_assistant=gaps,
            risks=risks,
            key_decisions=self._extract_key_decisions(arch_context),
            architectural_guiding_principles=self._extract_guiding_principles(arch_context),
            known_constraints=self._extract_constraints(arch_context),
            analysis_confidence=self._calculate_confidence(arch_summary),
            data_source="snapshot_artifacts",
            file_count=file_count,
            total_lines_of_code=total_lines
        )

        logger.info(f"Analysis complete: {len(components)} components, {file_count} files")
        return analysis

    def _extract_components(self, arch_context: Dict, snapshot_dir: str) -> Dict[str, ArchitecturalComponent]:
        """Extract architectural components from context."""
        components = {}

        key_modules = arch_context.get('key_modules', [])

        for i, module in enumerate(key_modules):
            if isinstance(module, dict):
                name = module.get('name', f'module_{i}')

                # Determine component type
                comp_type = self._determine_component_type(module, name)

                # Get files for this component
                files = module.get('files', [])
                if not files:
                    # Try to infer files from snapshot
                    files = self._infer_component_files(name, snapshot_dir)

                # Create component
                component = ArchitecturalComponent(
                    name=name,
                    type=comp_type,
                    purpose=module.get('description', '') or module.get('purpose', 'No description'),
                    description=module.get('detailed_description', ''),
                    files=files,
                    dependencies=module.get('dependencies', []),
                    patterns=module.get('patterns', []),
                    interfaces=self._extract_interfaces(module),
                    key_functions=module.get('key_functions', []),
                    complexity_score=self._calculate_complexity(module),
                    stability_score=self._assess_stability(module, name, snapshot_dir),
                    test_coverage=self._get_test_coverage(name, snapshot_dir),
                    documentation_status=self._assess_documentation(module, name, snapshot_dir),
                    ownership=module.get('ownership'),
                    created_at=self._parse_date(module.get('created_at')),
                    last_modified=self._parse_date(module.get('last_modified'))
                )

                components[name] = component
            elif isinstance(module, str):
                # Simple module name
                component = ArchitecturalComponent(
                    name=module,
                    type=ComponentType.UNKNOWN,
                    purpose=f"Module referenced as: {module}",
                    files=[],
                    dependencies=[],
                    patterns=[],
                    interfaces={},
                    complexity_score=0.5,
                    stability_score=0.5
                )
                components[module] = component

        # If no components found, create a default one
        if not components:
            logger.warning("No components found in architecture context")
            default_comp = ArchitecturalComponent(
                name="main",
                type=ComponentType.MODULE,
                purpose="Main codebase",
                description="Default component when architecture analysis is limited",
                files=[],
                dependencies=[],
                patterns=[],
                interfaces={},
                complexity_score=0.5,
                stability_score=0.5
            )
            components["main"] = default_comp

        return components

    def _extract_patterns(self, arch_context: Dict) -> List[str]:
        """Extract design patterns from architecture context."""
        patterns = []

        # Get explicit patterns
        explicit_patterns = arch_context.get('patterns', [])
        if isinstance(explicit_patterns, list):
            patterns.extend([p for p in explicit_patterns if isinstance(p, str)])

        # Extract implicit patterns from descriptions
        overview = arch_context.get('overview', '').lower()
        if 'singleton' in overview or 'factory' in overview or 'observer' in overview:
            # Extract mentioned patterns
            known_patterns = ['singleton', 'factory', 'observer', 'strategy',
                              'adapter', 'decorator', 'facade', 'proxy']
            for pattern in known_patterns:
                if pattern in overview:
                    patterns.append(pattern)

        # Deduplicate
        return list(dict.fromkeys(patterns))

    def _extract_tech_stack(self, arch_context: Dict) -> List[str]:
        """Extract technology stack from architecture context."""
        tech_stack = arch_context.get('tech_stack', [])
        if isinstance(tech_stack, list):
            return [t for t in tech_stack if isinstance(t, str)]
        return []

    def _identify_assistant_gaps(self, artifacts: Dict, components: Dict[str, ArchitecturalComponent]) -> List[str]:
        """Identify what assistant needs but doesn't get from current artifacts."""
        gaps = []

        loaded_artifacts = artifacts.get('loaded_artifacts', {})

        # Check for missing artifact types that would help assistant
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
            if component.documentation_status == 'none':
                gaps.append(f"Component {comp_name} lacks documentation")

        return gaps

    def _assess_architectural_risks(self, arch_context: Dict,
                                    components: Dict[str, ArchitecturalComponent]) -> List[Dict[str, Any]]:
        """Assess architectural risks."""
        risks = []

        # Check for tight coupling
        coupling_level = arch_context.get('coupling_level', 'medium')
        if coupling_level == 'high':
            risks.append({
                "type": "coupling",
                "level": RiskLevel.HIGH.value,
                "description": "High coupling between components",
                "impact": "Changes may have widespread effects",
                "mitigation": "Consider refactoring to reduce dependencies"
            })

        # Check for complexity
        component_count = len(components)
        if component_count > 15:
            risks.append({
                "type": "complexity",
                "level": RiskLevel.MEDIUM.value,
                "description": f"Many components ({component_count}) increase complexity",
                "impact": "Harder to understand and modify",
                "mitigation": "Consider modularization or documentation improvements"
            })

        # Check for documentation gaps
        doc_gaps = sum(1 for c in components.values()
                       if c.documentation_status in ['none', 'partial'])
        if doc_gaps > len(components) * 0.5:  # More than 50% undocumented
            risks.append({
                "type": "documentation",
                "level": RiskLevel.MEDIUM.value,
                "description": f"Significant documentation gaps ({doc_gaps}/{len(components)} components)",
                "impact": "Harder for assistant to understand architecture",
                "mitigation": "Improve documentation of key components"
            })

        # Check for testing gaps
        untested = sum(1 for c in components.values()
                       if c.test_coverage is None or c.test_coverage < 70)
        if untested > len(components) * 0.3:  # More than 30% poorly tested
            risks.append({
                "type": "testing",
                "level": RiskLevel.MEDIUM.value,
                "description": f"Limited test coverage ({untested}/{len(components)} components)",
                "impact": "Changes may introduce regressions",
                "mitigation": "Increase test coverage for modified components"
            })

        return risks

    # Helper methods for component analysis
    def _determine_component_type(self, module: Dict, name: str) -> ComponentType:
        """Determine component type from module data."""
        name_lower = name.lower()

        if any(x in name_lower for x in ['api', 'endpoint', 'route']):
            return ComponentType.API
        elif any(x in name_lower for x in ['db', 'database', 'store', 'repo']):
            return ComponentType.DATABASE
        elif any(x in name_lower for x in ['ui', 'frontend', 'view', 'template']):
            return ComponentType.UI
        elif any(x in name_lower for x in ['test', 'spec', 'fixture']):
            return ComponentType.TEST
        elif any(x in name_lower for x in ['config', 'settings', 'env']):
            return ComponentType.CONFIG
        elif any(x in name_lower for x in ['service', 'manager', 'handler']):
            return ComponentType.SERVICE
        elif any(x in name_lower for x in ['util', 'helper', 'common']):
            return ComponentType.UTILITY
        else:
            return ComponentType.MODULE

    def _infer_component_files(self, component_name: str, snapshot_dir: str) -> List[str]:
        """Infer files belonging to a component based on naming patterns."""
        # This is a simplified implementation
        # In production, this would scan the snapshot directory
        return []

    def _extract_interfaces(self, module: Dict) -> Dict[str, InterfaceDefinition]:
        """Extract interface definitions from module data."""
        interfaces = {}
        module_interfaces = module.get('interfaces', {})

        if isinstance(module_interfaces, dict):
            for iface_name, iface_data in module_interfaces.items():
                if isinstance(iface_data, dict):
                    interface = InterfaceDefinition(
                        name=iface_name,
                        description=iface_data.get('description', f"Interface for {iface_name}"),
                        methods=iface_data.get('methods', []),
                        inputs=iface_data.get('inputs', []),
                        outputs=iface_data.get('outputs', []),
                        errors=iface_data.get('errors', []),
                        examples=iface_data.get('examples', [])
                    )
                    interfaces[iface_name] = interface

        return interfaces

    def _calculate_complexity(self, module: Dict) -> float:
        """Calculate complexity score for a component (0-1)."""
        # Simplified implementation
        files_count = len(module.get('files', []))
        deps_count = len(module.get('dependencies', []))

        # Simple heuristic: more files and dependencies = more complex
        complexity = min(0.3 + (files_count * 0.05) + (deps_count * 0.03), 1.0)
        return round(complexity, 2)

    def _assess_stability(self, module: Dict, component_name: str, snapshot_dir: str) -> float:
        """Assess stability score for a component (0-1)."""
        # Simplified implementation
        # In production, would analyze git history, change frequency, etc.
        return 0.7  # Default moderate stability

    def _get_test_coverage(self, component_name: str, snapshot_dir: str) -> Optional[float]:
        """Get test coverage for a component."""
        # Simplified implementation
        return None

    def _assess_documentation(self, module: Dict, component_name: str, snapshot_dir: str) -> str:
        """Assess documentation status for a component."""
        # Simplified implementation
        if module.get('documentation') or module.get('description'):
            return 'partial'
        return 'unknown'

    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse date string to datetime."""
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except:
            return None

    def _extract_key_decisions(self, arch_context: Dict) -> List[Dict[str, Any]]:
        """Extract key architectural decisions."""
        decisions = arch_context.get('key_decisions', [])
        if isinstance(decisions, list):
            return decisions
        return []

    def _extract_guiding_principles(self, arch_context: Dict) -> List[str]:
        """Extract architectural guiding principles."""
        principles = arch_context.get('guiding_principles', [])
        if isinstance(principles, list):
            return [p for p in principles if isinstance(p, str)]
        return []

    def _extract_constraints(self, arch_context: Dict) -> List[Dict[str, Any]]:
        """Extract known architectural constraints."""
        constraints = arch_context.get('constraints', [])
        if isinstance(constraints, list):
            return constraints
        return []

    def _calculate_confidence(self, arch_summary: Dict) -> float:
        """Calculate confidence score for the analysis (0-1)."""
        # Simplified: more complete data = higher confidence
        if not arch_summary:
            return 0.3

        completeness_factors = []

        if arch_summary.get('architecture_context', {}).get('overview'):
            completeness_factors.append(0.2)

        if arch_summary.get('architecture_context', {}).get('key_modules'):
            completeness_factors.append(0.3)

        if arch_summary.get('architecture_context', {}).get('tech_stack'):
            completeness_factors.append(0.2)

        if arch_summary.get('architecture_context', {}).get('patterns'):
            completeness_factors.append(0.1)

        if arch_summary.get('architecture_context', {}).get('constraints'):
            completeness_factors.append(0.1)

        if arch_summary.get('architecture_context', {}).get('key_decisions'):
            completeness_factors.append(0.1)

        confidence = sum(completeness_factors)
        return min(confidence, 1.0)

    def _identify_strengths(self, arch_context: Dict, components: Dict[str, ArchitecturalComponent]) -> List[str]:
        """Identify architectural strengths."""
        strengths = []

        # Modularity
        if len(components) > 1 and len(components) < 10:
            strengths.append("Good modularity with clear component separation")

        # Clear patterns
        patterns = self._extract_patterns(arch_context)
        if patterns:
            strengths.append(f"Uses established patterns: {', '.join(patterns[:3])}")

        # Documentation
        documented = sum(1 for c in components.values()
                         if c.documentation_status in ['partial', 'complete'])
        if documented > len(components) * 0.5:
            strengths.append("Good component documentation")

        return strengths

    def _identify_weaknesses(self, arch_context: Dict, components: Dict[str, ArchitecturalComponent]) -> List[str]:
        """Identify architectural weaknesses."""
        weaknesses = []

        # Component count
        if len(components) > 15:
            weaknesses.append("High number of components may indicate over-engineering")
        elif len(components) <= 1:
            weaknesses.append("Monolithic structure with poor separation of concerns")

        # Documentation gaps
        undocumented = sum(1 for c in components.values()
                           if c.documentation_status == 'none')
        if undocumented > len(components) * 0.3:
            weaknesses.append(f"Limited documentation ({undocumented}/{len(components)} components undocumented)")

        return weaknesses

    def _calculate_repo_metrics(self, repo_index: Dict, snapshot_dir: str) -> Tuple[int, int]:
        """Calculate repository metrics (file count, total lines)."""
        if not repo_index or not isinstance(repo_index, dict):
            return 0, 0

        files = repo_index.get('files', [])
        if isinstance(files, list):
            return len(files), 0  # Simplified - would count lines in production

        return 0, 0


# ============================================================================
# VISION CREATOR (ASYNC)
# ============================================================================

class VisionCreator:
    """Creates solution visions aligned with architecture. ASYNC for API calls."""

    def __init__(self, deepseek_client: DeepSeekClient):
        self.client = deepseek_client

    async def create_vision(self,
                            requirements: str,
                            current_state: CurrentStateAnalysis,
                            user_feedback: Optional[str] = None) -> SolutionVision:
        """Create a solution vision through architectural reasoning."""

        logger.info(f"Creating vision for: {requirements[:50]}...")

        # Build comprehensive prompt for architectural reasoning
        prompt = self._build_vision_prompt(requirements, current_state, user_feedback)

        # Get architectural reasoning from LLM
        messages = [
            {"role": "system", "content": self._get_architect_role_prompt()},
            {"role": "user", "content": prompt}
        ]

        response_text = ""
        try:
            async for chunk in self.client.chat_completion(
                    messages=messages,
                    stream=True,
                    max_tokens=3000,
                    temperature=0.7
            ):
                response_text += chunk

            logger.info(f"Vision created successfully, response length: {len(response_text)}")
        except Exception as e:
            logger.error(f"Failed to create vision: {e}")
            response_text = f"Error creating vision: {e}"

        # Parse the structured response
        vision = self._parse_vision_response(response_text, requirements, current_state, user_feedback)

        return vision

    def _build_vision_prompt(self, requirements: str,
                             current_state: CurrentStateAnalysis,
                             user_feedback: Optional[str]) -> str:
        """Build prompt for architectural vision creation."""
        prompt = f"""# ARCHITECTURAL VISION CREATION

## CURRENT ARCHITECTURE ANALYSIS

**Overview**: {current_state.overview[:500]}

**Key Components ({len(current_state.components)}):**
{self._format_components_for_prompt(current_state.components)}

**Technology Stack**: {', '.join(current_state.tech_stack[:10])}

**Strengths**: {', '.join(current_state.strengths)}
**Weaknesses**: {', '.join(current_state.weaknesses)}
**Patterns Used**: {', '.join(current_state.patterns[:5])}

**Architectural Constraints**:
{self._format_constraints(current_state.known_constraints)}

**Known Risks**:
{self._format_risks(current_state.risks)}

## REQUIREMENTS TO IMPLEMENT
{requirements}

{f"## USER FEEDBACK FROM PREVIOUS ITERATION\n{user_feedback}" if user_feedback else ""}

## TASK: CREATE SOLUTION VISION

Create a solution vision that:
1. **Addresses the requirements** - Meet the stated needs
2. **Respects current architecture** - Build upon existing patterns and structures
3. **Leverages strengths** - Use what already works well
4. **Mitigates weaknesses** - Avoid or work around known issues
5. **Maintains integrity** - Keep the architecture coherent and consistent
6. **Considers constraints** - Work within the stated limitations

## OUTPUT FORMAT

Provide your response in this structured format:

**ARCHITECTURAL APPROACH**:
[High-level approach, 2-3 paragraphs]

**ALTERNATIVE APPROACHES CONSIDERED**:
1. [Approach 1]: [Why considered and rejected]
2. [Approach 2]: [Why considered and rejected]

**ACCEPTANCE CRITERIA**:
1. [Clear, testable criterion]
2. [Clear, testable criterion]
3. [Clear, testable criterion]

**ARCHITECTURAL CONSTRAINTS TO PRESERVE**:
1. [Constraint that must be maintained]
2. [Constraint that must be maintained]

**RISKS MITIGATED BY THIS APPROACH**:
1. [How this approach addresses known risk 1]
2. [How this approach addresses known risk 2]

**ASSUMPTIONS**:
1. [Assumption made]
2. [Assumption made]

**OPEN QUESTIONS**:
1. [Question that needs clarification]
2. [Question that needs clarification]

**PRIORITY & EFFORT ESTIMATE**:
[small/medium/large/x-large] effort, [low/medium/high/critical] priority
"""
        return prompt

    def _get_architect_role_prompt(self) -> str:
        """Get the system prompt for the architect role."""
        return """You are an experienced software architect and technical lead. 
Your role is to analyze existing codebases and create coherent, practical solution visions 
that respect architectural constraints while meeting requirements.

You think carefully about:
1. How to build upon existing patterns and structures
2. What changes will have the least disruption
3. How to maintain architectural integrity
4. What risks need mitigation
5. What assumptions you're making

You provide clear, structured reasoning that can be reviewed and iterated upon.
You're pragmatic, not academic. You prefer simple solutions that work over complex ones that might be "more correct" theoretically.

Format your responses clearly with the requested structure."""

    def _format_components_for_prompt(self, components: Dict[str, ArchitecturalComponent]) -> str:
        """Format components for the prompt."""
        if not components:
            return "No components identified."

        formatted = []
        for name, component in list(components.items())[:8]:  # Limit to 8 components
            formatted.append(f"- **{name}** ({component.type.value}): {component.purpose[:100]}")
            if component.dependencies:
                formatted.append(f"  Depends on: {', '.join(component.dependencies[:3])}")

        return "\n".join(formatted)

    def _format_constraints(self, constraints: List[Dict[str, Any]]) -> str:
        """Format constraints for the prompt."""
        if not constraints:
            return "No explicit constraints identified."

        formatted = []
        for i, constraint in enumerate(constraints[:5], 1):
            if isinstance(constraint, dict):
                desc = constraint.get('description', 'Unknown constraint')
                formatted.append(f"{i}. {desc}")
            elif isinstance(constraint, str):
                formatted.append(f"{i}. {constraint}")

        return "\n".join(formatted)

    def _format_risks(self, risks: List[Dict[str, Any]]) -> str:
        """Format risks for the prompt."""
        if not risks:
            return "No significant risks identified."

        formatted = []
        for i, risk in enumerate(risks[:5], 1):
            if isinstance(risk, dict):
                desc = risk.get('description', 'Unknown risk')
                level = risk.get('level', 'medium')
                formatted.append(f"{i}. [{level.upper()}] {desc}")

        return "\n".join(formatted)

    def _parse_vision_response(self, response: str, requirements: str,
                               current_state: CurrentStateAnalysis,
                               user_feedback: Optional[str]) -> SolutionVision:
        """Parse LLM response into structured SolutionVision."""

        # Extract sections from response
        sections = self._extract_sections(response)

        # Create vision with parsed data
        vision = SolutionVision(
            id=f"vision_{uuid.uuid4().hex[:8]}",
            requirements=requirements,
            architectural_approach=sections.get('architectural_approach', response[:500]),
            chosen_approach_reasoning="Generated through architectural analysis",
            rejected_approaches=self._parse_rejected_approaches(sections.get('alternative_approaches_considered', '')),
            acceptance_criteria=self._parse_list_items(sections.get('acceptance_criteria', '')),
            architectural_constraints=self._parse_list_items(sections.get('architectural_constraints_to_preserve', '')),
            success_metrics={
                "requirements_addressed": True,
                "architecture_preserved": True,
                "constraints_respected": True
            },
            risks_mitigated=self._parse_list_items(sections.get('risks_mitigated_by_this_approach', '')),
            user_feedback=user_feedback,
            assumptions=self._parse_list_items(sections.get('assumptions', '')),
            open_questions=self._parse_list_items(sections.get('open_questions', '')),
            priority=self._extract_priority(sections.get('priority_&_effort_estimate', '')),
            estimated_effort=self._extract_effort(sections.get('priority_&_effort_estimate', '')),
            confidence_score=0.8  # Default confidence
        )

        return vision

    def _extract_sections(self, text: str) -> Dict[str, str]:
        """Extract sections from structured response."""
        sections = {}
        current_section = None
        current_content = []

        lines = text.split('\n')
        for line in lines:
            line = line.strip()

            # Check for section headers (all caps, bold, or followed by colon)
            if (line.upper() == line and len(line) > 5 and ':' not in line) or \
                    line.startswith('**') and line.endswith('**') or \
                    (':' in line and line.split(':')[0].isupper()):

                # Save previous section
                if current_section and current_content:
                    sections[current_section] = '\n'.join(current_content).strip()

                # Start new section
                section_name = line.lower().replace('**', '').replace(':', '').strip()
                section_name = section_name.replace(' ', '_').replace('&', 'and')
                current_section = section_name
                current_content = []
            elif current_section:
                current_content.append(line)

        # Save last section
        if current_section and current_content:
            sections[current_section] = '\n'.join(current_content).strip()

        return sections

    def _parse_rejected_approaches(self, text: str) -> List[Dict[str, str]]:
        """Parse rejected approaches from text."""
        approaches = []

        # Look for numbered or bulleted items
        lines = text.split('\n')
        for line in lines:
            line = line.strip()

            # Check for patterns like "1. [Approach]: Reason" or "- [Approach]: Reason"
            if line.startswith(('1.', '2.', '3.', '4.', '5.', '- ', '* ')):
                # Extract approach and reason
                parts = line[2:].split(':', 1)
                if len(parts) == 2:
                    approach = parts[0].strip()
                    reason = parts[1].strip()
                    approaches.append({
                        'approach': approach,
                        'reason': reason
                    })

        return approaches

    def _parse_list_items(self, text: str) -> List[str]:
        """Parse list items from text."""
        items = []

        lines = text.split('\n')
        for line in lines:
            line = line.strip()

            # Check for numbered or bulleted items
            if (line.startswith(('1.', '2.', '3.', '4.', '5.', '- ', '* ', '• ')) or
                    (line and line[0].isdigit() and '. ' in line)):

                # Remove bullet/number
                if '. ' in line:
                    item = line.split('. ', 1)[1].strip()
                elif line.startswith(('- ', '* ', '• ')):
                    item = line[2:].strip()
                else:
                    item = line

                if item:
                    items.append(item)

        return items if items else [text.strip()] if text.strip() else []

    def _extract_priority(self, text: str) -> str:
        """Extract priority from text."""
        text_lower = text.lower()
        if 'critical' in text_lower:
            return 'critical'
        elif 'high' in text_lower:
            return 'high'
        elif 'medium' in text_lower:
            return 'medium'
        elif 'low' in text_lower:
            return 'low'
        return 'medium'

    def _extract_effort(self, text: str) -> str:
        """Extract effort estimate from text."""
        text_lower = text.lower()
        if 'x-large' in text_lower or 'extra large' in text_lower:
            return 'x-large'
        elif 'large' in text_lower:
            return 'large'
        elif 'medium' in text_lower:
            return 'medium'
        elif 'small' in text_lower:
            return 'small'
        return 'unknown'


# ============================================================================
# STRATEGY PLANNER (SYNC)
# ============================================================================

class StrategyPlanner:
    """Creates implementation strategies from visions. SYNC."""

    def __init__(self):
        pass

    def create_strategy(self, vision: SolutionVision,
                        current_state: CurrentStateAnalysis) -> ImplementationStrategy:
        """Create detailed implementation strategy."""

        logger.info(f"Creating strategy for vision: {vision.id}")

        # Analyze which components are affected by the vision
        affected_components = self._identify_affected_components(vision, current_state)

        # Determine what needs to be created vs modified
        new_components, modified_components = self._categorize_changes(
            affected_components, current_state
        )

        # Determine execution sequence
        execution_sequence = self._determine_execution_sequence(
            new_components, modified_components, current_state
        )

        # Identify dependencies
        dependencies = self._identify_dependencies(affected_components, current_state)

        # Identify interfaces that need to change
        interfaces_to_change = self._identify_interface_changes(vision, current_state)

        # Create strategy
        strategy = ImplementationStrategy(
            vision_id=vision.id,
            affected_components=affected_components,
            new_components=new_components,
            modified_components=modified_components,
            interfaces_to_change=interfaces_to_change,
            execution_sequence=execution_sequence,
            dependencies=dependencies,
            rollback_plan=self._create_rollback_plan(new_components, modified_components),
            estimated_timeline=self._estimate_timeline(vision, new_components, modified_components),
            phase_breakdown=self._create_phase_breakdown(execution_sequence),
            milestones=self._create_milestones(vision, execution_sequence),
            validation_checkpoints=self._create_validation_checkpoints(execution_sequence),
            risk_mitigation_strategies=self._create_risk_mitigation_strategies(vision, current_state)
        )

        logger.info(f"Strategy created: {len(new_components)} new, {len(modified_components)} modified components")
        return strategy

    def _identify_affected_components(self, vision: SolutionVision,
                                      current_state: CurrentStateAnalysis) -> List[str]:
        """Identify which components are affected by the vision."""
        affected = set()

        # Simple keyword matching (in production, would use more sophisticated NLP)
        requirements_lower = vision.requirements.lower()
        approach_lower = vision.architectural_approach.lower()

        for comp_name, component in current_state.components.items():
            comp_name_lower = comp_name.lower()
            purpose_lower = component.purpose.lower()

            # Check if component name or purpose appears in requirements or approach
            if (comp_name_lower in requirements_lower or
                    comp_name_lower in approach_lower or
                    any(word in purpose_lower for word in requirements_lower.split()[:10])):
                affected.add(comp_name)

        # Also consider components mentioned in acceptance criteria
        for criterion in vision.acceptance_criteria:
            criterion_lower = criterion.lower()
            for comp_name in current_state.components.keys():
                if comp_name.lower() in criterion_lower:
                    affected.add(comp_name)

        return list(affected)

    def _categorize_changes(self, affected_components: List[str],
                            current_state: CurrentStateAnalysis) -> Tuple[List[str], List[str]]:
        """Determine what needs to be created vs modified."""
        new_components = []
        modified_components = []

        for component_name in affected_components:
            if component_name in current_state.components:
                modified_components.append(component_name)
            else:
                # Component doesn't exist yet, needs to be created
                new_components.append(component_name)

        return new_components, modified_components

    def _determine_execution_sequence(self, new_components: List[str],
                                      modified_components: List[str],
                                      current_state: CurrentStateAnalysis) -> List[str]:
        """Determine optimal execution sequence."""
        sequence = []

        # First, create new components (they don't depend on existing modified ones)
        sequence.extend(new_components)

        # Then modify existing components
        sequence.extend(modified_components)

        # In production, would do topological sort based on dependencies
        return sequence

    def _identify_dependencies(self, affected_components: List[str],
                               current_state: CurrentStateAnalysis) -> Dict[str, List[str]]:
        """Identify dependencies between affected components."""
        dependencies = {}

        for component_name in affected_components:
            if component_name in current_state.components:
                component = current_state.components[component_name]
                # Only include dependencies that are also affected
                affected_deps = [
                    dep for dep in component.dependencies
                    if dep in affected_components
                ]
                if affected_deps:
                    dependencies[component_name] = affected_deps

        return dependencies

    def _identify_interface_changes(self, vision: SolutionVision,
                                    current_state: CurrentStateAnalysis) -> List[Dict[str, Any]]:
        """Identify interfaces that need to change."""
        # Simplified implementation
        # In production, would analyze vision text for interface mentions
        return []

    def _create_rollback_plan(self, new_components: List[str],
                              modified_components: List[str]) -> str:
        """Create rollback plan."""
        plan_parts = []

        if new_components:
            plan_parts.append(f"1. Remove newly created components: {', '.join(new_components)}")

        if modified_components:
            plan_parts.append(f"2. Restore original versions of modified components: {', '.join(modified_components)}")

        if not plan_parts:
            plan_parts.append("No changes to roll back.")

        plan_parts.append("3. Verify system returns to original state.")

        return "\n".join(plan_parts)

    def _estimate_timeline(self, vision: SolutionVision,
                           new_components: List[str],
                           modified_components: List[str]) -> str:
        """Estimate timeline for implementation."""
        total_components = len(new_components) + len(modified_components)

        if total_components == 0:
            return "No implementation needed."
        elif total_components == 1:
            return "1-2 days for single component change."
        elif total_components <= 3:
            return "3-5 days for small set of changes."
        elif total_components <= 6:
            return "1-2 weeks for moderate changes."
        else:
            return "2+ weeks for extensive changes."

    def _create_phase_breakdown(self, execution_sequence: List[str]) -> List[Dict[str, Any]]:
        """Create phase breakdown for the strategy."""
        phases = []

        # Group components into phases (simplified: 3 components per phase)
        for i in range(0, len(execution_sequence), 3):
            phase_components = execution_sequence[i:i+3]
            phases.append({
                'phase': f"Phase {i//3 + 1}",
                'components': phase_components,
                'objective': f"Implement {', '.join(phase_components)}",
                'validation': f"Test {len(phase_components)} component(s)"
            })

        return phases

    def _create_milestones(self, vision: SolutionVision,
                           execution_sequence: List[str]) -> List[Dict[str, Any]]:
        """Create milestones for the strategy."""
        milestones = []

        if execution_sequence:
            # First component completed
            milestones.append({
                'milestone': 'First Component',
                'component': execution_sequence[0],
                'criteria': f'{execution_sequence[0]} implemented and validated'
            })

            # Midpoint
            mid_point = len(execution_sequence) // 2
            if mid_point > 0:
                milestones.append({
                    'milestone': 'Halfway Point',
                    'components': execution_sequence[:mid_point],
                    'criteria': f'{mid_point} component(s) completed'
                })

            # All components
            milestones.append({
                'milestone': 'All Components',
                'components': execution_sequence,
                'criteria': 'All components implemented and integrated'
            })

        return milestones

    def _create_validation_checkpoints(self, execution_sequence: List[str]) -> List[Dict[str, Any]]:
        """Create validation checkpoints."""
        checkpoints = []

        for i, component in enumerate(execution_sequence, 1):
            checkpoints.append({
                'checkpoint': f'CP{i:02d}',
                'component': component,
                'validation': f'Validate {component} implementation',
                'criteria': ['Code compiles/runs', 'Tests pass', 'Interfaces work']
            })

        return checkpoints

    def _create_risk_mitigation_strategies(self, vision: SolutionVision,
                                           current_state: CurrentStateAnalysis) -> List[Dict[str, Any]]:
        """Create risk mitigation strategies."""
        strategies = []

        # Generic strategies based on common risks
        strategies.append({
            'risk': 'Breaking existing functionality',
            'mitigation': 'Comprehensive testing before and after changes',
            'owner': 'Assistant'
        })

        strategies.append({
            'risk': 'Architectural inconsistency',
            'mitigation': 'Regular architecture reviews during implementation',
            'owner': 'Assistant'
        })

        strategies.append({
            'risk': 'Scope creep',
            'mitigation': 'Strict adherence to acceptance criteria',
            'owner': 'Assistant'
        })

        return strategies


# ============================================================================
# WORK CHUNKER (SYNC)
# ============================================================================

class WorkChunker:
    """Breaks strategies into executable work chunks. SYNC."""

    def __init__(self):
        pass

    def chunk_strategy(self, strategy: ImplementationStrategy,
                       current_state: CurrentStateAnalysis) -> Dict[str, WorkChunk]:
        """Break strategy into concrete work chunks."""
        chunks = {}

        logger.info(f"Chunking strategy for {len(strategy.new_components)} new, "
                    f"{len(strategy.modified_components)} modified components")

        # Create chunks for new components
        for component_name in strategy.new_components:
            chunk = self._create_component_chunk(
                component_name, "create", strategy, current_state
            )
            chunks[chunk.id] = chunk

        # Create chunks for modified components
        for component_name in strategy.modified_components:
            chunk = self._create_component_chunk(
                component_name, "modify", strategy, current_state
            )
            chunks[chunk.id] = chunk

        # Update dependencies between chunks
        self._update_chunk_dependencies(chunks, strategy)

        logger.info(f"Created {len(chunks)} work chunks")
        return chunks

    def _create_component_chunk(self, component_name: str, action: str,
                                strategy: ImplementationStrategy,
                                current_state: CurrentStateAnalysis) -> WorkChunk:
        """Create a work chunk for a component."""
        chunk_id = f"{action}_{component_name}_{uuid.uuid4().hex[:4]}"

        # Determine files affected
        files_affected = []
        if component_name in current_state.components:
            component = current_state.components[component_name]
            files_affected = component.files[:5]  # Limit to 5 files

        # Create requirements description
        if action == "create":
            requirements = f"Create new component '{component_name}' with appropriate functionality"
        else:
            requirements = f"Modify existing component '{component_name}' to meet requirements"

        # Determine acceptance criteria
        acceptance_criteria = [
            f"Component '{component_name}' {action}d successfully",
            f"Code compiles/runs without errors",
            f"Changes align with architectural approach"
        ]

        # Determine risks
        risks = []
        if action == "create":
            risks.append({
                "type": "integration",
                "level": RiskLevel.MEDIUM.value,
                "description": f"New component '{component_name}' may not integrate properly"
            })
        else:
            risks.append({
                "type": "regression",
                "level": RiskLevel.MEDIUM.value,
                "description": f"Modifying '{component_name}' may break existing functionality"
            })

        # Create chunk
        chunk = WorkChunk(
            id=chunk_id,
            description=f"{action.capitalize()} component: {component_name}",
            component=component_name,
            files_affected=files_affected,
            requirements=requirements,
            acceptance_criteria=acceptance_criteria,
            validation_method="llm_review",
            dependencies=[],  # Will be updated later
            risks=risks,
            estimated_complexity=self._estimate_complexity(component_name, action, current_state),
            estimated_duration_minutes=self._estimate_duration(component_name, action)
        )

        return chunk

    def _estimate_complexity(self, component_name: str, action: str,
                             current_state: CurrentStateAnalysis) -> str:
        """Estimate complexity of a chunk."""
        if component_name in current_state.components:
            component = current_state.components[component_name]
            if component.complexity_score > 0.7:
                return "complex"
            elif component.complexity_score > 0.4:
                return "moderate"

        return "simple" if action == "create" else "moderate"

    def _estimate_duration(self, component_name: str, action: str) -> int:
        """Estimate duration in minutes."""
        if action == "create":
            return 60  # 1 hour for new component
        else:
            return 90  # 1.5 hours for modification

    def _update_chunk_dependencies(self, chunks: Dict[str, WorkChunk],
                                   strategy: ImplementationStrategy):
        """Update dependencies between chunks based on strategy."""
        # Map component names to chunk IDs
        component_to_chunk = {}
        for chunk_id, chunk in chunks.items():
            component_to_chunk[chunk.component] = chunk_id

        # Update dependencies based on strategy dependencies
        for component, deps in strategy.dependencies.items():
            if component in component_to_chunk:
                chunk_id = component_to_chunk[component]
                chunk = chunks[chunk_id]

                # Convert component dependencies to chunk dependencies
                chunk_deps = []
                for dep in deps:
                    if dep in component_to_chunk:
                        chunk_deps.append(component_to_chunk[dep])

                chunk.dependencies = chunk_deps


# ============================================================================
# IMPLEMENTATION ORCHESTRATOR (MIXED SYNC/ASYNC)
# ============================================================================

class ImplementationOrchestrator:
    """Orchestrates execution of work chunks. MIXED SYNC/ASYNC."""

    def __init__(self, file_operator, change_tracker, focused_validator):
        self.file_operator = file_operator
        self.tracker = change_tracker
        self.validator = focused_validator

    async def execute_chunk(self, chunk: WorkChunk,
                            session: ImplementationSession) -> WorkChunk:
        """Execute a single work chunk."""
        logger.info(f"Executing chunk: {chunk.id} ({chunk.component})")

        # Update status
        chunk.status = ImplementationStatus.IN_PROGRESS
        chunk.started_at = datetime.now()

        try:
            # Generate code using programmatic API
            generated_code = await self._generate_code_for_chunk(chunk, session)
            chunk.generated_code = generated_code
            chunk.status = ImplementationStatus.GENERATED

            # Validate the generated code
            validation_result = await self.validator.validate_chunk(chunk, session)

            if validation_result.overall_status == "passed":
                # Apply changes
                applied_changes = await self.file_operator.apply_changes(chunk, generated_code)
                chunk.applied_changes = applied_changes
                chunk.status = ImplementationStatus.APPLIED

                # Run post-application validation
                post_validation = await self.validator.validate_after_application(chunk, session)
                chunk.validation_results = post_validation

                if post_validation.get("passed", False):
                    chunk.status = ImplementationStatus.VALIDATED
                    chunk.completed_at = datetime.now()
                    if chunk.started_at:
                        duration = (chunk.completed_at - chunk.started_at).total_seconds()
                        chunk.actual_duration_minutes = int(duration / 60)
                else:
                    chunk.status = ImplementationStatus.FAILED
                    chunk.error_message = "Post-application validation failed"
            else:
                chunk.status = ImplementationStatus.FAILED
                chunk.feedback.append({
                    "type": "validation_failed",
                    "details": validation_result.failed_criteria,
                    "timestamp": datetime.now()
                })
                chunk.error_message = "Pre-application validation failed"

        except Exception as e:
            logger.error(f"Failed to execute chunk {chunk.id}: {e}")
            chunk.status = ImplementationStatus.FAILED
            chunk.retry_count += 1
            chunk.feedback.append({
                "type": "execution_error",
                "error": str(e),
                "timestamp": datetime.now()
            })
            chunk.error_message = str(e)

        # Track in change tracker
        await self.tracker.record_chunk_execution(chunk)

        return chunk

    async def _generate_code_for_chunk(self, chunk: WorkChunk,
                                       session: ImplementationSession) -> str:
        """Generate code for a chunk using LLM."""
        # This would call the programmatic API
        # Simplified for now
        return f"# Generated code for {chunk.component}\n# TODO: Implement actual generation"


# ============================================================================
# MAIN ENGINE CLASS (MIXED SYNC/ASYNC)
# ============================================================================

class ArchitecturalReasoningEngine:
    """
    Main engine orchestrating the entire reasoning process.

    SYNC methods: setup, analysis, planning
    ASYNC methods: API calls, execution
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.client = None
        self.state_analyzer = None
        self.vision_creator = None
        self.strategy_planner = None
        self.work_chunker = None
        self.learning_engine = None
        self.validator = None
        self.orchestrator = None
        self.file_operator = None
        self.change_tracker = None

        # Session management
        self.active_sessions: Dict[str, ImplementationSession] = {}
        self.sessions_dir = Path("storage/sessions")
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"ArchitecturalReasoningEngine initialized with config: {config_path}")

    async def initialize(self):
        """Async initialization (API client and async components)."""
        logger.info("Initializing ArchitecturalReasoningEngine...")

        # Initialize API client (async)
        self.client = DeepSeekClient(self.config_path)

        # Initialize existing modules (sync)
        self.state_analyzer = StateAnalyzer(SnapshotLoader(), FileLoader())

        # Initialize new components (sync)
        self.vision_creator = VisionCreator(self.client)
        self.strategy_planner = StrategyPlanner()
        self.work_chunker = WorkChunker()

        # Initialize learning engine (sync)
        self.learning_engine = LearningEngine()

        # Initialize validator (sync, may have async methods)
        self.validator = FocusedValidator()

        # Note: FileOperator and ChangeTracker will be initialized when needed
        # They require specific dependencies

        logger.info("ArchitecturalReasoningEngine initialized successfully")

    # ============================================================================
    # SESSION MANAGEMENT (SYNC)
    # ============================================================================

    def start_session_sync(self, requirements: str, snapshot_dir: str,
                           session_id: Optional[str] = None) -> ImplementationSession:
        """
        Start a new implementation session. SYNC.

        Creates session with initial analysis, applies learnings,
        but doesn't create vision yet (that's async).
        """
        if not session_id:
            session_id = f"session_{uuid.uuid4().hex[:8]}"

        logger.info(f"Starting implementation session: {session_id}")

        # 1. Analyze current state (sync)
        current_state = self.state_analyzer.analyze_snapshot(snapshot_dir)

        # 2. Create initial session with just analysis
        session = ImplementationSession(
            session_id=session_id,
            vision=None,  # Will be created async
            strategy=None,  # Will be created after vision
            work_chunks={},
            current_state=current_state,
            status="analyzed",
            tags=["new", "unplanned"],
            metadata={
                "requirements": requirements,
                "snapshot_dir": snapshot_dir,
                "started_at": datetime.now().isoformat()
            }
        )

        # 3. Apply relevant learnings (sync)
        applied_learnings = self.learning_engine.apply_to_session(session)
        session.applied_learnings = applied_learnings

        # 4. Save initial session
        self._save_session_sync(session)
        self.active_sessions[session_id] = session

        logger.info(f"Session {session_id} started with {len(current_state.components)} components analyzed")
        return session

    async def create_vision_for_session(self, session_id: str,
                                        user_feedback: Optional[str] = None) -> SolutionVision:
        """
        Create vision for an existing session. ASYNC.

        Requires API call to DeepSeek.
        """
        session = self.active_sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        logger.info(f"Creating vision for session: {session_id}")

        # Get requirements from session metadata
        requirements = session.metadata.get("requirements", "No requirements specified")

        # Create vision (async - API call)
        vision = await self.vision_creator.create_vision(
            requirements, session.current_state, user_feedback
        )

        # Update session with vision
        session.vision = vision
        session.status = "vision_created"
        session.updated_at = datetime.now()

        # Save updated session
        self._save_session_sync(session)

        logger.info(f"Vision created for session {session_id}: {vision.id}")
        return vision

    def create_strategy_for_session(self, session_id: str) -> ImplementationStrategy:
        """
        Create implementation strategy for a session with vision. SYNC.
        """
        session = self.active_sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        if not session.vision:
            raise ValueError(f"Session {session_id} has no vision. Create vision first.")

        logger.info(f"Creating strategy for session: {session_id}")

        # Create strategy (sync)
        strategy = self.strategy_planner.create_strategy(
            session.vision, session.current_state
        )

        # Update session with strategy
        session.strategy = strategy
        session.status = "strategy_created"
        session.updated_at = datetime.now()

        # Save updated session
        self._save_session_sync(session)

        logger.info(f"Strategy created for session {session_id}")
        return strategy

    def create_work_chunks_for_session(self, session_id: str) -> Dict[str, WorkChunk]:
        """
        Create work chunks for a session with strategy. SYNC.
        """
        session = self.active_sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        if not session.strategy:
            raise ValueError(f"Session {session_id} has no strategy. Create strategy first.")

        logger.info(f"Creating work chunks for session: {session_id}")

        # Create work chunks (sync)
        work_chunks = self.work_chunker.chunk_strategy(
            session.strategy, session.current_state
        )

        # Update session with work chunks
        session.work_chunks = work_chunks
        session.status = "chunks_created"
        session.updated_at = datetime.now()

        # Save updated session
        self._save_session_sync(session)

        logger.info(f"Created {len(work_chunks)} work chunks for session {session_id}")
        return work_chunks

    # ============================================================================
    # EXECUTION (ASYNC)
    # ============================================================================

    async def execute_session(self, session_id: str) -> ImplementationSession:
        """Execute an implementation session. ASYNC."""
        session = self.active_sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        if not session.work_chunks:
            raise ValueError(f"Session {session_id} has no work chunks. Create chunks first.")

        logger.info(f"Executing session: {session_id} with {len(session.work_chunks)} chunks")

        session.status = "executing"
        session.updated_at = datetime.now()

        # Initialize orchestrator if needed
        if not self.orchestrator:
            await self._initialize_orchestrator()

        # Get execution order from strategy
        execution_order = self._determine_chunk_execution_order(session)

        # Execute chunks in order
        for chunk_id in execution_order:
            chunk = session.work_chunks[chunk_id]

            # Check dependencies are satisfied
            if not self._check_dependencies_satisfied(chunk, session):
                logger.warning(f"Chunk {chunk_id} blocked by dependencies: {chunk.dependencies}")
                chunk.status = ImplementationStatus.BLOCKED
                continue

            # Execute chunk (async)
            logger.info(f"Executing chunk {chunk_id}: {chunk.description}")
            updated_chunk = await self.orchestrator.execute_chunk(chunk, session)
            session.work_chunks[chunk_id] = updated_chunk

            # Save progress
            session.updated_at = datetime.now()
            self._save_session_sync(session)

            # If chunk failed, we may need to adjust strategy
            if updated_chunk.status == ImplementationStatus.FAILED:
                logger.error(f"Chunk {chunk_id} failed: {updated_chunk.error_message}")
                session.status = "needs_review"
                break

        # Update session status
        completed_chunks = sum(1 for c in session.work_chunks.values()
                               if c.status == ImplementationStatus.VALIDATED)
        total_chunks = len(session.work_chunks)

        if completed_chunks == total_chunks:
            session.status = "completed"
            logger.info(f"Session {session_id} completed successfully")
        elif any(c.status == ImplementationStatus.FAILED for c in session.work_chunks.values()):
            session.status = "failed"
            logger.warning(f"Session {session_id} failed")
        else:
            session.status = "partially_completed"
            logger.info(f"Session {session_id} partially completed: {completed_chunks}/{total_chunks}")

        session.updated_at = datetime.now()
        self._save_session_sync(session)

        return session

    async def validate_session(self, session_id: str) -> ValidationResult:
        """Validate completed session against original vision. ASYNC."""
        session = self.active_sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        logger.info(f"Validating session: {session_id}")

        # Collect all chunk validations
        chunk_reports = []
        for chunk in session.work_chunks.values():
            report = await self.validator.validate_chunk(chunk, session)
            chunk_reports.append(report)

        # Create overall validation report
        overall_report = ValidationResult(
            validation_id=f"validation_{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            validation_level=ValidationLevel.COMPREHENSIVE,
            criteria_checked=[],
            passed_criteria=[],
            failed_criteria=[],
            warnings=[],
            issues_found=[],
            suggestions=[],
            architectural_integrity_check={},
            new_risks_identified=[],
            overall_status="pending",
            confidence_score=0.0
        )

        # Aggregate results
        for report in chunk_reports:
            overall_report.criteria_met.extend(report.criteria_met)
            overall_report.criteria_failed.extend(report.criteria_failed)
            overall_report.new_risks_identified.extend(report.new_risks_identified)
            overall_report.suggestions.extend(report.suggestions)

            # Collect warnings and issues
            overall_report.warnings.extend(report.warnings)
            overall_report.issues_found.extend(report.issues_found)

        # Determine overall status
        if all(r.overall_status == "passed" for r in chunk_reports):
            overall_report.overall_status = "passed"
            overall_report.confidence_score = 0.9
        elif any(r.overall_status == "failed" for r in chunk_reports):
            overall_report.overall_status = "failed"
            overall_report.confidence_score = 0.3
        else:
            overall_report.overall_status = "partial"
            overall_report.confidence_score = 0.6

        # Add session to validation history
        session.validation_history.append(overall_report.to_dict())
        session.updated_at = datetime.now()
        self._save_session_sync(session)

        # Capture learnings from validation
        self.learning_engine.capture_from_validation(session, overall_report)

        logger.info(f"Session {session_id} validation: {overall_report.overall_status}")
        return overall_report

    # ============================================================================
    # ITERATION & FEEDBACK (MIXED)
    # ============================================================================

    async def handle_iteration(self, session_id: str,
                               feedback: Dict[str, Any]) -> IterationPlan:
        """Handle feedback and create iteration plan. MIXED."""
        session = self.active_sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        logger.info(f"Handling iteration for session: {session_id}")

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
            estimated_effort=self._estimate_iteration_effort(session, issues),
            learnings_applied=self.learning_engine.get_relevant_learnings(session),
            root_cause_analysis=self._analyze_root_causes(issues),
            prevention_strategies=self._suggest_prevention_strategies(issues)
        )

        # Update session iteration
        session.iteration += 1
        session.status = f"iterating_{session.iteration}"
        session.updated_at = datetime.now()
        self._save_session_sync(session)

        logger.info(f"Created iteration plan for session {session_id}")
        return iteration_plan

    # ============================================================================
    # SESSION PERSISTENCE (SYNC)
    # ============================================================================

    def _save_session_sync(self, session: ImplementationSession) -> None:
        """Save session to JSON file. SYNC."""
        session_path = self.sessions_dir / f"{session.session_id}.json"

        try:
            # Convert to dict using our EnhancedJSONEncoder logic
            session_dict = session.to_dict()

            # Write to file
            with open(session_path, 'w', encoding='utf-8') as f:
                json.dump(session_dict, f, indent=2, default=str)

            logger.debug(f"Session saved: {session_path}")
        except Exception as e:
            logger.error(f"Failed to save session {session.session_id}: {e}")

    def load_session_sync(self, session_id: str) -> ImplementationSession:
        """Load session from JSON file. SYNC."""
        session_path = self.sessions_dir / f"{session_id}.json"

        if not session_path.exists():
            raise FileNotFoundError(f"Session file not found: {session_path}")

        try:
            with open(session_path, 'r', encoding='utf-8') as f:
                session_dict = json.load(f)

            session = ImplementationSession.from_dict(session_dict)
            self.active_sessions[session_id] = session

            logger.info(f"Session loaded: {session_id}")
            return session
        except Exception as e:
            logger.error(f"Failed to load session {session_id}: {e}")
            raise

    def list_sessions_sync(self) -> List[Dict[str, Any]]:
        """List all saved sessions. SYNC."""
        sessions = []

        for session_file in self.sessions_dir.glob("*.json"):
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    session_data = json.load(f)

                sessions.append({
                    'session_id': session_file.stem,
                    'status': session_data.get('status', 'unknown'),
                    'created_at': session_data.get('created_at'),
                    'updated_at': session_data.get('updated_at'),
                    'vision_id': session_data.get('vision', {}).get('id'),
                    'component_count': session_data.get('current_state', {}).get('component_count', 0)
                })
            except:
                continue

        # Sort by updated_at descending
        sessions.sort(key=lambda x: x.get('updated_at', ''), reverse=True)
        return sessions

    # ============================================================================
    # HELPER METHODS
    # ============================================================================

    async def _initialize_orchestrator(self):
        """Initialize the orchestrator with its dependencies."""
        # Import here to avoid circular imports
        from assistant.core.programmatic_api import ProgrammaticOrchestrator

        self.orchestrator = ProgrammaticOrchestrator(self)
        await self.orchestrator.initialize()

        # Initialize file operator and change tracker through orchestrator
        self.file_operator = self.orchestrator.file_operator
        self.change_tracker = self.orchestrator.change_tracker

    def _determine_chunk_execution_order(self, session: ImplementationSession) -> List[str]:
        """Determine execution order for chunks."""
        # Simple topological sort based on dependencies
        chunks = session.work_chunks
        visited = set()
        order = []

        def visit(chunk_id):
            if chunk_id in visited:
                return
            visited.add(chunk_id)

            chunk = chunks[chunk_id]
            for dep in chunk.dependencies:
                if dep in chunks:
                    visit(dep)

            order.append(chunk_id)

        for chunk_id in chunks.keys():
            if chunk_id not in visited:
                visit(chunk_id)

        return order

    def _check_dependencies_satisfied(self, chunk: WorkChunk,
                                      session: ImplementationSession) -> bool:
        """Check if all dependencies for a chunk are satisfied."""
        for dep_id in chunk.dependencies:
            if dep_id in session.work_chunks:
                dep_chunk = session.work_chunks[dep_id]
                if dep_chunk.status != ImplementationStatus.VALIDATED:
                    return False
        return True

    def _analyze_issues_from_feedback(self, feedback: Dict[str, Any],
                                      session: ImplementationSession) -> List[Dict[str, Any]]:
        """Analyze issues from user feedback."""
        issues = []

        if 'problems' in feedback:
            for problem in feedback['problems']:
                issues.append({
                    'type': 'problem',
                    'description': problem,
                    'severity': 'medium'
                })

        if 'missing_features' in feedback:
            for feature in feedback['missing_features']:
                issues.append({
                    'type': 'missing_feature',
                    'description': f"Missing: {feature}",
                    'severity': 'high'
                })

        if 'bugs' in feedback:
            for bug in feedback['bugs']:
                issues.append({
                    'type': 'bug',
                    'description': f"Bug: {bug}",
                    'severity': 'critical'
                })

        return issues

    def _identify_chunks_to_redo(self, session: ImplementationSession,
                                 issues: List[Dict[str, Any]]) -> List[str]:
        """Identify chunks that need to be redone."""
        chunks_to_redo = []

        for chunk_id, chunk in session.work_chunks.items():
            if chunk.status in [ImplementationStatus.FAILED, ImplementationStatus.BLOCKED]:
                chunks_to_redo.append(chunk_id)

        return chunks_to_redo

    def _identify_chunks_to_modify(self, session: ImplementationSession,
                                   issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Identify chunks that need modification."""
        chunks_to_modify = []

        # Simplified: modify chunks that had warnings or partial validation
        for chunk_id, chunk in session.work_chunks.items():
            if chunk.validation_results and chunk.validation_results.get('has_warnings'):
                chunks_to_modify.append({
                    'chunk_id': chunk_id,
                    'modifications': 'Address validation warnings',
                    'reason': 'Chunk had warnings during validation'
                })

        return chunks_to_modify

    def _identify_new_chunks_needed(self, session: ImplementationSession,
                                    issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Identify new chunks needed based on feedback."""
        new_chunks = []

        # Check for missing features in feedback
        for issue in issues:
            if issue['type'] == 'missing_feature':
                new_chunks.append({
                    'component': 'new_feature',
                    'description': f"Implement {issue['description']}",
                    'requirements': issue['description'],
                    'estimated_complexity': 'moderate'
                })

        return new_chunks

    def _determine_approach_adjustments(self, session: ImplementationSession,
                                        issues: List[Dict[str, Any]]) -> List[str]:
        """Determine approach adjustments needed."""
        adjustments = []

        # Analyze issues to suggest adjustments
        critical_issues = [i for i in issues if i.get('severity') == 'critical']
        if critical_issues:
            adjustments.append("Re-evaluate architectural approach due to critical issues")

        # Check for recurring patterns in issues
        issue_types = [i['type'] for i in issues]
        if issue_types.count('bug') > 2:
            adjustments.append("Increase testing and validation rigor")

        return adjustments

    def _estimate_iteration_effort(self, session: ImplementationSession,
                                   issues: List[Dict[str, Any]]) -> str:
        """Estimate effort for next iteration."""
        total_issues = len(issues)
        chunks_to_redo = len(self._identify_chunks_to_redo(session, issues))

        if total_issues == 0 and chunks_to_redo == 0:
            return "minor"
        elif total_issues <= 3 or chunks_to_redo <= 2:
            return "moderate"
        else:
            return "significant"

    def _analyze_root_causes(self, issues: List[Dict[str, Any]]) -> Optional[str]:
        """Analyze root causes of issues."""
        if not issues:
            return None

        # Simple root cause analysis
        issue_types = [i['type'] for i in issues]

        if 'bug' in issue_types:
            return "Insufficient testing or validation"
        elif 'missing_feature' in issue_types:
            return "Incomplete requirements analysis"
        elif 'problem' in issue_types:
            return "Implementation didn't match requirements"

        return "Unknown root cause"

    def _suggest_prevention_strategies(self, issues: List[Dict[str, Any]]) -> List[str]:
        """Suggest prevention strategies for future iterations."""
        strategies = []

        issue_types = [i['type'] for i in issues]

        if 'bug' in issue_types:
            strategies.append("Add more comprehensive validation checks")
            strategies.append("Implement automated testing for critical paths")

        if 'missing_feature' in issue_types:
            strategies.append("Improve requirements analysis before implementation")
            strategies.append("Validate acceptance criteria more thoroughly")

        if 'problem' in issue_types:
            strategies.append("Increase frequency of intermediate validations")
            strategies.append("Get earlier feedback on implementation approach")

        return strategies

    # ============================================================================
    # HIGH-LEVEL WORKFLOWS
    # ============================================================================

    async def implement_feature(self, requirements: str, snapshot_dir: str,
                                session_id: Optional[str] = None) -> ImplementationSession:
        """
        End-to-end feature implementation workflow.

        This is the main entry point for programmatic use.
        """
        logger.info(f"Starting feature implementation: {requirements[:50]}...")

        # 1. Start session (sync)
        session = self.start_session_sync(requirements, snapshot_dir, session_id)

        # 2. Create vision (async)
        vision = await self.create_vision_for_session(session.session_id)

        # 3. Create strategy (sync)
        strategy = self.create_strategy_for_session(session.session_id)

        # 4. Create work chunks (sync)
        work_chunks = self.create_work_chunks_for_session(session.session_id)

        # 5. Execute (async)
        session = await self.execute_session(session.session_id)

        # 6. Validate (async)
        validation = await self.validate_session(session.session_id)

        logger.info(f"Feature implementation completed: {session.session_id} - {validation.overall_status}")
        return session

    async def architectural_review(self, snapshot_dir: str) -> CurrentStateAnalysis:
        """
        Perform architectural review without implementation.

        Useful for understanding a codebase.
        """
        logger.info(f"Starting architectural review: {snapshot_dir}")

        # Analyze current state (sync)
        analysis = self.state_analyzer.analyze_snapshot(snapshot_dir)

        # Apply learnings to analysis
        self.learning_engine.apply_to_analysis(analysis)

        logger.info(f"Architectural review completed: {len(analysis.components)} components")
        return analysis


# ============================================================================
# SESSION UTILITIES
# ============================================================================

def load_session(session_id: str, config_path: str = "config.yaml") -> ImplementationSession:
    """
    Utility function to load a session without full engine initialization.
    SYNC.
    """
    engine = ArchitecturalReasoningEngine(config_path)
    return engine.load_session_sync(session_id)


def create_session_summary(session: ImplementationSession) -> Dict[str, Any]:
    """
    Create a summary of a session for reporting.
    SYNC.
    """
    total_chunks = len(session.work_chunks)
    completed_chunks = sum(1 for c in session.work_chunks.values()
                           if c.status == ImplementationStatus.VALIDATED)

    return {
        'session_id': session.session_id,
        'status': session.status,
        'iteration': session.iteration,
        'vision_id': session.vision.id if session.vision else None,
        'components_analyzed': len(session.current_state.components),
        'work_chunks': {
            'total': total_chunks,
            'completed': completed_chunks,
            'failed': sum(1 for c in session.work_chunks.values()
                          if c.status == ImplementationStatus.FAILED),
            'blocked': sum(1 for c in session.work_chunks.values()
                           if c.status == ImplementationStatus.BLOCKED)
        },
        'created_at': session.created_at.isoformat(),
        'updated_at': session.updated_at.isoformat(),
        'duration_minutes': int((session.updated_at - session.created_at).total_seconds() / 60)
    }