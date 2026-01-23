# src/snapshotter/git_ops.py
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def run(cmd: list[str], cwd: str | None = None) -> str:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}"
        )
    return p.stdout.strip()


def _is_probably_sha(ref: str) -> bool:
    r = (ref or "").strip()
    if len(r) not in (7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 40):
        return False
    return all(c in "0123456789abcdefABCDEF" for c in r)


def clone_and_checkout(repo_url: str, ref: str, workdir: str) -> str:
    """
    Clone repo into <workdir>/repo and checkout <ref>.

    Contract:
    - If ref is provided and cannot be fetched/checked out, this function MUST raise.
    - No silent fallbacks.

    Determinism notes:
    - Shallow clone + no tags reduces payload variability.
    - Checkout uses FETCH_HEAD in detached mode for exactness.
    """
    workdir_path = Path(workdir).resolve()
    workdir_path.mkdir(parents=True, exist_ok=True)

    repo_dir = workdir_path / "repo"
    if repo_dir.exists():
        shutil.rmtree(repo_dir, ignore_errors=True)

    # Clone using absolute destination; no cwd tricks -> no double nesting.
    # --no-tags keeps clone small and avoids tag-related variability.
    run(["git", "clone", "--depth", "1", "--no-tags", repo_url, str(repo_dir)], cwd=None)

    requested = (ref or "").strip()
    if requested:
        # Fetch the requested ref into FETCH_HEAD (works for branch/tag/SHA when resolvable).
        # If this fails, raise with full stdout/stderr (from run()).
        run(
            ["git", "fetch", "--depth", "1", "--no-tags", "origin", requested],
            cwd=str(repo_dir),
        )

        # Checkout exactly what we fetched. This avoids "pathspec not found" for remote branches.
        run(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=str(repo_dir))

        # If user passed a SHA, ensure we actually landed on it (or its prefix).
        if _is_probably_sha(requested):
            head = run(["git", "rev-parse", "HEAD"], cwd=str(repo_dir))
            if not head.lower().startswith(requested.lower()):
                raise RuntimeError(
                    f"Checkout verification failed: requested_ref looks like SHA '{requested}' "
                    f"but HEAD is '{head}'."
                )

    resolved_commit = run(["git", "rev-parse", "HEAD"], cwd=str(repo_dir))
    return resolved_commit
