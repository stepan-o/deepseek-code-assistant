# src/snapshotter/read_plan.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# --------------------------------------------------------------------------------------
# Deterministic Read Plan (Pass1-only inputs) — STRICT CONTRACT (LOCKED)
#
# Snapshotter architecture scope:
# - ReadPlan ranks files to read to understand repo architecture (entrypoints + internals).
# - External dependency inventory / security analysis is OUT OF SCOPE.
#
# REQUIRED Pass1 file-shape invariants for this module:
#   - files: list[dict] where each file has:
#       * path: str
#       * deps.import_edges: list[dict]  (preferred)
#         OR import_edges: list[dict]    (acceptable)
#
# Edge handling rules (LOCKED):
#   - ReadPlan ONLY uses "internal resolved" edges for graph signals:
#       * internal_resolved edge := dict with resolved_path: str (non-empty)
#   - All other edges (sentinel, external, unresolved) are ignored for scoring.
#   - We DO NOT require spec to be non-empty (sentinel may have spec="").
#   - We DO NOT require is_external to exist (Pass1 may include it; ReadPlan doesn't need it).
#
# Output contract:
#   - suggest_files_to_read(...) returns {"max_files_to_read_default": int, "candidates": [...]}
#   - "candidates" is a list of dicts: {"path": str, "score": float, "reasons": [str...]}
#   - No v2 list; downstream closure seeding must use read_plan["candidates"].
# --------------------------------------------------------------------------------------

# Known "app roots" treated as equivalent for scoring/bucketing.
_KNOWN_PREFIXES: tuple[str, ...] = (
    "frontend/",
    "apps/web/",
    "apps/frontend/",
)

_PREFIX_RX = r"(?:frontend/|apps/web/|apps/frontend/)"


def _strip_known_prefix(path: str) -> tuple[str, str]:
    p = (path or "").replace("\\", "/")
    for pref in _KNOWN_PREFIXES:
        if p.startswith(pref):
            return pref, p[len(pref) :]
    return "", p


# --- Pattern-based priorities (frontend/back-end entrypoints + configs; NOT security inventory) ---

HIGH_PATTERNS: list[tuple[re.Pattern[str], int, str]] = [
    # Next.js app router key files
    (re.compile(rf"^(?:{_PREFIX_RX})?app/(layout|page)\.(t|j)sx?$"), 80, "next_root_layout_or_page"),
    (re.compile(rf"^(?:{_PREFIX_RX})?app/.+/(layout|page)\.(t|j)sx?$"), 80, "next_layout_or_page"),
    (re.compile(rf"^(?:{_PREFIX_RX})?app/.+/(error|loading|not-found)\.(t|j)sx?$"), 70, "next_special_file"),
    (re.compile(rf"^(?:{_PREFIX_RX})?app/api/.+/route\.(t|j)s$"), 75, "next_app_api_route"),
    # Next.js pages router
    (re.compile(rf"^(?:{_PREFIX_RX})?pages/(_app|_document)\.(t|j)sx?$"), 75, "next_pages_router_core"),
    (re.compile(rf"^(?:{_PREFIX_RX})?pages/api/.+\.(t|j)s$"), 75, "next_pages_api_route"),
    (re.compile(rf"^(?:{_PREFIX_RX})?pages/index\.(t|j)sx?$"), 65, "next_pages_index"),
    # Middleware + config
    (re.compile(rf"^(?:{_PREFIX_RX})?middleware\.(t|j)s$"), 80, "middleware"),
    (re.compile(r"^next\.config\.(js|mjs|cjs)$"), 60, "next_config"),
    (re.compile(rf"^(?:{_PREFIX_RX})next\.config\.(js|mjs|cjs)$"), 55, "next_config_prefixed"),
    (re.compile(rf"^(?:{_PREFIX_RX})?instrumentation\.(t|j)s$"), 55, "instrumentation"),
    # Backend entrypoints (generic)
    (re.compile(r"(^|/)(main|app|server)\.py$"), 60, "backend_entrypoint"),
    (re.compile(r"(^|/)(routes|routers|controllers)/"), 55, "backend_routing"),
    (re.compile(r"(^|/)(api)/"), 55, "backend_api_dir"),
    # DB / schema / migrations
    (re.compile(r"(^|/)(db|database|models|schemas|schema|entities)/"), 65, "db_schema_models"),
    (re.compile(r"(^|/)migrations?/"), 60, "migrations"),
    (re.compile(r"(^|/)alembic/"), 60, "alembic"),
    (re.compile(r"(^|/)schema\.prisma$"), 70, "prisma_schema"),
    # Contracts / clients / SDK (architecture, not security)
    (re.compile(r"(^|/)(contracts|client|clients|sdk|openapi|swagger)/"), 70, "contract_or_sdk"),
    (re.compile(r"(^|/)(types|interfaces|dto|validators)/"), 55, "types_dto_validators"),
]

