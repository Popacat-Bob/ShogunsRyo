import cv2
import easyocr
from numpy import ndarray

class TextExtractor:
    def __init__(self, model: easyocr.Reader):
        self.model = model

    def extractFromImg(
        self,
        img: ndarray,
        blacklist: str = "¥®@&©|‘’“”™§",
        whitelist: str | None = None,
        scale: int = 3,
    ) -> str:
        """
        Extracts text from an image using OCR

        The image is:
            1. Converted to grayscale
            2. Upscaled
            3. Otsu-thresholded
            4. Passed to Tesseract
        """

        # Grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Upscale
        if scale > 1:
            gray = cv2.resize(
                gray,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_CUBIC,
            )

        # Binarize
        processed = cv2.threshold(
            gray,
            0,
            255,
            cv2.THRESH_BINARY | cv2.THRESH_OTSU,
        )[1]

        res = self.model.readtext(
                processed, 
                detail=0,
                blocklist=blacklist,
                allowlist=whitelist
                ) 

        return " ".join(res)
