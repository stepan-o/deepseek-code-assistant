# snapshotter/pass2_semantic.py
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from snapshotter.job import Job
from snapshotter.utils import sha256_bytes, utc_ts

# --------------------------------------------------------------------------------------
# Pass 2 Semantic Contract (LOCKED, strict; aligned with pass1.py)
#
# Outputs (LOCKED):
# - PASS2_SEMANTIC.json         (model output + pack fingerprints + strict metadata)
# - PASS2_ARCH_PACK.json        (bounded architecture evidence pack: path->content)
# - PASS2_SUPPORT_PACK.json     (bounded supporting pack: path->content)
# - PASS2_LLM_RAW.txt           (raw model text for inspection on failure)
# - PASS2_LLM_REPAIRED.txt      (optional: repaired JSON text if repair was used)
# --------------------------------------------------------------------------------------

PASS2_SEMANTIC_FILENAME = "PASS2_SEMANTIC.json"
PASS2_ARCH_PACK_FILENAME = "PASS2_ARCH_PACK.json"
PASS2_SUPPORT_PACK_FILENAME = "PASS2_SUPPORT_PACK.json"
PASS2_LLM_RAW_FILENAME = "PASS2_LLM_RAW.txt"
PASS2_LLM_REPAIRED_FILENAME = "PASS2_LLM_REPAIRED.txt"

PASS1_REPO_INDEX_SCHEMA_VERSION = "pass1_repo_index.v1"
PASS2_SEMANTIC_SCHEMA_VERSION = "pass2_semantic.v1"
PASS2_ARCH_PACK_SCHEMA_VERSION = "pass2_arch_pack.v1"
PASS2_SUPPORT_PACK_SCHEMA_VERSION = "pass2_support_pack.v1"


class Pass2SemanticError(RuntimeError):
    pass


class Pass2SemanticLLMOutputError(Pass2SemanticError):
    """
    Raised when the model returns text that cannot be parsed into the required JSON object.
    """

    def __init__(self, message: str, *, raw_text: str, repaired_text: str | None = None):
        super().__init__(message)
        self.raw_text = raw_text
        self.repaired_text = repaired_text


@dataclass(frozen=True)
class SemanticCaps:
    onboarding_enabled: bool
    model: str
    max_output_tokens: int

    # input caps (prevents accidental huge prompts)
    max_arch_input_chars: int
    max_arch_files: int
    max_arch_chars_per_file: int

    # supporting pack caps (gaps + onboarding)
    max_support_files: int
    max_support_chars: int
    max_support_chars_per_file: int

    # pack graph expansion bounds
    pack_dep_hops: int
    pack_max_dep_edges_per_file: int


# -------------------------------------------------------------------
# Deterministic Caps Configuration
# -------------------------------------------------------------------


def _caps_from_job(job: Job) -> SemanticCaps:
    """
    Deterministic caps configuration from Job schema.
    No env fallbacks - Job must provide all caps.
    """
    # Get pass2 config from job, create default if not present
    pass2_config = getattr(job, "pass2", None)

    # Helper to get value with validation
    def get_cap(name: str, default: Any, min_val: Any = None, max_val: Any = None) -> Any:
        # Try to get from pass2 config
        if pass2_config and hasattr(pass2_config, name):
            value = getattr(pass2_config, name)
            if value is not None:
                # Validate type
                if isinstance(default, bool):
                    return bool(value)
                elif isinstance(default, int):
                    try:
                        val = int(value)
                        if min_val is not None:
                            val = max(val, min_val)
                        if max_val is not None:
                            val = min(val, max_val)
                        return val
                    except (ValueError, TypeError):
                        pass
                elif isinstance(default, str):
                    if isinstance(value, str) and value.strip():
                        return value.strip()

        # Use default with validation
        if min_val is not None and isinstance(default, (int, float)):
            default = max(default, min_val)
        if max_val is not None and isinstance(default, (int, float)):
            default = min(default, max_val)
        return default

    # Core LLM configuration
    model = get_cap("model", "gpt-4.1-mini")
    max_output_tokens = get_cap("max_output_tokens", 2000, 256, 20000)
    onboarding_enabled = get_cap("onboarding_enabled", True)

    # Architecture pack caps
    max_arch_files = get_cap("max_arch_files", 120, 1, 240)
    max_arch_input_chars = get_cap("max_arch_input_chars", 240000, 10000, 500000)
    max_arch_chars_per_file = get_cap("max_arch_chars_per_file", 9000, 500, 60000)

    # Support pack caps
    max_support_files = get_cap("max_support_files", 28, 1, 120)
    max_support_chars = get_cap("max_support_chars", 120000, 5000, 300000)
    max_support_chars_per_file = get_cap("max_support_chars_per_file", 9000, 500, 60000)

    # Dependency expansion caps
    pack_dep_hops = get_cap("pack_dep_hops", 1, 0, 4)
    pack_max_dep_edges_per_file = get_cap("pack_max_dep_edges_per_file", 12, 0, 100)

    return SemanticCaps(
        onboarding_enabled=onboarding_enabled,
        model=model,
        max_output_tokens=max_output_tokens,
        max_arch_input_chars=max_arch_input_chars,
        max_arch_files=max_arch_files,
        max_arch_chars_per_file=max_arch_chars_per_file,
        max_support_files=max_support_files,
        max_support_chars=max_support_chars,
        max_support_chars_per_file=max_support_chars_per_file,
        pack_dep_hops=pack_dep_hops,
        pack_max_dep_edges_per_file=pack_max_dep_edges_per_file,
    )


# -------------------------------------------------------------------
# OpenAI Responses API (JSON-only)
# -------------------------------------------------------------------


