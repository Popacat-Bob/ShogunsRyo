"""
Checks whether PaddlePaddle can really use your NVIDIA GPU, and says what is wrong if not.
Run it with check_gpu.bat (or:  uv run python tools/check_gpu.py)
"""
import os
import subprocess
import sys
from pathlib import Path


def add_nvidia_dirs() -> list[str]:
    """Same trick main.py uses: expose pip-installed CUDA libraries to Windows."""
    roots = [Path(sys.prefix) / "Lib" / "site-packages"]
    found: list[str] = []
    for root in roots:
        for d in (root / "nvidia").glob("*/bin"):
            found.append(str(d))
    for d in found:
        try:
            os.add_dll_directory(d)
        except (OSError, AttributeError):
            pass
    if found:
        os.environ["PATH"] = os.pathsep.join(found) + os.pathsep + os.environ.get("PATH", "")
    return found


def main() -> int:
    print(f"Python {sys.version.split()[0]}")
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        print(f"NVIDIA GPU / driver: {out or '(nvidia-smi printed nothing)'}")
    except Exception as e:
        print(f"nvidia-smi not available ({type(e).__name__}). Is the NVIDIA driver installed?")

    dirs = add_nvidia_dirs()
    print("CUDA library folders from pip:", dirs if dirs else "NONE")
    for dll in ("cudnn64_9.dll", "cublas64_12.dll"):
        hits = [str(p) for d in dirs for p in Path(d).glob(dll)]
        print(f"  {dll}: {hits[0] if hits else 'NOT FOUND'}")

    try:
        import paddle
    except Exception as e:
        print(f"\nRESULT: PaddlePaddle would not even import ({type(e).__name__}: {e})")
        return 1
    cuda = paddle.device.is_compiled_with_cuda()
    count = paddle.device.cuda.device_count() if cuda else 0
    print(f"PaddlePaddle {paddle.__version__} | built with CUDA: {cuda} | GPUs visible: {count}")
    if not cuda:
        print("\nRESULT: You have the CPU-only PaddlePaddle. Run fix_opencv.bat (it reinstalls everything with uv sync).")
        return 1
    if count == 0:
        print("\nRESULT: PaddlePaddle has CUDA support but sees no GPU. Update your NVIDIA driver.")
        return 1

    try:
        paddle.set_device("gpu:0")
        conv = paddle.nn.Conv2D(3, 8, 3)  # convolutions are what need cuDNN
        y = conv(paddle.randn([1, 3, 64, 64]))
        try:
            paddle.device.synchronize()
        except AttributeError:
            paddle.device.cuda.synchronize()
        print("\nRESULT: GPU works. A convolution ran on the GPU.")
        return 0
    except Exception as e:
        msg = str(e)
        print(f"\nRESULT: the GPU test FAILED: {(msg.strip().splitlines() or [''])[0][:200]}")
        if "cudnn" in msg.lower():
            print("  cuDNN could not be loaded. Run fix_opencv.bat so nvidia-cudnn-cu12 gets installed,")
            print("  and make sure the 'cudnn64_9.dll' line above is not NOT FOUND.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
