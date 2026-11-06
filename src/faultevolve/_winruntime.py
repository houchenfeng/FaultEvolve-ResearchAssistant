"""Make CUDA torch importable from an Anaconda-based venv on Windows.

Anaconda ships MSVC runtime 14.29 next to python.exe, which wins the DLL search
and makes torch>=2.5's c10.dll fail with WinError 1114. Pinning the system copy
works only if it is loaded before anything else pulls in msvcp140 (numpy, pandas,
lightgbm), so this runs from the package root.
"""

from __future__ import annotations

import ctypes
import os
import sys


def prefer_system_msvc_runtime() -> None:
    if sys.platform != "win32":
        return
    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    for name in ("vcruntime140_1.dll", "msvcp140.dll", "msvcp140_1.dll"):
        path = os.path.join(system32, name)
        if os.path.exists(path):
            try:
                ctypes.WinDLL(path)
            except OSError:
                pass
