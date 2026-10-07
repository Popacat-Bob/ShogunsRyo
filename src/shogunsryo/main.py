import time
from paddleocr import PaddleOCR
from google import genai
from pynput.keyboard import KeyCode, Listener as KListener

from shogunsryo.Controller import Controller
from shogunsryo.DocCore import DocCore
from shogunsryo.utils.ProcessControls import PC
from shogunsryo.utils.ScreenCapture import ScreenCapture
from shogunsryo.utils.TextExtractor import TextExtractor
from shogunsryo.DecisionModel import GenAIModel, GroqModel, GenAIClient, GroqClient, UnifiedDecisionModel

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

def main():
    te = TextExtractor(
            PaddleOCR(
                lang="en",
                enable_mkldnn=False,
                text_det_box_thresh=0.4,
                text_det_thresh=0.2,
                text_det_unclip_ratio=2.0,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                )
            )

    genai, groq = \
        GenAIModel(client=GenAIClient(), model="gemini-3.5-flash-lite"),\
        GroqModel(client=GroqClient(), model="openai/gpt-oss-20b")

    genai.setSystemRules(prompt=DEFAULT_INITIAL_PROMPT, schema=SCHEMA)
    groq.setSystemRules(prompt=DEFAULT_INITIAL_PROMPT, schema=SCHEMA)
    umoz = UnifiedDecisionModel(models=[groq, genai])

    control = Controller(
        dc=DocCore(te=te),
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
