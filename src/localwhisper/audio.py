import threading
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000


def resample(audio: np.ndarray, src_rate: int) -> np.ndarray:
    if src_rate == SAMPLE_RATE or audio.size == 0:
        return audio
    if src_rate % SAMPLE_RATE == 0:
        factor = src_rate // SAMPLE_RATE
        usable = audio.size - audio.size % factor
        return audio[:usable].reshape(-1, factor).mean(axis=1)
    duration = audio.size / src_rate
    target = np.linspace(0, duration, int(duration * SAMPLE_RATE), endpoint=False)
    return np.interp(target, np.arange(audio.size) / src_rate, audio).astype(np.float32)


def trim_silence(audio: np.ndarray, pad_s: float = 0.25) -> np.ndarray:
    frame = SAMPLE_RATE // 50
    if audio.size < frame:
        return audio[:0]
    frames = audio[: audio.size - audio.size % frame].reshape(-1, frame)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    # adaptive: quiet microphones can peak 50x below normal levels; steady room noise stays below 3x its floor
    threshold = max(0.001, 0.1 * float(np.percentile(rms, 95)), 3 * float(np.percentile(rms, 10)))
    loud = np.flatnonzero(rms > threshold)
    if loud.size == 0:
        return audio[:0]
    pad = int(pad_s * SAMPLE_RATE)
    start = max(0, loud[0] * frame - pad)
    end = min(audio.size, (loud[-1] + 1) * frame + pad)
    return audio[start:end]


def split_for_asr(audio: np.ndarray, max_s: float = 40.0, search_s: float = 10.0) -> list[np.ndarray]:
    """Split long audio into chunks of at most max_s, cutting at the quietest 20 ms frame near each limit."""
    max_len, frame = int(max_s * SAMPLE_RATE), SAMPLE_RATE // 50
    chunks, start = [], 0
    while audio.size - start > max_len:
        lo = start + max_len - int(search_s * SAMPLE_RATE)
        window = audio[lo:start + max_len]
        energy = (window[: window.size - window.size % frame].reshape(-1, frame) ** 2).mean(axis=1)
        cut = lo + int(np.argmin(energy)) * frame + frame // 2
        chunks.append(audio[start:cut])
        start = cut
    chunks.append(audio[start:])
    return chunks


def normalize(audio: np.ndarray, peak: float = 0.9) -> np.ndarray:
    m = float(np.abs(audio).max()) if audio.size else 0.0
    return audio * (peak / m) if m > 0 else audio


def save_wav(path: Path, audio: np.ndarray) -> None:
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())


def load_audio_file(path: Path) -> np.ndarray:
    import soundfile as sf

    data, rate = sf.read(str(path), dtype="float32", always_2d=True)
    return resample(data.mean(axis=1), rate)


class Recorder:
    def __init__(self):
        self._chunks: list[np.ndarray] = []
        self._stream = None
        self._rate = SAMPLE_RATE
        self._lock = threading.Lock()
        self.level = 0.0

    def start(self) -> None:
        import sounddevice as sd

        self._chunks = []
        self.level = 0.0
        try:
            self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=self._callback)
            self._rate = SAMPLE_RATE
        except sd.PortAudioError:
            rate = int(sd.query_devices(kind="input")["default_samplerate"])
            self._stream = sd.InputStream(samplerate=rate, channels=1, dtype="float32", callback=self._callback)
            self._rate = rate
        self._stream.start()

    def _callback(self, indata, _frames, _time, _status) -> None:
        mono = indata[:, 0].copy()
        with self._lock:
            self._chunks.append(mono)
        self.level = float(np.sqrt((mono ** 2).mean()))

    def stop(self) -> np.ndarray:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._lock:
            audio = np.concatenate(self._chunks) if self._chunks else np.zeros(0, np.float32)
            self._chunks = []
        self.level = 0.0
        return resample(audio, self._rate)
