import tomllib 
from pathlib import Path 
import subprocess 
import math
import time
import cv2
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

# How far (RGB distance) a village colour may be from the seal colour and still count as a match
SEAL_MATCH_TOLERANCE = 40

# JSON key -> the name the game (and the claims) use
VILLAGE_NAMES = {
    "Shisato": "Shisato Street",
    "Kotobo": "Kotobe Street",
    "Farmers": "Farmers Bay",
    "Market": "The Market",
    "Western Village": "The Western Village",
    "River Hamlet": "The River Hamlet",
}

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


    @staticmethod
    def _patch_color(img: np.ndarray, y: int, x: int, r: int = 3) -> list[int]:
        '''
        Median colour of a small patch centred on (y, x), as [R, G, B].
        Used for the letter seal, which is a big solid circle, so its centre is safe.
        '''
        h, w = img.shape[:2]
        y = min(max(y, 0), h - 1)
        x = min(max(x, 0), w - 1)
        p = img[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1, :3].reshape(-1, 3)
        b, g, rr = np.median(p, axis=0)
        return [int(rr), int(g), int(b)]

    @staticmethod
    def _dot_color(img: np.ndarray, y: int, x: int, rx: int = 13, ry: int = 9) -> list[int]:
        '''
        Colour of the small round colour dot near (y, x), returned as [R, G, B].

        The village dots sit right next to the Ryo number, so their x position moves a
        few pixels depending on how wide that number is, and scaling the screen moves
        them a little more. Reading one fixed pixel can land on the dot's edge or on the
        background. So instead: look at a small window, find the blob that differs from
        the background, and take the median colour of its inside.

        Falls back to the median of a small patch at (y, x) if no dot is found.
        '''
        h, w = img.shape[:2]
        y = min(max(y, 0), h - 1)
        x = min(max(x, 0), w - 1)

        def patch_rgb() -> list[int]:
            return DocCore._patch_color(img, y, x, r=2)

        y0, y1 = max(0, y - ry), min(h, y + ry + 1)
        x0, x1 = max(0, x - rx), min(w, x + rx + 1)
        win = img[y0:y1, x0:x1, :3].astype(np.int16)  # BGR
        if win.shape[0] < 8 or win.shape[1] < 8:
            return patch_rgb()

        # Background = top and bottom bands of the window (the dot doesn't reach them)
        bands = np.concatenate([win[:2].reshape(-1, 3), win[-2:].reshape(-1, 3)])
        bg = np.median(bands, axis=0)
        dist = np.sqrt(((win - bg) ** 2).sum(axis=2))
        mask = (dist > 45).astype(np.uint8)

        n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        best, best_area = 0, 0
        for i in range(1, n):
            area = stats[i, cv2.CC_STAT_AREA]
            if area > best_area:
                best, best_area = i, area
        if best_area < 40:  # nothing dot-sized stands out from the background
            return patch_rgb()

        blob = (labels == best).astype(np.uint8)
        inner = cv2.erode(blob, np.ones((3, 3), np.uint8), iterations=2)
        sel = inner.astype(bool) if inner.sum() >= 10 else blob.astype(bool)
        b, g, r = np.median(win[sel], axis=0)
        return [int(r), int(g), int(b)]

    @staticmethod
    def _match_seal(seal: list[int], villages: dict[str, list[int]]) -> str:
        '''Name of the village whose colour matches the seal colour, or "none".'''
        best, best_d = "none", float("inf")
        for name, col in villages.items():
            d = math.dist(seal, col)
            if d < best_d:
                best, best_d = name, d
        return best if best_d <= SEAL_MATCH_TOLERANCE else "none"

    def _extractFText(
            self,
            md0: np.ndarray,
            md1: np.ndarray,
            nar: np.ndarray,
            q: np.ndarray,
        ):
        # Colours: the village dots move a few pixels with the width of the Ryo number, so look for
        # the dot near the expected spot instead of trusting one fixed pixel (see _dot_color).
        seal = self._patch_color(nar, 309, 49)
        colors = {
            "Shisato": self._dot_color(md0, 161, 477),
            "Kotobo": self._dot_color(md0, 215, 477),
            "Farmers": self._dot_color(md0, 268, 477),
            "Market": self._dot_color(md1, 163, 477),
            "Western Village": self._dot_color(md1, 216, 477),
            "River Hamlet": self._dot_color(md1, 271, 477),
        }
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
                "Seal Color": seal,
                "Seal Village": VILLAGE_NAMES.get(self._match_seal(seal, colors), "none"),
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
                "Color": colors["Shisato"],
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
                "Color": colors["Kotobo"],
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
                "Color": colors["Farmers"],
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
                "Color": colors["Market"],
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
                "Color": colors["Western Village"],
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
                "Color": colors["River Hamlet"],
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



