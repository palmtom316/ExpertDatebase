#!/usr/bin/env python3
"""Minimal sparse sidecar service for Sirchmunk-compatible API."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


DOCS_ROOT = Path(os.getenv("SPARSE_SIDECAR_DOCS_ROOT", "/data/docs"))
HOST = os.getenv("SIRCHMUNK_HOST", "0.0.0.0")
PORT = int(os.getenv("SIRCHMUNK_PORT", "8091"))
TOP_N_CAP = max(1, int(os.getenv("SIRCHMUNK_TOP_N_CAP", "400")))


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return default


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _normalize_text(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"(?<=[\u4e00-\u9fffA-Za-z0-9])\s+(?=[\u4e00-\u9fffA-Za-z0-9])", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _compact_for_match(text: str) -> str:
    compact = re.sub(r"\s+", "", str(text or "").lower())
    compact = re.sub(r"[，。！？；：、（）()【】\\[\\]<>《》“”‘’'\"`~·…—-]", "", compact)
    return compact


def _tokenize(query: str) -> list[str]:
    cleaned = _normalize_text(query).lower()
    if not cleaned:
        return []
    tokens = re.findall(r"[0-9a-zA-Z]+|[\u4e00-\u9fff]{1,8}", cleaned)
    out: list[str] = []
    for token in tokens:
        tok = token.strip()
        if not tok:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", tok) and len(tok) > 2:
            # Split long Chinese chunks to improve recall without external tokenizer.
            out.extend([tok[i : i + 2] for i in range(0, len(tok) - 1)])
            if len(tok) <= 8:
                out.append(tok)
        else:
            out.append(tok)
    return list(dict.fromkeys(out))


def _excerpt(text: str, query: str, max_chars: int = 220) -> str:
    source = _normalize_text(text)
    if not source:
        return ""
    q = _normalize_text(query)
    if not q:
        return source[:max_chars]
    pos = source.lower().find(q.lower())
    if pos < 0:
        return source[:max_chars]
    start = max(0, pos - max_chars // 3)
    end = min(len(source), start + max_chars)
    return source[start:end]


@dataclass
class PageDoc:
    doc_id: str
    page_no: int
    text: str
    source_path: str


def _load_docs(root: Path) -> list[PageDoc]:
    out: list[PageDoc] = []
    if not root.exists():
        return out
    for file_path in root.glob("*/*.txt"):
        if not file_path.is_file():
            continue
        doc_id = file_path.parent.name
        page_match = re.search(r"page_(\d+)\.txt$", file_path.name)
        page_no = int(page_match.group(1)) if page_match else 0
        if not doc_id or page_no <= 0:
            continue
        try:
            text = file_path.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        cleaned = _normalize_text(text)
        if not cleaned or cleaned.lower() == "discarded" or len(cleaned) < 4:
            continue
        out.append(
            PageDoc(
                doc_id=doc_id,
                page_no=page_no,
                text=cleaned,
                source_path=f"{doc_id}/{file_path.name}",
            )
        )
    return out


def _score(text: str, query: str, tokens: list[str]) -> float:
    q = query.lower()
    t = text.lower()
    q_compact = _compact_for_match(q)
    t_compact = _compact_for_match(t)
    score = 0.0
    if q and q in t:
        score += 20.0
    if q_compact and q_compact in t_compact:
        score += 28.0
    for token in tokens:
        if len(token) < 2:
            continue
        hits = t.count(token)
        hits += t_compact.count(_compact_for_match(token))
        if hits:
            score += hits * (1.0 + min(len(token), 10) / 10.0)
    return score


def _search(query: str, top_n: int) -> list[dict[str, Any]]:
    tokens = _tokenize(query)
    docs = _load_docs(DOCS_ROOT)
    scored: list[tuple[float, PageDoc]] = []
    for doc in docs:
        score = _score(doc.text, query, tokens)
        if score > 0:
            scored.append((score, doc))
    scored.sort(key=lambda item: item[0], reverse=True)
    result: list[dict[str, Any]] = []
    for score, doc in scored[:top_n]:
        result.append(
            {
                "doc_id": doc.doc_id,
                "page_no": doc.page_no,
                "excerpt": _excerpt(doc.text, query),
                "score": round(score, 6),
                "source_path": doc.source_path,
                "doc_name": doc.doc_id,
            }
        )
    return result


class _Handler(BaseHTTPRequestHandler):
    server_version = "Sirchmunk/0.1"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            docs = _load_docs(DOCS_ROOT)
            _json_response(
                self,
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "docs_root": str(DOCS_ROOT),
                    "indexed_pages": len(docs),
                },
            )
            return
        _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/search":
            _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        content_length = _safe_int(self.headers.get("Content-Length"), 0)
        try:
            raw = self.rfile.read(max(0, content_length))
            body = json.loads(raw.decode("utf-8") if raw else "{}")
        except Exception:  # noqa: BLE001
            _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "invalid json"})
            return

        query = _normalize_text((body or {}).get("query") or "")
        top_n = max(1, min(TOP_N_CAP, _safe_int((body or {}).get("top_n"), 50)))
        if not query:
            _json_response(self, HTTPStatus.OK, {"hits": []})
            return

        hits = _search(query=query, top_n=top_n)
        _json_response(self, HTTPStatus.OK, {"hits": hits})

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), _Handler)
    print(f"sirchmunk listening on {HOST}:{PORT}, docs_root={DOCS_ROOT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
