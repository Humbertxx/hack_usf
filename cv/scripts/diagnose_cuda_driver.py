#!/usr/bin/env python3
"""Call NVIDIA Driver API (libcuda) directly — narrows PyTorch vs driver vs env."""
from __future__ import annotations

import ctypes
import glob
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
    100: "CUDA_ERROR_NO_DEVICE",
    101: "CUDA_ERROR_INVALID_DEVICE",
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


def _check_dev_nvidia() -> dict:
    """Check /dev/nvidia* devices and their accessibility."""
    result = {
        "nvidia_devices": [],
        "nvidia_uvm": False,
        "nvidia_uvm_tools": False,
        "nvidia_ctl": False,
        "issues": [],
    }

    # Find all /dev/nvidia* devices
    nvidia_devs = sorted(glob.glob("/dev/nvidia*"))
    result["nvidia_devices"] = nvidia_devs

    for dev in nvidia_devs:
        if dev == "/dev/nvidia-uvm":
            result["nvidia_uvm"] = True
        elif dev == "/dev/nvidia-uvm-tools":
            result["nvidia_uvm_tools"] = True
        elif dev == "/dev/nvidiactl":
            result["nvidia_ctl"] = True

    # Check for specific issues
    if not result["nvidia_uvm"]:
        result["issues"].append("CRITICAL: /dev/nvidia-uvm missing — cuInit will fail")
    if not result["nvidia_ctl"]:
        result["issues"].append("CRITICAL: /dev/nvidiactl missing — no GPU control device")

    # Check for device number mismatch (e.g., /dev/nvidia7 without /dev/nvidia0)
    gpu_devs = [d for d in nvidia_devs if d.startswith("/dev/nvidia") and d[12:].isdigit()]
    if gpu_devs:
        device_nums = sorted(int(d[12:]) for d in gpu_devs)
        if device_nums and device_nums[0] != 0:
            result["issues"].append(
                f"WARNING: GPU device numbering starts at {device_nums[0]} (expected 0). "
                f"Found: {gpu_devs}. This may cause device ordinal issues."
            )

    return result


def _check_nvidia_uvm_module() -> dict:
    """Check if nvidia-uvm kernel module is loaded."""
    result = {"loaded": False, "in_proc_devices": False, "device_major": None}

    # Check /proc/modules
    try:
        with open("/proc/modules", encoding="utf-8") as f:
            for line in f:
                if line.startswith("nvidia_uvm "):
                    result["loaded"] = True
                    break
    except OSError:
        pass

    # Check /proc/devices for nvidia-uvm
    try:
        with open("/proc/devices", encoding="utf-8") as f:
            for line in f:
                if "nvidia-uvm" in line:
                    result["in_proc_devices"] = True
                    parts = line.split()
                    if parts and parts[0].isdigit():
                        result["device_major"] = int(parts[0])
                    break
    except OSError:
        pass

    return result


def _run_nvidia_smi() -> tuple[bool, str]:
    """Run nvidia-smi and return success status and output."""
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,uuid", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return proc.returncode == 0, proc.stdout.strip() or proc.stderr.strip()
    except FileNotFoundError:
        return False, "nvidia-smi not found"
    except subprocess.TimeoutExpired:
        return False, "nvidia-smi timed out"
    except Exception as e:
        return False, str(e)


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


