# snapshotter/graph.py
from __future__ import annotations

import codecs
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, TypedDict

from snapshotter.git_ops import clone_and_checkout
from snapshotter.job import Job
from snapshotter.pass1 import write_json
from snapshotter.pass2_semantic import Pass2SemanticError, generate_pass2_semantic_artifacts
from snapshotter.s3_uploader import S3Uploader
from snapshotter.utils import sha256_bytes, stable_json_fingerprint_sha256, utc_ts
from snapshotter.validate_basic import validate_basic_artifacts

try:
    from langgraph.graph import END, StateGraph
except Exception as e:  # pragma: no cover
    raise RuntimeError("LangGraph is required. Install 'langgraph'.") from e


# -----------------------------
# Stages (canonical)
# -----------------------------
STAGE_INIT = "init"
STAGE_PARSE_JOB = "parse_job"
STAGE_CLONE = "clone"
STAGE_PASS1_REPO_INDEX = "pass1_repo_index"
STAGE_PASS2_MAKE_READ_PLAN = "pass2_make_read_plan"
STAGE_PASS2_FETCH_FILES = "pass2_fetch_files"
STAGE_PASS2_GENERATE_OUTPUTS = "pass2_generate_outputs"
STAGE_PASS1_MANIFEST = "pass1_manifest"
STAGE_VALIDATE_BASIC = "validate_basic"
STAGE_UPLOAD = "upload"
STAGE_EMIT_RESULT = "emit_result"
STAGE_DONE = "done"
STAGE_DONE_DRY_RUN = "done_dry_run"


class SnapshotterStageError(RuntimeError):
    def __init__(self, stage: str, inner: Exception):
        super().__init__(str(inner))
        self.stage = stage
        self.inner = inner


@dataclass(frozen=True)
class RuntimeConfig:
    dry_run: bool
    aws_region: str | None


class SnapshotterState(TypedDict, total=False):
    payload: dict[str, Any]
    payload_src: str
    config: RuntimeConfig
    stage: str

    job: Job
    resolved_commit: str

    workdir: str
    repo_dir: str
    out_dir: str

    local_paths: dict[str, str]

    repo_index: dict[str, Any]

    # pass2 planning/fetching
    read_plan: list[str]
    pass2_caps: dict[str, int]
    read_plan_missing: list[str]
    file_contents_map: dict[str, str]

    # pass2 fetch reporting
    pass2_total_chars: int
    pass2_files_read: list[dict[str, Any]]
    pass2_not_read_reasons: dict[str, str]

    # pass2 planning debug (optional)
    pass2_read_plan_debug: dict[str, Any]

    # upload/output
    s3_paths: dict[str, Optional[str]]
    result: dict[str, Any]


# -----------------------------
# Artifact Path Registry - SINGLE SOURCE OF TRUTH
# -----------------------------
def build_local_paths(out_dir: str) -> dict[str, str]:
    """Centralized definition of all artifact file paths."""
    out_dir_path = Path(out_dir)
    return {
        # Pass1 artifacts (canonical)
        "pass1_repo_index": str(out_dir_path / "PASS1_REPO_INDEX.json"),
        "dependency_graph": str(out_dir_path / "DEPENDENCY_GRAPH.json"),

        # Convenience alias (non-canonical)
        "repo_index": str(out_dir_path / "repo_index.json"),

        # Pass2 semantic artifacts
        "pass2_semantic": str(out_dir_path / "PASS2_SEMANTIC.json"),
        "pass2_arch_pack": str(out_dir_path / "PASS2_ARCH_PACK.json"),
        "pass2_support_pack": str(out_dir_path / "PASS2_SUPPORT_PACK.json"),
        "pass2_llm_raw_output": str(out_dir_path / "PASS2_LLM_RAW_OUTPUT.txt"),
        "pass2_llm_repaired_output": str(out_dir_path / "PASS2_LLM_REPAIRED_OUTPUT.txt"),

        # Derived artifacts
        "architecture_snapshot": str(out_dir_path / "ARCHITECTURE_SUMMARY_SNAPSHOT.json"),
        "gaps": str(out_dir_path / "GAPS_AND_INCONSISTENCIES.json"),
        "onboarding": str(out_dir_path / "ONBOARDING.md"),
        "artifact_manifest": str(out_dir_path / "artifact_manifest.json"),
    }


def get_validation_paths(local_paths: dict[str, str]) -> dict[str, str]:
    """Extract paths required for validation."""
    return {
        "repo_index": local_paths["repo_index"],
        "artifact_manifest": local_paths["artifact_manifest"],
        "architecture_snapshot": local_paths["architecture_snapshot"],
        "gaps": local_paths["gaps"],
        "onboarding": local_paths["onboarding"],
        "pass2_semantic": local_paths["pass2_semantic"],
    }


