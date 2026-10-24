import logging
import os
import queue
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pystray

from offspeak import context as ctx
from offspeak import netguard, sounds, winapi
from offspeak.audio import SAMPLE_RATE, Recorder, load_audio_file, normalize, trim_silence
from offspeak.config import Config, Mode
from offspeak.settings_ui import SettingsWindow
from offspeak.history import History
from offspeak.hotkeys import Binding, HotkeyManager, parse_shortcut
from offspeak.pipeline import Pipeline
from offspeak.ui import Overlay, tray_image

log = logging.getLogger("offspeak")


def play_sound(settings, event: str) -> None:
    if settings.sound_effects:
        sounds.play(settings.sound_theme, event, settings.sound_volume)


class App:
    def __init__(self, config: Config):
        self.config = config
        self.history = History(config.root)
        self.pipeline = Pipeline(config.settings)
        self.recorder = Recorder()
        self.state = "ready"
        self.ptt = False
        self.mode: Mode = config.active_mode
        self.app_info: dict = {}
        self.context_future = None
        self.events: queue.Queue = queue.Queue()
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.ctx_worker = ThreadPoolExecutor(max_workers=1)
        self.hotkeys = HotkeyManager(lambda action, phase: self.events.put((action, phase)))
        self.overlay = Overlay(lambda: self.recorder.level)
        self.tray = pystray.Icon("Offspeak", tray_image("ready"), "Offspeak", self._menu())
        self.last_result = ""
        self.settings_window: SettingsWindow | None = None

    # -- lifecycle -----------------------------------------------------------
    def run(self) -> None:
        self._bind_hotkeys()
        self.hotkeys.start()
        threading.Thread(target=self._event_loop, daemon=True).start()
        self.tray.run_detached()
        self.history.cleanup_audio(self.config.settings.keep_recordings_days)
        self.worker.submit(self._preload, self.config.active_mode)
        s = self.config.settings
        hint = f"Hold {s.push_to_talk_shortcut} to dictate, or press {s.toggle_shortcut} to start/stop."
        print(f"Offspeak is running in the system tray (mode: {self.config.active_mode.name}).\n{hint}\n"
              "Quit via the tray icon menu or Ctrl+C here.", flush=True)
        self.overlay.show("ready", f"Ready - hold {s.push_to_talk_shortcut}", hide_after_ms=3000)
        signal.signal(signal.SIGINT, lambda *_: self._quit())
        self.overlay.mainloop()
        self.hotkeys.stop()
        self.tray.stop()

    def _preload(self, mode: Mode) -> None:
        try:
            self.pipeline.preload(mode)
        except Exception as e:
            log.exception("preload failed")
            self._notify(f"Model could not be loaded: {e}")

    def _bind_hotkeys(self) -> None:
        s = self.config.settings
        bindings = []
        for shortcut, action, enabled in (
            (s.toggle_shortcut, "toggle", None),
            (s.push_to_talk_shortcut, "ptt", None),
            (s.cancel_shortcut, "cancel", lambda: self.state == "recording"),
        ):
            if hk := parse_shortcut(shortcut):
                bindings.append(Binding(hk, action, enabled))
        for mode in self.config.modes.values():
            if hk := parse_shortcut(mode.shortcut):
                bindings.append(Binding(hk, f"mode:{mode.key}"))
        self.hotkeys.set_bindings(bindings)

    # -- event handling ------------------------------------------------------
    def _event_loop(self) -> None:
        while True:
            action, phase = self.events.get()
            try:
                self._handle(action, phase)
            except Exception as e:
                log.exception("event %s failed", action)
                self._set_state("error", str(e), hide_after_ms=4000)

    def _handle(self, action: str, phase: str) -> None:
        if action == "ptt":
            if phase == "down" and self.state == "ready":
                self._start(None, ptt=True)
            elif phase == "up" and self.state == "recording" and self.ptt:
                self._stop()
        elif phase != "down":
            return
        elif action == "toggle" or action.startswith("mode:"):
            if self.state == "ready":
                self._start(action.removeprefix("mode:") if action != "toggle" else None, ptt=False)
            elif self.state == "recording":
                self._stop()
        elif action == "cancel" and self.state == "recording":
            self.recorder.stop()
            play_sound(self.config.settings, "cancel")
            self._set_state("ready", "Cancelled", hide_after_ms=800)

    def _start(self, mode_key: str | None, ptt: bool) -> None:
        self.app_info = winapi.foreground_app()
        if mode_key:
            mode = self.config.modes[mode_key]
        else:
            mode = next((m for m in self.config.modes.values()
                         if m.activation_apps and ctx.matches_app(self.app_info, m.activation_apps)),
                        self.config.active_mode)
        self.mode, self.ptt = mode, ptt
        self.recorder.start()
        play_sound(self.config.settings, "start")
        self._set_state("recording", mode.name)
        self.context_future = self.ctx_worker.submit(ctx.gather, mode, self.app_info)

    def _stop(self) -> None:
        audio = self.recorder.stop()
        play_sound(self.config.settings, "stop")
        if self.app_info.get("pid") == os.getpid():
            # Dictating into Offspeak's own settings window: feed the raw text to its test area, don't paste.
            self._set_state("processing", "Transcribing for test")
            self._transcribe_for_test(audio, self._heard_in_settings)
            return
        self._set_state("processing", f"Transcribing ({self.mode.name})")
        self.worker.submit(self._process, audio, self.mode, self.context_future)

    def _heard_in_settings(self, text: str | None, error: str | None) -> None:
        if self.settings_window and self.settings_window.exists():
            self.settings_window.heard(text, error)
        self._set_state("ready", "Sent to test area", hide_after_ms=800)

    def _process(self, audio, mode: Mode, context_future) -> None:
        try:
            context = context_future.result(timeout=2) if context_future else {}
            result = self.pipeline.run(audio, mode, context)
            if result is None:
                self._set_state("ready", "No speech detected", hide_after_ms=1200)
                return
            self._deliver(result["result"], mode)
            self.history.add(audio, result)
            self.last_result = result["result"]
            self._set_state("done", f"{result['word_count']} words", hide_after_ms=1000)
        except Exception as e:
            log.exception("processing failed")
            self._set_state("error", str(e)[:60], hide_after_ms=5000)
            self._notify(str(e))

    def _deliver(self, text: str, mode: Mode) -> None:
        s = self.config.settings
        auto_paste = s.auto_paste if mode.auto_paste is None else mode.auto_paste
        if not auto_paste:
            winapi.set_clipboard_text(text)  # the user pastes it themselves
            return
        # keep a copy of what the user had copied only to put it back; nothing else reads the clipboard
        previous = winapi.snapshot_clipboard() if s.restore_clipboard_delay > 0 else None
        ours = winapi.set_clipboard_text(text, transient=True)
        time.sleep(0.05)
        winapi.send_ctrl_v()
        if previous is not None and ours is not None:
            def restore():
                time.sleep(s.restore_clipboard_delay)
                # only if nobody copied something new in the meantime
                if winapi.clipboard_sequence() == ours:
                    winapi.restore_clipboard(previous)
            threading.Thread(target=restore, daemon=True).start()

    def _set_state(self, state: str, label: str, hide_after_ms: int | None = None) -> None:
        self.state = "ready" if state in ("done", "error") else state
        self.tray.icon = tray_image(state)
        self.overlay.show(state, label, hide_after_ms)

    def _notify(self, message: str) -> None:
        try:
            self.tray.notify(message, "Offspeak")
        except Exception:
            pass

    # -- tray menu -----------------------------------------------------------
    def _menu(self) -> pystray.Menu:
        def mode_item(key: str, name: str) -> pystray.MenuItem:
            return pystray.MenuItem(name, lambda: self._select_mode(key),
                                    checked=lambda _i: self.config.settings.active_mode == key, radio=True)

        return pystray.Menu(
            pystray.MenuItem("Mode", pystray.Menu(lambda: (
                mode_item(m.key, m.name) for m in self.config.modes.values()))),
            pystray.MenuItem("Copy last result", self._copy_last, enabled=lambda _i: bool(self.last_result)),
            pystray.MenuItem("Transcribe file...", self._transcribe_file_dialog),
            pystray.MenuItem("Settings...", lambda: self.overlay.call(self._open_settings), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open data folder", lambda: os.startfile(self.config.root)),
            pystray.MenuItem("Reload settings", self._reload),
            pystray.MenuItem("Quit", self._quit),
        )

    def _select_mode(self, key: str) -> None:
        self.config.set_active_mode(key)
        self.worker.submit(self._preload, self.config.active_mode)

    def _copy_last(self) -> None:
        winapi.set_clipboard_text(self.last_result)

    def _reload(self) -> None:
        self.config.load()
        self.pipeline.settings = self.config.settings
        self._bind_hotkeys()
        self.tray.menu = self._menu()
        self.tray.update_menu()
        self.worker.submit(self._preload, self.config.active_mode)

    def _open_settings(self) -> None:
        if self.settings_window and self.settings_window.exists():
            return self.settings_window.show()
        self.settings_window = SettingsWindow(
            self.overlay.root, self.config.settings, self.config.modes, self.config.active_mode.language,
            on_save=self._save_settings, transcribe=self._transcribe_for_test,
            pause_hotkeys=lambda paused: setattr(self.hotkeys, "paused", paused),
            on_zoom=self._save_zoom)

    def _save_zoom(self, zoom: float) -> None:
        self.config.settings.ui_zoom = zoom
        self.config.save_settings()

    def _transcribe_for_test(self, audio, done) -> None:
        """Raw speech-to-text for the settings test area, on the same worker as normal dictation."""
        mode = self.config.active_mode

        def job():
            try:
                speech = trim_silence(audio)
                text = self.pipeline.transcribe(normalize(speech), mode) if speech.size >= SAMPLE_RATE // 4 else ""
                self.overlay.call(done, text, None)
            except Exception as e:
                log.exception("test transcription failed")
                self.overlay.call(done, None, str(e))

        self.worker.submit(job)

    def _save_settings(self, changes: dict) -> None:
        for key, shortcut in changes.pop("mode_shortcuts", {}).items():
            if key in self.config.modes and self.config.modes[key].shortcut != shortcut:
                self.config.modes[key].shortcut = shortcut
                self.config.save_mode(self.config.modes[key])
        for key, value in changes.items():
            setattr(self.config.settings, key, value)
        self.config.save_settings()
        self._bind_hotkeys()

    def _transcribe_file_dialog(self) -> None:
        self.overlay.call(self._ask_file)

    def _ask_file(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            parent=self.overlay.root, title="Transcribe audio file",
            filetypes=[("Audio", "*.wav *.flac *.mp3 *.ogg"), ("All files", "*.*")])
        if path:
            self._set_state("processing", "Transcribing file")
            self.worker.submit(self._process_file, path, self.config.active_mode)

    def _process_file(self, path: str, mode: Mode) -> None:
        try:
            audio = load_audio_file(path)
            result = self.pipeline.run(audio, mode, {})
            if result is None:
                self._set_state("ready", "No speech detected", hide_after_ms=1500)
                return
            result["from_file"] = True
            self.history.add(None, result)
            self.last_result = result["result"]
            winapi.set_clipboard_text(result["result"])
            self._set_state("done", "Copied to clipboard", hide_after_ms=1500)
        except Exception as e:
            log.exception("file transcription failed")
            self._set_state("error", str(e)[:60], hide_after_ms=5000)

    def _quit(self) -> None:
        self.overlay.quit()


def run_app() -> None:
    netguard.install()
    winapi.enable_dpi_awareness()
    config = Config()
    logging.basicConfig(filename=config.root / "offspeak.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    App(config).run()
