"""Worker job runner: consume queue message and process document."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid5, NAMESPACE_DNS

from worker.build_payload import build_payload
from worker.embedding_client import EmbeddingClient
from worker.ie_extract import extract_assets_from_chapter
from worker.mineru_client import MinerUClient
from worker.pipeline import process_mineru_result
from worker.vl_enhancer import VLRecognizer, extract_visual_candidates, merge_visual_text_into_mineru


class _EntityIndex:
    def get_or_create_id(self, kind: str, name: str) -> str:
        key = f"{kind}:{name}".strip().lower()
        return f"{kind}_{str(uuid5(NAMESPACE_DNS, key)).replace('-', '')[:16]}"


@dataclass
class WorkerRuntime:
    storage: Any
    qdrant_repo: Any
    doc_registry: Any
    mineru_client: MinerUClient
    embedding_client: EmbeddingClient
    asset_repo: Any | None = None
    entity_index: Any | None = None


def _put_artifact_bytes(storage: Any, key: str, payload: bytes, content_type: str) -> bool:
    put_fn = getattr(storage, "put_bytes", None)
    if not callable(put_fn):
        return False
    try:
        put_fn(key, payload, content_type=content_type)
        return True
    except TypeError:
        # Some test doubles expose a 2-arg put_bytes interface.
        try:
            put_fn(key, payload)
            return True
        except Exception:  # noqa: BLE001
            return False
    except Exception:  # noqa: BLE001
        return False


def _mineru_pages_to_markdown(mineru_result: dict[str, Any]) -> str:
    pages = mineru_result.get("pages") if isinstance(mineru_result, dict) else []
    if not isinstance(pages, list):
        return ""
    out: list[str] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_no = int(page.get("page_no") or 0)
        out.append(f"## 第 {page_no} 页")
        blocks = page.get("blocks")
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                text = str(block.get("text") or "").strip()
                if not text:
                    continue
                block_type = str(block.get("type") or "").strip().lower()
                if block_type == "title":
                    out.append(f"### {text}")
                else:
                    out.append(text)
        tables = page.get("tables")
        if isinstance(tables, list):
            for table in tables:
                if not isinstance(table, dict):
                    continue
                raw_text = str(table.get("raw_text") or "").strip()
                if raw_text:
                    out.append(f"> 表格: {raw_text}")
    return "\n\n".join(out).strip()


def process_document_job(job: dict[str, Any], rt: WorkerRuntime) -> dict[str, Any]:
    doc_id = str(job["doc_id"])
    version_id = str(job["version_id"])
    object_key = str(job["object_key"])

    rt.doc_registry.mark_version_status(version_id=version_id, status="processing", notes={"job": job})

    pdf_bytes = rt.storage.get_bytes(object_key)
    runtime_config = job.get("runtime_config") if isinstance(job.get("runtime_config"), dict) else {}
    try:
        mineru_result = rt.mineru_client.parse_pdf(pdf_bytes, runtime_config=runtime_config)
    except TypeError:
        mineru_result = rt.mineru_client.parse_pdf(pdf_bytes)

    visual_candidates = extract_visual_candidates(mineru_result)
    vl_result = VLRecognizer().enhance(visual_candidates, runtime_config=runtime_config)
    mineru_result = merge_visual_text_into_mineru(mineru_result, vl_result.get("items") or [])
    mineru_json_key = f"mineru/{doc_id}/{version_id}/mineru.pages.json"
    mineru_md_key = f"mineru/{doc_id}/{version_id}/mineru.pages.md"
    artifact_keys: dict[str, str] = {}
    mineru_json_bytes = json.dumps(mineru_result, ensure_ascii=False, indent=2).encode("utf-8")
    if _put_artifact_bytes(rt.storage, mineru_json_key, mineru_json_bytes, content_type="application/json"):
        artifact_keys["mineru_json_key"] = mineru_json_key
    mineru_md_text = _mineru_pages_to_markdown(mineru_result)
    if mineru_md_text and _put_artifact_bytes(
        rt.storage,
        mineru_md_key,
        mineru_md_text.encode("utf-8"),
        content_type="text/markdown; charset=utf-8",
    ):
        artifact_keys["mineru_md_key"] = mineru_md_key

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

    entity_index = rt.entity_index or _EntityIndex()
    upserted = 0
    doc_type = str(job.get("doc_type") or (result.get("classification") or {}).get("doc_type") or "规范规程")
    for chunk in result["chunks"]:
        chunk_for_payload = {
            **chunk,
            "doc_name": object_key.split("/")[-1],
            "doc_type": doc_type,
            "text": chunk.get("text", ""),
        }
        page_type = "other"
        table_struct = result.get("table_struct") or {}
        if table_struct.get("power_param_table"):
            page_type = "power_param_table"
        elif table_struct.get("device_inventory_table"):
            page_type = "device_inventory_table"
        elif table_struct.get("qualification_table"):
            page_type = "qualification_table"
        payload = build_payload(
            chunk=chunk_for_payload,
            ie_assets=ie_assets,
            relations_light=[],
            entity_index=entity_index,
            page_type=page_type,
        )
        try:
            vector = rt.embedding_client.embed_text(chunk_for_payload["text"], runtime_config=runtime_config)
        except TypeError:
            vector = rt.embedding_client.embed_text(chunk_for_payload["text"])
        point_id = f"{doc_id}:{version_id}:{chunk_for_payload['chunk_id']}"
        rt.qdrant_repo.upsert(point_id=point_id, vector=vector, payload=payload)
        upserted += 1

    summary = {
        "chunks": len(result["chunks"]),
        "upserted": upserted,
        "assets_extracted": len(ie_assets),
        "assets_written": assets_written,
        "quality_gate": result.get("quality_gate"),
        "classification": result.get("classification"),
        "table_struct_counts": {
            "power_param_table": len((result.get("table_struct") or {}).get("power_param_table", [])),
            "device_inventory_table": len((result.get("table_struct") or {}).get("device_inventory_table", [])),
            "qualification_table": len((result.get("table_struct") or {}).get("qualification_table", [])),
        },
        "intermediate_counts": {
            "blocks": len(result.get("normalized_blocks", [])),
            "tables": len(result.get("normalized_tables", [])),
            "chapters": len(result.get("chapters", [])),
            "chunks": len(result.get("chunks", [])),
        },
        "chunk_filter_stats": result.get("chunk_filter_stats") or {},
        "visual_enhancement": {
            "candidate_count": len(visual_candidates),
            "enhanced_count": len(vl_result.get("items") or []),
            "provider": vl_result.get("provider"),
            "model": vl_result.get("model"),
            "enabled": bool(vl_result.get("enabled")),
        },
        "artifacts": artifact_keys,
    }
    rt.doc_registry.mark_version_status(version_id=version_id, status="processed", notes=summary)
    return summary
