from ollama import Client
from pynput.keyboard import KeyCode
from enum import Enum
import time
import json

from shogunsryo.DocCore import DocCore
from shogunsryo.utils.ProcessControls import PC
from shogunsryo.ptypes.Generic import Coords

DEFAULT_INITIAL_PROMPT = """
After this message you will only receive JSON data.

In this JSON data, there is a "Claims" section. Verify whether each claim is true based on the rest of the JSON data.

Some letters, characters, or words may look slightly incorrect because the data was extracted using OCR. Use context clues and common sense to make your best judgment when interpreting possible OCR errors.

Once you have determined the answers, send ONLY a valid JSON list containing exactly four values:

1. A Boolean corresponding to the first claim.
2. A Boolean corresponding to the second claim.
3. A Boolean corresponding to the third claim.
4. An integer corresponding to the verdict.

There are 3 possible verdicts:

0 = Accept
1 = Reject
2 = Refer

Verdict rules:

1. Reject if at least one claim is false.
2. Refer if ALL claims are true AND the "Intent" field is one of the following:
   - "Wants a samurai punished"
   - "Wants a death sentence lifted"
   - "Wants to visit the shogun"
   - "Wants to change the tax rate"
3. Accept if all claims are true and the conditions for Refer are not met.

Changing the tax rate is NOT the same as having a specific amount of tax cancelled. A request to have a specific amount of tax cancelled does NOT warrant a Refer verdict.

Use context clues and common sense when interpreting OCR errors.

Do not include any explanation, markdown, code fences, or additional text.

Your response must look exactly like this:
[true, false, true, 1]
"""

class Verdict(Enum):
    ACCEPT = 0
    REJECT = 1 
    REFER = 2

class Controller:
    def __init__(self, dc: DocCore, pc: PC, ollama: Client):
        self.dc = dc
        self.pc = pc
        self.olla = ollama
    
    def answer(self, 
               b0: bool,
               b1: bool,
               b2: bool,
               v: int
               ):
        
        if b0: self.pc.move_to(Coords(1470, 734))
        else: self.pc.move_to(Coords(1375, 735))
        self.pc.click()  

        if b1: self.pc.move_to(Coords(1469, 768))
        else: self.pc.move_to(Coords(1348, 768))
        self.pc.click()

        if b2: self.pc.move_to(Coords(1470, 802))
        else: self.pc.move_to(Coords(1372, 802)) 
        self.pc.click()

        match v:
            case Verdict.ACCEPT: self.pc.move_to(Coords(681, 850))
            case Verdict.REJECT: self.pc.move_to(Coords(982, 848)) 
            case Verdict.REFER: self.pc.move_to(Coords(1243, 853)) 
    
    def sendInitialPrompt(self):
        res = self.olla.chat(
                model="qwen3:4b",
                messages=[
                    {
                        "role":"user",
                        "content": DEFAULT_INITIAL_PROMPT 
                        }
                    ]
                )
    def loop(self):
        self.pc.focus() 
        while not self.dc.isReadingDocs():
            self.pc.press(KeyCode.from_char("e"))
            time.sleep(2)
        
        docFrame = self.dc.getDocJson()
        res = self.olla.chat(
                model="qwen3:4b",
                messages=[
                    {
                        "role":"user",
                        "content": docFrame
                        }
                    ]
                )

        b0, b1, b2, v = json.loads(res.message.content)
        self.answer(b0, b1, b2, v)
        time.sleep(6)
