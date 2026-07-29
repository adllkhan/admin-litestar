"""Throwaway models for package tests — no host application involved."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, LargeBinary, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for test models."""


class Widget(Base):
    """A model with a hidden column and a searchable digest column."""

    __tablename__ = "widget"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    kind: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(String(5))
    _blob_data: Mapped[bytes | None] = mapped_column(
        "_blob_data", LargeBinary, nullable=True
    )
    digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Secret(Base):
    """A model carrying a column that must never be selected."""

    __tablename__ = "secret"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
