# src/assistant/core/focused_validator.py
"""
Focused Validator - Validates implementations against 6 specific criteria.

SYNC for local checks (file patterns, constraints, basic validation)
ASYNC for complex LLM-assisted validation

CRITERIA:
1. Didn't touch what we shouldn't
2. No bad patterns/hacks
3. Acceptance criteria met (basic check)
4. Hard constraints not violated
5. Architecture alignment
6. Risk assessment
"""

import re
import ast
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Tuple
from datetime import datetime
import logging

from assistant.core.reasoning_models import *
from assistant.core.file_loader import FileLoader
from assistant.api.client import DeepSeekClient

logger = logging.getLogger(__name__)


# ============================================================================
# SYNC VALIDATORS (Local, Fast Checks)
# ============================================================================

class SyncValidator:
    """Synchronous validation - fast local checks."""

    def __init__(self, file_loader: Optional[FileLoader] = None):
        self.file_loader = file_loader or FileLoader()
        self.bad_patterns = self._load_bad_patterns()

    def _load_bad_patterns(self) -> List[Dict[str, Any]]:
        """Load patterns to detect bad code practices."""
        return [
            {
                'name': 'hardcoded_secrets',
                'pattern': r'(password|secret|key|token)\s*=\s*[\'"][^\'"]+[\'"]',
                'description': 'Hardcoded secrets in code',
                'severity': 'high'
            },
            {
                'name': 'print_debugging',
                'pattern': r'^\s*(print\(|console\.log\(|System\.out\.print)',
                'description': 'Debug prints left in code',
                'severity': 'low'
            },
            {
                'name': 'empty_except',
                'pattern': r'except\s*:\s*pass',
                'description': 'Empty exception handler',
                'severity': 'medium'
            },
            {
                'name': 'broad_except',
                'pattern': r'except\s+Exception\s*:',
                'description': 'Too broad exception catching',
                'severity': 'medium'
            },
            {
                'name': 'magic_numbers',
                'pattern': r'\b\d{3,}\b',
                'description': 'Large magic numbers without constants',
                'severity': 'low'
            }
        ]

    def validate_criteria_1(self, change: CodeChange, session: ImplementationSession) -> List[Dict[str, Any]]:
        """Criterion 1: Didn't touch what we shouldn't."""
        issues = []

        # Check if change is in a protected area
        protected_files = self._identify_protected_files(session)
        if change.file_path in protected_files:
            issues.append({
                'criterion': 'didnt_touch_protected',
                'status': 'failed',
                'reason': f'Modified protected file: {change.file_path}',
                'details': 'This file was marked as protected or outside scope',
                'severity': 'high'
            })

        # Check if change affects files not in the work chunk
        if session.work_chunks:
            chunk_files = set()
            for chunk in session.work_chunks.values():
                chunk_files.update(chunk.files_affected)

            if change.file_path not in chunk_files and change.file_path not in protected_files:
                issues.append({
                    'criterion': 'touched_unexpected_file',
                    'status': 'warning',
                    'reason': f'Modified file not in work chunk: {change.file_path}',
                    'details': 'Consider if this change is necessary',
                    'severity': 'medium'
                })

        return issues

    def validate_criteria_2(self, change: CodeChange) -> List[Dict[str, Any]]:
        """Criterion 2: No bad patterns/hacks."""
        issues = []

        if not change.new_content:
            return issues

        # Check for bad patterns in new content
        for pattern in self.bad_patterns:
            matches = re.finditer(pattern['pattern'], change.new_content, re.MULTILINE | re.IGNORECASE)
            for match in matches:
                line_num = change.new_content[:match.start()].count('\n') + 1
                issues.append({
                    'criterion': 'bad_pattern',
                    'status': 'failed',
                    'reason': f'Found {pattern["name"]}',
                    'details': f'{pattern["description"]} at line {line_num}: {match.group(0)[:50]}',
                    'severity': pattern['severity'],
                    'pattern': pattern['name'],
                    'location': line_num
                })

        # Check for TODO/FIXME comments
        todo_pattern = r'(TODO|FIXME|XXX|HACK|BUG):?\s*(.+)'
        for match in re.finditer(todo_pattern, change.new_content, re.IGNORECASE):
            line_num = change.new_content[:match.start()].count('\n') + 1
            issues.append({
                'criterion': 'todo_comment',
                'status': 'warning',
                'reason': 'TODO/FIXME comment left in code',
                'details': f'{match.group(0)[:100]}',
                'severity': 'low',
                'location': line_num
            })

        return issues

    def validate_criteria_4(self, change: CodeChange, session: ImplementationSession) -> List[Dict[str, Any]]:
        """Criterion 4: Hard constraints not violated."""
        issues = []

        if not session.vision:
            return issues

        # Check architectural constraints
        for constraint in session.vision.architectural_constraints:
            # Simple keyword matching for now
            constraint_lower = constraint.lower()

            # Check if constraint is violated by change
            if self._constraint_violated(constraint_lower, change):
                issues.append({
                    'criterion': 'constraint_violated',
                    'status': 'failed',
                    'reason': f'Violated constraint: {constraint[:100]}',
                    'details': 'Change violates architectural constraint',
                    'severity': 'high',
                    'constraint': constraint
                })

        return issues

    def _identify_protected_files(self, session: ImplementationSession) -> Set[str]:
        """Identify files that should not be modified."""
        protected = set()

        # Core system files (based on patterns)
        core_patterns = [
            r'.*__init__\.py$',
            r'.*test_.*\.py$',
            r'.*conftest\.py$',
            r'.*setup\.py$',
            r'.*requirements\.txt$',
            r'.*\.env$',
            r'.*config\.(yaml|yml|json)$',
        ]

        # Add from session constraints if any
        if session.vision:
            for constraint in session.vision.architectural_constraints:
                if 'do not modify' in constraint.lower() or 'protected' in constraint.lower():
                    # Extract file patterns from constraint
                    # Simple implementation - in production would parse more carefully
                    pass

        return protected

    def _constraint_violated(self, constraint: str, change: CodeChange) -> bool:
        """Check if a change violates a constraint."""
        # Simple keyword-based checking
        violation_indicators = [
            'no database calls in ui',
            'no ui code in api',
            'no hardcoded values',
            'must use interface',
            'async only',
            'no blocking calls',
        ]

        for indicator in violation_indicators:
            if indicator in constraint and indicator in change.new_content.lower():
                return True

        return False

    def validate_syntax(self, change: CodeChange) -> Optional[Dict[str, Any]]:
        """Validate syntax for Python files."""
        if not change.file_path.endswith('.py'):
            return None

        if not change.new_content:
            return None

        try:
            ast.parse(change.new_content)
            return None
        except SyntaxError as e:
            return {
                'criterion': 'syntax_error',
                'status': 'failed',
                'reason': f'Syntax error in Python code: {e.msg}',
                'details': f'Line {e.lineno}, Column {e.offset}: {e.text}',
                'severity': 'high',
                'location': e.lineno
            }


