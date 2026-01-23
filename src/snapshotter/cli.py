# src/snapshotter/cli.py
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Tuple

from . import __version__
from . import main as main_module

STAGE_PARSE_JOB = "parse_job"


def _strip_wrapping_quotes(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
        return v[1:-1]
    return v


def _parse_dotenv_line(line: str) -> tuple[str, str] | None:
    """
    Minimal .env parser (deterministic, no external deps).
    Supports:
      - KEY=VALUE
      - export KEY=VALUE
      - comments (#...) when not inside quotes
      - quoted values with '...' or "..."
    Does NOT do variable expansion (${...}) by design.
    """
    s = line.strip()
    if not s or s.startswith("#"):
        return None

    if s.startswith("export "):
        s = s[len("export ") :].lstrip()
        if not s:
            return None

    if "=" not in s:
        return None

    key, rest = s.split("=", 1)
    key = key.strip()
    if not key:
        return None

    # Drop inline comments only when they are not within quotes.
    val = rest.strip()
    if not val:
        return key, ""

    if val[0] in ("'", '"'):
        quote = val[0]
        out = []
        escaped = False
        # consume the starting quote
        i = 1
        while i < len(val):
            ch = val[i]
            if escaped:
                out.append(ch)
                escaped = False
            else:
                if quote == '"' and ch == "\\":  # allow escapes in double-quotes
                    escaped = True
                elif ch == quote:
                    # end quote
                    i += 1
                    break
                else:
                    out.append(ch)
            i += 1
        value = "".join(out)
        # ignore anything after closing quote (including comments)
        return key, value

    # unquoted: strip trailing comment
    out2 = []
    for ch in val:
        if ch == "#":
            break
        out2.append(ch)
    value2 = "".join(out2).strip()
    return key, value2


def _load_dotenv_file(path: str, *, override: bool = False) -> bool:
    """
    Loads key/value pairs from a .env file into os.environ.
    Returns True if the file existed and was read.
    """
    p = Path(path)
    if not p.exists() or not p.is_file():
        return False

    for raw_line in p.read_text(encoding="utf-8").splitlines():
        parsed = _parse_dotenv_line(raw_line)
        if not parsed:
            continue
        k, v = parsed
        if not override and k in os.environ:
            continue
        os.environ[k] = v
    return True


def _read_job_payload_required(payload_src_hint: str | None) -> tuple[dict[str, Any], str]:
    """
    Contract (hard):
      - Canonical job input is SNAPSHOTTER_JOB_JSON (env JSON string).
      - For LOCAL runs only, env may be populated from a .env file if explicitly requested via CLI.
      - No file paths for job payload itself, no stdin. (.env is only for setting env vars.)

    Returns: (payload_dict, payload_src_string)
    """
    raw = os.environ.get("SNAPSHOTTER_JOB_JSON")
    if not raw or not raw.strip():
        raise RuntimeError("Missing required job payload: set SNAPSHOTTER_JOB_JSON to a JSON object string.")

    payload = json.loads(raw)

    if not isinstance(payload, dict):
        raise TypeError("SNAPSHOTTER_JOB_JSON must decode to a JSON object (dict).")

    src = payload_src_hint or "env:SNAPSHOTTER_JOB_JSON"
    return payload, src


def _print_success(obj: dict[str, Any]) -> None:
    # Keep output schema stable: graph result is already structured.
    print(json.dumps(obj, separators=(",", ":")), file=sys.stdout)


def _print_failure(stage: str, err: Exception) -> None:
    out = {
        "ok": False,
        "stage": stage,
        "error_code": f"SNAPSHOTTER_FAILED_{stage.upper()}",
        "error_message": str(err),
    }
    print(json.dumps(out, separators=(",", ":")), file=sys.stdout)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="snapshotter",
        description="Repo Snapshotter (graph-only)",
    )
    parser.add_argument(
        "--dotenv",
        nargs="?",
        const=".env",
        default=None,
        metavar="PATH",
        help="Optional: load env vars from a local .env file (default: ./.env).",
    )
    parser.add_argument(
        "--dotenv-override",
        action="store_true",
        help="Optional: allow .env values to override already-set environment variables.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run in dry-run mode (no side effects).",
    )
    parser.add_argument(
        "--aws-region",
        dest="aws_region",
        metavar="REGION",
        help="Optional AWS region override (otherwise AWS_REGION/AWS_DEFAULT_REGION are used).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"snapshotter {__version__}",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Contract: dry_run is CLI-controlled only (no env fallback).
    dry_run = bool(args.dry_run)

    # Optional local convenience: load .env ONLY if explicitly requested.
    payload_src_hint: str | None = None
    had_payload_before = bool(os.environ.get("SNAPSHOTTER_JOB_JSON", "").strip())

    if args.dotenv:
        loaded = _load_dotenv_file(str(args.dotenv), override=bool(args.dotenv_override))
        if loaded and not had_payload_before and bool(os.environ.get("SNAPSHOTTER_JOB_JSON", "").strip()):
            payload_src_hint = f"dotenv:{args.dotenv}#SNAPSHOTTER_JOB_JSON"

    try:
        payload, payload_src = _read_job_payload_required(payload_src_hint)

        result = main_module.run(
            job_payload=payload,
            dry_run=dry_run,
            payload_src=payload_src,
            aws_region=args.aws_region,
        )
        _print_success(result)
        return 0

    except Exception as e:  # noqa: BLE001 - top-level CLI error handler
        # If graph surfaced a stage-aware error, render it.
        try:
            from snapshotter.graph import SnapshotterStageError  # type: ignore
        except Exception:
            SnapshotterStageError = None  # type: ignore

        if SnapshotterStageError is not None and isinstance(e, SnapshotterStageError):
            _print_failure(e.stage, e)
            return 1

        # Payload / argument issues are parse_job
        if isinstance(e, (json.JSONDecodeError, RuntimeError, TypeError)):
            _print_failure(STAGE_PARSE_JOB, e)
            return 1

        # Everything else: unknown stage
        _print_failure("unknown", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
