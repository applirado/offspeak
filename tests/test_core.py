import json
import socket

import numpy as np
import pytest

from offspeak import netguard
from offspeak.audio import SAMPLE_RATE, resample, split_for_asr, trim_silence
from offspeak.config import Config, Mode
from offspeak.context import matches_app
from offspeak.engines import build_messages
from offspeak.history import History
from offspeak.hotkeys import Hotkey, format_shortcut, parse_shortcut
from offspeak.importer import import_superwhisper
from offspeak.textproc import apply_replacements, clean_llm_output, clean_transcript, correct_vocabulary


@pytest.mark.parametrize("text,expected", [
    ("Control+Space", Hotkey(frozenset({"ctrl"}), 0x20)),
    ("Control+Numpad0", Hotkey(frozenset({"ctrl"}), 0x60)),
    ("Control+Shift+KeyM", Hotkey(frozenset({"ctrl", "shift"}), 0x4D)),
    ("Escape", Hotkey(frozenset(), 0x1B)),
    ("alt+f9", Hotkey(frozenset({"alt"}), 0x78)),
    ("Ctrl+Digit3", Hotkey(frozenset({"ctrl"}), 0x33)),
])
def test_parse_shortcut(text, expected):
    assert parse_shortcut(text) == expected


@pytest.mark.parametrize("text", ["Control+Space", "Control+Numpad0", "Control+Shift+KeyM", "Escape",
                                  "Alt+F9", "Control+Digit3", "Shift+Win+ArrowUp", "Pause"])
def test_format_shortcut_round_trips(text):
    hk = parse_shortcut(text)
    assert format_shortcut(hk.mods, hk.vk) == text


def test_format_shortcut_unknown_key():
    assert format_shortcut(frozenset({"ctrl"}), 0xFF) is None


def test_parse_shortcut_empty_and_invalid():
    assert parse_shortcut("") is None
    with pytest.raises(ValueError):
        parse_shortcut("Control+Banana")
    with pytest.raises(ValueError):
        parse_shortcut("Control+Shift")


def test_replacements_whole_word_case_insensitive():
    reps = [{"original": "JetGPT", "with": "Chat-GPT"}, {"original": "Promz", "with": r"Prompts\1"}]
    assert apply_replacements("ask jetgpt about Promz, not JetGPTs", reps) == r"ask Chat-GPT about Prompts\1, not JetGPTs"


@pytest.mark.parametrize("text,expected", [
    ("einen MCP-Server für Databurse braucht", "einen MCP-Server für Dataverse braucht"),
    ("zu dem Dativerse-Skill", "zu dem Dataverse-Skill"),
    ("den Data verse Server", "den Dataverse Server"),
    ("im Azure DevOps Portal", "im Azure DevOps Portal"),
    ("das Team und die Daten", "das Team und die Daten"),
    ("mit Azur Def Ops", "mit Azure DevOps"),
    ("Views erstellen in Dataverse zu automatisieren", "Views erstellen in Dataverse zu automatisieren"),
    ("die Power-Platform-Skills", "die Power-Platform-Skills"),
    ("Nutzung von Cloud Code mit Plan", "Nutzung von Claude Code mit Plan"),
    ("Modelle lokal mit Ulama starten", "Modelle lokal mit Ollama starten"),
    ("lokal mit Olama", "lokal mit Ollama"),
    ("alle Alarme und eine Lama-Herde", "alle Alarme und eine Lama-Herde"),
    ("Ich habe unsere Anmeldung geprüft", "Ich habe unsere Anmeldung geprüft"),
    ("Sign in with entra ID", "Sign in with Entra ID"),
    ("before the GitHub actions run", "before the GitHub Actions run"),
    ("Convert the Yaml config", "Convert the YAML config"),
    ("Install it with NPM.", "Install it with npm."),
    ("Npm is installed.", "Npm is installed."),
    ("Run it with Lama.cpp", "Run it with llama.cpp"),
    ("Use slang chain for that", "Use LangChain for that"),
    ("Deploy the Fast API service", "Deploy the FastAPI service"),
    ("Two teams and a team lead", "Two teams and a team lead"),
])
def test_correct_vocabulary(text, expected):
    vocab = ["Dataverse", "Azure DevOps", "Teams", "Azure", "Power Platform", "Claude Code", "Ollama", "Entra ID",
             "GitHub Actions", "YAML", "npm", "llama.cpp", "LangChain", "FastAPI", "API"]
    assert correct_vocabulary(text, vocab) == expected