def _extract_text_from_responses_obj(resp: Any) -> str:
    """Extract text from OpenAI Responses API response."""
    # Try output_text first
    t = getattr(resp, "output_text", None)
    if isinstance(t, str) and t.strip():
        return t

    # Try output list
    out = getattr(resp, "output", None)
    if not isinstance(out, list):
        return ""

    chunks: list[str] = []
    for item in out:
        if isinstance(item, dict):
            item_content = item.get("content")
        else:
            item_content = getattr(item, "content", None)

        if item_content and isinstance(item_content, list):
            for c in item_content:
                if isinstance(c, dict):
                    c_text = c.get("text")
                else:
                    c_text = getattr(c, "text", None)

                if isinstance(c_text, str) and c_text:
                    chunks.append(c_text)
                elif isinstance(c_text, dict):
                    chunks.append(json.dumps(c_text, ensure_ascii=False))

    return "".join(chunks)


def _looks_truncated(text: str) -> bool:
    """Check if JSON looks truncated."""
    s = (text or "").strip()
    if not s:
        return False
    if not s.endswith("}"):
        return True

    in_str = False
    esc = False
    bal = 0
    for ch in s:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            bal += 1
        elif ch == "}":
            bal -= 1
    return bal != 0


def _extract_first_json_object_span(text: str) -> str | None:
    """Extract the first complete JSON object from text."""
    s = text or ""
    start = None

    in_str = False
    esc = False
    bal = 0

    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue

        if ch == '"':
            in_str = True
            continue

        if ch == "{":
            if start is None:
                start = i
            bal += 1
        elif ch == "}":
            if start is not None:
                bal -= 1
                if bal == 0:
                    return s[start : i + 1]
    return None


def _try_parse_json(text: str) -> dict[str, Any]:
    """Attempt to parse JSON, with extraction fallback."""
    text = (text or "").strip()
    if not text:
        raise Pass2SemanticError("OpenAI response was empty; expected a JSON object.")

    # First try direct parse
    try:
        obj = json.loads(text)
        if not isinstance(obj, dict):
            raise Pass2SemanticError("OpenAI response parsed but is not a JSON object.")
        return obj
    except Exception:
        # Try to extract JSON object from surrounding text
        candidate = _extract_first_json_object_span(text)
        if not candidate:
            raise Pass2SemanticError(f"OpenAI response was not valid JSON. First 400 chars:\n{text[:400]}")
        obj = json.loads(candidate)
        if not isinstance(obj, dict):
            raise Pass2SemanticError("Salvaged JSON parsed but is not a JSON object.")
        return obj


def _build_json_repair_prompt(bad_text: str) -> str:
    """Build prompt for JSON repair."""
    return (
            "You are a JSON repair tool.\n"
            "You will be given text that is intended to be a single JSON object, but may contain minor JSON syntax errors.\n"
            "Your task: output ONLY a valid JSON object that preserves the SAME structure and content as closely as possible.\n"
            "Rules:\n"
            "- Output JSON only. No markdown, no commentary.\n"
            "- Do not change top-level keys or semantics.\n"
            "- Only fix syntax (missing commas, quotes, escaping, trailing commas, etc.).\n\n"
            "INPUT (verbatim):\n"
            + (bad_text or "")
    )


