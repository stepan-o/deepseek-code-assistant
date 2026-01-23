# snapshotter/pass1.py
from __future__ import annotations

import ast
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from snapshotter.job import Job

# deterministic read-plan suggestions
from snapshotter.read_plan import suggest_files_to_read
from snapshotter.utils import is_probably_binary, sha256_bytes, utc_ts

try:
    import tomllib  # py3.11+
except Exception:  # pragma: no cover
    tomllib = None  # type: ignore

# --------------------------------------------------------------------------------------
# Pass 1 Contract (LOCKED, strict)
#
# Pass 1 MUST produce two first-class artifacts derived deterministically from the repo:
#   1) PASS1_REPO_INDEX.json   (scan facts + indexes + read plan block)
#   2) DEPENDENCY_GRAPH.json   (derived solely from PASS1_REPO_INDEX.import_index.by_path)
#
# Snapshotter is a single controlled system:
# - No back-compat schema paths.
# - No "try a few locations" for config caps.
# - No fallback heuristics that guess internal vs external beyond explicit rules.
#
# Language scope (LOCKED):
# - Pass1 parses imports ONLY for: python, typescript, javascript.
# - Non-supported languages are still included in files[] but import parsing is not performed.
#
# Architecture scope (LOCKED):
# - Snapshotter models ONLY repo-internal dependency structure for closure + read plan.
# - External dependency inventory / security dependency analysis is OUT OF SCOPE.
#
# ReadPlan compatibility requirement (LOCKED):
# - Every included file MUST carry deps.import_edges as a deterministic list (may be empty).
# - deps.import_edges MUST contain ONLY resolved internal edges:
#       {kind, spec, lineno, resolved_path, is_external=False}
# - Internal unresolved imports are recorded ONLY under deps.internal_unresolved_specs
#   and MUST NOT appear as edges.
# --------------------------------------------------------------------------------------

PASS1_REPO_INDEX_FILENAME = "PASS1_REPO_INDEX.json"
DEPENDENCY_GRAPH_FILENAME = "DEPENDENCY_GRAPH.json"

PASS1_REPO_INDEX_SCHEMA_VERSION = "pass1_repo_index.v1"
DEPENDENCY_GRAPH_SCHEMA_VERSION = "dependency_graph.v1"

LANG_BY_EXT = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".json": "json",
    ".md": "markdown",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
}

SUPPORTED_IMPORT_LANGS = {"python", "typescript", "javascript"}

# --------------------------------------------------------------------------------------
# JS/TS import extraction (regex + comment stripping; deterministic)
# --------------------------------------------------------------------------------------

JS_ANY_IMPORT_EXPORT_FROM_RE = re.compile(
    r"""(?msx)
    ^\s*
    (?P<kw>import|export)\s+
    (?:type\s+)?                 # "import type ..." / "export type ..."
    (?:[\s\S]*?)                 # bindings (may be multiline)
    \sfrom\s*
    ["'](?P<spec>[^"']+)["']\s*;?
    """
)

JS_IMPORT_SIDE_EFFECT_RE = re.compile(
    r"""(?mx)
    ^\s*import\s*["'](?P<spec>[^"']+)["']\s*;?
    """
)

JS_DYNAMIC_IMPORT_RE = re.compile(r"""\bimport\s*\(\s*["'](?P<spec>[^"']+)["']\s*\)""")
JS_REQUIRE_RE = re.compile(r"""\brequire\s*\(\s*["'](?P<spec>[^"']+)["']\s*\)""")

TS_IMPORT_ASSIGN_REQUIRE_RE = re.compile(
    r"""(?mx)
    ^\s*import\s+[A-Za-z_\$][\w\$]*\s*=\s*require\s*\(\s*["'](?P<spec>[^"']+)["']\s*\)\s*;?
    """
)

JS_TOP_DEF_RE = re.compile(
    r"""(?mx)
    ^\s*
    (?:export\s+(?:default\s+)?)?
    (?:declare\s+)?                 # TS
    (?:async\s+)?                   # async function
    (?:
        function\s+([A-Za-z_\$][\w\$]*)
      | class\s+([A-Za-z_\$][\w\$]*)
      | (?:const|let|var)\s+([A-Za-z_\$][\w\$]*)\s*=
      | interface\s+([A-Za-z_\$][\w\$]*)      # TS
      | type\s+([A-Za-z_\$][\w\$]*)\s*=       # TS
      | enum\s+([A-Za-z_\$][\w\$]*)           # TS
    )
    """
)

# ------------------------------------------------------------
# TS/JS path alias + module resolution
# ------------------------------------------------------------

JS_RESOLVE_EXTS = (
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".d.ts",
    ".json",
)

# Config locations are bounded + deterministic. No globbing.
CONFIG_CANDIDATES = (
    "tsconfig.json",
    "jsconfig.json",
    "frontend/tsconfig.json",
    "frontend/jsconfig.json",
    "frontend/tsconfig.base.json",
    "frontend/tsconfig.app.json",
    "frontend/tsconfig.build.json",
    "frontend/tsconfig.node.json",
    "frontend/tsconfig.shared.json",
    "apps/web/tsconfig.json",
    "apps/frontend/tsconfig.json",
    "packages/ui/tsconfig.json",
)

# -----------------------------
# Environment variable extraction (kept as general repo signal, NOT security inventory)
# -----------------------------
PY_ENV_PATTERNS = [
    re.compile(r"""\bos\.getenv\(\s*["']([A-Z0-9_]+)["']"""),
    re.compile(r"""\bos\.environ\.get\(\s*["']([A-Z0-9_]+)["']"""),
    re.compile(r"""\bos\.environ\[\s*["']([A-Z0-9_]+)["']\s*\]"""),
]

JS_ENV_PATTERNS = [
    re.compile(r"""\bprocess\.env\.([A-Z0-9_]+)\b"""),
    re.compile(r"""\bprocess\.env\[\s*["']([A-Z0-9_]+)["']\s*\]"""),
]

# -----------------------------
# Routing/auth hints (kept only for closure seeding, NOT security analysis)
# -----------------------------
NEXT_MW_MATCHER_RE = re.compile(r"""(?ms)\bmatcher\s*:\s*(\[[^\]]*\])""")
NEXT_PROTECTED_LIST_RE = re.compile(
    r"""(?ms)\b(PROTECTED|PROTECTED_PATHS|protectedPaths|adminPaths)\b[^{=\n]*[=:]\s*(\[[^\]]*\])"""
)

FRONTEND_LOGIN_RE = re.compile(r"""(?i)\b(/login|/signin|sign[-_ ]?in)\b""")
FRONTEND_AUTH_ME_RE = re.compile(r"""\b/auth/me\b""")
FRONTEND_COOKIE_NAME_RE = re.compile(
    r"""(?mx)
    \b(?:cookie(?:Name)?|COOKIE_NAME|AUTH_COOKIE|ACCESS_TOKEN_COOKIE)\b
    [^=\n]{0,80}
    =
    [^;\n]{0,120}
    """
)

PY_DEPENDS_RE = re.compile(r"""\bDepends\s*\(\s*([A-Za-z0-9_\.]+)\s*\)""")
PY_GET_CURRENT_RE = re.compile(r"""\bget_current_[A-Za-z0-9_]+\b""")
PY_AUTH_PATH_RE = re.compile(r"""\b/auth/(me|login|signin|refresh|logout)\b""")


def infer_language(path: str) -> str:
    ext = Path(path).suffix.lower()
    return LANG_BY_EXT.get(ext, "unknown")


def _lineno_from_index(text: str, idx: int) -> int:
    if idx <= 0:
        return 1
    return text.count("\n", 0, idx) + 1


