import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.qdrant_repo import InMemoryQdrantRepo, QdrantHttpRepo, create_qdrant_repo_from_env


def test_worker_qdrant_factory_builds_http_repo() -> None:
    old = dict(os.environ)
    try:
        os.environ["VECTORDB_ENDPOINT"] = "qdrant:6333"
        repo = create_qdrant_repo_from_env()
        assert isinstance(repo, QdrantHttpRepo)
    finally:
        os.environ.clear()
        os.environ.update(old)


def test_worker_qdrant_factory_falls_back_memory() -> None:
    old = dict(os.environ)
    try:
        os.environ.pop("VECTORDB_ENDPOINT", None)
        repo = create_qdrant_repo_from_env()
        assert isinstance(repo, InMemoryQdrantRepo)
    finally:
        os.environ.clear()
        os.environ.update(old)