def _openai_call_json(*, prompt: str, model: str, max_output_tokens: int, system: str) -> tuple[dict[str, Any], str, str | None]:
    """Call OpenAI API with deterministic retry logic."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise Pass2SemanticError("OPENAI_API_KEY is not set; cannot run pass2 semantic generation.")

    try:
        from openai import OpenAI
    except Exception as e:
        raise Pass2SemanticError(f"openai python SDK not available or too old for Responses API: {e}") from e

    client = OpenAI(api_key=api_key)

    input_payload = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    def _responses_create_text(inp: Any) -> str:
        """Try different API parameter combinations for compatibility."""
        last_err: Exception | None = None
        for attempt_kwargs in (
                {
                    "model": model,
                    "input": inp,
                    "max_output_tokens": max_output_tokens,
                    "text": {"format": {"type": "json_object"}},
                    "temperature": 0,
                },
                {
                    "model": model,
                    "input": inp,
                    "max_output_tokens": max_output_tokens,
                    "text": {"format": {"type": "json_object"}},
                },
                {
                    "model": model,
                    "input": inp,
                    "max_tokens": max_output_tokens,
                    "text": {"format": {"type": "json_object"}},
                },
        ):
            try:
                resp = client.responses.create(**attempt_kwargs)
                return _extract_text_from_responses_obj(resp)
            except TypeError as e:
                last_err = e
                continue
        raise Pass2SemanticError(f"OpenAI Responses API call failed due to incompatible SDK args: {last_err}")

    raw_text: str
    try:
        raw_text = _responses_create_text(input_payload)
    except Exception as e:
        raise Pass2SemanticError(f"OpenAI Responses API call failed: {e}") from e

    try:
        obj = _try_parse_json(raw_text)
        return obj, raw_text, None
    except Exception as parse_err:
        if _looks_truncated(raw_text):
            raise Pass2SemanticLLMOutputError(
                "OpenAI returned truncated/incomplete JSON (likely hit max output tokens). "
                "Increase pass2.max_output_tokens (Job) and retry.\n"
                f"Parse error: {parse_err}\n"
                f"First 400 chars:\n{raw_text[:400]}",
                raw_text=raw_text,
            ) from parse_err

        # Attempt repair
        repair_prompt = _build_json_repair_prompt(raw_text)
        repair_input = [
            {"role": "system", "content": "You are a JSON repair tool. Output JSON only."},
            {"role": "user", "content": repair_prompt},
        ]

        repaired_text: str | None = None
        try:
            repaired_text = _responses_create_text(repair_input)
        except Exception as e:
            raise Pass2SemanticLLMOutputError(
                "OpenAI JSON repair call failed.\n"
                f"First 400 chars of original:\n{raw_text[:400]}",
                raw_text=raw_text,
            ) from e

        try:
            obj2 = _try_parse_json(repaired_text)
            return obj2, raw_text, repaired_text
        except Exception as e:
            raise Pass2SemanticLLMOutputError(
                "Failed to parse OpenAI JSON response (including repair attempt).\n"
                f"Original first 400 chars:\n{raw_text[:400]}",
                raw_text=raw_text,
                repaired_text=repaired_text,
            ) from e


# -------------------------------------------------------------------
# Pass1 Contract Validation
# -------------------------------------------------------------------


def _assert_pass1_repo_index_contract(repo_index: dict[str, Any]) -> None:
    """Validate Pass1 contract assumptions."""
    if not isinstance(repo_index, dict):
        raise Pass2SemanticError("Pass1 contract violation: repo_index must be a dict.")

    if repo_index.get("schema_version") != PASS1_REPO_INDEX_SCHEMA_VERSION:
        raise Pass2SemanticError("Pass1 contract violation: repo_index.schema_version mismatch.")

    job = repo_index.get("job")
    if not isinstance(job, dict):
        raise Pass2SemanticError("Pass1 contract violation: repo_index.job must be a dict.")

    rc = job.get("resolved_commit")
    if not isinstance(rc, str) or not rc.strip() or rc.strip() == "unknown":
        raise Pass2SemanticError("Pass1 contract violation: job.resolved_commit missing/invalid.")

    rp = repo_index.get("read_plan")
    if not isinstance(rp, dict):
        raise Pass2SemanticError("Pass1 contract violation: repo_index.read_plan must be a dict.")

    files = repo_index.get("files")
    if not isinstance(files, list):
        raise Pass2SemanticError("Pass1 contract violation: repo_index.files must be a list.")


def _repo_paths_set(repo_index: dict[str, Any]) -> set[str]:
    """Get set of all file paths in repo index."""
    files = repo_index.get("files", [])
    if not isinstance(files, list):
        return set()

    s: set[str] = set()
    for f in files:
        if isinstance(f, dict):
            p = f.get("path")
            if isinstance(p, str) and p:
                s.add(p)
    return s


def _language_by_path_from_repo_index(repo_index: dict[str, Any]) -> dict[str, str]:
    """Build language mapping from repo index."""
    files = repo_index.get("files", [])
    if not isinstance(files, list):
        return {}

    out: dict[str, str] = {}
    for f in files:
        if isinstance(f, dict):
            p = f.get("path")
            lang = f.get("language")
            if isinstance(p, str) and p and isinstance(lang, str) and lang:
                out[p] = lang.strip()
    return out


def _signals_from_repo_index(repo_index: dict[str, Any]) -> dict[str, Any]:
    """Extract signals from repo index."""
    sig = repo_index.get("signals")
    return sig if isinstance(sig, dict) else {}


def _read_plan_candidates(repo_index: dict[str, Any]) -> list[str]:
    """Extract read plan candidates."""
    rp = repo_index.get("read_plan", {})
    if not isinstance(rp, dict):
        return []

    cands = rp.get("candidates", [])
    if not isinstance(cands, list):
        return []

    out: list[str] = []
    for it in cands:
        if isinstance(it, dict):
            p = it.get("path")
            if isinstance(p, str) and p.strip():
                out.append(p.strip())

    # Deduplicate preserving order
    seen: set[str] = set()
    dedup: list[str] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            dedup.append(p)
    return dedup


def _read_plan_closure_seeds(repo_index: dict[str, Any]) -> list[str]:
    """Extract closure seeds from read plan."""
    rp = repo_index.get("read_plan", {})
    if not isinstance(rp, dict):
        return []

    seeds = rp.get("closure_seeds", [])
    if not isinstance(seeds, list):
        return []

    seen: set[str] = set()
    out: list[str] = []
    for p in seeds:
        if isinstance(p, str) and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _extract_pass1_deps(repo_index: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """
    Extract dependency information from Pass1 repo index.

    Output per file:
      {
        "resolved_internal": set[str],
        "import_edges": list[dict],
        "flags": set[str],
        "language": str|None,
        "top_level_defs": list[str],
        "internal_unresolved_specs": list[str],
      }
    """
    files = repo_index.get("files", [])
    if not isinstance(files, list):
        return {}

    out: dict[str, dict[str, Any]] = {}

    for f in files:
        if not isinstance(f, dict):
            continue

        path = f.get("path")
        if not isinstance(path, str) or not path:
            continue

        deps = f.get("deps", {})
        if not isinstance(deps, dict):
            continue

        edges_raw = deps.get("import_edges", [])
        if not isinstance(edges_raw, list):
            edges_raw = []

        import_edges: list[dict[str, Any]] = []
        resolved_internal: set[str] = set()

        for e in edges_raw:
            if not isinstance(e, dict):
                continue

            spec = e.get("spec")
            resolved_path = e.get("resolved_path")
            is_external = e.get("is_external", True)

            if (isinstance(spec, str) and spec.strip() and
                    isinstance(resolved_path, str) and resolved_path.strip() and
                    not is_external):
                import_edges.append(dict(e))
                resolved_internal.add(resolved_path.strip())

        iu0 = deps.get("internal_unresolved_specs", [])
        internal_unresolved_specs = []
        if isinstance(iu0, list):
            for s in iu0:
                if isinstance(s, str) and s.strip():
                    internal_unresolved_specs.append(s.strip())

        flags_set: set[str] = set()
        fl = f.get("flags")
        if isinstance(fl, list):
            for x in fl:
                if isinstance(x, str) and x.strip():
                    flags_set.add(x.strip())

        lang = f.get("language")
        lang_str = lang.strip() if isinstance(lang, str) else None

        tdefs = f.get("top_level_defs", [])
        top_defs = []
        if isinstance(tdefs, list):
            for x in tdefs:
                if isinstance(x, str) and x.strip():
                    top_defs.append(x.strip())

        out[path] = {
            "resolved_internal": resolved_internal,
            "import_edges": import_edges,
            "flags": flags_set,
            "language": lang_str,
            "top_level_defs": top_defs,
            "internal_unresolved_specs": internal_unresolved_specs,
        }

    return out


# -------------------------------------------------------------------
# Deterministic Pack Selection
# -------------------------------------------------------------------


def _truncate_with_tail(text: str, max_chars: int) -> str:
    """Truncate text with tail preservation."""
    if not isinstance(text, str):
        return ""
    if max_chars <= 0 or len(text) <= max_chars:
        return text

    head = int(max_chars * 0.75)
    tail = max_chars - head
    if tail < 200:
        return text[:max_chars]

    return text[:head] + "\n/* …TRUNCATED… */\n" + text[-tail:]


def _entrypoints_from_signals(repo_index: dict[str, Any], *, available_paths: set[str]) -> list[str]:
    """Extract entrypoints from signals."""
    sig = _signals_from_repo_index(repo_index)
    eps = sig.get("entrypoints", [])
    if not isinstance(eps, list):
        return []

    out: list[str] = []
    for it in eps:
        if isinstance(it, dict):
            p = it.get("path")
            if isinstance(p, str) and p.strip() and p.strip() in available_paths:
                out.append(p.strip())
    return sorted(set(out))


def _candidate_spines_for_known_roots(available_paths: set[str]) -> list[str]:
    """Get known important files for scoring."""
    prefixes = ("", "frontend/", "apps/web/", "apps/frontend/")
    out: list[str] = []

    def add(p: str) -> None:
        if p in available_paths and p not in out:
            out.append(p)

    for pref in prefixes:
        add(f"{pref}middleware.ts")
        add(f"{pref}middleware.js")
        add(f"{pref}app/layout.tsx")
        add(f"{pref}app/layout.ts")
        add(f"{pref}app/page.tsx")
        add(f"{pref}app/page.ts")
        add(f"{pref}next.config.ts")
        add(f"{pref}next.config.js")
        add(f"{pref}package.json")
        add(f"{pref}tsconfig.json")
        add(f"{pref}jsconfig.json")

    for p in ("pyproject.toml", "uv.lock", "alembic.ini", "package.json", "tsconfig.json", "README.md", "readme.md"):
        add(p)

    for p in ("backend/main.py", "backend/app.py", "backend/server.py", "backend/security.py", "backend/config.py"):
        add(p)

    return out


def _compute_available_dep_graph(
        *,
        available_paths: set[str],
        deps_by_file: dict[str, dict[str, Any]],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Build dependency graph from available files."""
    out_edges: dict[str, set[str]] = {p: set() for p in available_paths}
    in_edges: dict[str, set[str]] = {p: set() for p in available_paths}

    for p in available_paths:
        info = deps_by_file.get(p, {})
        resolved = info.get("resolved_internal", set())
        for dep in resolved:
            if dep in available_paths:
                out_edges[p].add(dep)
                in_edges[dep].add(p)

    return out_edges, in_edges


