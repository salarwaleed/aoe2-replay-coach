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
import logging
import re
import threading
import time
import wave

from discord.ext import voice_recv

# ── DAVE (E2EE) decryption monkeypatch ───────────────────────────────────────
#
# Background
# ----------
# Discord enforces DAVE end-to-end encryption on all voice calls since
# 2026-03-02 (voice close code 4017 if a client refuses DAVE).  The bot is a
# full DAVE MLS participant: discord.py builds a davey.DaveSession and joins
# the MLS group, so it holds all current media keys.
#
# discord-ext-voice-recv (0.5.2a179) handles the *transport* layer correctly
# (xchacha20/xsalsa decrypt), but leaves the DAVE (SFrame/MLS) layer in place.
# PacketDecoder._decode_packet therefore feeds a still-DAVE-encrypted blob to
# Opus.decode(), which crashes with "OpusError: corrupted stream".
#
# The fix
# -------
# We monkey-patch PacketDecoder._decode_packet so that, just before the Opus
# decode call, the packet's decrypted_data is DAVE-decrypted via the live
# DaveSession.  The patched method:
#
#   1. Resolves the DaveSession from the VoiceRecvClient._connection attribute.
#   2. Looks up the sender user_id via VoiceRecvClient._ssrc_to_id[self.ssrc].
#   3. Calls dave_session.decrypt(user_id, MediaType.audio, packet.decrypted_data).
#   4. Replaces packet.decrypted_data with the plain Opus bytes in-place.
#   5. Falls through to the normal Opus decode.
#
# All failure paths (missing session, unknown ssrc, decrypt error) are guarded
# — the original (still-DAVE-encrypted) data is passed through so the existing
# OpusError is raised rather than a new crash.  This means the bot degrades
# gracefully and does not crash if DAVE is unavailable or the session is not yet
# ready.
#
# Object graph (confirmed from source inspection):
#   sink.voice_client                   → VoiceRecvClient
#   voice_client._connection            → VoiceConnectionState
#   voice_client._connection.dave_session → davey.DaveSession  (or None)
#   voice_client._ssrc_to_id[ssrc]      → sender user_id (int)

_dave_log = logging.getLogger(__name__ + ".dave_patch")


def _apply_dave_decrypt_patch() -> None:
    """Monkey-patch PacketDecoder._decode_packet to DAVE-decrypt before Opus.

    Safe to call multiple times — idempotent guard via _DAVE_PATCHED flag.
    No-ops cleanly if davey is not importable.
    """
    try:
        import davey as _davey
    except ImportError:
        _dave_log.warning("davey not importable; DAVE decrypt patch skipped")
        return

    from discord.ext.voice_recv.opus import PacketDecoder

    # Idempotency guard
    if getattr(PacketDecoder, "_DAVE_PATCHED", False):
        return

    _MediaType = _davey.MediaType
    _orig_decode_packet = PacketDecoder._decode_packet

    def _dave_decode_packet(self, packet):
        """Patched _decode_packet: DAVE-decrypt before Opus decode."""
        # Only intercept real packets (not FakePackets which have no audio)
        if packet:
            dave_session = None
            try:
                vc = self.sink.voice_client
                conn = getattr(vc, "_connection", None)
                if conn is not None:
                    dave_session = getattr(conn, "dave_session", None)
            except Exception:
                pass  # belt-and-suspenders; never crash here

            if dave_session is not None and dave_session.ready:
                user_id = None
                try:
                    user_id = vc._ssrc_to_id.get(self.ssrc)
                except Exception:
                    pass

                if user_id is not None:
                    try:
                        plain_opus = dave_session.decrypt(
                            user_id, _MediaType.audio, packet.decrypted_data
                        )
                        packet.decrypted_data = plain_opus
                        _dave_log.debug(
                            "DAVE decrypt OK: ssrc=%s uid=%s len=%s→%s",
                            self.ssrc, user_id,
                            len(packet.decrypted_data), len(plain_opus),
                        )
                    except Exception as exc:
                        # Decrypt failure: leave data as-is.  Opus will raise
                        # OpusError which voice_recv handles gracefully.
                        _dave_log.debug(
                            "DAVE decrypt failed: ssrc=%s uid=%s err=%r",
                            self.ssrc, user_id, exc,
                        )
                else:
                    _dave_log.debug(
                        "DAVE decrypt skipped: ssrc=%s not yet in ssrc_to_id",
                        self.ssrc,
                    )
            # else: session not ready / not present → passthrough (unmodified)

        return _orig_decode_packet(self, packet)

    PacketDecoder._decode_packet = _dave_decode_packet
    PacketDecoder._DAVE_PATCHED = True
    _dave_log.info("DAVE decrypt patch applied to PacketDecoder._decode_packet")


# Apply the patch at import time so it's active before any VoiceRecvClient is
# created.  This is safe: the patch only wraps a method; no network or Discord
# state is touched here.
_apply_dave_decrypt_patch()

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