# --------------------------------------------------------------------------------------
# Python parsing
# --------------------------------------------------------------------------------------
def parse_python_defs_and_imports(text: str) -> tuple[list[str], list[str]]:
    """
    Best-effort defs + unique import module tokens.
    Used ONLY as a fallback for top_defs + imports_raw when AST edge extraction fails.
    """
    defs: list[str] = []
    imports: list[str] = []
    try:
        tree = ast.parse(text)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defs.append(node.name)
            elif isinstance(node, ast.Import):
                for n in node.names:
                    imports.append(n.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
    except Exception:
        pass
    return defs, sorted(set(imports))


def parse_python_import_edges(text: str) -> tuple[list[str], list[dict[str, Any]]]:
    """
    Evidence-bearing import edges for python.
    Returns:
      - top_defs
      - import_edges: [{kind, spec, lineno}]
    """
    defs: list[str] = []
    edges: list[dict[str, Any]] = []
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defs.append(node.name)
        elif isinstance(node, ast.Import):
            for n in node.names:
                spec = n.name
                if spec:
                    edges.append({"kind": "import", "spec": spec, "lineno": int(getattr(node, "lineno", 1) or 1)})
        elif isinstance(node, ast.ImportFrom):
            level = int(getattr(node, "level", 0) or 0)
            mod = getattr(node, "module", None)
            spec = ("." * level) + (mod or "")
            spec = spec if spec else ("." * level) if level else ""
            if spec:
                edges.append({"kind": "from_import", "spec": spec, "lineno": int(getattr(node, "lineno", 1) or 1)})

    edges.sort(key=lambda e: (int(e.get("lineno", 1)), str(e.get("kind", "")), str(e.get("spec", ""))))
    return sorted(set(defs)), edges


# --------------------------------------------------------------------------------------
# JS/TS parsing
# --------------------------------------------------------------------------------------
def strip_js_ts_comments(text: str) -> str:
    """
    Remove // and /* */ comments while preserving newlines and string contents.
    Preserve newlines so match.start() -> lineno remains stable.
    """
    out: list[str] = []
    i = 0
    n = len(text)

    in_line = False
    in_block = False
    in_s = False
    in_d = False
    in_t = False
    esc = False

    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if in_line:
            if c == "\n":
                in_line = False
                out.append("\n")
            else:
                out.append(" ")
            i += 1
            continue

        if in_block:
            if c == "*" and nxt == "/":
                in_block = False
                out.append("  ")
                i += 2
            else:
                out.append("\n" if c == "\n" else " ")
                i += 1
            continue

        if in_s:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == "'":
                in_s = False
            i += 1
            continue

        if in_d:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_d = False
            i += 1
            continue

        if in_t:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == "`":
                in_t = False
            i += 1
            continue

        if c == "/" and nxt == "/":
            in_line = True
            out.append("  ")
            i += 2
            continue

        if c == "/" and nxt == "*":
            in_block = True
            out.append("  ")
            i += 2
            continue

        if c == "'":
            in_s = True
            out.append(c)
            i += 1
            continue

        if c == '"':
            in_d = True
            out.append(c)
            i += 1
            continue

        if c == "`":
            in_t = True
            out.append(c)
            i += 1
            continue

        out.append(c)
        i += 1

    return "".join(out)


def parse_js_ts_import_edges(text: str) -> tuple[list[str], list[dict[str, Any]]]:
    """
    Evidence-bearing JS/TS import edges.
    Returns:
      - top_defs
      - import_edges: [{kind, spec, lineno}]
    """
    cleaned = strip_js_ts_comments(text)
    edges: list[dict[str, Any]] = []

    for m in JS_IMPORT_SIDE_EFFECT_RE.finditer(cleaned):
        spec = m.group("spec")
        if spec:
            edges.append({"kind": "side_effect_import", "spec": spec, "lineno": _lineno_from_index(cleaned, m.start())})

    for m in JS_ANY_IMPORT_EXPORT_FROM_RE.finditer(cleaned):
        kw = (m.group("kw") or "").strip()
        spec = m.group("spec")
        if spec:
            edges.append(
                {
                    "kind": "export_from" if kw == "export" else "static_import",
                    "spec": spec,
                    "lineno": _lineno_from_index(cleaned, m.start()),
                }
            )

    for m in TS_IMPORT_ASSIGN_REQUIRE_RE.finditer(cleaned):
        spec = m.group("spec")
        if spec:
            edges.append({"kind": "import_assign_require", "spec": spec, "lineno": _lineno_from_index(cleaned, m.start())})

    for m in JS_DYNAMIC_IMPORT_RE.finditer(cleaned):
        spec = m.group("spec")
        if spec:
            edges.append({"kind": "dynamic_import", "spec": spec, "lineno": _lineno_from_index(cleaned, m.start())})

    for m in JS_REQUIRE_RE.finditer(cleaned):
        spec = m.group("spec")
        if spec:
            edges.append({"kind": "require", "spec": spec, "lineno": _lineno_from_index(cleaned, m.start())})

    defs: set[str] = set()
    for m in JS_TOP_DEF_RE.finditer(cleaned):
        for g in m.groups():
            if g and isinstance(g, str):
                defs.add(g)

    edges.sort(key=lambda e: (int(e.get("lineno", 1)), str(e.get("kind", "")), str(e.get("spec", ""))))
    return sorted(defs), edges


# --------------------------------------------------------------------------------------
# Config parsing + helpers
# --------------------------------------------------------------------------------------
def _strip_jsonc(text: str) -> str:
    return strip_js_ts_comments(text)


def _load_jsonc_file(abs_path: Path) -> dict[str, Any] | None:
    try:
        raw = abs_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    cleaned = _strip_jsonc(raw).strip()
    if not cleaned:
        return None
    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _normalize_rel_path(p: str) -> str:
    return p.replace("\\", "/").lstrip("./")


def _resolve_tsconfig_extends_path(current_cfg: Path, extends_value: str) -> Path | None:
    v = (extends_value or "").strip()
    if not v:
        return None

    # Only local file resolution here; no package-based extends.
    if not v.startswith(("./", "../", "/")):
        return None

    cand = v
    if not Path(cand).suffix:
        cand = cand + ".json"

    if cand.startswith("/"):
        p = Path(cand)
    else:
        p = current_cfg.parent / cand

    try:
        p = p.resolve()
    except Exception:
        pass

    if p.exists() and p.is_file():
        return p
    return None


def _load_tsconfig_with_extends(cfg_path: Path, *, max_depth: int = 6) -> list[Path]:
    chain: list[Path] = []
    visited: set[str] = set()

    cur: Path | None = cfg_path
    depth = 0
    while cur and depth < max_depth:
        key = str(cur)
        if key in visited:
            break
        visited.add(key)

        obj = _load_jsonc_file(cur)
        if not obj:
            break

        chain.append(cur)

        ext = obj.get("extends")
        if isinstance(ext, str) and ext.strip():
            nxt = _resolve_tsconfig_extends_path(cur, ext)
            if nxt is None:
                break
            cur = nxt
            depth += 1
            continue
        break

    return list(reversed(chain))


def _merge_tsconfig_compiler_options(chain_paths: list[Path]) -> tuple[str | None, dict[str, list[str]]]:
    merged_base_url: str | None = None
    merged_paths: dict[str, list[str]] = {}

    for p in chain_paths:
        obj = _load_jsonc_file(p)
        if not obj:
            continue
        co = obj.get("compilerOptions")
        if not isinstance(co, dict):
            continue

        bu = co.get("baseUrl")
        if isinstance(bu, str) and bu.strip():
            merged_base_url = bu.strip()

        ps = co.get("paths")
        if isinstance(ps, dict):
            for k, v in ps.items():
                if not isinstance(k, str) or not k.strip():
                    continue
                if isinstance(v, list):
                    vv = [x for x in v if isinstance(x, str) and x.strip()]
                    if vv:
                        merged_paths[k] = vv

    return merged_base_url, merged_paths


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _bounded_list_subdirs(root: Path, *, max_items: int = 200) -> list[Path]:
    if not root.exists() or not root.is_dir():
        return []
    try:
        names = sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.name)
    except Exception:
        return []
    return names[:max_items]


def _collect_workspace_packages(repo_dir: str) -> dict[str, Any]:
    """
    Deterministically build a map:
      - package name -> package root rel dir (dir containing its package.json)
    from root package.json workspaces ONLY.
    """
    repo_root = Path(repo_dir)
    roots_scanned: list[str] = []
    name_to_dir: dict[str, str] = {}

    root_pkg = repo_root / "package.json"
    root_obj = _read_json_if_exists(root_pkg) if root_pkg.exists() else None

    patterns: list[str] = []
    if isinstance(root_obj, dict):
        ws = root_obj.get("workspaces")
        if isinstance(ws, list):
            patterns.extend([str(x) for x in ws if isinstance(x, str)])
        elif isinstance(ws, dict):
            pkgs = ws.get("packages")
            if isinstance(pkgs, list):
                patterns.extend([str(x) for x in pkgs if isinstance(x, str)])

    def add_pkg(pkg_json: Path) -> None:
        obj = _read_json_if_exists(pkg_json)
        if not isinstance(obj, dict):
            return
        name = obj.get("name")
        if not isinstance(name, str) or not name.strip():
            return
        try:
            rel_dir = os.path.relpath(str(pkg_json.parent), repo_dir)
        except Exception:
            rel_dir = pkg_json.parent.as_posix()
        rel_dir = _normalize_rel_path(rel_dir)
        if name not in name_to_dir:
            name_to_dir[name] = rel_dir

    for pat in patterns:
        pat = (pat or "").strip()
        if not pat or not pat.endswith("/*"):
            continue
        root = pat[:-2].strip("/")
        root_dir = repo_root / root
        if not root_dir.exists() or not root_dir.is_dir():
            continue
        roots_scanned.append(root)

        for subdir in _bounded_list_subdirs(root_dir, max_items=200):
            pkg_json = subdir / "package.json"
            if pkg_json.exists() and pkg_json.is_file():
                add_pkg(pkg_json)

    roots_scanned = sorted(set(roots_scanned))
    name_to_dir = {k: name_to_dir[k] for k in sorted(name_to_dir.keys())}

    fp_obj = {"roots_scanned": roots_scanned, "packages": name_to_dir}
    fp_bytes = json.dumps(fp_obj, sort_keys=True, separators=(",", ":")).encode("utf-8", errors="replace")

    return {"roots_scanned": roots_scanned, "packages": name_to_dir, "fingerprint_sha256": sha256_bytes(fp_bytes)}


