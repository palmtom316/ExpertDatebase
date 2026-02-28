"""Storage adapters for worker side (local/MinIO)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from minio import Minio


class BinaryStorage(Protocol):
    def get_bytes(self, object_key: str) -> bytes:
        raise NotImplementedError


class LocalBinaryStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def get_bytes(self, object_key: str) -> bytes:
        return (self.root / object_key).read_bytes()


class MinioBinaryStorage:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str) -> None:
        parsed = urlparse(endpoint)
        secure = parsed.scheme == "https"
        host = parsed.netloc or parsed.path
        self.bucket = bucket
        self.client = Minio(host, access_key=access_key, secret_key=secret_key, secure=secure)

    def get_bytes(self, object_key: str) -> bytes:
        resp = self.client.get_object(self.bucket, object_key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()


def build_storage_from_env() -> BinaryStorage:
    backend = os.getenv("OBJECT_STORAGE_BACKEND", "auto").lower()
    if backend == "local":
        return LocalBinaryStorage(Path(os.getenv("LOCAL_STORAGE_ROOT", ".runtime/objects")))

    endpoint = os.getenv("MINIO_ENDPOINT")
    access_key = os.getenv("MINIO_ACCESS_KEY")
    secret_key = os.getenv("MINIO_SECRET_KEY")
    bucket = os.getenv("MINIO_BUCKET", "expertkb")
    if endpoint and access_key and secret_key:
        return MinioBinaryStorage(endpoint=endpoint, access_key=access_key, secret_key=secret_key, bucket=bucket)

    return LocalBinaryStorage(Path(os.getenv("LOCAL_STORAGE_ROOT", ".runtime/objects")))
