"""Pre-rendered Hindi voice replies for failures and interim acks.

Day 6 polish 1 + 4. Generated once via ``scripts/prerender_system_voices.py``,
uploaded to S3, Meta media_ids cached in DDB under
``pk=mom, sk=system_voice#<key>``. Lookup is constant-time on the hot path.

Pattern: ``failure_voice(key)`` returns a Hindi sentence string. The actual
audio bytes are pre-rendered and the media_id cached; ``_send_failure_voice``
in ``app.py`` resolves key → media_id from DDB and ``send_audio()`` directly,
skipping Sarvam on the hot path.
"""
from __future__ import annotations

import random

# 8 failure voices, all in Hindi. Per docs/DAY_6.md polish 4.
FAILURE_VOICES: dict[str, str] = {
    "executor_timeout": "मम्मी, अभी थोड़ी technical दिक्कत है, 5 minute में try करूंगी।",
    "out_of_stock": "मम्मी, {item} अभी available नहीं है, कुछ और मंगवा दूं?",
    "session_expired": "मम्मी, login refresh करना है, Deep को बता दिया है।",
    "unclear_intent": "मम्मी, समझ नहीं आया ठीक से, एक बार और बोलिए?",
    "pin_not_serviceable": "मम्मी, आपके area में {service} delivery नहीं है अभी।",
    "amount_too_high": "मम्मी, ये बहुत बड़ा amount है, Deep से confirm करना पड़ेगा।",
    "network_error": "मम्मी, internet में दिक्कत है, थोड़ी देर बाद try करूं?",
    "generic": "मम्मी, कुछ problem है, Deep को बता दिया, थोड़ी देर में ठीक हो जाएगा।",
}

# 3 interim ack variants — one is sent (BackgroundTask) within ~1s of every
# voice note arriving, before STT/LLM kick in. Per docs/DAY_6.md polish 1.
INTERIM_ACKS: list[str] = [
    "ठीक है मम्मी, देख रही हूँ",
    "एक minute मम्मी, check करती हूँ",
    "हाँ मम्मी, सुन लिया, थोड़ा रुकिए",
]

# A different pool when we know the turn will be slow (executor-bound).
INTERIM_ACKS_SLOW: list[str] = [
    "मम्मी, order लगा रही हूँ, थोड़ा time लगेगा",
    "मम्मी, check करती हूँ, 30 second रुकिए",
]


def failure_voice(key: str, **fmt_args: str) -> str:
    """Return the Hindi failure sentence for a known key, formatted with kwargs.

    Falls back to ``generic`` if the key is unknown.
    """
    template = FAILURE_VOICES.get(key, FAILURE_VOICES["generic"])
    try:
        return template.format(**fmt_args)
    except KeyError:
        return FAILURE_VOICES["generic"]


def random_interim_ack(slow: bool = False) -> str:
    pool = INTERIM_ACKS_SLOW if slow else INTERIM_ACKS
    return random.choice(pool)
