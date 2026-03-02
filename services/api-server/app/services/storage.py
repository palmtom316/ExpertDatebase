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

    def get_bytes(self, object_key: str) -> bytes:
        raise NotImplementedError

    def get_size(self, object_key: str) -> int:
        raise NotImplementedError

    def get_range(self, object_key: str, start: int, end: int) -> bytes:
        raise NotImplementedError

    def exists(self, object_key: str) -> bool:
        raise NotImplementedError

    def delete_bytes(self, object_key: str) -> None:
        raise NotImplementedError


class LocalObjectStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, object_key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        target = self.root / object_key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def get_bytes(self, object_key: str) -> bytes:
        return (self.root / object_key).read_bytes()

    def get_size(self, object_key: str) -> int:
        return (self.root / object_key).stat().st_size

    def get_range(self, object_key: str, start: int, end: int) -> bytes:
        if start < 0 or end < start:
            raise ValueError("invalid byte range")
        size = end - start + 1
        target = self.root / object_key
        with target.open("rb") as handle:
            handle.seek(start)
            return handle.read(size)

    def exists(self, object_key: str) -> bool:
        return (self.root / object_key).exists()

    def delete_bytes(self, object_key: str) -> None:
        target = self.root / object_key
        try:
            target.unlink()
        except FileNotFoundError:
            return


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

    def get_bytes(self, object_key: str) -> bytes:
        self._ensure_bucket()
        response = self.client.get_object(self.bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def get_size(self, object_key: str) -> int:
        self._ensure_bucket()
        stat = self.client.stat_object(self.bucket, object_key)
        return int(stat.size)

    def get_range(self, object_key: str, start: int, end: int) -> bytes:
        if start < 0 or end < start:
            raise ValueError("invalid byte range")
        self._ensure_bucket()
        length = end - start + 1
        response = self.client.get_object(self.bucket, object_key, offset=start, length=length)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def exists(self, object_key: str) -> bool:
        self._ensure_bucket()
        try:
            self.client.stat_object(self.bucket, object_key)
            return True
        except S3Error:
            return False

    def delete_bytes(self, object_key: str) -> None:
        self._ensure_bucket()
        try:
            self.client.remove_object(self.bucket, object_key)
        except S3Error as exc:
            code = str(getattr(exc, "code", "") or "")
            if code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                return
            raise


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
