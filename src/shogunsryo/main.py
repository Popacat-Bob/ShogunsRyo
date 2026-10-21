import os
import sys
import time
from pathlib import Path

# --- Windows setup (the only additions to this file) ---------------------------------------
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")  # skip a slow start-up check


def _add_nvidia_dll_dirs() -> None:
    """Let PaddlePaddle find the CUDA libraries installed with pip (nvidia-cudnn-cu12 etc.)."""
    if sys.platform != "win32":
        return
    roots = [Path(sys.prefix) / "Lib" / "site-packages"]
    found = [str(d) for r in roots for d in (r / "nvidia").glob("*/bin")]
    for d in found:
        try:
            os.add_dll_directory(d)
        except OSError:
            pass
    if found:
        os.environ["PATH"] = os.pathsep.join(found) + os.pathsep + os.environ.get("PATH", "")


_add_nvidia_dll_dirs()  # must run before paddle is imported

import numpy as np
from paddleocr import PaddleOCR
from google import genai
from pynput.keyboard import KeyCode, Listener as KListener

from shogunsryo.Controller import Controller
from shogunsryo.DocCore import DocCore
from shogunsryo.utils.ProcessControls import PC
from shogunsryo.utils.ScreenCapture import ScreenCapture
from shogunsryo.utils.TextExtractor import TextExtractor
from shogunsryo.utils.FastReader import FastReader
from shogunsryo.utils import Boost
from shogunsryo.DecisionModel import (
    GenAIModel, GroqModel, MistralModel, GenAIClient, GroqClient, UnifiedDecisionModel,
)

DEFAULT_INITIAL_PROMPT = """
After this message you will only receive JSON data.

In this JSON data, there is a "Claims" section. Verify whether each claim is true based on the rest of the JSON data.

IMPORTANT:
- Treat the JSON data as the source of truth.
- Claims may contain OCR errors. Correct obvious OCR errors using the surrounding JSON data.
- Do not interpret OCR mistakes literally when the intended value is obvious.
- Use context clues and common sense when interpreting possible OCR errors.
- Perform arithmetic explicitly when necessary.
- For comparisons such as "X more than Y", calculate the difference from the relevant numeric fields.
- A value of 0 means none/zero. For example, "Times Written": 0 means the person has NOT written this season.
- For color/seal claims, compare the RGB arrays exactly.
- Do not assume a claim is true merely because it sounds plausible.
- Check every claim independently.
- For seal claims, `Letter.Seal Color` identifies the seal shown on the letter.
- Each domain's `Color` field identifies that domain's seal color.
- To determine whether a seal belongs to a domain, compare the two RGB arrays exactly.
- RGB colors between seals of the same color may not match, allow a tolerance of 5 for each RGB value 
- `Letter.Seal Village` already names the village whose color matches the letter's seal ("none" if no village matches). Trust it for any claim about the seal.
- Example: if `Letter.Seal Color` is [255, 120, 177] and `Market.Color` is [255, 255, 172], then "This seal belongs to The Market" is FALSE.

Once you have determined the answers, send ONLY a JSON object with the keys claim1, claim2, and claim3:

1. A Boolean corresponding to the first claim.
2. A Boolean corresponding to the second claim.
3. A Boolean corresponding to the third claim.

Do NOT determine a verdict. The program will determine the verdict separately.

Do not include any explanation, markdown, code fences, or additional text.
"""


SCHEMA = {
    "type": "object",
    "properties": {
        "claim1": {"type": "boolean"},
        "claim2": {"type": "boolean"},
        "claim3": {"type": "boolean"},
    },
    "required": [
        "claim1",
        "claim2",
        "claim3",
    ],
}


REFER_INTENTS = {
    "wants a samurai punished",
    "wants a death sentence lifted",
    "wants to visit the shogun",
    "wants to speak to the shogun",
    "wants the tax rate changed",
    "wants a prisoner set free",
    "wants a domain boundary restored",
    "wants leave to carry a sword",
    "wants a priest appointed to the temple",
}

