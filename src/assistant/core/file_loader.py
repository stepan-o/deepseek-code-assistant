# src/assistant/core/file_loader.py
"""
Simple file loader for code context.
Synchronous implementation - no async needed for local file I/O.
"""
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class FileLoader:
    """Load and manage file contents for context."""

    def __init__(self, root_path: Optional[str] = None):
        self.root_path = Path(root_path or Path.cwd())
        self.file_cache = {}

    def load_file(self, file_path: str) -> Optional[str]:
        """Load a single file synchronously."""
        try:
            full_path = self.root_path / file_path

            # Check cache first
            if str(full_path) in self.file_cache:
                return self.file_cache[str(full_path)]

            # Check if file exists
            if not full_path.exists():
                logger.debug(f"File does not exist: {full_path}")
                return None

            # Read file synchronously
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Cache content
            self.file_cache[str(full_path)] = content
            logger.debug(f"Loaded file: {file_path} ({len(content)} chars)")
            return content

        except UnicodeDecodeError:
            # Skip binary files
            logger.debug(f"Skipping binary file: {file_path}")
            return None
        except Exception as e:
            logger.error(f"Error loading file {file_path}: {e}")
            return None

    def load_multiple_files(self, file_paths: List[str]) -> Dict[str, str]:
        """Load multiple files synchronously."""
        loaded_files = {}

        for path in file_paths:
            content = self.load_file(path)
            if content:
                loaded_files[path] = content

        logger.info(f"Loaded {len(loaded_files)}/{len(file_paths)} files")
        return loaded_files

    def clear_cache(self):
        """Clear the file cache."""
        self.file_cache.clear()


class SimpleChunker:
    """Simple token-aware text chunker."""

    def __init__(self, max_tokens: int = 1000):
        self.max_tokens = max_tokens

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Simple token estimation (4 chars ~ 1 token)."""
        # Rough approximation
        return len(text) // 4

    def chunk_text(self, text: str) -> List[str]:
        """Split text into token-aware chunks."""
        chunks = []

        # If text is small enough, return as is
        if self.estimate_tokens(text) <= self.max_tokens:
            return [text]

        # Split by lines for better context preservation
        lines = text.split('\n')
        current_chunk = []
        current_tokens = 0

        for line in lines:
            line_tokens = self.estimate_tokens(line)

            # If adding this line exceeds max tokens, start new chunk
            if current_tokens + line_tokens > self.max_tokens and current_chunk:
                chunks.append('\n'.join(current_chunk))
                current_chunk = [line]
                current_tokens = line_tokens
            else:
                current_chunk.append(line)
                current_tokens += line_tokens

        # Add the last chunk
        if current_chunk:
            chunks.append('\n'.join(current_chunk))

        return chunks

    def chunk_code_file(self, content: str, file_ext: str = "") -> List[Dict[str, Any]]:
        """Chunk code file with basic structure awareness."""
        chunks = self.chunk_text(content)

        chunked = []
        for i, chunk in enumerate(chunks):
            chunked.append({
                'content': chunk,
                'chunk_index': i,
                'total_chunks': len(chunks),
                'estimated_tokens': self.estimate_tokens(chunk)
            })

        return chunked