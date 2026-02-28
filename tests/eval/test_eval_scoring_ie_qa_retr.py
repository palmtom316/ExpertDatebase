import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.scorer import score_ie, score_qa, score_retrieval  # noqa: E402


class TestEvalScoring(unittest.TestCase):
    def test_ie_score_formula(self) -> None:
        score = score_ie(
            precision=0.8,
            recall=0.7,
            source_acc=0.9,
            json_valid=1.0,
            hall_penalty=5,
            power_bonus=8,
        )
        # 40*0.8 + 20*0.7 + 20*0.9 + 10*1 - 5 + 8 = 77
        self.assertAlmostEqual(score, 77.0, places=2)

    def test_qa_score_formula(self) -> None:
        score = score_qa(cite_presence=1, cite_acc=0.8, fact_acc=0.9, refusal_acc=1)
        self.assertAlmostEqual(score, 20 + 24 + 27 + 20, places=2)

    def test_retrieval_score_formula(self) -> None:
        score = score_retrieval(hit5=0.9, hit10=1.0, mrr=0.8, latency_score=0.7)
        self.assertAlmostEqual(score, 36 + 30 + 16 + 7, places=2)


if __name__ == "__main__":
    unittest.main()