def _expand_seeds_by_deps(
        *,
        seeds: list[str],
        out_edges: dict[str, set[str]],
        hops: int,
        max_added_per_file: int,
) -> list[str]:
    """Expand seed files by dependency hops."""
    if hops <= 0:
        return seeds

    seen: set[str] = set()
    order: list[str] = []

    def _add(p: str) -> None:
        if p not in seen:
            seen.add(p)
            order.append(p)

    for s in seeds:
        _add(s)

    frontier = list(seeds)
    for _ in range(hops):
        nxt: list[str] = []
        for p in frontier:
            deps = sorted(list(out_edges.get(p, set())))
            if max_added_per_file > 0:
                deps = deps[:max_added_per_file]
            for d in deps:
                if d not in seen:
                    _add(d)
                    nxt.append(d)
        frontier = nxt
        if not frontier:
            break

    return order


def _select_pack_paths_for_architecture(
        *,
        file_contents_map: dict[str, str],
        repo_index: dict[str, Any],
        deps_by_file: dict[str, dict[str, Any]],
        caps: SemanticCaps,
) -> tuple[list[str], dict[str, Any]]:
    """Select paths for architecture pack."""
    available_paths = set(file_contents_map.keys())
    if not available_paths:
        raise Pass2SemanticError("pass2: file_contents_map is empty; cannot build LLM evidence pack.")

    entrypoints = _entrypoints_from_signals(repo_index, available_paths=available_paths)
    closure_seeds = [p for p in _read_plan_closure_seeds(repo_index) if p in available_paths]
    read_plan = [p for p in _read_plan_candidates(repo_index) if p in available_paths]
    spines = _candidate_spines_for_known_roots(available_paths)

    # STRICT seed order (deterministic):
    seeds: list[str] = []
    for p in closure_seeds:
        if p not in seeds:
            seeds.append(p)
    for p in read_plan:
        if p not in seeds:
            seeds.append(p)
    for p in entrypoints:
        if p not in seeds:
            seeds.append(p)
    for p in spines:
        if p not in seeds:
            seeds.append(p)

    out_edges, in_edges = _compute_available_dep_graph(available_paths=available_paths, deps_by_file=deps_by_file)

    expanded = _expand_seeds_by_deps(
        seeds=seeds,
        out_edges=out_edges,
        hops=max(0, int(caps.pack_dep_hops)),
        max_added_per_file=max(0, int(caps.pack_max_dep_edges_per_file)),
    )

    lang_by_path = _language_by_path_from_repo_index(repo_index)

    def score(p: str) -> int:
        """Score function for file prioritization."""
        pl = p.lower()
        s = 0

        if p in closure_seeds:
            s += 1200
        if p in read_plan:
            s += 900
        if p in entrypoints:
            s += 800
        if p in spines:
            s += 650

        if pl.endswith(("main.py", "app.py", "server.py")):
            s += 240
        if pl.endswith(("/route.ts", "/route.js", "/page.tsx", "/layout.tsx")):
            s += 220
        if pl.endswith(("middleware.ts", "middleware.js")):
            s += 240
        if "security" in pl or "auth" in pl:
            s += 220

        s += min(80, 10 * len(in_edges.get(p, set())))
        s += min(40, 5 * len(out_edges.get(p, set())))

        if pl.startswith("backend/routers/"):
            s += 220
        if pl.startswith("backend/"):
            s += 60
        if "/app/api/" in pl and pl.endswith(("/route.ts", "/route.js")):
            s += 180

        if pl.startswith(("frontend/lib/", "apps/web/lib/", "apps/frontend/lib/")):
            s += 140
        if pl.startswith(("frontend/components/", "apps/web/components/", "apps/frontend/components/")):
            s += 120

        if pl.endswith("readme.md") or pl == "readme.md":
            s += 200
        if pl.startswith("docs/"):
            s += 120
        if pl.endswith(("pyproject.toml", "alembic.ini", "package.json", "next.config.ts", "next.config.js")):
            s += 160

        lang = lang_by_path.get(p, "")
        if lang in ("python", "typescript", "javascript"):
            s += 10

        return s

    ranked_all = sorted(list(available_paths), key=lambda p: (-score(p), p))

    ordered: list[str] = []
    seen: set[str] = set()

    def push(p: str) -> None:
        if p not in seen:
            seen.add(p)
            ordered.append(p)

    for p in expanded:
        push(p)
    for p in ranked_all:
        push(p)

    selection_debug = {
        "available_files": len(available_paths),
        "closure_seeds_count": len(closure_seeds),
        "read_plan_count": len(read_plan),
        "entrypoints_count": len(entrypoints),
        "spines_count": len(spines),
        "dep_hops": caps.pack_dep_hops,
        "dep_edges_per_file": caps.pack_max_dep_edges_per_file,
        "expanded_count": len(expanded),
    }
    return ordered, selection_debug


