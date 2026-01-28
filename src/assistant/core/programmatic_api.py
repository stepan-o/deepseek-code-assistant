# src/assistant/core/programmatic_api.py
"""
Programmatic API - Clean orchestration interface for scripts.

Provides simple, clean API surface for programmatic use of the
Architectural Reasoning Engine.

SYNC/ASYNC: Both interfaces - Async by default, sync wrapper available.
"""

import asyncio
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
import logging

from assistant.core.reasoning_engine import ArchitecturalReasoningEngine
from assistant.core.focused_validator import FocusedValidator, create_focused_validator
from assistant.core.reasoning_models import *
from assistant.core.file_loader import FileLoader
from assistant.core.context_manager import ContextManager

logger = logging.getLogger(__name__)


# ============================================================================
# FILE OPERATOR (Sync file operations)
# ============================================================================

class FileOperator:
    """Handles actual file operations for code changes."""

    def __init__(self, base_path: Optional[Path] = None):
        self.base_path = base_path or Path.cwd()
        self.file_loader = FileLoader(str(self.base_path))
        self.backup_dir = self.base_path / ".assistant_backups"
        self.backup_dir.mkdir(exist_ok=True)

        logger.info(f"FileOperator initialized with base path: {self.base_path}")

    async def apply_changes(self, chunk: WorkChunk, generated_code: str) -> List[Dict[str, Any]]:
        """Apply code changes from a work chunk."""
        applied_changes = []

        if not chunk.files_affected:
            logger.warning(f"Chunk {chunk.id} has no files to affect")
            return applied_changes

        # For now, we'll create or modify the first file
        # In production, this would be more sophisticated
        main_file = chunk.files_affected[0]
        file_path = self.base_path / main_file

        # Ensure directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Read existing content if file exists
        old_content = None
        if file_path.exists():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    old_content = f.read()
            except Exception as e:
                logger.error(f"Failed to read file {file_path}: {e}")
                old_content = ""

        # Create backup
        backup_path = None
        if old_content:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.backup_dir / f"{main_file.replace('/', '_')}_{timestamp}.bak"
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(old_content)

        # Write new content
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(generated_code)

            # Create change record
            change = CodeChange(
                id=f"change_{chunk.id}_{datetime.now().strftime('%H%M%S')}",
                description=f"Applied changes for chunk: {chunk.description}",
                change_type="modify" if old_content else "add",
                file_path=main_file,
                old_content=old_content,
                new_content=generated_code,
                reason=chunk.requirements,
                generated_by="programmatic_api",
                validation_status="pending",
                applied=True,
                applied_at=datetime.now(),
                rollback_path=str(backup_path) if backup_path else None
            )

            chunk.applied_changes.append(change)
            applied_changes.append(change.to_dict())

            logger.info(f"Applied changes to {main_file} ({len(generated_code)} chars)")

        except Exception as e:
            logger.error(f"Failed to write file {file_path}: {e}")
            # Restore from backup if possible
            if backup_path and backup_path.exists():
                try:
                    with open(backup_path, 'r', encoding='utf-8') as f:
                        backup_content = f.read()
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(backup_content)
                    logger.info(f"Restored {main_file} from backup")
                except Exception as restore_error:
                    logger.error(f"Failed to restore from backup: {restore_error}")

        return applied_changes

    def rollback_change(self, change: CodeChange) -> bool:
        """Rollback a single change."""
        if not change.rollback_path:
            logger.warning(f"No rollback path for change {change.id}")
            return False

        backup_path = Path(change.rollback_path)
        if not backup_path.exists():
            logger.error(f"Backup file not found: {backup_path}")
            return False

        try:
            with open(backup_path, 'r', encoding='utf-8') as f:
                backup_content = f.read()

            file_path = self.base_path / change.file_path
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(backup_content)

            logger.info(f"Rolled back change {change.id} on {change.file_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to rollback change {change.id}: {e}")
            return False


