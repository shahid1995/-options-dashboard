"""Timestamp standardization tests — verifies all fixes for deprecated patterns.

Ensures:
  1. No datetime.utcnow() in production code
  2. No naive datetime.now() in production code
  3. IST is imported from market_time, not redefined
  4. No __import__ hacks in production code
  5. No incorrect "Z" suffix on naive-IST timestamps
  6. Centralized utcnow() works correctly
  7. to_iso_utc() produces correct format
  8. to_ist_display() produces correct IST format
"""
from __future__ import annotations

import ast
import os
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# 1. No datetime.utcnow() in production code
# ---------------------------------------------------------------------------

def _find_py_files(root: str, exclude_dirs: tuple[str, ...] = ("__pycache__", ".git")) -> list[str]:
    """Recursively find .py files, excluding specified directories."""
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
        for f in filenames:
            if f.endswith(".py"):
                files.append(os.path.join(dirpath, f))
    return files


def test_no_utcnow_in_production():
    """datetime.utcnow() is deprecated in Python 3.12+ and must not be used."""
    backend_dir = os.path.join(os.path.dirname(__file__), "..")
    app_dir = os.path.join(backend_dir, "app")
    violations = []
    for filepath in _find_py_files(app_dir):
        with open(filepath, encoding='utf-8') as f:
            content = f.read()
        # Skip the time.py docstring which mentions utcnow() as deprecated
        norm = os.path.normpath(filepath)
        if norm.endswith(os.path.join("utils", "time.py")):
            continue
        if "datetime.utcnow()" in content:
            rel = os.path.relpath(filepath, backend_dir)
            violations.append(rel)
    assert not violations, f"datetime.utcnow() found in: {violations}"


# ---------------------------------------------------------------------------
# 2. No naive datetime.now() in production code
# ---------------------------------------------------------------------------

def test_no_naive_now_in_production():  # noqa: E501
    """datetime.now() without timezone returns naive local time — must not be used."""
    backend_dir = os.path.join(os.path.dirname(__file__), "..")
    app_dir = os.path.join(backend_dir, "app")
    violations = []
    for filepath in _find_py_files(app_dir):
        # Skip utility files that legitimately use datetime.now(IST)
        norm = os.path.normpath(filepath)
        if norm.endswith(os.path.join("utils", "time.py")):
            continue
        if norm.endswith(os.path.join("utils", "market_time.py")):
            continue
        with open(filepath, encoding='utf-8') as f:
            lines = f.readlines()
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Skip comments and strings
            if stripped.startswith("#") or stripped.startswith('"') or stripped.startswith("'"):
                continue
            # Skip _now() function definitions
            if "_now" in stripped and "def " in stripped:
                continue
            # Check for datetime.now() without arguments
            if "datetime.now()" in stripped and "datetime.now(timezone" not in stripped and "datetime.now(IST)" not in stripped:
                rel = os.path.relpath(filepath, backend_dir)
                violations.append(f"{rel}:{i}")
    assert not violations, f"Naive datetime.now() found in: {violations}"


# ---------------------------------------------------------------------------
# 3. IST only defined in market_time.py
# ---------------------------------------------------------------------------

def test_ist_single_definition():
    """IST timezone must be defined only in app/utils/market_time.py."""
    backend_dir = os.path.join(os.path.dirname(__file__), "..")
    app_dir = os.path.join(backend_dir, "app")
    violations = []
    for filepath in _find_py_files(app_dir):
        if "market_time.py" in filepath:
            continue
        with open(filepath, encoding='utf-8') as f:
            content = f.read()
        if "IST = timezone(timedelta" in content:
            rel = os.path.relpath(filepath, backend_dir)
            violations.append(rel)
    assert not violations, f"IST redefined in: {violations}"


# ---------------------------------------------------------------------------
# 4. No __import__ hacks in production code
# ---------------------------------------------------------------------------

