#!/usr/bin/env python3
"""Run offline retrieval evaluation against current index."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.services.retrieval_eval import evaluate_retrieval_samples
from app.services.search_service import create_search_repo_from_env, hybrid_search


class _EmptyEntityIndex:
    def match_names(self, kind: str, question: str) -> list[str]:
        return []

    def get_id(self, kind: str, name: str) -> str | None:
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            continue
        rows.append(obj)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality (Hit@5/10, MRR).")
    parser.add_argument("--dataset", required=True, help="Path to JSONL dataset.")
    parser.add_argument("--top-k", type=int, default=10, help="Max hits per query (default: 10).")
    parser.add_argument("--output", default="", help="Optional output JSON path.")
    parser.add_argument("--report", default="", help="Optional report JSON path (for gate checks).")
    args = parser.parse_args()

    dataset_path = Path(args.dataset).expanduser().resolve()
    if not dataset_path.exists():
        raise FileNotFoundError(f"dataset not found: {dataset_path}")
    samples = _read_jsonl(dataset_path)
    if not samples:
        raise RuntimeError("dataset is empty")

    repo = create_search_repo_from_env()
    entity_index = _EmptyEntityIndex()
    top_k = max(1, int(args.top_k))

    def _search(sample: dict[str, Any]) -> list[dict[str, Any]]:
        query = str(sample.get("query") or "").strip()
        if not query:
            return []
        must: list[dict[str, Any]] = []
        selected_doc_id = str(sample.get("selected_doc_id") or "").strip()
        selected_version_id = str(sample.get("selected_version_id") or "").strip()
        if selected_doc_id:
            must.append({"key": "doc_id", "match": {"value": selected_doc_id}})
        if selected_version_id:
            must.append({"key": "version_id", "match": {"value": selected_version_id}})
        search_filter = {"must": must} if must else None

        res = hybrid_search(
            question=query,
            repo=repo,
            entity_index=entity_index,
            top_k=top_k,
            search_filter=search_filter,
        )
        return res.get("hits") or []

    result = evaluate_retrieval_samples(samples=samples, search_fn=_search, top_k=top_k)
    result["dataset"] = str(dataset_path)
    result["allow_traffic"] = bool((result.get("release_gate") or {}).get("passed"))

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.output:
        out_path = Path(args.output).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.report:
        report_path = Path(args.report).expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
