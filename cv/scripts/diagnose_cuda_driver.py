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


def main() -> int:
    print("=== environment ===")
    for k in (
        "LD_LIBRARY_PATH",
        "CUDA_VISIBLE_DEVICES",
        "NVIDIA_VISIBLE_DEVICES",
        "NVIDIA_DRIVER_CAPABILITIES",
    ):
        print(f"{k}={os.environ.get(k, '<unset>')}")

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
