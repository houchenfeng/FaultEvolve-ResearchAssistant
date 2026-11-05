"""Process liveness, shared by the run claim and the Web run registry.

One implementation on purpose: two copies of a pid check drift apart, and the
answer decides whether a resume is allowed to start a second execution of the
same run.
"""

from __future__ import annotations

import ctypes
import os


def pid_alive(pid: int | None) -> bool | None:
    """Whether ``pid`` names a live process. ``None`` when unknowable.

    ``None`` rather than ``False`` matters: a remote handle has no local pid, and
    reporting a remote run as dead would be a claim this machine cannot support.
    """
    if pid is None or pid <= 0:
        return None
    if os.name == "nt":
        # OpenProcess + GetExitCodeProcess: no tasklist round-trip, no psutil.
        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(
            process_query_limited_information, False, int(pid)
        )
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return None
            return code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Alive, just not ours to signal.
        return True
    except OSError:
        return None
    return True
