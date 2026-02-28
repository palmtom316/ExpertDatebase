import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.services.eval_dataset import add_sample_to_dataset, ensure_dataset_layout, load_dataset_rows
from app.services.eval_repo import InMemoryEvalRepo


def test_eval_dataset_add_creates_manifest_input_truth(tmp_path: Path) -> None:
    old = dict(os.environ)
    try:
        os.environ["EVAL_DATASETS_ROOT"] = str(tmp_path)
        ensure_dataset_layout("v1.0")
        item = add_sample_to_dataset(
            dataset_version="v1.0",
            doc_id="doc_1",
            version_id="ver_1",
            question="合同金额是多少？",
            truth_answer="5000万元",
            task_type="QA",
        )
        rows = load_dataset_rows("v1.0")

        assert item["sample_id"]
        assert len(rows) == 1
        assert rows[0]["truth"]["answer"] == "5000万元"
    finally:
        os.environ.clear()
        os.environ.update(old)


def test_eval_repo_trends_from_results() -> None:
    repo = InMemoryEvalRepo()
    run = repo.create_run("v1.0", status="completed")
    repo.add_results(
        run_id=run["id"],
        results=[
            {"sample_id": "s1", "score_total": 90, "provider": "stub", "model": "stub", "breakdown_json": {}, "output_path": "a", "diff_path": "b"},
            {"sample_id": "s2", "score_total": 40, "provider": "stub", "model": "stub", "breakdown_json": {}, "output_path": "a", "diff_path": "b"},
        ],
    )
    trend = repo.build_trends()
    assert trend["total_results"] == 2
    assert trend["failed_results"] == 1
