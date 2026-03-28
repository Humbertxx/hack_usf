#!/usr/bin/env python3
"""Call NVIDIA Driver API (libcuda) directly — narrows PyTorch vs driver vs env."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import byref, c_int, c_uint

# CUresult (subset)
_CUDA_SUCCESS = 0
_ERRORS = {
    0: "CUDA_SUCCESS",
    1: "CUDA_ERROR_INVALID_VALUE",
    2: "CUDA_ERROR_OUT_OF_MEMORY",
    3: "CUDA_ERROR_NOT_INITIALIZED",
    999: "CUDA_ERROR_UNKNOWN",
}


def _cu_result_name(code: int) -> str:
    return _ERRORS.get(code, f"CUresult({code})")


_NO_LD_RETRY_FLAG = "_CUDA_DIAG_NO_LD_RETRY"


def _loaded_libcuda_paths() -> list[str]:
    """Best-effort: mapped libcuda .so paths for this process (Linux)."""
    paths: list[str] = []
    try:
        with open("/proc/self/maps", encoding="utf-8", errors="replace") as f:
            for line in f:
                if "libcuda.so" in line and " r-xp " in line:
                    parts = line.split()
                    if len(parts) >= 6:
                        p = parts[-1]
                        if p.startswith("/") and p not in paths:
                            paths.append(p)
    except OSError:
        pass
    return paths


def _warn_visible_devices() -> None:
    raw = os.environ.get("NVIDIA_VISIBLE_DEVICES")
    if raw is None:
        return
    if raw.strip().lower() == "void":
        print(
            "\n*** NVIDIA_VISIBLE_DEVICES=void tells the NVIDIA container stack not to expose GPUs\n"
            "    to CUDA (cuInit / PyTorch), even if nvidia-smi works.\n\n"
            "    Fix, then re-run:\n"
            "      export NVIDIA_VISIBLE_DEVICES=all\n"
            "    or:\n"
            "      unset NVIDIA_VISIBLE_DEVICES\n\n"
            "    If it keeps resetting, find what sets it (e.g. grep ~/.bashrc /etc/profile /workspace — 'void').\n",
            file=sys.stderr,
        )


def main() -> int:
    print("=== environment ===")
    for k in (
        "LD_LIBRARY_PATH",
        "CUDA_VISIBLE_DEVICES",
        "NVIDIA_VISIBLE_DEVICES",
        "NVIDIA_DRIVER_CAPABILITIES",
    ):
        print(f"{k}={os.environ.get(k, '<unset>')}")

    _warn_visible_devices()

    print("\n=== which libcuda ===")
    # Prefer what ldconfig knows; fallback to implicit load path
    try:
        out = subprocess.run(
            ["ldconfig", "-p"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            for line in out.stdout.splitlines():
                if "libcuda.so" in line:
                    print(line.strip())
        else:
            print("(ldconfig -p failed or unavailable)")
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"(skipped: {e})")

    print("\n=== ctypes CDLL('libcuda.so.1') ===")
    try:
        lib = ctypes.CDLL("libcuda.so.1")
    except OSError as e:
        print("FAILED:", e, file=sys.stderr)
        return 1

    mapped = _loaded_libcuda_paths()
    if mapped:
        print("Mapped executable libcuda (from /proc/self/maps):")
        for p in mapped:
            print(" ", p)
        if any("/usr/local/cuda" in p or "stubs" in p for p in mapped):
            print(
                "\nWARNING: libcuda is loading from the CUDA toolkit tree, not only the host driver.\n"
                "         Toolkit copies are often **stubs** — cuInit then returns CUDA_ERROR_UNKNOWN.\n"
                "         Prefer: unset LD_LIBRARY_PATH  (or remove /usr/local/cuda/... from it).\n",
                file=sys.stderr,
            )

    cu_init = lib.cuInit
    cu_init.argtypes = [c_uint]
    cu_init.restype = c_int

    cu_device_get_count = lib.cuDeviceGetCount
    cu_device_get_count.argtypes = [ctypes.POINTER(c_int)]
    cu_device_get_count.restype = c_int

    err = cu_init(0)
    print("cuInit(0) ->", _cu_result_name(err), f"({err})")
    if err != _CUDA_SUCCESS:
        print(
            "Driver init failed before device count — PyTorch will also fail here.",
            file=sys.stderr,
        )
        if (
            err == 999
            and os.environ.get("LD_LIBRARY_PATH")
            and _NO_LD_RETRY_FLAG not in os.environ
        ):
            print(
                "\nRe-running this script with LD_LIBRARY_PATH unset (one automatic retry)…\n",
                file=sys.stderr,
            )
            env = {k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}
            env[_NO_LD_RETRY_FLAG] = "1"
            script = os.path.abspath(__file__)
            os.execve(sys.executable, [sys.executable, script], env)
        print(
            "\nIf cuInit stayed failing: check /dev/nvidia*, NVIDIA_VISIBLE_DEVICES=void, pod image;\n"
            "or run:  env -u LD_LIBRARY_PATH python3 " + os.path.abspath(__file__),
            file=sys.stderr,
        )
        return 2

    n = c_int()
    err2 = cu_device_get_count(byref(n))
    print("cuDeviceGetCount ->", _cu_result_name(err2), f"({err2}), count={n.value}")
    if err2 != _CUDA_SUCCESS:
        return 3
    if n.value < 1:
        print("Driver reports zero devices — check nvidia-smi vs container injection.", file=sys.stderr)
        return 4

    print("\nDriver API sees at least one GPU. If torch.cuda.is_available() is still False,")
    print("try: unset LD_LIBRARY_PATH  # then re-test  # conflicting user-space stack")
    print("or install a RunPod PyTorch/CUDA template; or PyTorch nightly if sm_120 edge case.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
