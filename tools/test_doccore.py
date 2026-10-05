import subprocess
import pyautogui
from pynput import keyboard
from shogunsryo.DocCore import DocCore

def on_press(key):
    if getattr(key, "char", None) == "p":
        subprocess.run(["notify-send", "Shot"])
        DocCore().loop()
    elif key == keyboard.Key.esc:
        return False

with keyboard.Listener(on_press=on_press) as listener:
    listener.join()
