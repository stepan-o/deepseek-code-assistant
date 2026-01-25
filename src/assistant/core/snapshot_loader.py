# src/assistant/core/snapshot_loader.py
"""
Snapshot Loader for DeepSeek Code Assistant.

Minimal, synchronous loader for Snapshotter artifacts.
Just loads what Snapshotter already produced for context.
"""
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)


class SnapshotLoader:
    """Synchronous loader for Snapshotter artifacts."""

    def __init__(self):
        pass

    def load_snapshot(self, snapshot_dir: str) -> Dict[str, Any]:
        """
        Load essential artifacts from a snapshot directory.

        Args:
            snapshot_dir: Path to snapshot directory (e.g., "snapshots/repo/20240101_120000")

        Returns:
            Dictionary with loaded artifacts and metadata
        """
        snapshot_path = Path(snapshot_dir)

        if not snapshot_path.exists():
            raise FileNotFoundError(f"Snapshot directory not found: {snapshot_dir}")

        artifacts = {
            'snapshot_path': str(snapshot_path),
            'snapshot_name': snapshot_path.name,
            'loaded_artifacts': {}
        }

        # Load only the essential artifacts that assistant cares about
        artifact_files = [
            ('architecture_summary', 'ARCHITECTURE_SUMMARY_SNAPSHOT.json'),
            ('repo_index', 'repo_index.json'),
        ]

        for artifact_name, filename in artifact_files:
            filepath = snapshot_path / filename
            if filepath.exists():
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        artifacts['loaded_artifacts'][artifact_name] = data
                        logger.info(f"Loaded {filename}")
                except Exception as e:
                    logger.error(f"Failed to load {filename}: {e}")
                    artifacts['loaded_artifacts'][artifact_name] = None
            else:
                logger.warning(f"Artifact not found: {filepath}")
                artifacts['loaded_artifacts'][artifact_name] = None

        # Optional: Load onboarding markdown for human reference
        onboarding_path = snapshot_path / 'ONBOARDING.md'
        if onboarding_path.exists():
            try:
                with open(onboarding_path, 'r', encoding='utf-8') as f:
                    artifacts['loaded_artifacts']['onboarding'] = f.read()
            except Exception as e:
                logger.error(f"Failed to load ONBOARDING.md: {e}")

        return artifacts

    def get_key_files(self, artifacts: Dict[str, Any], max_files: int = 20) -> List[str]:
        """
        Get a list of key files from snapshot artifacts.
        Uses Snapshotter's already-determined important files.

        Args:
            artifacts: Loaded artifacts from load_snapshot()
            max_files: Maximum number of files to return

        Returns:
            List of file paths relative to repository root
        """
        file_list = []

        # Try to get files from architecture summary first
        arch_summary = artifacts.get('loaded_artifacts', {}).get('architecture_summary')
        if arch_summary and isinstance(arch_summary, dict):
            arch_context = arch_summary.get('architecture_context', {})

            # Get entry points (usually main files)
            entry_points = arch_context.get('entry_points', [])
            if isinstance(entry_points, list):
                file_list.extend(entry_points)

            # Get key modules and their files
            key_modules = arch_context.get('key_modules', [])
            if isinstance(key_modules, list):
                for module in key_modules[:5]:  # Limit to top 5 modules
                    if isinstance(module, dict):
                        module_files = module.get('files', [])
                        if isinstance(module_files, list):
                            file_list.extend(module_files[:3])  # Up to 3 files per module

        # Fallback: Use repo index if we don't have enough files
        repo_index = artifacts.get('loaded_artifacts', {}).get('repo_index')
        if repo_index and isinstance(repo_index, dict) and len(file_list) < max_files // 2:
            all_files = repo_index.get('files', [])
            if isinstance(all_files, list):
                # Prioritize Python files and non-test files
                python_files = [f for f in all_files if f.endswith('.py') and 'test' not in f.lower()]
                other_files = [f for f in all_files if not f.endswith('.py') and 'test' not in f.lower()]

                file_list.extend(python_files[:10])
                file_list.extend(other_files[:5])

        # Deduplicate and limit
        seen = set()
        unique_files = []
        for f in file_list:
            if isinstance(f, str) and f not in seen:
                seen.add(f)
                unique_files.append(f)

        return unique_files[:max_files]

    def create_system_message(self, artifacts: Dict[str, Any]) -> str:
        """
        Create a system message from snapshot artifacts.
        This will be prepended to chat conversations for context.

        Args:
            artifacts: Loaded artifacts from load_snapshot()

        Returns:
            Formatted system message string
        """
        arch_summary = artifacts.get('loaded_artifacts', {}).get('architecture_summary')

        if not arch_summary or not isinstance(arch_summary, dict):
            return "No architecture context available from snapshot."

        arch_context = arch_summary.get('architecture_context', {})
        if not arch_context:
            return "No architecture context available from snapshot."

        parts = []

        # Overview
        overview = arch_context.get('overview', '').strip()
        if overview:
            parts.append(f"## Architecture Overview\n\n{overview}\n")

        # Key modules (simplified)
        key_modules = arch_context.get('key_modules', [])
        if key_modules and isinstance(key_modules, list):
            parts.append("## Key Modules\n")
            for i, module in enumerate(key_modules[:8], 1):  # Limit to 8 modules
                if isinstance(module, dict):
                    name = module.get('name', f'Module {i}')
                    desc = module.get('description', '').strip()
                    purpose = module.get('purpose', '').strip()

                    if desc:
                        parts.append(f"- **{name}**: {desc}")
                    else:
                        parts.append(f"- {name}")

                    if purpose:
                        parts.append(f"  Purpose: {purpose}")
                elif isinstance(module, str):
                    parts.append(f"- {module}")
            parts.append("")

        # Technology stack
        tech_stack = arch_context.get('tech_stack', [])
        if tech_stack and isinstance(tech_stack, list):
            parts.append("## Technology Stack\n")
            for tech in tech_stack[:12]:  # Limit to 12 items
                if isinstance(tech, str):
                    parts.append(f"- {tech}")
            parts.append("")

        # Design patterns
        patterns = arch_context.get('patterns', [])
        if patterns and isinstance(patterns, list):
            parts.append("## Design Patterns\n")
            for pattern in patterns[:6]:
                if isinstance(pattern, str):
                    parts.append(f"- {pattern}")
            parts.append("")

        # Add note about snapshot source
        snapshot_name = artifacts.get('snapshot_name', 'unknown')
        parts.append(f"*Note: This context is from snapshot: {snapshot_name}*")

        return "\n".join(parts)

    def find_latest_snapshot(self, repo_name: str) -> Optional[str]:
        """
        Find the latest snapshot for a given repository.

        Args:
            repo_name: Name of the repository (directory name in snapshots/)

        Returns:
            Path to latest snapshot directory, or None if not found
        """
        snapshots_dir = Path("snapshots") / repo_name

        if not snapshots_dir.exists():
            return None

        # Get all snapshot directories (named as timestamps)
        snapshot_dirs = []
        for item in snapshots_dir.iterdir():
            if item.is_dir() and item.name:
                snapshot_dirs.append(item)

        if not snapshot_dirs:
            return None

        # Sort by directory name (timestamp) descending
        snapshot_dirs.sort(key=lambda x: x.name, reverse=True)

        return str(snapshot_dirs[0])


# Convenience function for one-line loading
def load_snapshot_context(snapshot_dir: str) -> tuple[Dict[str, Any], List[str], str]:
    """
    High-level function to load snapshot context.

    Args:
        snapshot_dir: Path to snapshot directory

    Returns:
        Tuple of (artifacts, key_files, system_message)
    """
    loader = SnapshotLoader()
    artifacts = loader.load_snapshot(snapshot_dir)
    key_files = loader.get_key_files(artifacts)
    system_message = loader.create_system_message(artifacts)

    return artifacts, key_files, system_message