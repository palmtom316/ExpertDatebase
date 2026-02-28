"""Base declarative class and model registry."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Ensure table metadata is registered as soon as Base is imported.
from . import asset  # noqa: E402,F401
from . import chunk  # noqa: E402,F401
from . import document  # noqa: E402,F401
from . import eval  # noqa: E402,F401
from . import llm_call_log  # noqa: E402,F401
