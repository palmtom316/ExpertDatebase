"""Scoring formulas for IE/TABLE/QA/RETR tasks."""

from __future__ import annotations


def clamp_0_100(score: float) -> float:
    return max(0.0, min(100.0, score))


def score_ie(
    precision: float,
    recall: float,
    source_acc: float,
    json_valid: float,
    hall_penalty: float,
    power_bonus: float,
) -> float:
    score = 40 * precision + 20 * recall + 20 * source_acc + 10 * json_valid - hall_penalty + power_bonus
    return clamp_0_100(score)


def score_table(row_acc: float, col_acc: float, cell_acc: float, num_acc: float) -> float:
    score = 25 * row_acc + 25 * col_acc + 35 * cell_acc + 15 * num_acc
    return clamp_0_100(score)


def score_qa(cite_presence: float, cite_acc: float, fact_acc: float, refusal_acc: float) -> float:
    score = 20 * cite_presence + 30 * cite_acc + 30 * fact_acc + 20 * refusal_acc
    return clamp_0_100(score)


def score_retrieval(hit5: float, hit10: float, mrr: float, latency_score: float) -> float:
    score = 40 * hit5 + 30 * hit10 + 20 * mrr + 10 * latency_score
    return clamp_0_100(score)
