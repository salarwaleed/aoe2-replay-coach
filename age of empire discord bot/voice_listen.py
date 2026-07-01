"""Voice listening module — wake-word detection and utterance capture.

Provides:
  - pcm48_stereo_to_wav16_mono(pcm) : pure PCM conversion helper
  - match_wake_word(transcript, wake) : pure wake-word extractor
  - WakeSink(AudioSink)               : records per-user PCM, flushes on silence

Discord delivers PCM at 48 000 Hz, 16-bit signed little-endian, 2 channels.
WakeSink buffers it per user in a background thread and fires on_utterance()
(async) after a silence gap, via asyncio.run_coroutine_threadsafe so the recv
thread never touches the event loop directly.
"""

from __future__ import annotations

import asyncio
import audioop
import io
import re
import threading
import time
import wave

from discord.ext import voice_recv

# ── DAVE (E2EE) disable patch ─────────────────────────────────────────────────
# discord.py 2.7.1 + davey advertises DAVE (max_dave_protocol_version=1) during
# voice IDENTIFY, which causes Discord to E2EE-encrypt every incoming audio packet
# INSIDE the xchacha20 transport layer.  discord-ext-voice-recv 0.5.2a179 has no
# DAVE decryption, so decrypted_data is a DAVE-encrypted blob and Opus raises
# "corrupted stream".  Patching this property to return 0 tells Discord we don't
# support DAVE, so it never enables the E2EE layer and decrypted_data is plain Opus.
# Voice SEND is unaffected: VoiceClient.can_encrypt also checks dave_session.ready,
# which stays False when dave_protocol_version never advances beyond 0.
from discord.voice_state import VoiceConnectionState as _VCS
_VCS.max_dave_protocol_version = property(lambda self: 0)

# ── PCM format delivered by discord-ext-voice-recv ──────────────────────────
SRC_RATE  = 48_000   # 48 kHz
SRC_WIDTH = 2        # 16-bit signed  (bytes per sample channel)
SRC_CH    = 2        # stereo

OUT_RATE  = 16_000   # Gemini STT expects 16 kHz


# ── Pure helpers (importable / unit-testable without Discord) ────────────────

def pcm48_stereo_to_wav16_mono(pcm: bytes) -> bytes:
    """Convert 48 kHz s16 stereo PCM to a 16 kHz mono WAV (bytes).

    Steps: stereo→mono mix, then rate-convert 48k→16k, then wrap as WAV.
    """
    # Mix stereo to mono (equal weight for each channel)
    mono = audioop.tomono(pcm, SRC_WIDTH, 0.5, 0.5)
    # Rate-convert 48 kHz → 16 kHz; audioop.ratecv returns (converted, state)
    converted, _ = audioop.ratecv(mono, SRC_WIDTH, 1, SRC_RATE, OUT_RATE, None)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(SRC_WIDTH)
        w.setframerate(OUT_RATE)
        w.writeframes(converted)
    return buf.getvalue()


def match_wake_word(transcript: str, wake: str = "teletron") -> str | None:
    """Check transcript for the wake word; return the query that follows it.

    Returns:
      - str  : text after the wake word (may be '' if just the wake word)
      - None : wake word not found

    Handles common variants:
      - case-insensitive
      - 'tele tron' (split form)
      - 'teletron 1' / 'teletron one' suffix after wake word (stripped)
      - leading filler punctuation/commas after name stripped
    """
    # Normalise: lowercase, collapse runs of whitespace
    text = re.sub(r'\s+', ' ', transcript.strip().lower())

    # Build a flexible regex for the wake word + optional variants.
    # Escape the wake word in case it has special chars.
    esc = re.escape(wake)
    # Also accept a space inserted in the middle (e.g. 'tele tron')
    # We split the wake word at every character boundary to allow optional spaces.
    spaced_wake = r'\s?'.join(list(esc))

    # Full pattern:  (optional junk)(wake)(optional trailing '1'/'one')(rest)
    pattern = (
        r'^(?:.*?\b)?'          # anything before (non-greedy, optional word boundary)
        r'(' + spaced_wake + r')'   # wake word (flexible spacing)
        r'(?:\s+(?:1|one))?'    # optional '1'/'one' immediately after wake word
        r'[,\.\s]*'             # optional filler punctuation/whitespace
        r'(.*?)$'               # captured remainder (query)
    )
    m = re.search(pattern, text, re.IGNORECASE)
    if m is None:
        return None  # wake word not found

    query = m.group(2).strip()
    # Strip a leading '1'/'one,' that slipped through (belt-and-suspenders)
    query = re.sub(r'^(?:1|one)[,\.\s]*', '', query, flags=re.IGNORECASE).strip()
    return query