def _extract_tsconfig_aliases(repo_dir: str) -> dict[str, Any]:
    repo_root = Path(repo_dir)
    used: list[str] = []
    base_url_repo_rel: str | None = None
    paths_repo_rel: dict[str, list[str]] = {}

    for rel in CONFIG_CANDIDATES:
        cfg = repo_root / rel
        if not cfg.exists() or not cfg.is_file():
            continue

        chain = _load_tsconfig_with_extends(cfg)
        if not chain:
            continue

        for cp in chain:
            try:
                rp = _normalize_rel_path(os.path.relpath(str(cp), repo_dir))
            except Exception:
                rp = _normalize_rel_path(cp.as_posix())
            if rp not in used:
                used.append(rp)

        merged_bu, merged_paths = _merge_tsconfig_compiler_options(chain)

        anchor_dir: Path = cfg.parent
        if isinstance(merged_bu, str) and merged_bu.strip():
            bu_norm = merged_bu.strip()
            if bu_norm == ".":
                anchor_dir = cfg.parent
            elif bu_norm.startswith("/"):
                anchor_dir = repo_root / bu_norm.lstrip("/")
            else:
                anchor_dir = cfg.parent / bu_norm

        if base_url_repo_rel is None and isinstance(merged_bu, str) and merged_bu.strip():
            try:
                base_url_repo_rel = _normalize_rel_path(os.path.relpath(str(anchor_dir.resolve()), repo_dir))
            except Exception:
                base_url_repo_rel = _normalize_rel_path(anchor_dir.as_posix())

        for alias_pat, targets in merged_paths.items():
            if not isinstance(alias_pat, str) or not alias_pat.strip():
                continue
            if not isinstance(targets, list):
                continue

            norm_targets: list[str] = []
            for t in targets:
                if not isinstance(t, str) or not t.strip():
                    continue
                t0 = t.strip()

                if t0.startswith("/"):
                    abs_t = repo_root / t0.lstrip("/")
                else:
                    abs_t = anchor_dir / t0

                try:
                    abs_t = abs_t.resolve()
                except Exception:
                    pass

                try:
                    rel_t = os.path.relpath(str(abs_t), repo_dir)
                except Exception:
                    rel_t = str(abs_t)

                nt = _normalize_rel_path(rel_t)
                if nt not in norm_targets:
                    norm_targets.append(nt)

            if norm_targets:
                paths_repo_rel.setdefault(alias_pat, [])
                for nt in norm_targets:
                    if nt not in paths_repo_rel[alias_pat]:
                        paths_repo_rel[alias_pat].append(nt)

    alias_prefixes: list[dict[str, Any]] = []
    alias_exact: list[dict[str, Any]] = []

    for alias_pat, targets in paths_repo_rel.items():
        if not isinstance(alias_pat, str):
            continue

        if "*" not in alias_pat:
            t_exact: list[str] = []
            for t in targets:
                if isinstance(t, str) and t:
                    tt = _normalize_rel_path(t)
                    if tt and tt not in t_exact:
                        t_exact.append(tt)
            if t_exact:
                alias_exact.append({"alias": alias_pat, "targets": t_exact})
            continue

        if alias_pat.endswith("/*"):
            alias_prefix = alias_pat[:-1]
        elif alias_pat.endswith("*"):
            alias_prefix = alias_pat[:-1]
        else:
            continue

        t_prefixes: list[str] = []
        for t in targets:
            if not isinstance(t, str) or not t:
                continue
            if t.endswith("/*"):
                tp = t[:-1]
            elif t.endswith("*"):
                tp = t[:-1]
            else:
                tp = t if t.endswith("/") else (t + "/")
            tp = _normalize_rel_path(tp)
            if tp and tp not in t_prefixes:
                t_prefixes.append(tp)

        if alias_prefix and t_prefixes:
            alias_prefixes.append({"alias_prefix": alias_prefix, "targets": t_prefixes})

    alias_prefixes.sort(
        key=lambda x: (
            -len(str(x.get("alias_prefix", ""))),
            str(x.get("alias_prefix", "")),
            json.dumps(x, sort_keys=True),
        )
    )
    alias_exact.sort(key=lambda x: (str(x.get("alias", "")), json.dumps(x, sort_keys=True)))

    used = sorted(used)

    out = {
        "configs_used": used,
        "baseUrl": base_url_repo_rel,
        "paths": paths_repo_rel,
        "alias_prefixes": alias_prefixes,
        "alias_exact": alias_exact,
    }

    fp_obj = {
        "baseUrl": out.get("baseUrl"),
        "alias_prefixes": out.get("alias_prefixes"),
        "alias_exact": out.get("alias_exact"),
        "paths": out.get("paths"),
        "configs_used": out.get("configs_used"),
    }
    fp_bytes = json.dumps(fp_obj, sort_keys=True, separators=(",", ":")).encode("utf-8", errors="replace")
    out["active_rules_fingerprint_sha256"] = sha256_bytes(fp_bytes)

    return out


def _workspace_package_name_for_spec(spec: str, workspace_packages: dict[str, str]) -> str | None:
    s = (spec or "").strip()
    if not s.startswith("@") or "/" not in s:
        return None
    matches = [name for name in workspace_packages.keys() if s == name or s.startswith(name + "/")]
    if not matches:
        return None
    matches.sort(key=lambda x: (-len(x), x))
    return matches[0]


def _candidate_paths_for_module_noext(module_noext: str) -> list[str]:
    out: list[str] = []
    p = module_noext.rstrip("/")
    if not p:
        return out
    for ext in JS_RESOLVE_EXTS:
        out.append(p + ext)
    for ext in JS_RESOLVE_EXTS:
        out.append(p + "/index" + ext)
    return out


