# src/shared/git_operations.py
"""
Shared git operations for both assistant and snapshotter.
Provides both synchronous and asynchronous interfaces.
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
import subprocess
import tempfile
import logging

logger = logging.getLogger(__name__)


def run_sync(cmd: list[str], cwd: str | Path | None = None) -> str:
    """Run command synchronously with error handling."""
    cwd_str = str(cwd) if cwd else None

    try:
        p = subprocess.run(
            cmd,
            cwd=cwd_str,
            capture_output=True,
            text=True,
            check=False  # We'll handle errors manually
        )

        if p.returncode != 0:
            error_msg = (
                f"Command failed: {' '.join(cmd)}\n"
                f"Exit code: {p.returncode}\n"
                f"STDOUT:\n{p.stdout}\n"
                f"STDERR:\n{p.stderr}"
            )
            raise RuntimeError(error_msg)

        return p.stdout.strip()

    except Exception as e:
        logger.error(f"Failed to run command {' '.join(cmd)}: {e}")
        raise


async def run_async(cmd: list[str], cwd: str | Path | None = None) -> str:
    """Run command asynchronously."""
    cwd_str = str(cwd) if cwd else None

    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd_str,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        error_msg = (
            f"Command failed: {' '.join(cmd)}\n"
            f"Exit code: {process.returncode}\n"
            f"STDOUT:\n{stdout.decode()}\n"
            f"STDERR:\n{stderr.decode()}"
        )
        raise RuntimeError(error_msg)

    return stdout.decode().strip()


def _is_probably_sha(ref: str) -> bool:
    """Check if a string looks like a git SHA."""
    r = (ref or "").strip()

    # SHA can be 7-40 characters
    if len(r) < 7 or len(r) > 40:
        return False

    # Check if it's hexadecimal
    return all(c in "0123456789abcdefABCDEF" for c in r)


class GitRepository:
    """Represents a git repository with operations."""

    def __init__(self, repo_path: str | Path):
        self.path = Path(repo_path).resolve()
        self._is_cloned = False

    def clone_and_checkout_sync(
            self,
            repo_url: str,
            ref: Optional[str] = None,
            depth: int = 1,
            with_tags: bool = False
    ) -> Tuple[str, str]:
        """
        Synchronously clone repo and checkout ref.

        Args:
            repo_url: Git repository URL
            ref: Branch, tag, or commit SHA to checkout
            depth: Clone depth (1 for shallow)
            with_tags: Whether to fetch tags

        Returns:
            Tuple of (commit_hash, repo_path)
        """
        # Clean up existing repo if exists
        if self.path.exists():
            shutil.rmtree(self.path, ignore_errors=True)

        self.path.mkdir(parents=True, exist_ok=True)

        # Build clone command
        clone_cmd = ["git", "clone"]

        if depth:
            clone_cmd.extend(["--depth", str(depth)])

        if not with_tags:
            clone_cmd.append("--no-tags")

        clone_cmd.extend([repo_url, str(self.path)])

        logger.info(f"Cloning {repo_url} to {self.path}")
        run_sync(clone_cmd)

        # Checkout ref if specified
        commit_hash = self._checkout_ref_sync(ref)

        self._is_cloned = True
        return commit_hash, str(self.path)

    async def clone_and_checkout_async(
            self,
            repo_url: str,
            ref: Optional[str] = None,
            depth: int = 1,
            with_tags: bool = False
    ) -> Tuple[str, str]:
        """Async version of clone_and_checkout."""
        # Clean up existing repo if exists
        if self.path.exists():
            shutil.rmtree(self.path, ignore_errors=True)

        self.path.mkdir(parents=True, exist_ok=True)

        # Build clone command
        clone_cmd = ["git", "clone"]

        if depth:
            clone_cmd.extend(["--depth", str(depth)])

        if not with_tags:
            clone_cmd.append("--no-tags")

        clone_cmd.extend([repo_url, str(self.path)])

        logger.info(f"Cloning {repo_url} to {self.path}")
        await run_async(clone_cmd)

        # Checkout ref if specified
        commit_hash = await self._checkout_ref_async(ref)

        self._is_cloned = True
        return commit_hash, str(self.path)

    def _checkout_ref_sync(self, ref: Optional[str] = None) -> str:
        """Checkout a ref synchronously."""
        if not ref:
            # Just get current HEAD
            return run_sync(["git", "rev-parse", "HEAD"], cwd=self.path)

        ref = ref.strip()

        # Fetch the requested ref
        fetch_cmd = ["git", "fetch", "origin", ref]
        if not with_tags:  # Use instance variable
            fetch_cmd.append("--no-tags")

        run_sync(fetch_cmd, cwd=self.path)

        # Checkout FETCH_HEAD (ensures exact commit)
        run_sync(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=self.path)

        # Verify SHA if it looks like one
        if _is_probably_sha(ref):
            head_sha = run_sync(["git", "rev-parse", "HEAD"], cwd=self.path)
            if not head_sha.lower().startswith(ref.lower()):
                raise RuntimeError(
                    f"Checkout verification failed: requested '{ref}' "
                    f"but got '{head_sha}'"
                )

        return run_sync(["git", "rev-parse", "HEAD"], cwd=self.path)

    async def _checkout_ref_async(self, ref: Optional[str] = None) -> str:
        """Checkout a ref asynchronously."""
        if not ref:
            # Just get current HEAD
            return await run_async(["git", "rev-parse", "HEAD"], cwd=self.path)

        ref = ref.strip()

        # Fetch the requested ref
        fetch_cmd = ["git", "fetch", "origin", ref]
        # Note: with_tags instance variable not available here
        # For simplicity, we'll always use --no-tags
        fetch_cmd.append("--no-tags")

        await run_async(fetch_cmd, cwd=self.path)

        # Checkout FETCH_HEAD
        await run_async(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=self.path)

        # Verify SHA if it looks like one
        if _is_probably_sha(ref):
            head_sha = await run_async(["git", "rev-parse", "HEAD"], cwd=self.path)
            if not head_sha.lower().startswith(ref.lower()):
                raise RuntimeError(
                    f"Checkout verification failed: requested '{ref}' "
                    f"but got '{head_sha}'"
                )

        return await run_async(["git", "rev-parse", "HEAD"], cwd=self.path)

    def get_repo_info(self) -> Dict[str, Any]:
        """Get repository information."""
        if not self._is_cloned:
            raise RuntimeError("Repository not cloned yet")

        try:
            remote_url = run_sync(["git", "config", "--get", "remote.origin.url"], cwd=self.path)
            current_branch = run_sync(["git", "branch", "--show-current"], cwd=self.path)
            commit_hash = run_sync(["git", "rev-parse", "HEAD"], cwd=self.path)
            commit_message = run_sync(["git", "log", "-1", "--pretty=%B"], cwd=self.path).strip()

            return {
                "path": str(self.path),
                "remote_url": remote_url,
                "current_branch": current_branch or "DETACHED",
                "commit_hash": commit_hash,
                "commit_message": commit_message,
                "is_detached": not bool(current_branch)
            }
        except Exception as e:
            logger.error(f"Failed to get repo info: {e}")
            raise

    def list_files(self, pattern: str = "*") -> list[str]:
        """List files in repository matching pattern."""
        if not self._is_cloned:
            raise RuntimeError("Repository not cloned yet")

        # Use git ls-files to get tracked files
        files = run_sync(["git", "ls-files"], cwd=self.path).split('\n')

        if pattern != "*":
            import fnmatch
            files = [f for f in files if fnmatch.fnmatch(f, pattern)]

        return [f for f in files if f.strip()]

    def get_file_content(self, filepath: str) -> str:
        """Get content of a file from repository."""
        if not self._is_cloned:
            raise RuntimeError("Repository not cloned yet")

        full_path = self.path / filepath
        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        with open(full_path, 'r', encoding='utf-8') as f:
            return f.read()


# Backward compatibility functions for snapshotter
def clone_and_checkout_sync(
        repo_url: str,
        ref: str,
        workdir: str,
        depth: int = 1,
        with_tags: bool = False
) -> str:
    """Synchronous clone and checkout (backward compatible)."""
    repo = GitRepository(Path(workdir) / "repo")
    commit_hash, _ = repo.clone_and_checkout_sync(
        repo_url=repo_url,
        ref=ref,
        depth=depth,
        with_tags=with_tags
    )
    return commit_hash


async def clone_and_checkout_async(
        repo_url: str,
        ref: str,
        workdir: str,
        depth: int = 1,
        with_tags: bool = False
) -> Tuple[str, str]:
    """Async clone and checkout."""
    repo = GitRepository(Path(workdir) / "repo")
    return await repo.clone_and_checkout_async(
        repo_url=repo_url,
        ref=ref,
        depth=depth,
        with_tags=with_tags
    )