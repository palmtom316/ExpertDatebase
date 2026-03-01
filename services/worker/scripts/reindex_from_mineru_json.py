#!/usr/bin/env python3
"""Reindex one document version directly from a MinerU structured JSON file."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from worker.build_payload import build_payload
from worker.embedding_client import EmbeddingClient
from worker.mineru_client import MinerUClient
from worker.pipeline import process_mineru_result
from worker.qdrant_repo import QdrantHttpRepo
from worker.runner import _EntityIndex


def _resolve_qdrant_endpoint(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        value = os.getenv("VECTORDB_ENDPOINT", "http://localhost:6333")
    if not value.startswith("http"):
        value = f"http://{value}"
    return value.rstrip("/")


def main() -> int:
    parser = argparse.ArgumentParser(description="Reindex one doc/version from MinerU JSON.")
    parser.add_argument("--mineru-json", required=True, help="Path to MinerU JSON file.")
    parser.add_argument("--doc-id", required=True, help="Document ID.")
    parser.add_argument("--version-id", required=True, help="Version ID.")
    parser.add_argument("--doc-name", required=True, help="Document display name.")
    parser.add_argument("--doc-type", default="规范规程", help="Document category.")
    parser.add_argument("--qdrant-endpoint", default="", help="Qdrant endpoint (default: VECTORDB_ENDPOINT).")
    parser.add_argument("--collection", default=os.getenv("QDRANT_COLLECTION", "chunks_v1"), help="Qdrant collection.")
    parser.add_argument("--vector-name", default=os.getenv("QDRANT_VECTOR_NAME", "text_embedding"), help="Vector name.")
    parser.add_argument("--reset-collection", action="store_true", help="Drop and recreate collection before upsert.")
    args = parser.parse_args()

    mineru_path = Path(args.mineru_json).expanduser().resolve()
    if not mineru_path.exists():
        raise FileNotFoundError(f"mineru json not found: {mineru_path}")

    raw = json.loads(mineru_path.read_text(encoding="utf-8"))
    client = MinerUClient()
    structured = client._to_pages_from_structured_json(raw)  # noqa: SLF001
    if not structured:
        raise RuntimeError("cannot parse MinerU JSON into pages")

    result = process_mineru_result(doc_id=args.doc_id, version_id=args.version_id, mineru_result=structured)
    endpoint = _resolve_qdrant_endpoint(args.qdrant_endpoint)
    repo = QdrantHttpRepo(endpoint=endpoint, collection=args.collection, vector_name=args.vector_name)
    embed = EmbeddingClient()
    entity_index = _EntityIndex()

    if args.reset_collection:
        requests.delete(f"{endpoint}/collections/{args.collection}", timeout=10)
        body = {"vectors": {args.vector_name: {"size": 1024, "distance": "Cosine"}}}
        resp = requests.put(f"{endpoint}/collections/{args.collection}", json=body, timeout=10)
        if resp.status_code not in (200, 201, 409):
            resp.raise_for_status()

    upserted = 0
    for chunk in result.get("chunks") or []:
        payload = build_payload(
            chunk={**chunk, "doc_name": args.doc_name, "doc_type": args.doc_type, "text": chunk.get("text", "")},
            ie_assets=[],
            relations_light=[],
            entity_index=entity_index,
            page_type="other",
        )
        vector = embed.embed_text(chunk.get("text", ""))
        point_id = f"{args.doc_id}:{args.version_id}:{chunk.get('chunk_id')}"
        repo.upsert(point_id=point_id, vector=vector, payload=payload)
        upserted += 1

    output = {
        "doc_id": args.doc_id,
        "version_id": args.version_id,
        "chunks": len(result.get("chunks") or []),
        "upserted": upserted,
        "chunk_filter_stats": result.get("chunk_filter_stats") or {},
        "intermediate_counts": {
            "blocks": len(result.get("normalized_blocks") or []),
            "tables": len(result.get("normalized_tables") or []),
            "chapters": len(result.get("chapters") or []),
        },
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

