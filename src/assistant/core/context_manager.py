# src/assistant/core/context_manager.py
"""
Basic context manager for code-aware conversations.
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from pathlib import Path
import json


@dataclass
class CodeContext:
    """Represents code context for a conversation."""
    files: Dict[str, str]  # filename -> content
    current_file: Optional[str] = None
    cursor_position: Optional[tuple] = None  # (line, column)
    project_root: Optional[Path] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'files': self.files,
            'current_file': self.current_file,
            'cursor_position': self.cursor_position,
            'project_root': str(self.project_root) if self.project_root else None
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CodeContext':
        """Create from dictionary."""
        return cls(
            files=data.get('files', {}),
            current_file=data.get('current_file'),
            cursor_position=data.get('cursor_position'),
            project_root=Path(data['project_root']) if data.get('project_root') else None
        )


class ContextManager:
    """Manage conversation context with code awareness."""

    def __init__(self, max_context_tokens: int = 32000):
        self.max_context_tokens = max_context_tokens
        self.code_context = CodeContext(files={})
        self.conversation_history = []

    def add_file(self, filename: str, content: str):
        """Add a file to context."""
        self.code_context.files[filename] = content

    def set_current_file(self, filename: str):
        """Set the current file being worked on."""
        self.code_context.current_file = filename

    def clear_files(self):
        """Clear all files from context."""
        self.code_context.files.clear()

    def add_to_history(self, role: str, content: str):
        """Add a message to conversation history."""
        self.conversation_history.append({
            'role': role,
            'content': content,
            'timestamp': None  # Could add timestamp if needed
        })

    def build_prompt(self, user_message: str, include_context: bool = True) -> List[Dict[str, str]]:
        """Build a prompt with context for the API."""
        messages = []

        # Add system message with context if available
        if include_context and self.code_context.files:
            system_msg = self._create_system_message()
            messages.append({"role": "system", "content": system_msg})

        # Add conversation history
        for msg in self.conversation_history[-10:]:  # Last 10 messages
            messages.append({"role": msg['role'], "content": msg['content']})

        # Add current user message
        messages.append({"role": "user", "content": user_message})

        return messages

    def _create_system_message(self) -> str:
        """Create a system message with current context."""
        system_parts = ["You are a code assistant with access to the following files:"]

        for filename, content in self.code_context.files.items():
            system_parts.append(f"\n--- File: {filename} ---")

            # Truncate if too long
            if len(content) > 5000:
                content = content[:2500] + "\n... [truncated] ...\n" + content[-2500:]

            system_parts.append(content)

        if self.code_context.current_file:
            system_parts.append(f"\nCurrently focused on: {self.code_context.current_file}")

        return '\n'.join(system_parts)

    def save_context(self, filepath: str):
        """Save context to file."""
        data = {
            'code_context': self.code_context.to_dict(),
            'conversation_history': self.conversation_history
        }

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

    def load_context(self, filepath: str):
        """Load context from file."""
        with open(filepath, 'r') as f:
            data = json.load(f)

        self.code_context = CodeContext.from_dict(data['code_context'])
        self.conversation_history = data['conversation_history']