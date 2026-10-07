import cv2
from paddleocr import PaddleOCRVL
from numpy import ndarray


class TextExtractor:
    def __init__(self, model: PaddleOCRVL):
        self.model = model

    def extractFromImg(
        self,
        img: ndarray,
        scale: int = 3,
    ) -> str:

        if img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR) 
        
        h, w = img.shape[:2]
        if max(h, w) < 300:
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

        res = self.model.predict(img)
        if not res: return ""

        return " ".join(res[0].json["res"]["rec_texts"])