# ============================================================================
# CHANGE TRACKER
# ============================================================================

class ChangeTracker:
    """Tracks and records all changes made by the assistant."""

    def __init__(self, storage_dir: str = "storage/changes"):
        self.storage_path = Path(storage_dir)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # Session tracking
        self.active_session = None
        self.changes_log = []

        logger.info(f"ChangeTracker initialized with storage: {self.storage_path}")

    async def record_chunk_execution(self, chunk: WorkChunk):
        """Record execution of a work chunk."""
        chunk_record = {
            'chunk_id': chunk.id,
            'description': chunk.description,
            'status': chunk.status.value,
            'executed_at': datetime.now().isoformat(),
            'duration_minutes': chunk.actual_duration_minutes,
            'changes_count': len(chunk.applied_changes),
            'validation_results': chunk.validation_results
        }

        self.changes_log.append(chunk_record)

        # Save to file
        if self.active_session:
            session_file = self.storage_path / f"{self.active_session}_changes.json"
            try:
                with open(session_file, 'w', encoding='utf-8') as f:
                    json.dump(self.changes_log, f, indent=2, default=str)
            except Exception as e:
                logger.error(f"Failed to save changes log: {e}")

    def start_session_tracking(self, session_id: str):
        """Start tracking changes for a session."""
        self.active_session = session_id
        self.changes_log = []
        logger.info(f"Started change tracking for session: {session_id}")

    def end_session_tracking(self):
        """End tracking for current session."""
        logger.info(f"Ended change tracking for session: {self.active_session}")
        self.active_session = None

    def get_session_summary(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get summary of changes for a session."""
        session_file = self.storage_path / f"{session_id}_changes.json"
        if not session_file.exists():
            return None

        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                changes = json.load(f)

            total_changes = sum(c.get('changes_count', 0) for c in changes)
            successful = sum(1 for c in changes if c.get('status') == 'validated')
            failed = sum(1 for c in changes if c.get('status') == 'failed')

            return {
                'session_id': session_id,
                'total_chunks': len(changes),
                'successful_chunks': successful,
                'failed_chunks': failed,
                'total_changes': total_changes,
                'first_execution': changes[0]['executed_at'] if changes else None,
                'last_execution': changes[-1]['executed_at'] if changes else None
            }
        except Exception as e:
            logger.error(f"Failed to load session summary: {e}")
            return None


# ============================================================================
# MAIN PROGRAMMATIC ORCHESTRATOR
# ============================================================================

class ProgrammaticOrchestrator:
    """
    Main orchestrator for programmatic use of the Architectural Reasoning Engine.

    Provides clean, simple API surface while handling engine lifecycle,
    validation, file operations, and change tracking.
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.engine = None
        self.validator = None
        self.file_operator = None
        self.change_tracker = None

        # Initialize sync components
        self.file_operator = FileOperator()
        self.change_tracker = ChangeTracker()

        logger.info("ProgrammaticOrchestrator initialized (sync components ready)")

    async def initialize(self):
        """Initialize all components (including async ones)."""
        logger.info("Initializing ProgrammaticOrchestrator...")

        # Initialize engine
        self.engine = ArchitecturalReasoningEngine(self.config_path)
        await self.engine.initialize()

        # Initialize validator
        self.validator = await create_focused_validator(self.config_path)

        # Note: file_operator and change_tracker were initialized in __init__

        logger.info("ProgrammaticOrchestrator fully initialized")

    # ============================================================================
    # HIGH-LEVEL API METHODS
    # ============================================================================

    async def implement_feature(self, requirements: str, snapshot_dir: str) -> ImplementationSession:
        """
        End-to-end feature implementation.

        This is the main entry point for programmatic use.
        """
        logger.info(f"Implementing feature: {requirements[:50]}...")

        # Start session
        session = self.engine.start_session_sync(requirements, snapshot_dir)
        self.change_tracker.start_session_tracking(session.session_id)

        # Create vision
        vision = await self.engine.create_vision_for_session(session.session_id)

        # Create strategy
        strategy = self.engine.create_strategy_for_session(session.session_id)

        # Create work chunks
        work_chunks = self.engine.create_work_chunks_for_session(session.session_id)

        # Execute session
        session = await self.engine.execute_session(session.session_id)

        # Validate session
        validation_result = await self.engine.validate_session(session.session_id)

        # End tracking
        self.change_tracker.end_session_tracking()

        logger.info(f"Feature implementation completed: {session.session_id}")
        return session

    async def architectural_review(self, snapshot_dir: str) -> CurrentStateAnalysis:
        """
        Perform architectural review without implementation.

        Useful for understanding a codebase.
        """
        logger.info(f"Starting architectural review: {snapshot_dir}")

        if not self.engine:
            await self.initialize()

        analysis = await self.engine.architectural_review(snapshot_dir)

        logger.info(f"Architectural review completed: {len(analysis.components)} components")
        return analysis

    async def create_implementation_plan(self, requirements: str, snapshot_dir: str) -> ImplementationSession:
        """
        Create implementation plan without executing.

        Returns session with vision, strategy, and work chunks, but not executed.
        """
        logger.info(f"Creating implementation plan: {requirements[:50]}...")

        if not self.engine:
            await self.initialize()

        # Start session
        session = self.engine.start_session_sync(requirements, snapshot_dir)

        # Create vision
        vision = await self.engine.create_vision_for_session(session.session_id)

        # Create strategy
        strategy = self.engine.create_strategy_for_session(session.session_id)

        # Create work chunks
        work_chunks = self.engine.create_work_chunks_for_session(session.session_id)

        # Update status
        session.status = "planned"
        session.updated_at = datetime.now()

        logger.info(f"Implementation plan created: {session.session_id}")
        logger.info(f"  Components: {len(session.current_state.components)}")
        logger.info(f"  Work chunks: {len(session.work_chunks)}")

        return session

    async def execute_plan(self, session_id: str) -> ImplementationSession:
        """
        Execute an existing implementation plan.

        Useful for separating planning from execution.
        """
        logger.info(f"Executing plan for session: {session_id}")

        if not self.engine:
            await self.initialize()

        # Load session
        session = self.engine.load_session_sync(session_id)
        self.change_tracker.start_session_tracking(session_id)

        # Execute
        session = await self.engine.execute_session(session_id)

        # Validate
        validation_result = await self.engine.validate_session(session_id)

        # End tracking
        self.change_tracker.end_session_tracking()

        logger.info(f"Plan execution completed: {session_id}")
        return session

    async def validate_implementation(self, session_id: str) -> ValidationResult:
        """
        Validate an implementation session.

        Can be used to re-validate after manual changes.
        """
        logger.info(f"Validating implementation: {session_id}")

        if not self.engine:
            await self.initialize()

        return await self.engine.validate_session(session_id)

    async def iterate_on_feedback(self, session_id: str, feedback: Dict[str, Any]) -> IterationPlan:
        """
        Handle feedback and create iteration plan.
        """
        logger.info(f"Creating iteration plan for session: {session_id}")

        if not self.engine:
            await self.initialize()

        return await self.engine.handle_iteration(session_id, feedback)

    # ============================================================================
    # UTILITY METHODS
    # ============================================================================

    async def get_session_summary(self, session_id: str) -> Dict[str, Any]:
        """Get summary of a session."""
        if not self.engine:
            await self.initialize()

        # Try to load session
        try:
            session = self.engine.load_session_sync(session_id)

            # Create summary
            total_chunks = len(session.work_chunks)
            completed_chunks = sum(1 for c in session.work_chunks.values()
                                   if c.status == ImplementationStatus.VALIDATED)

            summary = {
                'session_id': session_id,
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
                'duration_minutes': int((session.updated_at - session.created_at).total_seconds() / 60),
                'applied_learnings': len(session.applied_learnings)
            }

            # Add change tracking summary if available
            change_summary = self.change_tracker.get_session_summary(session_id)
            if change_summary:
                summary['change_tracking'] = change_summary

            return summary

        except Exception as e:
            logger.error(f"Failed to get session summary: {e}")
            return {
                'session_id': session_id,
                'error': str(e),
                'status': 'unknown'
            }

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List all available sessions."""
        if not self.engine:
            # Create minimal engine just for listing
            temp_engine = ArchitecturalReasoningEngine(self.config_path)
            return temp_engine.list_sessions_sync()

        return self.engine.list_sessions_sync()

    async def export_session(self, session_id: str, export_path: str) -> bool:
        """Export a session to a JSON file."""
        try:
            session = self.engine.load_session_sync(session_id)

            export_file = Path(export_path)
            export_file.parent.mkdir(parents=True, exist_ok=True)

            # Use EnhancedJSONEncoder for proper serialization
            from assistant.core.reasoning_models import EnhancedJSONEncoder

            with open(export_file, 'w', encoding='utf-8') as f:
                json.dump(session, f, cls=EnhancedJSONEncoder, indent=2)

            logger.info(f"Exported session {session_id} to {export_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to export session: {e}")
            return False

    async def import_session(self, import_path: str) -> Optional[ImplementationSession]:
        """Import a session from a JSON file."""
        try:
            import_file = Path(import_path)
            if not import_file.exists():
                logger.error(f"Import file not found: {import_path}")
                return None

            with open(import_file, 'r', encoding='utf-8') as f:
                session_data = json.load(f)

            # Convert to session object
            from assistant.core.reasoning_models import ImplementationSession
            session = ImplementationSession.from_dict(session_data)

            # Save to engine storage
            if not self.engine:
                await self.initialize()

            self.engine._save_session_sync(session)

            logger.info(f"Imported session {session.session_id} from {import_path}")
            return session

        except Exception as e:
            logger.error(f"Failed to import session: {e}")
            return None

    # ============================================================================
    # LEARNING SYSTEM INTEGRATION
    # ============================================================================

    async def search_learnings(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for relevant learnings."""
        if not self.engine:
            await self.initialize()

        from assistant.core.learning_engine import create_learning_engine

        learning_engine = create_learning_engine()
        results = learning_engine.search_learnings(query, limit)

        # Convert to dicts
        return [
            {
                'id': learning.id,
                'title': learning.title,
                'category': learning.category.value,
                'description': learning.description[:200],
                'confidence': learning.confidence_score,
                'relevance_score': score
            }
            for learning, score in results
        ]

    async def get_learning_stats(self) -> Dict[str, Any]:
        """Get learning system statistics."""
        from assistant.core.learning_engine import create_learning_engine

        learning_engine = create_learning_engine()
        return learning_engine.get_stats()

    # ============================================================================
    # CLEANUP
    # ============================================================================

    async def cleanup(self):
        """Clean up resources."""
        if self.engine and hasattr(self.engine, 'client'):
            await self.engine.client.close()

        logger.info("ProgrammaticOrchestrator cleaned up")


# ============================================================================
# SYNCHRONOUS WRAPPER
# ============================================================================

class ProgrammaticOrchestratorSync:
    """
    Synchronous wrapper for scripts that can't use async.

    Uses asyncio.run() internally. For simple scripts and REPL use.
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self._orchestrator = None

    def _ensure_orchestrator(self):
        """Initialize orchestrator if needed."""
        if not self._orchestrator:
            self._orchestrator = ProgrammaticOrchestrator(self.config_path)

    def implement_feature_sync(self, requirements: str, snapshot_dir: str) -> ImplementationSession:
        """Synchronous version of implement_feature."""
        self._ensure_orchestrator()
        return asyncio.run(self._orchestrator.implement_feature(requirements, snapshot_dir))

    def architectural_review_sync(self, snapshot_dir: str) -> CurrentStateAnalysis:
        """Synchronous version of architectural_review."""
        self._ensure_orchestrator()
        return asyncio.run(self._orchestrator.architectural_review(snapshot_dir))

    def create_implementation_plan_sync(self, requirements: str, snapshot_dir: str) -> ImplementationSession:
        """Synchronous version of create_implementation_plan."""
        self._ensure_orchestrator()
        return asyncio.run(self._orchestrator.create_implementation_plan(requirements, snapshot_dir))

    def execute_plan_sync(self, session_id: str) -> ImplementationSession:
        """Synchronous version of execute_plan."""
        self._ensure_orchestrator()
        return asyncio.run(self._orchestrator.execute_plan(session_id))

    def validate_implementation_sync(self, session_id: str) -> ValidationResult:
        """Synchronous version of validate_implementation."""
        self._ensure_orchestrator()
        return asyncio.run(self._orchestrator.validate_implementation(session_id))

    def get_session_summary_sync(self, session_id: str) -> Dict[str, Any]:
        """Synchronous version of get_session_summary."""
        self._ensure_orchestrator()
        return asyncio.run(self._orchestrator.get_session_summary(session_id))

    def list_sessions_sync(self) -> List[Dict[str, Any]]:
        """Synchronous version of list_sessions."""
        self._ensure_orchestrator()
        if self._orchestrator.engine:
            return self._orchestrator.engine.list_sessions_sync()

        # Create minimal engine just for listing
        temp_engine = ArchitecturalReasoningEngine(self.config_path)
        return temp_engine.list_sessions_sync()

    def search_learnings_sync(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Synchronous version of search_learnings."""
        from assistant.core.learning_engine import create_learning_engine

        learning_engine = create_learning_engine()
        results = learning_engine.search_learnings(query, limit)

        return [
            {
                'id': learning.id,
                'title': learning.title,
                'category': learning.category.value,
                'description': learning.description[:200],
                'confidence': learning.confidence_score,
                'relevance_score': score
            }
            for learning, score in results
        ]


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

async def create_orchestrator(config_path: str = "config.yaml") -> ProgrammaticOrchestrator:
    """Factory function to create and initialize an orchestrator."""
    orchestrator = ProgrammaticOrchestrator(config_path)
    await orchestrator.initialize()
    return orchestrator


def create_sync_orchestrator(config_path: str = "config.yaml") -> ProgrammaticOrchestratorSync:
    """Factory function to create a synchronous orchestrator."""
    return ProgrammaticOrchestratorSync(config_path)


# Quick access functions for common operations
async def quick_architectural_review(snapshot_dir: str, config_path: str = "config.yaml") -> Dict[str, Any]:
    """Quick architectural review - returns simplified dict."""
    orchestrator = await create_orchestrator(config_path)
    analysis = await orchestrator.architectural_review(snapshot_dir)

    return {
        'snapshot': snapshot_dir,
        'components': len(analysis.components),
        'tech_stack': analysis.tech_stack[:10],
        'patterns': analysis.patterns[:5],
        'strengths': analysis.strengths[:3],
        'weaknesses': analysis.weaknesses[:3],
        'risks': len(analysis.risks),
        'confidence': analysis.analysis_confidence
    }


async def quick_implementation_plan(requirements: str, snapshot_dir: str,
                                    config_path: str = "config.yaml") -> Dict[str, Any]:
    """Quick implementation plan - returns simplified dict."""
    orchestrator = await create_orchestrator(config_path)
    session = await orchestrator.create_implementation_plan(requirements, snapshot_dir)

    return {
        'session_id': session.session_id,
        'vision_id': session.vision.id if session.vision else None,
        'components_affected': len(session.strategy.affected_components) if session.strategy else 0,
        'new_components': len(session.strategy.new_components) if session.strategy else 0,
        'work_chunks': len(session.work_chunks),
        'estimated_effort': session.vision.estimated_effort if session.vision else 'unknown',
        'priority': session.vision.priority if session.vision else 'medium'
    }