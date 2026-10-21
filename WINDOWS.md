# Running the original code on Windows

Everything here is the author's code, unchanged, except these files:

| File | Why it had to change |
|---|---|
| `utils/ProcessControls.py` | The original controls the Sober window with Linux tools. This version finds Roblox on Windows and sends clicks/scrolls/keys that Roblox accepts. |
| `utils/ScreenCapture.py`, `utils/Scale.py` | The coordinates are for a 1920x1080 screen. On any other resolution they are scaled. At 1920x1080 this does nothing at all. |
| `main.py` | Adds the GPU libraries to the search path and picks the GPU (or CPU). The PaddleOCR settings are the author's. |
| `DecisionModel.py` | Only the imports: `openai` isn't installed by anything, and only an unused class needs it. |
| `pyproject.toml` | Windows + NVIDIA GPU packages (and one OpenCV only). |

Added, and OFF unless you ask for it: `utils/FastReader.py`. With `OCR_FAST=1` a letter's ~27 OCR reads are
done in one batch instead of one by one (the author's `DocCore`/`TextExtractor` are not edited; see the file's header).
Anything it is unsure about is read the author's way. `ocr_speed.bat` measures the speed and lists any field that
would read differently.

Also added (switch off with `BOOST=0`): `utils/Boost.py`. While the game is in front of this program, Windows can
slow it down, so it asks for high CPU priority, no power throttling and high GPU scheduling priority. `main.py` also prints
how long each letter's OCR takes (`SHOW_TIMING=0` hides it). Neither changes what the OCR reads.

Not changed: `Controller.py`, `DocCore.py`, `TextExtractor.py`, the prompt, the models, the OCR thresholds, all coordinates.

## Best accuracy: set Windows to 1920x1080
The author's coordinates were measured at 1920x1080, so on that resolution the code behaves exactly
like the original. Settings > System > Display > Display resolution > 1920x1080, with Roblox fullscreen.
(It also takes load off the GPU, which helps OCR speed.)

## Setup
1. `uv sync` in this folder (big download the first time).
2. Copy `.env.example` to `.env` and add your keys.
3. Double-click `run.bat`.

Helpers: `check_gpu.bat` (is the GPU usable?), `fix_opencv.bat` (rebuilds the environment), `fix_permissions.bat`.
