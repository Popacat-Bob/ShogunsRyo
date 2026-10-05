import subprocess
import pyautogui
from pynput import keyboard

def copy(text):
    subprocess.run(
        ["xclip", "-selection", "clipboard"],
        input=text.encode(),
        check=True,
    )

def on_press(key):
    if getattr(key, "char", None) == "p":
        x, y = pyautogui.position()
        r, g, b = pyautogui.pixel(x, y)
        copy(f"{x}, {y} | RGB: [{r}, {g}, {b}]")
        subprocess.run(["notify-send", "Copied", f"{x}, {y} | RGB: [{r}, {g}, {b}]"])
    elif key == keyboard.Key.esc:
        return False
with keyboard.Listener(on_press=on_press) as listener:
    listener.join()
