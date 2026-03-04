import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.services.retrieval.sparse.pg_bm25 import PgBM25SparseRetriever


def test_pg_bm25_returns_empty_when_schema_init_fails() -> None:
    retriever = PgBM25SparseRetriever(database_url="postgresql://placeholder")
    retriever._engine = object()  # type: ignore[assignment]
    with patch.object(retriever, "_ensure_schema", side_effect=RuntimeError("db down")):
        hits = retriever.search(query_text="变压器", top_n=5)
    assert hits == []


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _Conn:
    def __init__(self):
        self.calls = 0

    def execute(self, sql, params):  # noqa: ARG002
        self.calls += 1
        if self.calls == 1:
            return _Result([])
        return _Result(
            [
                {
                    "doc_id": "doc_1",
                    "page_no": 6,
                    "excerpt": "变压器安装要求",
                    "score": 3.5,
                    "source_path": "doc_1/page_006.txt",
                }
            ]
        )


class _Tx:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False


class _Engine:
    def __init__(self):
        self.conn = _Conn()

    def begin(self):
        return _Tx(self.conn)


def test_pg_bm25_uses_like_fallback_for_cjk_when_tsv_no_hits() -> None:
    retriever = PgBM25SparseRetriever(database_url="postgresql://placeholder")
    fake_engine = _Engine()
    retriever._engine = fake_engine  # type: ignore[assignment]
    with patch.object(retriever, "_ensure_schema", return_value=None):
        hits = retriever.search(query_text="变压器的安装有哪些规定", top_n=5)
    assert fake_engine.conn.calls == 2
    assert len(hits) == 1
    assert hits[0]["doc_id"] == "doc_1"
    assert hits[0]["page_no"] == 6
