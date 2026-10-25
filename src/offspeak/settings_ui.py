import sys
import tkinter as tk
import webbrowser
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import Callable

import numpy as np
from PIL import ImageTk

from offspeak import sounds
from offspeak.audio import Recorder
from offspeak.commands import COMMANDS, LANGUAGES, commands_for, default_phrases, phrases_with_defaults
from offspeak.config import Mode, Settings
from offspeak.hotkeys import MODIFIER_VKS, current_modifiers, format_shortcut
from offspeak.textproc import postprocess
from offspeak.icons import icon_image

IS_MAC = sys.platform == "darwin"
if IS_MAC:
    from offspeak import macapi as system
else:
    from offspeak import winapi as system
FONT = "Helvetica Neue" if IS_MAC else "Segoe UI"

GLOBAL_SHORTCUTS = (
    ("push_to_talk_shortcut", "Push-to-talk (hold)"),
    ("toggle_shortcut", "Start / stop recording"),
    ("cancel_shortcut", "Cancel recording"),
)
# keys that would hijack normal typing if used without a modifier
TYPING_VKS = {0x08, 0x09, 0x0D, 0x20, *range(0x30, 0x3A), *range(0x41, 0x5B)}

PAD = 8
WRAP = 600
ACCENT = "#0067c0"  # Windows 11 default accent
TAB_TEXT, TAB_TEXT_DIM = "#1a1a1a", "#6b6b6b"
HELP_BG = "#e8f1fb"
DOCS_URL = "https://github.com/applirado/offspeak#readme"

