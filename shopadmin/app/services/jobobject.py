"""Tiny ctypes wrapper around a Windows Job Object.

Why this exists
---------------
ShopAdmin starts ``ShopSystem.exe`` (the shopapi service) as a child process.
If ShopAdmin itself crashes or is killed from Task Manager, an ordinary child
process would be **orphaned** and keep running invisibly forever — the owner
would have no way to notice or stop it.

By putting the child in a Job Object created with
``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``, Windows itself kills the child when the
last handle to the job closes, which happens automatically when ShopAdmin's
process dies — even on a hard crash. No cleanup code has to run.

On non-Windows platforms (or if the API call fails for any reason) the manager
degrades gracefully: the job object is simply absent and the normal
terminate-then-kill path is used on shutdown.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Optional

from ..logging_setup import get_logger

log = get_logger("jobobject")

IS_WINDOWS = sys.platform.startswith("win")

# --- Win32 constants -------------------------------------------------------
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class JobObject:
    """A Windows job that kills its children when the app dies."""

    def __init__(self) -> None:
        self._handle: Optional[int] = None
        if not IS_WINDOWS:
            return
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateJobObjectW.restype = wintypes.HANDLE
            kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
            handle = kernel32.CreateJobObjectW(None, None)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())

            info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            ok = kernel32.SetInformationJobObject(
                wintypes.HANDLE(handle),
                JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            if not ok:
                raise ctypes.WinError(ctypes.get_last_error())
            self._handle = handle
            self._kernel32 = kernel32
        except Exception as exc:  # noqa: BLE001 - must never break startup
            log.warning("job object unavailable (%s); falling back to normal "
                        "process termination", type(exc).__name__)
            self._handle = None

    @property
    def active(self) -> bool:
        return self._handle is not None

    def assign(self, pid: int) -> bool:
        """Put a running process into the job. Returns True on success."""
        if self._handle is None:
            return False
        try:
            process_handle = self._kernel32.OpenProcess(
                PROCESS_TERMINATE | PROCESS_SET_QUOTA, False, int(pid)
            )
            if not process_handle:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                ok = self._kernel32.AssignProcessToJobObject(
                    wintypes.HANDLE(self._handle), wintypes.HANDLE(process_handle)
                )
                if not ok:
                    raise ctypes.WinError(ctypes.get_last_error())
                return True
            finally:
                self._kernel32.CloseHandle(wintypes.HANDLE(process_handle))
        except Exception as exc:  # noqa: BLE001
            log.warning("could not assign pid=%s to the job object: %s",
                        pid, type(exc).__name__)
            return False

    def close(self) -> None:
        if self._handle is None:
            return
        try:
            self._kernel32.CloseHandle(wintypes.HANDLE(self._handle))
        except Exception:  # pragma: no cover
            pass
        self._handle = None
