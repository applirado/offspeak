import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import Callable

import numpy as np
from PIL import ImageTk

from offspeak import sounds, winapi
from offspeak.audio import Recorder
from offspeak.commands import COMMANDS, LANGUAGES, commands_for, default_phrases, phrases_with_defaults
from offspeak.config import Mode, Settings
from offspeak.hotkeys import MODIFIER_VKS, current_modifiers, format_shortcut
from offspeak.textproc import postprocess
from offspeak.ui import icon_image

GLOBAL_SHORTCUTS = (
    ("push_to_talk_shortcut", "Push-to-talk (hold)"),
    ("toggle_shortcut", "Start / stop recording"),
    ("cancel_shortcut", "Cancel recording"),
)
# keys that would hijack normal typing if used without a modifier
TYPING_VKS = {0x08, 0x09, 0x0D, 0x20, *range(0x30, 0x3A), *range(0x41, 0x5B)}

PAD = 8
WRAP = 600
BASE_SIZE = 700
BASE_HEIGHT = 760
ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.7, 2.0, 0.1
NAMED_FONTS = ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont", "TkFixedFont", "TkCaptionFont",
               "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont")
_named_font_base: dict[str, int] = {}  # sizes at 100 %, captured once per process
# (audio, done) -> None; done(text, error) is called back on the Tk thread
Transcriber = Callable[[np.ndarray, Callable[[str | None, str | None], None]], None]


def _scrolled(parent: tk.Misc, make: Callable[[tk.Misc], tk.Widget]) -> tk.Widget:
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True)
    widget = make(frame)
    bar = ttk.Scrollbar(frame, orient="vertical", command=widget.yview)
    widget.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    widget.pack(side="left", fill="both", expand=True)
    return widget


def _scaled(size: int, zoom: float) -> int:
    # Tk font sizes are points when positive and pixels when negative; keep the sign
    s = round(size * zoom)
    return s or (1 if size > 0 else -1)


def _widgets(widget: tk.Misc):
    yield widget
    for child in widget.winfo_children():
        yield from _widgets(child)


def _show_symbol(symbol: str) -> str:
    return {"\n": "new line", "\n\n": "blank line", "": "(next word as text)"}.get(symbol, symbol)


