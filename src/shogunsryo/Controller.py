from google import genai
from google.genai import types

from pynput.keyboard import KeyCode
from enum import Enum
from pathlib import Path
from datetime import datetime
import time
import tomllib
import json
import os

from shogunsryo.DocCore import DocCore
from shogunsryo.utils.ProcessControls import PC
from shogunsryo.ptypes.Generic import Coords, Bbox


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


DEFAULTS = Path(__file__).parent / "config" / "defaults.toml"

DEFAULT_MODEL = "gemini-3.5-flash-lite"


class Verdict(Enum):
    ACCEPT = 0
    REJECT = 1
    REFER = 2


class Controller:
    def __init__(
        self,
        dc: DocCore,
        pc: PC,
        client: genai.Client,
        path=DEFAULTS
    ):
        self.dc = dc
        self.pc = pc
        self.client = client
        self.enabled = False

        self.log_dir = Path(__file__).parent / "log"
        self.log_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        log_file = self.log_dir / "logs.jsonl"

        if log_file.exists():
            log_file.unlink()

        with open(path, "rb") as f:
            data = tomllib.load(f)

        self.resf = Bbox(
            *[
                Coords(*data["Frames"]["result"][i:i + 2])
                for i in range(0, 4, 2)
            ]
        )

        self.config = types.GenerateContentConfig(
            system_instruction=DEFAULT_INITIAL_PROMPT,
            response_mime_type="application/json",
            response_schema=SCHEMA,
            temperature=0,
        )

    def log(
        self,
        docFrame,
        claims,
        verdict,
        ltype, 
    ):
        log_file = self.log_dir / "logs.jsonl"

        entry = {
            "timestamp": datetime.now().isoformat(),
            "log_type": str(ltype),
            "claims": claims,
            "verdict": verdict.value,
            "docFrame": docFrame,
        }

        with open(
            log_file,
            "a",
            encoding="utf-8"
        ) as f:
            f.write(
                json.dumps(
                    entry,
                    ensure_ascii=False
                ) + "\n"
            )

    def determine_verdict(
        self,
        docFrame,
        claims
    ) -> Verdict:
        if not all(claims):
            return Verdict.REJECT

        intent = (
            docFrame["Letter"]["Intent"]
            .strip()
            .lower()
        )

        # Handle common OCR truncation.
        match intent: 
            case "wants a domain boundary resto":
                intent = "wants a domain boundary restored"
            case "wants a priest appointedto the temple":
                intent = "wants a priest appointed to the temple"

        if intent in REFER_INTENTS:
            return Verdict.REFER

        return Verdict.ACCEPT

    def isSuccess(self) -> bool:
        res_img = self.dc.SC.screenshot(self.resf)

        res_str = self.dc.extractField(
            self.dc.SC.toArray(res_img)
        ).strip().upper()
        
        success_strings = {"EARNED", "EARED"}
        decomp = set(res_str.split())

        print(res_str)

        for s in success_strings:
            if s in decomp: return True

        return False

    def answer(
        self,
        b0: bool,
        b1: bool,
        b2: bool,
        v: Verdict
    ):
        print("INFO: Commenced Answering")

        if b0:
            self.pc.move_to(
                Coords(1470, 734)
            )
        else:
            self.pc.move_to(
                Coords(1375, 735)
            )

        self.pc.click()

        time.sleep(0.2)

        if b1:
            self.pc.move_to(
                Coords(1469, 768)
            )
        else:
            self.pc.move_to(
                Coords(1348, 768)
            )

        time.sleep(0.2)
        self.pc.click()

        time.sleep(0.2)

        if b2:
            self.pc.move_to(
                Coords(1470, 802)
            )
        else:
            self.pc.move_to(
                Coords(1372, 802)
            )

        time.sleep(0.2)
        self.pc.click()

        time.sleep(0.2)

        match v:
            case Verdict.ACCEPT:
                self.pc.move_to(
                    Coords(681, 850)
                )

            case Verdict.REJECT:
                self.pc.move_to(
                    Coords(982, 848)
                )

            case Verdict.REFER:
                self.pc.move_to(
                    Coords(1243, 853)
                )

        self.pc.click()

    def toggle_enabled(self):
        self.enabled = not self.enabled

    def loop(self):
        if not self.enabled:
            return

        self.pc.focus()

        while not self.dc.isReadingDocs():
            if not self.enabled:
                return

            print("INFO: Attempted to commence.")

            time.sleep(2)

            self.pc.ktap(
                KeyCode.from_char("e")
            )

            time.sleep(0.2)

            self.pc.move_to(
                Coords(1408, 857)
            )

            time.sleep(0.2)
            self.pc.click()

            time.sleep(1)

        docFrame = self.dc.getDocJson()

        try:
            docData = json.loads(docFrame)

            res = self.client.models.generate_content(
                model=DEFAULT_MODEL,
                contents=json.dumps(docData),
                config=self.config,
            )

            claims = json.loads(res.text)

            claim_values = [
                claims["claim1"],
                claims["claim2"],
                claims["claim3"],
            ]

            verdict = self.determine_verdict(
                docData,
                claim_values
            )

            print(
                f"CLAIMS: {claim_values} | "
                f"VERDICT: {verdict.name}"
            )

            self.answer(
                claims["claim1"],
                claims["claim2"],
                claims["claim3"],
                verdict
            )

            time.sleep(0.2)

            if not self.isSuccess():
                self.log(
                    docData,
                    claim_values,
                    verdict,
                    "Error"
                    )

        except Exception as e:
            print(
                f"ERROR: {e}\n"
                "DISABLING"
            )

            self.pc.move_to(
                Coords(1408, 857)
            )

            time.sleep(0.2)
            self.pc.click()

        time.sleep(6)
