"""Admin utilities to cleanup and retry failed document jobs."""

from __future__ import annotations

from typing import Any

from app.services.doc_registry import DocRegistry
from app.services.task_queue import TaskQueue


def _redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key or "").strip().lower()
            if any(token in key_text for token in ("api_key", "token", "secret", "password")):
                redacted[key] = "***"
                continue
            redacted[key] = _redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value


def list_failed_versions(registry: DocRegistry, limit: int | None = None) -> list[dict[str, Any]]:
    return registry.list_versions(statuses=["failed"], limit=limit)


def cleanup_failed_versions(registry: DocRegistry, limit: int | None = None) -> dict[str, Any]:
    failed = list_failed_versions(registry=registry, limit=limit)
    for item in failed:
        registry.update_version_status(
            version_id=item["id"],
            status="failed_archived",
            notes={
                "cleanup_from": "failed",
                "previous_notes": _redact_secrets(item.get("notes")),
            },
        )
    return {
        "cleaned_count": len(failed),
        "version_ids": [x["id"] for x in failed],
    }


def retry_failed_versions(
    registry: DocRegistry,
    task_queue: TaskQueue,
    limit: int | None = None,
) -> dict[str, Any]:
    failed = list_failed_versions(registry=registry, limit=limit)
    retried_ids: list[str] = []

    for item in failed:
        object_key = item.get("storage_key")
        doc_id = item.get("doc_id")
        version_id = item.get("id")
        if not object_key or not doc_id or not version_id:
            continue

        task_queue.enqueue_document_process(
            {
                "doc_id": doc_id,
                "version_id": version_id,
                "object_key": object_key,
                "doc_type": item.get("doc_type"),
            }
        )
        registry.update_version_status(
            version_id=version_id,
            status="retry_queued",
            notes={
                "retry_from": "failed",
                "previous_notes": _redact_secrets(item.get("notes")),
            },
        )
        retried_ids.append(version_id)

    return {
        "retried_count": len(retried_ids),
        "version_ids": retried_ids,
    }


def reprocess_version(
    registry: DocRegistry,
    task_queue: TaskQueue,
    version_id: str,
    runtime_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target_id = str(version_id or "").strip()
    if not target_id:
        return {"requeued": False, "reason": "missing_version_id"}

    versions = registry.list_versions(limit=None)
    item = next((v for v in versions if str(v.get("id") or "") == target_id), None)
    if item is None:
        return {"requeued": False, "reason": "not_found", "version_id": target_id}

    object_key = item.get("storage_key")
    doc_id = item.get("doc_id")
    if not object_key or not doc_id:
        return {"requeued": False, "reason": "missing_object_key_or_doc_id", "version_id": target_id}

    payload: dict[str, Any] = {
        "doc_id": doc_id,
        "version_id": target_id,
        "object_key": object_key,
        "doc_type": item.get("doc_type"),
    }
    if runtime_config:
        payload["runtime_config"] = runtime_config
    task_queue.enqueue_document_process(payload)

    prev_status = str(item.get("status") or "")
    registry.update_version_status(
        version_id=target_id,
        status="retry_queued",
        notes={
            "retry_from": prev_status or "unknown",
            "previous_notes": _redact_secrets(item.get("notes")),
            "trigger": "manual_reprocess",
        },
    )
    return {
        "requeued": True,
        "version_id": target_id,
        "doc_id": doc_id,
        "object_key": object_key,
        "previous_status": prev_status,
    }