class SettingsWindow:
    """Edit vocabulary, replacements and the spoken form of voice commands, with a live preview."""

    def __init__(self, master: tk.Misc, settings: Settings, modes: dict[str, Mode], language: str,
                 on_save: Callable[[dict], None], transcribe: Transcriber | None = None,
                 pause_hotkeys: Callable[[bool], None] | None = None,
                 on_zoom: Callable[[float], None] | None = None):
        self.on_save = on_save
        self.on_zoom = on_zoom or (lambda _zoom: None)
        self.zoom = min(ZOOM_MAX, max(ZOOM_MIN, settings.ui_zoom))
        self._font_base = {"list": 10, "hint": 9, "result": 10, "title": 11, "close": 11}
        self.fonts = {
            "title": tkfont.Font(family="Segoe UI", size=11, weight="bold"),
            "close": tkfont.Font(family="Segoe UI", size=11),
            "list": tkfont.Font(family="Segoe UI", size=10),
            "hint": tkfont.Font(family="Segoe UI", size=9, slant="italic"),
            "result": tkfont.Font(family="Segoe UI", size=10, weight="bold"),
        }
        self._wrap_base: dict[str, int] = {}
        self._column_base: dict[str, int] = {}
        self.transcribe = transcribe
        self.pause_hotkeys = pause_hotkeys or (lambda _paused: None)
        self.recorder: Recorder | None = None
        # row key -> shortcut; global keys are Settings attribute names, mode rows are "mode:<key>"
        self.shortcut_labels = {key: label for key, label in GLOBAL_SHORTCUTS}
        self.shortcut_labels.update({f"mode:{k}": f"Mode “{m.name}”" for k, m in modes.items()})
        self.shortcuts = {key: getattr(settings, key) for key, _ in GLOBAL_SHORTCUTS}
        self.shortcuts.update({f"mode:{k}": m.shortcut for k, m in modes.items()})
        self.capturing: str | None = None
        self.vocabulary = sorted(settings.vocabulary, key=str.lower)
        self.replacements = [dict(r) for r in settings.replacements]
        self.phrases = {lang: phrases_with_defaults(settings.voice_commands, lang) for lang in LANGUAGES}
        self.dirty = False

        self.win = tk.Toplevel(master)
        # Windows shows a new toplevel at once; keep it invisible until it is built, or it flashes small, then grows
        self.win.attributes("-alpha", 0.0)
        self.win.title("Offspeak - Settings")
        self._icon = ImageTk.PhotoImage(icon_image("ready", 64), master=self.win)
        self.win.iconphoto(False, self._icon)
        width = min(round(BASE_SIZE * self.zoom), int(self.win.winfo_screenwidth() * 0.95))
        height = min(round(BASE_HEIGHT * self.zoom), int(self.win.winfo_screenheight() * 0.9))
        self.win.geometry(f"{width}x{height}")
        self.win.minsize(560, 480)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        try:
            ttk.Style(self.win).theme_use("vista")
        except tk.TclError:
            pass

        self.enabled_var = tk.BooleanVar(value=settings.voice_commands_enabled)
        self.lang_var = tk.StringVar(value=LANGUAGES.get(language, LANGUAGES["de"]))

        self._header()
        notebook = ttk.Notebook(self.win)
        notebook.pack(fill="both", expand=True, padx=PAD, pady=(PAD, 0))
        notebook.add(self._vocabulary_tab(notebook), text="Vocabulary")
        notebook.add(self._replacements_tab(notebook), text="Replacements")
        notebook.add(self._commands_tab(notebook), text="Voice commands")
        notebook.add(self._shortcuts_tab(notebook), text="Shortcuts")
        notebook.add(self._sound_tab(notebook, settings), text="Sound")
        notebook.add(self._startup_tab(notebook), text="Startup")
        notebook.bind("<<NotebookTabChanged>>", lambda _e: self._end_capture())
        self._preview_section()

        buttons = ttk.Frame(self.win)
        buttons.pack(fill="x", padx=PAD, pady=PAD)
        ttk.Button(buttons, text="Close", command=self.close).pack(side="right")
        ttk.Button(buttons, text="Save", command=self.save).pack(side="right", padx=(0, PAD))
        self.status_var = tk.StringVar()
        ttk.Label(buttons, textvariable=self.status_var, foreground="#2e7d32").pack(side="right", padx=(0, PAD))
        self.win.bind("<Escape>", lambda _e: None if self.capturing else self.close())
        self.win.bind("<Control-s>", lambda _e: self.save())
        for seq in ("<Control-plus>", "<Control-equal>", "<Control-KP_Add>"):
            self.win.bind(seq, lambda _e: self._zoom_by(1))
        for seq in ("<Control-minus>", "<Control-KP_Subtract>"):
            self.win.bind(seq, lambda _e: self._zoom_by(-1))
        for seq in ("<Control-Key-0>", "<Control-KP_0>", "<Control-KP_Insert>"):
            self.win.bind(seq, lambda _e: self._zoom_by(0))
        self.win.bind("<Control-MouseWheel>", lambda e: self._zoom_by(1 if e.delta > 0 else -1))

        self._apply_zoom()
        self._refresh()
        self.win.update_idletasks()
        winapi.remove_caption(int(self.win.wm_frame(), 16))
        # idle callbacks run once the pending resize events are handled, so the final layout is what appears
        self.win.after_idle(self._reveal)

    def _reveal(self) -> None:
        self.win.attributes("-alpha", 1.0)
        self.win.lift()
        self.win.focus_force()

    # -- own title bar (the native one cannot follow the zoom) ---------------
    def _header(self) -> None:
        bg = ttk.Style(self.win).lookup("TFrame", "background") or "SystemButtonFace"
        header = tk.Frame(self.win, bg=bg)
        header.pack(fill="x", padx=(PAD * 2, PAD // 2), pady=(PAD, 0))
        self._header_icon = ImageTk.PhotoImage(icon_image("ready", 24), master=self.win)
        icon = tk.Label(header, image=self._header_icon, bg=bg)
        icon.pack(side="left", padx=(0, PAD))
        title = tk.Label(header, text="Offspeak", font=self.fonts["title"], bg=bg)
        title.pack(side="left")
        close = tk.Label(header, text="✕", font=self.fonts["close"], bg=bg, padx=PAD * 2, pady=PAD // 2,
                         cursor="hand2")
        close.pack(side="right")
        close.bind("<Enter>", lambda _e: close.configure(bg="#c42b1c", fg="white"))
        close.bind("<Leave>", lambda _e: close.configure(bg=bg, fg="black"))
        close.bind("<Button-1>", lambda _e: self.close())
        for widget in (header, icon, title):  # drag the window by its header
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag)

    def _start_drag(self, event) -> None:
        self._drag_offset = (event.x_root - self.win.winfo_x(), event.y_root - self.win.winfo_y())

    def _drag(self, event) -> None:
        dx, dy = self._drag_offset
        self.win.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    # -- zoom ----------------------------------------------------------------
    def _zoom_by(self, steps: int) -> str:
        """steps=0 resets to 100 %."""
        new = 1.0 if steps == 0 else round(min(ZOOM_MAX, max(ZOOM_MIN, self.zoom + steps * ZOOM_STEP)), 1)
        if new != self.zoom:
            old, self.zoom = self.zoom, new
            self._apply_zoom()
            w, h = self.win.winfo_width(), self.win.winfo_height()
            limit_w, limit_h = int(self.win.winfo_screenwidth() * 0.95), int(self.win.winfo_screenheight() * 0.9)
            self.win.geometry(f"{min(limit_w, round(w * new / old))}x{min(limit_h, round(h * new / old))}")
            self.on_zoom(new)
        self.status_var.set(f"Zoom {round(self.zoom * 100)} %")
        return "break"

    def _apply_zoom(self) -> None:
        for name in NAMED_FONTS:
            try:
                f = tkfont.nametofont(name, root=self.win)
            except tk.TclError:
                continue
            base = _named_font_base.setdefault(name, int(f.cget("size")))
            f.configure(size=_scaled(base, self.zoom))
        for key, f in self.fonts.items():
            f.configure(size=_scaled(self._font_base[key], self.zoom))
        linespace = tkfont.nametofont("TkDefaultFont", root=self.win).metrics("linespace")
        ttk.Style(self.win).configure("Treeview", rowheight=linespace + 6)
        for widget in _widgets(self.win):
            if isinstance(widget, ttk.Label):
                base = self._wrap_base.setdefault(str(widget), int(str(widget.cget("wraplength") or 0)))
                if base:
                    widget.configure(wraplength=round(base * self.zoom))
            elif isinstance(widget, ttk.Treeview):
                for col in widget["columns"]:
                    base = self._column_base.setdefault(f"{widget}.{col}", int(widget.column(col, "width")))
                    widget.column(col, width=round(base * self.zoom))

    # -- vocabulary ----------------------------------------------------------
    def _vocabulary_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=PAD)
        ttk.Label(tab, wraplength=WRAP, justify="left", text=(
            "Names and technical terms Offspeak should spell correctly. Terms with 6 or more letters are "
            'also fixed when they come out slightly wrong ("Databurse" becomes "Dataverse").'
        )).pack(fill="x", pady=(0, PAD))

        entry_row = ttk.Frame(tab)
        entry_row.pack(fill="x", pady=(0, PAD))
        self.term_var = tk.StringVar()
        entry = ttk.Entry(entry_row, textvariable=self.term_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _e: self._add_term())
        ttk.Button(entry_row, text="Add", command=self._add_term).pack(side="left", padx=(PAD, 0))
        ttk.Button(entry_row, text="Remove", command=self._remove_term).pack(side="left", padx=(PAD, 0))

        self.term_list = _scrolled(tab, lambda f: tk.Listbox(f, activestyle="none", font=self.fonts["list"],
                                                             selectmode="extended"))
        self.term_list.bind("<Delete>", lambda _e: self._remove_term())
        return tab

    def _add_term(self) -> None:
        term = self.term_var.get().strip()
        if term and term.lower() not in (t.lower() for t in self.vocabulary):
            self.vocabulary = sorted([*self.vocabulary, term], key=str.lower)
            self._changed()
        self.term_var.set("")

    def _remove_term(self) -> None:
        selected = {self.term_list.get(i) for i in self.term_list.curselection()}
        if selected:
            self.vocabulary = [t for t in self.vocabulary if t not in selected]
            self._changed()

    # -- replacements --------------------------------------------------------
    def _replacements_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=PAD)
        ttk.Label(tab, wraplength=WRAP, justify="left", text=(
            "Whole words or phrases that are always replaced, regardless of case. Useful for words that "
            'keep coming out wrong, or for shortcuts such as "mfg" -> "Mit freundlichen Grüssen".'
        )).pack(fill="x", pady=(0, PAD))

        form = ttk.Frame(tab)
        form.pack(fill="x", pady=(0, PAD))
        form.columnconfigure((0, 1), weight=1)
        ttk.Label(form, text="When transcribed as").grid(row=0, column=0, sticky="w")
        ttk.Label(form, text="Write").grid(row=0, column=1, sticky="w", padx=(PAD, 0))
        self.original_var, self.with_var = tk.StringVar(), tk.StringVar()
        ttk.Entry(form, textvariable=self.original_var).grid(row=1, column=0, sticky="ew")
        target = ttk.Entry(form, textvariable=self.with_var)
        target.grid(row=1, column=1, sticky="ew", padx=(PAD, 0))
        target.bind("<Return>", lambda _e: self._save_replacement())
        ttk.Button(form, text="Add / Update", command=self._save_replacement).grid(row=1, column=2, padx=(PAD, 0))
        ttk.Button(form, text="Remove", command=self._remove_replacement).grid(row=1, column=3, padx=(PAD, 0))

        self.rep_tree = _scrolled(tab, lambda f: ttk.Treeview(f, columns=("original", "with"), show="headings",
                                                              selectmode="browse"))
        self.rep_tree.heading("original", text="When transcribed as", anchor="w")
        self.rep_tree.heading("with", text="Write", anchor="w")
        self.rep_tree.bind("<<TreeviewSelect>>", self._select_replacement)
        self.rep_tree.bind("<Delete>", lambda _e: self._remove_replacement())
        return tab

    def _select_replacement(self, _event=None) -> None:
        if sel := self.rep_tree.selection():
            r = self.replacements[int(sel[0])]
            self.original_var.set(r["original"])
            self.with_var.set(r["with"])

    def _save_replacement(self) -> None:
        original, new = self.original_var.get().strip(), self.with_var.get().strip()
        if not original:
            return
        existing = next((r for r in self.replacements if r["original"].lower() == original.lower()), None)
        if existing:
            existing.update({"original": original, "with": new})
        else:
            self.replacements.append({"original": original, "with": new})
        self.original_var.set("")
        self.with_var.set("")
        self._changed()

    def _remove_replacement(self) -> None:
        if sel := self.rep_tree.selection():
            del self.replacements[int(sel[0])]
            self.original_var.set("")
            self.with_var.set("")
            self._changed()

    # -- voice commands ------------------------------------------------------
    def _commands_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=PAD)
        top = ttk.Frame(tab)
        top.pack(fill="x", pady=(0, PAD))
        ttk.Checkbutton(top, text="Enable voice commands", variable=self.enabled_var,
                        command=self._changed).pack(side="left")
        lang = ttk.Combobox(top, textvariable=self.lang_var, values=list(LANGUAGES.values()),
                            state="readonly", width=12)
        lang.pack(side="right")
        lang.bind("<<ComboboxSelected>>", lambda _e: self._refresh())
        ttk.Label(top, text="Language:").pack(side="right", padx=(0, PAD))
        ttk.Label(tab, wraplength=WRAP, justify="left", text=(
            "Say a command to insert punctuation or a line break; spacing is fixed automatically. "
            "The commands are fixed, how you say them is up to you. Separate several phrasings with "
            '";". The language follows the active mode; modes set to "auto" understand all languages.'
        )).pack(fill="x", pady=(0, PAD))

        form = ttk.Frame(tab)
        form.pack(fill="x", pady=(0, PAD))
        form.columnconfigure(1, weight=1)
        self.cmd_label_var = tk.StringVar(value="Select a command")
        ttk.Label(form, textvariable=self.cmd_label_var, width=24).grid(row=0, column=0, sticky="w")
        self.cmd_phrases_var = tk.StringVar()
        entry = ttk.Entry(form, textvariable=self.cmd_phrases_var)
        entry.grid(row=0, column=1, sticky="ew", padx=(PAD, 0))
        entry.bind("<Return>", lambda _e: self._apply_phrases())
        ttk.Button(form, text="Apply", command=self._apply_phrases).grid(row=0, column=2, padx=(PAD, 0))
        ttk.Button(form, text="Reset language", command=self._reset_language).grid(row=0, column=3, padx=(PAD, 0))

        self.cmd_tree = _scrolled(tab, lambda f: ttk.Treeview(f, columns=("command", "inserts", "spoken"),
                                                              show="headings", selectmode="browse"))
        for col, title, width in (("command", "Command", 190), ("inserts", "Inserts", 110), ("spoken", "Spoken as", 300)):
            self.cmd_tree.heading(col, text=title, anchor="w")
            self.cmd_tree.column(col, width=width, stretch=col == "spoken")
        self.cmd_tree.bind("<<TreeviewSelect>>", self._select_command)
        return tab

    def _language(self) -> str:
        return next(code for code, name in LANGUAGES.items() if name == self.lang_var.get())

    def _select_command(self, _event=None) -> None:
        if sel := self.cmd_tree.selection():
            cmd_id = sel[0]
            self.cmd_label_var.set(COMMANDS[cmd_id][0])
            self.cmd_phrases_var.set("; ".join(self.phrases[self._language()].get(cmd_id, [])))

    def _apply_phrases(self) -> None:
        if not (sel := self.cmd_tree.selection()):
            return
        phrases = [p.strip() for p in self.cmd_phrases_var.get().split(";") if p.strip()]
        self.phrases[self._language()][sel[0]] = phrases
        self._changed()
        self.cmd_tree.selection_set(sel[0])

    def _reset_language(self) -> None:
        lang = self._language()
        if messagebox.askyesno("Offspeak", f"Reset all {LANGUAGES[lang]} voice commands to their defaults?",
                               parent=self.win):
            self.phrases[lang] = default_phrases(lang)
            self.cmd_phrases_var.set("")
            self._changed()

    def _command_overrides(self) -> dict[str, dict[str, list[str]]]:
        overrides = {}
        for lang, table in self.phrases.items():
            defaults = default_phrases(lang)
            changed = {cmd: p for cmd, p in table.items() if p != defaults.get(cmd)}
            if changed:
                overrides[lang] = changed
        return overrides

    # -- shortcuts -----------------------------------------------------------
    def _shortcuts_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=PAD)
        ttk.Label(tab, wraplength=WRAP, justify="left", text=(
            'Click "Change" and press the new key combination. Push-to-talk records while you hold the keys; '
            "the other shortcuts start and stop a recording. A mode shortcut records in that mode."
        )).pack(fill="x", pady=(0, PAD))
        grid = ttk.Frame(tab)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        self.shortcut_vars: dict[str, tk.StringVar] = {}
        self.change_buttons: dict[str, ttk.Button] = {}
        for row, key in enumerate(self.shortcuts):
            if row == len(GLOBAL_SHORTCUTS):
                ttk.Separator(grid).grid(row=2 * row - 1, column=0, columnspan=4, sticky="ew", pady=PAD)
            r = 2 * row
            ttk.Label(grid, text=self.shortcut_labels[key]).grid(row=r, column=0, sticky="w", pady=2)
            var = tk.StringVar()
            ttk.Entry(grid, textvariable=var, state="readonly").grid(row=r, column=1, sticky="ew", padx=PAD)
            button = ttk.Button(grid, text="Change...", command=lambda k=key: self._capture(k))
            button.grid(row=r, column=2)
            ttk.Button(grid, text="Clear", command=lambda k=key: (self._end_capture(), self._set_shortcut(k, ""))
                       ).grid(row=r, column=3, padx=(PAD // 2, 0))
            self.shortcut_vars[key], self.change_buttons[key] = var, button
        self.shortcut_hint = ttk.Label(tab, foreground="#b3261e", wraplength=WRAP)
        self.shortcut_hint.pack(fill="x", pady=(PAD, 0))
        self.capture_target = ttk.Frame(tab, takefocus=True)
        self.capture_target.pack()
        self.capture_target.bind("<KeyPress>", self._captured_key)
        self._capture_timeout = None
        self._show_shortcuts()
        return tab

    def _show_shortcuts(self) -> None:
        for key, var in self.shortcut_vars.items():
            if key == self.capturing:
                var.set("Press the new shortcut...")
            else:
                var.set(self.shortcuts[key].replace("+", " + ") or "(none)")

    def _capture(self, key: str) -> None:
        if self.capturing == key:
            return self._end_capture()
        self._end_capture()
        self.capturing = key
        self.pause_hotkeys(True)
        self.change_buttons[key].configure(text="Cancel")
        self.shortcut_hint.configure(text="")
        self.capture_target.focus_set()
        # the global hotkeys are paused while capturing, so never leave capture mode running
        self._capture_timeout = self.win.after(10000, self._end_capture)
        self._show_shortcuts()

    def _end_capture(self) -> None:
        if self.capturing is None:
            return
        if self._capture_timeout:
            self.win.after_cancel(self._capture_timeout)
            self._capture_timeout = None
        self.change_buttons[self.capturing].configure(text="Change...")
        self.capturing = None
        self.pause_hotkeys(False)
        self._show_shortcuts()

    def _captured_key(self, event) -> str:
        key, vk = self.capturing, event.keycode
        if key is None or vk in MODIFIER_VKS:
            return "break"
        mods = current_modifiers()
        shortcut = format_shortcut(mods, vk)
        if shortcut is None:
            self.shortcut_hint.configure(text="This key cannot be used for a shortcut.")
        elif not mods and vk in TYPING_VKS and key != "cancel_shortcut":
            self.shortcut_hint.configure(text="Combine this key with Ctrl, Alt, Shift or Win, otherwise it "
                                              "would trigger while you type.")
        else:
            self._end_capture()
            self._set_shortcut(key, shortcut)
        return "break"

    def _set_shortcut(self, key: str, shortcut: str) -> None:
        clash = next((k for k, v in self.shortcuts.items() if shortcut and k != key and v == shortcut), None)
        if clash:
            self.shortcut_hint.configure(text=f"{shortcut} is already used for {self.shortcut_labels[clash]}.")
            return
        self.shortcut_hint.configure(text="")
        if self.shortcuts[key] != shortcut:
            self.shortcuts[key] = shortcut
            self.dirty = True
            self.status_var.set("")
        self._show_shortcuts()
        self._update_preview()

    # -- sound ---------------------------------------------------------------
    def _sound_tab(self, parent, settings: Settings) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=PAD)
        self.sound_on_var = tk.BooleanVar(value=settings.sound_effects)
        self.sound_theme_var = tk.StringVar(value=sounds.THEMES.get(settings.sound_theme, "Soft"))
        self.sound_volume_var = tk.DoubleVar(value=round(settings.sound_volume * 100))
        ttk.Checkbutton(tab, text="Play a sound when a recording starts, stops or is cancelled",
                        variable=self.sound_on_var, command=self._sound_changed).pack(anchor="w", pady=(0, PAD))

        grid = ttk.Frame(tab)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        ttk.Label(grid, text="Sound").grid(row=0, column=0, sticky="w", pady=PAD // 2)
        theme = ttk.Combobox(grid, textvariable=self.sound_theme_var, values=list(sounds.THEMES.values()),
                             state="readonly", width=12)
        theme.grid(row=0, column=1, sticky="w", padx=PAD)
        theme.bind("<<ComboboxSelected>>", lambda _e: (self._sound_changed(), self._preview_sound("start")))
        ttk.Label(grid, text="Volume").grid(row=1, column=0, sticky="w", pady=PAD // 2)
        volume_row = ttk.Frame(grid)
        volume_row.grid(row=1, column=1, sticky="ew", padx=PAD)
        self.volume_label = ttk.Label(volume_row, width=5)
        self.volume_label.pack(side="right")
        scale = ttk.Scale(volume_row, from_=0, to=100, variable=self.sound_volume_var,
                          command=lambda _v: self._sound_changed())
        scale.pack(side="left", fill="x", expand=True)
        scale.bind("<ButtonRelease-1>", lambda _e: self._preview_sound("start"))

        ttk.Label(grid, text="Preview").grid(row=2, column=0, sticky="w", pady=PAD // 2)
        buttons = ttk.Frame(grid)
        buttons.grid(row=2, column=1, sticky="w", padx=PAD)
        for event in sounds.EVENTS:
            ttk.Button(buttons, text=event.capitalize(), command=lambda e=event: self._preview_sound(e)).pack(
                side="left", padx=(0, PAD))
        self._update_volume_label()
        return tab

    def _sound_theme(self) -> str:
        return next(k for k, v in sounds.THEMES.items() if v == self.sound_theme_var.get())

    def _preview_sound(self, event: str) -> None:
        sounds.play(self._sound_theme(), event, round(self.sound_volume_var.get()) / 100)

    def _update_volume_label(self) -> None:
        self.volume_label.configure(text=f"{round(self.sound_volume_var.get())} %")

    def _sound_changed(self) -> None:
        self._update_volume_label()
        self.dirty = True
        self.status_var.set("")

    # -- startup -------------------------------------------------------------
    def _startup_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=PAD)
        self.autostart_var = tk.BooleanVar(value=winapi.get_autostart() is not None)
        ttk.Checkbutton(tab, text="Start Offspeak when I sign in to Windows", variable=self.autostart_var,
                        command=lambda: (setattr(self, "dirty", True), self.status_var.set(""))
                        ).pack(anchor="w", pady=(0, PAD))
        ttk.Label(tab, wraplength=WRAP, justify="left", text=(
            "Offspeak then starts in the tray, without a console window, from the installation it is running "
            'from now. Turn it off and on again after moving Offspeak. Also available as "offspeak autostart".'
        )).pack(fill="x")
        return tab

    # -- test area -----------------------------------------------------------
    def _preview_section(self) -> None:
        frame = ttk.LabelFrame(self.win, text="Test your rules", padding=PAD)
        frame.pack(fill="x", padx=PAD, pady=(PAD, 0))
        frame.columnconfigure(2, weight=1)
        self.speak_button = ttk.Button(frame, text="\U0001f3a4 Speak", width=10, command=self._toggle_recording)
        self.speak_button.grid(row=0, column=0, sticky="w")
        if self.transcribe is None:
            self.speak_button.state(["disabled"])
        ttk.Label(frame, text="Heard:").grid(row=0, column=1, sticky="w", padx=(PAD, PAD // 2))
        self.sample_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.sample_var).grid(row=0, column=2, sticky="ew")
        ttk.Label(frame, text="Result:").grid(row=1, column=1, sticky="nw", padx=(PAD, PAD // 2), pady=(PAD // 2, 0))
        self.result_label = ttk.Label(frame, wraplength=WRAP - 120, justify="left")
        self.result_label.grid(row=1, column=2, sticky="w", pady=(PAD // 2, 0))
        self.sample_var.trace_add("write", lambda *_: self._update_preview())

    def _toggle_recording(self) -> None:
        if self.recorder is None:
            self.recorder = Recorder()
            self.recorder.start()
            self.speak_button.configure(text="■ Stop")
            self._hint("Listening... click Stop when you are done.")
            return
        audio = self.recorder.stop()
        self.recorder = None
        self.speak_button.configure(text="\U0001f3a4 Speak")
        self.speak_button.state(["disabled"])
        self._hint("Transcribing...")
        self.transcribe(audio, self.heard)

    def heard(self, text: str | None, error: str | None) -> None:
        if not self.exists():
            return
        self.speak_button.state(["!disabled"])
        if error:
            self._hint(f"Could not transcribe: {error}")
        elif not text:
            self._hint("No speech detected - try again a little louder.")
        else:
            self.sample_var.set(text)

    def _hint(self, message: str) -> None:
        self.result_label.configure(text=message, foreground="#6b6b6b", font=self.fonts["hint"])

    def _update_preview(self) -> None:
        sample = self.sample_var.get()
        if not sample.strip():
            ptt = self.shortcuts.get("push_to_talk_shortcut", "")
            ptt_hint = f" or hold {ptt.replace('+', ' + ')}" if ptt else ""
            return self._hint(f"Click \U0001f3a4 Speak{ptt_hint} and say a sentence, or type what Offspeak "
                              "heard. The result uses your current rules, including unsaved changes.")
        lang = self._language()
        commands = commands_for(lang, {lang: self.phrases[lang]}) if self.enabled_var.get() else []
        text = postprocess(sample, self.vocabulary, self.replacements, commands)
        self.result_label.configure(text=text.replace("\n", "⏎\n"), foreground="",
                                    font=self.fonts["result"])

    # -- state ---------------------------------------------------------------
    def _changed(self) -> None:
        self.dirty = True
        self.status_var.set("")
        self._refresh()

    def _refresh(self) -> None:
        self.term_list.delete(0, "end")
        for term in self.vocabulary:
            self.term_list.insert("end", term)
        self.rep_tree.delete(*self.rep_tree.get_children())
        for i, r in enumerate(self.replacements):
            self.rep_tree.insert("", "end", iid=str(i), values=(r["original"], r["with"]))
        table = self.phrases[self._language()]
        selected = self.cmd_tree.selection()
        self.cmd_tree.delete(*self.cmd_tree.get_children())
        for cmd_id, (label, symbol, _kind) in COMMANDS.items():
            spoken = "; ".join(table.get(cmd_id, [])) or "(off)"
            self.cmd_tree.insert("", "end", iid=cmd_id, values=(label, _show_symbol(symbol), spoken))
        if selected and self.cmd_tree.exists(selected[0]):
            self.cmd_tree.selection_set(selected[0])
        self._update_preview()

    def save(self) -> None:
        if self.autostart_var.get() != (winapi.get_autostart() is not None):
            winapi.set_autostart(self.autostart_var.get())
        self.on_save({
            "vocabulary": list(self.vocabulary),
            "replacements": [dict(r) for r in self.replacements],
            "voice_commands_enabled": self.enabled_var.get(),
            "voice_commands": self._command_overrides(),
            "sound_effects": self.sound_on_var.get(),
            "sound_theme": self._sound_theme(),
            "sound_volume": round(self.sound_volume_var.get()) / 100,
            **{key: v for key, v in self.shortcuts.items() if not key.startswith("mode:")},
            "mode_shortcuts": {key.removeprefix("mode:"): v for key, v in self.shortcuts.items()
                               if key.startswith("mode:")},
        })
        self.dirty = False
        self.status_var.set("Saved")
        self.win.after(2000, lambda: self.exists() and self.status_var.set(""))

    def close(self) -> None:
        if self.dirty:
            answer = messagebox.askyesnocancel("Offspeak", "Save changes to the settings?", parent=self.win)
            if answer is None:
                return
            if answer:
                self.save()
        if self.recorder is not None:
            self.recorder.stop()
            self.recorder = None
        self._end_capture()
        self.win.destroy()

    def show(self) -> None:
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()

    def exists(self) -> bool:
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False