# -----------------------------
# Helpers
# -----------------------------
def _file_sha256(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def _stable_fingerprint_for_artifact(path: Path) -> str:
    raw = path.read_bytes()
    if path.suffix.lower() == ".json":
        try:
            obj = json.loads(raw.decode("utf-8"))
            return stable_json_fingerprint_sha256(obj)
        except Exception:
            return sha256_bytes(raw)
    return sha256_bytes(raw)


def _read_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    obj = json.loads(raw.decode("utf-8"))
    return obj if isinstance(obj, dict) else {}


def _require_file(path: Path, *, label: str) -> None:
    if not path.exists():
        raise RuntimeError(f"required artifact missing: {label} ({path})")
    try:
        if path.stat().st_size <= 0:
            raise RuntimeError(f"required artifact empty: {label} ({path})")
    except FileNotFoundError:
        raise RuntimeError(f"required artifact missing: {label} ({path})")


def build_artifact_manifest(local_paths: dict[str, str]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    stable_fingerprints: dict[str, str] = {}

    # Artifacts to include in manifest (excluding debug/raw files)
    manifest_artifacts = [
        "pass1_repo_index",
        "dependency_graph",
        "repo_index",
        "architecture_snapshot",
        "gaps",
        "onboarding",
        "pass2_semantic",
        "pass2_arch_pack",
        "pass2_support_pack",
    ]

    for name in manifest_artifacts:
        p = local_paths.get(name)
        if not p:
            continue
        path = Path(p)
        if not path.exists():
            continue

        raw = path.read_bytes()
        items.append(
            {
                "name": name,
                "filename": path.name,
                "bytes": len(raw),
                "sha256": sha256_bytes(raw),
            }
        )
        stable_fingerprints[name] = _stable_fingerprint_for_artifact(path)

    items.sort(key=lambda x: x["name"])

    canonical = json.dumps(
        stable_fingerprints,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    run_fingerprint_sha256 = sha256_bytes(canonical)

    return {
        "generated_at": utc_ts(),
        "items": items,
        "stable_fingerprints": stable_fingerprints,
        "run_fingerprint_sha256": run_fingerprint_sha256,
    }


def _repo_index_included_paths(repo_index: dict[str, Any]) -> list[str]:
    files = repo_index.get("files", []) or []
    out: list[str] = []
    for f in files:
        if not isinstance(f, dict):
            continue
        p = f.get("path")
        if isinstance(p, str) and p:
            out.append(p)
    return sorted(out)


def _pass2_defaults_from_env() -> dict[str, int]:
    """
    Pass 2 fetch caps.
    """
    max_files = int(os.environ.get("SNAPSHOTTER_PASS2_MAX_FILES", "120"))

    max_total_chars_raw = os.environ.get("SNAPSHOTTER_PASS2_MAX_TOTAL_CHARS", "").strip()
    max_total_chars = int(max_total_chars_raw) if max_total_chars_raw else 250000

    max_chars_per_file_raw = os.environ.get("SNAPSHOTTER_PASS2_MAX_CHARS_PER_FILE", "").strip()
    max_chars_per_file = int(max_chars_per_file_raw) if max_chars_per_file_raw else 0

    caps: dict[str, int] = {"max_files": max_files, "max_total_chars": max_total_chars}
    if max_chars_per_file > 0:
        caps["max_chars_per_file"] = max_chars_per_file
    return caps


def _require_read_plan_obj(repo_index: dict[str, Any]) -> dict[str, Any]:
    """
    LOCKED CONTRACT:
      - Pass1 MUST emit repo_index["read_plan"] as an object (dict).
    """
    rp = repo_index.get("read_plan")
    if not isinstance(rp, dict):
        raise RuntimeError("PASS1_REPO_INDEX.read_plan must be an object (dict)")
    return rp


def _extract_candidate_paths(repo_index: dict[str, Any]) -> list[str]:
    """
    Extract Pass1 read plan candidates.
    """
    rp = _require_read_plan_obj(repo_index)
    v = rp.get("candidates")

    if not isinstance(v, list) or not v:
        raise RuntimeError("PASS1_REPO_INDEX.read_plan.candidates must be a non-empty list")

    out: list[str] = []
    for it in v:
        if isinstance(it, str) and it:
            out.append(it)
            continue
        if isinstance(it, dict):
            p = it.get("path")
            if isinstance(p, str) and p:
                out.append(p)
                continue
        raise RuntimeError("PASS1_REPO_INDEX.read_plan.candidates contains invalid entry")

    return out


def _extract_closure_seed_paths(repo_index: dict[str, Any]) -> list[str]:
    """
    Extract Pass1 read plan closure seeds.
    """
    rp = _require_read_plan_obj(repo_index)
    v = rp.get("closure_seeds")

    if v is None:
        return []

    if not isinstance(v, list):
        raise RuntimeError("PASS1_REPO_INDEX.read_plan.closure_seeds must be a list when present")

    out: list[str] = []
    for it in v:
        if isinstance(it, str) and it:
            out.append(it)
            continue
        if isinstance(it, dict):
            p = it.get("path")
            if isinstance(p, str) and p:
                out.append(p)
                continue
        raise RuntimeError("PASS1_REPO_INDEX.read_plan.closure_seeds contains invalid entry")

    return out


def _deterministic_read_plan(repo_index: dict[str, Any], *, max_files: int) -> tuple[list[str], dict[str, Any]]:
    """
    Deterministic plan selection.
    """
    seed_paths = _extract_closure_seed_paths(repo_index)
    cand_paths = _extract_candidate_paths(repo_index)

    raw_combined = seed_paths + cand_paths
    combined_dedup = list(dict.fromkeys(raw_combined))

    included = _repo_index_included_paths(repo_index)
    included_set = set(included)

    before_filter = len(combined_dedup)
    plan = [p for p in combined_dedup if p in included_set]
    filtered_out = before_filter - len(plan)

    used_topoff = False
    if len(plan) < max_files:
        used_topoff = True
        seen = set(plan)
        for p in included:
            if p in seen:
                continue
            plan.append(p)
            seen.add(p)
            if len(plan) >= max_files:
                break

    final = plan[:max_files]

    debug: dict[str, Any] = {
        "max_files": max_files,
        "closure_seeds_len_raw": len(seed_paths),
        "candidates_len_raw": len(cand_paths),
        "combined_len_raw": len(raw_combined),
        "combined_len_deduped": len(combined_dedup),
        "combined_filtered_out_not_in_repo": filtered_out,
        "included_len": len(included),
        "used_topoff": used_topoff,
        "final_plan_len": len(final),
    }
    return final, debug


def _llm_read_plan_stub(repo_index: dict[str, Any], *, max_files: int) -> tuple[list[str], list[str], dict[str, Any]]:
    """
    v0.1 uses deterministic plan selection.
    """
    plan, debug = _deterministic_read_plan(repo_index, max_files=max_files)
    return plan, [], debug


def _stream_read_utf8_with_replacement(path: Path, *, max_chars: int) -> tuple[str, bool]:
    """
    Stream read file as UTF-8 with replacement, up to max_chars characters.
    """
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    chunks: list[str] = []
    total = 0
    hit_limit = False

    with path.open("rb") as f:
        while True:
            b = f.read(8192)
            if not b:
                break
            s = decoder.decode(b)
            if not s:
                continue
            chunks.append(s)
            total += len(s)

            if total >= max_chars:
                overflow = total - max_chars
                if overflow > 0:
                    chunks[-1] = chunks[-1][:-overflow]
                hit_limit = True
                break

        if not hit_limit:
            tail = decoder.decode(b"", final=True)
            if tail:
                chunks.append(tail)

    return "".join(chunks), hit_limit


def _compute_files_not_read(
        *,
        repo_index: dict[str, Any],
        files_read: list[dict[str, Any]],
        read_plan_selected: list[str],
        not_read_reasons_for_selected: dict[str, str],
) -> list[dict[str, Any]]:
    """
    Build files_not_read across *all included* paths.
    """
    included_paths = _repo_index_included_paths(repo_index)

    read_paths = [
        it.get("path")
        for it in files_read
        if isinstance(it, dict) and isinstance(it.get("path"), str) and it.get("path")
    ]
    read_set = set(read_paths)

    plan_set = {p for p in read_plan_selected if isinstance(p, str) and p}

    out: list[dict[str, Any]] = []
    for p in included_paths:
        if p in read_set:
            continue

        reason = not_read_reasons_for_selected.get(p)
        if not reason:
            reason = "not_in_read_plan" if p not in plan_set else "unknown_not_read"
        out.append({"path": p, "reason": reason})

    return out


def _infer_module_type(path: str) -> str:
    """Infer module type from file path."""
    p = path.lower()
    if p.endswith(".py"):
        if "routers/" in p or "routes/" in p:
            return "api_router"
        elif "models/" in p or "schemas/" in p:
            return "data_model"
        elif "security" in p or "auth" in p:
            return "security"
        elif "migrations/" in p:
            return "migration"
        elif "scripts/" in p:
            return "script"
        elif "config" in p:
            return "configuration"
        else:
            return "backend_module"
    elif p.endswith((".ts", ".tsx", ".js", ".jsx")):
        if "/app/" in p or "/pages/" in p:
            if "layout" in p:
                return "layout"
            elif "page" in p:
                return "page"
            elif "route" in p:
                return "api_route"
        elif "/components/" in p:
            return "ui_component"
        elif "/lib/" in p or "/utils/" in p:
            return "utility"
        elif "middleware" in p:
            return "middleware"
        else:
            return "frontend_module"
    elif p.endswith(".md"):
        return "documentation"
    else:
        return "unknown"


def _extract_modules_from_llm_output(llm_output: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Extract architecture modules from LLM output evidence.
    Returns deterministic, normalized modules list.
    """
    modules: list[dict[str, Any]] = []

    # Extract from evidence.notable_files
    evidence = llm_output.get("evidence", {})
    notable_files = evidence.get("notable_files", [])

    if not isinstance(notable_files, list):
        return modules

    # Group by inferred module name for deduplication
    module_map: dict[str, dict[str, Any]] = {}

    for nf in notable_files:
        if not isinstance(nf, dict):
            continue

        path = nf.get("path")
        why = nf.get("why", "")

        if not isinstance(path, str) or not path:
            continue

        # Infer module name from path (without extension)
        module_name = Path(path).stem
        if not module_name:
            continue

        # Normalize module name (camelCase to Title Case)
        module_name_norm = module_name.replace("_", " ").replace("-", " ").title()

        if module_name_norm not in module_map:
            module_map[module_name_norm] = {
                "name": module_name_norm,
                "type": _infer_module_type(path),
                "evidence_paths": [],
                "responsibilities": [],
                "dependencies": []
            }

        module = module_map[module_name_norm]

        # Add evidence path if not already present
        if path not in module["evidence_paths"]:
            module["evidence_paths"].append(path)

        # Add responsibility from "why" if meaningful
        if isinstance(why, str) and why.strip():
            clean_why = why.strip()
            if clean_why and clean_why not in module["responsibilities"]:
                module["responsibilities"].append(clean_why[:200])  # Truncate for consistency

    # Convert to list and sort for determinism
    for module in module_map.values():
        # Ensure evidence_paths is sorted
        module["evidence_paths"].sort()

        # Ensure responsibilities is sorted and non-empty
        module["responsibilities"].sort()
        if not module["responsibilities"]:
            module["responsibilities"] = ["Module extracted from architectural evidence"]

        modules.append(module)

    # Sort modules by name for determinism
    modules.sort(key=lambda m: m["name"])

    return modules


def _normalize_architecture_snapshot(
        *,
        arch: dict[str, Any],
        repo_url: str,
        resolved_commit: str,
        job_id: str,
        repo_index: dict[str, Any],
        read_plan_selected: list[str],
        read_plan_missing: list[str],
        pass2_caps: dict[str, int],
        read_plan_source: str,
        read_plan_debug: dict[str, Any] | None,
        pass2_total_chars: int,
        files_read: list[dict[str, Any]],
        files_not_read: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Force self-auditing + required top-level keys.
    """
    out = dict(arch or {})

    # ENFORCE CORRECT SCHEMA VERSION
    out["schema_version"] = "architecture_snapshot.v1"
    out["generated_at"] = utc_ts()
    out["repo"] = {"repo_url": repo_url, "resolved_commit": resolved_commit or "unknown", "job_id": job_id}

    out["read_plan"] = {
        "selected_paths": read_plan_selected,
        "missing_paths": read_plan_missing,
        "caps": pass2_caps,
        "source": read_plan_source,
    }
    if read_plan_debug is not None:
        out["read_plan_debug"] = read_plan_debug

    files_scanned = int(repo_index.get("counts", {}).get("files_scanned", 0))
    files_included = int(repo_index.get("counts", {}).get("files_included", 0))

    out["coverage"] = {
        "files_scanned": files_scanned,
        "files_read": len(files_read),
        "files_not_read": len(files_not_read),
        "files_included_from_pass1": files_included,
    }
    out["pass2_total_chars"] = int(pass2_total_chars)

    out["files_read"] = files_read
    out["files_not_read"] = files_not_read

    # Ensure modules list exists and is properly normalized
    modules = out.get("modules")
    if not isinstance(modules, list):
        modules = []
        out["modules"] = modules

    uncertainties = out.get("uncertainties")
    if not isinstance(uncertainties, list):
        uncertainties = []
        out["uncertainties"] = uncertainties

    # Normalize each module
    for i, m in enumerate(modules):
        if not isinstance(m, dict):
            continue

        name = m.get("name")
        if not isinstance(name, str) or not name.strip():
            m["name"] = f"unknown_module_{i}"

        mtype = m.get("type")
        if not isinstance(mtype, str) or not mtype.strip():
            m["type"] = "unknown"

        ev = m.get("evidence_paths")
        if not isinstance(ev, list):
            ev = []
        ev = [p for p in ev if isinstance(p, str) and p]
        m["evidence_paths"] = ev

        resp = m.get("responsibilities")
        if not isinstance(resp, list) or not resp:
            resp = []
        resp = [r for r in resp if isinstance(r, str) and r.strip()]

        if not ev:
            m["responsibilities"] = ["unknown"]
            uncertainties.append(
                {
                    "type": "ungrounded_module",
                    "description": f"Module '{m['name']}' lacks evidence_paths in files_read; responsibilities set to unknown.",
                    "files_involved": [],
                    "suggested_questions": ["Which files define this module's responsibilities? Add them to read_plan."],
                }
            )
        else:
            if not resp:
                m["responsibilities"] = ["unknown"]
                uncertainties.append(
                    {
                        "type": "empty_responsibilities",
                        "description": f"Module '{m['name']}' had no responsibilities listed; set to unknown.",
                        "files_involved": ev,
                        "suggested_questions": ["What does this module do? Add explicit responsibilities."],
                    }
                )
            else:
                m["responsibilities"] = resp

        deps = m.get("dependencies")
        if not isinstance(deps, list):
            deps = []
        deps = [d for d in deps if isinstance(d, str) and d.strip()]
        m["dependencies"] = deps

    return out


# -----------------------------
# Nodes
# -----------------------------
def node_load_job(state: SnapshotterState) -> SnapshotterState:
    stage = STAGE_PARSE_JOB
    try:
        job = Job.model_validate(state["payload"]).finalize()

        workdir = ".snapshotter_tmp"
        repo_dir = f"{workdir}/repo"
        out_dir = f"out/{job.repo_slug or 'repo'}/{job.timestamp_utc or 'ts'}/{job.job_id or 'job'}"
        Path(workdir).mkdir(parents=True, exist_ok=True)
        Path(out_dir).mkdir(parents=True, exist_ok=True)

        # Build ALL artifact paths in one place
        local_paths = build_local_paths(out_dir)

        state["stage"] = stage
        state["job"] = job
        state["workdir"] = workdir
        state["repo_dir"] = repo_dir
        state["out_dir"] = out_dir
        state["local_paths"] = local_paths
        return state
    except Exception as e:
        raise SnapshotterStageError(stage, e) from e


def node_clone_repo(state: SnapshotterState) -> SnapshotterState:
    stage = STAGE_CLONE
    try:
        job = state["job"]
        resolved_commit = clone_and_checkout(job.repo_url, job.ref, state["workdir"])
        state["stage"] = stage
        state["resolved_commit"] = resolved_commit
        return state
    except Exception as e:
        raise SnapshotterStageError(stage, e) from e


def node_pass1_build_index(state: SnapshotterState) -> SnapshotterState:
    """
    LOCKED CONTRACT:
      - Pass1 stage MUST produce BOTH:
          * PASS1_REPO_INDEX.json (canonical)
          * DEPENDENCY_GRAPH.json (canonical)
    """
    stage = STAGE_PASS1_REPO_INDEX
    try:
        job = state["job"]
        lp = state["local_paths"]
        out_dir = Path(state["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)

        resolved_commit = state.get("resolved_commit", "unknown")

        from snapshotter.pass1 import generate_pass1_artifacts

        # Run Pass1 (canonical artifact writer).
        generate_pass1_artifacts(
            repo_dir=state["repo_dir"],
            job=job,
            out_dir=str(out_dir),
            resolved_commit=resolved_commit,
        )

        pass1_repo_index_path = Path(lp["pass1_repo_index"])
        dependency_graph_path = Path(lp["dependency_graph"])

        # Enforce contract: both artifacts must exist and be non-empty.
        _require_file(pass1_repo_index_path, label="PASS1_REPO_INDEX")
        _require_file(dependency_graph_path, label="DEPENDENCY_GRAPH")

        # Load canonical repo_index.
        repo_index = _read_json(pass1_repo_index_path)

        # Enforce resolved_commit injection correctness.
        job_obj = repo_index.get("job")
        if not isinstance(job_obj, dict):
            raise RuntimeError("PASS1_REPO_INDEX.job must be an object (dict)")
        rc = job_obj.get("resolved_commit")
        if not isinstance(rc, str) or not rc:
            raise RuntimeError("PASS1_REPO_INDEX.job.resolved_commit is required (missing/empty)")
        if rc != resolved_commit:
            raise RuntimeError(
                f"resolved_commit mismatch: pass1_repo_index has '{rc}' but orchestrator resolved '{resolved_commit}'"
            )

        # Convenience alias for tools that still look for repo_index.json.
        write_json(lp["repo_index"], repo_index)

        state["stage"] = stage
        state["repo_index"] = repo_index
        return state
    except Exception as e:
        raise SnapshotterStageError(stage, e) from e


def node_pass2_make_read_plan(state: SnapshotterState) -> SnapshotterState:
    stage = STAGE_PASS2_MAKE_READ_PLAN
    try:
        caps = _pass2_defaults_from_env()
        repo_index = state["repo_index"]

        included_paths = _repo_index_included_paths(repo_index)
        included_set = set(included_paths)

        selected, requested_missing, plan_debug = _llm_read_plan_stub(repo_index, max_files=caps["max_files"])

        # Gate selection to repo-included paths
        selected_in_repo = [p for p in selected if isinstance(p, str) and p in included_set]

        # Missing: anything explicitly requested_missing + anything selected but not in repo
        missing_set: set[str] = set()
        for p in requested_missing:
            if isinstance(p, str) and p and p not in included_set:
                missing_set.add(p)
        for p in selected:
            if isinstance(p, str) and p and p not in included_set:
                missing_set.add(p)
        missing = sorted(missing_set)

        # Cap then de-dupe preserving order
        selected_in_repo = selected_in_repo[: caps["max_files"]]
        seen: set[str] = set()
        final_plan: list[str] = []
        for p in selected_in_repo:
            if p in seen:
                continue
            seen.add(p)
            final_plan.append(p)

        plan_debug = dict(plan_debug or {})
        plan_debug["final_plan_len_after_repo_gate"] = len(final_plan)
        plan_debug["caps_max_files"] = int(caps.get("max_files", 0))

        state["stage"] = stage
        state["read_plan"] = final_plan
        state["pass2_caps"] = caps
        state["read_plan_missing"] = missing
        state["pass2_read_plan_debug"] = plan_debug
        return state
    except Exception as e:
        raise SnapshotterStageError(stage, e) from e


def node_pass2_fetch_files(state: SnapshotterState) -> SnapshotterState:
    stage = STAGE_PASS2_FETCH_FILES
    try:
        repo_dir = Path(state["repo_dir"])
        caps = state.get("pass2_caps", _pass2_defaults_from_env())
        max_total = int(caps.get("max_total_chars", 250000))
        max_per_file = int(caps.get("max_chars_per_file", 0))  # optional; 0 => disabled

        total_chars = 0
        contents: dict[str, str] = {}
        files_read: list[dict[str, Any]] = []
        not_read_reasons: dict[str, str] = {}

        plan = state.get("read_plan", [])

        for rel in plan:
            if not isinstance(rel, str) or not rel:
                continue

            remaining = max_total - total_chars
            if remaining <= 0:
                not_read_reasons[rel] = "exceeds_total_char_cap"
                continue

            fp = repo_dir / rel
            if not fp.exists():
                not_read_reasons[rel] = "missing_on_disk"
                continue

            try:
                if max_per_file > 0 and max_per_file <= remaining:
                    text, hit = _stream_read_utf8_with_replacement(fp, max_chars=max_per_file + 1)
                    longer_than_cap = hit or (len(text) > max_per_file)
                    if longer_than_cap:
                        text = text[:max_per_file]
                    n = len(text)

                    if n > remaining:
                        not_read_reasons[rel] = "exceeds_total_char_cap"
                        continue

                    contents[rel] = text
                    total_chars += n
                    files_read.append({"path": rel, "chars": n, "truncated": bool(longer_than_cap)})
                    continue

                text, hit = _stream_read_utf8_with_replacement(fp, max_chars=remaining + 1)
                too_big = hit or (len(text) > remaining)
                if too_big:
                    not_read_reasons[rel] = "exceeds_total_char_cap"
                    continue

                n = len(text)
                contents[rel] = text
                total_chars += n
                files_read.append({"path": rel, "chars": n, "truncated": False})

            except Exception:
                not_read_reasons[rel] = "decode_issues"
                continue

        state["stage"] = stage
        state["file_contents_map"] = contents
        state["pass2_total_chars"] = total_chars
        state["pass2_files_read"] = files_read
        state["pass2_not_read_reasons"] = not_read_reasons
        return state
    except Exception as e:
        raise SnapshotterStageError(stage, e) from e


def node_pass2_generate_outputs(state: SnapshotterState) -> SnapshotterState:
    stage = STAGE_PASS2_GENERATE_OUTPUTS
    try:
        job = state["job"]
        lp = state["local_paths"]
        repo_index = state["repo_index"]
        resolved_commit = state.get("resolved_commit", "unknown")

        files_read = state.get("pass2_files_read", [])
        not_read_reasons = state.get("pass2_not_read_reasons", {})
        files_not_read = _compute_files_not_read(
            repo_index=repo_index,
            files_read=files_read,
            read_plan_selected=state.get("read_plan", []),
            not_read_reasons_for_selected=not_read_reasons,
        )

        # NEW Pass2 API (pass2_semantic.py)
        pass2_out = generate_pass2_semantic_artifacts(
            repo_dir=state["repo_dir"],
            job=job,
            out_dir=Path(state["out_dir"]),
            pass1_repo_index=repo_index,
            repo_url=job.repo_url,
        )

        pass2_semantic = pass2_out.get("pass2_semantic", {}) if isinstance(pass2_out, dict) else {}
        llm_out = pass2_semantic.get("llm_output", {}) if isinstance(pass2_semantic, dict) else {}
        if not isinstance(llm_out, dict):
            llm_out = {}

        # FIXED: Extract clean summary without LLM-hallucinated caps
        summary = llm_out.get("summary", {}) if isinstance(llm_out.get("summary"), dict) else {}

        # Remove any hallucinated caps from summary
        clean_summary = {
            "primary_stack": summary.get("primary_stack"),
            "architecture_overview": summary.get("architecture_overview", ""),
            "key_components": summary.get("key_components", []),
            "data_flows": summary.get("data_flows", []),
            "auth_and_routing_notes": summary.get("auth_and_routing_notes", []),
            "risks_or_gaps": summary.get("risks_or_gaps", []),
        }

        # Ensure required fields are present
        if not isinstance(clean_summary["architecture_overview"], str):
            clean_summary["architecture_overview"] = ""
        if not isinstance(clean_summary["key_components"], list):
            clean_summary["key_components"] = []
        if not isinstance(clean_summary["data_flows"], list):
            clean_summary["data_flows"] = []
        if not isinstance(clean_summary["auth_and_routing_notes"], list):
            clean_summary["auth_and_routing_notes"] = []
        if not isinstance(clean_summary["risks_or_gaps"], list):
            clean_summary["risks_or_gaps"] = []

        # Extract modules from LLM output evidence
        modules = _extract_modules_from_llm_output(llm_out)

        # Build proper architecture snapshot
        arch = {
            "schema_version": "architecture_snapshot.v1",
            "generated_at": utc_ts(),
            "repo": {"repo_url": job.repo_url, "resolved_commit": resolved_commit},
            "summary": clean_summary,
            "modules": modules,
            "uncertainties": [],
            # evidence block preserved from llm_output if present
            "evidence": llm_out.get("evidence", {}) if isinstance(llm_out.get("evidence"), dict) else {},
        }

        # Gaps extraction (clean, no source pollution)
        gaps_raw = {
            "schema_version": "gaps.v1",
            "generated_at": utc_ts(),
            "repo": {"repo_url": job.repo_url, "resolved_commit": resolved_commit},
            "risks_or_gaps": clean_summary["risks_or_gaps"],
        }

        # ONBOARDING.md: lightweight onboarding from clean summary
        lines: list[str] = []
        lines.append(f"# Onboarding\n")
        primary_stack = clean_summary.get("primary_stack")
        if isinstance(primary_stack, str) and primary_stack.strip():
            lines.append(f"**Primary stack:** {primary_stack.strip()}\n")

        overview = clean_summary.get("architecture_overview")
        if isinstance(overview, str) and overview.strip():
            lines.append("## Overview\n")
            lines.append(overview.strip() + "\n")

        key_components = clean_summary.get("key_components")
        if isinstance(key_components, list) and key_components:
            lines.append("## Key components\n")
            for x in key_components:
                if isinstance(x, str) and x.strip():
                    lines.append(f"- {x.strip()}")
            lines.append("")

        data_flows = clean_summary.get("data_flows")
        if isinstance(data_flows, list) and data_flows:
            lines.append("## Data flows\n")
            for x in data_flows:
                if isinstance(x, str) and x.strip():
                    lines.append(f"- {x.strip()}")
            lines.append("")

        auth_notes = clean_summary.get("auth_and_routing_notes")
        if isinstance(auth_notes, list) and auth_notes:
            lines.append("## Auth and routing notes\n")
            for x in auth_notes:
                if isinstance(x, str) and x.strip():
                    lines.append(f"- {x.strip()}")
            lines.append("")

        onboarding_md = "\n".join(lines).strip() + "\n"

        # Normalize architecture snapshot with coverage data
        arch = _normalize_architecture_snapshot(
            arch=arch,
            repo_url=job.repo_url,
            resolved_commit=resolved_commit,
            job_id=job.job_id or "unknown",
            repo_index=repo_index,
            read_plan_selected=state.get("read_plan", []),
            read_plan_missing=state.get("read_plan_missing", []),
            pass2_caps=state.get("pass2_caps", _pass2_defaults_from_env()),
            read_plan_source="pass2_semantic",
            read_plan_debug=state.get("pass2_read_plan_debug"),
            pass2_total_chars=int(state.get("pass2_total_chars", 0)),
            files_read=files_read,
            files_not_read=files_not_read,
        )

        write_json(lp["architecture_snapshot"], arch)
        write_json(lp["gaps"], gaps_raw)
        Path(lp["onboarding"]).write_text(onboarding_md, encoding="utf-8")

        state["stage"] = stage
        return state
    except Exception as e:
        raise SnapshotterStageError(stage, e) from e


def node_pass1_manifest(state: SnapshotterState) -> SnapshotterState:
    stage = STAGE_PASS1_MANIFEST
    try:
        lp = state["local_paths"]

        # Enforce contract again before fingerprinting/upload selection.
        _require_file(Path(lp["pass1_repo_index"]), label="PASS1_REPO_INDEX")
        _require_file(Path(lp["dependency_graph"]), label="DEPENDENCY_GRAPH")

        manifest = build_artifact_manifest(lp)
        write_json(lp["artifact_manifest"], manifest)
        state["stage"] = stage
        return state
    except Exception as e:
        raise SnapshotterStageError(stage, e) from e


def node_validate_basic(state: SnapshotterState) -> SnapshotterState:
    stage = STAGE_VALIDATE_BASIC
    try:
        validation_paths = get_validation_paths(state["local_paths"])
        validate_basic_artifacts(validation_paths)
        state["stage"] = stage
        return state
    except Exception as e:
        raise SnapshotterStageError(stage, e) from e


def node_upload_artifacts(state: SnapshotterState) -> SnapshotterState:
    stage = STAGE_UPLOAD
    try:
        job = state["job"]
        cfg = state["config"]
        lp = state["local_paths"]

        uploader = S3Uploader(bucket=job.output.s3_bucket, prefix=job.s3_job_prefix(), region=cfg.aws_region)

        if cfg.dry_run:
            state["stage"] = stage
            state["s3_paths"] = {}
            return state

        # Upload all artifacts defined in local_paths (except debug/raw files)
        upload_candidates = [
            "pass1_repo_index",
            "dependency_graph",
            "repo_index",
            "artifact_manifest",
            "architecture_snapshot",
            "gaps",
            "onboarding",
            "pass2_semantic",
            "pass2_arch_pack",
            "pass2_support_pack",
        ]

        s3_paths: dict[str, Optional[str]] = {}
        for key in upload_candidates:
            path = lp.get(key)
            if not path:
                continue
            p = Path(path)
            if not p.exists():
                continue

            content_type = "application/json" if p.suffix == ".json" else "text/markdown"
            s3_paths[key] = uploader.upload_file(p.name, path, content_type=content_type)

        state["stage"] = stage
        state["s3_paths"] = s3_paths
        return state
    except Exception as e:
        raise SnapshotterStageError(stage, e) from e


def node_emit_result(state: SnapshotterState) -> SnapshotterState:
    stage = STAGE_EMIT_RESULT
    try:
        job = state["job"]
        cfg = state["config"]
        resolved_commit = state.get("resolved_commit", "unknown")
        lp = state["local_paths"]

        repo_index_sha = _file_sha256(lp["repo_index"])

        if cfg.dry_run:
            state["result"] = {
                "ok": True,
                "stage": STAGE_DONE_DRY_RUN,
                "job_id": job.job_id,
                "repo_url": job.repo_url,
                "requested_ref": job.ref,
                "resolved_commit": resolved_commit,
                "s3_bucket": job.output.s3_bucket,
                "s3_prefix": job.s3_job_prefix(),
                "job_payload_source": state.get("payload_src", "unknown"),
                "artifacts_local": lp,  # Include ALL local paths
                "hashes": {"repo_index_sha256": repo_index_sha},
            }
            state["stage"] = stage
            return state

        s3p = state.get("s3_paths", {})
        state["result"] = {
            "ok": True,
            "stage": STAGE_DONE,
            "job_id": job.job_id,
            "repo_url": job.repo_url,
            "requested_ref": job.ref,
            "resolved_commit": resolved_commit,
            "s3_bucket": job.output.s3_bucket,
            "s3_prefix": job.s3_job_prefix(),
            "job_payload_source": state.get("payload_src", "unknown"),
            "artifacts_s3": s3p,
            "artifacts_local": lp,
            "hashes": {"repo_index_sha256": repo_index_sha},
        }
        state["stage"] = stage
        return state
    except Exception as e:
        raise SnapshotterStageError(stage, e) from e


# -----------------------------
# Graph wiring
# -----------------------------
def build_snapshotter_graph():
    g = StateGraph(SnapshotterState)

    g.add_node("load_job", node_load_job)
    g.add_node("clone_repo", node_clone_repo)
    g.add_node("pass1_build_index", node_pass1_build_index)
    g.add_node("pass2_make_read_plan", node_pass2_make_read_plan)
    g.add_node("pass2_fetch_files", node_pass2_fetch_files)
    g.add_node("pass2_generate_outputs", node_pass2_generate_outputs)
    g.add_node("pass1_manifest", node_pass1_manifest)
    g.add_node("validate_basic", node_validate_basic)
    g.add_node("upload_artifacts", node_upload_artifacts)
    g.add_node("emit_result", node_emit_result)

    g.set_entry_point("load_job")
    g.add_edge("load_job", "clone_repo")
    g.add_edge("clone_repo", "pass1_build_index")
    g.add_edge("pass1_build_index", "pass2_make_read_plan")
    g.add_edge("pass2_make_read_plan", "pass2_fetch_files")
    g.add_edge("pass2_fetch_files", "pass2_generate_outputs")
    g.add_edge("pass2_generate_outputs", "pass1_manifest")
    g.add_edge("pass1_manifest", "validate_basic")
    g.add_edge("validate_basic", "upload_artifacts")
    g.add_edge("upload_artifacts", "emit_result")
    g.add_edge("emit_result", END)

    return g.compile()


def run_snapshotter_graph(
        *,
        payload: dict[str, Any],
        payload_src: str,
        dry_run: bool,
        aws_region: str | None,
) -> dict[str, Any]:
    app = build_snapshotter_graph()
    state: SnapshotterState = {
        "payload": payload,
        "payload_src": payload_src,
        "config": RuntimeConfig(dry_run=dry_run, aws_region=aws_region),
        "stage": STAGE_INIT,
    }
    final_state = app.invoke(state)
    return final_state["result"]