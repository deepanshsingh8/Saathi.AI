"""Pure-function tests for utils/hindi.py — no external services."""
from __future__ import annotations

import pytest

from saathi.utils.hindi import (
    PRONUNCIATION_OVERRIDES,
    apply_pronunciation_overrides,
    rupees_for_confirmation,
    rupees_to_hindi_words,
)


@pytest.mark.parametrize(
    "amount,expected",
    [
        (0, "शून्य रुपये"),
        (1, "एक रुपये"),
        (19, "उन्नीस रुपये"),
        (20, "बीस रुपये"),
        (99, "निन्यानवे रुपये"),
        (100, "एक सौ रुपये"),
        (101, "एक सौ एक रुपये"),
        (999, "नौ सौ निन्यानवे रुपये"),
        (1000, "एक हज़ार रुपये"),
        (3240, "तीन हज़ार दो सौ चालीस रुपये"),
        (99_999, "निन्यानवे हज़ार नौ सौ निन्यानवे रुपये"),
        (1_00_000, "एक लाख रुपये"),
        (1_00_001, "एक लाख एक रुपये"),
        (12_34_567, "बारह लाख चौंतीस हज़ार पाँच सौ सड़सठ रुपये"),
        (1_00_00_000, "एक करोड़ रुपये"),
    ],
)
def test_rupees_to_hindi_words(amount: int, expected: str):
    assert rupees_to_hindi_words(amount) == expected


def test_rupees_negative_raises():
    with pytest.raises(ValueError):
        rupees_to_hindi_words(-1)


def test_rupees_above_ceiling_raises():
    with pytest.raises(ValueError):
        rupees_to_hindi_words(99_99_99_999 + 1)


def test_rupees_for_confirmation_below_threshold():
    # < 1000 — natural form only, no digit-by-digit.
    assert rupees_for_confirmation(340) == "तीन सौ चालीस रुपये"
    assert "—" not in rupees_for_confirmation(999)


def test_rupees_for_confirmation_at_threshold():
    out = rupees_for_confirmation(1000)
    assert out.startswith("एक हज़ार रुपये")
    assert "—" in out
    # Digit-by-digit suffix
    assert out.endswith("एक शून्य शून्य शून्य रुपये")


def test_rupees_for_confirmation_3240():
    out = rupees_for_confirmation(3240)
    assert out == "तीन हज़ार दो सौ चालीस रुपये — तीन दो चार शून्य रुपये"


def test_pronunciation_overrides_basic():
    PRONUNCIATION_OVERRIDES["Telma"] = "टेल्मा"  # already there but assert idempotent
    assert apply_pronunciation_overrides("Telma 40 खत्म हो गयी") == "टेल्मा 40 खत्म हो गयी"


def test_pronunciation_overrides_case_insensitive():
    assert "टेल्मा" in apply_pronunciation_overrides("telma is the medicine")
    assert "टेल्मा" in apply_pronunciation_overrides("TELMA")


def test_pronunciation_overrides_word_boundary():
    # 'Telmamax' should NOT be replaced — different word.
    out = apply_pronunciation_overrides("Telmamax is different")
    assert "Telmamax" in out
    assert "टेल्मा" not in out


def test_pronunciation_overrides_idempotent_on_devanagari():
    # Already-Devanagari text doesn't get re-replaced.
    out = apply_pronunciation_overrides("टेल्मा 40")
    assert out == "टेल्मा 40"
