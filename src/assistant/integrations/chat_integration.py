# src/assistant/integrations/chat_integration.py
"""
Chat Integration - Bridges reasoning engine with existing chat CLI.

MIXED: Sync for state management, Async for engine calls.
Injected into ChatCLI, makes engine state visible in chat.
"""

import asyncio
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Union, Tuple
from datetime import datetime
import logging

from assistant.core.programmatic_api import ProgrammaticOrchestrator, create_orchestrator
from assistant.core.reasoning_models import *
from assistant.ui.chat_cli import ChatCLI

logger = logging.getLogger(__name__)


class ChatIntegration:
    """Integrates reasoning engine with chat interface."""

    def __init__(self, chat_cli: ChatCLI, config_path: str = "config.yaml"):
        self.chat_cli = chat_cli
        self.config_path = config_path
        self.orchestrator = None
        self.current_session = None
        self.engine_initialized = False

        # Engine state for chat display
        self.engine_status = "not_initialized"
        self.last_operation = None
        self.active_sessions = []

        logger.info("ChatIntegration initialized")

    async def initialize(self):
        """Initialize engine connection."""
        try:
            logger.info("Initializing ChatIntegration engine...")
            self.orchestrator = await create_orchestrator(self.config_path)
            self.engine_initialized = True
            self.engine_status = "ready"
            logger.info("ChatIntegration engine initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize ChatIntegration: {e}")
            self.engine_status = f"error: {str(e)[:50]}"
            return False

    def is_available(self) -> bool:
        """Check if engine integration is available."""
        return self.engine_initialized and self.orchestrator is not None

    async def start_architectural_dialogue(self, user_query: str) -> Dict[str, Any]:
        """
        Start an architectural reasoning dialogue.

        Returns structured response for chat display.
        """
        if not self.is_available():
            return {
                'status': 'error',
                'message': 'Engine not available. Try /architect-init first.',
                'suggestion': 'Use /architect-init to initialize the engine.'
            }

        try:
            logger.info(f"Starting architectural dialogue: {user_query[:50]}...")
            self.engine_status = "processing"
            self.last_operation = "architectural_dialogue"

            # Extract requirements and snapshot from query context
            requirements, snapshot_dir = self._extract_from_query(user_query)

            if not snapshot_dir:
                return {
                    'status': 'error',
                    'message': 'No snapshot context available.',
                    'suggestion': 'First load a snapshot with: /load-snapshot or deepseek load-snapshot'
                }

            # Start session
            session = self.orchestrator.engine.start_session_sync(requirements, snapshot_dir)
            self.current_session = session

            # Create vision
            vision = await self.orchestrator.engine.create_vision_for_session(session.session_id)

            # Update engine state
            self.engine_status = "vision_created"
            self.active_sessions.append(session.session_id)

            # Prepare response for chat
            response = {
                'status': 'success',
                'session_id': session.session_id,
                'vision_id': vision.id,
                'message': f"✅ Created architectural vision for: {requirements[:100]}...",
                'details': {
                    'architectural_approach': vision.architectural_approach[:500] + ("..." if len(vision.architectural_approach) > 500 else ""),
                    'acceptance_criteria': vision.acceptance_criteria[:3],
                    'estimated_effort': vision.estimated_effort,
                    'priority': vision.priority
                },
                'actions': [
                    {'command': '/session plan', 'description': 'Create implementation plan'},
                    {'command': '/session strategy', 'description': 'View implementation strategy'},
                    {'command': '/session chunks', 'description': 'Break down into work chunks'},
                    {'command': '/session execute', 'description': 'Execute implementation'}
                ]
            }

            # Inject into chat context
            self.inject_into_chat_context(session, self.chat_cli.context_manager)

            return response

        except Exception as e:
            logger.error(f"Architectural dialogue failed: {e}")
            self.engine_status = "error"
            return {
                'status': 'error',
                'message': f'Architectural reasoning failed: {str(e)}',
                'suggestion': 'Check if snapshot is properly loaded and API is available.'
            }

    async def handle_session_command(self, command: str, args: List[str], session_id: Optional[str] = None) -> Dict[str, Any]:
        """Handle session-related commands."""
        if not self.is_available():
            return {
                'status': 'error',
                'message': 'Engine not initialized.',
                'suggestion': 'Use /architect-init first.'
            }

        # Use current session if not specified
        target_session = session_id or (self.current_session.session_id if self.current_session else None)

        if not target_session:
            return {
                'status': 'error',
                'message': 'No active session.',
                'suggestion': 'Start a session with: /architect <requirements>'
            }

        try:
            if command == 'plan':
                # Create implementation plan
                strategy = self.orchestrator.engine.create_strategy_for_session(target_session)
                work_chunks = self.orchestrator.engine.create_work_chunks_for_session(target_session)

                return {
                    'status': 'success',
                    'session_id': target_session,
                    'message': f"✅ Created implementation plan for session {target_session}",
                    'details': {
                        'affected_components': len(strategy.affected_components),
                        'new_components': len(strategy.new_components),
                        'work_chunks': len(work_chunks),
                        'execution_sequence': strategy.execution_sequence[:5]
                    },
                    'actions': [
                        {'command': '/session execute', 'description': 'Execute the plan'},
                        {'command': '/session chunks list', 'description': 'List all work chunks'},
                        {'command': '/session validate', 'description': 'Validate the plan'}
                    ]
                }

            elif command == 'execute':
                # Execute session
                self.engine_status = "executing"
                session = await self.orchestrator.engine.execute_session(target_session)

                # Validate
                validation = await self.orchestrator.engine.validate_session(target_session)

                self.engine_status = "completed"

                return {
                    'status': 'success',
                    'session_id': target_session,
                    'message': f"✅ Executed session {target_session}: {validation.overall_status}",
                    'details': {
                        'status': session.status,
                        'validation_result': validation.overall_status,
                        'confidence': validation.confidence_score,
                        'chunks_completed': sum(1 for c in session.work_chunks.values()
                                                if c.status == ImplementationStatus.VALIDATED),
                        'total_chunks': len(session.work_chunks)
                    },
                    'actions': [
                        {'command': f'/session summary {target_session}', 'description': 'View detailed summary'},
                        {'command': '/learnings capture', 'description': 'Capture learnings from this session'},
                        {'command': '/session iterate', 'description': 'Iterate based on feedback'}
                    ]
                }

            elif command == 'summary':
                # Get session summary
                summary = await self.orchestrator.get_session_summary(target_session)

                return {
                    'status': 'success',
                    'session_id': target_session,
                    'message': f"📊 Session {target_session} summary",
                    'details': summary,
                    'format': 'table'  # Hint for chat to format as table
                }

            elif command == 'list':
                # List all sessions
                sessions = self.orchestrator.list_sessions()

                return {
                    'status': 'success',
                    'message': f"📁 Available sessions: {len(sessions)}",
                    'details': sessions[:10],  # Limit to 10
                    'format': 'sessions_table'
                }

            elif command == 'chunks':
                # Handle chunk subcommands
                if not args:
                    return {
                        'status': 'error',
                        'message': 'Missing chunk command.',
                        'suggestion': 'Use: /session chunks <list|status|validate>'
                    }

                subcommand = args[0]
                if subcommand == 'list':
                    # Load session to get chunks
                    session = self.orchestrator.engine.load_session_sync(target_session)
                    chunks = list(session.work_chunks.values())

                    chunk_list = [
                        {
                            'id': c.id[:8],
                            'description': c.description,
                            'component': c.component,
                            'status': c.status.value,
                            'complexity': c.estimated_complexity
                        }
                        for c in chunks[:20]  # Limit to 20
                    ]

                    return {
                        'status': 'success',
                        'session_id': target_session,
                        'message': f"📋 Work chunks for session {target_session}: {len(chunks)}",
                        'details': chunk_list,
                        'format': 'chunks_table'
                    }

            elif command == 'validate':
                # Validate session
                validation = await self.orchestrator.validate_implementation(target_session)

                return {
                    'status': 'success',
                    'session_id': target_session,
                    'message': f"🔍 Validation result: {validation.overall_status}",
                    'details': {
                        'status': validation.overall_status,
                        'confidence': validation.confidence_score,
                        'criteria_passed': len(validation.passed_criteria),
                        'criteria_failed': len(validation.failed_criteria),
                        'issues_found': len(validation.issues_found),
                        'warnings': len(validation.warnings)
                    },
                    'actions': [
                        {'command': f'/session issues {target_session}', 'description': 'View validation issues'},
                        {'command': f'/session iterate {target_session}', 'description': 'Create iteration plan'}
                    ]
                }

            else:
                return {
                    'status': 'error',
                    'message': f'Unknown session command: {command}',
                    'suggestion': 'Available: plan, execute, summary, list, chunks, validate'
                }

        except Exception as e:
            logger.error(f"Session command failed: {e}")
            return {
                'status': 'error',
                'message': f'Session operation failed: {str(e)}',
                'suggestion': 'Check if session exists and engine is properly initialized.'
            }

    async def handle_learnings_command(self, command: str, args: List[str]) -> Dict[str, Any]:
        """Handle learning-related commands."""
        if not self.is_available():
            return {
                'status': 'error',
                'message': 'Engine not initialized.',
                'suggestion': 'Use /architect-init first.'
            }

        try:
            if command == 'search':
                if not args:
                    return {
                        'status': 'error',
                        'message': 'Missing search query.',
                        'suggestion': 'Use: /learnings search <query>'
                    }

                query = ' '.join(args)
                results = await self.orchestrator.search_learnings(query, limit=5)

                return {
                    'status': 'success',
                    'message': f'🔍 Learnings search: "{query}"',
                    'details': results,
                    'format': 'learnings_table'
                }

            elif command == 'stats':
                stats = await self.orchestrator.get_learning_stats()

                return {
                    'status': 'success',
                    'message': '📊 Learning system statistics',
                    'details': stats,
                    'format': 'stats_table'
                }

            elif command == 'capture':
                if self.current_session:
                    # Capture learnings from current session
                    from assistant.core.learning_engine import create_learning_engine

                    learning_engine = create_learning_engine()
                    # This would capture from session validation history
                    # Simplified for now

                    return {
                        'status': 'success',
                        'message': '💾 Learnings captured from current session',
                        'details': {
                            'session_id': self.current_session.session_id,
                            'learnings_captured': 'simulated - would capture from validation'
                        }
                    }
                else:
                    return {
                        'status': 'error',
                        'message': 'No active session to capture learnings from.',
                        'suggestion': 'Start a session first with /architect'
                    }

            elif command == 'apply':
                if self.current_session:
                    # Apply learnings to current session
                    from assistant.core.learning_engine import create_learning_engine

                    learning_engine = create_learning_engine()
                    applied = learning_engine.apply_to_session(self.current_session)

                    return {
                        'status': 'success',
                        'message': f'✅ Applied {len(applied)} learnings to current session',
                        'details': {
                            'session_id': self.current_session.session_id,
                            'learnings_applied': len(applied),
                            'learnings': [l['learning_title'][:50] for l in applied[:3]]
                        }
                    }
                else:
                    return {
                        'status': 'error',
                        'message': 'No active session to apply learnings to.',
                        'suggestion': 'Start a session first with /architect'
                    }

            else:
                return {
                    'status': 'error',
                    'message': f'Unknown learnings command: {command}',
                    'suggestion': 'Available: search, stats, capture, apply'
                }

        except Exception as e:
            logger.error(f"Learnings command failed: {e}")
            return {
                'status': 'error',
                'message': f'Learnings operation failed: {str(e)}'
            }

    async def handle_validation_command(self, args: List[str]) -> Dict[str, Any]:
        """Handle validation commands."""
        if not self.is_available():
            return {
                'status': 'error',
                'message': 'Engine not initialized.',
                'suggestion': 'Use /architect-init first.'
            }

        if not args:
            return {
                'status': 'error',
                'message': 'Missing validation target.',
                'suggestion': 'Use: /validate <session|chunk|file>'
            }

        target_type = args[0]

        try:
            if target_type == 'session':
                if len(args) < 2:
                    return {
                        'status': 'error',
                        'message': 'Missing session ID.',
                        'suggestion': 'Use: /validate session <session_id>'
                    }

                session_id = args[1]
                validation = await self.orchestrator.validate_implementation(session_id)

                return {
                    'status': 'success',
                    'message': f'🔍 Session validation: {validation.overall_status}',
                    'details': {
                        'session_id': session_id,
                        'status': validation.overall_status,
                        'confidence': validation.confidence_score,
                        'issues': len(validation.issues_found),
                        'warnings': len(validation.warnings)
                    },
                    'validation_result': validation.to_dict()
                }

            elif target_type == 'quick':
                # Quick validation of current context
                if not self.current_session:
                    return {
                        'status': 'error',
                        'message': 'No active session for quick validation.',
                        'suggestion': 'Start a session first with /architect'
                    }

                # Simplified quick validation
                from assistant.core.focused_validator import quick_validation

                # Validate first chunk if exists
                if self.current_session.work_chunks:
                    chunk = list(self.current_session.work_chunks.values())[0]
                    result = await quick_validation(chunk, self.current_session)

                    return {
                        'status': 'success',
                        'message': '⚡ Quick validation completed',
                        'details': result
                    }
                else:
                    return {
                        'status': 'warning',
                        'message': 'No work chunks to validate.',
                        'suggestion': 'Create a plan first with /session plan'
                    }

            else:
                return {
                    'status': 'error',
                    'message': f'Unknown validation target: {target_type}',
                    'suggestion': 'Available: session, quick'
                }

        except Exception as e:
            logger.error(f"Validation command failed: {e}")
            return {
                'status': 'error',
                'message': f'Validation failed: {str(e)}'
            }

    def inject_into_chat_context(self, session: ImplementationSession, chat_context: Any):
        """Inject engine state into chat context."""
        # Store session reference in chat context manager
        if hasattr(chat_context, 'session_metadata'):
            chat_context.session_metadata = {
                'engine_session_id': session.session_id,
                'engine_status': session.status,
                'vision_id': session.vision.id if session.vision else None,
                'injected_at': datetime.now().isoformat()
            }

        # Also update our own state
        self.current_session = session

        logger.info(f"Injected session {session.session_id} into chat context")

    def get_session_summary(self, session_id: str) -> Dict[str, Any]:
        """Get summary for chat display."""
        if not self.orchestrator:
            return {'error': 'Orchestrator not initialized'}

        try:
            # Use sync method since this might be called from sync context
            summary = asyncio.run(self.orchestrator.get_session_summary(session_id))
            return summary
        except Exception as e:
            logger.error(f"Failed to get session summary: {e}")
            return {'error': str(e)}

    def get_engine_status(self) -> Dict[str, Any]:
        """Get current engine status for chat display."""
        return {
            'initialized': self.engine_initialized,
            'status': self.engine_status,
            'current_session': self.current_session.session_id if self.current_session else None,
            'active_sessions': len(self.active_sessions),
            'last_operation': self.last_operation,
            'timestamp': datetime.now().isoformat()
        }

    def _extract_from_query(self, query: str) -> Tuple[str, Optional[str]]:
        """Extract requirements and snapshot from query."""
        # For now, use the query as requirements
        requirements = query

        # Try to get snapshot from chat context
        snapshot_dir = None
        if hasattr(self.chat_cli, 'context_manager'):
            ctx_manager = self.chat_cli.context_manager
            if hasattr(ctx_manager, 'snapshot_metadata'):
                snapshot_meta = ctx_manager.snapshot_metadata
                if snapshot_meta:
                    snapshot_dir = snapshot_meta.get('snapshot_dir')

        # Fallback: try to find latest snapshot
        if not snapshot_dir:
            from assistant.core.snapshot_loader import SnapshotLoader
            loader = SnapshotLoader()
            # Try to find any snapshot
            # This is simplified - in production would be more sophisticated
            pass

        return requirements, snapshot_dir

    async def cleanup(self):
        """Clean up resources."""
        if self.orchestrator:
            await self.orchestrator.cleanup()

        logger.info("ChatIntegration cleaned up")


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