NEG_PATTERNS: list[tuple[re.Pattern[str], int, str]] = [
    (re.compile(r"(^|/)__tests__(/|$)"), 60, "tests"),
    (re.compile(r"(^|/)(test|tests)(/|$)"), 60, "tests"),
    (re.compile(r"\.(spec|test)\.(t|j)sx?$"), 60, "tests"),
    (re.compile(r"\.stories\.(t|j)sx?$"), 40, "storybook"),
]

DEFAULT_CAPS = {
    # Caps are keyed by "logical roots" (after stripping known prefixes).
    "app/": 35,
    "pages/": 20,
    "src/": 25,
    "lib/": 25,
    "backend/": 25,
    "api/": 25,
    "server/": 25,
    "other": 9999,
}

DEFAULT_MUST_INCLUDE = [
    rf"^(?:{_PREFIX_RX})?middleware\.(t|j)s$",
    r"^next\.config\.(js|mjs|cjs)$",
    rf"^(?:{_PREFIX_RX})?next\.config\.(js|mjs|cjs)$",
    rf"^(?:{_PREFIX_RX})?app/layout\.(t|j)sx?$",
    rf"^(?:{_PREFIX_RX})?app/page\.(t|j)sx?$",
    rf"^(?:{_PREFIX_RX})?pages/_app\.(t|j)sx?$",
    rf"^(?:{_PREFIX_RX})?pages/_document\.(t|j)sx?$",
]


@dataclass(frozen=True)
class Candidate:
    path: str
    score: float
    reasons: list[str]


def _bucket(path: str) -> str:
    _, stripped = _strip_known_prefix(path)
    for k in ("app/", "pages/", "src/", "lib/", "backend/", "api/", "server/"):
        if stripped.startswith(k):
            return k
    return "other"


def _edges_for_file(f: dict[str, Any]) -> list[dict[str, Any]]:
    """
    STRICT: ReadPlan accepts only evidence-bearing containers from Pass1.
    Looks for:
      - f["deps"]["import_edges"] (preferred)
      - f["import_edges"] (acceptable)
    Container may include sentinel/unresolved edges; ReadPlan will ignore them for scoring.
    """
    deps = f.get("deps")
    if isinstance(deps, dict):
        edges = deps.get("import_edges")
        if isinstance(edges, list):
            return [e for e in edges if isinstance(e, dict)]
    edges2 = f.get("import_edges")
    if isinstance(edges2, list):
        return [e for e in edges2 if isinstance(e, dict)]
    raise RuntimeError("read_plan: file missing deps.import_edges or import_edges (Pass1 contract violation)")


