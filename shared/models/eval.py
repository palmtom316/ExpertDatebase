"""Evaluation run/result models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class EvalRun(Base):
    __tablename__ = "eval_run"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="created", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class EvalSample(Base):
    __tablename__ = "eval_sample"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("eval_run.id"), nullable=False)
    sample_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    input_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    truth_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class EvalResult(Base):
    __tablename__ = "eval_result"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("eval_run.id"), nullable=False)
    sample_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    score_total: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    breakdown_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    diff_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
