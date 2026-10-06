import time
from paddleocr import PaddleOCR
from google import genai
from pynput.keyboard import KeyCode, Listener as KListener

from shogunsryo.Controller import Controller
from shogunsryo.DocCore import DocCore
from shogunsryo.utils.ProcessControls import PC
from shogunsryo.utils.ScreenCapture import ScreenCapture
from shogunsryo.utils.TextExtractor import TextExtractor


def main():
    te = TextExtractor(
            PaddleOCR(
                lang="en",
                enable_mkldnn=False,
                text_det_box_thresh=0.4,
                text_det_thresh=0.2,
                text_det_unclip_ratio=2.0,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                )
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
