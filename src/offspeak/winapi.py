import ctypes
import subprocess
import sys
import time
import winreg
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL, VK_V = 0x11, 0x56

user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
user32.EnumClipboardFormats.restype = wintypes.UINT
user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
user32.RegisterClipboardFormatW.restype = wintypes.UINT
kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def _open_clipboard() -> bool:
    for _ in range(20):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.02)
    return False


def get_clipboard_text() -> str | None:
    if not _open_clipboard():
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _global_from_bytes(data: bytes):
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, max(1, len(data)))
    if not handle:
        return None
    ptr = kernel32.GlobalLock(handle)
    ctypes.memmove(ptr, data, len(data))
    kernel32.GlobalUnlock(handle)
    return handle


def _put(fmt: int, data: bytes) -> bool:
    """SetClipboardData with a fresh global copy; the clipboard must be open."""
    handle = _global_from_bytes(data)
    if handle and user32.SetClipboardData(fmt, handle):
        return True
    if handle:
        kernel32.GlobalFree(handle)
    return False


def _mark_transient() -> None:
    """Keep this content out of the Win+V clipboard history and cloud clipboard."""
    for name in ("ExcludeClipboardContentFromMonitorProcessing", "CanIncludeInClipboardHistory",
                 "CanUploadToCloudClipboard"):
        _put(user32.RegisterClipboardFormatW(name), (0).to_bytes(4, "little"))


def clipboard_sequence() -> int:
    return user32.GetClipboardSequenceNumber()


def set_clipboard_text(text: str, transient: bool = False) -> int | None:
    """Replace the clipboard with text; returns the clipboard sequence number afterwards, or None."""
    if not _open_clipboard():
        return None
    try:
        user32.EmptyClipboard()
        if not _put(CF_UNICODETEXT, (text + "\0").encode("utf-16-le")):
            return None
        if transient:
            _mark_transient()
    finally:
        user32.CloseClipboard()
    return clipboard_sequence()


# Formats whose handles are GDI objects or owned by the source app; Windows re-synthesises CF_BITMAP from CF_DIB.
_UNCOPYABLE = {2, 3, 9, 14, 0x80, 0x82, 0x83, 0x8E, *range(0x200, 0x400)}
SNAPSHOT_LIMIT = 256 << 20


def snapshot_clipboard() -> list[tuple[int, bytes]] | None:
    """Copy every memory-based clipboard format (text, images, HTML, RTF, files, ...), or None if unavailable."""
    if not _open_clipboard():
        return None
    formats, total, fmt = [], 0, 0
    try:
        while fmt := user32.EnumClipboardFormats(fmt):
            if fmt in _UNCOPYABLE:
                continue
            handle = user32.GetClipboardData(fmt)
            size = kernel32.GlobalSize(handle) if handle else 0
            ptr = kernel32.GlobalLock(handle) if size else None
            if not ptr:
                continue
            try:
                formats.append((fmt, ctypes.string_at(ptr, size)))
            finally:
                kernel32.GlobalUnlock(handle)
            total += size
            if total > SNAPSHOT_LIMIT:
                return None
        return formats
    finally:
        user32.CloseClipboard()


def restore_clipboard(snapshot: list[tuple[int, bytes]]) -> bool:
    if not _open_clipboard():
        return False
    try:
        user32.EmptyClipboard()
        for fmt, data in snapshot:
            _put(fmt, data)
        if snapshot:
            _mark_transient()  # the original copy is already in the history
        return True
    finally:
        user32.CloseClipboard()


def send_ctrl_v() -> None:
    events = [(VK_CONTROL, 0), (VK_V, 0), (VK_V, KEYEVENTF_KEYUP), (VK_CONTROL, KEYEVENTF_KEYUP)]
    inputs = (INPUT * len(events))()
    for i, (vk, flags) in enumerate(events):
        inputs[i].type = INPUT_KEYBOARD
        inputs[i].u.ki = KEYBDINPUT(wVk=vk, dwFlags=flags)
    user32.SendInput(len(events), inputs, ctypes.sizeof(INPUT))


def foreground_app() -> dict:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return {}
    title = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title, 512)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = ""
    proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if proc:
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(proc, 0, buf, ctypes.byref(size)):
                exe = buf.value
        finally:
            kernel32.CloseHandle(proc)
    return {"name": Path(exe).stem if exe else "", "path": exe, "title": title.value, "pid": pid.value}


def make_no_activate(hwnd: int) -> None:
    GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST = -20, 0x08000000, 0x00000080, 0x00000008
    get = user32.GetWindowLongPtrW
    get.argtypes, get.restype = [wintypes.HWND, ctypes.c_int], ctypes.c_ssize_t
    put = user32.SetWindowLongPtrW
    put.argtypes, put.restype = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t
    put(hwnd, GWL_EXSTYLE, get(hwnd, GWL_EXSTYLE) | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)


def remove_caption(hwnd: int) -> None:
    """Hide the native title bar but keep the resizable frame, shadow and taskbar button (Win 11: round corners)."""
    GWL_STYLE, WS_CAPTION = -16, 0x00C00000
    SWP_FLAGS = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020  # NOSIZE NOMOVE NOZORDER NOACTIVATE FRAMECHANGED
    get = user32.GetWindowLongPtrW
    get.argtypes, get.restype = [wintypes.HWND, ctypes.c_int], ctypes.c_ssize_t
    put = user32.SetWindowLongPtrW
    put.argtypes, put.restype = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t
    put(hwnd, GWL_STYLE, get(hwnd, GWL_STYLE) & ~WS_CAPTION)
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_FLAGS)
    # the client area moved up by the caption height; repaint it instead of showing shifted pixels
    RDW_INVALIDATE, RDW_ERASE, RDW_FRAME, RDW_ALLCHILDREN, RDW_UPDATENOW = 0x1, 0x4, 0x400, 0x80, 0x100
    user32.RedrawWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    user32.RedrawWindow(hwnd, None, None, RDW_INVALIDATE | RDW_ERASE | RDW_FRAME | RDW_ALLCHILDREN | RDW_UPDATENOW)
    try:
        DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, 2
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                                                   ctypes.byref(ctypes.c_int(DWMWCP_ROUND)), 4)
    except OSError:
        pass  # Windows 10 has square corners


_instance_mutex = None


def acquire_single_instance(name: str) -> bool:
    global _instance_mutex
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    _instance_mutex = kernel32.CreateMutexW(None, False, name)
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "Offspeak"


def autostart_command() -> str:
    """Console-less command that starts the tray app from the current installation."""
    scripts = Path(sys.executable).parent
    launcher = scripts / "offspeakw.exe"
    if launcher.exists():
        return subprocess.list2cmdline([str(launcher), "run"])
    pythonw = scripts / "pythonw.exe"
    return subprocess.list2cmdline([str(pythonw if pythonw.exists() else sys.executable), "-m", "offspeak", "run"])


def get_autostart() -> str | None:
    """The command Windows runs at sign-in, or None if Offspeak does not start automatically."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, RUN_VALUE)[0]
    except FileNotFoundError:
        return None


def set_autostart(enabled: bool) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass


def enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except OSError:
        pass
