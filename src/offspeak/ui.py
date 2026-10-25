import logging
import queue
import threading
import time
import tkinter as tk

from offspeak import winapi
from offspeak.icons import STATE_COLORS, icon_image, tray_image  # noqa: F401 (re-exported for app.py)

TRANSPARENT = "#010203"


class Overlay:
    """Small always-on-top pill near the bottom of the screen or the active window that never takes focus."""

    W, H = 300, 44

    def __init__(self, level_source, position_source=lambda: "screen"):
        self.level_source = level_source
        self.position_source = position_source
        self.root = tk.Tk()
        # without a console, Tk would print errors in callbacks (buttons, settings) to nowhere
        self.root.report_callback_exception = lambda *exc: logging.error("Error in the UI", exc_info=exc)
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", TRANSPARENT)
        self.root.configure(bg=TRANSPARENT)
        self.canvas = tk.Canvas(self.root, width=self.W, height=self.H, bg=TRANSPARENT, highlightthickness=0)
        self.canvas.pack()
        self._calls: queue.Queue = queue.Queue()
        self._state = "hidden"
        self._label = ""
        self._started = 0.0
        self._hide_job = None
        self.root.update_idletasks()
        winapi.make_no_activate(int(self.root.wm_frame(), 16))
        self.root.after(40, self._tick)

    def call(self, fn, *args) -> None:
        """Thread-safe: run fn on the Tk thread."""
        self._calls.put((fn, args))

    def show(self, state: str, label: str, hide_after_ms: int | None = None) -> None:
        if threading.current_thread() is not threading.main_thread():
            return self.call(self.show, state, label, hide_after_ms)
        if state == "recording" and self._state != "recording":
            self._started = time.monotonic()
        self._state, self._label = state, label
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None
        x, y = winapi.overlay_position(self.W, self.H, self.position_source())
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        if hide_after_ms:
            self._hide_job = self.root.after(hide_after_ms, self.hide)

    def hide(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return self.call(self.hide)
        self._state = "hidden"
        self.root.withdraw()

    def _tick(self) -> None:
        while not self._calls.empty():
            fn, args = self._calls.get_nowait()
            fn(*args)
        if self._state != "hidden":
            self._draw()
        self.root.after(40, self._tick)

    def _draw(self) -> None:
        c, w, h = self.canvas, self.W, self.H
        c.delete("all")
        r = h // 2
        bg = "#1c1d21"
        c.create_oval(0, 0, h, h, fill=bg, outline=bg)
        c.create_oval(w - h, 0, w, h, fill=bg, outline=bg)
        c.create_rectangle(r, 0, w - r, h, fill=bg, outline=bg)
        color = STATE_COLORS.get(self._state, "#8a8f98")
        c.create_oval(16, r - 6, 28, r + 6, fill=color, outline=color)
        text = self._label
        if self._state == "recording":
            secs = int(time.monotonic() - self._started)
            text = f"{secs // 60}:{secs % 60:02d}  {self._label}"
            level = min(1.0, self.level_source() * 12)
            bar_w = 70
            c.create_rectangle(w - 24 - bar_w, r - 3, w - 24, r + 3, fill="#3a3b40", outline="")
            c.create_rectangle(w - 24 - bar_w, r - 3, w - 24 - bar_w + int(bar_w * level), r + 3,
                               fill=color, outline="")
        c.create_text(38, r, text=text, anchor="w", fill="#f2f2f3", font=("Segoe UI", 10))

    def mainloop(self) -> None:
        self.root.mainloop()

    def quit(self) -> None:
        self.call(self.root.quit)
