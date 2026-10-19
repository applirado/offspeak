import ctypes
import time
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


def set_clipboard_text(text: str) -> bool:
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
    if not handle:
        return False
    ptr = kernel32.GlobalLock(handle)
    ctypes.memmove(ptr, data, size)
    kernel32.GlobalUnlock(handle)
    if not _open_clipboard():
        kernel32.GlobalFree(handle)
        return False
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            return False
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
    return {"name": Path(exe).stem if exe else "", "path": exe, "title": title.value}


def make_no_activate(hwnd: int) -> None:
    GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST = -20, 0x08000000, 0x00000080, 0x00000008
    get = user32.GetWindowLongPtrW
    get.argtypes, get.restype = [wintypes.HWND, ctypes.c_int], ctypes.c_ssize_t
    put = user32.SetWindowLongPtrW
    put.argtypes, put.restype = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t
    put(hwnd, GWL_EXSTYLE, get(hwnd, GWL_EXSTYLE) | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)


_instance_mutex = None


def acquire_single_instance(name: str) -> bool:
    global _instance_mutex
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    _instance_mutex = kernel32.CreateMutexW(None, False, name)
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except OSError:
        pass
