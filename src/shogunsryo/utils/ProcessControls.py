import subprocess 
import time
from pynput.keyboard import Controller as KController, KeyCode
from pynput.mouse import Controller as MController, Button

from shogunsryo.ptypes.Generic import Coords

def _ease_in_out(t):
    return t * t * (3 - 2 * t)   

class PC:
    '''
    A Process Controller meant for handling controls of a specific process
    '''
    def __init__(self, pname: str = "sober", pclass: str = "sober"):
        self.pname = pname
        self.pclass = pclass 
        self.mouse = MController()
        self.keyb = KController()

    
    def _delta(self, target: Coords) -> tuple[int, int]:
        x, y = self.mouse.position
        tx, ty = target.x, target.y
        return (tx - x, ty - y)

       # smoothstep
    
    def focus(self):
        ''' 
        Focuses the window of the corresponding process class 
        '''
        r = subprocess.run(
            ["xdotool", "search", "--class", self.pclass],
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

    def move_to(self, c: Coords, duration=0.4, steps=40, ease=_ease_in_out):
        sx, sy = self.mouse.position
        x, y = c.x, c.y
        for i in range(1, steps + 1):
            t = ease(i / steps)
            self.mouse.position = (round(sx + (x - sx) * t),
                              round(sy + (y - sy) * t))
        time.sleep(duration / steps)

    def click(self, c: Coords | None = None, n: int = 1):
        if c: self.move_to(c)
        self.mouse.click(Button.left, n)
    
    def press(self, key: KeyCode):
        self.keyb.press(key)

    def ktap(self, key: KeyCode):
        self.keyb.tap(key)

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
