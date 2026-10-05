import cv2
import pytesseract
from numpy import ndarray


def extractFromImg(
    img: ndarray,
    psm: int = 6,
    blacklist: str = "¥®@&©|‘’“”™§",
    whitelist: str | None = None,
    scale: int = 3,
) -> str:
    """
    Extracts text from an image using Tesseract OCR.

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

    config = f"--psm {psm}"

    if blacklist:
        config += f" -c tessedit_char_blacklist={blacklist}"

    if whitelist:
        config += f" -c tessedit_char_whitelist={whitelist}"

    return pytesseract.image_to_string(
        processed,
        config=config,
    )
