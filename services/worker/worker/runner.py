"""Worker job runner: consume queue message and process document."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from worker.build_payload import build_payload
from worker.embedding_client import EmbeddingClient
from worker.ie_extract import extract_assets_from_chapter
from worker.mineru_client import MinerUClient
from worker.pipeline import process_mineru_result


class _EntityIndex:
    def get_or_create_id(self, kind: str, name: str) -> str:
        return f"{kind[:2]}:{abs(hash(name)) % 100000}"


@dataclass
class WorkerRuntime:
    storage: Any
    qdrant_repo: Any
    doc_registry: Any
    mineru_client: MinerUClient
    embedding_client: EmbeddingClient
    asset_repo: Any | None = None


def process_document_job(job: dict[str, Any], rt: WorkerRuntime) -> dict[str, Any]:
    doc_id = str(job["doc_id"])
    version_id = str(job["version_id"])
    object_key = str(job["object_key"])

    rt.doc_registry.mark_version_status(version_id=version_id, status="processing", notes={"job": job})

    pdf_bytes = rt.storage.get_bytes(object_key)
    mineru_result = rt.mineru_client.parse_pdf(pdf_bytes)
    result = process_mineru_result(doc_id=doc_id, version_id=version_id, mineru_result=mineru_result)

    ie_assets: list[dict[str, Any]] = []
    for chapter in result["chapters"]:
        ie_assets.extend(
            extract_assets_from_chapter(
                text=str(chapter.get("text", "")),
                page_no=int(chapter.get("start_page", 0) or 0),
            )
        )

    assets_written = 0
    if rt.asset_repo is not None and ie_assets:
        write_result = rt.asset_repo.write_assets(doc_id=doc_id, version_id=version_id, assets=ie_assets)
        if isinstance(write_result, int):
            assets_written = write_result
        else:
            assets_written = len(ie_assets)

    entity_index = _EntityIndex()
    upserted = 0
    for chunk in result["chunks"]:
        chunk_for_payload = {
            **chunk,
            "doc_name": object_key.split("/")[-1],
            "doc_type": "project_proof",
            "text": chunk.get("text", ""),
        }
        payload = build_payload(
            chunk=chunk_for_payload,
            ie_assets=ie_assets,
            relations_light=[],
            entity_index=entity_index,
            page_type="other",
        )
        vector = rt.embedding_client.embed_text(chunk_for_payload["text"])
        rt.qdrant_repo.upsert(point_id=chunk_for_payload["chunk_id"], vector=vector, payload=payload)
        upserted += 1

    summary = {
        "chunks": len(result["chunks"]),
        "upserted": upserted,
        "assets_extracted": len(ie_assets),
        "assets_written": assets_written,
    }
    rt.doc_registry.mark_version_status(version_id=version_id, status="processed", notes=summary)
    return summary