def _build_arch_files_pack(
        *,
        ordered_paths: list[str],
        file_contents_map: dict[str, str],
        caps: SemanticCaps,
) -> dict[str, str]:
    """Build architecture pack from ordered paths."""
    out: dict[str, str] = {}
    total = 0

    for p in ordered_paths:
        if len(out) >= caps.max_arch_files:
            break

        c = file_contents_map.get(p, "")
        if not isinstance(c, str) or not c:
            continue

        remaining = caps.max_arch_input_chars - total
        if remaining <= 0:
            break

        c2 = _truncate_with_tail(c, caps.max_arch_chars_per_file)
        if len(c2) > remaining:
            c2 = _truncate_with_tail(c2, remaining)
        if not c2:
            continue

        out[p] = c2
        total += len(c2)

    # ensure minimum breadth deterministically
    floor = min(12, caps.max_arch_files)
    if len(out) < floor:
        for p in ordered_paths:
            if len(out) >= min(24, caps.max_arch_files):
                break
            if p in out:
                continue
            c = file_contents_map.get(p, "")
            if not isinstance(c, str) or not c:
                continue
            remaining = caps.max_arch_input_chars - total
            if remaining <= 0:
                break
            c2 = _truncate_with_tail(c, min(caps.max_arch_chars_per_file, remaining))
            if not c2:
                continue
            out[p] = c2
            total += len(c2)

    return out


def _select_supporting_files_for_gaps_and_onboarding(
        file_contents_map: dict[str, str],
        repo_index: dict[str, Any],
        *,
        max_files: int,
        max_total_chars: int,
        max_chars_per_file: int,
) -> dict[str, str]:
    """Select supporting files for gaps and onboarding."""
    available = set(file_contents_map.keys())
    entrypoints = set(_entrypoints_from_signals(repo_index, available_paths=available))

    closure_seeds = [p for p in _read_plan_closure_seeds(repo_index) if p in available]
    read_plan = [p for p in _read_plan_candidates(repo_index) if p in available]
    spines = _candidate_spines_for_known_roots(available)

    def score(p: str) -> int:
        pl = p.lower()
        s = 0
        if p in closure_seeds:
            s += 1100
        if p in read_plan:
            s += 900
        if p in entrypoints:
            s += 800
        if p in spines:
            s += 650
        if pl.endswith("readme.md") or pl == "readme.md":
            s += 260
        if pl.startswith("docs/") or "/docs/" in pl:
            s += 200
        if pl.endswith(".md"):
            s += 150
        if pl.endswith(("pyproject.toml", "alembic.ini", "uv.lock")):
            s += 140
        if "next.config" in pl or "eslint" in pl:
            s += 110
        if pl.endswith(("package.json", "tsconfig.json", "jsconfig.json")):
            s += 85
        if pl.endswith((".ts", ".tsx", ".py")):
            s += 10
        return s

    ranked = sorted(list(available), key=lambda p: (-score(p), p))

    ordered: list[str] = []
    seen: set[str] = set()

    def push(p: str) -> None:
        if p not in seen:
            seen.add(p)
            ordered.append(p)

    for p in closure_seeds:
        push(p)
    for p in read_plan:
        push(p)
    for p in spines:
        push(p)
    for p in ranked:
        push(p)

    out: dict[str, str] = {}
    total = 0

    for p in ordered:
        if len(out) >= max_files:
            break
        c = file_contents_map.get(p, "")
        if not isinstance(c, str) or not c:
            continue
        remaining = max_total_chars - total
        if remaining <= 0:
            break
        c2 = _truncate_with_tail(c, max_chars_per_file)
        if len(c2) > remaining:
            c2 = _truncate_with_tail(c2, remaining)
        if not c2:
            continue
        out[p] = c2
        total += len(c2)

    return out