def build_ocr() -> PaddleOCR:
    """
    The author's PaddleOCR settings, unchanged. Only the device is chosen here: the GPU if it
    works, otherwise the CPU. Set OCR_DEVICE=cpu to force the CPU.
    """
    settings = dict(
        lang="en",
        enable_mkldnn=False,
        text_det_box_thresh=0.4,
        text_det_thresh=0.2,
        text_det_unclip_ratio=2.0,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    if os.environ.get("OCR_DEVICE", "auto").strip().lower() != "cpu":
        try:
            ocr = PaddleOCR(**settings, device="gpu:0")
            list(ocr.predict(np.full((64, 256, 3), 255, dtype=np.uint8)))  # fails here, not mid-run
            print("INFO: PaddleOCR is running on the GPU")
            ocr.device_str = "gpu:0"
            return ocr
        except Exception as e:
            first = (str(e).strip().splitlines() or [""])[0][:160]
            print(f"WARN: GPU not usable ({type(e).__name__}: {first}); using the CPU")
    ocr = PaddleOCR(**settings, device="cpu")
    print("INFO: PaddleOCR is running on the CPU")
    ocr.device_str = "cpu"
    return ocr


def build_models() -> list:
    """
    The language models, tried in order; the next one takes over when one is rate limited.
    Every Groq model has its own daily allowance, so listing two gives twice the free tokens.

      GROQ_MODELS     default "openai/gpt-oss-120b,openai/gpt-oss-20b"
      MISTRAL_MODELS  default "ministral-8b-latest,open-mistral-nemo"  (the two that work on the free plan;
                      mistral-small/medium/large are not available on it)
      GEMINI_MODEL    default "gemini-3.5-flash-lite"
      MODEL_ORDER     default "groq,gemini,mistral": the strongest models first, and the Mistral
                      free models (a huge allowance) as the safety net that keeps it running

    A model whose API key is missing is skipped.
    """
    groups: dict[str, list] = {"groq": [], "mistral": [], "gemini": []}
    if os.environ.get("GROQ_API_KEY"):
        client = GroqClient()
        for name in os.environ.get("GROQ_MODELS", "openai/gpt-oss-120b,openai/gpt-oss-20b").split(","):
            if name.strip():
                groups["groq"].append(GroqModel(client=client, model=name.strip()))
    else:
        print("INFO: no GROQ_API_KEY, so Groq is skipped")
    if os.environ.get("MISTRAL_API_KEY"):
        names = os.environ.get("MISTRAL_MODELS") or os.environ.get("MISTRAL_MODEL") or "ministral-8b-latest,open-mistral-nemo"
        for name in names.split(","):
            if name.strip():
                groups["mistral"].append(MistralModel(os.environ["MISTRAL_API_KEY"], name.strip()))
    else:
        print("INFO: no MISTRAL_API_KEY, so Mistral is skipped")
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        groups["gemini"].append(GenAIModel(client=GenAIClient(),
                                           model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")))
    else:
        print("INFO: no GEMINI_API_KEY, so Gemini is skipped")

    order = [x.strip() for x in os.environ.get("MODEL_ORDER", "groq,gemini,mistral").lower().split(",") if x.strip()]
    for g in groups:  # anything not mentioned goes last
        if g not in order:
            order.append(g)
    models = [m for g in order for m in groups.get(g, [])]
    if not models:
        sys.exit("ERROR: no API keys found. Put GEMINI_API_KEY, GROQ_API_KEY and/or MISTRAL_API_KEY in the .env file.")

    for m in models:
        m.setSystemRules(prompt=DEFAULT_INITIAL_PROMPT, schema=SCHEMA)
    print("INFO: Models in order: " + "  ->  ".join(m.model for m in models))
    return models


def main():
    # Keep Windows from slowing this program down while the game is in front (BOOST=0 turns it off)
    if os.environ.get("BOOST", "1").strip().lower() not in ("0", "false", "no"):
        print("INFO: Boost:", Boost.apply())

    ocr = build_ocr()
    te = TextExtractor(ocr)
    dc = DocCore(te=te)

    # Optional speed-up, OFF by default (OCR_FAST=1 to try it). See utils/FastReader.py.
    if os.environ.get("OCR_FAST", "0").strip().lower() in ("1", "true", "yes"):
        fast = FastReader.create(te, ocr, getattr(ocr, "device_str", "cpu"))
        if fast:
            fast.install(dc)

    # Show how long reading each letter takes (SHOW_TIMING=0 hides it). Does not change anything.
    if os.environ.get("SHOW_TIMING", "1").strip().lower() not in ("0", "false", "no"):
        _read_letter = dc._extractFText

        def _timed(*args, **kwargs):
            t0 = time.perf_counter()
            result = _read_letter(*args, **kwargs)
            print(f"INFO: OCR read the letter in {time.perf_counter() - t0:.1f}s")
            return result

        dc._extractFText = _timed

    umoz = UnifiedDecisionModel(models=build_models())

    control = Controller(
        dc=dc,
        pc=PC(),
        umo = umoz,
        refer_intents=REFER_INTENTS,
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
