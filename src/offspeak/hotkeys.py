import re
from dataclasses import dataclass
from typing import Callable

from offspeak import winapi

WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
LLKHF_INJECTED = 0x10

MODIFIERS = {
    "ctrl": (0x11, {0x11, 0xA2, 0xA3}),
    "shift": (0x10, {0x10, 0xA0, 0xA1}),
    "alt": (0x12, {0x12, 0xA4, 0xA5}),
    "win": (0x5B, {0x5B, 0x5C}),
}
MODIFIER_ALIASES = {"control": "ctrl", "ctrl": "ctrl", "shift": "shift", "alt": "alt", "option": "alt",
                    "meta": "win", "super": "win", "win": "win", "cmd": "win"}
NAMED_KEYS = {
    "space": 0x20, "escape": 0x1B, "esc": 0x1B, "enter": 0x0D, "return": 0x0D, "tab": 0x09,
    "backspace": 0x08, "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23, "pageup": 0x21,
    "pagedown": 0x22, "pause": 0x13, "scrolllock": 0x91, "capslock": 0x14, "backquote": 0xC0,
    "arrowleft": 0x25, "arrowup": 0x26, "arrowright": 0x27, "arrowdown": 0x28,
    "numpadmultiply": 0x6A, "numpadadd": 0x6B, "numpadsubtract": 0x6D, "numpaddecimal": 0x6E,
    "numpaddivide": 0x6F,
}


VK_NAMES = {
    0x20: "Space", 0x1B: "Escape", 0x0D: "Enter", 0x09: "Tab", 0x08: "Backspace", 0x2D: "Insert",
    0x2E: "Delete", 0x24: "Home", 0x23: "End", 0x21: "PageUp", 0x22: "PageDown", 0x13: "Pause",
    0x91: "ScrollLock", 0x14: "CapsLock", 0xC0: "Backquote", 0x25: "ArrowLeft", 0x26: "ArrowUp",
    0x27: "ArrowRight", 0x28: "ArrowDown", 0x6A: "NumpadMultiply", 0x6B: "NumpadAdd",
    0x6D: "NumpadSubtract", 0x6E: "NumpadDecimal", 0x6F: "NumpadDivide",
}
MODIFIER_VKS = {vk for _, vks in MODIFIERS.values() for vk in vks}
MODIFIER_LABELS = (("ctrl", "Control"), ("shift", "Shift"), ("alt", "Alt"), ("win", "Win"))


@dataclass(frozen=True)
class Hotkey:
    mods: frozenset[str]
    vk: int


def key_name(vk: int) -> str | None:
    if vk in VK_NAMES:
        return VK_NAMES[vk]
    if 0x60 <= vk <= 0x69:
        return f"Numpad{vk - 0x60}"
    if 0x30 <= vk <= 0x39:
        return f"Digit{vk - 0x30}"
    if 0x41 <= vk <= 0x5A:
        return f"Key{chr(vk)}"
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x6F}"
    return None


def format_shortcut(mods: frozenset[str], vk: int) -> str | None:
    """Inverse of parse_shortcut, e.g. ({"ctrl", "shift"}, 0x4D) -> "Control+Shift+KeyM"."""
    name = key_name(vk)
    if name is None:
        return None
    return "+".join([label for mod, label in MODIFIER_LABELS if mod in mods] + [name])


def parse_shortcut(text: str) -> Hotkey | None:
    if not text or not text.strip():
        return None
    mods, key = set(), None
    for raw in text.split("+"):
        token = raw.strip().lower()
        if token in MODIFIER_ALIASES:
            mods.add(MODIFIER_ALIASES[token])
        elif token in NAMED_KEYS:
            key = NAMED_KEYS[token]
        elif m := re.fullmatch(r"(?:numpad|num)(\d)", token):
            key = 0x60 + int(m.group(1))
        elif m := re.fullmatch(r"(?:digit)?(\d)", token):
            key = 0x30 + int(m.group(1))
        elif m := re.fullmatch(r"(?:key)?([a-z])", token):
            key = ord(m.group(1).upper())
        elif m := re.fullmatch(r"f(\d{1,2})", token):
            key = 0x6F + int(m.group(1))
        else:
            raise ValueError(f"Unknown key '{raw}' in shortcut '{text}'")
    if key is None:
        raise ValueError(f"Shortcut '{text}' has no main key")
    return Hotkey(frozenset(mods), key)


def current_modifiers() -> frozenset[str]:
    return frozenset(name for name, (vk, _) in MODIFIERS.items() if winapi.key_down(vk) or
                     (name == "win" and winapi.key_down(0x5C)))


@dataclass
class Binding:
    hotkey: Hotkey
    action: str
    enabled: Callable[[], bool] | None = None


class HotkeyManager:
    """Low-level keyboard hook; matching key presses are swallowed so the focused app never sees them."""

    def __init__(self, on_event: Callable[[str, str], None]):
        self.on_event = on_event
        self.bindings: list[Binding] = []
        self._held: dict[int, Binding] = {}
        self._listener = None
        self.paused = False  # set while the user is typing a new shortcut

    def set_bindings(self, bindings: list[Binding]) -> None:
        self.bindings = bindings

    def start(self) -> None:
        from pynput import keyboard

        self._listener = keyboard.Listener(win32_event_filter=self._filter)
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()

    def _filter(self, msg, data) -> bool:
        if data.flags & LLKHF_INJECTED:
            return False
        vk = data.vkCode
        if msg in (WM_KEYDOWN, WM_SYSKEYDOWN):
            if self.paused:
                return False
            if vk in self._held:
                self._listener.suppress_event()
            mods = current_modifiers()
            for b in self.bindings:
                if b.hotkey.vk == vk and b.hotkey.mods == mods and (b.enabled is None or b.enabled()):
                    self._held[vk] = b
                    self.on_event(b.action, "down")
                    self._listener.suppress_event()
        elif msg in (WM_KEYUP, WM_SYSKEYUP):
            b = self._held.pop(vk, None)
            if b is not None:
                self.on_event(b.action, "up")
                self._listener.suppress_event()
        return False
