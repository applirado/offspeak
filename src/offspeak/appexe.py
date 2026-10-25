"""OffSpeak.exe: a copy of pythonw.exe with OffSpeak's name and icon.

Windows names a process after its executable's version info, so with plain pythonw.exe the tray icon
shows up as "Python" in the taskbar settings and in Task Manager. A copy of pythonw.exe in its own
folder in the venv, next to the Python DLLs, runs the venv like the original (it finds ..\\pyvenv.cfg).
It cannot live in Scripts: file names ignore case there, and Scripts\\offspeak.exe is the console command.
"""

import ctypes
import filecmp
import shutil
import struct
import sys
import tempfile
from ctypes import wintypes
from importlib.metadata import version
from pathlib import Path

EXE_NAME = "OffSpeak.exe"
RT_ICON, RT_GROUP_ICON, RT_VERSION = 3, 14, 16
LANG_EN_US = 0x0409

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
kernel32.BeginUpdateResourceW.restype = wintypes.HANDLE
kernel32.UpdateResourceW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, wintypes.WORD,
                                     ctypes.c_void_p, wintypes.DWORD]
kernel32.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
kernel32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
kernel32.LoadLibraryExW.restype = wintypes.HMODULE
kernel32.FreeLibrary.argtypes = [wintypes.HMODULE]
ENUM_NAME = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
ENUM_LANG = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p, wintypes.WORD,
                               ctypes.c_void_p)
kernel32.EnumResourceNamesW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, ENUM_NAME, ctypes.c_void_p]
kernel32.EnumResourceLanguagesW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p, ENUM_LANG,
                                            ctypes.c_void_p]


def exe_path() -> Path:
    return Path(sys.prefix) / "OffSpeak" / EXE_NAME


def _pad4(data: bytes) -> bytes:
    return data + b"\0" * (-len(data) % 4)


def _block(key: str, value: bytes = b"", children: list[bytes] = (), text: bool = False) -> bytes:
    """One VS_VERSIONINFO node: wLength, wValueLength, wType, key, value, children, each 4-byte aligned."""
    body = _pad4(b"\0" * 6 + (key + "\0").encode("utf-16-le")) + value
    for child in children:
        body = _pad4(body) + child
    value_length = len(value) // 2 if text else len(value)
    return struct.pack("<3H", len(body), value_length, int(text)) + body[6:]


def version_info(app_version: str) -> bytes:
    parts = [int(p) for p in app_version.split(".")[:4] if p.isdigit()] + [0] * 4
    ms, ls = parts[0] << 16 | parts[1], parts[2] << 16 | parts[3]
    fixed = struct.pack("<13I", 0xFEEF04BD, 0x10000, ms, ls, ms, ls, 0x3F, 0, 0x40004, 1, 0, 0, 0)
    strings = {
        "CompanyName": "Applirado",
        "FileDescription": "OffSpeak",
        "FileVersion": app_version,
        "InternalName": "OffSpeak",
        "LegalCopyright": "MIT License",
        "OriginalFilename": EXE_NAME,
        "ProductName": "OffSpeak",
        "ProductVersion": app_version,
    }
    table = _block("040904B0", children=[_block(k, (v + "\0").encode("utf-16-le"), text=True)
                                         for k, v in strings.items()])
    translation = _block("Translation", struct.pack("<2H", LANG_EN_US, 0x04B0))
    return _block("VS_VERSION_INFO", fixed, [_block("StringFileInfo", children=[table]),
                                             _block("VarFileInfo", children=[translation])])


def icon_resources(ico: bytes) -> tuple[list[bytes], bytes]:
    """The images of an .ico file as RT_ICON resources 1..n, and the RT_GROUP_ICON that lists them."""
    count = struct.unpack_from("<3H", ico)[2]
    images, group = [], struct.pack("<3H", 0, 1, count)
    for i in range(count):
        entry = struct.unpack_from("<4B2H2I", ico, 6 + 16 * i)
        size, offset = entry[6], entry[7]
        images.append(ico[offset:offset + size])
        group += struct.pack("<4B2HIH", *entry[:7], i + 1)
    return images, group


def _existing(path: Path, types: tuple[int, ...]) -> list[tuple[int, int, int]]:
    """(type, name, language) of the resources of these types; names that are strings are left out."""
    module = kernel32.LoadLibraryExW(str(path), None, 0x2)  # LOAD_LIBRARY_AS_DATAFILE
    if not module:
        raise ctypes.WinError(ctypes.get_last_error())
    found = []
    try:
        for rtype in types:
            def on_name(_module, _type, name, _param, rtype=rtype):
                if name is not None and name < 0x10000:  # IS_INTRESOURCE
                    kernel32.EnumResourceLanguagesW(module, rtype, name, on_lang, None)
                return True

            def on_lang(_module, _type, name, lang, _param, rtype=rtype):
                found.append((rtype, name, lang))
                return True

            on_name, on_lang = ENUM_NAME(on_name), ENUM_LANG(on_lang)
            kernel32.EnumResourceNamesW(module, rtype, on_name, None)
    finally:
        kernel32.FreeLibrary(module)
    return found


def brand(path: Path, icon: Path | None, app_version: str) -> None:
    """Replace the version info, and the icon if one is given, of the executable at path."""
    types = (RT_VERSION, RT_ICON, RT_GROUP_ICON) if icon else (RT_VERSION,)
    old = _existing(path, types)
    new = [(RT_VERSION, 1, LANG_EN_US, version_info(app_version))]
    if icon:
        images, group = icon_resources(icon.read_bytes())
        new += [(RT_ICON, i + 1, LANG_EN_US, data) for i, data in enumerate(images)]
        new.append((RT_GROUP_ICON, 1, LANG_EN_US, group))
    handle = kernel32.BeginUpdateResourceW(str(path), False)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    ok = all(kernel32.UpdateResourceW(handle, rtype, name, lang, None, 0) for rtype, name, lang in old)
    ok = ok and all(kernel32.UpdateResourceW(handle, rtype, name, lang, data, len(data))
                    for rtype, name, lang, data in new)
    error = ctypes.get_last_error()
    if not kernel32.EndUpdateResourceW(handle, not ok) or not ok:
        raise ctypes.WinError(error or ctypes.get_last_error())


def create(icon: Path | None = None) -> Path:
    """Create or update OffSpeak.exe in the running venv.

    Files that are already up to date are left alone, so this also works while OffSpeak is running.
    """
    base, target = Path(sys.base_prefix), exe_path()
    if base == Path(sys.prefix):
        raise RuntimeError("OffSpeak.exe can only be created in a virtual environment.")
    target.parent.mkdir(exist_ok=True)
    for dll in base.glob("*.dll"):  # python3.dll, python312.dll and the C runtime
        copy = target.parent / dll.name
        if not (copy.exists() and filecmp.cmp(dll, copy, shallow=False)):
            shutil.copy2(dll, copy)
    with tempfile.TemporaryDirectory() as tmp:
        exe = Path(tmp) / EXE_NAME
        shutil.copyfile(base / "pythonw.exe", exe)
        brand(exe, icon, version("offspeak"))
        if not (target.exists() and filecmp.cmp(exe, target, shallow=False)):
            shutil.copyfile(exe, target)
    return target
