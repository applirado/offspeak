"""The menu bar app on macOS (preview): hold Option+Space, talk, let go, and the text is pasted into the active app.

Compared to Windows there is no recording pill yet: the menu bar icon shows the state (yellow ready, red
recording, blue transcribing, green done). The settings window runs in a process of its own (offspeak settings),
because AppKit and Tk both need the main thread; the app reloads settings.json whenever it changes.
"""

import logging
import queue
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import AppKit
import rumps

from offspeak import context as ctx
from offspeak import macapi, netguard, sounds
from offspeak.audio import Recorder
from offspeak.config import Config, Mode
from offspeak.history import History
from offspeak.icons import STATE_COLORS, icon_image
from offspeak.machotkeys import SHORTCUT_LABEL, MacHotkeys
from offspeak.pipeline import Pipeline

log = logging.getLogger("offspeak")
ICON_PIXELS = 44  # the 22 pt menu bar icon on a Retina display


def play_sound(settings, event: str) -> None:
    if settings.sound_effects:
        sounds.play(settings.sound_theme, event, settings.sound_volume)


class MacApp(rumps.App):
    def __init__(self, config: Config):
        self.config = config
        self.icons = {}
        icon_dir = config.root / "icons"
        icon_dir.mkdir(parents=True, exist_ok=True)
        for state in STATE_COLORS:
            self.icons[state] = str(icon_dir / f"{state}.png")
            icon_image(state, ICON_PIXELS).save(self.icons[state])
        super().__init__("OffSpeak", icon=self.icons["ready"], template=False, quit_button=None)

        self.history = History(config.root)
        self.pipeline = Pipeline(config.settings)
        self.recorder = Recorder()
        self.state = "ready"
        self.mode: Mode = config.active_mode
        self.app_info: dict = {}
        self.context_future = None
        self.last_result = ""
        self.events: queue.Queue = queue.Queue()
        self.ui: queue.Queue = queue.Queue()  # AppKit may only be touched on the main thread
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.ctx_worker = ThreadPoolExecutor(max_workers=1)
        self.hotkeys = MacHotkeys(lambda action, phase: self.events.put((action, phase)),
                                  lambda: self.state == "recording")
        self.hotkeys_started = False
        self.icon_reset_at = 0.0
        self.settings_process: subprocess.Popen | None = None
        self.settings_mtime = self._settings_mtime()

        self.status_item = rumps.MenuItem("")
        self.mode_menu = rumps.MenuItem("Mode")
        self.menu = [
            self.status_item,
            None,
            self.mode_menu,
            rumps.MenuItem("Copy last result", callback=lambda _: macapi.set_clipboard_text(self.last_result)),
            None,
            rumps.MenuItem("Settings…", callback=lambda _: self._open_settings(), key=","),
            rumps.MenuItem("Open data folder", callback=lambda _: subprocess.Popen(["open", str(config.root)])),
            rumps.MenuItem("Quit OffSpeak", callback=lambda _: rumps.quit_application()),
        ]
        self._fill_mode_menu()
        rumps.Timer(self._tick, 0.05).start()
        rumps.Timer(self._check_permission, 2).start()
        rumps.Timer(self._check_settings_file, 1).start()

    # -- lifecycle -------------------------------------------------------------
    def run(self, **options) -> None:
        # a menu bar app: no Dock icon and no app menu, also when Python itself is the main executable
        AppKit.NSApplication.sharedApplication().setActivationPolicy_(
            AppKit.NSApplicationActivationPolicyAccessory)
        threading.Thread(target=self._event_loop, daemon=True).start()
        self.history.cleanup_audio(self.config.settings.keep_recordings_days)
        self.worker.submit(self._preload, self.config.active_mode)
        self._check_permission(None, prompt=True)
        print(f"OffSpeak is running in the menu bar (mode: {self.config.active_mode.name}). "
              f"Hold {SHORTCUT_LABEL} to dictate.", flush=True)
        super().run(**options)

    def _check_permission(self, _timer, prompt: bool = False) -> None:
        """The shortcut and pasting need Accessibility; start listening as soon as the user allows it."""
        if self.hotkeys_started:
            return
        if macapi.accessibility_trusted(prompt=prompt):
            self.hotkeys.start()
            self.hotkeys_started = True
            self.status_item.title = f"Hold {SHORTCUT_LABEL} to dictate"
            self.status_item.set_callback(None)
        else:
            self.status_item.title = "⚠︎ Allow OffSpeak under Accessibility…"
            self.status_item.set_callback(lambda _: macapi.open_accessibility_settings())

    def _preload(self, mode: Mode) -> None:
        try:
            self.pipeline.preload(mode)
        except Exception:
            log.exception("preload failed")
            self._set_state("error")

    # -- menu ------------------------------------------------------------------
    def _fill_mode_menu(self) -> None:
        for title in list(self.mode_menu.keys()):
            del self.mode_menu[title]
        for mode in self.config.modes.values():
            item = rumps.MenuItem(mode.name, callback=lambda _, key=mode.key: self._select_mode(key))
            item.state = int(mode.key == self.config.settings.active_mode)
            self.mode_menu.add(item)

    def _select_mode(self, key: str) -> None:
        self.config.set_active_mode(key)
        self._fill_mode_menu()
        self.worker.submit(self._preload, self.config.active_mode)

    def _open_settings(self) -> None:
        if self.settings_process and self.settings_process.poll() is None:
            return  # already open
        self.settings_process = subprocess.Popen([sys.executable, "-m", "offspeak", "settings"])

    def _settings_mtime(self) -> float:
        try:
            return self.config.settings_path.stat().st_mtime
        except OSError:
            return 0.0

    def _check_settings_file(self, _timer) -> None:
        """Pick up what the settings window saved, or what the user edited in settings.json."""
        mtime = self._settings_mtime()
        if mtime != self.settings_mtime:
            self.settings_mtime = mtime
            self._reload()

    def _reload(self) -> None:
        self.config.load()
        self.pipeline.settings = self.config.settings
        self._fill_mode_menu()
        self.worker.submit(self._preload, self.config.active_mode)

    # -- dictation -------------------------------------------------------------
    def _event_loop(self) -> None:
        while True:
            action, phase = self.events.get()
            try:
                self._handle(action, phase)
            except Exception:
                log.exception("event %s failed", action)
                self._set_state("error")

    def _handle(self, action: str, phase: str) -> None:
        if action == "ptt":
            if phase == "down" and self.state == "ready":
                self._start()
            elif phase == "up" and self.state == "recording":
                self._stop()
        elif action == "cancel" and self.state == "recording":
            self.recorder.stop()
            play_sound(self.config.settings, "cancel")
            self._set_state("ready")

    def _start(self) -> None:
        self.app_info = macapi.foreground_app()
        self.mode = next((m for m in self.config.modes.values()
                          if m.activation_apps and ctx.matches_app(self.app_info, m.activation_apps)),
                         self.config.active_mode)
        self.recorder.start()
        play_sound(self.config.settings, "start")
        self._set_state("recording")
        self.context_future = self.ctx_worker.submit(ctx.gather, self.mode, self.app_info)

    def _stop(self) -> None:
        audio = self.recorder.stop()
        play_sound(self.config.settings, "stop")
        self._set_state("processing")
        self.worker.submit(self._process, audio, self.mode, self.context_future)

    def _process(self, audio, mode: Mode, context_future) -> None:
        try:
            context = context_future.result(timeout=2) if context_future else {}
            result = self.pipeline.run(audio, mode, context)
            if result is None:
                self._set_state("ready")
                return
            self._deliver(result["result"], mode)
            self.history.add(audio, result)
            self.last_result = result["result"]
            self._set_state("done")
        except Exception:
            log.exception("processing failed")
            self._set_state("error")

    def _deliver(self, text: str, mode: Mode) -> None:
        s = self.config.settings
        auto_paste = s.auto_paste if mode.auto_paste is None else mode.auto_paste
        if not auto_paste:
            macapi.set_clipboard_text(text)  # the user pastes it themselves
            return
        # keep a copy of what the user had copied only to put it back; nothing else reads the clipboard
        previous = macapi.snapshot_clipboard() if s.restore_clipboard_delay > 0 else None
        ours = macapi.set_clipboard_text(text, transient=True)
        time.sleep(0.05)
        macapi.send_cmd_v()
        if previous is not None:
            def restore():
                time.sleep(s.restore_clipboard_delay)
                if macapi.clipboard_sequence() == ours:  # only if nobody copied something new in the meantime
                    macapi.restore_clipboard(previous)
            threading.Thread(target=restore, daemon=True).start()

    # -- menu bar icon -----------------------------------------------------------
    def _set_state(self, state: str) -> None:
        """Thread-safe; green "done" and red "error" are a short flash before the icon turns yellow again."""
        self.state = "ready" if state in ("done", "error") else state
        self.ui.put(state)

    def _tick(self, _timer) -> None:
        while not self.ui.empty():
            state = self.ui.get_nowait()
            self.icon = self.icons[state]
            self.icon_reset_at = time.monotonic() + (1.0 if state == "done" else 4.0) \
                if state in ("done", "error") else 0.0
        if self.icon_reset_at and time.monotonic() > self.icon_reset_at and self.state == "ready":
            self.icon = self.icons["ready"]
            self.icon_reset_at = 0.0


def run_app() -> None:
    netguard.install()
    config = Config()
    logging.basicConfig(filename=config.root / "offspeak.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    MacApp(config).run()