def test_clean_transcript_and_llm_output():
    assert clean_transcript(" [BLANK_AUDIO]  Hallo   Welt ") == "Hallo Welt"
    assert clean_llm_output("<think>hmm</think>\n<transcript>Hi there.</transcript>", "hi there") == "Hi there."
    assert clean_llm_output('"Hi."', "hi") == "Hi."


def test_build_messages_includes_context_only_when_present():
    plain = build_messages("hello", "", {}, [])
    assert "<" not in plain[0]["content"]
    assert plain[1]["content"] == "<transcript>\nhello\n</transcript>"
    rich = build_messages("hello", "Custom.", {"application": {"name": "Code", "title": "x.py"},
                                               "selection": "sel"}, ["Kubernetes"])
    sys_prompt = rich[0]["content"]
    assert sys_prompt.startswith("Custom.")
    assert "<selected_text>\nsel\n</selected_text>" in sys_prompt
    assert "Kubernetes" in sys_prompt
    assert sys_prompt.index("<selected_text>") < sys_prompt.index("<active_application>")
    # stable instructions form a shared prefix, so llama.cpp can reuse its prompt cache
    assert sys_prompt.startswith(build_messages("x", "Custom.", {}, [])[0]["content"])


def test_split_for_asr_cuts_at_quiet_point():
    audio = np.full(SAMPLE_RATE * 100, 0.5, np.float32)
    audio[SAMPLE_RATE * 35: SAMPLE_RATE * 35 + 800] = 0
    chunks = split_for_asr(audio)
    assert sum(c.size for c in chunks) == audio.size
    assert all(c.size <= SAMPLE_RATE * 40 for c in chunks)
    assert abs(chunks[0].size - SAMPLE_RATE * 35) < 800
    assert len(split_for_asr(audio[: SAMPLE_RATE * 10])) == 1


def test_matches_app():
    apps = ["openai.chatgpt-desktop_2p2nqsd0c76g0!chatgpt", "microsoft.visualstudiocode", "slack.exe"]
    assert matches_app({"name": "ChatGPT"}, apps)
    assert matches_app({"name": "Code"}, apps)
    assert matches_app({"name": "slack"}, apps)
    assert not matches_app({"name": "notepad"}, apps)
    assert not matches_app({}, apps)


def test_tray_icon_tile_shows_the_state():
    from offspeak.icons import STATE_COLORS, icon_image

    for state in ("ready", "recording", "processing", "done"):
        img = icon_image(state, 64)
        assert img.size == (64, 64)
        assert img.getpixel((0, 0))[3] == 0  # rounded corner stays transparent
        rgb = tuple(int(STATE_COLORS[state][i:i + 2], 16) for i in (1, 3, 5))
        assert all(abs(a - b) <= 2 for a, b in zip(img.getpixel((58, 6))[:3], rgb))  # plain tile, top right


def test_audio_helpers():
    assert resample(np.ones(48000, np.float32), 48000).size == SAMPLE_RATE
    assert resample(np.ones(44100, np.float32), 44100).size == SAMPLE_RATE
    audio = np.zeros(SAMPLE_RATE * 3, np.float32)
    audio[SAMPLE_RATE:SAMPLE_RATE * 2] = 0.5
    trimmed = trim_silence(audio)
    assert SAMPLE_RATE <= trimmed.size <= SAMPLE_RATE * 1.6
    assert trim_silence(np.zeros(SAMPLE_RATE, np.float32)).size == 0
    assert trim_silence(audio * 0.01).size == trimmed.size
    rng = np.random.default_rng(0)
    assert trim_silence(rng.normal(0, 0.003, SAMPLE_RATE * 2).astype(np.float32)).size == 0


def test_config_creates_default_mode(tmp_path):
    cfg = Config(tmp_path)
    assert cfg.active_mode.key == "default"
    cfg.save_mode(Mode(key="mail", name="Mail", language_model="x"))
    cfg.set_active_mode("mail")
    assert Config(tmp_path).active_mode.name == "Mail"


def test_history_add_and_search(tmp_path):
    h = History(tmp_path)
    h.add(np.zeros(1600, np.float32), {"mode": "Default", "raw_text": "hallo welt", "result": "Hallo Welt!"})
    assert len(h.recent()) == 1
    assert h.search("welt")[0]["result"] == "Hallo Welt!"
    assert h.search('quote"s') == []
    assert next(tmp_path.glob("recordings/*/Output.wav")).exists()


def test_history_never_stores_the_context(tmp_path):
    h = History(tmp_path)
    secret = {"selection": "hunter2", "clipboard": "IBAN DE00", "application": {"name": "Outlook", "title": "Re: Salary"}}
    h.add(None, {"mode": "Default", "raw_text": "hi", "result": "Hi", "app_name": "Outlook", "context": secret})
    meta = next(tmp_path.glob("recordings/*/meta.json")).read_text(encoding="utf-8")
    assert "hunter2" not in meta and "IBAN" not in meta and "Salary" not in meta
    assert json.loads(meta)["app_name"] == "Outlook"


