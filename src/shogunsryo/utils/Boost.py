"""
Windows only. Keeps this program's OCR from being slowed down while the game is in front.

The OCR measured 0.8 seconds for a letter when this program's window was in front, but 30+
seconds while Roblox was fullscreen in front of it. Windows treats the program behind a game
differently in three ways, and each can be switched off for our own process. None of this changes
what the OCR reads, only how quickly Windows lets it run.

  1. CPU priority   -> HIGH      (the game otherwise wins every scheduling decision)
  2. Power throttling -> OFF     (Windows can push a background program onto slow "efficiency" cores)
  3. GPU scheduling priority -> HIGH  (the GPU is shared with the game; ours queues behind it)

Needs administrator rights for the GPU part, which run.bat already asks for. Each step is tried
on its own, so one failing doesn't stop the others. Turn it all off with BOOST=0.
"""
import ctypes
import sys


class _PowerThrottling(ctypes.Structure):
    _fields_ = [("Version", ctypes.c_ulong), ("ControlMask", ctypes.c_ulong), ("StateMask", ctypes.c_ulong)]


def apply() -> str:
    """Returns a one-line summary of what worked."""
    if sys.platform != "win32":
        return "not Windows, nothing to do"

    results: list[str] = []
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    handle = k32.GetCurrentProcess()

    # 1. CPU priority class: HIGH_PRIORITY_CLASS = 0x80
    try:
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        k32.SetPriorityClass.restype = ctypes.c_int
        results.append("CPU priority high: " + ("ok" if k32.SetPriorityClass(handle, 0x80) else "refused"))
    except Exception as e:
        results.append(f"CPU priority high: failed ({type(e).__name__})")

    # 2. Opt out of power throttling: ProcessPowerThrottling = 4, EXECUTION_SPEED = 0x1, state 0 = never throttle
    try:
        k32.SetProcessInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
        k32.SetProcessInformation.restype = ctypes.c_int
        state = _PowerThrottling(1, 0x1, 0x0)
        ok = k32.SetProcessInformation(handle, 4, ctypes.byref(state), ctypes.sizeof(state))
        results.append("power throttling off: " + ("ok" if ok else "refused"))
    except Exception as e:
        results.append(f"power throttling off: failed ({type(e).__name__})")

    # 3. GPU scheduling priority class: D3DKMT_SCHEDULINGPRIORITYCLASS_HIGH = 4 (0 = success)
    try:
        fn = ctypes.windll.gdi32.D3DKMTSetProcessSchedulingPriorityClass
        fn.argtypes = [ctypes.c_void_p, ctypes.c_int]
        fn.restype = ctypes.c_long
        status = fn(handle, 4)
        results.append("GPU priority high: " + ("ok" if status == 0 else f"refused (0x{status & 0xFFFFFFFF:08X})"))
    except Exception as e:
        results.append(f"GPU priority high: failed ({type(e).__name__})")

    return ", ".join(results)
