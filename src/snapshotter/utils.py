# src/snapshotter/utils.py
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any


def utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()


def sha256_text(s: str) -> str:
    return sha256_bytes(s.encode("utf-8"))


def is_probably_binary(data: bytes, *, sample_size: int = 8192, min_utf8_ratio: float = 0.85) -> bool:
    """
    Deterministic binary heuristic:
      - If sample contains NUL bytes -> binary.
      - Else, if UTF-8 "ignore" decoding preserves too little -> binary.

    min_utf8_ratio is:
      preserved_bytes / sample_bytes
    where preserved_bytes is len(decoded.encode("utf-8")) after decoding with errors="ignore".
    """
    if not data:
        return False

    sample = data[:sample_size]

    if b"\x00" in sample:
        return True

    # If it decodes as UTF-8 cleanly, treat as text.
    try:
        sample.decode("utf-8")
        return False
    except UnicodeDecodeError:
        pass

    decoded = sample.decode("utf-8", errors="ignore")
    preserved = len(decoded.encode("utf-8"))
    ratio = preserved / max(1, len(sample))
    return ratio < min_utf8_ratio


def repo_slug_from_url(repo_url: str) -> str:
    # "https://github.com/org/repo.git" -> "org__repo"
    s = repo_url.rstrip("/")
    s = re.sub(r"\.git$", "", s)
    parts = s.split("/")
    if len(parts) >= 2:
        return f"{parts[-2]}__{parts[-1]}"
    return re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()


def getenv(name: str, default: str | None = None) -> str | None:
    # Thin wrapper kept for legacy internal callers; does not add fallback behavior.
    v = os.getenv(name)
    return v if v is not None else default


# -----------------------------
# Stable fingerprint helpers
# -----------------------------
# These helpers are used to build deterministic IDs and artifact fingerprints.
# They MUST be stable across processes/reruns for the same logical input.

VOLATILE_KEYS_DEFAULT: set[str] = {
    "generated_at",
    "job_id",
    "timestamp_utc",
    "repo_slug",
    # resolved_commit is derived at runtime; callers may choose to include it in their own
    # fingerprint by passing a custom volatile_keys set that does NOT strip it.
    "resolved_commit",
}


def _strip_volatile(obj: Any, volatile_keys: set[str]) -> Any:
    """
    Recursively remove volatile keys from dicts/lists.
    Used to build stable fingerprints across reruns.
    """
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k in volatile_keys:
                continue
            out[k] = _strip_volatile(v, volatile_keys)
        return out
    if isinstance(obj, list):
        return [_strip_volatile(x, volatile_keys) for x in obj]
    return obj


def stable_json_dumps(obj: Any) -> str:
    """
    Deterministic JSON serialization for JSON-like objects.
    - sort keys
    - stable separators
    - no ASCII-forcing (keep unicode stable)
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def stable_json_fingerprint_sha256(obj: Any, volatile_keys: set[str] | None = None) -> str:
    """
    Stable hash for JSON-like objects where only volatile keys differ between reruns.
    - strips volatile keys recursively
    - canonicalizes JSON (sort_keys + stable separators)
    """
    vk = set(VOLATILE_KEYS_DEFAULT) if volatile_keys is None else set(volatile_keys)
    stripped = _strip_volatile(obj, vk)
    canonical = stable_json_dumps(stripped)
    return sha256_text(canonical)


# -----------------------------
# Deterministic normalization helpers
# -----------------------------

_PATH_SEP_RE = re.compile(r"[\\]+")


def norm_relpath(path: str) -> str:
    """
    Deterministic path normalization for Snapshotter artifacts.
    - converts backslashes to forward slashes
    - strips leading "./" and leading "/"
    - collapses duplicate slashes
    - does NOT resolve ".." (callers should reject parent traversal elsewhere)
    """
    p = (path or "").strip()
    p = _PATH_SEP_RE.sub("/", p)
    while p.startswith("./"):
        p = p[2:]
    p = p.lstrip("/")
    p = re.sub(r"/{2,}", "/", p)
    return p


def assert_no_parent_traversal(path: str) -> None:
    """
    Hard contract: artifacts must not reference parent traversal paths.
    """
    p = norm_relpath(path)
    if p == ".." or p.startswith("../") or "/../" in f"/{p}/":
        raise ValueError(f"Illegal path traversal segment in path: {path!r}")
