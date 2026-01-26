# src/assistant/core/learning_engine.py
"""
Learning Engine - captures and applies insights from implementation sessions.

All sync - JSON file operations, pattern matching, learning application.
No async operations needed.

Principles:
1. Simple JSON storage (append-only)
2. Learning relevance based on keyword similarity, not complex ML
3. Capture concrete insights, not vague observations
4. Learning application is advisory, not prescriptive
"""

import json
import uuid
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Tuple
from datetime import datetime
from dataclasses import asdict
import re
from collections import defaultdict

from assistant.core.reasoning_models import *

logger = logging.getLogger(__name__)


# ============================================================================
# LEARNING STORAGE MANAGER
# ============================================================================

class LearningStorage:
    """Manages storage and retrieval of learning points in JSON files."""

    def __init__(self, storage_dir: str = "storage/learnings"):
        self.storage_path = Path(storage_dir)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # Primary learnings file
        self.learnings_file = self.storage_path / "learnings.json"

        # Index files for faster lookup
        self.category_index_file = self.storage_path / "category_index.json"
        self.keyword_index_file = self.storage_path / "keyword_index.json"

        # In-memory cache
        self.learnings_cache: List[LearningPoint] = []
        self.category_index: Dict[str, List[str]] = {}  # category -> learning_ids
        self.keyword_index: Dict[str, List[str]] = {}   # keyword -> learning_ids

        # Load existing learnings
        self._load_all_learnings()

        logger.info(f"LearningStorage initialized with {len(self.learnings_cache)} learnings")

    def _load_all_learnings(self):
        """Load all learnings from storage."""
        try:
            if self.learnings_file.exists():
                with open(self.learnings_file, 'r', encoding='utf-8') as f:
                    learnings_data = json.load(f)

                self.learnings_cache = [
                    LearningPoint.from_dict(data) for data in learnings_data
                ]
                logger.debug(f"Loaded {len(self.learnings_cache)} learnings from file")
            else:
                self.learnings_cache = []
                logger.debug("No existing learnings file found")

            # Load or rebuild indexes
            self._load_or_rebuild_indexes()

        except Exception as e:
            logger.error(f"Failed to load learnings: {e}")
            self.learnings_cache = []
            self._rebuild_indexes()

    def _load_or_rebuild_indexes(self):
        """Load indexes from file or rebuild them."""
        try:
            if self.category_index_file.exists() and self.keyword_index_file.exists():
                with open(self.category_index_file, 'r', encoding='utf-8') as f:
                    self.category_index = json.load(f)
                with open(self.keyword_index_file, 'r', encoding='utf-8') as f:
                    self.keyword_index = json.load(f)
                logger.debug("Indexes loaded from file")
            else:
                self._rebuild_indexes()
        except Exception as e:
            logger.error(f"Failed to load indexes, rebuilding: {e}")
            self._rebuild_indexes()

    def _rebuild_indexes(self):
        """Rebuild indexes from learnings cache."""
        self.category_index = defaultdict(list)
        self.keyword_index = defaultdict(list)

        for learning in self.learnings_cache:
            # Index by category
            category_key = learning.category.value
            self.category_index[category_key].append(learning.id)

            # Index by keywords
            for keyword in learning.relevance_keywords:
                self.keyword_index[keyword].append(learning.id)

        self._save_indexes()
        logger.debug("Indexes rebuilt")

    def _save_indexes(self):
        """Save indexes to files."""
        try:
            with open(self.category_index_file, 'w', encoding='utf-8') as f:
                json.dump(self.category_index, f, indent=2)
            with open(self.keyword_index_file, 'w', encoding='utf-8') as f:
                json.dump(self.keyword_index, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save indexes: {e}")

    def save_learning(self, learning: LearningPoint) -> bool:
        """Save a learning point to storage."""
        try:
            # Add to cache
            self.learnings_cache.append(learning)

            # Update indexes
            category_key = learning.category.value
            self.category_index[category_key].append(learning.id)

            for keyword in learning.relevance_keywords:
                self.keyword_index[keyword].append(learning.id)

            # Save to file (append to array)
            if self.learnings_file.exists():
                with open(self.learnings_file, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
            else:
                existing_data = []

            existing_data.append(learning.to_dict())

            with open(self.learnings_file, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, indent=2)

            # Save indexes
            self._save_indexes()

            logger.info(f"Learning saved: {learning.id} - {learning.title}")
            return True

        except Exception as e:
            logger.error(f"Failed to save learning {learning.id}: {e}")
            return False

    def get_learning(self, learning_id: str) -> Optional[LearningPoint]:
        """Get a learning point by ID."""
        for learning in self.learnings_cache:
            if learning.id == learning_id:
                return learning
        return None

    def get_learnings_by_category(self, category: LearningCategory,
                                  limit: int = 10) -> List[LearningPoint]:
        """Get learnings by category."""
        category_key = category.value
        learning_ids = self.category_index.get(category_key, [])

        learnings = []
        for learning_id in learning_ids[:limit]:
            learning = self.get_learning(learning_id)
            if learning:
                learnings.append(learning)

        return learnings

    def get_learnings_by_keyword(self, keyword: str,
                                 limit: int = 10) -> List[LearningPoint]:
        """Get learnings by keyword."""
        learning_ids = self.keyword_index.get(keyword.lower(), [])

        learnings = []
        for learning_id in learning_ids[:limit]:
            learning = self.get_learning(learning_id)
            if learning:
                learnings.append(learning)

        return learnings

    def search_learnings(self, query: str,
                         limit: int = 10) -> List[Tuple[LearningPoint, float]]:
        """Search learnings by relevance to query."""
        query_lower = query.lower()
        query_words = set(re.findall(r'\w+', query_lower))

        scored_learnings = []

        for learning in self.learnings_cache:
            if learning.archived:
                continue

            score = self._calculate_relevance_score(learning, query_words, query_lower)
            if score > 0:
                scored_learnings.append((learning, score))

        # Sort by score descending
        scored_learnings.sort(key=lambda x: x[1], reverse=True)

        return [(learning, score) for learning, score in scored_learnings[:limit]]

    def _calculate_relevance_score(self, learning: LearningPoint,
                                   query_words: Set[str], query_lower: str) -> float:
        """Calculate relevance score between learning and query."""
        score = 0.0

        # Check title
        if learning.title:
            title_lower = learning.title.lower()
            for word in query_words:
                if word in title_lower:
                    score += 3.0

        # Check description
        if learning.description:
            desc_lower = learning.description.lower()
            for word in query_words:
                if word in desc_lower:
                    score += 1.0

        # Check relevance keywords
        for keyword in learning.relevance_keywords:
            keyword_lower = keyword.lower()
            for word in query_words:
                if word in keyword_lower or keyword_lower in query_lower:
                    score += 2.0

        # Check context (component names, patterns, etc.)
        if learning.context:
            context_str = str(learning.context).lower()
            for word in query_words:
                if word in context_str:
                    score += 0.5

        # Apply confidence multiplier
        score *= learning.confidence_score

        return score

    def get_all_learnings(self, include_archived: bool = False) -> List[LearningPoint]:
        """Get all learnings."""
        if include_archived:
            return self.learnings_cache.copy()
        else:
            return [l for l in self.learnings_cache if not l.archived]

    def delete_learning(self, learning_id: str) -> bool:
        """Soft delete a learning (mark as archived)."""
        learning = self.get_learning(learning_id)
        if not learning:
            return False

        learning.archived = True

        # Update in file
        try:
            with open(self.learnings_file, 'r', encoding='utf-8') as f:
                learnings_data = json.load(f)

            for i, data in enumerate(learnings_data):
                if data['id'] == learning_id:
                    learnings_data[i]['archived'] = True
                    break

            with open(self.learnings_file, 'w', encoding='utf-8') as f:
                json.dump(learnings_data, f, indent=2)

            logger.info(f"Learning archived: {learning_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to archive learning {learning_id}: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get learning storage statistics."""
        total = len(self.learnings_cache)
        active = sum(1 for l in self.learnings_cache if not l.archived)

        category_counts = defaultdict(int)
        for learning in self.learnings_cache:
            if not learning.archived:
                category_counts[learning.category.value] += 1

        return {
            'total_learnings': total,
            'active_learnings': active,
            'archived_learnings': total - active,
            'by_category': dict(category_counts),
            'storage_path': str(self.storage_path)
        }


# ============================================================================
# LEARNING EXTRACTOR
# ============================================================================

class LearningExtractor:
    """Extracts learning points from implementation sessions and validation results."""

    def __init__(self):
        pass

    def extract_from_validation(self,
                                session: ImplementationSession,
                                validation_result: ValidationResult) -> List[LearningPoint]:
        """Extract learning points from validation results."""
        learnings = []

        # Extract from failed criteria
        for failed in validation_result.failed_criteria:
            learning = self._extract_from_failed_criterion(failed, session, validation_result)
            if learning:
                learnings.append(learning)

        # Extract from warnings
        for warning in validation_result.warnings:
            learning = self._extract_from_warning(warning, session, validation_result)
            if learning:
                learnings.append(learning)

        # Extract from issues found
        for issue in validation_result.issues_found:
            learning = self._extract_from_issue(issue, session, validation_result)
            if learning:
                learnings.append(learning)

        # Extract from new risks identified
        for risk in validation_result.new_risks_identified:
            learning = self._extract_from_risk(risk, session, validation_result)
            if learning:
                learnings.append(learning)

        # Extract from overall validation status
        if validation_result.overall_status == "passed":
            learning = self._extract_from_success(session, validation_result)
            if learning:
                learnings.append(learning)

        logger.info(f"Extracted {len(learnings)} learning(s) from validation")
        return learnings

    def _extract_from_failed_criterion(self, failed_criterion: Dict[str, Any],
                                       session: ImplementationSession,
                                       validation_result: ValidationResult) -> Optional[LearningPoint]:
        """Extract learning from a failed acceptance criterion."""
        criterion = failed_criterion.get('criterion', 'Unknown criterion')
        reason = failed_criterion.get('reason', 'Unknown reason')

        # Determine category based on reason
        category = self._categorize_failure(reason)

        # Extract keywords from criterion
        keywords = self._extract_keywords(criterion) + self._extract_keywords(reason)

        # Create context
        context = {
            'session_id': session.session_id,
            'validation_id': validation_result.validation_id,
            'criterion': criterion,
            'reason': reason,
            'failed_at': datetime.now().isoformat()
        }

        # Create learning
        learning = LearningPoint(
            id=f"learning_{uuid.uuid4().hex[:8]}",
            category=category,
            title=f"Failed: {criterion[:50]}",
            description=f"Criterion '{criterion}' failed because: {reason}",
            source_session_id=session.session_id,
            source_chunk_id=validation_result.work_chunk_id,
            context=context,
            mistake_to_avoid=f"Don't make the same mistake that caused: {criterion}",
            application_conditions=["Similar criteria in future implementations"],
            confidence_score=0.9,  # High confidence for failures
            relevance_keywords=keywords,
            tags=["failure", "validation", category.value]
        )

        return learning

    def _extract_from_warning(self, warning: Dict[str, Any],
                              session: ImplementationSession,
                              validation_result: ValidationResult) -> Optional[LearningPoint]:
        """Extract learning from a validation warning."""
        warning_type = warning.get('type', 'Unknown warning')
        details = warning.get('details', 'No details')

        # Create context
        context = {
            'session_id': session.session_id,
            'validation_id': validation_result.validation_id,
            'warning_type': warning_type,
            'details': details
        }

        # Extract keywords
        keywords = self._extract_keywords(warning_type) + self._extract_keywords(details)

        learning = LearningPoint(
            id=f"learning_{uuid.uuid4().hex[:8]}",
            category=LearningCategory.VALIDATION,
            title=f"Warning: {warning_type[:50]}",
            description=f"Validation warning: {warning_type}. Details: {details}",
            source_session_id=session.session_id,
            context=context,
            application_conditions=["Similar validation scenarios"],
            confidence_score=0.7,
            relevance_keywords=keywords,
            tags=["warning", "validation"]
        )

        return learning

    def _extract_from_issue(self, issue: Dict[str, Any],
                            session: ImplementationSession,
                            validation_result: ValidationResult) -> Optional[LearningPoint]:
        """Extract learning from a found issue."""
        issue_type = issue.get('type', 'Unknown issue')
        description = issue.get('description', 'No description')
        severity = issue.get('severity', 'medium')

        # Determine category based on issue type
        category = self._categorize_issue(issue_type)

        # Create context
        context = {
            'session_id': session.session_id,
            'validation_id': validation_result.validation_id,
            'issue_type': issue_type,
            'description': description,
            'severity': severity
        }

        # Extract keywords
        keywords = self._extract_keywords(issue_type) + self._extract_keywords(description)

        learning = LearningPoint(
            id=f"learning_{uuid.uuid4().hex[:8]}",
            category=category,
            title=f"Issue: {issue_type[:50]}",
            description=f"Found issue: {issue_type}. Description: {description}. Severity: {severity}",
            source_session_id=session.session_id,
            context=context,
            mistake_to_avoid=f"Avoid issue type: {issue_type}",
            application_conditions=["Similar implementation scenarios"],
            confidence_score=0.8 if severity == 'high' else 0.6,
            relevance_keywords=keywords,
            tags=["issue", severity]
        )

        return learning

    def _extract_from_risk(self, risk: Dict[str, Any],
                           session: ImplementationSession,
                           validation_result: ValidationResult) -> Optional[LearningPoint]:
        """Extract learning from a new risk identified."""
        risk_type = risk.get('type', 'Unknown risk')
        description = risk.get('description', 'No description')
        level = risk.get('level', 'medium')

        # Create context
        context = {
            'session_id': session.session_id,
            'validation_id': validation_result.validation_id,
            'risk_type': risk_type,
            'description': description,
            'level': level
        }

        # Extract keywords
        keywords = self._extract_keywords(risk_type) + self._extract_keywords(description)

        learning = LearningPoint(
            id=f"learning_{uuid.uuid4().hex[:8]}",
            category=LearningCategory.CONSTRAINT,
            title=f"Risk: {risk_type[:50]}",
            description=f"Identified risk: {risk_type}. Description: {description}. Level: {level}",
            source_session_id=session.session_id,
            context=context,
            constraint_discovered=f"Risk to consider: {risk_type}",
            application_conditions=["Future implementations with similar characteristics"],
            confidence_score=0.7,
            relevance_keywords=keywords,
            tags=["risk", level]
        )

        return learning

    def _extract_from_success(self, session: ImplementationSession,
                              validation_result: ValidationResult) -> Optional[LearningPoint]:
        """Extract learning from successful validation."""
        # Only create success learning if validation was comprehensive
        if validation_result.validation_level != ValidationLevel.COMPREHENSIVE:
            return None

        # Create context
        context = {
            'session_id': session.session_id,
            'validation_id': validation_result.validation_id,
            'validation_level': validation_result.validation_level.value,
            'confidence_score': validation_result.confidence_score,
            'criteria_met': len(validation_result.criteria_met)
        }

        # Extract keywords from session vision
        keywords = []
        if session.vision:
            keywords.extend(self._extract_keywords(session.vision.requirements))
            keywords.extend(self._extract_keywords(session.vision.architectural_approach))

        learning = LearningPoint(
            id=f"learning_{uuid.uuid4().hex[:8]}",
            category=LearningCategory.SUCCESS,
            title="Successful comprehensive validation",
            description=f"Session {session.session_id} passed comprehensive validation with {validation_result.confidence_score:.1%} confidence",
            source_session_id=session.session_id,
            context=context,
            success_to_repeat="This implementation approach worked well",
            application_conditions=["Similar requirements and architecture"],
            confidence_score=validation_result.confidence_score,
            relevance_keywords=keywords,
            tags=["success", "validation", "comprehensive"]
        )

        return learning

    def _categorize_failure(self, reason: str) -> LearningCategory:
        """Categorize a failure based on reason."""
        reason_lower = reason.lower()

        if any(word in reason_lower for word in ['architecture', 'pattern', 'design']):
            return LearningCategory.ARCHITECTURE
        elif any(word in reason_lower for word in ['code', 'syntax', 'implementation']):
            return LearningCategory.CODE_PATTERN
        elif any(word in reason_lower for word in ['test', 'validation', 'criteria']):
            return LearningCategory.VALIDATION
        elif any(word in reason_lower for word in ['constraint', 'limit', 'boundary']):
            return LearningCategory.CONSTRAINT
        else:
            return LearningCategory.MISTAKE

    def _categorize_issue(self, issue_type: str) -> LearningCategory:
        """Categorize an issue based on type."""
        issue_lower = issue_type.lower()

        if any(word in issue_lower for word in ['architecture', 'design', 'structure']):
            return LearningCategory.ARCHITECTURE
        elif any(word in issue_lower for word in ['code', 'pattern', 'style']):
            return LearningCategory.CODE_PATTERN
        elif any(word in issue_lower for word in ['security', 'performance', 'scalability']):
            return LearningCategory.BEST_PRACTICE
        else:
            return LearningCategory.MISTAKE

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text."""
        if not isinstance(text, str):
            return []

        # Remove special characters and split
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())

        # Filter out common stop words
        stop_words = {'the', 'and', 'for', 'with', 'this', 'that', 'have', 'from',
                      'which', 'would', 'could', 'should', 'been', 'were', 'what',
                      'when', 'where', 'why', 'how', 'then', 'than', 'their', 'there',
                      'about', 'above', 'after', 'again', 'against', 'all', 'am',
                      'an', 'any', 'are', 'as', 'at', 'be', 'because', 'been',
                      'before', 'being', 'below', 'between', 'both', 'but', 'by',
                      'cannot', 'did', 'do', 'does', 'doing', 'down', 'during',
                      'each', 'few', 'further', 'had', 'has', 'have', 'having',
                      'he', 'her', 'here', 'hers', 'herself', 'him', 'himself',
                      'his', 'if', 'in', 'into', 'is', 'it', 'its', 'itself',
                      'me', 'more', 'most', 'my', 'myself', 'no', 'nor', 'not',
                      'of', 'off', 'on', 'once', 'only', 'or', 'other', 'our',
                      'ours', 'ourselves', 'out', 'over', 'own', 'same', 'she',
                      'so', 'some', 'such', 'than', 'that', 'the', 'their',
                      'theirs', 'them', 'themselves', 'then', 'there', 'these',
                      'they', 'this', 'those', 'through', 'to', 'too', 'under',
                      'until', 'up', 'very', 'was', 'we', 'were', 'what', 'whatever',
                      'when', 'whenever', 'where', 'wherever', 'whether', 'which',
                      'while', 'who', 'whoever', 'whom', 'whose', 'why', 'will',
                      'with', 'within', 'without', 'you', 'your', 'yours', 'yourself',
                      'yourselves'}

        keywords = [word for word in words if word not in stop_words]

        # Limit to unique keywords
        return list(set(keywords))[:10]  # Max 10 keywords

    def extract_from_session_decisions(self, session: ImplementationSession) -> List[LearningPoint]:
        """Extract learning points from session decisions log."""
        learnings = []

        for decision in session.decisions_log:
            learning = self._extract_from_decision(decision, session)
            if learning:
                learnings.append(learning)

        return learnings

    def _extract_from_decision(self, decision: Dict[str, Any],
                               session: ImplementationSession) -> Optional[LearningPoint]:
        """Extract learning from a decision."""
        decision_type = decision.get('type', 'Unknown decision')
        description = decision.get('description', 'No description')
        rationale = decision.get('rationale', 'No rationale')
        outcome = decision.get('outcome', 'unknown')

        # Determine category based on outcome
        if outcome == 'success':
            category = LearningCategory.SUCCESS
        elif outcome == 'failure':
            category = LearningCategory.MISTAKE
        else:
            category = LearningCategory.BEST_PRACTICE

        # Create context
        context = {
            'session_id': session.session_id,
            'decision_type': decision_type,
            'description': description,
            'rationale': rationale,
            'outcome': outcome,
            'timestamp': decision.get('timestamp')
        }

        # Extract keywords
        keywords = (self._extract_keywords(decision_type) +
                    self._extract_keywords(description) +
                    self._extract_keywords(rationale))

        # Determine learning content based on outcome
        if outcome == 'success':
            success_to_repeat = f"Decision '{decision_type}' led to successful outcome"
            title = f"Successful decision: {decision_type[:50]}"
        elif outcome == 'failure':
            mistake_to_avoid = f"Avoid decision type '{decision_type}' that led to failure"
            title = f"Failed decision: {decision_type[:50]}"
        else:
            best_practice_identified = f"Consider decision approach: {decision_type}"
            title = f"Decision: {decision_type[:50]}"

        learning = LearningPoint(
            id=f"learning_{uuid.uuid4().hex[:8]}",
            category=category,
            title=title,
            description=f"Decision: {decision_type}. Description: {description}. Rationale: {rationale}. Outcome: {outcome}.",
            source_session_id=session.session_id,
            context=context,
            success_to_repeat=success_to_repeat if outcome == 'success' else None,
            mistake_to_avoid=mistake_to_avoid if outcome == 'failure' else None,
            best_practice_identified=best_practice_identified if outcome not in ['success', 'failure'] else None,
            application_conditions=["Similar decision scenarios"],
            confidence_score=0.8 if outcome in ['success', 'failure'] else 0.6,
            relevance_keywords=keywords,
            tags=["decision", outcome]
        )

        return learning


# ============================================================================
# LEARNING APPLICATOR
# ============================================================================

class LearningApplicator:
    """Applies relevant learnings to sessions and analyses."""

    def __init__(self, storage: LearningStorage):
        self.storage = storage

    def apply_to_session(self, session: ImplementationSession) -> List[Dict[str, Any]]:
        """
        Apply relevant learnings to a session.

        Returns list of applied learnings with application details.
        """
        applied_learnings = []

        # Get relevant learnings based on session context
        relevant_learnings = self._find_relevant_learnings_for_session(session)

        for learning, relevance_score in relevant_learnings:
            application = self._apply_learning_to_session(learning, session, relevance_score)
            if application:
                applied_learnings.append(application)

                # Update learning stats
                learning.times_applied += 1
                # We'll save this update when the session completes

        logger.info(f"Applied {len(applied_learnings)} learning(s) to session {session.session_id}")
        return applied_learnings

    def apply_to_analysis(self, analysis: CurrentStateAnalysis) -> List[Dict[str, Any]]:
        """
        Apply relevant learnings to an architectural analysis.

        Adds constraints, warnings, or suggestions to the analysis.
        """
        applied_learnings = []

        # Get relevant learnings based on analysis
        relevant_learnings = self._find_relevant_learnings_for_analysis(analysis)

        for learning, relevance_score in relevant_learnings:
            application = self._apply_learning_to_analysis(learning, analysis, relevance_score)
            if application:
                applied_learnings.append(application)

        return applied_learnings

    def _find_relevant_learnings_for_session(self, session: ImplementationSession) -> List[Tuple[LearningPoint, float]]:
        """Find learnings relevant to a session."""
        # Build search query from session context
        query_parts = []

        # Add requirements
        if session.vision:
            query_parts.append(session.vision.requirements)
            query_parts.append(session.vision.architectural_approach)

        # Add component names
        for comp_name in session.current_state.components.keys():
            query_parts.append(comp_name)

        # Add technology stack
        query_parts.extend(session.current_state.tech_stack)

        # Add patterns
        query_parts.extend(session.current_state.patterns)

        query = " ".join(query_parts)

        # Search for relevant learnings
        relevant_learnings = self.storage.search_learnings(query, limit=20)

        # Filter by application conditions if possible
        filtered_learnings = []
        for learning, score in relevant_learnings:
            if self._check_application_conditions(learning, session):
                filtered_learnings.append((learning, score))

        return filtered_learnings[:10]  # Return top 10

    def _find_relevant_learnings_for_analysis(self, analysis: CurrentStateAnalysis) -> List[Tuple[LearningPoint, float]]:
        """Find learnings relevant to an architectural analysis."""
        # Build search query from analysis
        query_parts = []

        # Add overview
        query_parts.append(analysis.overview)

        # Add component names and purposes
        for comp_name, component in analysis.components.items():
            query_parts.append(comp_name)
            query_parts.append(component.purpose)

        # Add technology stack and patterns
        query_parts.extend(analysis.tech_stack)
        query_parts.extend(analysis.patterns)

        # Add strengths and weaknesses
        query_parts.extend(analysis.strengths)
        query_parts.extend(analysis.weaknesses)

        query = " ".join(query_parts)

        # Search for relevant learnings
        return self.storage.search_learnings(query, limit=15)

    def _check_application_conditions(self, learning: LearningPoint,
                                      session: ImplementationSession) -> bool:
        """Check if learning's application conditions are met for this session."""
        if not learning.application_conditions:
            return True

        # Simple keyword matching for now
        conditions_met = 0
        total_conditions = len(learning.application_conditions)

        # Build session context string for matching
        session_context = self._build_session_context_string(session)

        for condition in learning.application_conditions:
            condition_lower = condition.lower()

            # Check if condition appears in session context
            if condition_lower in session_context.lower():
                conditions_met += 1

        # Require at least 50% of conditions to be met
        return conditions_met >= total_conditions * 0.5 if total_conditions > 0 else True

    def _build_session_context_string(self, session: ImplementationSession) -> str:
        """Build a string representation of session context for matching."""
        context_parts = []

        if session.vision:
            context_parts.append(session.vision.requirements)
            context_parts.append(session.vision.architectural_approach)

        for comp_name in session.current_state.components.keys():
            context_parts.append(comp_name)

        context_parts.extend(session.current_state.tech_stack)
        context_parts.extend(session.current_state.patterns)

        return " ".join(context_parts)

    def _apply_learning_to_session(self, learning: LearningPoint,
                                   session: ImplementationSession,
                                   relevance_score: float) -> Optional[Dict[str, Any]]:
        """Apply a learning to a session."""
        application = {
            'learning_id': learning.id,
            'learning_title': learning.title,
            'category': learning.category.value,
            'relevance_score': relevance_score,
            'applied_at': datetime.now().isoformat(),
            'impact': {}
        }

        # Apply based on learning category
        if learning.category == LearningCategory.CONSTRAINT:
            impact = self._apply_constraint_learning(learning, session)
        elif learning.category == LearningCategory.BEST_PRACTICE:
            impact = self._apply_best_practice_learning(learning, session)
        elif learning.category == LearningCategory.MISTAKE:
            impact = self._apply_mistake_learning(learning, session)
        elif learning.category == LearningCategory.SUCCESS:
            impact = self._apply_success_learning(learning, session)
        elif learning.category == LearningCategory.ARCHITECTURE:
            impact = self._apply_architecture_learning(learning, session)
        elif learning.category == LearningCategory.CODE_PATTERN:
            impact = self._apply_code_pattern_learning(learning, session)
        elif learning.category == LearningCategory.VALIDATION:
            impact = self._apply_validation_learning(learning, session)
        else:
            impact = {'type': 'generic', 'message': f'Consider: {learning.description[:100]}...'}

        if not impact:
            return None

        application['impact'] = impact

        # Add to session's applied learnings
        session.applied_learnings.append(application)

        return application

    def _apply_learning_to_analysis(self, learning: LearningPoint,
                                    analysis: CurrentStateAnalysis,
                                    relevance_score: float) -> Optional[Dict[str, Any]]:
        """Apply a learning to an architectural analysis."""
        application = {
            'learning_id': learning.id,
            'learning_title': learning.title,
            'category': learning.category.value,
            'relevance_score': relevance_score,
            'applied_at': datetime.now().isoformat(),
            'impact': {}
        }

        # Add as a constraint or warning to analysis
        if learning.category == LearningCategory.CONSTRAINT and learning.constraint_discovered:
            if 'known_constraints' not in analysis:
                analysis.known_constraints = []
            analysis.known_constraints.append({
                'type': 'learning_constraint',
                'description': learning.constraint_discovered,
                'source': f"Learning: {learning.id}",
                'confidence': learning.confidence_score
            })
            application['impact'] = {'type': 'constraint_added', 'constraint': learning.constraint_discovered}

        elif learning.category == LearningCategory.RISK and 'risk' in learning.context:
            if 'risks' not in analysis:
                analysis.risks = []
            analysis.risks.append({
                'type': 'learning_risk',
                'description': f"Historical risk: {learning.context.get('risk')}",
                'source': f"Learning: {learning.id}",
                'confidence': learning.confidence_score
            })
            application['impact'] = {'type': 'risk_added', 'risk': learning.context.get('risk')}

        else:
            # Generic learning application
            application['impact'] = {'type': 'consideration', 'message': learning.description[:200]}

        return application

    def _apply_constraint_learning(self, learning: LearningPoint,
                                   session: ImplementationSession) -> Dict[str, Any]:
        """Apply a constraint learning."""
        if learning.constraint_discovered:
            # Add to session constraints
            if not session.vision:
                session.vision = create_solution_vision(
                    requirements="",
                    architectural_approach="",
                    chosen_approach_reasoning="",
                    acceptance_criteria=[],
                    architectural_constraints=[]
                )

            session.vision.architectural_constraints.append(
                f"Historical constraint: {learning.constraint_discovered}"
            )

            return {
                'type': 'constraint_added',
                'constraint': learning.constraint_discovered,
                'message': f"Added constraint based on past experience: {learning.constraint_discovered}"
            }

        return {'type': 'generic', 'message': f"Constraint learning applied: {learning.title}"}

    def _apply_best_practice_learning(self, learning: LearningPoint,
                                      session: ImplementationSession) -> Dict[str, Any]:
        """Apply a best practice learning."""
        if learning.best_practice_identified:
            # Add to session decisions log
            session.decisions_log.append({
                'type': 'best_practice_applied',
                'description': f"Applied best practice from learning: {learning.title}",
                'rationale': learning.best_practice_identified,
                'timestamp': datetime.now().isoformat(),
                'source': f"learning:{learning.id}"
            })

            return {
                'type': 'best_practice_applied',
                'practice': learning.best_practice_identified,
                'message': f"Applied best practice: {learning.best_practice_identified}"
            }

        return {'type': 'generic', 'message': f"Best practice considered: {learning.title}"}

    def _apply_mistake_learning(self, learning: LearningPoint,
                                session: ImplementationSession) -> Dict[str, Any]:
        """Apply a mistake learning."""
        if learning.mistake_to_avoid:
            # Add to session decisions log as warning
            session.decisions_log.append({
                'type': 'mistake_warning',
                'description': f"Avoiding mistake from learning: {learning.title}",
                'rationale': learning.mistake_to_avoid,
                'timestamp': datetime.now().isoformat(),
                'source': f"learning:{learning.id}"
            })

            return {
                'type': 'mistake_warning',
                'mistake': learning.mistake_to_avoid,
                'message': f"Warning: Avoid mistake - {learning.mistake_to_avoid}"
            }

        return {'type': 'generic', 'message': f"Mistake to avoid: {learning.title}"}

    def _apply_success_learning(self, learning: LearningPoint,
                                session: ImplementationSession) -> Dict[str, Any]:
        """Apply a success learning."""
        if learning.success_to_repeat:
            # Add to session decisions log
            session.decisions_log.append({
                'type': 'success_pattern_applied',
                'description': f"Repeating success pattern from learning: {learning.title}",
                'rationale': learning.success_to_repeat,
                'timestamp': datetime.now().isoformat(),
                'source': f"learning:{learning.id}"
            })

            return {
                'type': 'success_pattern_applied',
                'pattern': learning.success_to_repeat,
                'message': f"Repeating success pattern: {learning.success_to_repeat}"
            }

        return {'type': 'generic', 'message': f"Success pattern to repeat: {learning.title}"}

    def _apply_architecture_learning(self, learning: LearningPoint,
                                     session: ImplementationSession) -> Dict[str, Any]:
        """Apply an architecture learning."""
        if learning.pattern_recognized:
            # Add pattern to session's current state
            if learning.pattern_recognized not in session.current_state.patterns:
                session.current_state.patterns.append(learning.pattern_recognized)

            return {
                'type': 'pattern_added',
                'pattern': learning.pattern_recognized,
                'message': f"Added architectural pattern: {learning.pattern_recognized}"
            }

        return {'type': 'generic', 'message': f"Architectural consideration: {learning.title}"}

    def _apply_code_pattern_learning(self, learning: LearningPoint,
                                     session: ImplementationSession) -> Dict[str, Any]:
        """Apply a code pattern learning."""
        # Could add to acceptance criteria or validation rules
        return {
            'type': 'code_pattern_considered',
            'message': f"Code pattern to consider: {learning.description[:100]}..."
        }

    def _apply_validation_learning(self, learning: LearningPoint,
                                   session: ImplementationSession) -> Dict[str, Any]:
        """Apply a validation learning."""
        # Could add to validation criteria
        return {
            'type': 'validation_rule_considered',
            'message': f"Validation consideration: {learning.description[:100]}..."
        }

    def update_learning_success(self, learning_id: str, was_successful: bool):
        """Update learning success statistics."""
        learning = self.storage.get_learning(learning_id)
        if not learning:
            return

        if was_successful:
            learning.times_successful += 1

        learning.last_applied = datetime.now()

        # Update confidence based on success rate
        if learning.times_applied > 0:
            success_rate = learning.times_successful / learning.times_applied
            learning.confidence_score = min(0.95, max(0.3, success_rate))

        # Save updated learning
        self.storage.save_learning(learning)


# ============================================================================
# MAIN LEARNING ENGINE CLASS
# ============================================================================

class LearningEngine:
    """
    Main Learning Engine coordinating learning capture and application.

    All sync operations - JSON file I/O, pattern matching, learning application.
    """

    def __init__(self, storage_dir: str = "storage/learnings"):
        self.storage = LearningStorage(storage_dir)
        self.extractor = LearningExtractor()
        self.applicator = LearningApplicator(self.storage)

        logger.info(f"LearningEngine initialized with {len(self.storage.get_all_learnings())} existing learnings")

    # ============================================================================
    # CAPTURE METHODS
    # ============================================================================

    def capture_from_validation(self,
                                session: ImplementationSession,
                                validation_result: ValidationResult):
        """Capture learning points from validation results."""
        learnings = self.extractor.extract_from_validation(session, validation_result)

        for learning in learnings:
            # Add session context if not already present
            if 'session_id' not in learning.context:
                learning.context['session_id'] = session.session_id

            # Add validation context
            learning.context['validation_id'] = validation_result.validation_id
            learning.context['validation_status'] = validation_result.overall_status

            # Save learning
            self.storage.save_learning(learning)

        logger.info(f"Captured {len(learnings)} learning(s) from validation")

        # Also capture from session decisions
        decision_learnings = self.extractor.extract_from_session_decisions(session)
        for learning in decision_learnings:
            self.storage.save_learning(learning)

        logger.info(f"Captured {len(decision_learnings)} learning(s) from decisions")

    def capture_from_session_completion(self, session: ImplementationSession):
        """Capture learning points from completed session."""
        # Extract learnings from final session state
        learnings = []

        # Capture overall session outcome
        if session.status == "completed":
            learning = self._capture_session_success(session)
            if learning:
                learnings.append(learning)
        elif session.status == "failed":
            learning = self._capture_session_failure(session)
            if learning:
                learnings.append(learning)

        # Capture patterns from work chunks
        chunk_learnings = self._capture_chunk_patterns(session)
        learnings.extend(chunk_learnings)

        for learning in learnings:
            self.storage.save_learning(learning)

        logger.info(f"Captured {len(learnings)} learning(s) from session completion")

    def _capture_session_success(self, session: ImplementationSession) -> Optional[LearningPoint]:
        """Capture learning from successful session."""
        context = {
            'session_id': session.session_id,
            'status': session.status,
            'iteration': session.iteration,
            'component_count': len(session.current_state.components),
            'chunk_count': len(session.work_chunks),
            'completed_at': datetime.now().isoformat()
        }

        keywords = []
        if session.vision:
            keywords.extend(self.extractor._extract_keywords(session.vision.requirements))

        learning = LearningPoint(
            id=f"learning_{uuid.uuid4().hex[:8]}",
            category=LearningCategory.SUCCESS,
            title=f"Successful session: {session.session_id}",
            description=f"Session {session.session_id} completed successfully with {len(session.work_chunks)} chunks",
            source_session_id=session.session_id,
            context=context,
            success_to_repeat="Similar sessions likely to succeed",
            application_conditions=["Similar requirements and architecture"],
            confidence_score=0.85,
            relevance_keywords=keywords,
            tags=["session_success", "completion"]
        )

        return learning

    def _capture_session_failure(self, session: ImplementationSession) -> Optional[LearningPoint]:
        """Capture learning from failed session."""
        # Analyze failure reasons
        failed_chunks = [c for c in session.work_chunks.values()
                         if c.status == ImplementationStatus.FAILED]

        failure_reasons = []
        for chunk in failed_chunks[:3]:  # Top 3 failures
            if chunk.error_message:
                failure_reasons.append(chunk.error_message[:100])

        context = {
            'session_id': session.session_id,
            'status': session.status,
            'iteration': session.iteration,
            'failed_chunks': len(failed_chunks),
            'failure_reasons': failure_reasons,
            'failed_at': datetime.now().isoformat()
        }

        keywords = ["failure", "session"]
        if session.vision:
            keywords.extend(self.extractor._extract_keywords(session.vision.requirements))

        learning = LearningPoint(
            id=f"learning_{uuid.uuid4().hex[:8]}",
            category=LearningCategory.MISTAKE,
            title=f"Failed session: {session.session_id}",
            description=f"Session {session.session_id} failed with {len(failed_chunks)} failed chunks. Reasons: {', '.join(failure_reasons[:3])}",
            source_session_id=session.session_id,
            context=context,
            mistake_to_avoid="Avoid similar session setups that led to failure",
            application_conditions=["Similar session configurations"],
            confidence_score=0.9,  # High confidence for failures
            relevance_keywords=keywords,
            tags=["session_failure", "mistake"]
        )

        return learning

    def _capture_chunk_patterns(self, session: ImplementationSession) -> List[LearningPoint]:
        """Capture learning patterns from work chunks."""
        learnings = []

        for chunk_id, chunk in session.work_chunks.items():
            if chunk.status == ImplementationStatus.VALIDATED and chunk.validation_results:
                # Successful chunk pattern
                learning = self._capture_successful_chunk_pattern(chunk, session)
                if learning:
                    learnings.append(learning)

            elif chunk.status == ImplementationStatus.FAILED and chunk.error_message:
                # Failed chunk pattern
                learning = self._capture_failed_chunk_pattern(chunk, session)
                if learning:
                    learnings.append(learning)

        return learnings

    def _capture_successful_chunk_pattern(self, chunk: WorkChunk,
                                          session: ImplementationSession) -> Optional[LearningPoint]:
        """Capture learning from successful work chunk."""
        context = {
            'session_id': session.session_id,
            'chunk_id': chunk.id,
            'component': chunk.component,
            'status': chunk.status.value,
            'complexity': chunk.estimated_complexity,
            'duration_minutes': chunk.actual_duration_minutes,
            'completed_at': chunk.completed_at.isoformat() if chunk.completed_at else None
        }

        keywords = ["success", "chunk", chunk.component.lower()]
        keywords.extend(self.extractor._extract_keywords(chunk.description))

        learning = LearningPoint(
            id=f"learning_{uuid.uuid4().hex[:8]}",
            category=LearningCategory.SUCCESS,
            title=f"Successful chunk: {chunk.component}",
            description=f"Chunk for component '{chunk.component}' completed successfully in {chunk.actual_duration_minutes} minutes",
            source_session_id=session.session_id,
            source_chunk_id=chunk.id,
            context=context,
            success_to_repeat=f"Similar chunks for component '{chunk.component}' likely to succeed",
            application_conditions=[f"Component: {chunk.component}", f"Complexity: {chunk.estimated_complexity}"],
            confidence_score=0.8,
            relevance_keywords=keywords,
            tags=["chunk_success", chunk.component]
        )

        return learning

    def _capture_failed_chunk_pattern(self, chunk: WorkChunk,
                                      session: ImplementationSession) -> Optional[LearningPoint]:
        """Capture learning from failed work chunk."""
        context = {
            'session_id': session.session_id,
            'chunk_id': chunk.id,
            'component': chunk.component,
            'status': chunk.status.value,
            'error_message': chunk.error_message,
            'retry_count': chunk.retry_count,
            'failed_at': datetime.now().isoformat()
        }

        keywords = ["failure", "chunk", chunk.component.lower(), "error"]
        keywords.extend(self.extractor._extract_keywords(chunk.error_message or ""))

        learning = LearningPoint(
            id=f"learning_{uuid.uuid4().hex[:8]}",
            category=LearningCategory.MISTAKE,
            title=f"Failed chunk: {chunk.component}",
            description=f"Chunk for component '{chunk.component}' failed with error: {chunk.error_message}",
            source_session_id=session.session_id,
            source_chunk_id=chunk.id,
            context=context,
            mistake_to_avoid=f"Avoid similar chunk implementations for component '{chunk.component}'",
            application_conditions=[f"Component: {chunk.component}", "Similar error conditions"],
            confidence_score=0.85,
            relevance_keywords=keywords,
            tags=["chunk_failure", chunk.component, "error"]
        )

        return learning

    # ============================================================================
    # APPLICATION METHODS
    # ============================================================================

    def apply_to_session(self, session: ImplementationSession) -> List[Dict[str, Any]]:
        """Apply relevant learnings to a session."""
        return self.applicator.apply_to_session(session)

    def apply_to_analysis(self, analysis: CurrentStateAnalysis) -> List[Dict[str, Any]]:
        """Apply relevant learnings to an architectural analysis."""
        return self.applicator.apply_to_analysis(analysis)

    def get_relevant_learnings(self, session: ImplementationSession,
                               limit: int = 10) -> List[Tuple[LearningPoint, float]]:
        """Get learnings relevant to a session."""
        return self.applicator._find_relevant_learnings_for_session(session)[:limit]

    # ============================================================================
    # QUERY & MANAGEMENT METHODS
    # ============================================================================

    def search_learnings(self, query: str, limit: int = 10) -> List[Tuple[LearningPoint, float]]:
        """Search for learnings by query."""
        return self.storage.search_learnings(query, limit)

    def get_learnings_by_category(self, category: LearningCategory,
                                  limit: int = 10) -> List[LearningPoint]:
        """Get learnings by category."""
        return self.storage.get_learnings_by_category(category, limit)

    def get_learning(self, learning_id: str) -> Optional[LearningPoint]:
        """Get a learning by ID."""
        return self.storage.get_learning(learning_id)

    def get_all_learnings(self, include_archived: bool = False) -> List[LearningPoint]:
        """Get all learnings."""
        return self.storage.get_all_learnings(include_archived)

    def get_stats(self) -> Dict[str, Any]:
        """Get learning engine statistics."""
        return self.storage.get_stats()

    def archive_learning(self, learning_id: str) -> bool:
        """Archive a learning (soft delete)."""
        return self.storage.delete_learning(learning_id)

    def update_learning_success(self, learning_id: str, was_successful: bool):
        """Update learning success statistics."""
        self.applicator.update_learning_success(learning_id, was_successful)

    def export_learnings(self, filepath: Path) -> bool:
        """Export all learnings to a JSON file."""
        try:
            learnings = self.storage.get_all_learnings(include_archived=True)
            learnings_data = [learning.to_dict() for learning in learnings]

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(learnings_data, f, indent=2)

            logger.info(f"Exported {len(learnings)} learnings to {filepath}")
            return True
        except Exception as e:
            logger.error(f"Failed to export learnings: {e}")
            return False

    def import_learnings(self, filepath: Path) -> int:
        """Import learnings from a JSON file."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                learnings_data = json.load(f)

            imported_count = 0
            for data in learnings_data:
                try:
                    learning = LearningPoint.from_dict(data)
                    if self.storage.save_learning(learning):
                        imported_count += 1
                except:
                    continue

            logger.info(f"Imported {imported_count} learnings from {filepath}")
            return imported_count
        except Exception as e:
            logger.error(f"Failed to import learnings: {e}")
            return 0

    def clear_all_learnings(self) -> bool:
        """Clear all learnings (use with caution!)."""
        try:
            # Delete storage files
            if self.storage.learnings_file.exists():
                self.storage.learnings_file.unlink()
            if self.storage.category_index_file.exists():
                self.storage.category_index_file.unlink()
            if self.storage.keyword_index_file.exists():
                self.storage.keyword_index_file.unlink()

            # Clear cache
            self.storage.learnings_cache = []
            self.storage.category_index = {}
            self.storage.keyword_index = {}

            logger.warning("All learnings cleared")
            return True
        except Exception as e:
            logger.error(f"Failed to clear learnings: {e}")
            return False


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def create_learning_engine(storage_dir: Optional[str] = None) -> LearningEngine:
    """Factory function to create a LearningEngine."""
    if storage_dir:
        return LearningEngine(storage_dir)
    return LearningEngine()


def get_learning_stats() -> Dict[str, Any]:
    """Get learning statistics (convenience function)."""
    engine = create_learning_engine()
    return engine.get_stats()


def search_relevant_learnings(query: str, session: Optional[ImplementationSession] = None,
                              limit: int = 10) -> List[Tuple[LearningPoint, float]]:
    """
    Search for learnings relevant to a query or session.

    If session is provided, finds learnings relevant to session context.
    Otherwise, searches by query.
    """
    engine = create_learning_engine()

    if session:
        return engine.get_relevant_learnings(session, limit)
    else:
        return engine.search_learnings(query, limit)


def capture_validation_learnings(session: ImplementationSession,
                                 validation_result: ValidationResult):
    """Capture learnings from validation results (convenience function)."""
    engine = create_learning_engine()
    engine.capture_from_validation(session, validation_result)