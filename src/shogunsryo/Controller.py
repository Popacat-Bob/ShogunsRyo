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
from shogunsryo.DecisionModel import UnifiedDecisionModel

DEFAULTS = Path(__file__).parent / "config" / "defaults.toml"



class Verdict(Enum):
    ACCEPT = 0
    REJECT = 1
    REFER = 2


class Controller:
    def __init__(
        self,
        dc: DocCore,
        pc: PC,
        umo: UnifiedDecisionModel,
        refer_intents: set[str],
        path=DEFAULTS,
    ):
        self.dc = dc
        self.pc = pc
        self.umo = umo
        self.enabled = False
        self.refer_intents = refer_intents

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

        if intent in self.refer_intents:
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
                Coords(1329, 664)
            )
        else:
            self.pc.move_to(
                Coords(1227, 664)
            )
        
        time.sleep(0.2)
        self.pc.click()
        time.sleep(0.2)

        if b1:
            self.pc.move_to(
                Coords(1333, 703)
            )
        else:
            self.pc.move_to(
                Coords(1227, 703)
            )

        time.sleep(0.2)
        self.pc.click()
        time.sleep(0.2)

        if b2:
            self.pc.move_to(
                Coords(1333, 741)
            )
        else:
            self.pc.move_to(
                Coords(1227, 741)
            )

        time.sleep(0.2)
        self.pc.click()
        time.sleep(0.2)

        match v:
            case Verdict.ACCEPT:
                self.pc.move_to(
                    Coords(681, 794)
                )

            case Verdict.REJECT:
                self.pc.move_to(
                    Coords(982, 794)
                )

            case Verdict.REFER:
                self.pc.move_to(
                    Coords(1243, 794)
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

            time.sleep(0.2)

            self.pc.ktap(
                KeyCode.from_char("e")
            )

            time.sleep(0.2)

            self.pc.move_to(
                Coords(1358, 794)
            )

            time.sleep(0.2)
            self.pc.click()

            time.sleep(0.2)

        docFrame = self.dc.getDocJson()

        try:
            docData = json.loads(docFrame)

            claims = json.loads(self.umo.request(docData))

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
            self.enabled = False

        time.sleep(6)
