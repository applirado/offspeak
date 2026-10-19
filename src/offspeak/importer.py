"""Import modes, replacements, vocabulary and shortcuts from an existing Superwhisper installation."""

import json
from pathlib import Path

from offspeak import models
from offspeak.config import SUPERWHISPER_DIR, Config, Mode


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def import_superwhisper(config: Config, source: Path = SUPERWHISPER_DIR) -> list[str]:
    if not source.is_dir():
        raise FileNotFoundError(f"No Superwhisper data found at {source}")
    report = []
    dirs = config.settings.model_dirs()
    voices, llms = models.voice_models(dirs), models.language_models(dirs)
    fallback_voice = models.best_voice_model(voices) or "small"
    fallback_llm = next(iter(llms), "")

    for path in sorted((source / "modes").glob("*.json")):
        sw = _read(path)
        voice = sw.get("voiceModelID") or ""
        if voice not in voices:
            report.append(f"mode '{sw.get('name')}': voice model '{voice}' is cloud/missing -> {fallback_voice}")
            voice = fallback_voice
        llm = sw.get("languageModelID") or ""
        if sw.get("type") == "voice":
            llm = ""
        elif llm and llm not in llms:
            report.append(f"mode '{sw.get('name')}': language model '{llm}' is cloud/missing -> {fallback_llm or 'none'}")
            llm = fallback_llm
        mode = Mode(
            key=sw.get("key") or path.stem,
            name=sw.get("name") or path.stem,
            voice_model=voice,
            language=sw.get("language") or "auto",
            translate_to_english=bool(sw.get("translateToEnglish")),
            language_model=llm,
            prompt=sw.get("prompt") or "",
            context_from_clipboard=bool(sw.get("contextFromClipboard")),
            context_from_selection=bool(sw.get("contextFromSelection")),
            context_from_active_app=bool(sw.get("contextFromActiveApplication", True)),
            activation_apps=list(sw.get("activationApps") or []),
            shortcut=sw.get("shortcut") or "",
            auto_paste=sw.get("autoPaste"),
        )
        config.save_mode(mode)
        report.append(f"imported mode '{mode.name}' ({mode.voice_model} / {mode.language_model or 'no LLM'})")

    sw_settings = _read(source / "settings" / "settings.json")
    s = config.settings
    s.replacements = [{"original": r["original"], "with": r["with"]}
                      for r in sw_settings.get("replacements", []) if r.get("original")]
    s.vocabulary = [v if isinstance(v, str) else v.get("word", "") for v in sw_settings.get("vocabulary", [])]
    s.vocabulary = [v for v in s.vocabulary if v]
    report.append(f"imported {len(s.replacements)} replacements, {len(s.vocabulary)} vocabulary words")

    prefs = _read(source / "preferences.json")
    s.toggle_shortcut = prefs.get("toggleRecordingShortcut", s.toggle_shortcut)
    s.push_to_talk_shortcut = prefs.get("pushToTalkShortcut", s.push_to_talk_shortcut)
    s.cancel_shortcut = prefs.get("cancelRecordingShortcut", s.cancel_shortcut)
    s.auto_paste = prefs.get("autoPasteEnabled", s.auto_paste)
    s.restore_clipboard_delay = prefs.get("restoreClipboardTimeDelay", s.restore_clipboard_delay)
    s.sound_effects = prefs.get("enableSoundEffects", s.sound_effects)
    if period := prefs.get("recordingPreservationPeriod"):
        s.keep_recordings_days = max(1, int(period) // 86400)
    if prefs.get("activeMode") in config.modes:
        s.active_mode = prefs["activeMode"]
    config.save_settings()
    report.append("imported shortcuts and preferences")
    return report
