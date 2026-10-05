import time
import easyocr
from google import genai
from pynput.keyboard import KeyCode, Listener as KListener

from shogunsryo.Controller import Controller
from shogunsryo.DocCore import DocCore
from shogunsryo.utils.ProcessControls import PC
from shogunsryo.utils.ScreenCapture import ScreenCapture
from shogunsryo.utils.TextExtractor import TextExtractor


def main():
    te = TextExtractor(
            easyocr.Reader(["en"], gpu=False) 
            )
    control = Controller(
        dc=DocCore(te=te),
        pc=PC(),
        client=genai.Client()
    )

    def on_p(key):
        if getattr(key, "char", None) == "p":
            control.toggle_enabled()
            print(f"Toggled {'On' if control.enabled else 'Off'}")

    listener = KListener(
        on_press=on_p
    )

    listener.start()
    while True:
        control.loop()

if __name__ == "__main__": main()
