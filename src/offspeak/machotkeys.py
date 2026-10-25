"""Option+Space push-to-talk and Esc to cancel on macOS (preview: the shortcut is fixed)."""

from typing import Callable

import Quartz
from pynput import keyboard

KEY_SPACE, KEY_ESCAPE = 49, 53  # kVK_Space, kVK_ANSI_Escape
OTHER_MODIFIERS = Quartz.kCGEventFlagMaskCommand | Quartz.kCGEventFlagMaskControl | Quartz.kCGEventFlagMaskShift
SHORTCUT_LABEL = "⌥ Space"


class MacHotkeys:
    """Calls on_event("ptt", "down"/"up") and on_event("cancel", "down"); the keys it uses never reach the app."""

    def __init__(self, on_event: Callable[[str, str], None], cancel_enabled: Callable[[], bool]):
        self.on_event = on_event
        self.cancel_enabled = cancel_enabled
        self.held = False
        self.listener: keyboard.Listener | None = None

    def start(self) -> None:
        self.listener = keyboard.Listener(darwin_intercept=self._intercept)
        self.listener.start()

    def stop(self) -> None:
        if self.listener:
            self.listener.stop()

    def _intercept(self, event_type, event):
        code = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        if code == KEY_SPACE:
            if event_type == Quartz.kCGEventKeyDown:
                flags = Quartz.CGEventGetFlags(event)
                if self.held:
                    return None  # key repeat while held
                if flags & Quartz.kCGEventFlagMaskAlternate and not flags & OTHER_MODIFIERS:
                    self.held = True
                    self.on_event("ptt", "down")
                    return None
            elif event_type == Quartz.kCGEventKeyUp and self.held:
                # also when Option was let go first
                self.held = False
                self.on_event("ptt", "up")
                return None
        elif code == KEY_ESCAPE and event_type == Quartz.kCGEventKeyDown and self.cancel_enabled():
            self.on_event("cancel", "down")
            return None
        return event
