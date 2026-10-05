import time
from ollama import Client
from pynput.keyboard import KeyCode, Listener as KListener

from shogunsryo.Controller import Controller
from shogunsryo.DocCore import DocCore
from shogunsryo.utils.ProcessControls import PC
from shogunsryo.utils.ScreenCapture import ScreenCapture


def main():
    olla = Client(
        host="http://localhost:11434"
    )

    control = Controller(
        dc=DocCore(),
        pc=PC(),
        ollama=olla
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
