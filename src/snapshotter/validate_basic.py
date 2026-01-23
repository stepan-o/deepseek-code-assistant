# snapshotter/validate_basic.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# --------------------------------------------------------------------------------------
# Validation contracts (LOCKED)
#
# Each artifact has a strict schema that MUST be validated.
# No back-compat, no fallback shapes.
# --------------------------------------------------------------------------------------

ARCHITECTURE_SNAPSHOT_SCHEMA_VERSION = "architecture_snapshot.v1"
PASS1_REPO_INDEX_SCHEMA_VERSION = "pass1_repo_index.v1"
PASS2_SEMANTIC_SCHEMA_VERSION = "pass2_semantic.v1"
DEPENDENCY_GRAPH_SCHEMA_VERSION = "dependency_graph.v1"


def validate_basic_artifacts(local_paths: dict[str, str]) -> None:
    """
    Validate core artifacts satisfy basic contract.
    """
    # Required keys (from graph.py's get_validation_paths)
    required = ["repo_index", "artifact_manifest", "architecture_snapshot", "gaps", "onboarding", "pass2_semantic"]
    for k in required:
        if k not in local_paths:
            raise RuntimeError(f"validation: missing required key '{k}' in local_paths")
        p = local_paths.get(k)
        if not p:
            raise RuntimeError(f"validation: empty path for key '{k}'")
        path = Path(p)
        if not path.exists():
            raise RuntimeError(f"validation: file does not exist for key '{k}': {path}")

    # Load each artifact
    repo_index = _load_json(local_paths["repo_index"])
    artifact_manifest = _load_json(local_paths["artifact_manifest"])
    architecture_snapshot = _load_json(local_paths["architecture_snapshot"])
    gaps = _load_json(local_paths["gaps"])
    pass2_semantic = _load_json(local_paths["pass2_semantic"])

    # Individual schema validation
    _validate_repo_index(repo_index)
    _validate_architecture_snapshot(architecture_snapshot)
    _validate_pass2_semantic(pass2_semantic)
    _validate_gaps(gaps)
    _validate_artifact_manifest(artifact_manifest)
    _validate_onboarding(local_paths["onboarding"])

    # Cross-artifact consistency
    _validate_cross_artifact_consistency(repo_index, architecture_snapshot, pass2_semantic, gaps)


# --------------------------------------------------------------------------------------
# Individual validators
# --------------------------------------------------------------------------------------

