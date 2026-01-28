# src/assistant/integrations/__init__.py
"""
Integration modules for DeepSeek Code Assistant.
"""

from assistant.integrations.chat_integration import ChatIntegration
from assistant.integrations.git import GitIntegration

__all__ = [
    'ChatIntegration',
    'GitIntegration'
]