# Day 2 — Voice in, voice out

**Goal by EOD:** Mom sends a Hindi voice note → Saathi transcribes it → echoes the transcript back as a Hindi voice reply. No LLM, no intent, no executor. Just clean voice round-trip.

**Out of scope today:** Intent classification (Day 3). Tool calling (Day 3). Any merchant interaction (Days 3–5).

## Why today matters

Voice is the single hardest UX surface in this product. If Sarvam Saaras misunderstands Mom's accent, or Bulbul mispronounces brand names, no amount of LLM cleverness rescues the bot. Day 2 is about proving the speech round-trip is reliable enough to build on, *before* you build the LLM on top of it.

The acceptance test is brutal and correct: Mom says something in Hindi-English mix; bot replies with the same words back in voice. If the words come back wrong, you know it's a speech problem, not an intent problem.

## Prereqs from Day 1

- Echo bot working over text.
- Sarvam API key in env.
- AWS credentials with S3 and Bedrock access.
- `saathi-media` S3 bucket exists in `ap-south-1` with SSE-KMS default encryption.

## New dependencies

Add to `pyproject.toml`:
```
sarvamai==4.23.2
pydub==0.25.1     # only for length probing; no FFmpeg conversion needed
```

## Files to build

### `src/saathi/storage/s3.py` (new)

Two functions:

```python
async def put_voice(user: str, kind: str, data: bytes, ext: str = "oga") -> str:
    """Upload to s3://saathi-media/{user}/{kind}/{ts}.{ext}.
    Returns the s3:// URI. Encrypted via bucket default KMS.
    kind ∈ {'inbound', 'outbound', 'prescription', 'receipt'}.
    """

async def get_object(s3_uri: str) -> bytes:
    """Fetch by s3:// URI. Used in tests and for replay."""
```

Use `aioboto3`. Single shared session via FastAPI dependency injection — don't re-create the session per call.

### `src/saathi/messaging/whatsapp.py` (extend)

Add three functions:

```python
async def download_media(media_id: str) -> tuple[bytes, str]:
    """Two-step fetch:
    1. GET graph.facebook.com/v22.0/{media_id} with Bearer auth → returns {url, mime_type}
    2. GET that url (also Bearer-auth required) → bytes.
    Returns (bytes, mime_type). The URL is short-lived (~5 min), so this must be called
    promptly from the worker, not deferred.
    """

async def upload_media(data: bytes, mime_type: str) -> str:
    """Multipart POST to /v22.0/{phone_id}/media.
    Returns Meta media ID. Use this to send outbound audio."""

async def send_audio(to: str, media_id: str) -> str:
    """Send {'type':'audio','audio':{'id': media_id}} via the messages endpoint.
    Returns WAMID."""
```

Important: WhatsApp inbound voice notes are OGG/Opus mono 16 kHz. Sarvam accepts this format directly — **do not transcode**. Outbound audio Sarvam returns is MP3 24 kHz — Meta accepts this as `audio/mpeg`.

### `src/saathi/speech/sarvam.py` (new)

Two async functions:

```python
async def transcribe(audio: bytes, mode: Literal["transcribe","codemix","translit"] = "codemix") -> str:
    """Saaras v3 STT.
    - language_code='hi-IN' for Hindi-dominant; 'unknown' for auto-detect.
    - mode='codemix' preserves English words as English ('Telma' stays 'Telma', not 'टेल्मा').
    - For files >30s, use the Saaras batch API (defer; Day 2 only handles ≤30s).
    Returns the transcript string. Raises SarvamError on failure.
    """

async def synthesize(text: str, voice: str = "vidya") -> bytes:
    """Bulbul v3 TTS.
    - voice ∈ {'vidya','anushka','meera','arvind','amol'}; default 'vidya' (warm female Hindi).
    - pitch=0, pace=1.0, loudness=1.2 (older-listener-friendly cadence).
    - Returns 24 kHz MP3 bytes.
    """
```

Use the `sarvamai` Python SDK. Wrap timeouts and 429 retries — Sarvam is generally fast (<1s) but rate-limits can hit during peak hours.

Define `SarvamError` exception.

### `src/saathi/speech/fallback.py` (new — but skeletal)

Stub for Whisper fallback. Just the signature today; implementation when Sarvam first 429s in production:

```python
async def transcribe_whisper_fallback(audio: bytes) -> str:
    """STUB: replaced when first Sarvam 429 hits production."""
    raise NotImplementedError("Whisper fallback not yet wired")
```

Add to STATUS.md under "Stubs".

### `src/saathi/utils/hindi.py` (new)

Helpers Bulbul needs to speak amounts correctly:

```python
PRONUNCIATION_OVERRIDES: dict[str, str] = {
    # Brand names Bulbul mispronounces. Populated as we discover them.
    # Key: English brand. Value: Devanagari respelling for TTS input.
}

def rupees_to_hindi_words(amount: int) -> str:
    """3240 -> 'तीन हज़ार दो सौ चालीस रुपये'.
    Handles 0 to 99_99_999 (Indian crore system). Above that, raise ValueError.
    Used in any TTS that mentions an amount ≥ ₹100.
    """

def apply_pronunciation_overrides(text: str) -> str:
    """Replace English brand tokens with Devanagari respellings before sending to TTS.
    Word-boundary regex; case-insensitive."""
```

Write tests for `rupees_to_hindi_words`. Edge cases: 0, 1, 99, 100, 999, 1000, 99999, 100000, 9999999.

### `src/saathi/app.py` (extend)

Wire the voice path. In `handle_text_message`'s sibling `handle_audio_message`:

1. Get `media_id` from `msg["audio"]["id"]`.
2. Call `whatsapp.download_media(media_id)` → bytes, mime.
3. `s3.put_voice("mom", "inbound", bytes)` → S3 URI (fire-and-forget, don't block on it).
4. `sarvam.transcribe(bytes)` → transcript.
5. For Day 2 only: echo the transcript back. Synthesize it: `sarvam.synthesize(transcript)` → mp3 bytes.
6. `whatsapp.upload_media(mp3, "audio/mpeg")` → media_id.
7. `whatsapp.send_audio(mom_number, media_id)`.

Wrap with timing logs at each step. Log structure:
```json
{"conv_id": "...", "stage": "stt", "latency_ms": 750, "transcript_len": 42}
```

### Worker pattern — async or inline?

For Day 2 keep it **inline** in the webhook handler. The whole round-trip should be under 6 seconds; Meta's 20s webhook ack timeout has plenty of room. Use `BackgroundTasks` so the 200 OK goes back to Meta immediately, then the work happens.

**Don't introduce SQS today.** That's a Day 6 polish task if latency becomes an issue.

## Tests

### `tests/test_speech.py`

Use fixtures in `tests/fixtures/`:
- `mom_hello.oga` — 3-second recording of "नमस्ते"
- `mom_medicine.oga` — 8-second "टेलमा 40 खत्म हो गयी, please order करवा दो"
- `mom_amount.oga` — 4-second "तीन हज़ार दो सौ चालीस रुपये"

These are *recorded by Deep with Mom* on Day 2 morning. They're the ground truth.

Tests:
- Transcribe `mom_hello.oga` → expect "नमस्ते" or "namaste" (case-insensitive substring).
- Transcribe `mom_medicine.oga` with mode='codemix' → expect substring "Telma" (English preserved) AND substring "खत्म".
- Synthesize "नमस्ते मम्मी" → returns non-empty bytes, starts with MP3 header (`b'\xff\xfb'` or `b'ID3'`).
- `rupees_to_hindi_words(3240)` == "तीन हज़ार दो सौ चालीस रुपये".
- `apply_pronunciation_overrides("Telma 40")` == "टेल्मा 40" (after seeding the dict).

### `tests/test_messaging.py` (extend)

- Mock the two-step media download with `respx`. Assert both calls carry Bearer auth.
- Mock upload_media. Assert multipart payload contains `messaging_product=whatsapp` field.

## Acceptance criteria

- [ ] Mom sends voice note "नमस्ते Saathi, कैसी हो?" → receives voice reply with same words within 6 seconds.
- [ ] Mom sends voice note "टेलमा 40 खत्म हो गयी" → receives voice reply containing "Telma" or "टेल्मा" and "खत्म".
- [ ] Mom sends voice note with amount "तीन हज़ार रुपये" → reply preserves the amount intelligibly.
- [ ] Inbound voice notes show up in `s3://saathi-media/mom/inbound/`.
- [ ] All tests green: `uv run pytest -q`.
- [ ] Latency P50 < 5s end-to-end (log it).

## Reality checks Deep should do

1. **Listen to Mom's reply herself.** Day 2 evening, play her one of Saathi's voice replies. Does she understand `vidya`'s voice? If she squints, try `anushka` or `meera`. Pick one and lock it in `config.py::TTS_VOICE`.

2. **Pronunciation audit.** Have Mom say the 5–8 medicine brand names she uses. Run them through Saaras → run the transcripts back through Bulbul. The ones that come back garbled get added to `PRONUNCIATION_OVERRIDES`. Likely candidates: Telma, Glycomet, Ecosprin, Pantop, Crocin.

3. **Confirm the 16 kHz Opus**. If Sarvam returns weird transcripts, the first thing to check is whether Meta changed the inbound audio codec (they sometimes ship variations). Inspect the actual bytes from `download_media` — first 4 bytes should be `OggS`.

## Stop conditions

- Sarvam Saaras returns garbled output for clean Hindi voice notes — try `mode='transcribe'` instead of `'codemix'`. If still garbled, the audio is likely encoded wrong; check the OggS header.
- Bulbul output won't play on WhatsApp — verify the MP3 header and that you uploaded with `mime_type="audio/mpeg"` not `"audio/mp3"`.
- Sarvam 429s repeatedly — check your free credit balance; you may have burned through it in testing. Top up.

## What NOT to do today

- Do not introduce Claude/LLM calls. Day 3.
- Do not add intent classification. Day 3.
- Do not start any executor module. Days 3–5.
- Do not add SQS, Celery, or any async queue.
- Do not over-engineer the S3 paths — `mom/inbound/<ts>.oga` is fine. No partitioning yet.

## EOD ritual

Update `docs/STATUS.md`:

```markdown
## Day 2 — done <date>

### Running
- Voice round-trip: webhook → Sarvam STT → Sarvam TTS → WhatsApp send
- S3 archive of all inbound voice notes
- P50 latency: <fill in>

### Built
- src/saathi/speech/sarvam.py — Saaras STT + Bulbul TTS
- src/saathi/storage/s3.py — voice archival
- src/saathi/messaging/whatsapp.py — media download/upload/send_audio
- src/saathi/utils/hindi.py — rupees_to_hindi_words + pronunciation overrides
- tests/fixtures/*.oga — recorded ground truth from Mom

### Locked decisions
- TTS voice: <vidya|anushka|meera>
- STT mode default: codemix

### Stubbed
- src/saathi/speech/fallback.py — Whisper backup (no implementation yet)

### Pending external
- Swiggy MCP whitelist (still waiting)
- 1mg merchant API (still waiting)
- WhatsApp templates: <approved|in review>

### Next
- Day 3: Intent classification + Claude orchestrator + first executor (medicine via 1mg/PharmEasy Playwright)
```