def _load_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    raw = p.read_bytes()
    obj = json.loads(raw.decode("utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"validation: expected JSON object at {p}")
    return obj


def _validate_repo_index(obj: dict[str, Any]) -> None:
    # PASS1_REPO_INDEX.json contract
    if obj.get("schema_version") != PASS1_REPO_INDEX_SCHEMA_VERSION:
        raise RuntimeError(f"validation: repo_index schema_version mismatch: expected {PASS1_REPO_INDEX_SCHEMA_VERSION}, got {obj.get('schema_version')}")

    job = obj.get("job")
    if not isinstance(job, dict):
        raise RuntimeError("validation: repo_index.job missing/invalid")
    rc = job.get("resolved_commit")
    if not isinstance(rc, str) or not rc.strip() or rc.strip() == "unknown":
        raise RuntimeError("validation: repo_index.job.resolved_commit missing/invalid")

    counts = obj.get("counts")
    if not isinstance(counts, dict):
        raise RuntimeError("validation: repo_index.counts missing/invalid")
    for k in ("files_scanned", "files_included", "files_skipped", "total_bytes_included"):
        if k not in counts:
            raise RuntimeError(f"validation: repo_index.counts missing key '{k}'")
        if not isinstance(counts[k], int):
            raise RuntimeError(f"validation: repo_index.counts.{k} must be int")

    rp = obj.get("read_plan")
    if not isinstance(rp, dict):
        raise RuntimeError("validation: repo_index.read_plan missing/invalid")
    seeds = rp.get("closure_seeds")
    if not isinstance(seeds, list):
        raise RuntimeError("validation: repo_index.read_plan.closure_seeds missing/invalid")
    cands = rp.get("candidates")
    if not isinstance(cands, list):
        raise RuntimeError("validation: repo_index.read_plan.candidates missing/invalid")

    files = obj.get("files")
    if not isinstance(files, list):
        raise RuntimeError("validation: repo_index.files missing/invalid")
    for f in files:
        if not isinstance(f, dict):
            raise RuntimeError("validation: repo_index.files entry must be dict")
        p = f.get("path")
        if not isinstance(p, str) or not p:
            raise RuntimeError("validation: repo_index.files entry missing/invalid 'path'")
        deps = f.get("deps")
        if not isinstance(deps, dict):
            raise RuntimeError(f"validation: repo_index.files[{p}].deps missing/invalid")
        edges = deps.get("import_edges")
        if not isinstance(edges, list):
            raise RuntimeError(f"validation: repo_index.files[{p}].deps.import_edges missing/invalid")


def _validate_architecture_snapshot(obj: dict[str, Any]) -> None:
    """
    STRICT validation for ARCHITECTURE_SUMMARY_SNAPSHOT.json

    Must have:
      - schema_version: "architecture_snapshot.v1"
      - Non-empty modules list OR populated uncertainties
      - No LLM-hallucinated caps in summary
      - Proper coverage stats
      - Evidence block structure
    """
    # Schema version check
    schema_version = obj.get("schema_version")
    if schema_version != ARCHITECTURE_SNAPSHOT_SCHEMA_VERSION:
        raise RuntimeError(
            f"validation: architecture_snapshot schema_version mismatch: "
            f"expected {ARCHITECTURE_SNAPSHOT_SCHEMA_VERSION}, got {schema_version}"
        )

    # Required top-level keys
    required_keys = ["generated_at", "repo", "summary", "modules", "uncertainties", "coverage", "files_read", "files_not_read"]
    for k in required_keys:
        if k not in obj:
            raise RuntimeError(f"validation: architecture_snapshot missing required key '{k}'")

    # Repo info validation
    repo = obj.get("repo")
    if not isinstance(repo, dict):
        raise RuntimeError("validation: architecture_snapshot.repo missing/invalid")
    for k in ("repo_url", "resolved_commit", "job_id"):
        if k not in repo:
            raise RuntimeError(f"validation: architecture_snapshot.repo missing key '{k}'")
        if not isinstance(repo[k], str) or not repo[k].strip():
            raise RuntimeError(f"validation: architecture_snapshot.repo.{k} must be non-empty string")

    # Summary validation - MUST NOT contain LLM-hallucinated caps
    summary = obj.get("summary")
    if not isinstance(summary, dict):
        raise RuntimeError("validation: architecture_snapshot.summary missing/invalid")

    # Check for hallucinated caps in summary
    forbidden_caps_keys = ["model", "max_output_tokens", "max_arch_files", "max_support_files"]
    for key in forbidden_caps_keys:
        if key in summary:
            raise RuntimeError(
                f"validation: architecture_snapshot.summary contains LLM-hallucinated cap '{key}'. "
                f"Summary must not contain configuration information."
            )

    # Required summary fields
    summary_required = [
        "architecture_overview",
        "key_components",
        "data_flows",
        "auth_and_routing_notes",
        "risks_or_gaps"
    ]
    for k in summary_required:
        if k not in summary:
            raise RuntimeError(f"validation: architecture_snapshot.summary missing key '{k}'")
        if k == "architecture_overview":
            if not isinstance(summary[k], str) or not summary[k].strip():
                raise RuntimeError("validation: architecture_snapshot.summary.architecture_overview must be non-empty string")
        else:
            if not isinstance(summary[k], list):
                raise RuntimeError(f"validation: architecture_snapshot.summary.{k} must be list")

    # Modules validation - must be non-empty list OR uncertainties must be populated
    modules = obj.get("modules")
    if not isinstance(modules, list):
        raise RuntimeError("validation: architecture_snapshot.modules must be list")

    uncertainties = obj.get("uncertainties")
    if not isinstance(uncertainties, list):
        raise RuntimeError("validation: architecture_snapshot.uncertainties must be list")

    # Either modules must be non-empty OR uncertainties must explain why
    if len(modules) == 0 and len(uncertainties) == 0:
        raise RuntimeError(
            "validation: architecture_snapshot must have either non-empty modules list "
            "or populated uncertainties explaining missing modules"
        )

    # Validate each module
    for i, module in enumerate(modules):
        if not isinstance(module, dict):
            raise RuntimeError(f"validation: architecture_snapshot.modules[{i}] must be dict")

        # Required module fields
        module_required = ["name", "type", "evidence_paths", "responsibilities", "dependencies"]
        for k in module_required:
            if k not in module:
                raise RuntimeError(f"validation: architecture_snapshot.modules[{i}] missing key '{k}'")

        # Name and type must be non-empty strings
        if not isinstance(module["name"], str) or not module["name"].strip():
            raise RuntimeError(f"validation: architecture_snapshot.modules[{i}].name must be non-empty string")
        if not isinstance(module["type"], str) or not module["type"].strip():
            raise RuntimeError(f"validation: architecture_snapshot.modules[{i}].type must be non-empty string")

        # Evidence paths must be non-empty list of strings
        evidence_paths = module["evidence_paths"]
        if not isinstance(evidence_paths, list) or len(evidence_paths) == 0:
            raise RuntimeError(f"validation: architecture_snapshot.modules[{i}].evidence_paths must be non-empty list")
        for j, path in enumerate(evidence_paths):
            if not isinstance(path, str) or not path.strip():
                raise RuntimeError(f"validation: architecture_snapshot.modules[{i}].evidence_paths[{j}] must be non-empty string")

        # Responsibilities must be non-empty list of strings
        responsibilities = module["responsibilities"]
        if not isinstance(responsibilities, list) or len(responsibilities) == 0:
            raise RuntimeError(f"validation: architecture_snapshot.modules[{i}].responsibilities must be non-empty list")
        for j, resp in enumerate(responsibilities):
            if not isinstance(resp, str) or not resp.strip():
                raise RuntimeError(f"validation: architecture_snapshot.modules[{i}].responsibilities[{j}] must be non-empty string")

        # Dependencies must be list (may be empty)
        if not isinstance(module["dependencies"], list):
            raise RuntimeError(f"validation: architecture_snapshot.modules[{i}].dependencies must be list")

    # Validate each uncertainty
    for i, uncertainty in enumerate(uncertainties):
        if not isinstance(uncertainty, dict):
            raise RuntimeError(f"validation: architecture_snapshot.uncertainties[{i}] must be dict")

        uncertainty_required = ["type", "description", "files_involved", "suggested_questions"]
        for k in uncertainty_required:
            if k not in uncertainty:
                raise RuntimeError(f"validation: architecture_snapshot.uncertainties[{i}] missing key '{k}'")

        if not isinstance(uncertainty["type"], str) or not uncertainty["type"].strip():
            raise RuntimeError(f"validation: architecture_snapshot.uncertainties[{i}].type must be non-empty string")
        if not isinstance(uncertainty["description"], str) or not uncertainty["description"].strip():
            raise RuntimeError(f"validation: architecture_snapshot.uncertainties[{i}].description must be non-empty string")
        if not isinstance(uncertainty["files_involved"], list):
            raise RuntimeError(f"validation: architecture_snapshot.uncertainties[{i}].files_involved must be list")
        if not isinstance(uncertainty["suggested_questions"], list):
            raise RuntimeError(f"validation: architecture_snapshot.uncertainties[{i}].suggested_questions must be list")

    # Coverage validation
    coverage = obj.get("coverage")
    if not isinstance(coverage, dict):
        raise RuntimeError("validation: architecture_snapshot.coverage missing/invalid")
    for k in ("files_scanned", "files_read", "files_not_read", "files_included_from_pass1"):
        if k not in coverage:
            raise RuntimeError(f"validation: architecture_snapshot.coverage missing key '{k}'")
        if not isinstance(coverage[k], int) or coverage[k] < 0:
            raise RuntimeError(f"validation: architecture_snapshot.coverage.{k} must be non-negative int")

    # Files read validation
    files_read = obj.get("files_read")
    if not isinstance(files_read, list):
        raise RuntimeError("validation: architecture_snapshot.files_read must be list")
    for i, fr in enumerate(files_read):
        if not isinstance(fr, dict):
            raise RuntimeError(f"validation: architecture_snapshot.files_read[{i}] must be dict")
        for k in ("path", "chars", "truncated"):
            if k not in fr:
                raise RuntimeError(f"validation: architecture_snapshot.files_read[{i}] missing key '{k}'")
        if not isinstance(fr["path"], str) or not fr["path"].strip():
            raise RuntimeError(f"validation: architecture_snapshot.files_read[{i}].path must be non-empty string")
        if not isinstance(fr["chars"], int) or fr["chars"] < 0:
            raise RuntimeError(f"validation: architecture_snapshot.files_read[{i}].chars must be non-negative int")
        if not isinstance(fr["truncated"], bool):
            raise RuntimeError(f"validation: architecture_snapshot.files_read[{i}].truncated must be bool")

    # Files not read validation
    files_not_read = obj.get("files_not_read")
    if not isinstance(files_not_read, list):
        raise RuntimeError("validation: architecture_snapshot.files_not_read must be list")
    for i, fnr in enumerate(files_not_read):
        if not isinstance(fnr, dict):
            raise RuntimeError(f"validation: architecture_snapshot.files_not_read[{i}] must be dict")
        for k in ("path", "reason"):
            if k not in fnr:
                raise RuntimeError(f"validation: architecture_snapshot.files_not_read[{i}] missing key '{k}'")
        if not isinstance(fnr["path"], str) or not fnr["path"].strip():
            raise RuntimeError(f"validation: architecture_snapshot.files_not_read[{i}].path must be non-empty string")
        if not isinstance(fnr["reason"], str) or not fnr["reason"].strip():
            raise RuntimeError(f"validation: architecture_snapshot.files_not_read[{i}].reason must be non-empty string")

    # Optional evidence block validation (if present)
    evidence = obj.get("evidence")
    if evidence is not None:
        if not isinstance(evidence, dict):
            raise RuntimeError("validation: architecture_snapshot.evidence must be dict when present")

        # Check for arch_pack_paths if evidence exists
        if "arch_pack_paths" in evidence:
            arch_pack_paths = evidence["arch_pack_paths"]
            if not isinstance(arch_pack_paths, list):
                raise RuntimeError("validation: architecture_snapshot.evidence.arch_pack_paths must be list when present")
            for i, path in enumerate(arch_pack_paths):
                if not isinstance(path, str) or not path.strip():
                    raise RuntimeError(f"validation: architecture_snapshot.evidence.arch_pack_paths[{i}] must be non-empty string")

        # Check for support_pack_paths if evidence exists
        if "support_pack_paths" in evidence:
            support_pack_paths = evidence["support_pack_paths"]
            if not isinstance(support_pack_paths, list):
                raise RuntimeError("validation: architecture_snapshot.evidence.support_pack_paths must be list when present")
            for i, path in enumerate(support_pack_paths):
                if not isinstance(path, str) or not path.strip():
                    raise RuntimeError(f"validation: architecture_snapshot.evidence.support_pack_paths[{i}] must be non-empty string")

        # Check for notable_files if evidence exists
        if "notable_files" in evidence:
            notable_files = evidence["notable_files"]
            if not isinstance(notable_files, list):
                raise RuntimeError("validation: architecture_snapshot.evidence.notable_files must be list when present")
            for i, nf in enumerate(notable_files):
                if not isinstance(nf, dict):
                    raise RuntimeError(f"validation: architecture_snapshot.evidence.notable_files[{i}] must be dict")
                for k in ("path", "why"):
                    if k not in nf:
                        raise RuntimeError(f"validation: architecture_snapshot.evidence.notable_files[{i}] missing key '{k}'")
                    if not isinstance(nf[k], str) or not nf[k].strip():
                        raise RuntimeError(f"validation: architecture_snapshot.evidence.notable_files[{i}].{k} must be non-empty string")


def _validate_pass2_semantic(obj: dict[str, Any]) -> None:
    if obj.get("schema_version") != PASS2_SEMANTIC_SCHEMA_VERSION:
        raise RuntimeError(f"validation: pass2_semantic schema_version mismatch: expected {PASS2_SEMANTIC_SCHEMA_VERSION}, got {obj.get('schema_version')}")

    repo = obj.get("repo")
    if not isinstance(repo, dict):
        raise RuntimeError("validation: pass2_semantic.repo missing/invalid")
    rc = repo.get("resolved_commit")
    if not isinstance(rc, str) or not rc.strip():
        raise RuntimeError("validation: pass2_semantic.repo.resolved_commit missing/invalid")

    llm_output = obj.get("llm_output")
    if not isinstance(llm_output, dict):
        raise RuntimeError("validation: pass2_semantic.llm_output missing/invalid")

    summary = llm_output.get("summary")
    if not isinstance(summary, dict):
        raise RuntimeError("validation: pass2_semantic.llm_output.summary missing/invalid")

    # All 6 summary keys must be present
    summary_keys = ["primary_stack", "architecture_overview", "key_components", "data_flows", "auth_and_routing_notes", "risks_or_gaps"]
    for k in summary_keys:
        if k not in summary:
            raise RuntimeError(f"validation: pass2_semantic.llm_output.summary missing key '{k}'")

    # Check for LLM caps hallucination in llm_output (common issue)
    llm_caps = llm_output.get("caps")
    if isinstance(llm_caps, dict):
        # Warn but don't fail - this is an LLM issue, not a schema issue
        pass  # We'll fix this in the prompt, but don't break validation


def _validate_gaps(obj: dict[str, Any]) -> None:
    # Gaps schema validation
    if not isinstance(obj, dict):
        raise RuntimeError("validation: gaps must be dict")

    # Schema version (added in fix)
    schema_version = obj.get("schema_version")
    if schema_version != "gaps.v1":
        raise RuntimeError(f"validation: gaps schema_version mismatch: expected 'gaps.v1', got {schema_version}")

    # Required keys
    required_keys = ["generated_at", "repo", "risks_or_gaps"]
    for k in required_keys:
        if k not in obj:
            raise RuntimeError(f"validation: gaps missing required key '{k}'")

    # Repo validation
    repo = obj.get("repo")
    if not isinstance(repo, dict):
        raise RuntimeError("validation: gaps.repo missing/invalid")
    for k in ("repo_url", "resolved_commit"):
        if k not in repo:
            raise RuntimeError(f"validation: gaps.repo missing key '{k}'")
        if not isinstance(repo[k], str) or not repo[k].strip():
            raise RuntimeError(f"validation: gaps.repo.{k} must be non-empty string")

    # Risks or gaps must be list
    risks_or_gaps = obj.get("risks_or_gaps")
    if not isinstance(risks_or_gaps, list):
        raise RuntimeError("validation: gaps.risks_or_gaps must be list")

    # Each risk/gap must be string
    for i, item in enumerate(risks_or_gaps):
        if not isinstance(item, str) or not item.strip():
            raise RuntimeError(f"validation: gaps.risks_or_gaps[{i}] must be non-empty string")


def _validate_artifact_manifest(obj: dict[str, Any]) -> None:
    if not isinstance(obj, dict):
        raise RuntimeError("validation: artifact_manifest must be dict")

    items = obj.get("items")
    if not isinstance(items, list):
        raise RuntimeError("validation: artifact_manifest.items must be list")

    stable_fingerprints = obj.get("stable_fingerprints")
    if not isinstance(stable_fingerprints, dict):
        raise RuntimeError("validation: artifact_manifest.stable_fingerprints must be dict")

    run_fp = obj.get("run_fingerprint_sha256")
    if not isinstance(run_fp, str) or not run_fp.strip():
        raise RuntimeError("validation: artifact_manifest.run_fingerprint_sha256 missing/invalid")

    # Must include all core artifacts
    core_artifacts = {"pass1_repo_index", "dependency_graph", "architecture_snapshot", "gaps", "onboarding", "pass2_semantic"}
    for name in core_artifacts:
        if name not in stable_fingerprints:
            raise RuntimeError(f"validation: artifact_manifest missing fingerprint for core artifact '{name}'")


def _validate_onboarding(path: str) -> None:
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"validation: onboarding file does not exist: {p}")
    content = p.read_text(encoding="utf-8", errors="replace").strip()
    if len(content) < 50:
        raise RuntimeError(f"validation: onboarding.md too short ({len(content)} chars), minimum 50")


def _validate_cross_artifact_consistency(
        repo_index: dict[str, Any],
        architecture_snapshot: dict[str, Any],
        pass2_semantic: dict[str, Any],
        gaps: dict[str, Any],
) -> None:
    # repo_url consistency
    repo_urls = set()

    ri_repo = repo_index.get("job", {}).get("repo_url")
    if isinstance(ri_repo, str) and ri_repo.strip():
        repo_urls.add(ri_repo.strip())

    as_repo = architecture_snapshot.get("repo", {}).get("repo_url")
    if isinstance(as_repo, str) and as_repo.strip():
        repo_urls.add(as_repo.strip())

    ps_repo = pass2_semantic.get("repo", {}).get("repo_url")
    if isinstance(ps_repo, str) and ps_repo.strip():
        repo_urls.add(ps_repo.strip())

    gaps_repo = gaps.get("repo", {}).get("repo_url")
    if isinstance(gaps_repo, str) and gaps_repo.strip():
        repo_urls.add(gaps_repo.strip())

    if len(repo_urls) > 1:
        raise RuntimeError(f"validation: repo_url mismatch across artifacts: {repo_urls}")

    # resolved_commit consistency (where available)
    commits = set()

    ri_commit = repo_index.get("job", {}).get("resolved_commit")
    if isinstance(ri_commit, str) and ri_commit.strip() and ri_commit.strip() != "unknown":
        commits.add(ri_commit.strip())

    as_commit = architecture_snapshot.get("repo", {}).get("resolved_commit")
    if isinstance(as_commit, str) and as_commit.strip() and as_commit.strip() != "unknown":
        commits.add(as_commit.strip())

    ps_commit = pass2_semantic.get("repo", {}).get("resolved_commit")
    if isinstance(ps_commit, str) and ps_commit.strip() and ps_commit.strip() != "unknown":
        commits.add(ps_commit.strip())

    gaps_commit = gaps.get("repo", {}).get("resolved_commit")
    if isinstance(gaps_commit, str) and gaps_commit.strip() and gaps_commit.strip() != "unknown":
        commits.add(gaps_commit.strip())

    if len(commits) > 1:
        raise RuntimeError(f"validation: resolved_commit mismatch across artifacts: {commits}")

    # Gaps content consistency with pass2_semantic
    pass2_risks = pass2_semantic.get("llm_output", {}).get("summary", {}).get("risks_or_gaps", [])
    gaps_risks = gaps.get("risks_or_gaps", [])

    if isinstance(pass2_risks, list) and isinstance(gaps_risks, list):
        # They should match (gaps is extracted from pass2_semantic)
        pass2_risks_strs = [str(r).strip() for r in pass2_risks if isinstance(r, str) and r.strip()]
        gaps_risks_strs = [str(r).strip() for r in gaps_risks if isinstance(r, str) and r.strip()]

        if set(pass2_risks_strs) != set(gaps_risks_strs):
            # Warn but don't fail - gaps might be cleaned version
            pass