# ── WakeSink ─────────────────────────────────────────────────────────────────

class WakeSink(voice_recv.AudioSink):
    """AudioSink that buffers PCM per user and fires on_utterance after silence.

    on_utterance: async callable(user, wav_bytes) -> None  (scheduled on loop)
    min_sec     : minimum audio duration to bother transcribing (avoids noise)
    max_sec     : maximum recording window (safety cap)
    silence_gap : seconds of silence that triggers flush
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        on_utterance,
        *,
        min_sec: float = 0.4,
        max_sec: float = 15.0,
        silence_gap: float = 0.8,
    ):
        super().__init__()
        self._loop         = loop
        self._on_utterance = on_utterance
        self._min_sec      = min_sec
        self._max_sec      = max_sec
        self._silence_gap  = silence_gap

        # Per-user state, guarded by _lock
        self._lock:       threading.Lock              = threading.Lock()
        self._buffers:    dict[int, bytearray]        = {}  # user.id → PCM buffer
        self._last_write: dict[int, float]            = {}  # user.id → timestamp

        # Background flusher thread
        self._stop_event  = threading.Event()
        self._flusher     = threading.Thread(
            target=self._flush_loop,
            name="wake-sink-flusher",
            daemon=True,
        )
        self._flusher.start()

    # ── AudioSink interface ──────────────────────────────────────────────────

    def wants_opus(self) -> bool:
        """Return False: we want decoded PCM, not raw Opus."""
        return False

    def write(self, user, data) -> None:
        """Called from the voice recv thread; just buffer PCM quickly."""
        if user is None:
            return
        pcm = data.pcm
        if not pcm:
            return

        uid = user.id
        now = time.monotonic()
        with self._lock:
            if uid not in self._buffers:
                self._buffers[uid]    = bytearray()
                self._last_write[uid] = now
            self._buffers[uid].extend(pcm)
            self._last_write[uid] = now

    def cleanup(self) -> None:
        """Signal the flusher to stop."""
        self._stop_event.set()

    # ── Internal flusher ────────────────────────────────────────────────────

    def _flush_loop(self) -> None:
        """Background thread: every 200 ms check for users who went silent."""
        while not self._stop_event.is_set():
            self._stop_event.wait(0.2)
            if self._stop_event.is_set():
                break
            self._check_buffers()

    def _check_buffers(self) -> None:
        now = time.monotonic()
        to_flush: list[tuple] = []

        with self._lock:
            for uid, last_t in list(self._last_write.items()):
                if now - last_t >= self._silence_gap:
                    buf = self._buffers.pop(uid, None)
                    self._last_write.pop(uid, None)
                    if buf:
                        to_flush.append((uid, bytes(buf)))

        # Process outside the lock so write() can proceed
        for uid, pcm in to_flush:
            self._maybe_fire(uid, pcm)

    def _maybe_fire(self, uid: int, pcm: bytes) -> None:
        """Convert PCM to WAV and fire on_utterance if duration is in range."""
        # Duration in seconds: bytes / (sample_rate * bytes_per_sample * channels)
        duration = len(pcm) / (SRC_RATE * SRC_WIDTH * SRC_CH)
        if duration < self._min_sec or duration > self._max_sec:
            return

        try:
            wav = pcm48_stereo_to_wav16_mono(pcm)
        except Exception:
            return  # conversion error — skip silently

        # Retrieve the user object from the voice_client (best-effort)
        user = self._get_user(uid)
        if user is None:
            return  # can't identify who spoke

        asyncio.run_coroutine_threadsafe(
            self._on_utterance(user, wav),
            self._loop,
        )

    def _get_user(self, uid: int):
        """Try to look up the Member/User object from the attached voice client."""
        try:
            vc = self.voice_client
            if vc is None:
                return None
            # VoiceRecvClient has access to the guild
            member = vc.guild.get_member(uid)
            if member:
                return member
            # Fallback: discord.py client cache
            client = vc.client
            if client:
                return client.get_user(uid)
        except Exception:
            pass
        return None