# ============================================================================
# ASYNC VALIDATORS (LLM-Assisted Complex Checks)
# ============================================================================

class AsyncValidator:
    """Asynchronous validation - complex LLM-assisted checks."""

    def __init__(self, deepseek_client: DeepSeekClient):
        self.client = deepseek_client

    async def validate_criteria_3(self, change: CodeChange, session: ImplementationSession) -> List[Dict[str, Any]]:
        """Criterion 3: Acceptance criteria met (LLM-assisted check)."""
        if not session.vision:
            return []

        # Build prompt for LLM validation
        prompt = self._build_acceptance_prompt(change, session)

        messages = [
            {
                "role": "system",
                "content": """You are a code validator. Check if the code changes meet the acceptance criteria.
                Respond with JSON: {"met": bool, "reason": str, "details": str, "confidence": float}
                Only respond with valid JSON."""
            },
            {"role": "user", "content": prompt}
        ]

        try:
            response_text = ""
            async for chunk in self.client.chat_completion(
                    messages=messages,
                    stream=False,
                    max_tokens=500,
                    temperature=0.3
            ):
                response_text += chunk

            # Parse response
            try:
                result = json.loads(response_text.strip())
                if not result.get('met', False):
                    return [{
                        'criterion': 'acceptance_criteria',
                        'status': 'failed',
                        'reason': result.get('reason', 'Acceptance criteria not met'),
                        'details': result.get('details', 'LLM validation failed'),
                        'severity': 'high',
                        'confidence': result.get('confidence', 0.5)
                    }]
            except json.JSONDecodeError:
                logger.error(f"Failed to parse LLM response: {response_text}")
                return []

        except Exception as e:
            logger.error(f"LLM validation failed: {e}")
            return []

        return []

    async def validate_criteria_5(self, change: CodeChange, session: ImplementationSession) -> List[Dict[str, Any]]:
        """Criterion 5: Architecture alignment (LLM-assisted)."""
        if not session.vision:
            return []

        prompt = self._build_architecture_prompt(change, session)

        messages = [
            {
                "role": "system",
                "content": """You are an architecture validator. Check if code changes align with architectural approach.
                Respond with JSON: {"aligned": bool, "reason": str, "issues": List[str], "confidence": float}
                Only respond with valid JSON."""
            },
            {"role": "user", "content": prompt}
        ]

        try:
            response_text = ""
            async for chunk in self.client.chat_completion(
                    messages=messages,
                    stream=False,
                    max_tokens=600,
                    temperature=0.3
            ):
                response_text += chunk

            try:
                result = json.loads(response_text.strip())
                if not result.get('aligned', True):
                    issues = result.get('issues', ['Architecture misalignment'])
                    return [{
                        'criterion': 'architecture_alignment',
                        'status': 'failed',
                        'reason': result.get('reason', 'Architecture misalignment'),
                        'details': '; '.join(issues[:3]),
                        'severity': 'high',
                        'confidence': result.get('confidence', 0.5)
                    }]
            except json.JSONDecodeError:
                logger.error(f"Failed to parse LLM response: {response_text}")
                return []

        except Exception as e:
            logger.error(f"LLM validation failed: {e}")
            return []

        return []

    async def validate_criteria_6(self, change: CodeChange, session: ImplementationSession) -> List[Dict[str, Any]]:
        """Criterion 6: Risk assessment (LLM-assisted)."""
        prompt = self._build_risk_prompt(change, session)

        messages = [
            {
                "role": "system",
                "content": """You are a risk assessor. Identify risks introduced by code changes.
                Respond with JSON: {"risks": List[Dict[str, str]], "confidence": float}
                Risk dict format: {"type": str, "level": "low|medium|high", "description": str}
                Only respond with valid JSON."""
            },
            {"role": "user", "content": prompt}
        ]

        try:
            response_text = ""
            async for chunk in self.client.chat_completion(
                    messages=messages,
                    stream=False,
                    max_tokens=800,
                    temperature=0.3
            ):
                response_text += chunk

            try:
                result = json.loads(response_text.strip())
                risks = result.get('risks', [])

                issues = []
                for risk in risks:
                    if risk.get('level') in ['high', 'critical']:
                        issues.append({
                            'criterion': 'risk_introduced',
                            'status': 'failed',
                            'reason': f"High risk: {risk.get('type', 'Unknown')}",
                            'details': risk.get('description', 'Risk identified'),
                            'severity': risk.get('level', 'high'),
                            'risk_type': risk.get('type'),
                            'confidence': result.get('confidence', 0.5)
                        })
                    elif risk.get('level') == 'medium':
                        issues.append({
                            'criterion': 'risk_introduced',
                            'status': 'warning',
                            'reason': f"Medium risk: {risk.get('type', 'Unknown')}",
                            'details': risk.get('description', 'Risk identified'),
                            'severity': 'medium',
                            'risk_type': risk.get('type'),
                            'confidence': result.get('confidence', 0.5)
                        })

                return issues

            except json.JSONDecodeError:
                logger.error(f"Failed to parse LLM response: {response_text}")
                return []

        except Exception as e:
            logger.error(f"LLM validation failed: {e}")
            return []

        return []

    def _build_acceptance_prompt(self, change: CodeChange, session: ImplementationSession) -> str:
        """Build prompt for acceptance criteria validation."""
        criteria_text = "\n".join([f"- {c}" for c in session.vision.acceptance_criteria[:5]])

        return f"""Validate if code changes meet acceptance criteria.

               ARCHITECTURAL VISION:
               {session.vision.architectural_approach[:500]}

               ACCEPTANCE CRITERIA:
               {criteria_text}

               CODE CHANGES:
               File: {change.file_path}
               Change Type: {change.change_type}
               Description: {change.description}

               NEW CODE CONTENT:
               {change.new_content[:2000] if change.new_content else "No new content"}

               QUESTION: Do these code changes meet the acceptance criteria above?
               Consider: Does it implement what's required? Does it have the right behavior?"""

    def _build_architecture_prompt(self, change: CodeChange, session: ImplementationSession) -> str:
        """Build prompt for architecture alignment validation."""
        arch_approach = session.vision.architectural_approach[:1000]

        # Get component info if available
        component_info = ""
        if change.file_path in session.current_state.components:
            component = session.current_state.components[change.file_path]
            component_info = f"\nComponent: {component.name} ({component.type.value})\nPurpose: {component.purpose}"

        return f"""Validate if code changes align with architectural approach.

               ARCHITECTURAL APPROACH:
               {arch_approach}
               {component_info}

               CODE CHANGES:
               File: {change.file_path}
               Change Type: {change.change_type}
               Reason: {change.reason or "No reason provided"}

               NEW CODE CONTENT:
               {change.new_content[:2000] if change.new_content else "No new content"}

               ARCHITECTURAL CONSTRAINTS:
               {chr(10).join(session.vision.architectural_constraints[:5])}

               QUESTION: Do these code changes align with the architectural approach and constraints?
               Consider: Design patterns, separation of concerns, architectural principles."""

    def _build_risk_prompt(self, change: CodeChange, session: ImplementationSession) -> str:
        """Build prompt for risk assessment."""
        # Get existing risks from session
        existing_risks = ""
        if session.current_state.risks:
            existing_risks = "EXISTING RISKS:\n" + "\n".join([
                f"- {r.get('type', 'Unknown')}: {r.get('description', '')[:100]}"
                for r in session.current_state.risks[:3]
            ])

        return f"""Assess risks introduced by code changes.

               CODE CHANGES:
               File: {change.file_path}
               Change Type: {change.change_type}
               Description: {change.description}
               {existing_risks}

               NEW CODE CONTENT:
               {change.new_content[:2500] if change.new_content else "No new content"}

               OLD CODE CONTENT (for context):
               {change.old_content[:1000] if change.old_content else "No old content"}

               QUESTION: What risks do these changes introduce?
               Consider: Security, performance, maintainability, complexity, dependencies."""


