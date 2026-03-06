import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.services.runtime_defaults import (  # type: ignore[attr-defined]
    DEFAULT_RETRIEVAL_EVAL_DATASET,
    apply_runtime_defaults,
)


def test_apply_runtime_defaults_uses_siliconflow_stack() -> None:
    runtime = apply_runtime_defaults({})

    assert runtime["ocr_provider"] == "siliconflow"
    assert runtime["ocr_model"] == "deepseek-ai/DeepSeek-OCR"
    assert runtime["ocr_base_url"] == "https://api.siliconflow.cn/v1"
    assert runtime["embedding_provider"] == "siliconflow"
    assert runtime["embedding_model"] == "Qwen/Qwen3-Embedding-8B"
    assert runtime["embedding_base_url"] == "https://api.siliconflow.cn/v1"
    assert runtime["embedding_dimensions"] == "4096"
    assert runtime["rerank_provider"] == "siliconflow"
    assert runtime["rerank_model"] == "Qwen/Qwen3-Reranker-8B"
    assert runtime["rerank_base_url"] == "https://api.siliconflow.cn/v1"


def test_apply_runtime_defaults_preserves_explicit_overrides() -> None:
    runtime = apply_runtime_defaults(
        {
            "ocr_provider": "openai",
            "ocr_model": "gpt-4o-mini",
            "ocr_base_url": "https://ocr.example.com/v1",
            "embedding_provider": "local",
            "embedding_model": "bge-large-zh",
            "embedding_base_url": "http://embed.local/v1",
            "embedding_dimensions": "1024",
            "rerank_provider": "openai",
            "rerank_model": "foo-reranker",
            "rerank_base_url": "https://rerank.example.com/v1",
        }
    )

    assert runtime["ocr_provider"] == "openai"
    assert runtime["ocr_model"] == "gpt-4o-mini"
    assert runtime["ocr_base_url"] == "https://ocr.example.com/v1"
    assert runtime["embedding_provider"] == "local"
    assert runtime["embedding_model"] == "bge-large-zh"
    assert runtime["embedding_base_url"] == "http://embed.local/v1"
    assert runtime["embedding_dimensions"] == "1024"
    assert runtime["rerank_provider"] == "openai"
    assert runtime["rerank_model"] == "foo-reranker"
    assert runtime["rerank_base_url"] == "https://rerank.example.com/v1"


def test_apply_runtime_defaults_treats_auto_env_as_unset(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "auto")
    monkeypatch.setenv("RERANK_PROVIDER", "auto")

    runtime = apply_runtime_defaults({})

    assert runtime["embedding_provider"] == "siliconflow"
    assert runtime["rerank_provider"] == "siliconflow"


def test_default_retrieval_eval_dataset_points_to_eight_spec_pack() -> None:
    expected = ROOT / "datasets" / "v1.2" / "retrieval_eval_eight_specs_bid_32.jsonl"
    assert DEFAULT_RETRIEVAL_EVAL_DATASET == expected.resolve()
    assert DEFAULT_RETRIEVAL_EVAL_DATASET.exists()
    rows = [line for line in DEFAULT_RETRIEVAL_EVAL_DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 32
