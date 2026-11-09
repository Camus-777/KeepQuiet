"""Local settings and Windows user-bound voiceprint encryption."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import math


def data_dir() -> Path:
    root = Path(os.environ.get("KEEPQUIET_DATA_DIR") or
                Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "KeepQuiet")
    root.mkdir(parents=True, exist_ok=True)
    return root


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path: Path, value) -> None:
    atomic_bytes(path, json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))


def _backup_invalid(path):
    path.rename(path.with_name(f"{path.name}.invalid-{time.time_ns()}"))


def read_json(path: Path, default=None, *, on_invalid=None):
    try:
        value = json.loads(path.read_text("utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        return value
    except FileNotFoundError:
        return default
    except (ValueError, UnicodeError):
        _backup_invalid(path)
        if on_invalid:
            on_invalid()
        return default


def read_settings(path: Path, *, on_invalid=None):
    settings = read_json(path, {}, on_invalid=on_invalid) or {}
    enums = {
        'theme': ('dark', 'light'),
        'purity_mode': ('natural', 'balanced', 'ultra', 'custom'),
        'filter_mode': ('natural', 'balanced', 'ultra'),
        'custom_filter_mode': ('natural', 'balanced', 'ultra'),
    }
    numbers = {'gate_threshold_db', 'output_gain_db', 'custom_gate_threshold_db',
               'custom_output_gain_db', 'last_driver_check'}
    invalid = []
    for key, value in settings.items():
        valid = True
        if key in enums:
            valid = isinstance(value, str) and value in enums[key]
        elif key in numbers:
            try:
                valid = type(value) in (int, float) and math.isfinite(value)
            except OverflowError:
                valid = False
            if key == 'last_driver_check' and valid:
                valid = value >= 0
        elif key == 'profile_schema':
            valid = type(value) is int and value >= 0
        elif key in ('auto_driver', 'check_driver_updates'):
            valid = type(value) is bool
        elif key in ('input_device', 'output_device'):
            valid = isinstance(value, dict) and isinstance(value.get('host'), str) and bool(value['host'])
            if valid:
                valid = all(isinstance(value.get(field), str) for field in ('name', 'endpoint_id') if field in value)
                valid = valid and bool(value.get('endpoint_id') or value.get('name'))
        if not valid:
            invalid.append(key)
    if invalid:
        _backup_invalid(path)
        for key in invalid:
            del settings[key]
        write_json(path, settings)
        if on_invalid:
            on_invalid()
    return settings


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def protect(data: bytes, decrypt: bool = False) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("声纹加密需要 Windows DPAPI。")
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, target = Blob(len(data), buf), Blob()
    if decrypt:
        fn = crypt.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        fn = crypt.CryptProtectData
        fn.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = fn(ctypes.byref(source), "KeepQuiet voiceprint", None, None, None, 1,
                ctypes.byref(target))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def save_voiceprint(value: dict) -> None:
    atomic_bytes(data_dir() / "voiceprint.protected", protect(json.dumps(value).encode()))


def load_voiceprint():
    path = data_dir() / "voiceprint.protected"
    if not path.exists():
        raise RuntimeError("请先录入目标声线。输出保持静音。")
    import alkove
    voice = alkove.Voiceprint.from_json(json.loads(protect(path.read_bytes(), decrypt=True)))
    if voice is None:
        raise RuntimeError("声纹与当前模型版本不兼容，请重新录入。")
    return voice


def forget_voiceprint() -> None:
    (data_dir() / "voiceprint.protected").unlink(missing_ok=True)
