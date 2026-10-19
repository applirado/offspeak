"""Gentle synthesised feedback sounds (no system beeper)."""

import functools
import io
import threading
import wave
import winsound

import numpy as np

RATE = 44100
THEMES = {"soft": "Soft", "chime": "Chime", "click": "Click"}
EVENTS = ("start", "stop", "cancel")


def _tone(freqs: list[float], duration: float, decay: float, harmonics: tuple[float, ...] = ()) -> np.ndarray:
    """A tone gliding through freqs, with a short fade-in and exponential decay to avoid clicks."""
    n = int(RATE * duration)
    t = np.arange(n) / RATE
    freq = np.interp(t, np.linspace(0, duration, len(freqs)), freqs)
    phase = 2 * np.pi * np.cumsum(freq) / RATE
    wave_ = np.sin(phase) + sum(a * np.sin((i + 2) * phase) for i, a in enumerate(harmonics))
    envelope = np.minimum(1, t / 0.006) * np.exp(-t / decay)
    envelope[-int(RATE * 0.01):] *= np.linspace(1, 0, int(RATE * 0.01))
    return wave_ * envelope


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(RATE * seconds))


def _click(freq: float) -> np.ndarray:
    rng = np.random.default_rng(int(freq))
    n = int(RATE * 0.018)
    t = np.arange(n) / RATE
    tick = rng.normal(0, 0.4, n) * np.exp(-t / 0.002) + np.sin(2 * np.pi * freq * t) * np.exp(-t / 0.004)
    return tick


def _samples(theme: str, event: str) -> np.ndarray:
    if theme == "chime":
        bell = (0.25, 0.08)
        notes = {"start": (1046.5, 1318.5), "stop": (1318.5, 1046.5), "cancel": (659.3, 523.3)}[event]
        return np.concatenate([_tone([notes[0]], 0.18, 0.08, bell), _silence(0.01), _tone([notes[1]], 0.35, 0.12, bell)])
    if theme == "click":
        return {"start": _click(2400), "stop": _click(1600),
                "cancel": np.concatenate([_click(1200), _silence(0.05), _click(1200)])}[event]
    glide = {"start": [620, 880], "stop": [880, 620], "cancel": [440, 330]}[event]
    return _tone(glide, 0.12, 0.05, (0.15,))


@functools.lru_cache(maxsize=64)
def wav_bytes(theme: str, event: str, volume: float) -> bytes:
    samples = _samples(theme, event)
    samples = samples / max(1e-9, float(np.abs(samples).max())) * 0.4 * max(0.0, min(1.0, volume))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((samples * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def play(theme: str, event: str, volume: float) -> None:
    """Fire and forget; SND_MEMORY cannot be combined with SND_ASYNC, so play on a thread."""
    if volume <= 0:
        return
    data = wav_bytes(theme if theme in THEMES else "soft", event, round(volume, 2))
    threading.Thread(target=winsound.PlaySound, args=(data, winsound.SND_MEMORY | winsound.SND_NODEFAULT),
                     daemon=True).start()
