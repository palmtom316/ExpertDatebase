"""Storage adapters with local and MinIO backends."""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error


class ObjectStorage(Protocol):
    def put_bytes(self, object_key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        raise NotImplementedError

    def exists(self, object_key: str) -> bool:
        raise NotImplementedError


class LocalObjectStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, object_key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        target = self.root / object_key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def exists(self, object_key: str) -> bool:
        return (self.root / object_key).exists()


class MinioObjectStorage:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
    ) -> None:
        parsed = urlparse(endpoint)
        secure = parsed.scheme == "https"
        host = parsed.netloc or parsed.path
        self.bucket = bucket
        self.client = Minio(host, access_key=access_key, secret_key=secret_key, secure=secure)
        self._bucket_checked = False

    def _ensure_bucket(self) -> None:
        if self._bucket_checked:
            return
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)
        self._bucket_checked = True

    def put_bytes(self, object_key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self._ensure_bucket()
        body = io.BytesIO(data)
        self.client.put_object(self.bucket, object_key, body, len(data), content_type=content_type)

    def exists(self, object_key: str) -> bool:
        self._ensure_bucket()
        try:
            self.client.stat_object(self.bucket, object_key)
            return True
        except S3Error:
            return False


def build_storage_from_env() -> ObjectStorage:
    backend = os.getenv("OBJECT_STORAGE_BACKEND", "auto").lower()
    if backend == "local":
        return LocalObjectStorage(Path(os.getenv("LOCAL_STORAGE_ROOT", ".runtime/objects")))

    endpoint = os.getenv("MINIO_ENDPOINT")
    access_key = os.getenv("MINIO_ACCESS_KEY")
    secret_key = os.getenv("MINIO_SECRET_KEY")
    bucket = os.getenv("MINIO_BUCKET", "expertkb")

    if endpoint and access_key and secret_key:
        return MinioObjectStorage(endpoint=endpoint, access_key=access_key, secret_key=secret_key, bucket=bucket)

    return LocalObjectStorage(Path(os.getenv("LOCAL_STORAGE_ROOT", ".runtime/objects")))
