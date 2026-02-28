import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.scorer import (  # noqa: E402
    amount_within_tolerance,
    line_length_within_tolerance,
    score_ie,
    score_qa,
    score_retrieval,
    voltage_exact_match,
)


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

    def test_amount_tolerance_plus_minus_one_percent(self) -> None:
        self.assertTrue(amount_within_tolerance(pred_amount=1010000, truth_amount=1000000))
        self.assertFalse(amount_within_tolerance(pred_amount=1030000, truth_amount=1000000))

    def test_voltage_must_match_exactly(self) -> None:
        self.assertTrue(voltage_exact_match(pred_kv=110, truth_kv=110))
        self.assertFalse(voltage_exact_match(pred_kv=220, truth_kv=110))

    def test_line_length_tolerance_plus_minus_point_one_km(self) -> None:
        self.assertTrue(line_length_within_tolerance(pred_km=12.04, truth_km=12.1))
        self.assertFalse(line_length_within_tolerance(pred_km=11.8, truth_km=12.1))


if __name__ == "__main__":
    unittest.main()
