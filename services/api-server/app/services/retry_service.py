"""Admin utilities to cleanup and retry failed document jobs."""

from __future__ import annotations

from typing import Any

from app.services.doc_registry import DocRegistry
from app.services.task_queue import TaskQueue


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
                "previous_notes": item.get("notes"),
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
            }
        )
        registry.update_version_status(
            version_id=version_id,
            status="retry_queued",
            notes={
                "retry_from": "failed",
                "previous_notes": item.get("notes"),
            },
        )
        retried_ids.append(version_id)

    return {
        "retried_count": len(retried_ids),
        "version_ids": retried_ids,
    }