def test_context_reads_the_selection_only_for_a_language_model_and_never_the_clipboard(monkeypatch):
    import sys

    from offspeak import context

    reads = []
    monkeypatch.setattr(context, "selected_text", lambda: reads.append("selection") or "sel")
    if sys.platform == "win32":
        from offspeak import winapi

        monkeypatch.setattr(winapi, "get_clipboard_text", lambda: pytest.fail("the clipboard must not be read"))
    plain = Mode(key="d", name="D", context_from_selection=True)
    assert context.gather(plain, {"name": "Code", "title": "x.py"}) == {"application": {"name": "Code", "title": "x.py"}}
    assert reads == []
    # modes saved by older versions may still carry "context_from_clipboard"; it is ignored
    rewriting = Mode.from_dict({"key": "m", "name": "M", "language_model": "qwen", "context_from_clipboard": True})
    assert context.gather(rewriting, {}) == {"selection": "sel"}
    assert reads == ["selection"]


def test_import_superwhisper(tmp_path, monkeypatch):
    sw = tmp_path / "sw"
    monkeypatch.setattr("offspeak.config.SUPERWHISPER_DIR", sw)
    (sw / "modes").mkdir(parents=True)
    (sw / "settings").mkdir()
    (sw / "models").mkdir()
    (sw / "models" / "ggml-small.bin").write_bytes(b"")
    (sw / "models" / "llama-3B.gguf").write_bytes(b"")
    (sw / "modes" / "default.json").write_text(json.dumps({
        "key": "default", "name": "Default", "type": "super", "voiceModelID": "sv-1", "language": "de",
        "languageModelID": "gpt-5", "prompt": "", "contextFromSelection": True, "shortcut": "Control+Numpad1"}))
    (sw / "modes" / "dictate.json").write_text(json.dumps({
        "key": "dictate", "name": "Dictate", "type": "voice", "voiceModelID": "small", "languageModelID": "gpt-5"}))
    (sw / "settings" / "settings.json").write_text(json.dumps({
        "replacements": [{"id": "1", "original": "Promz", "with": "Prompts"}], "vocabulary": ["Dataverse"]}))
    (sw / "preferences.json").write_text(json.dumps({
        "pushToTalkShortcut": "Control+Space", "toggleRecordingShortcut": "Control+Numpad0",
        "activeMode": "default", "recordingPreservationPeriod": 2592000}))
    cfg = Config(tmp_path / "lw")
    cfg.settings.models_dirs = [str(sw / "models")]
    import_superwhisper(cfg, sw)
    cfg = Config(tmp_path / "lw")
    default = cfg.modes["default"]
    assert (default.voice_model, default.language_model, default.language) == ("small", "llama-3B", "de")
    assert cfg.modes["dictate"].language_model == ""
    assert cfg.settings.replacements == [{"original": "Promz", "with": "Prompts"}]
    assert cfg.settings.vocabulary == ["Dataverse"]
    assert cfg.settings.keep_recordings_days == 30


def test_netguard_blocks_remote_but_allows_loopback():
    netguard.install()
    with socket.socket() as s, pytest.raises(netguard.NetworkBlocked):
        s.connect(("93.184.216.34", 80))
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    with server, socket.socket() as s:
        s.connect(server.getsockname())


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="Windows only")
def test_app_exe_has_own_name_and_icon(tmp_path):
    import ctypes
    import shutil
    import sys
    from pathlib import Path

    from offspeak import appexe

    exe = tmp_path / "OffSpeak.exe"
    shutil.copyfile(Path(sys.base_prefix) / "pythonw.exe", exe)
    appexe.brand(exe, Path(__file__).parents[1] / "assets" / "offspeak.ico", "1.2.3")
    version = ctypes.WinDLL("version")
    size = version.GetFileVersionInfoSizeW(str(exe), None)
    data = ctypes.create_string_buffer(size)
    assert version.GetFileVersionInfoW(str(exe), 0, size, data)
    value, length = ctypes.c_wchar_p(), ctypes.c_uint()
    assert version.VerQueryValueW(data, r"\StringFileInfo\040904B0\FileDescription", ctypes.byref(value),
                                  ctypes.byref(length))
    assert value.value == "OffSpeak"
    assert {r[0] for r in appexe._existing(exe, (appexe.RT_GROUP_ICON,))} == {appexe.RT_GROUP_ICON}
