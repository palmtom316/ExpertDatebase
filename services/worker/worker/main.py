"""Worker entrypoint: queue consumption loop."""

from __future__ import annotations

import json
import os
import time

from worker.asset_writer import build_asset_repo_from_env
from worker.doc_registry import build_doc_status_registry_from_env
from worker.embedding_client import EmbeddingClient
from worker.entity_index import build_entity_index_from_env
from worker.mineru_client import MinerUClient
from worker.qdrant_index import ensure_payload_indexes
from worker.qdrant_repo import create_qdrant_repo_from_env
from worker.queue import build_job_queue_from_env
from worker.runner import WorkerRuntime, process_document_job
from worker.storage import build_storage_from_env

try:
    from shared.logging_config import configure_logging, get_logger
    configure_logging()
    _log = get_logger("worker")
except ImportError:
    import logging
    _log = logging.getLogger("worker")  # type: ignore[assignment]


def _init_qdrant_indexes() -> None:
    endpoint = os.getenv("VECTORDB_ENDPOINT", "").strip()
    if not endpoint:
        return
    if not endpoint.startswith("http"):
        endpoint = f"http://{endpoint}"

    collection = os.getenv("QDRANT_COLLECTION", "chunks_v1")
    result = ensure_payload_indexes(endpoint=endpoint, collection=collection)
    _log.info("qdrant indexes ready", result=result)


def run_forever(max_idle_cycles: int | None = None) -> None:
    queue = build_job_queue_from_env()
    try:
        _init_qdrant_indexes()
    except Exception as exc:  # noqa: BLE001
        _log.warning("qdrant index init failed", error=str(exc))

    runtime = WorkerRuntime(
        storage=build_storage_from_env(),
        qdrant_repo=create_qdrant_repo_from_env(),
        doc_registry=build_doc_status_registry_from_env(),
        mineru_client=MinerUClient(),
        embedding_client=EmbeddingClient(),
        asset_repo=build_asset_repo_from_env(),
        entity_index=build_entity_index_from_env(),
    )

    idle = 0
    poll_timeout = int(os.getenv("WORKER_POLL_TIMEOUT", "5"))
    _log.info("worker started", poll_timeout=poll_timeout)

    while True:
        job = queue.pop_document_job(timeout_s=poll_timeout)
        if not job:
            idle += 1
            if max_idle_cycles is not None and idle >= max_idle_cycles:
                _log.info("worker idle max reached, exiting")
                return
            continue

        idle = 0
        version_id = str(job.get("version_id", ""))
        doc_id = str(job.get("doc_id", ""))
        try:
            summary = process_document_job(job, runtime)
            _log.info(
                "document processed",
                doc_id=doc_id,
                version_id=version_id,
                chunks=summary.get("chunks"),
                upserted=summary.get("upserted"),
                assets=summary.get("assets_extracted"),
            )
        except Exception as exc:  # noqa: BLE001
            if version_id:
                runtime.doc_registry.mark_version_status(version_id=version_id, status="failed", notes={"error": str(exc)})
            _log.error("document processing failed", doc_id=doc_id, version_id=version_id, error=str(exc))
            time.sleep(1)


def main() -> None:
    run_forever()


if __name__ == "__main__":
    main()
