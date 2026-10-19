import threading
from pathlib import Path

import numpy as np

from localwhisper.audio import SAMPLE_RATE, split_for_asr
from localwhisper.config import DEFAULT_PROMPT
from localwhisper.textproc import clean_llm_output, clean_transcript

CONTEXT_LIMIT = 1000


class ParakeetEngine:
    """NVIDIA Parakeet TDT (ONNX, int8) via onnx-asr: multilingual, punctuated, several times faster than whisper on CPU."""

    def __init__(self, threads: int):
        self.threads = threads
        self._model = None
        self._path: Path | None = None
        self._lock = threading.Lock()

    def load(self, path: Path):
        import onnx_asr
        import onnxruntime as ort

        with self._lock:
            if self._path != path:
                self._model = None
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = self.threads
                quantization = "int8" if any(path.glob("*.int8.onnx")) else None
                self._model = onnx_asr.load_model(f"nemo-{path.name}", path, quantization=quantization,
                                                  sess_options=opts)
                self._path = path
            return self._model

    def transcribe(self, path: Path, audio: np.ndarray) -> str:
        model = self.load(path)
        with self._lock:
            texts = [model.recognize(chunk.astype(np.float32), sample_rate=SAMPLE_RATE)
                     for chunk in split_for_asr(audio)]
        return clean_transcript(" ".join(texts))


class WhisperEngine:
    def __init__(self, threads: int):
        self.threads = threads
        self._model = None
        self._path: Path | None = None
        self._lock = threading.Lock()

    def load(self, path: Path):
        from pywhispercpp.model import Model

        with self._lock:
            if self._path != path:
                self._model = None
                self._model = Model(str(path), n_threads=self.threads, redirect_whispercpp_logs_to=None,
                                    print_progress=False, print_realtime=False)
                self._path = path
            return self._model

    def transcribe(self, path: Path, audio: np.ndarray, language: str, translate: bool,
                   vocabulary: list[str]) -> str:
        model = self.load(path)
        with self._lock:
            segments = model.transcribe(
                audio.astype(np.float32),
                language=language or "auto",
                translate=translate,
                initial_prompt=", ".join(vocabulary),
                no_context=True,
                suppress_blank=True,
            )
        return clean_transcript(" ".join(s.text for s in segments))


def build_messages(transcript: str, prompt: str, context: dict, vocabulary: list[str]) -> list[dict]:
    # Ordered from most to least stable so llama.cpp can reuse the cached prompt prefix between dictations.
    system = (prompt or DEFAULT_PROMPT).strip() + (
        "\n\nAny background context below is only for spelling names and technical terms correctly. "
        "Never copy it into your output, unless the transcript explicitly asks you to transform it "
        '(for example "translate this" or "make this more formal"); then output the transformed text.'
    )
    parts = []
    if vocabulary:
        parts.append(f"<vocabulary>{', '.join(vocabulary)}</vocabulary>")
    for key, tag in (("clipboard", "clipboard"), ("selection", "selected_text")):
        if value := (context.get(key) or "").strip():
            parts.append(f"<{tag}>\n{value[:CONTEXT_LIMIT]}\n</{tag}>")
    if app := context.get("application"):
        parts.append(f"<active_application>{app.get('name', '')} - {app.get('title', '')}</active_application>")
    if parts:
        system += "\n\n" + "\n".join(parts)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"<transcript>\n{transcript}\n</transcript>"},
    ]


class LlamaEngine:
    def __init__(self, threads: int, context_size: int):
        self.threads = threads
        self.context_size = context_size
        self._model = None
        self._path: Path | None = None
        self._lock = threading.Lock()

    def load(self, path: Path):
        from llama_cpp import Llama

        with self._lock:
            if self._path != path:
                self._model = None
                self._model = Llama(str(path), n_ctx=self.context_size, n_threads=self.threads, verbose=False)
                self._path = path
                # Evaluate the fixed instructions once so the first dictation hits a warm prompt cache.
                self._model.create_chat_completion(messages=build_messages("", "", {}, []), max_tokens=1)
            return self._model

    def rewrite(self, path: Path, transcript: str, prompt: str, context: dict, vocabulary: list[str]) -> str:
        model = self.load(path)
        messages = build_messages(transcript, prompt, context, vocabulary)
        with self._lock:
            result = model.create_chat_completion(
                messages=messages,
                temperature=0.0,
                max_tokens=max(256, len(transcript) // 2 + 256),
            )
        output = clean_llm_output(result["choices"][0]["message"]["content"] or "", transcript)
        return output or transcript