def test_no_import_hacks():
    """Inline __import__() must not be used in production code."""
    backend_dir = os.path.join(os.path.dirname(__file__), "..")
    app_dir = os.path.join(backend_dir, "app")
    violations = []
    for filepath in _find_py_files(app_dir):
        with open(filepath, encoding='utf-8') as f:
            content = f.read()
        if '__import__("datetime")' in content or "__import__('datetime')" in content:
            rel = os.path.relpath(filepath, backend_dir)
            violations.append(rel)
    assert not violations, f"__import__ hacks found in: {violations}"


# ---------------------------------------------------------------------------
# 5. No incorrect "Z" suffix on naive-IST timestamps
# ---------------------------------------------------------------------------

def test_no_z_suffix_on_naive_ist():
    """Appending 'Z' to naive-IST timestamps is semantically incorrect."""
    backend_dir = os.path.join(os.path.dirname(__file__), "..")
    app_dir = os.path.join(backend_dir, "app")
    violations = []
    for filepath in _find_py_files(app_dir):
        with open(filepath, encoding='utf-8') as f:
            content = f.read()
        # Look for isoformat() + "Z" patterns
        if 'isoformat() + "Z"' in content or "isoformat() + 'Z'" in content:
            rel = os.path.relpath(filepath, backend_dir)
            violations.append(rel)
    assert not violations, f"Naive-IST timestamps with 'Z' suffix in: {violations}"


# ---------------------------------------------------------------------------
# 6. Centralized utcnow() works correctly
# ---------------------------------------------------------------------------

def test_utcnow_returns_aware_utc():
    """app.utils.time.utcnow() returns timezone-aware UTC datetime."""
    from app.utils.time import utcnow
    dt = utcnow()
    assert dt.tzinfo is not None, "utcnow() returned naive datetime"
    assert dt.tzinfo == timezone.utc, f"utcnow() tzinfo is {dt.tzinfo}, expected UTC"


def test_utcnow_matches_system_time():
    """app.utils.time.utcnow() is approximately equal to system time."""
    from app.utils.time import utcnow
    before = datetime.now(timezone.utc)
    dt = utcnow()
    after = datetime.now(timezone.utc)
    assert before <= dt <= after, "utcnow() is outside system time range"


# ---------------------------------------------------------------------------
# 7. to_iso_utc() produces correct format
# ---------------------------------------------------------------------------

def test_to_iso_utc_format():
    """to_iso_utc() produces ISO 8601 with +00:00 offset."""
    from app.utils.time import to_iso_utc
    dt = datetime(2026, 8, 29, 8, 25, tzinfo=timezone.utc)
    result = to_iso_utc(dt)
    assert result == "2026-08-29T08:25:00+00:00", f"Got: {result}"


def test_to_iso_utc_none():
    """to_iso_utc(None) returns None."""
    from app.utils.time import to_iso_utc
    assert to_iso_utc(None) is None


def test_to_iso_utc_naive_assumes_utc():
    """to_iso_utc() with naive datetime assumes UTC."""
    from app.utils.time import to_iso_utc
    dt = datetime(2026, 8, 29, 8, 25)
    result = to_iso_utc(dt)
    assert "+00:00" in result, f"Missing UTC offset: {result}"


# ---------------------------------------------------------------------------
# 8. to_ist_display() produces correct IST format
# ---------------------------------------------------------------------------

def test_to_ist_display_format():
    """to_ist_display() formats as '29 Aug, 7:25 pm' for IST."""
    from app.utils.time import to_ist_display
    # 2026-08-29T13:55:00Z = 19:25 IST
    dt = datetime(2026, 8, 29, 13, 55, tzinfo=timezone.utc)
    result = to_ist_display(dt)
    assert "29 Aug" in result, f"Expected '29 Aug' in '{result}'"
    assert "7:25 pm" in result.lower(), f"Expected '7:25 pm' in '{result}'"



def test_critical_utc_to_ist_display():
    """2026-08-29T13:55:00Z must display as 29 Aug, 7:25 pm in IST."""
    from app.utils.time import to_ist_display
    dt = datetime(2026, 8, 29, 13, 55, tzinfo=timezone.utc)
    result = to_ist_display(dt)
    assert result == "29 Aug, 7:25 pm", f"Expected 29 Aug, 7:25 pm, got {result}"