async def create_chat_integration(chat_cli: ChatCLI, config_path: str = "config.yaml") -> ChatIntegration:
    """Factory function to create and initialize chat integration."""
    integration = ChatIntegration(chat_cli, config_path)
    await integration.initialize()
    return integration


def format_engine_response_for_chat(response: Dict[str, Any]) -> str:
    """Format engine response for chat display."""
    if response.get('status') == 'error':
        return f"❌ {response.get('message', 'Unknown error')}\n💡 {response.get('suggestion', '')}"

    if response.get('status') == 'success':
        message = response.get('message', 'Success')
        details = response.get('details', {})

        # Format based on response type
        if response.get('format') == 'table':
            # Simplified table formatting
            return f"✅ {message}\n📊 Details available in structured format"
        elif response.get('format') == 'sessions_table':
            sessions = details
            session_list = "\n".join([f"  • {s['session_id']} - {s['status']}" for s in sessions[:5]])
            return f"✅ {message}\n{session_list}"
        else:
            # Simple text format
            details_text = ""
            if isinstance(details, dict):
                details_text = "\n".join([f"  • {k}: {v}" for k, v in details.items() if v])

            actions_text = ""
            if 'actions' in response:
                actions = response['actions']
                actions_text = "\n\nAvailable actions:\n" + "\n".join(
                    [f"  {a['command']} - {a['description']}" for a in actions[:3]]
                )

            return f"✅ {message}\n{details_text}{actions_text}"

    return str(response)