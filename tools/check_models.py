"""
Tries every language model you have a key for on one small test letter with a KNOWN answer,
and shows what each one said, how long it took, and any error. Run it with check_models.bat.

The test letter's three claims are: TRUE (the body says so), TRUE (the seal matches Farmers Bay),
FALSE (Farmers Bay has 60 houses, the claim says 61). So a correct model answers [True, True, False].
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from shogunsryo import main as M
from shogunsryo.DecisionModel import MistralHTTPError, MistralModel

LETTER = {
    "Meta": {"Signed On": "1", "Times Written": "1", "Today": "0"},
    "Letter": {
        "From": "From Farmers Bay",
        "Intent": "Wants to speak to the Shogun",
        "Seal Color": [120, 177, 89],
        "Seal Village": "Farmers Bay",
        "Body": "We have looked after the hill shrine for 7 generations. Now we hear a samurai has been given "
                "the hill, and 5 strips of our shrine land with it.",
    },
    "Shisato": {"Ryo": "138", "Head": "Yasu", "Houses": "36", "Color": [85, 172, 238]},
    "Kotobo": {"Ryo": "127", "Head": "Kuma", "Houses": "29", "Color": [255, 172, 51]},
    "Farmers": {"Ryo": "100", "Head": "Ochiyo", "Houses": "60", "Color": [120, 177, 89]},
    "Market": {"Ryo": "169", "Head": "Hanzo", "Houses": "83", "Color": [221, 46, 68]},
    "Western Village": {"Ryo": "99", "Head": "Goro", "Houses": "27", "Color": [170, 142, 214]},
    "River Hamlet": {"Ryo": "79", "Head": "Kichi", "Houses": "25", "Color": [253, 203, 88]},
    "Claims": [
        "5 strips of shrine land went with the hill.",
        "This seal belongs to Farmers Bay.",
        "Farmers Bay has 61 houses.",
    ],
}
EXPECTED = [True, True, False]


def main() -> int:
    models = M.build_models()
    print()
    right = 0
    failed: dict[str, Exception] = {}
    for m in models:
        t0 = time.perf_counter()
        try:
            reply = json.loads(m.request(LETTER))
            got = [reply["claim1"], reply["claim2"], reply["claim3"]]
            ok = got == EXPECTED
            right += ok
            print(f"{m.model:28} {time.perf_counter() - t0:5.1f}s  answered {got}  {'CORRECT' if ok else 'WRONG (expected ' + str(EXPECTED) + ')'}")
            notes = getattr(m, "last_notes", "")
            if notes:
                print(f"{'':28} notes: {notes}")
            limits = getattr(m, "last_headers", {})
            if limits:
                print(f"{'':28} limits reported by the server: {limits}")
        except Exception as e:
            failed[m.model] = e
            print(f"{m.model:28} {time.perf_counter() - t0:5.1f}s  FAILED: {type(e).__name__}: {str(e)[:600]}")
    print(f"\n{right} of {len(models)} models answered correctly. (One letter is a small test; a wrong answer isn't proof a model is bad.)")

    # Mistral said "rate limited" straight away: see whether other Mistral models have their own allowance
    mistral = next((m for m in models if isinstance(m, MistralModel)), None)
    err = failed.get(mistral.model) if mistral else None
    if mistral and isinstance(err, MistralHTTPError) and err.status_code == 429:
        print("\nMistral refused the first request as rate limited. Trying other Mistral models one by one")
        print("(each can have its own limit; pausing between them so we don't trip a 1-per-second limit):")
        for name in ("ministral-8b-latest", "open-mistral-nemo", "ministral-3b-latest", "mistral-small-latest"):
            time.sleep(1.5)
            alt = MistralModel(mistral._key, name, notes=mistral._notes)
            alt._system, alt._schema = mistral._system, mistral._schema
            t0 = time.perf_counter()
            try:
                reply = json.loads(alt.request(LETTER))
                got = [reply["claim1"], reply["claim2"], reply["claim3"]]
                print(f"  {name:26} {time.perf_counter() - t0:5.1f}s  worked, answered {got}  {'CORRECT' if got == EXPECTED else 'WRONG'}")
            except Exception as e:
                print(f"  {name:26} {time.perf_counter() - t0:5.1f}s  FAILED: {type(e).__name__}: {str(e)[:300]}")
        print("\nIf one of those worked, put   MISTRAL_MODEL=<that name>   in your .env file.")
        print("If all say rate limited, open console.mistral.ai > Limits and check the numbers for your workspace.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
