"""Entity dictionary model for stable cross-process IDs."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class EntityDictionary(Base):
    __tablename__ = "entity_dictionary"
    __table_args__ = (UniqueConstraint("entity_kind", "entity_name", name="uq_entity_kind_name"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_name: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
