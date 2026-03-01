"""Structured lookup for certificate/standard/project style queries."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text


_CERT_PAT = re.compile(r"(?<![A-Z0-9])([A-Z]{1,6}(?:-[A-Z0-9]{1,10}){2,})(?![A-Z0-9])")
_STD_PAT = re.compile(
    r"(?<![A-Za-z0-9])((?:GB|DL/T|DL|NB/T|IEC|ISO)\s*[-A-Z]*\s*\d{2,6}(?:-\d{4})?)(?![A-Za-z0-9])",
    flags=re.IGNORECASE,
)
_PROJECT_NO_PAT = re.compile(r"(?:项目编号|项目号|编号)[:：\s]*([A-Za-z0-9/_-]{4,})")


def _extract_structured_tokens(question: str) -> list[str]:
    q = str(question or "")
    tokens: list[str] = []
    tokens.extend(m.group(1).strip().upper() for m in _CERT_PAT.finditer(q))
    tokens.extend(m.group(1).strip().upper() for m in _STD_PAT.finditer(q))
    for m in _PROJECT_NO_PAT.finditer(q):
        tokens.append(m.group(1).strip().upper())
    out: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


class StructuredLookupService:
    def __init__(
        self,
        assets_path: str | None = None,
        database_url: str | None = None,
    ) -> None:
        self.assets_path = Path(assets_path or os.getenv("ASSET_JSONL_PATH", ".runtime/assets.jsonl"))
        if database_url is None and self.assets_path.exists():
            self.database_url = ""
        else:
            self.database_url = str(database_url or os.getenv("DATABASE_URL") or "").strip()
        self._engine = create_engine(self.database_url, pool_pre_ping=True) if self.database_url else None

    def _jsonl_rows(self) -> list[dict[str, Any]]:
        if not self.assets_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.assets_path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows

    def _sql_rows(self, tokens: list[str], top_n: int) -> list[dict[str, Any]]:
        if not self._engine or not tokens:
            return []
        like_clauses = []
        params: dict[str, Any] = {"limit": max(1, int(top_n))}
        for idx, token in enumerate(tokens):
            key = f"tk{idx}"
            params[key] = f"%{token}%"
            like_clauses.append(f"UPPER(CAST(data_json AS TEXT)) LIKE :{key}")
        where = " OR ".join(like_clauses) or "1=0"
        sql = text(
            f"""
            SELECT
              doc_id,
              version_id,
              source_page,
              source_excerpt,
              data_json,
              asset_type
            FROM assets
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT :limit
            """
        )
        with self._engine.begin() as conn:
            rows = conn.execute(sql, params).mappings().all()
        return [dict(row) for row in rows]

    def _row_score(self, row: dict[str, Any], tokens: list[str]) -> float:
        corpus = " ".join(
            [
                str(row.get("asset_type") or ""),
                str(row.get("source_excerpt") or ""),
                json.dumps(row.get("data_json") or {}, ensure_ascii=False),
            ]
        ).upper()
        hit = sum(1 for token in tokens if token in corpus)
        return float(hit * 10)

    def _normalize_hit(self, row: dict[str, Any], score: float) -> dict[str, Any]:
        return {
            "doc_id": str(row.get("doc_id") or "").strip(),
            "page_no": int(row.get("source_page") or 0),
            "excerpt": str(row.get("source_excerpt") or "").strip(),
            "score": score,
            "source": "structured",
            "version_id": str(row.get("version_id") or "").strip(),
            "asset_type": str(row.get("asset_type") or "").strip(),
        }

    def lookup(self, question: str, top_n: int = 50) -> list[dict[str, Any]]:
        tokens = _extract_structured_tokens(question)
        if not tokens:
            return []
        rows = self._sql_rows(tokens=tokens, top_n=top_n) if self._engine else self._jsonl_rows()
        hits: list[dict[str, Any]] = []
        for row in rows:
            score = self._row_score(row, tokens=tokens)
            if score <= 0:
                continue
            hit = self._normalize_hit(row=row, score=score)
            if hit["doc_id"] and hit["page_no"] > 0:
                hits.append(hit)
        hits.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        return hits[: max(1, int(top_n))]