def _resolve_js_ts_import_to_repo_path(
        *,
        spec: str,
        from_file_repo_path: str,
        repo_dir: str,
        alias_info: dict[str, Any],
        workspace_packages: dict[str, str],
) -> dict[str, Any]:
    """
    Resolver that returns a small, evidence-friendly record.

    Architecture-only contract:
    - We attempt to resolve only to repo paths.
    - We classify unresolved as internal_unresolved only when the spec is "repo-shaped"
      (relative/rooted/alias/workspace/baseUrl). Otherwise we treat it as external and
      it will be dropped from architecture edges.
    """
    s = (spec or "").strip()
    if not s:
        return {
            "resolved_path": None,
            "resolution_kind": None,
            "resolution_candidates_tried_count": 0,
            "resolution_attempted": False,
            "classification": "external",
            "classification_reason": "empty",
        }

    repo_root = Path(repo_dir)
    from_dir = Path(from_file_repo_path).parent.as_posix().rstrip("/")
    candidates_tried = 0

    def _try_candidates(module_noext: str, kind: str) -> tuple[str | None, str | None]:
        nonlocal candidates_tried
        if not module_noext:
            return None, None
        for cand in _candidate_paths_for_module_noext(module_noext):
            candidates_tried += 1
            if (repo_root / cand).exists():
                if cand.endswith("/index.ts") or "/index." in cand:
                    return _normalize_rel_path(cand), "index_file"
                return _normalize_rel_path(cand), kind
        return None, None

    # 0) workspace package (@scope/pkg[/...]) resolution
    pkg_name = _workspace_package_name_for_spec(s, workspace_packages) if workspace_packages else None
    if pkg_name:
        pkg_root = workspace_packages[pkg_name]
        tail = s[len(pkg_name) :].lstrip("/")
        candidates = []
        if tail:
            candidates.append(_normalize_rel_path(f"{pkg_root}/{tail}"))
            candidates.append(_normalize_rel_path(f"{pkg_root}/src/{tail}"))
        else:
            candidates.append(_normalize_rel_path(f"{pkg_root}/index"))
            candidates.append(_normalize_rel_path(f"{pkg_root}/src/index"))
            candidates.append(_normalize_rel_path(f"{pkg_root}/src"))

        for module_noext in candidates:
            if Path(module_noext).suffix:
                candidates_tried += 1
                ok = (repo_root / module_noext).exists()
                if ok:
                    return {
                        "resolved_path": module_noext,
                        "resolution_kind": "workspace_package_direct",
                        "resolution_candidates_tried_count": candidates_tried,
                        "resolution_attempted": True,
                        "classification": "internal_resolved",
                        "classification_reason": "workspace_package",
                        "workspace_package": pkg_name,
                    }
            resolved, res_kind = _try_candidates(module_noext, "workspace_package")
            if resolved:
                return {
                    "resolved_path": resolved,
                    "resolution_kind": res_kind or "workspace_package",
                    "resolution_candidates_tried_count": candidates_tried,
                    "resolution_attempted": True,
                    "classification": "internal_resolved",
                    "classification_reason": "workspace_package",
                    "workspace_package": pkg_name,
                }

        return {
            "resolved_path": None,
            "resolution_kind": None,
            "resolution_candidates_tried_count": candidates_tried,
            "resolution_attempted": True,
            "classification": "internal_unresolved",
            "classification_reason": "workspace_package",
            "workspace_package": pkg_name,
        }

    # 1) relative
    if s.startswith(("./", "../")):
        base = f"{from_dir}/{s}" if from_dir else s
        module_noext = os.path.normpath(Path(base).as_posix()).replace("\\", "/").lstrip("./")

        if Path(s).suffix:
            candidates_tried += 1
            cand = _normalize_rel_path(module_noext)
            ok = (repo_root / cand).exists()
            return {
                "resolved_path": cand if ok else None,
                "resolution_kind": "direct_file",
                "resolution_candidates_tried_count": candidates_tried,
                "resolution_attempted": True,
                "classification": "internal_resolved" if ok else "internal_unresolved",
                "classification_reason": "relative",
            }

        resolved, res_kind = _try_candidates(module_noext, "ext_appended")
        return {
            "resolved_path": resolved,
            "resolution_kind": res_kind,
            "resolution_candidates_tried_count": candidates_tried,
            "resolution_attempted": True,
            "classification": "internal_resolved" if resolved else "internal_unresolved",
            "classification_reason": "relative",
        }

    # 2) rooted from repo root
    if s.startswith("/"):
        module_noext = s.lstrip("/")
        if Path(module_noext).suffix:
            candidates_tried += 1
            cand = _normalize_rel_path(module_noext)
            ok = (repo_root / cand).exists()
            return {
                "resolved_path": cand if ok else None,
                "resolution_kind": "direct_file",
                "resolution_candidates_tried_count": candidates_tried,
                "resolution_attempted": True,
                "classification": "internal_resolved" if ok else "internal_unresolved",
                "classification_reason": "rooted",
            }
        resolved, res_kind = _try_candidates(module_noext, "ext_appended")
        return {
            "resolved_path": resolved,
            "resolution_kind": res_kind,
            "resolution_candidates_tried_count": candidates_tried,
            "resolution_attempted": True,
            "classification": "internal_resolved" if resolved else "internal_unresolved",
            "classification_reason": "rooted",
        }

    # 3) exact aliases
    alias_exact = alias_info.get("alias_exact") or []
    if isinstance(alias_exact, list):
        for rule in alias_exact:
            if not isinstance(rule, dict):
                continue
            alias = rule.get("alias")
            targets = rule.get("targets")
            if not isinstance(alias, str) or not alias:
                continue
            if not isinstance(targets, list) or not targets:
                continue
            if s == alias or s.startswith(alias + "/"):
                tail = s[len(alias) :].lstrip("/")
                for t in targets:
                    if not isinstance(t, str) or not t:
                        continue
                    base = t.rstrip("/")
                    module_noext = _normalize_rel_path(
                        os.path.normpath(f"{base}/{tail}" if tail else base).replace("\\", "/")
                    )

                    if Path(s).suffix:
                        candidates_tried += 1
                        ok = (repo_root / module_noext).exists()
                        return {
                            "resolved_path": module_noext if ok else None,
                            "resolution_kind": "alias_exact",
                            "resolution_candidates_tried_count": candidates_tried,
                            "resolution_attempted": True,
                            "classification": "internal_resolved" if ok else "internal_unresolved",
                            "classification_reason": "alias_exact",
                        }

                    resolved, res_kind = _try_candidates(module_noext, "alias_exact")
                    return {
                        "resolved_path": resolved,
                        "resolution_kind": res_kind or "alias_exact",
                        "resolution_candidates_tried_count": candidates_tried,
                        "resolution_attempted": True,
                        "classification": "internal_resolved" if resolved else "internal_unresolved",
                        "classification_reason": "alias_exact",
                    }

    # 4) alias prefixes
    alias_prefixes = alias_info.get("alias_prefixes", [])
    if isinstance(alias_prefixes, list):
        for rule in alias_prefixes:
            if not isinstance(rule, dict):
                continue
            ap = rule.get("alias_prefix")
            targets = rule.get("targets")
            if not isinstance(ap, str) or not ap:
                continue
            if not isinstance(targets, list) or not targets:
                continue
            if s.startswith(ap):
                tail = s[len(ap) :].lstrip("/")
                for tp in targets:
                    if not isinstance(tp, str) or not tp:
                        continue
                    module_noext = _normalize_rel_path(os.path.normpath((tp + tail).replace("\\", "/")).replace("\\", "/"))

                    if Path(s).suffix:
                        candidates_tried += 1
                        ok = (repo_root / module_noext).exists()
                        return {
                            "resolved_path": module_noext if ok else None,
                            "resolution_kind": "alias_target",
                            "resolution_candidates_tried_count": candidates_tried,
                            "resolution_attempted": True,
                            "classification": "internal_resolved" if ok else "internal_unresolved",
                            "classification_reason": "alias_rule",
                        }

                    resolved, res_kind = _try_candidates(module_noext, "alias_target")
                    return {
                        "resolved_path": resolved,
                        "resolution_kind": res_kind or "alias_target",
                        "resolution_candidates_tried_count": candidates_tried,
                        "resolution_attempted": True,
                        "classification": "internal_resolved" if resolved else "internal_unresolved",
                        "classification_reason": "alias_rule",
                    }

    # 5) baseUrl resolution ONLY if baseUrl is present in tsconfig chain
    base_url = alias_info.get("baseUrl")
    if isinstance(base_url, str) and base_url.strip():
        module_noext = _normalize_rel_path(f"{base_url.rstrip('/')}/{s.lstrip('/')}")
        if Path(module_noext).suffix:
            candidates_tried += 1
            ok = (repo_root / module_noext).exists()
            return {
                "resolved_path": module_noext if ok else None,
                "resolution_kind": "baseUrl",
                "resolution_candidates_tried_count": candidates_tried,
                "resolution_attempted": True,
                "classification": "internal_resolved" if ok else "internal_unresolved",
                "classification_reason": "baseUrl",
            }
        resolved, res_kind = _try_candidates(module_noext, "baseUrl")
        if resolved:
            return {
                "resolved_path": resolved,
                "resolution_kind": res_kind or "baseUrl",
                "resolution_candidates_tried_count": candidates_tried,
                "resolution_attempted": True,
                "classification": "internal_resolved",
                "classification_reason": "baseUrl",
            }
        return {
            "resolved_path": None,
            "resolution_kind": None,
            "resolution_candidates_tried_count": candidates_tried,
            "resolution_attempted": True,
            "classification": "internal_unresolved",
            "classification_reason": "baseUrl",
        }

    # Otherwise: external (architecture-out-of-scope)
    return {
        "resolved_path": None,
        "resolution_kind": None,
        "resolution_candidates_tried_count": candidates_tried,
        "resolution_attempted": True,
        "classification": "external",
        "classification_reason": "bare_or_scoped",
    }


# --------------------------------------------------------------------------------------
# Python roots + resolution
# --------------------------------------------------------------------------------------
def _candidate_paths_for_py_module(module_path: str) -> list[str]:
    out: list[str] = []
    p = module_path.strip("/").replace("\\", "/")
    if not p:
        return out
    out.append(p + ".py")
    out.append(p + "/__init__.py")
    return out


def _discover_python_roots(repo_dir: str) -> dict[str, Any]:
    """
    Deterministically discover python import roots.
    Keep it config-driven:
      - "" (repo root) always
      - "src" if present
      - pyproject.toml hints (poetry packages[].from, setuptools package-dir)
    """
    repo_root = Path(repo_dir)
    roots: list[str] = [""]

    if (repo_root / "src").exists() and (repo_root / "src").is_dir():
        roots.append("src")

    pyproject = repo_root / "pyproject.toml"
    if tomllib and pyproject.exists() and pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            data = None

        def _maybe_add_root(v: Any) -> None:
            if isinstance(v, str) and v.strip():
                rr = _normalize_rel_path(v.strip().rstrip("/"))
                if rr not in roots:
                    roots.append(rr)

        if isinstance(data, dict):
            tool = data.get("tool")
            if isinstance(tool, dict):
                poetry = tool.get("poetry")
                if isinstance(poetry, dict):
                    pkgs = poetry.get("packages")
                    if isinstance(pkgs, list):
                        for ent in pkgs:
                            if isinstance(ent, dict):
                                _maybe_add_root(ent.get("from"))
                setuptools = tool.get("setuptools")
                if isinstance(setuptools, dict):
                    pkg_dir = setuptools.get("package-dir") or setuptools.get("package_dir")
                    if isinstance(pkg_dir, dict):
                        _maybe_add_root(pkg_dir.get("") or pkg_dir.get("."))

    roots = [_normalize_rel_path(r) for r in roots]
    roots = [r for i, r in enumerate(roots) if r not in roots[:i]]
    roots = sorted(roots, key=lambda x: (0 if x == "" else 1, x))

    fp_obj = {"roots": roots}
    fp_bytes = json.dumps(fp_obj, sort_keys=True, separators=(",", ":")).encode("utf-8", errors="replace")
    return {"roots": roots, "fingerprint_sha256": sha256_bytes(fp_bytes)}


