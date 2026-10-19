import functools
import queue
import threading
import time
import tkinter as tk

from PIL import Image, ImageChops, ImageDraw

from offspeak import winapi

STATE_COLORS = {"ready": "#3e63dd", "recording": "#e5484d", "processing": "#f5a524", "done": "#30a46c",
                "error": "#e5484d"}
TRANSPARENT = "#010203"
ICON_CANVAS = 512  # drawn large, then downsampled for smooth edges


def _curve(p0, p1, p2, steps: int = 24) -> list[tuple[float, float]]:
    """Quadratic Bezier from p0 to p2 with control point p1."""
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1])
            for t in (i / steps for i in range(steps + 1))]


@functools.lru_cache(maxsize=32)
def icon_image(state: str, size: int = 64, tight: bool = False) -> Image.Image:
    """The Offspeak cockatoo on a circle whose colour shows the recording state.

    tight=True crops to head, crest and beak and fills the whole circle, for the tiny tray icon.
    """
    s, white, beak = ICON_CANVAS, "#ffffff", "#1f2933"
    bird = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(bird)
    for base_a, tip, base_b in (((168, 175), (95, 40), (215, 140)), ((200, 150), (165, 18), (252, 128)),
                                ((236, 136), (250, 22), (290, 130))):
        d.polygon(_curve(base_a, (tip[0] - 10, tip[1] + 60), tip) + _curve(tip, (tip[0] + 40, tip[1] + 70), base_b),
                  fill=white)
    d.ellipse((130, 115, 350, 335), fill=white)
    d.ellipse((140, 255, 380, 640), fill=white)
    upper = (_curve((312, 160), (405, 150), (432, 245)) + _curve((432, 245), (440, 300), (414, 340))
             + _curve((414, 340), (406, 290), (378, 268)) + _curve((378, 268), (350, 252), (322, 262)))
    d.polygon(upper, fill=beak)
    d.polygon(_curve((326, 262), (372, 262), (384, 292)) + _curve((384, 292), (360, 318), (330, 300)),
              fill="#3b4752")
    d.ellipse((238, 168, 296, 226), fill=beak)
    d.ellipse((259, 179, 276, 196), fill=white)

    margin = 8
    if tight:
        bird = bird.crop((70, 0, 470, 400)).resize((s, s), Image.LANCZOS)
        margin = 2
    circle = (margin, margin, s - margin, s - margin)
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse(circle, fill=STATE_COLORS.get(state, STATE_COLORS["ready"]))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).ellipse(circle, fill=255)
    bird.putalpha(ImageChops.multiply(bird.getchannel("A"), mask))  # body is cut off at the circle edge
    img.alpha_composite(bird)
    return img.resize((size, size), Image.LANCZOS)


def tray_image(state: str) -> Image.Image:
    # high resolution, so Windows downsamples to the 16-32 px tray size itself instead of upscaling
    return icon_image(state, 256, tight=True)


class Overlay:
    """Small always-on-top pill near the bottom of the screen that never takes focus."""

    W, H = 300, 44

    def __init__(self, level_source):
        self.level_source = level_source
        self.root = tk.Tk()
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
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{self.W}x{self.H}+{(sw - self.W) // 2}+{sh - self.H - 90}")
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
