import time

import numpy as np

from offspeak import models
from offspeak.audio import SAMPLE_RATE, normalize, trim_silence
from offspeak.config import Mode, Settings
from offspeak.engines import LlamaEngine, ParakeetEngine, WhisperEngine
from offspeak.textproc import apply_replacements, correct_vocabulary, similarity, word_count

MIN_PROOFREAD_SIMILARITY = 0.6


class Pipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.whisper = WhisperEngine(settings.thread_count())
        self.parakeet = ParakeetEngine(settings.thread_count())
        self.llama = LlamaEngine(settings.thread_count(), settings.llm_context_size)

    def voice_path(self, mode: Mode):
        return models.resolve(mode.voice_model, models.voice_models(self.settings.model_dirs()))

    def llm_path(self, mode: Mode):
        if not mode.language_model:
            return None
        return models.resolve(mode.language_model, models.language_models(self.settings.model_dirs()))

    def preload(self, mode: Mode) -> None:
        voice = self.voice_path(mode)
        (self.parakeet if voice.is_dir() else self.whisper).load(voice)
        if (path := self.llm_path(mode)) is not None:
            self.llama.load(path)

    def transcribe(self, audio: np.ndarray, mode: Mode) -> str:
        voice = self.voice_path(mode)
        if not voice.is_dir():
            return self.whisper.transcribe(voice, audio, mode.language, mode.translate_to_english,
                                           self.settings.vocabulary)
        if mode.translate_to_english:
            raise ValueError(f"{mode.voice_model} cannot translate; choose a whisper model for mode '{mode.name}'")
        return self.parakeet.transcribe(voice, audio)

    def run(self, audio: np.ndarray, mode: Mode, context: dict) -> dict | None:
        """Returns None when the audio holds no speech."""
        s = self.settings
        speech = trim_silence(audio)
        if speech.size < SAMPLE_RATE * s.min_recording_ms / 1000:
            return None
        t0 = time.perf_counter()
        raw = self.transcribe(normalize(speech), mode)
        stt_ms = int((time.perf_counter() - t0) * 1000)
        if not raw:
            return None
        raw = apply_replacements(correct_vocabulary(raw, s.vocabulary), s.replacements)
        result, llm_ms, llm_rejected = raw, 0, False
        if (llm := self.llm_path(mode)) is not None:
            t1 = time.perf_counter()
            result = apply_replacements(self.llama.rewrite(llm, raw, mode.prompt, context, s.vocabulary),
                                        s.replacements)
            llm_ms = int((time.perf_counter() - t1) * 1000)
            # Plain proofreading must stay close to what was said; small models sometimes answer or rewrite.
            if not mode.prompt and not context.get("selection") and similarity(raw, result) < MIN_PROOFREAD_SIMILARITY:
                result, llm_rejected = raw, True
        return {
            "mode": mode.name,
            "voice_model": mode.voice_model,
            "language_model": mode.language_model,
            "language": mode.language,
            "duration_ms": int(audio.size * 1000 / SAMPLE_RATE),
            "stt_ms": stt_ms,
            "llm_ms": llm_ms,
            "llm_rejected": llm_rejected,
            "raw_text": raw,
            "result": result,
            "raw_word_count": word_count(raw),
            "word_count": word_count(result),
            "app_name": (context.get("application") or {}).get("name", ""),
            "context": context,
        }
