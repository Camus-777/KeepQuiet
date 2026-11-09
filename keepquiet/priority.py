"""Elevate only the audio worker; restore every setting on exit."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import sys


@contextmanager
def audio_priority():
    info = {"process": "normal", "thread": "normal", "error": None}
    if sys.platform != "win32":
        yield info
        return
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    avrt = ctypes.WinDLL("avrt", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetPriorityClass.argtypes = [wintypes.HANDLE]
    kernel.GetPriorityClass.restype = wintypes.DWORD
    kernel.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    avrt.AvSetMmThreadCharacteristicsW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    avrt.AvSetMmThreadCharacteristicsW.restype = wintypes.HANDLE
    avrt.AvSetMmThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
    avrt.AvRevertMmThreadCharacteristics.argtypes = [wintypes.HANDLE]
    proc = kernel.GetCurrentProcess()
    old = kernel.GetPriorityClass(proc)
    handle = None
    try:
        if kernel.SetPriorityClass(proc, 0x80):  # HIGH_PRIORITY_CLASS, never REALTIME
            info["process"] = "High"
        task = wintypes.DWORD()
        handle = avrt.AvSetMmThreadCharacteristicsW("Pro Audio", ctypes.byref(task))
        if handle:
            if avrt.AvSetMmThreadPriority(handle, 2):  # AVRT_PRIORITY_CRITICAL
                info["thread"] = "MMCSS Pro Audio / Critical"
            else:
                info["thread"] = "MMCSS Pro Audio"
        if not handle or info["process"] == "normal":
            info["error"] = f"部分优先级设置未生效 (Win32 {ctypes.get_last_error()})"
        yield info
    finally:
        if handle:
            avrt.AvRevertMmThreadCharacteristics(handle)
        if old:
            kernel.SetPriorityClass(proc, old)