# -------------------------------------------------------------------
# File Reading
# -------------------------------------------------------------------


_BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf",
    ".zip", ".gz", ".bz2", ".xz", ".7z",
    ".mp4", ".mov", ".mp3", ".wav",
    ".ttf", ".otf", ".woff", ".woff2",
}


def _read_repo_file_text(repo_dir: str, rel_path: str, *, max_bytes: int) -> str | None:
    """Read file text with binary detection."""
    p = Path(repo_dir) / rel_path
    if not p.exists() or not p.is_file():
        return None
    if p.suffix.lower() in _BINARY_EXTS:
        return None
    try:
        raw = p.read_bytes()
    except Exception:
        return None
    if max_bytes > 0 and len(raw) > max_bytes:
        raw = raw[:max_bytes]
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return None


def _build_file_contents_map(repo_dir: str, repo_index: dict[str, Any], job: Job) -> dict[str, str]:
    """Build map of file contents from repo."""
    max_file_bytes = getattr(job.limits, "max_file_bytes", 0)
    if not isinstance(max_file_bytes, int) or max_file_bytes <= 0:
        max_file_bytes = 512_000  # safe fallback

    files = repo_index.get("files", [])
    if not isinstance(files, list):
        return {}

    out: dict[str, str] = {}
    for f in files:
        if not isinstance(f, dict):
            continue
        rp = f.get("path")
        if not isinstance(rp, str) or not rp:
            continue
        txt = _read_repo_file_text(repo_dir, rp, max_bytes=max_file_bytes)
        if isinstance(txt, str) and txt:
            out[rp] = txt
    return out


# -------------------------------------------------------------------
# LLM Output Validation and Repair
# -------------------------------------------------------------------


def _validate_and_repair_llm_output(obj: dict[str, Any], caps: SemanticCaps, repo_meta: dict[str, Any]) -> dict[str, Any]:
    """
    Validate and repair LLM output to ensure proper schema.
    LLM should NOT output caps - we add them deterministically.
    """
    # Start with expected structure
    result: dict[str, Any] = {
        "schema_version": PASS2_SEMANTIC_SCHEMA_VERSION,
        "generated_at": "ISO8601",  # Will be replaced by parent
        "repo": repo_meta,
        # Caps are added by parent, NOT by LLM
        "summary": {},
        "evidence": {},
    }

    # Extract and validate summary from LLM output
    llm_summary = obj.get("summary")
    if isinstance(llm_summary, dict):
        # Primary stack - allow null or string
        primary_stack = llm_summary.get("primary_stack")
        if primary_stack is None or isinstance(primary_stack, str):
            result["summary"]["primary_stack"] = primary_stack
        else:
            result["summary"]["primary_stack"] = None

        # Architecture overview - must be string
        overview = llm_summary.get("architecture_overview")
        if isinstance(overview, str) and overview.strip():
            result["summary"]["architecture_overview"] = overview.strip()
        else:
            result["summary"]["architecture_overview"] = ""

        # List fields - must be arrays of strings
        for list_field in ["key_components", "data_flows", "auth_and_routing_notes", "risks_or_gaps"]:
            value = llm_summary.get(list_field)
            if isinstance(value, list):
                # Filter to only strings and limit length
                filtered = [str(item) for item in value if isinstance(item, str) and item.strip()]
                result["summary"][list_field] = filtered[:50]  # Reasonable limit
            else:
                result["summary"][list_field] = []

    else:
        # No valid summary from LLM
        result["summary"] = {
            "primary_stack": None,
            "architecture_overview": "",
            "key_components": [],
            "data_flows": [],
            "auth_and_routing_notes": [],
            "risks_or_gaps": [],
        }

    # Extract and validate evidence from LLM output
    llm_evidence = obj.get("evidence")
    if isinstance(llm_evidence, dict):
        # Arch pack paths - must be list of strings
        arch_paths = llm_evidence.get("arch_pack_paths")
        if isinstance(arch_paths, list):
            result["evidence"]["arch_pack_paths"] = [
                str(p) for p in arch_paths if isinstance(p, str) and p.strip()
            ][:100]  # Reasonable limit
        else:
            result["evidence"]["arch_pack_paths"] = []

        # Support pack paths - must be list of strings
        support_paths = llm_evidence.get("support_pack_paths")
        if isinstance(support_paths, list):
            result["evidence"]["support_pack_paths"] = [
                str(p) for p in support_paths if isinstance(p, str) and p.strip()
            ][:100]
        else:
            result["evidence"]["support_pack_paths"] = []

        # Notable files - must be list of dicts with path and why
        notable = llm_evidence.get("notable_files")
        if isinstance(notable, list):
            validated_notable = []
            for item in notable[:50]:  # Reasonable limit
                if isinstance(item, dict):
                    path = item.get("path")
                    why = item.get("why")
                    if isinstance(path, str) and path.strip() and isinstance(why, str) and why.strip():
                        validated_notable.append({
                            "path": path.strip(),
                            "why": why.strip()[:500]  # Limit length
                        })
            result["evidence"]["notable_files"] = validated_notable
        else:
            result["evidence"]["notable_files"] = []

    else:
        # No valid evidence from LLM
        result["evidence"] = {
            "arch_pack_paths": [],
            "support_pack_paths": [],
            "notable_files": [],
        }

    # Remove any caps that LLM might have hallucinated
    result.pop("caps", None)

    return result


# -------------------------------------------------------------------
# Prompt Construction
# -------------------------------------------------------------------


