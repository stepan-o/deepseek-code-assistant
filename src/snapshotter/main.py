# src/snapshotter/main.py
from __future__ import annotations

import os
from typing import Any, Dict, Optional


def _discover_aws_region(explicit: Optional[str] = None) -> Optional[str]:
    if explicit:
        return explicit
    # default region discovery (AWS commonly sets one of these)
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or None


def run(
        job_payload: Dict[str, Any],
        dry_run: bool = False,
        *,
        payload_src: str = "unknown",
        aws_region: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Core entrypoint used by snapshotter.cli.

    This repo is graph-only: snapshotter.graph owns the full workflow
    (clone → pass1 → pass2 semantic → manifest → validate → upload → emit result).

    No dotenv, no "linear vs graph" switch, no Replit-only codepaths.
    """
    aws_region = _discover_aws_region(aws_region)

    from snapshotter.graph import run_snapshotter_graph

    # Let SnapshotterStageError bubble up so the CLI can render stage-aware JSON.
    return run_snapshotter_graph(
        payload=job_payload,
        payload_src=payload_src,
        dry_run=dry_run,
        aws_region=aws_region,
    )
