"""Day 6 polish tests: failure voices, abort flag, interim acks."""
from __future__ import annotations

from saathi.llm.abort import is_stop_command
from saathi.messaging.templates import (
    FAILURE_VOICES,
    INTERIM_ACKS,
    INTERIM_ACKS_SLOW,
    failure_voice,
    random_interim_ack,
)

# ─── FAILURE_VOICES ──────────────────────────────────────────────────────────


def test_failure_voices_eight_entries():
    assert len(FAILURE_VOICES) == 8


def test_failure_voices_have_devanagari():
    """Each failure voice must contain Devanagari script — never pure-English fallback."""
    for key, text in FAILURE_VOICES.items():
        has_devanagari = any("ऀ" <= c <= "ॿ" for c in text)
        assert has_devanagari, f"{key!r} has no Devanagari: {text!r}"


def test_failure_voice_lookup_known_key():
    out = failure_voice("network_error")
    assert "internet" in out


def test_failure_voice_lookup_unknown_key_falls_back_to_generic():
    out = failure_voice("nonexistent_key")
    assert out == FAILURE_VOICES["generic"]


def test_failure_voice_format_substitutes():
    out = failure_voice("out_of_stock", item="दूध")
    assert "दूध" in out


def test_failure_voice_missing_format_var_falls_back():
    """If a template needs ``{item}`` but caller forgets, we don't raise."""
    out = failure_voice("out_of_stock")  # missing `item`
    assert out == FAILURE_VOICES["generic"]


def test_random_interim_ack_in_pool():
    assert random_interim_ack() in INTERIM_ACKS
    assert random_interim_ack(slow=True) in INTERIM_ACKS_SLOW


# ─── Abort flag (stop-keyword) ───────────────────────────────────────────────


def test_abort_detects_roko():
    assert is_stop_command("रोको Saathi") is True


def test_abort_detects_cancel():
    assert is_stop_command("cancel kar do") is True


def test_abort_detects_ruk_ja():
    assert is_stop_command("रुक जा अभी") is True


def test_abort_detects_radd():
    assert is_stop_command("रद्द कर दो") is True


def test_abort_does_not_fire_on_mid_sentence_roko():
    """'और तो रोको कर देती हूँ' = 'okay let me stop' — रोको is descriptive, not imperative."""
    assert is_stop_command("और तो रोको कर देती हूँ अब") is False


def test_abort_empty_transcript():
    assert is_stop_command("") is False
    assert is_stop_command("   ") is False


def test_abort_does_not_fire_on_normal_request():
    assert is_stop_command("टेलमा 40 खत्म हो गयी") is False
    assert is_stop_command("दूध और ब्रेड मंगवा दो") is False
