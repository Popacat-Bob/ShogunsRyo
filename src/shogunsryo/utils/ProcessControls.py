import os
import subprocess
import sys
import time

from pynput.keyboard import Controller as KController, Key, KeyCode
from pynput.mouse import Controller as MController, Button

from shogunsryo.ptypes.Generic import Coords

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

if IS_WINDOWS:
    import ctypes

    import psutil
    import win32con
    import win32gui
    import win32process

    
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def _ease_in_out(t):
    return t * t * (3 - 2 * t)


class PC:
    '''
    A Process Controller meant for handling controls of a specific process.

    Backends:
      - Linux (X11 only): windows are found by WM_CLASS via xdotool (`pclass`).
      - Windows: windows are found by process name via pywin32/psutil (`pname`).
    '''

    def __init__(self, pname: str = "sober", pclass: str = "sober"):
        self.pname = pname
        self.pclass = pclass
        self.mouse = MController()
        self.keyb = KController()

        if IS_LINUX and (
            os.environ.get("XDG_SESSION_TYPE") == "wayland"
            and not os.environ.get("DISPLAY")
        ):
            raise RuntimeError(
                "Wayland session without X11 detected. pynput and xdotool need "
                "an X11 display (run under Xorg, Xvfb, or XWayland)."
            )

    def _delta(self, target: Coords) -> tuple[int, int]:
        x, y = self.mouse.position
        return (target.x - x, target.y - y)

    # ------------------------------------------------------------------ focus

    def focus(self):
        '''
        Focuses the window of the corresponding process.
        Returns the window id (X11 window id or Windows HWND).
        '''
        if IS_LINUX:
            return self._focus_x11()
        if IS_WINDOWS:
            return self._focus_win32()
        raise NotImplementedError(f"focus() is not implemented for {sys.platform!r}")

    def _focus_x11(self):
        r = subprocess.run(
            ["xdotool", "search", "--onlyvisible", "--class", self.pclass],
            capture_output=True, text=True,
        )
        ids = r.stdout.split()
        if not ids:
            raise RuntimeError(f"No window with class {self.pclass!r}")
        wid = ids[0]
        subprocess.run(
            ["xdotool", "windowactivate", "--sync", wid],
            check=True,
        )
        time.sleep(0.2)
        return wid

    def _focus_win32(self):
        target = self.pname.lower()
        if target.endswith(".exe"):
            target = target[:-4]

        found = []

        def cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            if not win32gui.GetWindowText(hwnd):      
                return True
            if win32gui.GetWindow(hwnd, win32con.GW_OWNER):  
                return True
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                name = psutil.Process(pid).name().lower()
            except psutil.Error:
                return True
            if name.endswith(".exe"):
                name = name[:-4]
            if name == target:
                l, t, r, b = win32gui.GetWindowRect(hwnd)
                found.append(((r - l) * (b - t), hwnd))
            return True

        win32gui.EnumWindows(cb, None)
        if not found:
            raise RuntimeError(f"No window for process {self.pname!r}")

        hwnd = max(found)[1]  # largest matching window is most likely the main one

        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            # Windows blocks foreground changes unless input was just sent;
            # tapping Alt satisfies that restriction.
            self.keyb.tap(Key.alt)
            win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.2)
        return hwnd

    # ------------------------------------------------------------------ mouse

    def move_to(self, c: Coords, duration=0.4, steps=40, ease=_ease_in_out):
        steps = max(1, steps)
        sx, sy = self.mouse.position
        x, y = c.x, c.y
        for i in range(1, steps + 1):
            t = ease(i / steps)
            self.mouse.position = (round(sx + (x - sx) * t),
                                   round(sy + (y - sy) * t))
            time.sleep(duration / steps)

    def click(self, c: Coords | None = None, n: int = 1):
        if c:
            self.move_to(c)
        self.mouse.click(Button.left, n)

    def scroll(self, clicks: int, c: Coords | None = None, delay=0.03):
        '''
        Positive = up, negative = down. Optionally move to pos first.
        '''
        if c is not None:
            self.mouse.position = (c.x, c.y)
            time.sleep(0.05)
        step = 1 if clicks > 0 else -1
        for _ in range(abs(clicks)):
            self.mouse.scroll(0, step)
            time.sleep(delay)

    # --------------------------------------------------------------- keyboard

    def press(self, key: KeyCode | Key):
        self.keyb.press(key)

    def release(self, key: KeyCode | Key):
        self.keyb.release(key)

    def ktap(self, key: KeyCode | Key):
        self.keyb.tap(key)
