import tomllib 
from pathlib import Path 
import subprocess 
import time
import numpy as np
import json
import pyautogui

from shogunsryo.ptypes.Generic import Coords, Dimensions, Bbox
from shogunsryo.utils.ScreenCapture import ScreenCapture
from shogunsryo.utils.ProcessControls import PC
from shogunsryo.utils.TextExtractor import TextExtractor

DEFAULTS = Path(__file__).parent / "config" / "defaults.toml"
TEST_DIR = Path(__file__).parent / "test/"
TEST_DIR_S = f"{TEST_DIR}"

INTEGER_WHITELIST="0123456789"

class DocCore:
    def __init__(self, te: TextExtractor, path=DEFAULTS):
        with open(path, "rb") as f:
            data = tomllib.load(f)

        self.sd = Dimensions(*data["Screen"]["resolution"])
        self.n_b = Bbox(*[Coords(*data["Frames"]["narrative"][i:i+2]) for i in range(0, 4, 2)])
        self.md_b = Bbox(*[Coords(*data["Frames"]["misc_details"][i:i+2]) for i in range(0, 4, 2)])
        self.q_b = Bbox(*[Coords(*data["Frames"]["questions"][i:i+2]) for i in range(0, 4, 2)])
        self.vf = Bbox(*[Coords(*data["Frames"]["verify_frame"][i:i+2]) for i in range(0, 4, 2)])

        self.SC = ScreenCapture(self.sd)
        self.PC = PC()
        self.TE = te
    
    
    def extractField(
            self, 
            img: np.ndarray, 
            coords = None, 
            wl: str | None = None,
            ):
        crop = img
        if coords: 
            crop = img[coords[0]:coords[1], coords[2]:coords[3]]

        if wl:
            return self.TE.extractFromImg(
                    crop,
                    ).strip()

        return self.TE.extractFromImg(crop).strip()


    def _extractFText(
            self,
            md0: np.ndarray,
            md1: np.ndarray,
            md2: np.ndarray,
            nar: np.ndarray,
            q: np.ndarray,
        ):
        # [y1, y2, x1, x2]
        return {
            "Meta": {
                "Signed On": self.extractField(
                    md0, (31, 51, 373, 413),
                    wl=INTEGER_WHITELIST
                ),
                "Times Written": self.extractField(
                    md0, (66, 87, 370, 415),
                ),
                "Today": self.extractField(
                    md0, (100, 122, 373, 415),
                    wl=INTEGER_WHITELIST
                ),
            },
            "Letter": {
                "From": self.extractField(nar, (3, 30, 3, 267)),
                "Intent": self.extractField(nar, (30, 48, 3, 394)),
                "Seal Color": self.extractField(nar, (169, 191, 55, 362)),
                "Body": self.extractField(nar, (62, 149, 3, 381)),
            },
            "Shisato": {
                "Ryo": self.extractField(
                    md0, (166, 185, 364, 414),
                    wl=INTEGER_WHITELIST
                ),
                "Head": self.extractField(md0, (196, 219, 63, 131)),
                "Houses": self.extractField(
                    md0, (199, 219, 339, 416),
                    wl=INTEGER_WHITELIST
                ),
                "Color": self.extractField(nar, (169, 191, 289, 362)),
            },
            "Kotobe": {
                "Ryo": self.extractField(
                    md1, (32, 50, 361, 412),
                    wl=INTEGER_WHITELIST
                ),
                "Head": self.extractField(md1, (63, 83, 64, 107)),
                "Houses": self.extractField(
                    md1, (64, 83, 336, 413),
                    wl=INTEGER_WHITELIST
                ),
                "Color": self.extractField(nar, (32, 52, 286, 362)),
            },
            "Farmers": {
                "Ryo": self.extractField(
                    md1, (93, 115, 357, 411),
                    wl=INTEGER_WHITELIST
                ),
                "Head": self.extractField(md1, (125, 144, 65, 109)),
                "Houses": self.extractField(
                    md1, (125, 145, 338, 418),
                    wl=INTEGER_WHITELIST
                ),
                "Color": self.extractField(nar, (92, 113, 287, 358)),
            },
            "Market": {
                "Ryo": self.extractField(
                    md2, (45, 65, 355, 412),
                    wl=INTEGER_WHITELIST
                ),
                "Head": self.extractField(md2, (67, 96, 64, 105)),
                "Houses": self.extractField(
                    md2, (75, 97, 339, 411),
                    wl=INTEGER_WHITELIST
                ),
                "Color": self.extractField(nar, (45, 63, 279, 353)),
            },
            "Western Village": {
                "Ryo": self.extractField(
                    md2, (107, 128, 361, 412),
                    wl=INTEGER_WHITELIST
                ),
                "Head": self.extractField(md2, (139, 157, 64, 109)),
                "Houses": self.extractField(
                    md2, (138, 157, 339, 414),
                    wl=INTEGER_WHITELIST
                ),
                "Color": self.extractField(nar, (106, 127, 275, 362)),
            },
            "River Hamlet": {
                "Ryo": self.extractField(
                    md2, (169, 189, 361, 414),
                    wl=INTEGER_WHITELIST
                ),
                "Head": self.extractField(md2, (200, 219, 64, 109)),
                "Houses": self.extractField(
                    md2, (200, 219, 339, 412),
                    wl=INTEGER_WHITELIST
                ),
                "Color": self.extractField(nar, (169, 191, 275, 362)),
            },
            "Claims": [
                self.extractField(q, (11, 32, 11, 568)),
                self.extractField(q, (48, 69, 10, 564)),
                self.extractField(q, (85, 108, 14, 560)),
            ],
        }
    
    def isReadingDocs(self):
        vf_img = self.SC.screenshot(self.vf)
        text = self.extractField(self.SC.toArray(vf_img)).strip().upper() #type: ignore
        return text == "LETTER"

    def getDocJson(self):
        # o = f"{TEST_DIR}/"
        # self.sc.screenshot(self.n_b, o_dir=o, file_name="test_nar")
        # self.sc.screenshot(self.md_b, o_dir=o, file_name="test_md")
        # self.sc.screenshot(self.q_b, o_dir=o, file_name="test_q")
        
        print("INFO: Commenced doc analysis")
        self.PC.scroll(clicks=4, c=self.md_b.mid)
        time.sleep(0.2)
        # Take screenshots of the 3 document frames
        nar_img = self.SC.screenshot(self.n_b, o_dir=TEST_DIR_S, file_name="test_nar")
        q_img = self.SC.screenshot(self.q_b, o_dir=TEST_DIR_S, file_name="test_q")
        md0_img = self.SC.screenshot(self.md_b, o_dir=TEST_DIR_S, file_name="test_md0")
        

        # Scroll and take screenshots of the misc document frame
        self.PC.scroll(clicks=-2, c=self.md_b.mid)
        time.sleep(0.2)
        md1_img = self.SC.screenshot(self.md_b, o_dir=TEST_DIR_S, file_name="test_md1")

        # Next one 
        self.PC.scroll(clicks=-2, c=self.md_b.mid)
        time.sleep(0.2)
        md2_img = self.SC.screenshot(self.md_b, o_dir=TEST_DIR_S, file_name="test_md2")

        
        # Prepare a JSON for the prompt
        return  json.dumps(
                    self._extractFText(
                        self.SC.toArray(md0_img),
                        self.SC.toArray(md1_img),
                        self.SC.toArray(md2_img),
                        self.SC.toArray(nar_img),
                        self.SC.toArray(q_img)),
                    indent = 2)