# In-app help per tab, shown under "How it works" and with F1
HELP = {
    "vocabulary": (
        "Enter only the correct spelling. OffSpeak then fixes anything that sounds similar, so you do not "
        'need to list the wrong versions: "Ulama" and "Olama" become "Ollama", "Data verse" becomes "Dataverse".\n'
        "• This works for terms with 6 or more letters; shorter ones are too close to ordinary words.\n"
        "• Whisper models and the AI clean-up also get the list as a spelling hint.\n"
        "• If a term still comes out wrong, add it under Replacements.\n"
        "Try it in “Test your rules” below: type a misspelt version under “Heard”."
    ),
    "replacements": (
        "Most names and terms only need the Vocabulary. Use replacements for what it cannot fix:\n"
        '• short words: "Jason" -> "JSON"\n'
        '• words that come out very differently: "Kuber Netties" -> "Kubernetes"\n'
        '• text snippets: "my email" -> "anna@example.com"\n'
        "Replacements match whole words, ignore upper and lower case, and run after the vocabulary, so "
        "they always have the last word."
    ),
    "commands": (
        "The voice model already sets periods, commas and question marks by itself. Voice commands are for "
        "what it does not do: line breaks, paragraphs, brackets and quotes, or a specific character.\n"
        '• Several phrasings per command, separated by ";", let you say it the way you are used to '
        '("period; full stop").\n'
        '• OffSpeak tells the command apart from the word: "I agree, period." ends the sentence, '
        '"a long period" stays as it is.\n'
        '• To write a command word itself, say "literally" (in German "wörtlich") before it.\n'
        "If you mostly dictate plain text, you can switch voice commands off."
    ),
    "shortcuts": (
        "• Push-to-talk records while you hold the keys and inserts the text when you let go.\n"
        "• Start / stop: press once to start, again to stop; good for longer dictations.\n"
        "• Cancel stops a recording without inserting anything.\n"
        "• A mode shortcut records in that mode, for example one with an AI prompt for e-mails.\n"
        "Letters, digits, Space and Enter need Ctrl, Alt, Shift or Win, or they would trigger while you "
        "type. New shortcuts work as soon as you save."
    ),
    "sound": (
        "Short sounds tell you that a recording started, stopped or was cancelled, so you do not have to "
        "watch the screen. Use the buttons to listen to each sound; Soft and Cockatoo are the gentlest.\n"
        "The recording indicator appears on the screen you are working on. At the bottom of the active "
        "window, it stays close to your text, for example in a screen recording."
    ),
    "startup": (
        "OffSpeak adds itself to your Windows sign-in programs (no admin rights needed) and starts in the "
        "tray without a console window. If you move the OffSpeak folder, turn this off and on again, or run "
        "setup.cmd once more."
    ),
}
OVERLAY_POSITIONS = {"screen": "at the bottom of the screen", "window": "at the bottom of the active window"}
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
        self._font_base = {"list": 10, "hint": 9, "result": 10, "title": 11, "close": 11, "tab": 10, "link": 9}
        if IS_MAC:  # Tk on macOS counts 72 points per inch, so the same sizes come out smaller than on Windows
            self._font_base = {key: round(size * 1.3) for key, size in self._font_base.items()}
        self.fonts = {
            "title": tkfont.Font(family=FONT, size=11, weight="bold"),
            "close": tkfont.Font(family=FONT, size=11),
            "tab": tkfont.Font(family=FONT if IS_MAC else "Segoe UI Semibold", size=10,
                               weight="bold" if IS_MAC else "normal"),
            "link": tkfont.Font(family=FONT, size=9),
            "list": tkfont.Font(family=FONT, size=10),
            "hint": tkfont.Font(family=FONT, size=9, slant="italic"),
            "result": tkfont.Font(family=FONT, size=10, weight="bold"),
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
        self.win.title("OffSpeak - Settings")
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

        if not IS_MAC:
            self._header()
        self._help_toggles: dict[str, Callable[[], None]] = {}  # tab widget path -> show/hide its help
        self._open_help: Callable[[], None] | None = None  # toggle of the help that is shown
        notebook = ttk.Notebook(self.win, style="Pages.TNotebook")
        notebook.add(self._vocabulary_tab(notebook), text="Vocabulary")
        notebook.add(self._replacements_tab(notebook), text="Replacements")
        notebook.add(self._commands_tab(notebook), text="Voice commands")
        shortcuts_tab = self._shortcuts_tab(notebook)
        if not IS_MAC:
            notebook.add(shortcuts_tab, text="Shortcuts")
        notebook.add(self._sound_tab(notebook, settings), text="Sound & display")
        notebook.add(self._startup_tab(notebook), text="Startup")
        tab_bar = self._tab_bar(notebook)
        notebook.enable_traversal()  # Ctrl+Tab / Ctrl+Shift+Tab
        notebook.bind("<<NotebookTabChanged>>", lambda _e: self._end_capture(), add=True)

        # The buttons and the test area are packed (at the bottom) before the notebook, so a tall page, for
        # example with its help open, shrinks the page instead of pushing them out of the window.
        buttons = ttk.Frame(self.win)
        buttons.pack(side="bottom", fill="x", padx=PAD, pady=PAD)
        ttk.Button(buttons, text="Close", command=self.close).pack(side="right")
        ttk.Button(buttons, text="Save", command=self.save).pack(side="right", padx=(0, PAD))
        self.status_var = tk.StringVar()
        ttk.Label(buttons, textvariable=self.status_var, foreground="#2e7d32").pack(side="right", padx=(0, PAD))
        self._preview_section()
        notebook.pack(fill="both", expand=True, padx=PAD, pady=(PAD, 0))
        self.win.bind("<Escape>", lambda _e: None if self.capturing else self.close())
        self.win.bind("<Control-s>", lambda _e: self.save())
        self.win.bind("<F1>", lambda _e: self._help_toggles.get(notebook.select(), lambda: None)())
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
        # all tab headers must fit, also with large fonts or display scaling
        needed = tab_bar.winfo_reqwidth() + 4 * PAD
        self.win.minsize(max(560, needed), 480)
        if width < needed:
            self.win.geometry(f"{needed}x{height}")
            self.win.update_idletasks()
        if not IS_MAC:
            system.remove_caption(int(self.win.wm_frame(), 16))
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
        title = tk.Label(header, text="OffSpeak", font=self.fonts["title"], bg=bg)
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

    # -- tabs (the native vista tabs are barely visible on Windows 11) -------
    def _tab_bar(self, notebook: ttk.Notebook) -> tk.Frame:
        """Windows 11 style headers: text tabs with an accent bar under the selected one."""
        style = ttk.Style(self.win)
        style.layout("Pages.TNotebook.Tab", [])  # the notebook only switches pages; this bar shows the tabs
        bg = style.lookup("TFrame", "background") or "SystemButtonFace"
        bar = tk.Frame(self.win, bg=bg)
        bar.pack(fill="x", padx=PAD * 2, pady=(PAD, 0))
        self._tabs: list[tuple[tk.Label, tk.Frame]] = []
        for index, page in enumerate(notebook.tabs()):
            cell = tk.Frame(bar, bg=bg, cursor="hand2")
            cell.pack(side="left", padx=(0, PAD * 2))
            label = tk.Label(cell, text=notebook.tab(page, "text"), font=self.fonts["tab"], bg=bg, padx=2, pady=2)
            label.pack()
            line = tk.Frame(cell, height=3, bg=bg)
            line.pack(fill="x", padx=2)
            for widget in (cell, label, line):
                widget.bind("<Button-1>", lambda _e, i=index: notebook.select(i))
                widget.bind("<Enter>", lambda _e, i=index: self._show_tabs(notebook, hover=i))
                widget.bind("<Leave>", lambda _e: self._show_tabs(notebook))
            self._tabs.append((label, line))
        notebook.bind("<<NotebookTabChanged>>", lambda _e: self._show_tabs(notebook), add=True)
        self._show_tabs(notebook)
        return bar

    def _show_tabs(self, notebook: ttk.Notebook, hover: int | None = None) -> None:
        selected = notebook.index("current")
        for index, (label, line) in enumerate(self._tabs):
            label.configure(fg=TAB_TEXT if index in (selected, hover) else TAB_TEXT_DIM)
            line.configure(bg=ACCENT if index == selected else line.master["bg"])

    # -- in-app help ----------------------------------------------------------
    def _help(self, tab: ttk.Frame, key: str) -> None:
        """A "How it works" link that unfolds this tab's help text; F1 does the same."""
        link = ttk.Label(tab, text="How it works ▸", foreground=ACCENT, cursor="hand2", font=self.fonts["link"])
        link.pack(anchor="w", pady=(0, PAD))
        box = tk.Frame(tab, bg=HELP_BG, padx=PAD, pady=PAD)
        ttk.Label(box, text=HELP[key], wraplength=WRAP - 2 * PAD, justify="left", background=HELP_BG).pack(fill="x")
        docs = ttk.Label(box, text="Full documentation on GitHub ↗", foreground=ACCENT, background=HELP_BG,
                         cursor="hand2", font=self.fonts["link"])
        docs.pack(anchor="w", pady=(PAD // 2, 0))
        docs.bind("<Button-1>", lambda _e: webbrowser.open(DOCS_URL))
        grown = [None]  # pixels the window grew for this help while it is shown, None while hidden

        def resize(delta: int) -> None:
            if IS_MAC:
                self.win.geometry(f"{self.win.winfo_width()}x{self.win.winfo_height() + delta}")
            else:
                system.grow_window(int(self.win.wm_frame(), 16), delta)

        def toggle() -> None:
            if grown[0] is None:
                if self._open_help is not None:  # one help at a time, so the window grows only once
                    self._open_help()
                box.pack(after=link, fill="x", pady=(0, PAD))
                # make room for the help instead of squeezing the page, as far as the screen allows
                self.win.update_idletasks()
                limit = int(self.win.winfo_screenheight() * 0.9)
                grown[0] = max(0, min(box.winfo_reqheight() + PAD, limit - self.win.winfo_height()))
                resize(grown[0])
                self._open_help = toggle
            else:
                box.pack_forget()
                resize(-grown[0])
                grown[0] = self._open_help = None
            link.configure(text="How it works ▾" if grown[0] is not None else "How it works ▸")

        link.bind("<Button-1>", lambda _e: toggle())
        self._help_toggles[str(tab)] = toggle

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
        for _label, line in self._tabs:
            line.configure(height=max(2, round(3 * self.zoom)))
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
            "Names and technical terms OffSpeak should spell correctly. Terms with 6 or more letters are "
            'also fixed when they come out slightly wrong ("Databurse" becomes "Dataverse").'
        )).pack(fill="x", pady=(0, PAD // 2))
        self._help(tab, "vocabulary")

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
            "Words or phrases that are always replaced, regardless of case. Most terms only need the "
            "Vocabulary; use this for short words, very different spellings and snippets such as "
            '"my email" -> "anna@example.com".'
        )).pack(fill="x", pady=(0, PAD // 2))
        self._help(tab, "replacements")

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
        )).pack(fill="x", pady=(0, PAD // 2))
        self._help(tab, "commands")

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
        if messagebox.askyesno("OffSpeak", f"Reset all {LANGUAGES[lang]} voice commands to their defaults?",
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
        )).pack(fill="x", pady=(0, PAD // 2))
        self._help(tab, "shortcuts")
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
                        variable=self.sound_on_var, command=self._sound_changed).pack(anchor="w", pady=(0, PAD // 2))
        self._help(tab, "sound")

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

        self.overlay_position_var = tk.StringVar(value=OVERLAY_POSITIONS.get(settings.overlay_position,
                                                                             OVERLAY_POSITIONS["screen"]))
        if IS_MAC:
            return tab
        ttk.Separator(tab).pack(fill="x", pady=PAD)
        position_row = ttk.Frame(tab)
        position_row.pack(fill="x")
        ttk.Label(position_row, text="Show the recording indicator").pack(side="left")
        position = ttk.Combobox(position_row, textvariable=self.overlay_position_var,
                                values=list(OVERLAY_POSITIONS.values()), state="readonly", width=28)
        position.pack(side="left", padx=PAD)
        position.bind("<<ComboboxSelected>>", lambda _e: self._sound_changed())
        return tab

    def _overlay_position(self) -> str:
        return next(k for k, v in OVERLAY_POSITIONS.items() if v == self.overlay_position_var.get())

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
        self.autostart_var = tk.BooleanVar(value=system.get_autostart() is not None)
        sign_in = "log in to your Mac" if IS_MAC else "sign in to Windows"
        ttk.Checkbutton(tab, text=f"Start OffSpeak when I {sign_in}", variable=self.autostart_var,
                        command=lambda: (setattr(self, "dirty", True), self.status_var.set(""))
                        ).pack(anchor="w", pady=(0, PAD))
        ttk.Label(tab, wraplength=WRAP, justify="left", text=(
            "OffSpeak then opens OffSpeak.app in the menu bar." if IS_MAC else
            "OffSpeak then starts in the tray, without a console window, from the installation it is running "
            'from now. Turn it off and on again after moving OffSpeak. Also available as "offspeak autostart".'
        )).pack(fill="x", pady=(0, PAD // 2))
        if not IS_MAC:
            self._help(tab, "startup")
        return tab

    # -- test area -----------------------------------------------------------
    def _preview_section(self) -> None:
        frame = ttk.LabelFrame(self.win, text="Test your rules", padding=PAD)
        frame.pack(side="bottom", fill="x", padx=PAD, pady=(PAD, 0))
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
            ptt = "Option+Space" if IS_MAC else self.shortcuts.get("push_to_talk_shortcut", "")
            ptt_hint = f" or hold {ptt.replace('+', ' + ')}" if ptt else ""
            return self._hint(f"Click \U0001f3a4 Speak{ptt_hint} and say a sentence, or type what OffSpeak "
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
        if self.autostart_var.get() != (system.get_autostart() is not None):
            system.set_autostart(self.autostart_var.get())
        self.on_save({
            "vocabulary": list(self.vocabulary),
            "replacements": [dict(r) for r in self.replacements],
            "voice_commands_enabled": self.enabled_var.get(),
            "voice_commands": self._command_overrides(),
            "sound_effects": self.sound_on_var.get(),
            "sound_theme": self._sound_theme(),
            "sound_volume": round(self.sound_volume_var.get()) / 100,
            "overlay_position": self._overlay_position(),
            **{key: v for key, v in self.shortcuts.items() if not key.startswith("mode:")},
            "mode_shortcuts": {key.removeprefix("mode:"): v for key, v in self.shortcuts.items()
                               if key.startswith("mode:")},
        })
        self.dirty = False
        self.status_var.set("Saved")
        self.win.after(2000, lambda: self.exists() and self.status_var.set(""))

    def close(self) -> None:
        if self.dirty:
            answer = messagebox.askyesnocancel("OffSpeak", "Save changes to the settings?", parent=self.win)
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


def run_standalone() -> None:
    """The settings window in a process of its own: on macOS the menu bar app's main thread belongs to AppKit,
    and Tk needs the main thread too. The menu bar app reloads settings.json when this window saves it."""
    import queue
    import threading

    from offspeak import netguard
    from offspeak.audio import SAMPLE_RATE, normalize, trim_silence
    from offspeak.config import Config

    netguard.install()
    if IS_MAC:  # the app menu says "OffSpeak" instead of "Python"
        try:
            from Foundation import NSBundle

            NSBundle.mainBundle().infoDictionary()["CFBundleName"] = "OffSpeak"
        except Exception:
            pass
    config = Config()
    root = tk.Tk()  # Tk creates the macOS application object itself, so AppKit calls come after it
    root.withdraw()
    if IS_MAC:  # the window's colours are light; in dark mode macOS would put light text on them
        try:
            import AppKit

            AppKit.NSApplication.sharedApplication().setAppearance_(
                AppKit.NSAppearance.appearanceNamed_(AppKit.NSAppearanceNameAqua))
        except Exception:
            pass
    results: queue.Queue = queue.Queue()  # Tk may only be called from its own thread
    pipeline = []

    def transcribe(audio, done) -> None:
        """Raw speech-to-text for the test area; the voice model is loaded on the first use."""
        def job():
            try:
                if not pipeline:
                    from offspeak.pipeline import Pipeline

                    pipeline.append(Pipeline(config.settings))
                speech = trim_silence(audio)
                text = (pipeline[0].transcribe(normalize(speech), config.active_mode)
                        if speech.size >= SAMPLE_RATE // 4 else "")
                results.put((done, text, None))
            except Exception as e:
                results.put((done, None, str(e)))

        threading.Thread(target=job, daemon=True).start()

    def save(changes: dict) -> None:
        for key, shortcut in changes.pop("mode_shortcuts", {}).items():
            if key in config.modes and config.modes[key].shortcut != shortcut:
                config.modes[key].shortcut = shortcut
                config.save_mode(config.modes[key])
        for key, value in changes.items():
            setattr(config.settings, key, value)
        config.save_settings()

    def zoom(value: float) -> None:
        config.settings.ui_zoom = value
        config.save_settings()

    window = SettingsWindow(root, config.settings, config.modes, config.active_mode.language,
                            on_save=save, transcribe=transcribe, on_zoom=zoom)
    if IS_MAC:  # started from a menu bar app, the window would otherwise open behind the active app
        try:
            import AppKit

            AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        except Exception:
            pass

    def poll() -> None:
        while not results.empty():
            done, text, error = results.get_nowait()
            done(text, error)
        if window.exists():
            root.after(100, poll)
        else:
            root.quit()

    poll()
    root.mainloop()