def _build_system_prompt() -> str:
    """Build system prompt for LLM."""
    return (
        "You are Snapshotter Pass2 Semantic - an expert software architect analyzing codebases.\n"
        "You must output ONLY a single JSON object (no markdown, no commentary).\n"
        "The JSON must follow the requested schema strictly.\n"
        "\n"
        "**CRITICAL RULES:**\n"
        "1. For 'generated_at', use the exact string 'ISO8601' (do not replace it).\n"
        "2. DO NOT include a 'caps' field in your output.\n"
        "3. For 'repo', use the provided repo metadata.\n"
        "4. Be concise but insightful in your analysis.\n"
        "5. Reference only files present in the provided packs.\n"
        "\n"
        "If you are unsure about something, use nulls and empty arrays, but keep all required keys present."
    )


def _build_user_prompt(
        *,
        repo_meta: dict[str, Any],
        caps: SemanticCaps,
        pass1_repo_index: dict[str, Any],
        arch_pack: dict[str, str],
        support_pack: dict[str, str],
        deps_by_file: dict[str, dict[str, Any]],
) -> str:
    """Build user prompt for LLM."""
    # Create lightweight dependency summary
    dep_summary: dict[str, Any] = {}
    for p in sorted(deps_by_file.keys())[:50]:  # Limit for prompt size
        info = deps_by_file[p]
        resolved = sorted(list(info.get("resolved_internal", set())))[:5]
        unresolved = info.get("internal_unresolved_specs", [])[:5]

        dep_summary[p] = {
            "resolved_internal_count": len(info.get("resolved_internal", set())),
            "resolved_internal_sample": resolved,
            "internal_unresolved_specs": unresolved[:5] if isinstance(unresolved, list) else [],
            "flags": sorted(list(info.get("flags", set())))[:5],
            "language": info.get("language"),
            "top_level_defs": info.get("top_level_defs", [])[:10],
        }

    # Schema that LLM should follow (WITHOUT caps field)
    schema = {
        "schema_version": PASS2_SEMANTIC_SCHEMA_VERSION,
        "generated_at": "ISO8601",
        "repo": {"repo_url": "string|null", "resolved_commit": "string"},
        "summary": {
            "primary_stack": "string|null",
            "architecture_overview": "string",
            "key_components": ["string"],
            "data_flows": ["string"],
            "auth_and_routing_notes": ["string"],
            "risks_or_gaps": ["string"],
        },
        "evidence": {
            "arch_pack_paths": ["string"],
            "support_pack_paths": ["string"],
            "notable_files": [{"path": "string", "why": "string"}],
        },
    }

    sig = _signals_from_repo_index(pass1_repo_index)
    resolver_inputs = pass1_repo_index.get("resolver_inputs", {})

    payload = {
        "repo_meta": repo_meta,
        "schema": schema,
        "pass1_signals": sig,
        "pass1_resolver_inputs": resolver_inputs,
        "deps_summary": dep_summary,
        "arch_pack_sample": {k: v[:1000] + "..." if len(v) > 1000 else v
                             for k, v in list(arch_pack.items())[:10]},  # Sample only
        "support_pack_sample": {k: v[:1000] + "..." if len(v) > 1000 else v
                                for k, v in list(support_pack.items())[:5]},  # Sample only
        "rules": [
            "Output JSON only - no markdown, no commentary.",
            "Reference only files present in the packs (arch_pack_paths and support_pack_paths).",
            "For 'generated_at', use exactly 'ISO8601' (do not replace with a timestamp).",
            "DO NOT include a 'caps' field in your output.",
            "Be concise: key_components, data_flows, etc. should be bullet-point style strings.",
            "Focus on architecture, data flows, auth/routing patterns, and risks/gaps.",
            "Use the provided repo metadata for the 'repo' field.",
        ],
    }

    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


# -------------------------------------------------------------------
# Artifact Writers
# -------------------------------------------------------------------


def _write_text(path: str | Path, text: str) -> None:
    """Write text file atomically."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = (text or "")
    if payload and not payload.endswith("\n"):
        payload += "\n"
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8", newline="\n")
    os.replace(tmp, p)


def _write_json(path: str | Path, obj: dict[str, Any]) -> None:
    """Write JSON file atomically with deterministic formatting."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8", newline="\n")
    os.replace(tmp, p)


