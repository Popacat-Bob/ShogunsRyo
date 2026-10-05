from ollama import Client
from pynput.keyboard import KeyCode
from enum import Enum
from pathlib import Path
from datetime import datetime
import time
import tomllib
import json

from shogunsryo.DocCore import DocCore
from shogunsryo.utils.ProcessControls import PC
from shogunsryo.ptypes.Generic import Coords, Bbox

DEFAULT_INITIAL_PROMPT = """
After this message you will only receive JSON data.

In this JSON data, there is a "Claims" section. Verify whether each claim is true based on the rest of the JSON data.

Some letters, characters, or words may look slightly incorrect because the data was extracted using OCR. Use context clues and common sense when interpreting possible OCR errors.

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
    "required": ["claim1", "claim2", "claim3"],
}

REFER_INTENTS = {
    "wants a samurai punished",
    "wants a death sentence lifted",
    "wants to visit the shogun",
    "wants to speak to the shogun",
    "wants to change the tax rate",
    "wants a prisoner set free",
    "wants a domain boundary restored",
    "wants leave to carry a sword"
}

DEFAULTS = Path(__file__).parent / "config" / "defaults.toml"


class Verdict(Enum):
    ACCEPT = 0
    REJECT = 1
    REFER = 2


class Controller:
    def __init__(self, dc: DocCore, pc: PC, ollama: Client, path=DEFAULTS):
        self.dc = dc
        self.pc = pc
        self.olla = ollama
        self.enabled = False

        self.log_dir = Path(__file__).parent / "log"
        self.log_dir.mkdir(parents=True, exist_ok=True)


        log_file = self.log_dir / "errors.jsonl"
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

    def log_error(self, docFrame, claims, verdict, error):
        log_file = self.log_dir / "errors.jsonl"

        entry = {
            "timestamp": datetime.now().isoformat(),
            "error": str(error),
            "claims": claims,
            "verdict": verdict.value,
            "docFrame": docFrame,
        }

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def determine_verdict(self, docFrame, claims) -> Verdict:
        if not all(claims):
            return Verdict.REJECT

        intent = docFrame["Letter"]["Intent"].strip().lower()

        # Handle common OCR truncation.
        if intent == "wants a domain boundary resto":
            intent = "wants a domain boundary restored"

        if intent in REFER_INTENTS:
            return Verdict.REFER

        return Verdict.ACCEPT

    def isSuccess(self) -> bool:
        res_img = self.dc.SC.screenshot(self.resf)
        res_str = self.dc.extractField(
            self.dc.SC.toArray(res_img)
        ).strip().upper()
        print(res_str)
        return "EARNED" in set(res_str.split())

    def answer(
        self,
        b0: bool,
        b1: bool,
        b2: bool,
        v: Verdict
    ):
        print("INFO: Commenced Answering")

        if b0:
            self.pc.move_to(Coords(1470, 734))
        else:
            self.pc.move_to(Coords(1375, 735))

        self.pc.click()

        time.sleep(0.2)

        if b1:
            self.pc.move_to(Coords(1469, 768))
        else:
            self.pc.move_to(Coords(1348, 768))

        time.sleep(0.2)
        self.pc.click()

        time.sleep(0.2)

        if b2:
            self.pc.move_to(Coords(1470, 802))
        else:
            self.pc.move_to(Coords(1372, 802))

        time.sleep(0.2)
        self.pc.click()

        time.sleep(0.2)

        match v:
            case Verdict.ACCEPT:
                self.pc.move_to(Coords(681, 850))
            case Verdict.REJECT:
                self.pc.move_to(Coords(982, 848))
            case Verdict.REFER:
                self.pc.move_to(Coords(1243, 853))

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

            self.pc.press(KeyCode.from_char("e"))
            time.sleep(1)

            self.pc.move_to(Coords(1408, 857))
            time.sleep(0.2)
            self.pc.click()

            time.sleep(1)

        docFrame = self.dc.getDocJson()

        try:
            # getDocJson() appears to return JSON text.
            docData = json.loads(docFrame)

            res = self.olla.chat(
                model="qwen3:4b",
                messages=[
                    {
                        "role": "system",
                        "content": DEFAULT_INITIAL_PROMPT
                    },
                    {
                        "role": "user",
                        "content": docFrame
                    }
                ],
                think=False,
                format=SCHEMA,
                keep_alive="30m",
                options={
                    "temperature": 0,
                    "num_predict": 30
                },
            )

            print(f"REPLY: {res.message.content}")

            claims = json.loads(res.message.content)

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
                self.log_error(
                    docData,
                    claim_values,
                    verdict,
                    "Wrong Answer"
                )

        except Exception as e:
            self.log_error(
                docFrame,
                None,
                Verdict.REJECT,
                e
            )

            print(f"ERROR: {e}")

        time.sleep(6)
