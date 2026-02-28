"""Dataset helpers for eval set management."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4


def _dataset_dir(dataset_version: str) -> Path:
    base = Path(os.getenv("EVAL_DATASETS_ROOT", "datasets"))
    return base / dataset_version


def _manifest_path(dataset_version: str) -> Path:
    return _dataset_dir(dataset_version) / "manifest.json"


def _inputs_path(dataset_version: str) -> Path:
    return _dataset_dir(dataset_version) / "inputs.jsonl"


def _truths_path(dataset_version: str) -> Path:
    return _dataset_dir(dataset_version) / "truths.jsonl"


def ensure_dataset_layout(dataset_version: str = "v1.0") -> dict[str, str]:
    d = _dataset_dir(dataset_version)
    d.mkdir(parents=True, exist_ok=True)

    manifest = _manifest_path(dataset_version)
    inputs = _inputs_path(dataset_version)
    truths = _truths_path(dataset_version)

    if not manifest.exists():
        manifest.write_text(json.dumps({"dataset_version": dataset_version, "samples": []}, ensure_ascii=False, indent=2), encoding="utf-8")
    if not inputs.exists():
        inputs.write_text("", encoding="utf-8")
    if not truths.exists():
        truths.write_text("", encoding="utf-8")

    return {
        "dataset_dir": str(d),
        "manifest": str(manifest),
        "inputs": str(inputs),
        "truths": str(truths),
    }


def add_sample_to_dataset(
    dataset_version: str,
    doc_id: str,
    version_id: str,
    question: str,
    truth_answer: str,
    task_type: str = "QA",
) -> dict[str, Any]:
    paths = ensure_dataset_layout(dataset_version)
    manifest_path = Path(paths["manifest"])
    inputs_path = Path(paths["inputs"])
    truths_path = Path(paths["truths"])

    sample_id = f"s_{uuid4().hex[:10]}"
    input_row = {
        "sample_id": sample_id,
        "doc_id": doc_id,
        "version_id": version_id,
        "task_type": task_type,
        "question": question,
    }
    truth_row = {
        "sample_id": sample_id,
        "task_type": task_type,
        "answer": truth_answer,
    }

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    samples = manifest.get("samples") or []
    samples.append(
        {
            "sample_id": sample_id,
            "task_type": task_type,
            "input_ref": "inputs.jsonl",
            "truth_ref": "truths.jsonl",
        }
    )
    manifest["samples"] = samples
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    with inputs_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(input_row, ensure_ascii=False) + "\n")
    with truths_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(truth_row, ensure_ascii=False) + "\n")

    return {
        "sample_id": sample_id,
        "dataset_version": dataset_version,
        "task_type": task_type,
        "manifest_path": str(manifest_path),
    }


def load_dataset_rows(dataset_version: str) -> list[dict[str, Any]]:
    paths = ensure_dataset_layout(dataset_version)
    inputs = [json.loads(x) for x in Path(paths["inputs"]).read_text(encoding="utf-8").splitlines() if x.strip()]
    truths = [json.loads(x) for x in Path(paths["truths"]).read_text(encoding="utf-8").splitlines() if x.strip()]

    truth_map = {str(x.get("sample_id")): x for x in truths}
    rows: list[dict[str, Any]] = []
    for item in inputs:
        sample_id = str(item.get("sample_id"))
        truth = truth_map.get(sample_id, {})
        rows.append(
            {
                "sample_id": sample_id,
                "task_type": str(item.get("task_type") or "QA"),
                "input": item,
                "truth": truth,
            }
        )
    return rows
