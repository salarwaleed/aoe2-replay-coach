"""PCM conversion used before sending captured voice to cloud STT:
48 kHz 16-bit stereo -> 16 kHz mono WAV."""
import io
import wave

import voice_listen as vl


def test_pcm48_stereo_to_wav16_mono_produces_valid_wav():
    # 0.5 s of 48 kHz stereo silence: 24000 frames * 2 channels * 2 bytes.
    pcm = b"\x00\x00" * 48000  # 24000 stereo frames
    wav = vl.pcm48_stereo_to_wav16_mono(pcm)

    assert wav[:4] == b"RIFF"
    with wave.open(io.BytesIO(wav), "rb") as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        # ~0.5 s at 16 kHz, allowing a small resampler edge tolerance.
        assert 7500 <= w.getnframes() <= 8500


def test_empty_pcm_still_yields_a_readable_wav_header():
    wav = vl.pcm48_stereo_to_wav16_mono(b"")
    assert wav[:4] == b"RIFF"
    with wave.open(io.BytesIO(wav), "rb") as w:
        assert w.getnframes() == 0
