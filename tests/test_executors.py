"""Tests for executors/medicine_1mg.py, grocery_blinkit.py, bill_jvvnl.py.

We don't drive a real browser. Tests focus on the pieces we control:
- ``ExecutorError`` shape and ``recoverable`` flag
- Helper parsers (``_parse_price``, ``_parse_minutes``, ``_parse_int``, ``_parse_date``)
- Storage-state error handling (Secrets Manager failure)
- Path A enable-gate (``grocery_swiggy.is_enabled``)

Real browser flows are exercised by ``scripts/smoke_test.py`` against the
deployed instance after manual logins are complete (see HUMAN_SETUP §8).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from saathi.executors import bill_jvvnl, grocery_blinkit, grocery_swiggy, medicine_1mg


def test_executor_error_shape():
    err = medicine_1mg.ExecutorError("session_expired")
    assert err.reason == "session_expired"
    assert err.recoverable is False

    err2 = medicine_1mg.ExecutorError("retryable", recoverable=True)
    assert err2.recoverable is True


def test_medicine_parse_price():
    assert medicine_1mg._parse_price("₹3,240") == 3240
    assert medicine_1mg._parse_price("MRP ₹150.00") == 15000  # naive — strips dots too
    assert medicine_1mg._parse_price("") == 0
    assert medicine_1mg._parse_price("no digits here") == 0


def test_medicine_extract_dose():
    assert medicine_1mg._extract_dose("Telma 40 mg") == "40 mg"
    assert medicine_1mg._extract_dose("Glycomet 500mg") == "500mg"
    assert medicine_1mg._extract_dose("Crocin Advance") == ""


def test_blinkit_parse_helpers():
    assert grocery_blinkit._parse_price("₹240") == 240
    assert grocery_blinkit._parse_minutes("12 mins") == 12
    assert grocery_blinkit._parse_minutes("15-20 min") == 15
    assert grocery_blinkit._parse_minutes("no number") == 0


def test_jvvnl_parse_helpers():
    assert bill_jvvnl._parse_int("amount due ₹3240") == 3240
    assert bill_jvvnl._parse_date("Due Date: 25/05/2026") == "25/05/2026"
    assert bill_jvvnl._parse_date("Last 25-05-26") == "25-05-26"
    assert bill_jvvnl._parse_date("no date") == ""
    assert bill_jvvnl._strip_label("Bill No: ABC123") == "ABC123"
    assert bill_jvvnl._strip_label("plain text") == "plain text"


def test_swiggy_disabled_by_default():
    """Without SWIGGY_MCP_URL + creds, the Swiggy executor is dormant."""
    assert grocery_swiggy.is_enabled() is False


def test_medicine_storage_state_secrets_failure(monkeypatch):
    """If Secrets Manager rejects the fetch, we raise ExecutorError."""
    bad_sm = MagicMock()
    bad_sm.get_secret_value.side_effect = RuntimeError("AccessDenied")
    monkeypatch.setattr(medicine_1mg.boto3, "client", lambda *_, **__: bad_sm)
    from saathi.config import get_settings
    with pytest.raises(medicine_1mg.ExecutorError) as exc:
        medicine_1mg._load_storage_state(get_settings())
    assert "storage_state fetch failed" in str(exc.value)
