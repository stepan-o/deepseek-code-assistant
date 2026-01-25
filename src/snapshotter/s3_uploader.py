# snapshotter/s3_uploader.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import boto3


@dataclass
class S3Uploader:
    bucket: str
    prefix: str
    region: str | None = None

    def __post_init__(self):
        # region may be None; boto3 will use env/config
        self.s3 = boto3.client("s3", region_name=self.region)

    def _key(self, rel_key: str) -> str:
        rel_key = rel_key.lstrip("/")
        return f"{self.prefix.rstrip('/')}/{rel_key}"

    def put_bytes(self, rel_key: str, data: bytes, content_type: str | None = None) -> str:
        key = self._key(rel_key)
        extra = {"ServerSideEncryption": "AES256"}  # REQUIRED by your bucket policy
        if content_type:
            extra["ContentType"] = content_type
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)
        return f"s3://{self.bucket}/{key}"

    def upload_file(self, rel_key: str, path: str | Path, content_type: str | None = None) -> str:
        key = self._key(rel_key)
        extra = {"ServerSideEncryption": "AES256"}  # REQUIRED
        if content_type:
            extra["ContentType"] = content_type
        self.s3.upload_file(str(path), self.bucket, key, ExtraArgs=extra)
        return f"s3://{self.bucket}/{key}"
