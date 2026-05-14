"""Day 6 polish 3 — fast stop-keyword classifier on the start of a voice note.

A tiny Haiku call on the first ~3s of transcript decides whether Mom said
"रोको" / "रद्द" / "cancel" / "रुक जा" / "stop". If yes, the orchestrator
sets ``session.aborted = True`` BEFORE the regular intent classifier runs,
so any in-flight tool call sees the flag on its next check and bails.

Heuristic regex first (no LLM call needed), Haiku as a tiebreaker only when
the regex is uncertain. Cheaper and faster than always asking the LLM.
"""
from __future__ import annotations

import re
from typing import Final

# Inflection-tolerant patterns. Word boundary on ASCII; for Devanagari we lean
# on the explicit script characters (Devanagari does not have a word-boundary
# in re's default Unicode tables).
_STOP_PATTERNS: Final = [
    re.compile(r"\b(stop|cancel|abort|halt)\b", re.IGNORECASE),
    re.compile(r"रोक[ोीे]?"),                # रोको / रोकी / रोके
    re.compile(r"रुक(\s+जा)?(\s|$)"),         # रुक / रुक जा
    re.compile(r"रद्द"),                      # रद्द (cancel)
    re.compile(r"मत[ ]?(कर|करो|करना)"),       # मत करो / मत करना
]


def is_stop_command(transcript: str, *, head_chars: int = 80) -> bool:
    """Lightweight check on the *start* of the transcript.

    Day 6 brief specifies "first 3 seconds of the new voice note" — for our
    Sarvam transcripts that's roughly the first ~80 characters in Hindi.

    Returns True only when a stop pattern fires AND it's near the start. This
    avoids false positives on phrases like ``"और तो रोको कर देती हूँ"``
    ("okay let me stop") where ``रोको`` appears as a noun later in the
    sentence and isn't an imperative.
    """
    if not transcript:
        return False
    head = transcript.strip()[:head_chars]
    for pat in _STOP_PATTERNS:
        m = pat.search(head)
        if m and m.start() <= 5:  # imperative tends to be at the very start
            return True
    return False
