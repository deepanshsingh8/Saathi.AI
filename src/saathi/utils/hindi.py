"""Hindi text helpers for TTS.

Bulbul speaks numerals and brand names better when they are spelled out
in Devanagari. Two helpers:

- ``rupees_to_hindi_words(amount)``: ``3240 -> "तीन हज़ार दो सौ चालीस रुपये"``.
- ``apply_pronunciation_overrides(text)``: word-boundary-replace English
  brand tokens with Devanagari respellings before sending to TTS.

The override dict starts seeded with a handful of medicines that are likely
to appear in Mom's first orders. Add to it as Day 2/7 reality testing
discovers more (per docs/DAY_2.md "Pronunciation audit").
"""
from __future__ import annotations

import re

# Seed with the most likely candidates from PLAN §2.1 / DAY_2 §"Pronunciation audit".
# RE-VALIDATE after Mom's voice round-trip on Day 2.
PRONUNCIATION_OVERRIDES: dict[str, str] = {
    "Telma": "टेल्मा",
    "Glycomet": "ग्लाइकोमेट",
    "Ecosprin": "एकोस्प्रिन",
    "Pantop": "पैन्टोप",
    "Crocin": "क्रोसिन",
    "Saathi": "साथी",
}

# Hindi numeral words for 0-99 and the powers we care about.
_UNITS = [
    "शून्य", "एक", "दो", "तीन", "चार", "पाँच", "छह", "सात", "आठ", "नौ",
    "दस", "ग्यारह", "बारह", "तेरह", "चौदह", "पंद्रह", "सोलह", "सत्रह", "अठारह", "उन्नीस",
]

# Index 20..99 — Hindi has irregular tens; brute-force is the cleanest readable form.
_TWENTY_TO_NINETYNINE = {
    20: "बीस", 21: "इक्कीस", 22: "बाईस", 23: "तेईस", 24: "चौबीस", 25: "पच्चीस",
    26: "छब्बीस", 27: "सत्ताईस", 28: "अट्ठाईस", 29: "उनतीस",
    30: "तीस", 31: "इकतीस", 32: "बत्तीस", 33: "तैंतीस", 34: "चौंतीस", 35: "पैंतीस",
    36: "छत्तीस", 37: "सैंतीस", 38: "अड़तीस", 39: "उनतालीस",
    40: "चालीस", 41: "इकतालीस", 42: "बयालीस", 43: "तैंतालीस", 44: "चौवालीस", 45: "पैंतालीस",
    46: "छियालीस", 47: "सैंतालीस", 48: "अड़तालीस", 49: "उनचास",
    50: "पचास", 51: "इक्यावन", 52: "बावन", 53: "तिरपन", 54: "चौवन", 55: "पचपन",
    56: "छप्पन", 57: "सत्तावन", 58: "अट्ठावन", 59: "उनसठ",
    60: "साठ", 61: "इकसठ", 62: "बासठ", 63: "तिरसठ", 64: "चौंसठ", 65: "पैंसठ",
    66: "छियासठ", 67: "सड़सठ", 68: "अड़सठ", 69: "उनहत्तर",
    70: "सत्तर", 71: "इकहत्तर", 72: "बहत्तर", 73: "तिहत्तर", 74: "चौहत्तर", 75: "पचहत्तर",
    76: "छिहत्तर", 77: "सतहत्तर", 78: "अठहत्तर", 79: "उनासी",
    80: "अस्सी", 81: "इक्यासी", 82: "बयासी", 83: "तिरासी", 84: "चौरासी", 85: "पचासी",
    86: "छियासी", 87: "सत्तासी", 88: "अट्ठासी", 89: "नवासी",
    90: "नब्बे", 91: "इक्यानवे", 92: "बानवे", 93: "तिरानवे", 94: "चौरानवे", 95: "पचानवे",
    96: "छियानवे", 97: "सत्तानवे", 98: "अट्ठानवे", 99: "निन्यानवे",
}


def _under_hundred(n: int) -> str:
    if n < 20:
        return _UNITS[n]
    return _TWENTY_TO_NINETYNINE[n]


def _under_thousand(n: int) -> str:
    if n < 100:
        return _under_hundred(n)
    hundreds, rest = divmod(n, 100)
    head = f"{_UNITS[hundreds]} सौ"
    return head if rest == 0 else f"{head} {_under_hundred(rest)}"


def rupees_to_hindi_words(amount: int) -> str:
    """Convert an INR integer amount to its Hindi word form, suffixed with " रुपये".

    Uses the Indian crore system (lakhs and crores). Handles 0 to 9_99_99_999.
    Above that, raises ValueError — Saathi caps Mom's order at ₹2,500 anyway,
    so this ceiling is more than safe.
    """
    if amount < 0:
        raise ValueError("negative amount")
    if amount > 99_99_99_999:
        raise ValueError("amount above 99,99,99,999 not supported")

    if amount == 0:
        return "शून्य रुपये"

    parts: list[str] = []

    crore, rest = divmod(amount, 1_00_00_000)
    if crore:
        parts.append(f"{_under_hundred(crore) if crore < 100 else _under_thousand(crore)} करोड़")

    lakh, rest = divmod(rest, 1_00_000)
    if lakh:
        parts.append(f"{_under_hundred(lakh)} लाख")

    thousand, rest = divmod(rest, 1_000)
    if thousand:
        parts.append(f"{_under_hundred(thousand)} हज़ार")

    if rest:
        parts.append(_under_thousand(rest))

    parts.append("रुपये")
    return " ".join(parts)


def rupees_for_confirmation(amount: int) -> str:
    """For amounts ≥ ₹1000, returns the natural phrasing followed by digit-by-digit
    re-statement, joined by ' — '. Below ₹1000, returns just the natural phrasing.

    Used in spend confirmation voice replies (Day 6 polish item 2).
    """
    natural = rupees_to_hindi_words(amount)
    if amount < 1000:
        return natural
    digits = " ".join(_UNITS[int(d)] for d in str(amount))
    return f"{natural} — {digits} रुपये"


_OVERRIDE_PATTERN_CACHE: tuple[re.Pattern[str], dict[str, str]] | None = None


def _build_override_pattern() -> tuple[re.Pattern[str], dict[str, str]]:
    """Compile a single case-insensitive word-boundary regex for all overrides."""
    keys = sorted(PRONUNCIATION_OVERRIDES.keys(), key=len, reverse=True)
    if not keys:
        return re.compile(r"$^"), {}
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(k) for k in keys) + r")\b",
        flags=re.IGNORECASE,
    )
    lower_map = {k.lower(): v for k, v in PRONUNCIATION_OVERRIDES.items()}
    return pattern, lower_map


def apply_pronunciation_overrides(text: str) -> str:
    """Replace English brand tokens in ``text`` with their Devanagari respellings.

    Word-boundary, case-insensitive. Idempotent on already-replaced text
    (Devanagari tokens won't match the English keys).
    """
    pattern, lower_map = _build_override_pattern()
    return pattern.sub(lambda m: lower_map[m.group(1).lower()], text)
