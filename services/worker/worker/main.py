"""Worker entrypoint: queue consumption loop."""

from __future__ import annotations

import json
import os
import time

from worker.doc_registry import build_doc_status_registry_from_env
from worker.embedding_client import EmbeddingClient
from worker.mineru_client import MinerUClient
from worker.qdrant_repo import create_qdrant_repo_from_env
from worker.queue import build_job_queue_from_env
from worker.runner import WorkerRuntime, process_document_job
from worker.storage import build_storage_from_env


def run_forever(max_idle_cycles: int | None = None) -> None:
    queue = build_job_queue_from_env()
    runtime = WorkerRuntime(
        storage=build_storage_from_env(),
        qdrant_repo=create_qdrant_repo_from_env(),
        doc_registry=build_doc_status_registry_from_env(),
        mineru_client=MinerUClient(),
        embedding_client=EmbeddingClient(),
    )

    idle = 0
    poll_timeout = int(os.getenv("WORKER_POLL_TIMEOUT", "5"))
    print("worker started")

    while True:
        job = queue.pop_document_job(timeout_s=poll_timeout)
        if not job:
            idle += 1
            if max_idle_cycles is not None and idle >= max_idle_cycles:
                print("worker idle max reached, exiting")
                return
            continue

        idle = 0
        try:
            summary = process_document_job(job, runtime)
            print("worker processed", json.dumps({"job": job, "summary": summary}, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            version_id = str(job.get("version_id", ""))
            if version_id:
                runtime.doc_registry.mark_version_status(version_id=version_id, status="failed", notes={"error": str(exc)})
            print("worker failed", str(exc))
            time.sleep(1)


def main() -> None:
    run_forever()


if __name__ == "__main__":
    main()
