import urllib.request
from pathlib import Path

WHISPER_MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin"
PARAKEET_MODELS = ("parakeet-tdt-0.6b-v3", "parakeet-tdt-0.6b-v2")
VOICE_PREFERENCE = ["parakeet-tdt-0.6b-v3", "large-v3-turbo", "large-v3-turbo-q5_0", "medium", "small", "base", "tiny"]


def voice_models(dirs: list[Path]) -> dict[str, Path]:
    """whisper.cpp models are single ggml-*.bin files; Parakeet models are folders of ONNX files."""
    found = {}
    for d in dirs:
        for p in sorted(d.glob("ggml-*.bin")):
            found.setdefault(p.stem.removeprefix("ggml-"), p)
        for name in PARAKEET_MODELS:
            if any((d / name).glob("*.onnx")):
                found.setdefault(name, d / name)
    return found


def download_parakeet_model(name: str, target_dir: Path) -> Path:
    import onnx_asr

    target = target_dir / name
    onnx_asr.load_model(f"nemo-{name}", target, quantization="int8")
    return target


def language_models(dirs: list[Path]) -> dict[str, Path]:
    found = {}
    for d in dirs:
        for p in sorted(d.glob("*.gguf")):
            found.setdefault(p.stem, p)
    return found


def resolve(model_id: str, available: dict[str, Path]) -> Path:
    if model_id in available:
        return available[model_id]
    candidate = Path(model_id)
    if candidate.is_file():
        return candidate
    names = ", ".join(sorted(available)) or "none"
    raise FileNotFoundError(f"Model '{model_id}' not found locally. Available: {names}")


def best_voice_model(available: dict[str, Path]) -> str | None:
    for name in VOICE_PREFERENCE:
        if name in available:
            return name
    return next(iter(available), None)


def download_whisper_model(name: str, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"ggml-{name}.bin"
    tmp = target.with_suffix(".part")
    with urllib.request.urlopen(WHISPER_MODEL_URL.format(name=name)) as resp, open(tmp, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r{done * 100 // total:3d}%  {done >> 20} / {total >> 20} MB", end="", flush=True)
    print()
    tmp.replace(target)
    return target
