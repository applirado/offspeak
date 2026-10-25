import argparse
import json
import os
import sys
from pathlib import Path

from offspeak.config import DATA_DIR, Config


def cmd_run(_args) -> None:
    from offspeak import winapi
    from offspeak.app import run_app

    if not winapi.acquire_single_instance("Offspeak.SingleInstance"):
        print("Offspeak is already running.", file=sys.stderr)
        return
    run_app()


def cmd_transcribe(args) -> None:
    from offspeak import netguard
    from offspeak.audio import load_audio_file
    from offspeak.pipeline import Pipeline

    netguard.install()
    config = Config()
    mode = config.modes[args.mode] if args.mode else config.active_mode
    if args.no_llm:
        mode.language_model = ""
    result = Pipeline(config.settings).run(load_audio_file(Path(args.file)), mode, {})
    if result is None:
        print("(no speech detected)", file=sys.stderr)
        return
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(result["result"])


def cmd_history(args) -> None:
    from offspeak.history import History

    h = History(DATA_DIR)
    rows = h.search(args.query, args.limit) if args.query else h.recent(args.limit)
    for r in reversed(rows):
        print(f"[{r['datetime']}] ({r['mode']}, {r['duration_ms'] / 1000:.1f}s) {r['result']}")


def cmd_models(_args) -> None:
    from offspeak import models

    def size_mb(p: Path) -> int:
        return (sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else p.stat().st_size) >> 20

    dirs = Config().settings.model_dirs()
    print("Model folders:\n  " + "\n  ".join(str(d) for d in dirs))
    print("Voice models (Parakeet / whisper.cpp):")
    for name, p in models.voice_models(dirs).items():
        print(f"  {name:24} {size_mb(p):6} MB  {p}")
    print("Language models (GGUF):")
    for name, p in models.language_models(dirs).items():
        print(f"  {name:24} {size_mb(p):6} MB  {p}")


def cmd_download(args) -> None:
    from offspeak.models import PARAKEET_MODELS, download_parakeet_model, download_whisper_model

    download = download_parakeet_model if args.name in PARAKEET_MODELS else download_whisper_model
    print(download(args.name, DATA_DIR / "models"))


def cmd_import(_args) -> None:
    from offspeak.importer import import_superwhisper

    for line in import_superwhisper(Config()):
        print(line)


def cmd_autostart(args) -> None:
    from offspeak import winapi

    if args.state:
        winapi.set_autostart(args.state == "on")
    command = winapi.get_autostart()
    print(f"Autostart is on: {command}" if command else "Autostart is off.")


def cmd_create_exe(args) -> None:
    from offspeak import appexe

    print(appexe.create(Path(args.icon) if args.icon else None))


def main() -> None:
    # pythonw / offspeakw has no console, so these are None; libraries such as pywhispercpp call flush() on them
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w"))
    parser = argparse.ArgumentParser(prog="offspeak", description="Offline voice dictation.")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="start the tray app (default)").set_defaults(func=cmd_run)
    p = sub.add_parser("transcribe", help="transcribe an audio file")
    p.add_argument("file")
    p.add_argument("--mode", help="mode key (default: active mode)")
    p.add_argument("--no-llm", action="store_true", help="skip language-model clean-up")
    p.add_argument("--json", action="store_true", help="print full result as JSON")
    p.set_defaults(func=cmd_transcribe)
    p = sub.add_parser("history", help="show or search past dictations")
    p.add_argument("query", nargs="?")
    p.add_argument("-n", "--limit", type=int, default=20)
    p.set_defaults(func=cmd_history)
    sub.add_parser("models", help="list local models").set_defaults(func=cmd_models)
    p = sub.add_parser("download-model", help="download a voice model (parakeet-tdt-0.6b-v3, or whisper.cpp: small, large-v3-turbo, ...)")
    p.add_argument("name")
    p.set_defaults(func=cmd_download)
    sub.add_parser("import-superwhisper", help="import modes and settings from Superwhisper").set_defaults(func=cmd_import)
    p = sub.add_parser("autostart", help="start Offspeak when you sign in to Windows (on/off; no argument shows the state)")
    p.add_argument("state", nargs="?", choices=("on", "off"))
    p.set_defaults(func=cmd_autostart)
    p = sub.add_parser("create-exe", help="create OffSpeak.exe, which runs the tray app under its own name (used by setup)")
    p.add_argument("--icon", help=".ico file for the executable")
    p.set_defaults(func=cmd_create_exe)
    args = parser.parse_args()
    (getattr(args, "func", None) or cmd_run)(args)