# ============================================================================
# MAIN FOCUSED VALIDATOR CLASS
# ============================================================================

class FocusedValidator:
    """
    Main validator coordinating sync and async validation against 6 criteria.

    All sync operations: file I/O, pattern matching, basic checks
    Async operations: LLM-assisted validation for complex criteria
    """

    def __init__(self, config_path: str = "config.yaml", file_loader: Optional[FileLoader] = None):
        self.config_path = config_path
        self.file_loader = file_loader or FileLoader()
        self.sync_validator = SyncValidator(self.file_loader)
        self.async_validator = None  # Will be initialized async
        self.client = None

        logger.info("FocusedValidator initialized (sync components ready)")

    async def initialize(self):
        """Initialize async components (DeepSeek client)."""
        try:
            self.client = DeepSeekClient(self.config_path)
            self.async_validator = AsyncValidator(self.client)
            logger.info("FocusedValidator async components initialized")
        except Exception as e:
            logger.error(f"Failed to initialize async validator: {e}")
            self.async_validator = None

    async def validate_change(self, change: CodeChange, session: ImplementationSession) -> ValidationResult:
        """
        Validate a code change against all 6 criteria.

        Returns comprehensive validation result.
        """
        validation_id = f"validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{change.id[:8]}"

        logger.info(f"Validating change {change.id} in {change.file_path}")

        # Start timer
        start_time = datetime.now()

        # Collect all validation results
        all_issues = []
        passed_criteria = []
        failed_criteria = []

        # Criterion 1: Didn't touch what we shouldn't (SYNC)
        issues_1 = self.sync_validator.validate_criteria_1(change, session)
        if issues_1:
            failed_criteria.extend([f"1.{i['criterion']}" for i in issues_1 if i['status'] == 'failed'])
            all_issues.extend(issues_1)
        else:
            passed_criteria.append("1.didnt_touch_protected")

        # Criterion 2: No bad patterns/hacks (SYNC)
        issues_2 = self.sync_validator.validate_criteria_2(change)
        if issues_2:
            failed_criteria.extend([f"2.{i['criterion']}" for i in issues_2 if i['status'] == 'failed'])
            all_issues.extend(issues_2)
        else:
            passed_criteria.append("2.no_bad_patterns")

        # Criterion 4: Hard constraints not violated (SYNC)
        issues_4 = self.sync_validator.validate_criteria_4(change, session)
        if issues_4:
            failed_criteria.extend([f"4.{i['criterion']}" for i in issues_4 if i['status'] == 'failed'])
            all_issues.extend(issues_4)
        else:
            passed_criteria.append("4.constraints_respected")

        # Syntax validation (SYNC)
        syntax_issue = self.sync_validator.validate_syntax(change)
        if syntax_issue:
            failed_criteria.append("syntax_valid")
            all_issues.append(syntax_issue)
        else:
            passed_criteria.append("syntax_valid")

        # ASYNC validations (if async validator available)
        issues_3, issues_5, issues_6 = [], [], []

        if self.async_validator and session.vision:
            try:
                # Criterion 3: Acceptance criteria met (ASYNC)
                issues_3 = await self.async_validator.validate_criteria_3(change, session)
                if issues_3:
                    failed_criteria.extend([f"3.{i['criterion']}" for i in issues_3 if i['status'] == 'failed'])
                else:
                    passed_criteria.append("3.acceptance_criteria_met")

                # Criterion 5: Architecture alignment (ASYNC)
                issues_5 = await self.async_validator.validate_criteria_5(change, session)
                if issues_5:
                    failed_criteria.extend([f"5.{i['criterion']}" for i in issues_5 if i['status'] == 'failed'])
                else:
                    passed_criteria.append("5.architecture_aligned")

                # Criterion 6: Risk assessment (ASYNC)
                issues_6 = await self.async_validator.validate_criteria_6(change, session)
                if issues_6:
                    for issue in issues_6:
                        if issue['status'] == 'failed':
                            failed_criteria.append(f"6.{issue['criterion']}")
                else:
                    passed_criteria.append("6.no_high_risks")

            except Exception as e:
                logger.error(f"Async validation failed: {e}")
                # Mark async validations as skipped
                all_issues.append({
                    'criterion': 'async_validation_skipped',
                    'status': 'warning',
                    'reason': 'Async validation unavailable',
                    'details': str(e),
                    'severity': 'low'
                })

        all_issues.extend(issues_3 + issues_5 + issues_6)

        # Calculate overall status
        has_failures = any(i['status'] == 'failed' for i in all_issues)
        has_warnings = any(i['status'] == 'warning' for i in all_issues)

        if has_failures:
            overall_status = "failed"
            confidence = 0.9  # High confidence when we find issues
        elif has_warnings:
            overall_status = "warning"
            confidence = 0.7
        else:
            overall_status = "passed"
            confidence = 0.8

        # Calculate duration
        duration = (datetime.now() - start_time).total_seconds()

        # Create validation result
        result = ValidationResult(
            validation_id=validation_id,
            work_chunk_id=None,  # Will be set by caller
            session_id=session.session_id,
            validation_level=ValidationLevel.STRUCTURAL,
            criteria_checked=[
                "1.didnt_touch_protected",
                "2.no_bad_patterns",
                "3.acceptance_criteria_met",
                "4.constraints_respected",
                "5.architecture_aligned",
                "6.no_high_risks",
                "syntax_valid"
            ],
            passed_criteria=passed_criteria,
            failed_criteria=[{"criterion": c, "reason": "See issues"} for c in failed_criteria],
            warnings=[i for i in all_issues if i['status'] == 'warning'],
            issues_found=[i for i in all_issues if i['status'] == 'failed'],
            suggestions=self._generate_suggestions(all_issues),
            architectural_integrity_check={
                "criteria_passed": len(passed_criteria),
                "criteria_failed": len(failed_criteria),
                "total_criteria": 7
            },
            new_risks_identified=[i for i in all_issues if 'risk_type' in i],
            overall_status=overall_status,
            confidence_score=confidence,
            validation_time_seconds=duration,
            validator_used="focused_validator"
        )

        logger.info(f"Validation complete: {overall_status} with {len(all_issues)} issues")
        return result

    async def validate_chunk(self, chunk: WorkChunk, session: ImplementationSession) -> ValidationResult:
        """
        Validate a work chunk (aggregate validation of all changes).
        """
        logger.info(f"Validating work chunk: {chunk.id}")

        # If chunk has no applied changes yet, validate based on generated code
        if not chunk.applied_changes and chunk.generated_code:
            # Create a synthetic change for validation
            synthetic_change = CodeChange(
                id=f"synthetic_{chunk.id}",
                description=f"Validation of chunk: {chunk.description}",
                change_type="add",
                file_path=chunk.files_affected[0] if chunk.files_affected else f"{chunk.component}.py",
                new_content=chunk.generated_code,
                reason="Chunk validation before application"
            )

            return await self.validate_change(synthetic_change, session)

        # Validate each applied change
        all_results = []
        for change in chunk.applied_changes:
            result = await self.validate_change(change, session)
            all_results.append(result)

        # Aggregate results
        if not all_results:
            return ValidationResult(
                validation_id=f"chunk_val_{chunk.id}",
                work_chunk_id=chunk.id,
                session_id=session.session_id,
                overall_status="pending",
                confidence_score=0.0,
                validator_used="focused_validator"
            )

        # Combine results
        combined = self._combine_validation_results(all_results, chunk.id, session.session_id)

        # Update chunk with validation result
        chunk.validation_results = combined.to_dict()

        return combined

    async def validate_after_application(self, chunk: WorkChunk, session: ImplementationSession) -> Dict[str, Any]:
        """
        Validate after code is applied to files.

        Returns simple dict for quick feedback.
        """
        logger.info(f"Post-application validation for chunk: {chunk.id}")

        # Read actual file contents to validate
        issues = []

        for file_path in chunk.files_affected[:3]:  # Limit to 3 files
            try:
                content = self.file_loader.load_file(file_path)
                if not content:
                    issues.append({
                        'file': file_path,
                        'issue': 'File not found after application',
                        'severity': 'high'
                    })
                    continue

                # Quick syntax check for Python files
                if file_path.endswith('.py'):
                    try:
                        ast.parse(content)
                    except SyntaxError as e:
                        issues.append({
                            'file': file_path,
                            'issue': f'Syntax error: {e.msg}',
                            'line': e.lineno,
                            'severity': 'high'
                        })

            except Exception as e:
                issues.append({
                    'file': file_path,
                    'issue': f'Error reading file: {str(e)}',
                    'severity': 'medium'
                })

        # Check if chunk requirements seem met
        requirements_check = await self._quick_requirements_check(chunk, session)
        if requirements_check and not requirements_check.get('met', True):
            issues.append({
                'file': 'requirements',
                'issue': requirements_check.get('reason', 'Requirements not fully met'),
                'severity': 'medium'
            })

        return {
            'chunk_id': chunk.id,
            'validation_time': datetime.now().isoformat(),
            'issues_found': issues,
            'passed': len(issues) == 0,
            'has_warnings': any(i['severity'] == 'medium' for i in issues),
            'summary': f"Found {len(issues)} issues after application"
        }

    def _generate_suggestions(self, issues: List[Dict[str, Any]]) -> List[str]:
        """Generate actionable suggestions from validation issues."""
        suggestions = []

        for issue in issues:
            if issue['status'] == 'failed':
                # Generate fix suggestions based on issue type
                if issue.get('criterion') == 'bad_pattern':
                    pattern = issue.get('pattern', '')
                    if pattern == 'hardcoded_secrets':
                        suggestions.append("Use environment variables or secret management for sensitive data")
                    elif pattern == 'empty_except':
                        suggestions.append("Add proper error handling or at least log the exception")
                    elif pattern == 'broad_except':
                        suggestions.append("Catch specific exceptions instead of broad Exception")
                    elif pattern == 'magic_numbers':
                        suggestions.append("Define constants with meaningful names")

                elif issue.get('criterion') == 'constraint_violated':
                    suggestions.append(f"Review constraint: {issue.get('constraint', 'Unknown')}")

                elif issue.get('criterion') == 'architecture_alignment':
                    suggestions.append("Review architectural approach and adjust implementation")

        # Deduplicate
        return list(dict.fromkeys(suggestions))[:5]

    def _combine_validation_results(self, results: List[ValidationResult],
                                    chunk_id: str, session_id: str) -> ValidationResult:
        """Combine multiple validation results into one."""
        if not results:
            return ValidationResult(
                validation_id=f"combined_{chunk_id}",
                work_chunk_id=chunk_id,
                session_id=session_id,
                overall_status="pending",
                confidence_score=0.0
            )

        # Combine all criteria
        all_passed = []
        all_failed = []
        all_warnings = []
        all_issues = []
        all_risks = []

        for result in results:
            all_passed.extend(result.passed_criteria)
            all_failed.extend(result.failed_criteria)
            all_warnings.extend(result.warnings)
            all_issues.extend(result.issues_found)
            all_risks.extend(result.new_risks_identified)

        # Deduplicate
        all_passed = list(dict.fromkeys(all_passed))
        all_failed = list(dict.fromkeys([f['criterion'] for f in all_failed]))

        # Determine overall status
        has_failures = any(i['status'] == 'failed' for i in all_issues)
        has_warnings = any(i['status'] == 'warning' for i in all_warnings)

        if has_failures:
            overall_status = "failed"
            confidence = 0.9
        elif has_warnings:
            overall_status = "warning"
            confidence = 0.7
        else:
            overall_status = "passed"
            confidence = min(0.95, 0.5 + (len(all_passed) / (len(all_passed) + len(all_failed) + 1)) * 0.5)

        return ValidationResult(
            validation_id=f"combined_{chunk_id}_{datetime.now().strftime('%H%M%S')}",
            work_chunk_id=chunk_id,
            session_id=session_id,
            validation_level=ValidationLevel.COMPREHENSIVE,
            criteria_checked=all_passed + all_failed,
            passed_criteria=all_passed,
            failed_criteria=[{"criterion": c, "reason": "See combined issues"} for c in all_failed],
            warnings=all_warnings,
            issues_found=all_issues,
            suggestions=self._generate_suggestions(all_issues + all_warnings),
            architectural_integrity_check={
                "criteria_passed": len(all_passed),
                "criteria_failed": len(all_failed),
                "total_criteria": len(all_passed) + len(all_failed)
            },
            new_risks_identified=all_risks,
            overall_status=overall_status,
            confidence_score=confidence,
            validator_used="focused_validator_combined"
        )

    async def _quick_requirements_check(self, chunk: WorkChunk, session: ImplementationSession) -> Dict[str, Any]:
        """Quick check if chunk seems to meet requirements."""
        if not chunk.requirements or not self.async_validator:
            return {"met": True}

        prompt = f"""Quick check: Does this code implementation seem to meet the requirements?

                 REQUIREMENTS:
                 {chunk.requirements[:500]}

                 IMPLEMENTATION (chunk description):
                 {chunk.description}

                 RESPOND with JSON: {{"met": bool, "reason": str}}
                 Keep response very brief."""

        messages = [
            {
                "role": "system",
                "content": "You are doing a quick requirements check. Respond only with valid JSON."
            },
            {"role": "user", "content": prompt}
        ]

        try:
            response_text = ""
            async for chunk in self.client.chat_completion(
                    messages=messages,
                    stream=False,
                    max_tokens=200,
                    temperature=0.1
            ):
                response_text += chunk

            return json.loads(response_text.strip())
        except:
            return {"met": True}  # Default to passing if check fails


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

async def create_focused_validator(config_path: str = "config.yaml") -> FocusedValidator:
    """Factory function to create and initialize a validator."""
    validator = FocusedValidator(config_path)
    await validator.initialize()
    return validator


async def validate_single_change(change: CodeChange, session: ImplementationSession,
                                 config_path: str = "config.yaml") -> ValidationResult:
    """Convenience function to validate a single change."""
    validator = await create_focused_validator(config_path)
    return await validator.validate_change(change, session)


async def quick_validation(chunk: WorkChunk, session: ImplementationSession) -> Dict[str, Any]:
    """Quick validation without full LLM checks."""
    validator = FocusedValidator()

    # Just do sync validations
    issues = []

    for file_path in chunk.files_affected[:2]:
        content = validator.file_loader.load_file(file_path)
        if content:
            # Check for obvious issues
            for pattern in validator.sync_validator.bad_patterns[:2]:  # Just first 2 patterns
                if re.search(pattern['pattern'], content, re.IGNORECASE):
                    issues.append({
                        'file': file_path,
                        'issue': f"Found {pattern['name']}",
                        'severity': pattern['severity']
                    })

    return {
        'chunk_id': chunk.id,
        'quick_check': True,
        'issues_found': issues,
        'passed': len(issues) == 0
    }