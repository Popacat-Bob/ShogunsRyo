import cv2
import mss
import mss.tools
import numpy as np

from shogunsryo.ptypes.Generic import Dimensions, Bbox, RGB
from shogunsryo.utils.Scale import SX, SY


class _Shot:
    '''
    Minimal stand-in for an mss ScreenShot, used when a capture had to be
    resized back to the 1920x1080 reference size.
    '''

    def __init__(self, bgra: np.ndarray):
        bgra = np.ascontiguousarray(bgra)
        self.height, self.width = bgra.shape[:2]
        self.size = (self.width, self.height)
        self.bgra = bgra.tobytes()
        self.rgb = np.ascontiguousarray(bgra[:, :, 2::-1]).tobytes()

class ScreenCapture:
    ''' 
    A screen capture utility that can:
        1. Get the color at the current cursor
        2. Take screenshots of certain regions
    '''

    def __init__(self, sd: Dimensions):
        self.sd = sd 
        self._sct = mss.mss()
    
    def _formatBboxToSCTReg(self, b: Bbox):
        # Bbox is in 1920x1080 reference coords; convert to real screen pixels.
        return {
                'left': round(b.TopLeft.x * SX),
                'top': round(b.TopLeft.y * SY),
                'width': max(1, round(b.width * SX)),
                'height': max(1, round(b.height * SY))
                }

    def toArray(self, shot: mss.ScreenShot) -> np.ndarray:
        '''
        Converts an mss ScreenShot to a BGRA uint8 array
        '''
        return np.frombuffer(shot.bgra, dtype=np.uint8).reshape(shot.height, shot.width, 4)
    
    def isWithinRGB(self, aRGB: RGB, tRGB: RGB, tol: int):
       return all (
               abs(actual - target) <= tol
               for actual, target in zip(aRGB, tRGB)
               ) 

    def screenshot(self, b: Bbox, o_dir: str | None = None, file_name: str = "test.png"):
        '''
        Takes:
            1. Bbox - the bounding box of the region to screenshot 
            2. o_dir (optional) - the directory to store the screenshot in (if specified)
            3. file_name - the name of the img file MUST include extension
        '''
        try: 
            sc = self._sct.grab(self._formatBboxToSCTReg(b))
            if (sc.width, sc.height) != (b.width, b.height):
                # Resize back to the reference size so the fixed crop offsets
                # in DocCore keep lining up on any resolution.
                arr = np.frombuffer(sc.bgra, dtype=np.uint8).reshape(sc.height, sc.width, 4)
                interp = cv2.INTER_AREA if SX >= 1 else cv2.INTER_CUBIC
                sc = _Shot(cv2.resize(arr, (b.width, b.height), interpolation=interp))
            if o_dir: 
                o_path = o_dir + '/' + file_name
                mss.tools.to_png(sc.rgb, sc.size, output=o_path)
            return sc
        except Exception as e:
            print(f"Error, unable to take a screenshot: {e}")
            raise
        