def _resolve_python_import_to_repo_path(
        *,
        spec: str,
        from_file_repo_path: str,
        repo_dir: str,
        python_roots: list[str],
) -> dict[str, Any]:
    s = (spec or "").strip()
    if not s:
        return {
            "resolved_path": None,
            "resolution_kind": None,
            "resolution_candidates_tried_count": 0,
            "resolution_attempted": False,
            "classification": "external",
            "classification_reason": "empty",
        }

    repo_root = Path(repo_dir)
    from_dir = Path(from_file_repo_path).parent.as_posix().rstrip("/")
    candidates_tried = 0

    def _try_py_candidates(module_path: str) -> str | None:
        nonlocal candidates_tried
        mp = module_path.strip("/").replace("\\", "/")
        if not mp:
            return None
        roots = python_roots or [""]
        for r in roots:
            prefix = _normalize_rel_path(r).rstrip("/")
            base = f"{prefix}/{mp}" if prefix else mp
            for cand in _candidate_paths_for_py_module(base):
                candidates_tried += 1
                if (repo_root / cand).exists():
                    return _normalize_rel_path(cand)
        return None

    # relative: leading dots
    m = re.match(r"^(\.+)(.*)$", s)
    if m:
        dots = m.group(1) or ""
        rest = (m.group(2) or "").lstrip(".")
        level = len(dots)

        base = from_dir
        for _ in range(max(level, 1)):
            if "/" in base:
                base = base.rsplit("/", 1)[0]
            else:
                base = ""
                break

        if rest:
            module_path = f"{base}/{rest.replace('.', '/')}" if base else rest.replace(".", "/")
        else:
            module_path = base

        module_path = _normalize_rel_path(os.path.normpath(module_path).replace("\\", "/"))
        resolved = _try_py_candidates(module_path)
        return {
            "resolved_path": resolved,
            "resolution_kind": "relative",
            "resolution_candidates_tried_count": candidates_tried,
            "resolution_attempted": True,
            "classification": "internal_resolved" if resolved else "internal_unresolved",
            "classification_reason": "relative",
        }

    # absolute: try roots; unresolved absolute is treated as external (architecture-out-of-scope)
    module_path = s.replace(".", "/")
    resolved = _try_py_candidates(module_path)
    return {
        "resolved_path": resolved,
        "resolution_kind": "absolute",
        "resolution_candidates_tried_count": candidates_tried,
        "resolution_attempted": True,
        "classification": "internal_resolved" if resolved else "external",
        "classification_reason": "absolute",
    }


# --------------------------------------------------------------------------------------
# Env vars + signals
# --------------------------------------------------------------------------------------
def _extract_env_var_edges(text: str, *, language: str) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    if not text:
        return edges

    if language == "python":
        for rx in PY_ENV_PATTERNS:
            for m in rx.finditer(text):
                key = m.group(1)
                if key:
                    edges.append({"kind": "env_var", "key": key, "lineno": _lineno_from_index(text, m.start())})
    elif language in ("typescript", "javascript"):
        cleaned = strip_js_ts_comments(text)
        for rx in JS_ENV_PATTERNS:
            for m in rx.finditer(cleaned):
                key = m.group(1)
                if key:
                    edges.append({"kind": "env_var", "key": key, "lineno": _lineno_from_index(cleaned, m.start())})

    edges.sort(key=lambda e: (int(e.get("lineno", 1)), str(e.get("key", ""))))
    dedup: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str]] = set()
    for e in edges:
        t = (int(e.get("lineno", 1)), str(e.get("kind", "")), str(e.get("key", "")))
        if t not in seen:
            seen.add(t)
            dedup.append(e)
    return dedup


def _entrypoint_signals_for_file(rel_path: str, language: str, text: str) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    p = rel_path.replace("\\", "/")

    if p.startswith("frontend/") and ("/app/" in p or "/pages/" in p):
        if p.endswith(("/page.tsx", "/page.jsx", "/page.ts", "/page.js")):
            signals.append({"kind": "entrypoint_hint", "path": p, "why": "next_page"})
        if p.endswith(("/layout.tsx", "/layout.jsx")):
            signals.append({"kind": "entrypoint_hint", "path": p, "why": "next_layout"})
        if p.endswith(("/route.ts", "/route.js")):
            signals.append({"kind": "entrypoint_hint", "path": p, "why": "next_route"})

    if p.endswith(("/main.py", "/app.py", "/server.py")) and language == "python":
        signals.append({"kind": "entrypoint_hint", "path": p, "why": "common_backend_filename"})

    if language == "python" and "__name__" in text and "if __name__" in text and "__main__" in text:
        signals.append({"kind": "entrypoint_hint", "path": p, "why": "python___main__"})
    if language == "python" and "FastAPI(" in text:
        signals.append({"kind": "entrypoint_hint", "path": p, "why": "fastapi_app"})
    if language == "python" and "uvicorn.run" in text:
        signals.append({"kind": "entrypoint_hint", "path": p, "why": "uvicorn_run"})
    if language in ("typescript", "javascript") and ("createRoot(" in text or "ReactDOM.render" in text):
        signals.append({"kind": "entrypoint_hint", "path": p, "why": "react_dom_mount"})

    return signals


