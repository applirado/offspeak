import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")


def test_clipboard_is_put_back_after_pasting():
    from offspeak import macapi

    macapi.set_clipboard_text("what the user copied")
    snapshot = macapi.snapshot_clipboard()
    ours = macapi.set_clipboard_text("dictated text", transient=True)
    assert macapi.clipboard_sequence() == ours
    macapi.restore_clipboard(snapshot)
    import AppKit

    pb = AppKit.NSPasteboard.generalPasteboard()
    assert pb.stringForType_(AppKit.NSPasteboardTypeString) == "what the user copied"
    assert macapi.TRANSIENT_TYPE not in (pb.types() or [])


def test_option_space_is_push_to_talk_and_never_reaches_the_app():
    import Quartz

    from offspeak.machotkeys import KEY_ESCAPE, KEY_SPACE, MacHotkeys

    events, recording = [], [False]
    hk = MacHotkeys(lambda action, phase: events.append((action, phase)), lambda: recording[0])

    def key(code, down, flags=0):
        event = Quartz.CGEventCreateKeyboardEvent(None, code, down)
        Quartz.CGEventSetFlags(event, flags)
        return event

    alt = Quartz.kCGEventFlagMaskAlternate
    assert hk._intercept(Quartz.kCGEventKeyDown, key(KEY_SPACE, True, alt)) is None
    assert hk._intercept(Quartz.kCGEventKeyDown, key(KEY_SPACE, True, alt)) is None  # key repeat
    assert hk._intercept(Quartz.kCGEventKeyUp, key(KEY_SPACE, False)) is None  # Option already let go
    assert events == [("ptt", "down"), ("ptt", "up")]

    plain = key(KEY_SPACE, True)
    assert hk._intercept(Quartz.kCGEventKeyDown, plain) is plain
    cmd_alt = key(KEY_SPACE, True, alt | Quartz.kCGEventFlagMaskCommand)
    assert hk._intercept(Quartz.kCGEventKeyDown, cmd_alt) is cmd_alt

    escape = key(KEY_ESCAPE, True)
    assert hk._intercept(Quartz.kCGEventKeyDown, escape) is escape  # not recording: Esc is the app's
    recording[0] = True
    assert hk._intercept(Quartz.kCGEventKeyDown, key(KEY_ESCAPE, True)) is None
    assert events[-1] == ("cancel", "down")


def test_autostart_opens_the_app_at_login(tmp_path, monkeypatch):
    from offspeak import macapi

    monkeypatch.setattr(macapi, "LAUNCH_AGENT", tmp_path / "com.applirado.offspeak.plist")
    monkeypatch.setenv("OFFSPEAK_APP", "/Users/test/Applications/OffSpeak.app")
    assert macapi.get_autostart() is None
    macapi.set_autostart(True)
    assert macapi.get_autostart() == "/usr/bin/open -a /Users/test/Applications/OffSpeak.app"
    macapi.set_autostart(False)
    assert macapi.get_autostart() is None


def test_settings_window_opens_and_saves(tmp_path):
    import tkinter as tk

    from offspeak.config import Config
    from offspeak.settings_ui import SettingsWindow

    config = Config(tmp_path)
    root = tk.Tk()
    root.withdraw()
    saved = []
    window = SettingsWindow(root, config.settings, config.modes, "en", on_save=saved.append)
    root.update()
    tabs = [label.cget("text") for label, _line in window._tabs]
    assert "Shortcuts" not in tabs and "Vocabulary" in tabs  # the preview's shortcut is fixed
    window.vocabulary.append("Dataverse")
    window.save()
    assert "Dataverse" in saved[0]["vocabulary"]
    window.win.destroy()
    root.destroy()
