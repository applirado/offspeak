"""macOS counterparts of winapi: clipboard, paste, active app, autostart, single instance and permissions."""

import fcntl
import os
import plistlib
import subprocess
from pathlib import Path

import AppKit
import Quartz

from offspeak.config import DATA_DIR

# clipboard managers leave items of this type out of their history, like Win+V does with OffSpeak's text
TRANSIENT_TYPE = "org.nspasteboard.TransientType"
KEY_V = 9  # kVK_ANSI_V
LAUNCH_AGENT = Path.home() / "Library" / "LaunchAgents" / "com.applirado.offspeak.plist"
SETTINGS_ACCESSIBILITY = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
SETTINGS_MICROPHONE = "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"


def _pasteboard():
    return AppKit.NSPasteboard.generalPasteboard()


def clipboard_sequence() -> int:
    return _pasteboard().changeCount()


def snapshot_clipboard() -> list[dict[str, bytes]]:
    """Every item on the clipboard with all its types, only to put it back after pasting."""
    items = []
    for item in _pasteboard().pasteboardItems() or []:
        types = {}
        for t in item.types():
            data = item.dataForType_(t)
            if data is not None:
                types[str(t)] = bytes(data)
        items.append(types)
    return items


def restore_clipboard(snapshot: list[dict[str, bytes]]) -> None:
    pb = _pasteboard()
    pb.clearContents()
    items = []
    for types in snapshot:
        item = AppKit.NSPasteboardItem.alloc().init()
        for t, data in types.items():
            item.setData_forType_(AppKit.NSData.dataWithBytes_length_(data, len(data)), t)
        items.append(item)
    if items:
        pb.writeObjects_(items)


def set_clipboard_text(text: str, transient: bool = False) -> int:
    pb = _pasteboard()
    pb.declareTypes_owner_([AppKit.NSPasteboardTypeString] + ([TRANSIENT_TYPE] if transient else []), None)
    pb.setString_forType_(text, AppKit.NSPasteboardTypeString)
    if transient:
        pb.setString_forType_("", TRANSIENT_TYPE)
    return pb.changeCount()


def send_cmd_v() -> None:
    source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    for down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(source, KEY_V, down)
        # only Command, even if the user still holds Option from the shortcut
        Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def foreground_app() -> dict:
    app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return {}
    return {"name": app.localizedName() or "", "path": app.bundleIdentifier() or "", "title": "",
            "pid": app.processIdentifier()}


def accessibility_trusted(prompt: bool = False) -> bool:
    """Whether OffSpeak may watch the shortcut and paste; with prompt, macOS asks the user once."""
    from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt

    return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: prompt}))


def open_accessibility_settings() -> None:
    subprocess.Popen(["open", SETTINGS_ACCESSIBILITY])


def open_microphone_settings() -> None:
    subprocess.Popen(["open", SETTINGS_MICROPHONE])


_instance_lock = None


def acquire_single_instance(name: str) -> bool:
    global _instance_lock
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _instance_lock = open(DATA_DIR / f"{name}.lock", "w")
    try:
        fcntl.flock(_instance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def app_bundle() -> Path:
    """OffSpeak.app, which setup.sh builds in ~/Applications; OFFSPEAK_APP overrides it."""
    return Path(os.environ.get("OFFSPEAK_APP") or Path.home() / "Applications" / "OffSpeak.app")


def get_autostart() -> str | None:
    """What macOS opens at login, or None if OffSpeak does not start automatically."""
    if not LAUNCH_AGENT.exists():
        return None
    return " ".join(plistlib.loads(LAUNCH_AGENT.read_bytes()).get("ProgramArguments", []))


def set_autostart(enabled: bool) -> None:
    if not enabled:
        LAUNCH_AGENT.unlink(missing_ok=True)
        return
    LAUNCH_AGENT.parent.mkdir(parents=True, exist_ok=True)
    LAUNCH_AGENT.write_bytes(plistlib.dumps({
        "Label": "com.applirado.offspeak",
        "ProgramArguments": ["/usr/bin/open", "-a", str(app_bundle())],
        "RunAtLoad": True,
    }))
