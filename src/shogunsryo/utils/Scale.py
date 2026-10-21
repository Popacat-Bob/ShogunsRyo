"""
Screen scaling helper.

All coordinates in the project (Controller click points, defaults.toml frames,
DocCore crop offsets) were measured on a 1920x1080 screen. This module detects
the real screen size so those reference coordinates can be mapped onto it.

Assumes the game fills the whole primary screen (fullscreen / F11).
"""
import sys

REF_W, REF_H = 1920, 1080


def _screen_size() -> tuple[int, int]:
    if sys.platform == "win32":
        import ctypes

        # Report real pixels (not DPI-scaled ones). Safe to call more than once.
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass
        user32 = ctypes.windll.user32
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    return REF_W, REF_H


SCREEN_W, SCREEN_H = _screen_size()
SX = SCREEN_W / REF_W
SY = SCREEN_H / REF_H

print(f"INFO: Screen {SCREEN_W}x{SCREEN_H} (scale x{SX:.3f}, y{SY:.3f} vs 1920x1080)")
if abs(SX - SY) > 0.01:
    print("WARN: Screen is not 16:9, so positions may be slightly off.")
