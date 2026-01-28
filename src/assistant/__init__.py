# src/assistant/__init__.py
"""
DeepSeek Code Assistant with Architectural Reasoning Engine.
"""

__version__ = "0.1.0"
__author__ = "DeepSeek Code Assistant Team"

from assistant.core.reasoning_engine import ArchitecturalReasoningEngine
from assistant.core.learning_engine import LearningEngine
from assistant.core.programmatic_api import ProgrammaticOrchestrator
from assistant.core.focused_validator import FocusedValidator

__all__ = [
    'ArchitecturalReasoningEngine',
    'LearningEngine',
    'ProgrammaticOrchestrator',
    'FocusedValidator'
]