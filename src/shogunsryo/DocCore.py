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
            nar: np.ndarray,
            q: np.ndarray,
        ):
        return {
            "Meta": {
                "Signed On": self.extractField(
                    md0, (37, 56, 526, 584),
                    wl=INTEGER_WHITELIST
                ),
                "Times Written": self.extractField(
                    md0, (65, 85, 415, 545),
                ),
                "Today": self.extractField(
                    md0, (94, 114, 532, 541),
                    wl=INTEGER_WHITELIST
                ),
            },
            "Letter": {
                "From": self.extractField(nar, (11, 38, 12, 235)),
                "Intent": self.extractField(nar, (52, 69, 12, 285)),
                "Seal Color": nar[309, 49][::-1][:3].tolist(),
                "Body": self.extractField(nar, (85, 144, 12, 525)),
            },
            "Shisato": {
                "Ryo": self.extractField(
                    md0, (153, 174, 485, 513),
                    wl=INTEGER_WHITELIST
                ),
                "Head": self.extractField(md0, (180, 197, 84, 142)),
                "Houses": self.extractField(
                    md0, (177, 197, 475, 492),
                    wl=INTEGER_WHITELIST
                ),
                "Color": md0[161, 475][::-1][:3].tolist(),
            },
            "Kotobo": {
                "Ryo": self.extractField(
                    md0, (207, 226, 485, 513),
                    wl=INTEGER_WHITELIST
                ),
                "Head": self.extractField(md0, (231, 250, 84, 142)),
                "Houses": self.extractField(
                    md0, (234, 252, 475, 492),
                    wl=INTEGER_WHITELIST
                ),
                "Color": md0[215, 475][::-1][:3].tolist(),
            },
            "Farmers": {
                "Ryo": self.extractField(
                    md0, (260, 280, 485, 513),
                    wl=INTEGER_WHITELIST
                ),
                "Head": self.extractField(md0, (291, 309, 84, 142)),
                "Houses": self.extractField(
                    md0, (286, 305, 475, 492),
                    wl=INTEGER_WHITELIST
                ),
                "Color": md0[268, 475][::-1][:3].tolist(),
            },
            "Market": {
                "Ryo": self.extractField(
                    md1, (154, 175, 485, 513),
                    wl=INTEGER_WHITELIST
                ),
                "Head": self.extractField(md1, (181, 203, 84, 142)),
                "Houses": self.extractField(
                    md1, (182, 199, 475, 492),
                    wl=INTEGER_WHITELIST
                ),
                "Color": md1[163, 475][::-1][:3].tolist(),
            },
            "Western Village": {
                "Ryo": self.extractField(
                    md1, (208, 228, 485, 513),
                    wl=INTEGER_WHITELIST
                ),
                "Head": self.extractField(md1, (232, 252, 84, 142)),
                "Houses": self.extractField(
                    md1, (236, 256, 475, 492),
                    wl=INTEGER_WHITELIST
                ),
                "Color": md1[216, 475][::-1][:3].tolist(),
            },
            "River Hamlet": {
                "Ryo": self.extractField(
                    md1, (261, 281, 475, 513),
                    wl=INTEGER_WHITELIST
                ),
                "Head": self.extractField(md1, (288, 308, 84, 142)),
                "Houses": self.extractField(
                    md1, (288, 308, 475, 492),
                    wl=INTEGER_WHITELIST
                ),
                "Color": md1[271, 475][::-1][:3].tolist(),
            },
            "Claims": [
                self.extractField(q, (5, 26, 14, 355)),
                self.extractField(q, (38, 59, 14, 355)),
                self.extractField(q, (75, 96, 14, 355)),
            ],
        }
    
    def isReadingDocs(self):
        vf_img = self.SC.screenshot(self.vf)
        text = self.extractField(self.SC.toArray(vf_img)).strip().upper() #type: ignore
        return text == "LETTERS"

    def getDocJson(self):
        # o = f"{TEST_DIR}/"
        # self.sc.screenshot(self.n_b, o_dir=o, file_name="test_nar")
        # self.sc.screenshot(self.md_b, o_dir=o, file_name="test_md")
        # self.sc.screenshot(self.q_b, o_dir=o, file_name="test_q")
        
        print("INFO: Commenced doc analysis")
        self.PC.scroll(clicks=2, c=self.md_b.mid)
        time.sleep(0.2)
        # Take screenshots of the 3 document frames
        nar_img = self.SC.screenshot(self.n_b, o_dir=TEST_DIR_S, file_name="test_nar")
        md0_img = self.SC.screenshot(self.md_b, o_dir=TEST_DIR_S, file_name="test_md0")
        q_img = self.SC.screenshot(self.q_b, o_dir=TEST_DIR_S, file_name="test_q")
        

        # Scroll and take screenshots of the misc document frame (bottom half)
        self.PC.scroll(clicks=-2, c=self.md_b.mid)
        time.sleep(0.2)
        md1_img = self.SC.screenshot(self.md_b, o_dir=TEST_DIR_S, file_name="test_md1")
        
        # Prepare a JSON for the prompt
        return  json.dumps(
                    self._extractFText(
                        self.SC.toArray(md0_img),
                        self.SC.toArray(md1_img),
                        self.SC.toArray(nar_img),
                        self.SC.toArray(q_img)),
                    indent = 2)