def _package_json_signals(text: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(text)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None

    scripts = obj.get("scripts")
    sig: dict[str, Any] = {}
    if isinstance(scripts, dict):
        sig["scripts"] = {k: scripts[k] for k in sorted(scripts.keys()) if isinstance(k, str)}
    for k in ("main", "module", "type", "bin", "name", "workspaces"):
        v = obj.get(k)
        if v is not None:
            sig[k] = v
    for dep_key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        v = obj.get(dep_key)
        if isinstance(v, dict):
            # note: this is not used for dependency inventory; it is a lightweight repo signal.
            sig[dep_key] = sorted([str(x) for x in v.keys()])

    return sig or None


def _maybe_extract_next_routing_signals(rel_path: str, text: str) -> dict[str, Any] | None:
    p = rel_path.replace("\\", "/")
    if not p.startswith("frontend/"):
        return None

    out: dict[str, Any] = {}

    if "/app/" in p and "/(" in p:
        out["route_group_hint"] = p

    if p.endswith(("/middleware.ts", "/middleware.js", "/middleware.tsx")):
        m = NEXT_MW_MATCHER_RE.search(text)
        if m:
            out["middleware_matcher_raw"] = m.group(1)[:2000]
            out["middleware_matcher_lineno"] = _lineno_from_index(text, m.start())
        m2 = NEXT_PROTECTED_LIST_RE.search(text)
        if m2:
            out["protected_list_raw"] = m2.group(2)[:2000]
            out["protected_list_lineno"] = _lineno_from_index(text, m2.start(2))

    return out or None


def _maybe_extract_auth_signals(rel_path: str, language: str, text: str) -> list[dict[str, Any]]:
    p = rel_path.replace("\\", "/")
    out: list[dict[str, Any]] = []

    if language in ("typescript", "javascript"):
        cleaned = strip_js_ts_comments(text)
        for m in FRONTEND_AUTH_ME_RE.finditer(cleaned):
            out.append({"kind": "frontend_auth_me_ref", "path": p, "lineno": _lineno_from_index(cleaned, m.start())})
        for m in FRONTEND_LOGIN_RE.finditer(cleaned):
            out.append({"kind": "frontend_login_ref", "path": p, "lineno": _lineno_from_index(cleaned, m.start())})
        for m in FRONTEND_COOKIE_NAME_RE.finditer(cleaned):
            out.append({"kind": "frontend_cookie_name_block", "path": p, "lineno": _lineno_from_index(cleaned, m.start())})

    if language == "python":
        for m in PY_DEPENDS_RE.finditer(text):
            sym = (m.group(1) or "").strip()
            if sym:
                out.append({"kind": "backend_depends_ref", "path": p, "lineno": _lineno_from_index(text, m.start()), "symbol": sym})
        for m in PY_GET_CURRENT_RE.finditer(text):
            sym = (m.group(0) or "").strip()
            if sym:
                out.append({"kind": "backend_get_current_ref", "path": p, "lineno": _lineno_from_index(text, m.start()), "symbol": sym})
        for m in PY_AUTH_PATH_RE.finditer(text):
            out.append({"kind": "backend_auth_path_ref", "path": p, "lineno": _lineno_from_index(text, m.start())})

    return out


def _tags_for_read_plan_path(p: str) -> list[str]:
    tags: list[str] = []
    s = (p or "").replace("\\", "/")
    if not s:
        return tags
    if s.endswith("frontend/middleware.ts") or s.endswith("frontend/middleware.js"):
        tags.append("next_middleware")
    if "/app/" in s and s.endswith("/layout.tsx"):
        tags.append("next_layout")
    if "/app/" in s and s.endswith("/page.tsx"):
        tags.append("next_page")
    if "/app/" in s and "/(admin)" in s:
        tags.append("next_admin_route_group")
    if s.endswith("/route.ts") or s.endswith("/route.js"):
        tags.append("next_route")
    if s.endswith(("main.py", "app.py", "server.py")):
        tags.append("backend_entrypoint")
    if "auth" in s.lower():
        tags.append("auth")
    if "middleware" in s.lower():
        tags.append("middleware")
    if "rbac" in s.lower() or "admin" in s.lower():
        tags.append("rbac_or_admin")
    return tags


def _normalize_read_plan_candidates(obj: Any) -> list[dict[str, Any]]:
    """
    Strict contract: suggest_files_to_read returns a dict with a "candidates" list of dicts.
    Anything else is a contract violation.
    """
    if not isinstance(obj, dict):
        raise RuntimeError("pass1: read_plan suggestions must be a dict")
    c = obj.get("candidates")
    if not isinstance(c, list):
        raise RuntimeError("pass1: read_plan suggestions missing candidates list")
    out: list[dict[str, Any]] = []
    for it in c:
        if not isinstance(it, dict):
            raise RuntimeError("pass1: read_plan candidate must be dict")
        p = it.get("path")
        if not isinstance(p, str) or not p.strip():
            raise RuntimeError("pass1: read_plan candidate missing/invalid path")
        out.append(dict(it))
    return out


def _read_plan_max_files(job: Job) -> int:
    """
    Strict contract: read-plan suggestion generation cap comes ONLY from Job:
      job.pass2.max_files
    Fallback only if absent (Job schema not yet updated) -> 120.
    """
    v = getattr(getattr(job, "pass2", None), "max_files", None)
    try:
        n = int(v)  # type: ignore[arg-type]
        if n > 0:
            return min(n, 240)
    except Exception:
        pass
    return 120


# --------------------------------------------------------------------------------------
# Pass1 core builder
# --------------------------------------------------------------------------------------
def build_repo_index(repo_dir: str, job: Job, *, resolved_commit: str) -> dict[str, Any]:
    """
    Build PASS1_REPO_INDEX.json data.

    Strict contract:
    - resolved_commit is REQUIRED here (graph must know it from checkout).
    - output schema_version + deterministic read_plan block.
    """
    files: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    total_bytes = 0
    files_scanned = 0
    files_included = 0

    deny_dirs = set(job.filters.deny_dirs)
    deny_file_regex = [re.compile(p) for p in job.filters.deny_file_regex]
    allow_all = "*" in job.filters.allow_exts
    allow_exts = set([e.lower().lstrip(".") for e in job.filters.allow_exts if e != "*"])

    allow_binary = bool(getattr(job.filters, "allow_binary", False))
    max_files_reached = False

    # Resolver inputs collected once (deterministic)
    ts_aliases = _extract_tsconfig_aliases(repo_dir)
    workspace_info = _collect_workspace_packages(repo_dir)
    python_roots_info = _discover_python_roots(repo_dir)

    workspace_packages_map: dict[str, str] = {}
    pkgs = workspace_info.get("packages")
    if isinstance(pkgs, dict):
        workspace_packages_map = {str(k): str(v) for k, v in pkgs.items() if isinstance(k, str) and isinstance(v, str)}

    python_roots: list[str] = [""]
    r = python_roots_info.get("roots")
    if isinstance(r, list):
        python_roots = [str(x) for x in r if isinstance(x, str)]

    repo_signals: dict[str, Any] = {
        "entrypoints": [],
        "package_json": {},
        "env_vars": [],
        "routing": {"middleware": [], "route_group_hints": []},
        "auth": {"occurrences": []},
    }

    _env_locations: dict[str, list[dict[str, Any]]] = {}
    _entrypoint_set: set[tuple[str, str]] = set()

    _routing_mw_set: set[tuple[str, int, str]] = set()
    _routing_route_group_set: set[str] = set()
    _auth_occ_set: set[str] = set()

    def record_skip(rel_path: str, reason: str, size: int | None = None) -> None:
        skipped.append({"path": rel_path, "reason": reason, "bytes": int(size or 0)})

    for root, dirs, filenames in os.walk(repo_dir):
        dirs[:] = sorted([d for d in dirs if d not in deny_dirs])
        filenames = sorted(filenames)

        if max_files_reached:
            break

        for fn in filenames:
            if files_scanned >= job.limits.max_files:
                if not max_files_reached:
                    record_skip("*", "max_files_reached")
                    max_files_reached = True
                break

            abs_path = os.path.join(root, fn)
            rel_path = os.path.relpath(abs_path, repo_dir).replace("\\", "/")
            files_scanned += 1

            if any(rx.search(rel_path) for rx in deny_file_regex):
                record_skip(rel_path, "deny_file_regex")
                continue

            ext = Path(rel_path).suffix.lower().lstrip(".")
            if not allow_all and ext not in allow_exts:
                record_skip(rel_path, "ext_not_allowed")
                continue

            try:
                size = os.stat(abs_path).st_size
            except OSError:
                record_skip(rel_path, "stat_failed")
                continue

            if size > job.limits.max_file_bytes:
                record_skip(rel_path, "max_file_bytes_exceeded", size)
                continue

            if total_bytes + size > job.limits.max_total_bytes:
                record_skip(rel_path, "max_total_bytes_exceeded", size)
                continue

            try:
                raw = Path(abs_path).read_bytes()
            except Exception:
                record_skip(rel_path, "read_failed", size)
                continue

            if (not allow_binary) and is_probably_binary(raw):
                record_skip(rel_path, "binary_file", size)
                continue

            sha = sha256_bytes(raw)
            language = infer_language(rel_path)

            # Architecture-only:
            # - deps.import_edges contains ONLY resolved internal edges
            # - deps.internal_unresolved_specs captures unresolved internal-only specs
            imports_raw: list[str] = []
            internal_resolved_paths: list[str] = []
            internal_unresolved_specs_sorted: list[str] = []

            import_edges_internal_resolved: list[dict[str, Any]] = []
            top_defs: list[str] = []
            flags: list[str] = []

            try:
                text = raw.decode("utf-8", errors="replace")
            except Exception:
                record_skip(rel_path, "text_decode_failed", size)
                continue

            # general repo signals
            resource_edges = _extract_env_var_edges(text, language=language)
            for e in resource_edges:
                key = str(e.get("key", "")).strip()
                if not key:
                    continue
                _env_locations.setdefault(key, [])
                _env_locations[key].append({"path": rel_path, "lineno": int(e.get("lineno", 1) or 1)})

            for s in _entrypoint_signals_for_file(rel_path, language, text):
                p = str(s.get("path", "")).strip()
                why = str(s.get("why", "")).strip()
                if p and why:
                    _entrypoint_set.add((p, why))

            rs = _maybe_extract_next_routing_signals(rel_path, text)
            if rs:
                if "middleware_matcher_raw" in rs:
                    ln = int(rs.get("middleware_matcher_lineno", 1) or 1)
                    prev = str(rs.get("middleware_matcher_raw") or "")[:200]
                    _routing_mw_set.add((rel_path, ln, prev))
                if "protected_list_raw" in rs:
                    ln = int(rs.get("protected_list_lineno", 1) or 1)
                    prev = str(rs.get("protected_list_raw") or "")[:200]
                    _routing_mw_set.add((rel_path, ln, prev))
                if "route_group_hint" in rs:
                    pth = str(rs.get("route_group_hint") or "")
                    if pth:
                        _routing_route_group_set.add(pth)

            for occ in _maybe_extract_auth_signals(rel_path, language, text):
                _auth_occ_set.add(json.dumps(occ, sort_keys=True, separators=(",", ":")))

            # -------------------------
            # Import parsing: supported langs only
            # -------------------------
            if language == "python":
                try:
                    top_defs, import_edges_raw = parse_python_import_edges(text)
                    imports_raw = sorted({str(e.get("spec")) for e in import_edges_raw if e.get("spec")})
                except Exception:
                    flags.append("python_parse_failed")
                    top_defs, imports_raw = parse_python_defs_and_imports(text)
                    import_edges_raw = []

                internal_set: set[str] = set()
                internal_unresolved_specs: set[str] = set()

                for e in import_edges_raw:
                    if not isinstance(e, dict):
                        continue
                    spec = str(e.get("spec", "")).strip()
                    if not spec:
                        continue

                    res = _resolve_python_import_to_repo_path(
                        spec=spec,
                        from_file_repo_path=rel_path,
                        repo_dir=repo_dir,
                        python_roots=python_roots,
                    )

                    resolved_path = res.get("resolved_path")
                    if isinstance(resolved_path, str) and resolved_path:
                        internal_set.add(resolved_path)
                        import_edges_internal_resolved.append(
                            {
                                "kind": str(e.get("kind", "")),
                                "spec": spec,
                                "lineno": int(e.get("lineno", 1) or 1),
                                "resolved_path": resolved_path,
                                "is_external": False,
                            }
                        )
                    else:
                        # Record unresolved ONLY as a spec (no edge emission).
                        # Keep only relative/"repo-shaped" unresolved.
                        if spec.startswith(".") or str(res.get("classification")) == "internal_unresolved":
                            internal_unresolved_specs.add(spec)
                            flags.append("import_unresolved")

                internal_resolved_paths = sorted(internal_set)
                internal_unresolved_specs_sorted = sorted(internal_unresolved_specs)

            elif language in ("typescript", "javascript"):
                try:
                    top_defs, import_edges_raw = parse_js_ts_import_edges(text)
                    if not top_defs:
                        flags.append("top_level_defs_best_effort_empty")
                    imports_raw = sorted({str(e.get("spec")) for e in import_edges_raw if e.get("spec")})
                except Exception:
                    flags.append("js_ts_parse_failed")
                    top_defs = []
                    imports_raw = []
                    import_edges_raw = []

                internal_set: set[str] = set()
                internal_unresolved_specs: set[str] = set()

                for e in import_edges_raw:
                    if not isinstance(e, dict):
                        continue
                    spec = str(e.get("spec", "")).strip()
                    if not spec:
                        continue

                    res = _resolve_js_ts_import_to_repo_path(
                        spec=spec,
                        from_file_repo_path=rel_path,
                        repo_dir=repo_dir,
                        alias_info=ts_aliases,
                        workspace_packages=workspace_packages_map,
                    )

                    classification = str(res.get("classification", "external"))
                    resolved_path = res.get("resolved_path")

                    if isinstance(resolved_path, str) and resolved_path:
                        internal_set.add(resolved_path)
                        import_edges_internal_resolved.append(
                            {
                                "kind": str(e.get("kind", "")),
                                "spec": spec,
                                "lineno": int(e.get("lineno", 1) or 1),
                                "resolved_path": resolved_path,
                                "is_external": False,
                            }
                        )
                    else:
                        # Record unresolved ONLY as a spec (no edge emission).
                        if classification == "internal_unresolved":
                            internal_unresolved_specs.add(spec)
                            flags.append("import_unresolved")

                internal_resolved_paths = sorted(internal_set)
                internal_unresolved_specs_sorted = sorted(internal_unresolved_specs)

            else:
                # Non-supported: no parsing performed.
                flags.append("language_no_import_parse")
                top_defs = []
                imports_raw = []
                internal_resolved_paths = []
                internal_unresolved_specs_sorted = []
                import_edges_internal_resolved = []

            # Canonical evidence list for ReadPlan: resolved internal edges only (may be empty).
            import_edges_sorted = sorted(
                import_edges_internal_resolved,
                key=lambda e: (
                    int(e.get("lineno", 1) or 1),
                    str(e.get("kind", "")),
                    str(e.get("spec", "")),
                    str(e.get("resolved_path") or ""),
                ),
            )

            if rel_path.endswith("package.json") and language == "json":
                sig = _package_json_signals(text)
                if sig:
                    repo_signals["package_json"][rel_path] = sig

            total_bytes += size
            files_included += 1

            deps_block = {
                "import_edges": import_edges_sorted,
                "internal_resolved_paths": internal_resolved_paths,
                "internal_unresolved_specs": internal_unresolved_specs_sorted,
                # Kept for schema stability; out of scope so always empty.
                "external_specs": [],
                "ambiguous_specs": [],
            }

            files.append(
                {
                    "path": rel_path,
                    "bytes": size,
                    "sha256": sha,
                    "language": language,
                    "imports_raw": imports_raw,
                    "imports_resolved_internal": internal_resolved_paths,
                    "imports_external": [],  # out of scope
                    "top_level_defs": top_defs,
                    "flags": flags,
                    # ReadPlan expects either deps.import_edges or import_edges; we provide both.
                    "import_edges": import_edges_sorted,
                    "deps": deps_block,
                    "resource_edges": resource_edges,
                }
            )

        if max_files_reached:
            break

    files.sort(key=lambda x: x["path"])
    skipped.sort(key=lambda x: x["path"])

    # ------------------------------------------------------------------
    # import_index.by_path + reverse_internal derived from Pass1 facts
    # ------------------------------------------------------------------
    import_index_by_path: dict[str, Any] = {}
    reverse_internal: dict[str, list[dict[str, Any]]] = {}

    file_by_path = {f.get("path"): f for f in files if isinstance(f, dict) and isinstance(f.get("path"), str)}

    for f in files:
        p = str(f.get("path", "") or "")
        deps = f.get("deps") if isinstance(f.get("deps"), dict) else {}
        if not p or not isinstance(deps, dict):
            continue

        internal_resolved = deps.get("internal_resolved_paths") or []
        internal_unresolved = deps.get("internal_unresolved_specs") or []

        import_index_by_path[p] = {
            "internal_resolved_paths": sorted([x for x in internal_resolved if isinstance(x, str) and x]),
            "internal_unresolved_specs": sorted([x for x in internal_unresolved if isinstance(x, str) and x]),
            # schema-stable, but out of scope:
            "external_specs": [],
            "ambiguous_specs": [],
        }

        edges = deps.get("import_edges") or []
        if isinstance(edges, list):
            for e in edges:
                if not isinstance(e, dict):
                    continue
                rp = e.get("resolved_path")
                if not isinstance(rp, str) or not rp:
                    continue
                if bool(e.get("is_external", False)):
                    continue
                reverse_internal.setdefault(rp, [])
                reverse_internal[rp].append(
                    {
                        "path": p,
                        "lineno": int(e.get("lineno", 1) or 1),
                        "spec": str(e.get("spec", "") or ""),
                        "kind": str(e.get("kind", "") or ""),
                    }
                )

    reverse_internal_out: dict[str, Any] = {}
    for target in sorted(reverse_internal.keys()):
        lst = reverse_internal[target]
        lst_sorted = sorted(
            lst,
            key=lambda x: (str(x.get("path", "")), int(x.get("lineno", 1) or 1), str(x.get("spec", ""))),
        )
        dedup: list[dict[str, Any]] = []
        seen = set()
        for it in lst_sorted:
            t = (
                str(it.get("path", "")),
                int(it.get("lineno", 1) or 1),
                str(it.get("spec", "")),
                str(it.get("kind", "")),
            )
            if t not in seen:
                seen.add(t)
                dedup.append({"path": t[0], "lineno": t[1], "spec": t[2], "kind": t[3]})
        reverse_internal_out[target] = dedup

    repo_import_index = {"by_path": import_index_by_path, "reverse_internal": reverse_internal_out}

    # ------------------------------------------------------------------
    # Read plan: canonical {closure_seeds, candidates[]} block
    # ------------------------------------------------------------------
    read_plan_suggestions_raw = suggest_files_to_read(files, max_files=_read_plan_max_files(job))
    candidates = _normalize_read_plan_candidates(read_plan_suggestions_raw)

    # closure seeds: routing/auth + suggested "important" + dependency-adjacent
    closure_seed_set: set[str] = set()

    for p in sorted(_routing_route_group_set):
        closure_seed_set.add(p)

    for p in file_by_path.keys():
        if isinstance(p, str) and p.endswith(("frontend/middleware.ts", "frontend/middleware.js")):
            closure_seed_set.add(p)

    auth_occ_paths: set[str] = set()
    for k in _auth_occ_set:
        try:
            occ = json.loads(k)
        except Exception:
            continue
        if isinstance(occ, dict):
            pp = occ.get("path")
            if isinstance(pp, str) and pp:
                auth_occ_paths.add(pp)
    for p in sorted(auth_occ_paths):
        if len(closure_seed_set) >= 60:
            break
        closure_seed_set.add(p)

    for c in candidates:
        p = c.get("path")
        if not isinstance(p, str) or not p:
            continue
        tags = _tags_for_read_plan_path(p)
        if any(t in ("next_middleware", "auth", "rbac_or_admin", "next_admin_route_group") for t in tags):
            closure_seed_set.add(p)

    entrypoint_paths = sorted({p for (p, _why) in _entrypoint_set})
    for p in entrypoint_paths[:40]:
        closure_seed_set.add(p)
        deps = import_index_by_path.get(p, {}).get("internal_resolved_paths") or []
        if isinstance(deps, list):
            for d in deps[:30]:
                if isinstance(d, str) and d in file_by_path:
                    closure_seed_set.add(d)
        if len(closure_seed_set) >= 160:
            break

    read_plan_closure_seeds = sorted(closure_seed_set)

    # ------------------------------------------------------------------
    # finalize signals deterministically
    # ------------------------------------------------------------------
    repo_signals["entrypoints"] = [
        {"kind": "entrypoint_hint", "path": p, "why": why}
        for (p, why) in sorted(_entrypoint_set, key=lambda t: (t[0], t[1]))
    ]

    env_vars_out: list[dict[str, Any]] = []
    for k in sorted(_env_locations.keys()):
        locs = _env_locations[k]
        locs_sorted = sorted(locs, key=lambda x: (str(x.get("path", "")), int(x.get("lineno", 1) or 1)))
        dedup: list[dict[str, Any]] = []
        seen = set()
        for l in locs_sorted:
            t = (str(l.get("path", "")), int(l.get("lineno", 1) or 1))
            if t not in seen:
                seen.add(t)
                dedup.append({"path": t[0], "lineno": t[1]})
        env_vars_out.append({"key": k, "locations": dedup})
    repo_signals["env_vars"] = env_vars_out

    repo_signals["routing"]["route_group_hints"] = sorted(_routing_route_group_set)
    repo_signals["routing"]["middleware"] = [
        {"path": p, "lineno": ln, "matcher_preview": prev}
        for (p, ln, prev) in sorted(_routing_mw_set, key=lambda t: (t[0], t[1], t[2]))
    ]

    auth_occ_list: list[dict[str, Any]] = []
    for k in sorted(_auth_occ_set):
        try:
            occ = json.loads(k)
        except Exception:
            continue
        if isinstance(occ, dict):
            auth_occ_list.append(occ)
    auth_occ_list = sorted(
        auth_occ_list,
        key=lambda o: (
            str(o.get("path", "")),
            int(o.get("lineno", 1) or 1),
            str(o.get("kind", "")),
            str(o.get("symbol", "")),
        ),
    )
    repo_signals["auth"]["occurrences"] = auth_occ_list

    # ------------------------------------------------------------------
    # Contract job block
    # ------------------------------------------------------------------
    job_block = job.model_dump()
    job_block["resolved_commit"] = resolved_commit

    # ------------------------------------------------------------------
    # resolver_inputs: explicit + fingerprinted
    # ------------------------------------------------------------------
    resolver_inputs = {
        "tsconfig_aliases": {
            "configs_used": ts_aliases.get("configs_used", []),
            "baseUrl": ts_aliases.get("baseUrl"),
            "alias_prefixes": ts_aliases.get("alias_prefixes", []),
            "alias_exact": ts_aliases.get("alias_exact", []),
            "active_rules_fingerprint_sha256": ts_aliases.get("active_rules_fingerprint_sha256"),
        },
        "workspace_packages": workspace_info,
        "python_roots": python_roots_info,
    }

    return {
        "schema_version": PASS1_REPO_INDEX_SCHEMA_VERSION,
        "generated_at": utc_ts(),
        "job": job_block,
        "counts": {
            "files_scanned": files_scanned,
            "files_included": files_included,
            "files_skipped": len(skipped),
            "total_bytes_included": total_bytes,
        },
        "filters": job.model_dump().get("filters", {}),
        "resolver_inputs": resolver_inputs,
        "signals": repo_signals,
        "import_index": repo_import_index,
        "files": files,
        "skipped_files": skipped,
        "read_plan": {
            "closure_seeds": read_plan_closure_seeds,
            "candidates": candidates,
        },
    }


# --------------------------------------------------------------------------------------
# Deterministic dependency graph artifact (derived solely from PASS1 import_index.by_path)
# --------------------------------------------------------------------------------------
def _stable_json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8", errors="replace")


def build_dependency_graph(pass1_repo_index: dict[str, Any]) -> dict[str, Any]:
    """
    DEPENDENCY_GRAPH.json (canonical):
    - Derived ONLY from pass1_repo_index["import_index"]["by_path"] (no other sources).
    """
    if not isinstance(pass1_repo_index, dict):
        raise ValueError("pass1_repo_index must be a dict")
    ii = pass1_repo_index.get("import_index")
    if not isinstance(ii, dict):
        raise ValueError("pass1_repo_index.import_index missing/invalid")
    by_path = ii.get("by_path")
    if not isinstance(by_path, dict):
        raise ValueError("pass1_repo_index.import_index.by_path missing/invalid")

    job = pass1_repo_index.get("job")
    if not isinstance(job, dict):
        raise ValueError("pass1_repo_index.job missing/invalid")
    resolved_commit = job.get("resolved_commit")
    if not isinstance(resolved_commit, str) or not resolved_commit.strip() or resolved_commit == "unknown":
        raise ValueError("pass1_repo_index.job.resolved_commit missing/invalid")

    forward_internal: dict[str, list[str]] = {}
    reverse_internal: dict[str, list[str]] = {}
    unresolved_internal_specs: dict[str, list[str]] = {}

    # schema-stable but out-of-scope:
    external_specs: dict[str, list[str]] = {}

    for src in sorted(by_path.keys()):
        v = by_path[src]
        if not isinstance(src, str) or not src:
            continue
        if not isinstance(v, dict):
            continue

        ir = v.get("internal_resolved_paths", [])
        iu = v.get("internal_unresolved_specs", [])

        ir_list = sorted([x for x in ir if isinstance(x, str) and x])
        iu_list = sorted([x for x in iu if isinstance(x, str) and x])

        forward_internal[src] = ir_list
        if iu_list:
            unresolved_internal_specs[src] = iu_list

        for dst in ir_list:
            reverse_internal.setdefault(dst, [])
            reverse_internal[dst].append(src)

    for dst in list(reverse_internal.keys()):
        reverse_internal[dst] = sorted(set(reverse_internal[dst]))

    counts = {
        "files_with_nodes": len(sorted(by_path.keys())),
        "edges_internal": sum(len(v) for v in forward_internal.values()),
        "files_with_unresolved_internal": len(unresolved_internal_specs),
    }

    repo_url = job.get("repo_url")
    out = {
        "schema_version": DEPENDENCY_GRAPH_SCHEMA_VERSION,
        "generated_at": utc_ts(),
        "repo": {"repo_url": repo_url, "resolved_commit": resolved_commit},
        "forward_internal": forward_internal,
        "reverse_internal": reverse_internal,
        "unresolved_internal_specs": unresolved_internal_specs,
        # schema-stable, out of scope:
        "external_specs": external_specs,
        "counts": counts,
    }

    fp_obj = {
        "repo": out["repo"],
        "forward_internal": out["forward_internal"],
        "unresolved_internal_specs": out["unresolved_internal_specs"],
        # keep in fingerprint for stability of key presence; it will be empty
        "external_specs": out["external_specs"],
    }
    out["fingerprint_sha256"] = sha256_bytes(_stable_json_bytes(fp_obj))
    return out


# --------------------------------------------------------------------------------------
# Artifact writers (atomic; deterministic formatting)
# --------------------------------------------------------------------------------------
def write_json(path: str | Path, obj: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    fd, tmp = tempfile.mkstemp(prefix=p.name + ".", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(payload)
        os.replace(tmp, p)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def _assert_pass1_repo_index_contract(repo_index: dict[str, Any]) -> None:
    """
    Fail-fast contract enforcement. No back-compat.
    """
    if repo_index.get("schema_version") != PASS1_REPO_INDEX_SCHEMA_VERSION:
        raise ValueError("PASS1 repo_index schema_version mismatch")
    job = repo_index.get("job")
    if not isinstance(job, dict):
        raise ValueError("PASS1 repo_index.job missing/invalid")
    rc = job.get("resolved_commit")
    if not isinstance(rc, str) or not rc.strip() or rc == "unknown":
        raise ValueError("PASS1 repo_index.job.resolved_commit missing/invalid")
    ii = repo_index.get("import_index")
    if not isinstance(ii, dict) or not isinstance(ii.get("by_path"), dict):
        raise ValueError("PASS1 repo_index.import_index.by_path missing/invalid")
    rp = repo_index.get("read_plan")
    if not isinstance(rp, dict):
        raise ValueError("PASS1 repo_index.read_plan missing/invalid")
    if not isinstance(rp.get("closure_seeds"), list) or not isinstance(rp.get("candidates"), list):
        raise ValueError("PASS1 repo_index.read_plan.* missing/invalid")


def generate_pass1_artifacts(
        *,
        repo_dir: str,
        job: Job,
        out_dir: str | Path,
        resolved_commit: str,
) -> dict[str, Any]:
    """
    PASS 1 "proper contract" entrypoint.

    Writes BOTH:
      - PASS1_REPO_INDEX.json
      - DEPENDENCY_GRAPH.json

    Strict:
    - resolved_commit REQUIRED (orchestrator knows it).
    - no "unknown" placeholder.
    """
    if not isinstance(resolved_commit, str) or not resolved_commit.strip():
        raise ValueError("generate_pass1_artifacts requires resolved_commit")

    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    repo_index = build_repo_index(repo_dir, job, resolved_commit=resolved_commit)
    _assert_pass1_repo_index_contract(repo_index)

    dep_graph = build_dependency_graph(repo_index)

    write_json(out_root / PASS1_REPO_INDEX_FILENAME, repo_index)
    write_json(out_root / DEPENDENCY_GRAPH_FILENAME, dep_graph)

    return {
        "pass1_repo_index_path": str(out_root / PASS1_REPO_INDEX_FILENAME),
        "dependency_graph_path": str(out_root / DEPENDENCY_GRAPH_FILENAME),
        "pass1_repo_index": repo_index,
    }
