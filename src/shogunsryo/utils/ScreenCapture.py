import mss 
import mss.tools
import numpy as np

from shogunsryo.ptypes.Generic import Dimensions, Bbox, RGB

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
        return {
                'left': b.TopLeft.x ,
                'top': b.TopLeft.y,
                'width': b.width,
                'height': b.height 
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
            if o_dir: 
                o_path = o_dir + '/' + file_name
                mss.tools.to_png(sc.rgb, sc.size, output=o_path)
            return sc
        except Exception as e:
            print(f"Error, unable to take a screenshot: {e}")
            raise
        


