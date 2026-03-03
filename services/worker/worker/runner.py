"""Worker job runner: consume queue message and process document."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
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


def _export_sparse_sidecar_pages(mineru_result: dict[str, Any], doc_id: str) -> dict[str, Any]:
    root = Path(os.getenv("SPARSE_SIDECAR_DOCS_ROOT", "/data/docs"))
    target_dir = root / doc_id
    pages = mineru_result.get("pages") if isinstance(mineru_result, dict) else []
    if not isinstance(pages, list):
        return {"enabled": False, "reason": "invalid pages"}

    written = 0
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        for page in pages:
            if not isinstance(page, dict):
                continue
            page_no = int(page.get("page_no") or 0)
            if page_no <= 0:
                continue
            lines: list[str] = []
            blocks = page.get("blocks") or []
            tables = page.get("tables") or []
            if isinstance(blocks, list):
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    text = str(block.get("text") or "").strip()
                    if text:
                        lines.append(text)
            if isinstance(tables, list):
                for table in tables:
                    if not isinstance(table, dict):
                        continue
                    text = str(table.get("raw_text") or "").strip()
                    if text:
                        lines.append(text)
            if not lines:
                continue
            file_path = target_dir / f"page_{page_no:03d}.txt"
            file_path.write_text("\n".join(lines), encoding="utf-8")
            written += 1
    except Exception as exc:  # noqa: BLE001
        return {"enabled": False, "reason": str(exc), "root": str(target_dir)}

    return {"enabled": True, "root": str(target_dir), "pages_written": written}


def _env_enabled(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw not in {"0", "false", "no", "off", ""}


def _doc_type_allowed_for_table_vl(doc_type: str) -> bool:
    raw = str(os.getenv("WORKER_TABLE_VL_FALLBACK_DOC_TYPES", "规范规程")).strip()
    allow_types = {x.strip() for x in raw.split(",") if x.strip()}
    if not allow_types:
        return True
    return str(doc_type or "").strip() in allow_types


def _table_vl_timeout_s() -> float:
    raw = str(os.getenv("WORKER_TABLE_VL_TIMEOUT_S", "")).strip()
    if not raw:
        return float(os.getenv("VL_HTTP_TIMEOUT_S", "30"))
    try:
        return float(raw)
    except Exception:  # noqa: BLE001
        return float(os.getenv("VL_HTTP_TIMEOUT_S", "30"))


def _build_table_repair_context(
    mineru_result: dict[str, Any],
    doc_type: str,
    runtime_config: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    if not _env_enabled("WORKER_ENABLE_TABLE_VL_FALLBACK", default=False):
        return {}, {"attempted": 0, "applied": 0}
    if not _doc_type_allowed_for_table_vl(doc_type):
        return {}, {"attempted": 0, "applied": 0}

    pages = mineru_result.get("pages")
    if not isinstance(pages, list):
        return {}, {"attempted": 0, "applied": 0}

    candidates: list[dict[str, Any]] = []
    for page_index, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            continue
        page_no = int(page.get("page_no") or page_index)
        tables = page.get("tables")
        if not isinstance(tables, list):
            continue
        for idx, table in enumerate(tables, start=1):
            if not isinstance(table, dict):
                continue
            raw_text = str(table.get("raw_text") or "").strip()
            if not raw_text:
                continue
            table_id = f"t_{page_no}_{idx}"
            candidates.append(
                {
                    "visual_type": "table",
                    "page_no": page_no,
                    "source": "table",
                    "table_idx": idx,
                    "table_id": table_id,
                    "text_hint": raw_text[:1000],
                    "image_url": str(table.get("url") or table.get("image_url") or "").strip(),
                }
            )

    max_items = max(1, int(os.getenv("WORKER_TABLE_VL_MAX_ITEMS_PER_DOC", "20")))
    selected = candidates[:max_items]
    if not selected:
        return {}, {"attempted": 0, "applied": 0}

    vl_result = VLRecognizer().enhance(
        selected,
        runtime_config=runtime_config,
        task="table_repair",
        max_items=max_items,
        timeout_s=_table_vl_timeout_s(),
    )
    repairs: dict[str, dict[str, Any]] = {}
    for item in vl_result.get("items") or []:
        table_id = str(item.get("table_id") or "").strip()
        if not table_id:
            continue
        repairs[table_id] = item

    return repairs, {"attempted": len(selected), "applied": len(repairs)}


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

    doc_type_for_vl = str(job.get("doc_type") or "规范规程")
    table_vl_repairs, table_vl_stats = _build_table_repair_context(
        mineru_result=mineru_result,
        doc_type=doc_type_for_vl,
        runtime_config=runtime_config,
    )

    sparse_sidecar = _export_sparse_sidecar_pages(mineru_result=mineru_result, doc_id=doc_id)
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

    result = process_mineru_result(
        doc_id=doc_id,
        version_id=version_id,
        mineru_result=mineru_result,
        vl_table_repairs_by_table_id=table_vl_repairs,
    )

    ie_engine = str(runtime_config.get("ie_engine") or "").strip().lower()
    if not ie_engine:
        ie_engine = "langextract" if str(os.getenv("ENABLE_LANGEXTRACT", "0")).strip() in {"1", "true", "True"} else "custom"
    ie_assets: list[dict[str, Any]] = []
    for chapter in result["chapters"]:
        ie_assets.extend(
            extract_assets_from_chapter(
                text=str(chapter.get("text", "")),
                page_no=int(chapter.get("start_page", 0) or 0),
                engine=ie_engine,
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

    # Build per-page page_type map from table_struct results
    table_struct = result.get("table_struct") or {}
    _power_pages = {int(t.get("page_no") or 0) for t in table_struct.get("power_param_table", [])}
    _device_pages = {int(t.get("page_no") or 0) for t in table_struct.get("device_inventory_table", [])}
    _qual_pages = {int(t.get("page_no") or 0) for t in table_struct.get("qualification_table", [])}

    for chunk in result["chunks"]:
        chunk_for_payload = {
            **chunk,
            "doc_name": object_key.split("/")[-1],
            "doc_type": str(chunk.get("doc_type") or doc_type),
            "text": chunk.get("text", ""),
        }
        # Determine page_type per-chunk based on the chunk's start page
        page_start = int(chunk.get("page_start") or 0)
        if page_start in _power_pages:
            page_type = "power_param_table"
        elif page_start in _device_pages:
            page_type = "device_inventory_table"
        elif page_start in _qual_pages:
            page_type = "qualification_table"
        elif str(chunk.get("source_type") or "").strip() in {"table_row", "cross_page_table_row", "table_raw", "table_summary"}:
            page_type = "table"
        else:
            page_type = "other"
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
        "table_repair_counts": {
            "none": sum(
                1
                for tables in (result.get("table_struct") or {}).values()
                for t in (tables or [])
                if str((t or {}).get("repair_strategy") or "") == "none"
            ),
            "stub": sum(
                1
                for tables in (result.get("table_struct") or {}).values()
                for t in (tables or [])
                if str((t or {}).get("repair_strategy") or "") == "stub"
            ),
            "vl_fallback": sum(
                1
                for tables in (result.get("table_struct") or {}).values()
                for t in (tables or [])
                if str((t or {}).get("repair_strategy") or "") == "vl_fallback"
            ),
        },
        "table_vl_attempted": int(table_vl_stats.get("attempted") or 0),
        "table_vl_applied": sum(
            1
            for tables in (result.get("table_struct") or {}).values()
            for t in (tables or [])
            if str((t or {}).get("repair_strategy") or "") == "vl_fallback"
        ),
        "intermediate_counts": {
            "blocks": len(result.get("normalized_blocks", [])),
            "tables": len(result.get("normalized_tables", [])),
            "chapters": len(result.get("chapters", [])),
            "chunks": len(result.get("chunks", [])),
        },
        "chunk_filter_stats": result.get("chunk_filter_stats") or {},
        "ie_engine": ie_engine,
        "sparse_sidecar": sparse_sidecar,
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
