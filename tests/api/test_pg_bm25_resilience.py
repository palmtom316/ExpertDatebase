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