def _stable_json_bytes(obj: Any) -> bytes:
    """Create deterministic JSON bytes for fingerprinting."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8", errors="replace")


def _fingerprint_pack(pack_obj: dict[str, Any]) -> str:
    """Create fingerprint for pack object."""
    return sha256_bytes(_stable_json_bytes(pack_obj))


# -------------------------------------------------------------------
# Public Entrypoint
# -------------------------------------------------------------------


def generate_pass2_semantic_artifacts(
        *,
        repo_dir: str,
        job: Job,
        out_dir: str | Path,
        pass1_repo_index: dict[str, Any],
        repo_url: str | None = None,
) -> dict[str, Any]:
    """
    Pass 2 semantic analysis entrypoint.

    Writes all Pass2 artifacts deterministically.
    """
    # Validate Pass1 contract
    _assert_pass1_repo_index_contract(pass1_repo_index)

    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    # Get deterministic caps from job
    caps = _caps_from_job(job)

    # Determine repo URL (compatibility with callers)
    if isinstance(repo_url, str):
        repo_url = repo_url.strip() or None
    if repo_url is None:
        repo_url = getattr(job, "repo_url", "").strip() or None

    # Get resolved commit from Pass1
    job_block = pass1_repo_index.get("job", {})
    resolved_commit = job_block.get("resolved_commit", "")
    if not isinstance(resolved_commit, str) or not resolved_commit.strip():
        raise Pass2SemanticError("Pass1 repo_index missing resolved_commit")

    repo_meta = {"repo_url": repo_url, "resolved_commit": resolved_commit}

    # Build file contents map
    deps_by_file = _extract_pass1_deps(pass1_repo_index)
    file_contents_map = _build_file_contents_map(repo_dir, pass1_repo_index, job)

    # Select and build packs
    ordered_paths, selection_debug = _select_pack_paths_for_architecture(
        file_contents_map=file_contents_map,
        repo_index=pass1_repo_index,
        deps_by_file=deps_by_file,
        caps=caps,
    )

    arch_files = _build_arch_files_pack(
        ordered_paths=ordered_paths,
        file_contents_map=file_contents_map,
        caps=caps,
    )

    support_files = _select_supporting_files_for_gaps_and_onboarding(
        file_contents_map,
        pass1_repo_index,
        max_files=caps.max_support_files,
        max_total_chars=caps.max_support_chars,
        max_chars_per_file=caps.max_support_chars_per_file,
    )

    # Create and write architecture pack
    arch_pack_obj = {
        "schema_version": PASS2_ARCH_PACK_SCHEMA_VERSION,
        "generated_at": utc_ts(),
        "repo": repo_meta,
        "caps": {
            "max_arch_files": caps.max_arch_files,
            "max_arch_input_chars": caps.max_arch_input_chars,
            "max_arch_chars_per_file": caps.max_arch_chars_per_file,
            "pack_dep_hops": caps.pack_dep_hops,
            "pack_max_dep_edges_per_file": caps.pack_max_dep_edges_per_file,
        },
        "selection_debug": selection_debug,
        "files": {k: arch_files[k] for k in sorted(arch_files.keys())},
    }
    arch_pack_obj["fingerprint_sha256"] = _fingerprint_pack(
        {"repo": arch_pack_obj["repo"], "caps": arch_pack_obj["caps"], "files": arch_pack_obj["files"]}
    )

    # Create and write support pack
    support_pack_obj = {
        "schema_version": PASS2_SUPPORT_PACK_SCHEMA_VERSION,
        "generated_at": utc_ts(),
        "repo": repo_meta,
        "caps": {
            "max_support_files": caps.max_support_files,
            "max_support_chars": caps.max_support_chars,
            "max_support_chars_per_file": caps.max_support_chars_per_file,
        },
        "files": {k: support_files[k] for k in sorted(support_files.keys())},
    }
    support_pack_obj["fingerprint_sha256"] = _fingerprint_pack(
        {"repo": support_pack_obj["repo"], "caps": support_pack_obj["caps"], "files": support_pack_obj["files"]}
    )

    _write_json(out_root / PASS2_ARCH_PACK_FILENAME, arch_pack_obj)
    _write_json(out_root / PASS2_SUPPORT_PACK_FILENAME, support_pack_obj)

    # LLM call with validated output
    system = _build_system_prompt()
    user_prompt = _build_user_prompt(
        repo_meta=repo_meta,
        caps=caps,
        pass1_repo_index=pass1_repo_index,
        arch_pack=arch_pack_obj["files"],
        support_pack=support_pack_obj["files"],
        deps_by_file=deps_by_file,
    )

    obj, raw_text, repaired_text = _openai_call_json(
        prompt=user_prompt,
        model=caps.model,
        max_output_tokens=caps.max_output_tokens,
        system=system,
    )

    _write_text(out_root / PASS2_LLM_RAW_FILENAME, raw_text)
    if repaired_text is not None:
        _write_text(out_root / PASS2_LLM_REPAIRED_FILENAME, repaired_text)

    # Validate and repair LLM output
    cleaned_llm_output = _validate_and_repair_llm_output(obj, caps, repo_meta)

    # Create final Pass2 semantic artifact with deterministic caps
    pass2_semantic = {
        "schema_version": PASS2_SEMANTIC_SCHEMA_VERSION,
        "generated_at": utc_ts(),
        "repo": repo_meta,
        # Caps added DETERMINISTICALLY here, not by LLM
        "caps": {
            "onboarding_enabled": caps.onboarding_enabled,
            "model": caps.model,
            "max_output_tokens": caps.max_output_tokens,
            "max_arch_input_chars": caps.max_arch_input_chars,
            "max_arch_files": caps.max_arch_files,
            "max_arch_chars_per_file": caps.max_arch_chars_per_file,
            "max_support_files": caps.max_support_files,
            "max_support_chars": caps.max_support_chars,
            "max_support_chars_per_file": caps.max_support_chars_per_file,
            "pack_dep_hops": caps.pack_dep_hops,
            "pack_max_dep_edges_per_file": caps.pack_max_dep_edges_per_file,
        },
        "inputs": {
            "pass1_repo_index_schema_version": pass1_repo_index.get("schema_version"),
            "pass1_repo_index_fingerprint_sha256": sha256_bytes(_stable_json_bytes(pass1_repo_index)),
            "arch_pack_fingerprint_sha256": arch_pack_obj.get("fingerprint_sha256"),
            "support_pack_fingerprint_sha256": support_pack_obj.get("fingerprint_sha256"),
        },
        "llm_output": cleaned_llm_output,
        "llm_raw_paths": {
            "raw_text": PASS2_LLM_RAW_FILENAME,
            "repaired_text": PASS2_LLM_REPAIRED_FILENAME if repaired_text is not None else None,
        },
    }

    # Fingerprint the deterministic parts
    fp_obj = {
        "repo": pass2_semantic["repo"],
        "caps": pass2_semantic["caps"],
        "inputs": pass2_semantic["inputs"],
        "llm_output": pass2_semantic["llm_output"],
    }
    pass2_semantic["fingerprint_sha256"] = sha256_bytes(_stable_json_bytes(fp_obj))

    _write_json(out_root / PASS2_SEMANTIC_FILENAME, pass2_semantic)

    return {
        "pass2_semantic_path": str(out_root / PASS2_SEMANTIC_FILENAME),
        "pass2_arch_pack_path": str(out_root / PASS2_ARCH_PACK_FILENAME),
        "pass2_support_pack_path": str(out_root / PASS2_SUPPORT_PACK_FILENAME),
        "pass2_semantic": pass2_semantic,
    }