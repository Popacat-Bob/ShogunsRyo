"""
Optional speed-up (OFF unless OCR_FAST=1). The author's code is not modified.

A letter needs ~27 OCR reads, one at a time. Each one is a separate trip to the GPU, and when a
game is rendering on the same GPU every trip has to wait its turn. That is what makes a letter
take 30+ seconds while the same reads take under a second with the game closed.

How this works, without touching DocCore:
  1. Run the author's DocCore._extractFText once, but hand every crop to a recorder instead of the
     OCR. (DocCore never looks at what the OCR returns while building the data, so this is safe.)
  2. Read all the one-line crops in ONE batch with the recognition model the author's pipeline
     already uses.
  3. Run DocCore._extractFText again, this time returning the texts read in step 2.

Safety nets: a crop that is tall (the letter body), or that the recognition model is not
confident about (below MIN_SCORE), or that comes back empty, is read by the author's own full
pipeline, exactly as before. Any error anywhere falls back to the author's one-by-one reading.
"""
import cv2
import numpy as np

SINGLE_LINE_MAX_H = 32   # taller crops (before enlarging) may be several lines: use the full pipeline
MIN_SCORE = 0.8          # recognition confidence below this: use the full pipeline
DOT_CLEAN_MAX_W = 60     # narrow crops (the Ryo / houses numbers, the head names) are cleaned of colour dots


def _pipeline_rec_name(ocr) -> str | None:
    """Name of the recognition model the PaddleOCR pipeline itself is using (so we use the same one)."""
    for path in (("paddlex_pipeline", "_pipeline", "text_rec_model"), ("paddlex_pipeline", "text_rec_model")):
        obj = ocr
        try:
            for attr in path:
                obj = getattr(obj, attr)
        except AttributeError:
            continue
        name = getattr(obj, "model_name", None)
        if name:
            return str(name)
    return None


class FastReader:
    def __init__(self, te, rec):
        self.te = te          # the author's TextExtractor
        self.rec = rec        # paddleocr.TextRecognition
        self.last = ""        # one-line summary of the last letter, for logging

    @classmethod
    def create(cls, te, ocr, device: str):
        """Returns a FastReader, or None (with a printed reason) if it can't be set up."""
        try:
            from paddleocr import TextRecognition

            name = _pipeline_rec_name(ocr)
            if not name:
                print("WARN: OCR_FAST: could not find which recognition model the pipeline uses; staying with normal reads")
                return None
            rec = TextRecognition(model_name=name, device=device, enable_mkldnn=False)
            list(rec.predict(input=[np.full((48, 160, 3), 255, dtype=np.uint8)], batch_size=1))  # self-test
            print(f"INFO: OCR_FAST is ON (batched reads with {name} on {device})")
            return cls(te, rec)
        except Exception as e:
            first = (str(e).strip().splitlines() or [""])[0][:160]
            print(f"WARN: OCR_FAST unavailable ({type(e).__name__}: {first}); staying with normal reads")
            return None

    @staticmethod
    def _blank_dots(crop: np.ndarray) -> np.ndarray:
        """
        Paint over strongly coloured pixels with the background colour. The Ryo number crops
        catch part of the coloured village dot, and the recognition model reads that sliver as
        a "0" ("62" came back as "062"). Digits and the faint head names are grey/brown and the
        paper is beige, both nearly colourless, so colourfulness (Lab chroma) separates them.
        (The full pipeline finds the text first and ignores the dot, which is why only this
        batched path needs it. Coloured TEXT lives in wide crops, which are left alone.)
        """
        if crop.ndim != 3 or crop.shape[2] < 3 or crop.size == 0:
            return crop
        bgr = np.ascontiguousarray(crop[:, :, :3])
        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.int16)
        mask = (np.hypot(lab[:, :, 1] - 128, lab[:, :, 2] - 128) > 22).astype(np.uint8)
        if not mask.any():
            return crop
        mask = cv2.dilate(mask, np.ones((3, 3), np.uint8)).astype(bool)
        if mask.all():
            return crop
        out = crop.copy()
        out[mask, :3] = np.median(bgr[~mask].reshape(-1, 3), axis=0).astype(np.uint8)
        return out

    # -- same preparation the author's TextExtractor does ------------------------------------------
    @staticmethod
    def _prep(img: np.ndarray, scale: int = 3) -> np.ndarray:
        if img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        h, w = img.shape[:2]
        if max(h, w) < 300:
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        return img

    def read_all(self, crops: list[np.ndarray], slow_read) -> list[str]:
        """Texts for every crop. slow_read(crop) is the author's own one-crop reader."""
        out: list[str | None] = [None] * len(crops)
        idx = [i for i, c in enumerate(crops) if c.shape[0] <= SINGLE_LINE_MAX_H]
        batch = [self._prep(self._blank_dots(crops[i]) if crops[i].shape[1] < DOT_CLEAN_MAX_W else crops[i])
                 for i in idx]
        confident = 0
        if batch:
            for i, r in zip(idx, list(self.rec.predict(input=batch, batch_size=len(batch)))):
                data = getattr(r, "json", r)
                data = data.get("res", data)
                text, score = str(data.get("rec_text") or "").strip(), float(data.get("rec_score") or 0.0)
                if text and score >= MIN_SCORE:
                    out[i] = text
                    confident += 1
        again = 0
        for i, c in enumerate(crops):
            if out[i] is None:
                out[i] = slow_read(c)
                again += 1
        self.last = f"OCR fast: {confident} read in one batch, {again} read the normal way"
        return [o or "" for o in out]

    def install(self, doc_core) -> None:
        """Replace doc_core._extractFText with a version that reads all crops in one batch."""
        original = doc_core._extractFText
        te = self.te
        reader = self

        def batched(md0, md1, nar, q):
            real = te.extractFromImg                      # the author's bound method
            try:
                # pass 1: collect the crops
                crops: list[np.ndarray] = []
                te.extractFromImg = lambda img, *a, **k: (crops.append(img), "")[1]
                try:
                    original(md0, md1, nar, q)
                finally:
                    te.__dict__.pop("extractFromImg", None)
                texts = reader.read_all(crops, real)
                print(f"INFO: {reader.last}")
                # pass 2: build the real data, handing back the texts in the same order
                it = iter(texts)
                te.extractFromImg = lambda img, *a, **k: next(it)
                try:
                    return original(md0, md1, nar, q)
                finally:
                    te.__dict__.pop("extractFromImg", None)
            except Exception as e:                        # anything odd: do exactly what the author's code does
                te.__dict__.pop("extractFromImg", None)
                print(f"WARN: OCR_FAST failed ({type(e).__name__}: {str(e)[:100]}); reading normally this letter")
                return original(md0, md1, nar, q)

        doc_core._extractFText = batched