def _print_fix_suggestions(dev_check: dict, uvm_check: dict) -> None:
    """Print actionable fix suggestions based on detected issues."""
    print("\n" + "=" * 60, file=sys.stderr)
    print("DIAGNOSIS & FIX SUGGESTIONS", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    if not uvm_check["in_proc_devices"] or not dev_check["nvidia_uvm"]:
        print(
            "\n[1] nvidia-uvm module/device issue detected.\n"
            "    Try these fixes (may require host access or pod restart):\n\n"
            "    # If you have root/sudo on the HOST:\n"
            "    sudo modprobe nvidia-uvm\n\n"
            "    # If /dev/nvidia-uvm is missing but module is loaded:\n"
            "    # Get the major device number:\n"
            "    grep nvidia-uvm /proc/devices\n"
            "    # Create the device (replace <MAJOR> with actual number):\n"
            "    sudo mknod -m 666 /dev/nvidia-uvm c <MAJOR> 0\n"
            "    sudo mknod -m 666 /dev/nvidia-uvm-tools c <MAJOR> 1\n",
            file=sys.stderr,
        )

    if dev_check["issues"]:
        for issue in dev_check["issues"]:
            if "numbering starts at" in issue:
                print(
                    "\n[2] GPU device index mismatch detected.\n"
                    "    The container sees a non-zero GPU device number.\n"
                    "    Possible fixes:\n\n"
                    "    # Set CUDA_VISIBLE_DEVICES to remap:\n"
                    "    export CUDA_VISIBLE_DEVICES=0\n\n"
                    "    # Or when starting the container, use explicit device mapping:\n"
                    "    docker run --device=/dev/nvidia7:/dev/nvidia0 ...\n\n"
                    "    # Or use GPU UUID instead of index:\n"
                    "    nvidia-smi -L  # to get UUID\n"
                    "    export CUDA_VISIBLE_DEVICES=GPU-<uuid>\n",
                    file=sys.stderr,
                )

    print(
        "\n[3] General RunPod/container fixes:\n"
        "    - Restart the pod (sometimes fixes transient driver issues)\n"
        "    - Use a different pod template with CUDA pre-configured\n"
        "    - Check if the host has multiple GPUs and only some are allocated\n"
        "    - Verify NVIDIA_DRIVER_CAPABILITIES includes 'compute'\n",
        file=sys.stderr,
    )


def main() -> int:
    print("=== Environment Variables ===")
    for k in (
        "LD_LIBRARY_PATH",
        "CUDA_VISIBLE_DEVICES",
        "NVIDIA_VISIBLE_DEVICES",
        "NVIDIA_DRIVER_CAPABILITIES",
    ):
        print(f"{k}={os.environ.get(k, '<unset>')}")

    _warn_visible_devices()

    # Check nvidia-smi first
    print("\n=== nvidia-smi ===")
    smi_ok, smi_out = _run_nvidia_smi()
    if smi_ok:
        print("nvidia-smi OK:")
        for line in smi_out.split("\n"):
            print(f"  {line}")
    else:
        print(f"nvidia-smi FAILED: {smi_out}", file=sys.stderr)

    # Check /dev/nvidia* devices
    print("\n=== /dev/nvidia* Devices ===")
    dev_check = _check_dev_nvidia()
    if dev_check["nvidia_devices"]:
        print("Found devices:")
        for dev in dev_check["nvidia_devices"]:
            # Check permissions
            try:
                readable = os.access(dev, os.R_OK)
                writable = os.access(dev, os.W_OK)
                perm = f"r={'Y' if readable else 'N'} w={'Y' if writable else 'N'}"
            except Exception:
                perm = "unknown"
            print(f"  {dev} ({perm})")
    else:
        print("  NO /dev/nvidia* devices found!", file=sys.stderr)

    if dev_check["issues"]:
        print("\nDevice issues:")
        for issue in dev_check["issues"]:
            print(f"  {issue}", file=sys.stderr)

    # Check nvidia-uvm module
    print("\n=== nvidia-uvm Module ===")
    uvm_check = _check_nvidia_uvm_module()
    print(f"Module loaded: {uvm_check['loaded']}")
    print(f"In /proc/devices: {uvm_check['in_proc_devices']}")
    if uvm_check["device_major"]:
        print(f"Device major number: {uvm_check['device_major']}")

    # Check which libcuda
    print("\n=== libcuda Location ===")
    try:
        proc = subprocess.run(
            ["ldconfig", "-p"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in proc.stdout.split("\n"):
            if "libcuda.so" in line:
                print(line.strip())
    except Exception as e:
        print(f"ldconfig failed: {e}")

    # Try loading libcuda
    print("\n=== ctypes CDLL('libcuda.so.1') ===")
    try:
        lib = ctypes.CDLL("libcuda.so.1")
    except OSError as e:
        print(f"Failed to load libcuda.so.1: {e}", file=sys.stderr)
        return 1

    # Show which library was actually loaded
    for p in _loaded_libcuda_paths():
        print(f"Mapped executable libcuda (from /proc/self/maps):\n  {p}")

    # Check for stub library issue
    ld_path = os.environ.get("LD_LIBRARY_PATH", "")
    if "/usr/local/cuda" in ld_path:
        print(
            "\n*** WARNING: LD_LIBRARY_PATH contains /usr/local/cuda paths.\n"
            "    Toolkit copies are often **stubs** — cuInit then returns CUDA_ERROR_UNKNOWN.\n"
            "    Prefer: unset LD_LIBRARY_PATH (or remove /usr/local/cuda/... from it).\n",
            file=sys.stderr,
        )

    cu_init = lib.cuInit
    cu_init.argtypes = [c_uint]
    cu_init.restype = c_int

    cu_device_get_count = lib.cuDeviceGetCount
    cu_device_get_count.argtypes = [ctypes.POINTER(c_int)]
    cu_device_get_count.restype = c_int

    err = cu_init(0)
    print(f"\ncuInit(0) -> {_cu_result_name(err)} ({err})")

    if err != _CUDA_SUCCESS:
        print(
            "\nDriver init failed before device count — PyTorch will also fail here.",
            file=sys.stderr,
        )

        # Print detailed fix suggestions
        _print_fix_suggestions(dev_check, uvm_check)

        if (
            err == 999
            and os.environ.get("LD_LIBRARY_PATH")
            and _NO_LD_RETRY_FLAG not in os.environ
        ):
            print(
                "\n--- Retrying with LD_LIBRARY_PATH unset ---\n",
                file=sys.stderr,
            )
            env = {k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}
            env[_NO_LD_RETRY_FLAG] = "1"
            script = os.path.abspath(__file__)
            os.execve(sys.executable, [sys.executable, script], env)

        return 2

    n = c_int()
    err2 = cu_device_get_count(byref(n))
    print(f"cuDeviceGetCount -> {_cu_result_name(err2)} ({err2}), count={n.value}")

    if err2 != _CUDA_SUCCESS:
        return 3
    if n.value < 1:
        print(
            "Driver reports zero devices — check nvidia-smi vs container injection.",
            file=sys.stderr,
        )
        return 4

    print("\n" + "=" * 60)
    print("SUCCESS: Driver API sees at least one GPU!")
    print("=" * 60)
    print("\nIf torch.cuda.is_available() is still False:")
    print("  1. unset LD_LIBRARY_PATH  # conflicting user-space stack")
    print("  2. Reinstall PyTorch with matching CUDA version")
    print("  3. Use RunPod PyTorch/CUDA template")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
