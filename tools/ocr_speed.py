"""
Where does the OCR time go? Run with ocr_speed.bat.

Part 1 times single OCR reads (so you can see if the game is slowing the GPU).
Part 2 reads a whole letter the author's way and the batched way (OCR_FAST), and shows any
field that reads differently. It uses the screenshots the app saved for the last letter it read.

Run it twice: once with Roblox CLOSED and once with Roblox OPEN (on the letter screen).
Send Claude the file(s) it saves in the debug folder.
"""
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import cv2
import numpy as np

from shogunsryo import main as M
from shogunsryo.DocCore import DocCore
from shogunsryo.utils.FastReader import FastReader
from shogunsryo.utils import Boost
from shogunsryo.utils.TextExtractor import TextExtractor

LOG: list[str] = []


def out(*a) -> None:
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


NAMES = (["Signed On", "Times Written", "Today", "From", "Intent", "Body"]
         + [f"{v}.{f}" for v in ("Shisato", "Kotobo", "Farmers", "Market", "Western Village", "River Hamlet")
            for f in ("Ryo", "Head", "Houses")]
         + ["Claim 1", "Claim 2", "Claim 3"])


def gpu_line() -> str:
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=10).stdout.strip()
        return r or "?"
    except Exception:
        return "?"


def roblox_running() -> bool:
    try:
        import psutil
        return any("roblox" in (p.info["name"] or "").lower() for p in psutil.process_iter(["name"]))
    except Exception:
        return False


def foreground_title() -> str:
    """Title of the window that is in front right now (so we can tell if the game was)."""
    if sys.platform != "win32":
        return "?"
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        return buf.value or "(no title)"
    except Exception:
        return "?"


def load(name: str) -> np.ndarray:
    im = cv2.imread(str(Path(M.__file__).parent / "test" / name))
    if im is None:
        sys.exit(f"Could not read the saved screenshot {name}. Run the app on one letter first.")
    return np.concatenate([im, np.full(im.shape[:2] + (1,), 255, np.uint8)], 2)


def main() -> int:
    delay = int(os.environ.get("OCR_SPEED_DELAY", "15") or 0)
    if delay:
        print(f"\nThe real app runs with Roblox in FRONT of this window. To measure the same thing,")
        print(f"click on the Roblox window (letter screen, fullscreen) within {delay} seconds.")
        print("(Run  ocr_speed.bat now  to skip this wait and measure with this window in front.)\n")
        for i in range(delay, 0, -1):
            print(f"  starting in {i:2d}s ...", end="\r", flush=True)
            time.sleep(1)
        print(" " * 40)
    if os.environ.get("BOOST", "1").strip().lower() not in ("0", "false", "no"):
        out("Boost:", Boost.apply())
    else:
        out("Boost: OFF (BOOST=0)")
    out(f"Roblox running: {roblox_running()} | window in front: {foreground_title()!r} | GPU utilisation / memory before: {gpu_line()}")
    ocr = M.build_ocr()
    device = getattr(ocr, "device_str", "?")
    te = TextExtractor(ocr)
    md0, md1, nar, q = (load(n) for n in ("test_md0", "test_md1", "test_nar", "test_q"))

    # ---- Part 1: single reads
    crop = md0[153:174, 485:513]
    for _ in range(3):
        te.extractFromImg(crop)  # warm-up
    times = []
    for _ in range(12):
        t0 = time.perf_counter()
        te.extractFromImg(crop)
        times.append((time.perf_counter() - t0) * 1000)
    med = statistics.median(times)
    out(f"\nPart 1: one OCR read ({device}): median {med:.0f} ms, slowest {max(times):.0f} ms, fastest {min(times):.0f} ms")
    out(f"        GPU utilisation / memory during: {gpu_line()} | window in front: {foreground_title()!r}")
    out("        => 27 reads per letter would take about", f"{med * 27 / 1000:.1f} s")

    # ---- Part 2: a whole letter
    dc = DocCore.__new__(DocCore)
    dc.TE = te
    crops: list[np.ndarray] = []
    real = te.extractFromImg
    te.extractFromImg = lambda img, *a, **k: (crops.append(img), "")[1]
    try:
        dc._extractFText(md0, md1, nar, q)
    finally:
        te.__dict__.pop("extractFromImg", None)
    out(f"\nPart 2: the letter needs {len(crops)} reads")
    names = NAMES if len(crops) == len(NAMES) else [f"crop {i}" for i in range(len(crops))]

    t0 = time.perf_counter()
    normal = [real(c) for c in crops]
    t_normal = time.perf_counter() - t0
    out(f"  the author's way (one read each):  {t_normal:.1f} s")

    fast = FastReader.create(te, ocr, getattr(ocr, "device_str", "cpu"))
    if fast is None:
        out("  batched way: not available on this machine (see the WARN line above)")
    else:
        for run in (1, 2):
            t0 = time.perf_counter()
            batched = fast.read_all(crops, real)
            t_fast = time.perf_counter() - t0
            out(f"  batched way, run {run}:              {t_fast:.1f} s   ({fast.last})")
        diffs = [(names[i], normal[i].strip(), batched[i].strip()) for i in range(len(crops)) if normal[i].strip() != batched[i].strip()]
        out(f"  fields that read DIFFERENTLY: {len(diffs)} of {len(crops)}")
        for n, a, b in diffs:
            out(f"      {n}: {a!r} (author's way)  vs  {b!r} (batched)")

    out("\nAll fields, the author's way:")
    for n, t in zip(names, normal):
        out(f"  {n:24} {t!r}")
    out(f"\nRoblox running: {roblox_running()} | GPU utilisation / memory after: {gpu_line()}")
    Path("debug").mkdir(exist_ok=True)
    name = "ocr_speed_roblox_in_front.txt" if delay else "ocr_speed_window_in_front.txt"
    Path("debug", name).write_text("\n".join(LOG), encoding="utf-8")
    out(f"Saved debug/{name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
