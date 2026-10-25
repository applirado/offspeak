"""Gentle synthesised feedback sounds (no system beeper)."""

import functools
import io
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path

import numpy as np

RATE = 44100
THEMES = {"soft": "Soft", "cockatoo": "Cockatoo", "chime": "Chime", "click": "Click"}
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


def _mallet(freq: float, duration: float = 0.4, decay: float = 0.1) -> np.ndarray:
    """A soft marimba-like note: the overtones (at marimba ratios) die away faster than the fundamental."""
    t = np.arange(int(RATE * duration)) / RATE
    note = sum(a * np.sin(2 * np.pi * freq * ratio * t) * np.exp(-t / (decay / speed))
               for ratio, a, speed in ((1, 1.0, 1), (3.93, 0.12, 3), (9.2, 0.03, 6)))
    attack = np.minimum(1, t / 0.003)
    fade = np.ones_like(t)
    fade[-int(RATE * 0.02):] = np.linspace(1, 0, int(RATE * 0.02))
    return note * attack * fade


def _chirp(f_start: float, f_peak: float, f_end: float, duration: float) -> np.ndarray:
    """A short bird call: pitch rises to f_peak and falls to f_end, with a slight warble and a bell-shaped envelope."""
    x = np.arange(int(RATE * duration)) / (RATE * duration)
    rise = np.sin(np.pi * np.minimum(x / 0.6, 1) / 2)  # 0 -> 1 over the first 60 %
    freq = np.where(x < 0.6, f_start + (f_peak - f_start) * rise,
                    f_peak + (f_end - f_peak) * (x - 0.6) / 0.4)
    freq = freq * (1 + 0.015 * np.sin(2 * np.pi * 45 * x * duration))
    phase = 2 * np.pi * np.cumsum(freq) / RATE
    return (np.sin(phase) + 0.08 * np.sin(2 * phase)) * np.sin(np.pi * x) ** 2


def _mix(*parts: tuple[float, np.ndarray]) -> np.ndarray:
    """Overlay (start_seconds, samples) pairs."""
    length = max(int(RATE * start) + len(s) for start, s in parts)
    out = np.zeros(length)
    for start, s in parts:
        out[int(RATE * start):int(RATE * start) + len(s)] += s
    return out


def _room(samples: np.ndarray) -> np.ndarray:
    """A few faint early reflections so the sound is less dry."""
    out = np.concatenate([samples, _silence(0.05)])
    for delay, gain in ((0.017, 0.18), (0.029, 0.11), (0.043, 0.06)):
        d = int(RATE * delay)
        out[d:d + len(samples)] += gain * samples
    return out


def _samples(theme: str, event: str) -> np.ndarray:
    if theme == "soft":
        notes = {"start": ((0, 784.0), (0.07, 1046.5)), "stop": ((0, 1046.5), (0.07, 784.0)),
                 "cancel": ((0, 523.3), (0.11, 523.3))}[event]
        return _room(_mix(*((start, _mallet(f)) for start, f in notes)))
    if theme == "cockatoo":
        calls = {"start": ((0, (1700, 2500, 2200, 0.07)), (0.1, (1900, 2900, 2600, 0.08))),
                 "stop": ((0, (2600, 2700, 1700, 0.11)),),
                 "cancel": ((0, (1300, 1500, 1100, 0.06)), (0.09, (1300, 1500, 1100, 0.06)))}[event]
        return _room(_mix(*((start, _chirp(*call)) for start, call in calls)))
    if theme == "chime":
        bell = (0.25, 0.08)
        notes = {"start": (1046.5, 1318.5), "stop": (1318.5, 1046.5), "cancel": (659.3, 523.3)}[event]
        return np.concatenate([_tone([notes[0]], 0.18, 0.08, bell), _silence(0.01), _tone([notes[1]], 0.35, 0.12, bell)])
    if theme == "click":
        return {"start": _click(2400), "stop": _click(1600),
                "cancel": np.concatenate([_click(1200), _silence(0.05), _click(1200)])}[event]
    raise ValueError(f"unknown sound theme {theme!r}")


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
    if sys.platform == "darwin":
        path = Path(tempfile.gettempdir()) / f"offspeak-{theme}-{event}-{round(volume, 2)}.wav"
        if not path.exists():
            path.write_bytes(data)
        subprocess.Popen(["afplay", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    import winsound

    threading.Thread(target=winsound.PlaySound, args=(data, winsound.SND_MEMORY | winsound.SND_NODEFAULT),
                     daemon=True).start()
