"""Asset model for IE extraction outputs."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False)
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    data_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    source_page: Mapped[int] = mapped_column(Integer, nullable=False)
    source_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    block_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    table_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    row_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
