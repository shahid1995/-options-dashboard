"""Timestamp serialization regression tests.

Verifies that all user-facing application timestamps are serialized with
explicit UTC offset (+00:00), ensuring the frontend correctly interprets
the instant regardless of browser timezone.

Covers:
  - Naive UTC datetime from SQLite -> +00:00
  - Aware UTC datetime -> +00:00
  - None handling
  - Pydantic model serialization
  - from_attributes (SQLAlchemy round-trip)
  - Critical acceptance test: 2026-08-29T13:55:00Z -> IST 29 Aug, 7:25 pm
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import BaseModel, ConfigDict

from app.schemas import UtcDatetime, _serialize_utc_datetime
from app.utils.time import to_ist_display


# ---------------------------------------------------------------------------
# Helper schemas for testing
# ---------------------------------------------------------------------------

class _OrderLike(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    created_at: UtcDatetime
    updated_at: UtcDatetime


class _PositionLike(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    opened_at: UtcDatetime
    closed_at: UtcDatetime | None


class _TradeLike(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    entry_at: UtcDatetime
    exit_at: UtcDatetime | None


# Simulate SQLAlchemy model (naive UTC from SQLite)
class _FakeORM:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


# ---------------------------------------------------------------------------
# 1. _serialize_utc_datetime core behavior
# ---------------------------------------------------------------------------

class TestSerializeUtcDatetime:
    def test_naive_utc_gets_offset(self):
        """Naive UTC datetime from SQLite gets +00:00 offset."""
        dt = datetime(2026, 8, 29, 13, 55, 0)
        result = _serialize_utc_datetime(dt)
        assert result == "2026-08-29T13:55:00+00:00"

    def test_aware_utc_preserved(self):
        """Aware UTC datetime keeps its offset."""
        dt = datetime(2026, 8, 29, 13, 55, 0, tzinfo=timezone.utc)
        result = _serialize_utc_datetime(dt)
        assert result == "2026-08-29T13:55:00+00:00"

    def test_none_returns_none(self):
        """None is passed through."""
        assert _serialize_utc_datetime(None) is None

    def test_naive_midnight(self):
        """Naive UTC midnight gets +00:00."""
        dt = datetime(2026, 8, 30, 0, 0, 0)
        result = _serialize_utc_datetime(dt)
        assert result == "2026-08-30T00:00:00+00:00"

    def test_naive_with_microseconds(self):
        """Microseconds are preserved."""
        dt = datetime(2026, 8, 29, 13, 55, 0, 123456)
        result = _serialize_utc_datetime(dt)
        assert "+00:00" in result
        assert "123456" in result


# ---------------------------------------------------------------------------
# 2. Pydantic UtcDatetime field serialization
# ---------------------------------------------------------------------------

class TestUtcDatetimePydantic:
    def test_naive_field_serializes_with_offset(self):
        """UtcDatetime field on a Pydantic model adds +00:00."""
        m = _OrderLike(
            created_at=datetime(2026, 8, 29, 13, 55),
            updated_at=datetime(2026, 8, 29, 13, 55),
        )
        dumped = m.model_dump(mode="json")
        assert "+00:00" in dumped["created_at"]
        assert "+00:00" in dumped["updated_at"]

    def test_from_attributes_naive_utc(self):
        """Simulates SQLAlchemy -> Pydantic round-trip with naive UTC."""
        orm = _FakeORM(
            opened_at=datetime(2026, 8, 29, 13, 55),
            closed_at=None,
        )
        m = _PositionLike.model_validate(orm)
        dumped = m.model_dump(mode="json")
        assert "+00:00" in dumped["opened_at"]
        assert dumped["closed_at"] is None

    def test_from_attributes_with_exit(self):
        """Position with closed_at gets offset."""
        orm = _FakeORM(
            opened_at=datetime(2026, 8, 29, 13, 55),
            closed_at=datetime(2026, 8, 29, 14, 30),
        )
        m = _PositionLike.model_validate(orm)
        dumped = m.model_dump(mode="json")
        assert "+00:00" in dumped["opened_at"]
        assert "+00:00" in dumped["closed_at"]

    def test_trade_entry_exit(self):
        """Trade entry/exit timestamps get offset."""
        orm = _FakeORM(
            entry_at=datetime(2026, 8, 29, 13, 55),
            exit_at=datetime(2026, 8, 29, 14, 30),
        )
        m = _TradeLike.model_validate(orm)
        dumped = m.model_dump(mode="json")
        assert "+00:00" in dumped["entry_at"]
        assert "+00:00" in dumped["exit_at"]


# ---------------------------------------------------------------------------
# 3. Critical acceptance test: UTC -> IST display
# ---------------------------------------------------------------------------

class TestCriticalAcceptance:
    def test_utc_to_ist_display(self):
        """2026-08-29T13:55:00Z displays as 29 Aug, 7:25 pm in IST."""
        dt = datetime(2026, 8, 29, 13, 55, tzinfo=timezone.utc)
        result = to_ist_display(dt)
        assert result == "29 Aug, 7:25 pm", f"Got: {result}"

    def test_serialized_utc_parses_correctly(self):
        """Simulates what the frontend does: new Date(iso).toLocaleString('en-IN')."""
        # Backend serializes naive UTC with +00:00
        naive_utc = datetime(2026, 8, 29, 13, 55)
        serialized = _serialize_utc_datetime(naive_utc)
        assert serialized == "2026-08-29T13:55:00+00:00"

        # Frontend would do: new Date("2026-08-29T13:55:00+00:00")
        # This correctly parses as UTC, then toLocaleString("en-IN") converts to IST
        assert "+00:00" in serialized
        # The instant is 13:55 UTC = 19:25 IST
        dt = datetime(2026, 8, 29, 13, 55, tzinfo=timezone.utc)
        assert to_ist_display(dt) == "29 Aug, 7:25 pm"

    def test_midnight_crossing(self):
        """2026-08-29T18:30:00Z = 30 Aug, 12:00 am IST."""
        naive_utc = datetime(2026, 8, 29, 18, 30)
        serialized = _serialize_utc_datetime(naive_utc)
        assert "2026-08-29T18:30:00+00:00" == serialized
        dt_aware = datetime(2026, 8, 29, 18, 30, tzinfo=timezone.utc)
        result = to_ist_display(dt_aware)
        assert "30 Aug" in result
        assert "12:00 am" in result

    def test_morning_ist(self):
        """2026-08-29T03:45:00Z = 29 Aug, 9:15 am IST."""
        naive_utc = datetime(2026, 8, 29, 3, 45)
        serialized = _serialize_utc_datetime(naive_utc)
        assert "2026-08-29T03:45:00+00:00" == serialized
        dt_aware = datetime(2026, 8, 29, 3, 45, tzinfo=timezone.utc)
        result = to_ist_display(dt_aware)
        assert "29 Aug" in result
        assert "9:15 am" in result
