import io
import wave

import pytest

from offspeak import sounds


@pytest.mark.parametrize("theme", list(sounds.THEMES))
@pytest.mark.parametrize("event", sounds.EVENTS)
def test_sounds_are_short_quiet_wavs(theme, event):
    data = sounds.wav_bytes(theme, event, 1.0)
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, sounds.RATE)
        frames = w.readframes(w.getnframes())
        assert 0 < w.getnframes() / sounds.RATE < 0.8
    peak = max(abs(int.from_bytes(frames[i:i + 2], "little", signed=True)) for i in range(0, len(frames), 2))
    assert 0.35 * 32767 < peak <= 0.41 * 32767  # never full scale


def test_volume_scales_amplitude():
    loud, quiet = sounds.wav_bytes("soft", "start", 1.0), sounds.wav_bytes("soft", "start", 0.25)
    peak = lambda d: max(abs(int.from_bytes(d[i:i + 2], "little", signed=True)) for i in range(44, len(d), 2))  # noqa: E731
    assert abs(peak(quiet) / peak(loud) - 0.25) < 0.01