def _internal_resolved_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Internal edge := resolved_path is a non-empty string.
    Everything else (sentinel/external/unresolved) is ignored.
    """
    out: list[dict[str, Any]] = []
    for e in edges:
        rp = e.get("resolved_path")
        if isinstance(rp, str) and rp:
            out.append(e)
    return out


def _assert_files_shape(files: list[dict[str, Any]]) -> list[str]:
    if not isinstance(files, list) or not files:
        raise RuntimeError("read_plan: files must be a non-empty list")

    included_paths: list[str] = []
    for f in files:
        if not isinstance(f, dict):
            raise RuntimeError("read_plan: files must contain dict entries only")
        p = f.get("path")
        if not isinstance(p, str) or not p:
            raise RuntimeError("read_plan: every file must include non-empty 'path' string")
        included_paths.append(p)

        # Require edges container to exist; may contain sentinel/unresolved.
        _ = _edges_for_file(f)

    return included_paths


def _compute_imported_by(files: list[dict[str, Any]], included_paths: list[str]) -> dict[str, int]:
    """
    STRICT fan-in (architecture-only):
      imported_by_count[path] = number of internal-resolved edges whose resolved_path == path
    """
    included_set = set(included_paths)
    imported_by: dict[str, int] = {p: 0 for p in included_paths}

    for f in files:
        edges = _edges_for_file(f)
        for e in _internal_resolved_edges(edges):
            rp = e.get("resolved_path")
            if isinstance(rp, str) and rp in included_set:
                imported_by[rp] = imported_by.get(rp, 0) + 1

    return imported_by


def _imports_count_for_file(f: dict[str, Any]) -> int:
    """
    STRICT fan-out (architecture-only):
      imports_count = number of internal-resolved edges (resolved_path present)
    """
    edges = _edges_for_file(f)
    return len(_internal_resolved_edges(edges))


def _score(path: str, imports_count: int, imported_by_count: int) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    for rx, w, r in HIGH_PATTERNS:
        if rx.search(path):
            score += float(w)
            reasons.append(r)

    for rx, w, r in NEG_PATTERNS:
        if rx.search(path):
            score -= float(w)
            reasons.append(f"deprioritized:{r}")

    # graph-ish signals (deterministic, architecture-only)
    score += 2.0 * float(imports_count)
    score += 10.0 * float(imported_by_count)

    if imports_count == 0 and imported_by_count == 0:
        reasons.append("graph_isolated_or_no_internal_edges")

    return score, reasons


def suggest_files_to_read(
        files: list[dict[str, Any]],
        max_files: int = 120,
        caps: dict[str, int] | None = None,
) -> dict[str, Any]:
    """
    Returns a stable, deterministic selection of top files.

    Output contract:
      {
        "max_files_to_read_default": int,
        "candidates": [
          {"path": str, "score": float, "reasons": [str... (bounded)]},
          ...
        ]
      }
    """
    caps = dict(caps) if caps is not None else dict(DEFAULT_CAPS)

    included_paths = _assert_files_shape(files)
    imported_by = _compute_imported_by(files, included_paths)

    cands: list[Candidate] = []
    for f in files:
        path = f.get("path")
        if not isinstance(path, str) or not path:
            continue

        imports_count = _imports_count_for_file(f)
        score, reasons = _score(path, imports_count, imported_by.get(path, 0))
        cands.append(Candidate(path=path, score=score, reasons=reasons))

    # stable ordering: score desc, then path asc
    cands.sort(key=lambda c: (-c.score, c.path))

    must_include_rx = [re.compile(p) for p in DEFAULT_MUST_INCLUDE]
    picked: list[Candidate] = []
    picked_set: set[str] = set()

    # Ensure bucket_counts covers all buckets we may produce.
    bucket_counts: dict[str, int] = {k: 0 for k in caps.keys()}
    if "other" not in bucket_counts:
        bucket_counts["other"] = 0
        caps.setdefault("other", 9999)

    def try_pick(c: Candidate) -> None:
        b = _bucket(c.path)
        if c.path in picked_set:
            return
        if bucket_counts.get(b, 0) >= caps.get(b, 9999):
            return
        picked.append(c)
        picked_set.add(c.path)
        bucket_counts[b] = bucket_counts.get(b, 0) + 1

    # seed must-include
    for c in cands:
        if any(rx.search(c.path) for rx in must_include_rx):
            try_pick(c)

    # fill remainder under caps
    for c in cands:
        if len(picked) >= int(max_files):
            break
        try_pick(c)

    return {
        "max_files_to_read_default": int(max_files),
        "candidates": [
            {"path": c.path, "score": round(float(c.score), 3), "reasons": c.reasons[:8]}
            for c in picked
        ],
    }
