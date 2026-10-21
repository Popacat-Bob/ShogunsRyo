import os
import subprocess
import sys
import time

from pynput.keyboard import Controller as KController, Key, KeyCode
from pynput.mouse import Controller as MController, Button

from shogunsryo.ptypes.Generic import Coords
from shogunsryo.utils.Scale import SX, SY

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

if IS_WINDOWS:
    import ctypes

    import psutil
    import win32api
    import win32con
    import win32gui
    import win32process

    # Make pynput coordinates match real pixels on scaled displays.
    # Must run before any pynput controller is created.
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass

    # Raw SendInput wheel events (this is what Roblox accepted in the scroll test)
    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long), ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("u", _INPUT_UNION)]

    def _send_wheel(delta: int):
        inp = _INPUT(0, _INPUT_UNION(
            _MOUSEINPUT(0, 0, delta & 0xFFFFFFFF, 0x0800, 0, 0)  # MOUSEEVENTF_WHEEL
        ))
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


# If scrolling works but doesn't go far enough, raise this (2 = twice as far).
SCROLL_MULT = 1

# ---- Mouse speed ------------------------------------------------------------
# "safe" = the timings that were tested to work in Roblox.
# "fast" = about 3x quicker. If clicks or scrolls start missing, go back to safe.
# Choose with the MOUSE_SPEED environment variable (run.bat: set MOUSE_SPEED=fast)
# or by editing the default on the next line. All values are seconds.
_PRESETS = {
    "safe": dict(glide=0.40, steps=40, nudge_a=0.05, nudge_b=0.10, hold=0.08, after=0.05,
                 hover=0.10, wiggle=0.04, wiggle_end=0.20, notch=0.10, scroll_end=0.20),
    "fast": dict(glide=0.15, steps=15, nudge_a=0.02, nudge_b=0.04, hold=0.04, after=0.02,
                 hover=0.05, wiggle=0.015, wiggle_end=0.08, notch=0.05, scroll_end=0.10),
}
SPEED = os.environ.get("MOUSE_SPEED", "safe").strip().lower()
if SPEED not in _PRESETS:
    SPEED = "safe"
T = _PRESETS[SPEED]
print(f"INFO: Mouse speed = {SPEED}")


def _ease_in_out(t):
    # smoothstep
    return t * t * (3 - 2 * t)


class PC:
    '''
    A Process Controller meant for handling controls of a specific process.

    Backends:
      - Linux (X11 only): windows are found by WM_CLASS via xdotool (`pclass`).
      - Windows: windows are found by process name via pywin32/psutil (`pname`).
    '''

    def __init__(self, pname: str | None = None, pclass: str = "sober"):
        # Linux Roblox client is Sober; Windows is RobloxPlayerBeta
        # (Microsoft Store build can show up as Windows10Universal).
        if pname is None:
            pname = "RobloxPlayerBeta" if IS_WINDOWS else "sober"
        self.pname = pname
        self.pclass = pclass
        self._pname_fallbacks = (
            ("RobloxPlayerBeta", "Windows10Universal", "Roblox")
            if IS_WINDOWS else (pname,)
        )
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

    @staticmethod
    def _to_screen(c: Coords) -> tuple[int, int]:
        '''Map a 1920x1080 reference coordinate to the real screen.'''
        return round(c.x * SX), round(c.y * SY)

    def _delta(self, target: Coords) -> tuple[int, int]:
        x, y = self.mouse.position
        tx, ty = self._to_screen(target)
        return (tx - x, ty - y)

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
        targets = []
        for name in (self.pname, *self._pname_fallbacks):
            n = name.lower()
            if n.endswith(".exe"):
                n = n[:-4]
            if n not in targets:
                targets.append(n)

        found = []

        def cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            if not win32gui.GetWindowText(hwnd):      # skip untitled helper windows
                return True
            if win32gui.GetWindow(hwnd, win32con.GW_OWNER):  # skip owned popups
                return True
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                name = psutil.Process(pid).name().lower()
            except psutil.Error:
                return True
            if name.endswith(".exe"):
                name = name[:-4]
            if name in targets:
                l, t, r, b = win32gui.GetWindowRect(hwnd)
                found.append(((r - l) * (b - t), hwnd))
            return True

        win32gui.EnumWindows(cb, None)
        if not found:
            raise RuntimeError(
                f"No window for process {self.pname!r} "
                f"(also tried {list(self._pname_fallbacks)})"
            )

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

    def move_to(self, c: Coords, duration=None, steps=None, ease=_ease_in_out):
        duration = T["glide"] if duration is None else duration
        steps = max(1, T["steps"] if steps is None else steps)
        sx, sy = self.mouse.position
        x, y = self._to_screen(c)
        for i in range(1, steps + 1):
            t = ease(i / steps)
            self.mouse.position = (round(sx + (x - sx) * t),
                                   round(sy + (y - sy) * t))
            time.sleep(duration / steps)

    def click(self, c: Coords | None = None, n: int = 1, hold: float | None = None):
        if c:
            self.move_to(c)
        hold = T["hold"] if hold is None else hold
        # Nudge the cursor so the game receives real mouse-move events
        if IS_WINDOWS:
            # Roblox ignores pynput's clicks; win32api's mouse_event works.
            win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, 1, 0, 0, 0)
            time.sleep(T["nudge_a"])
            win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, -1, 0, 0, 0)
            time.sleep(T["nudge_b"])
            for _ in range(n):
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                time.sleep(hold)  # hold the button so the game registers it
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                time.sleep(T["after"])
            return
        self.mouse.move(1, 0)
        time.sleep(T["nudge_a"])
        self.mouse.move(-1, 0)
        time.sleep(T["nudge_b"])
        for _ in range(n):
            self.mouse.press(Button.left)
            time.sleep(hold)
            self.mouse.release(Button.left)
            time.sleep(T["after"])

    def scroll(self, clicks: int, c: Coords | None = None, delay=None):
        '''
        Positive = up, negative = down. Optionally move to pos first.
        '''
        delay = T["notch"] if delay is None else delay
        if c is not None:
            self.mouse.position = self._to_screen(c)
            time.sleep(T["hover"])
            if IS_WINDOWS:
                # Roblox only scrolls a panel once it has seen the cursor move
                # over it, so wiggle the cursor after placing it (net zero).
                for dx in (4, 4, 4, 4, -4, -4, -4, -4):
                    win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, dx, 0, 0, 0)
                    time.sleep(T["wiggle"])
                time.sleep(T["wiggle_end"])
        step = 1 if clicks > 0 else -1
        for _ in range(abs(clicks) * SCROLL_MULT):
            if IS_WINDOWS:
                _send_wheel(120 * step)  # one wheel notch is 120 units
            else:
                self.mouse.scroll(0, step)
            time.sleep(delay)
        time.sleep(T["scroll_end"])  # let the panel finish moving

    # --------------------------------------------------------------- keyboard

    def press(self, key: KeyCode | Key):
        self.keyb.press(key)

    def release(self, key: KeyCode | Key):
        self.keyb.release(key)

    def ktap(self, key: KeyCode | Key):
        self.keyb.tap(key)
