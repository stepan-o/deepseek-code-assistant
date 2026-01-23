# src/snapshotter/job.py
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from snapshotter.utils import repo_slug_from_url, stable_json_fingerprint_sha256, utc_ts


class Limits(BaseModel):
    max_file_bytes: int = 10 * 1024 * 1024
    max_total_bytes: int = 250 * 1024 * 1024
    max_files: int = 20000


class Filters(BaseModel):
    deny_dirs: list[str] = ["node_modules", ".git", ".next", "dist", "build", ".venv"]
    deny_file_regex: list[str] = [
        # key material
        r"(?i).*\.pem$",
        r"(?i).*\.key$",
        r"(?i).*id_rsa$",
        # env secrets (".env", ".env.local", ".env.production", etc.)
        r"(?i)(^|/)\.env(\..*)?$",
        # common credential filenames (requested)
        r"(?i)(^|/)credentials\.json$",
        r"(?i)(^|/)service[_-]?account.*\.json$",
    ]
    allow_exts: list[str] = ["*"]

    # v0.1 safety: binary files are skipped unless explicitly allowed
    allow_binary: bool = False


class Output(BaseModel):
    s3_bucket: str
    s3_prefix: str


class Metadata(BaseModel):
    triggered_by: Literal["manual", "langgraph", "cron"] = "manual"
    notes: str | None = None


class Job(BaseModel):
    job_id: str | None = None
    repo_url: str
    ref: str
    mode: Literal["full", "light"] = "full"
    limits: Limits = Field(default_factory=Limits)
    filters: Filters = Field(default_factory=Filters)
    output: Output
    metadata: Metadata = Field(default_factory=Metadata)

    # derived at runtime
    repo_slug: str | None = None
    timestamp_utc: str | None = None

    def finalize(self) -> "Job":
        """
        Contract:
        - No randomness.
        - If job_id is not provided, derive a deterministic id from the job's canonical content.
        - timestamp_utc may vary per run, but identity (job_id) must not.
        """
        self.repo_slug = repo_slug_from_url(self.repo_url)
        self.timestamp_utc = utc_ts()

        if not self.job_id:
            # Deterministic: stable fingerprint of the canonical job content.
            # We fingerprint THIS model's data; timestamp_utc/repo_slug are not set yet when dumping here.
            # If callers pre-populate derived fields anyway, the default volatile set strips them.
            fp = stable_json_fingerprint_sha256(self.model_dump(mode="python"))
            self.job_id = fp[:12]

        # Guardrail: avoid accidental path duplication if someone set job_id equal to timestamp.
        if self.timestamp_utc and self.job_id == self.timestamp_utc:
            raise ValueError("job_id must not equal timestamp_utc (would duplicate path segments).")

        return self

    def s3_job_prefix(self) -> str:
        assert self.repo_slug and self.timestamp_utc and self.job_id
        return f"{self.output.s3_prefix}/{self.repo_slug}/{self.timestamp_utc}/{self.job_id}"
