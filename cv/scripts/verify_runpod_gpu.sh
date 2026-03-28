#!/usr/bin/env bash
set -euo pipefail

echo "=== CUDA-related environment ==="
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES-<unset>}"
echo "NVIDIA_VISIBLE_DEVICES=${NVIDIA_VISIBLE_DEVICES-<unset>}"
echo "NVIDIA_DRIVER_CAPABILITIES=${NVIDIA_DRIVER_CAPABILITIES-<unset>}"
if [[ "${NVIDIA_VISIBLE_DEVICES-}" == "void" ]]; then
  echo
  echo "WARNING: NVIDIA_VISIBLE_DEVICES=void disables CUDA for PyTorch/libcuda; use:" >&2
  echo "  export NVIDIA_VISIBLE_DEVICES=all   # or: unset NVIDIA_VISIBLE_DEVICES" >&2
fi
echo

echo "=== NVIDIA device nodes (GPU must be passed into the container) ==="
if ls /dev/nvidia* >/dev/null 2>&1; then
  ls -la /dev/nvidia*
  echo
  echo "Character devices matching /dev/nvidia[0-9]:"
  shopt -s nullglob
  nodes=(/dev/nvidia[0-9])
  shopt -u nullglob
  if ((${#nodes[@]} == 0)); then
    echo "(none — unusual; CUDA may still work via nvidiactl + UVM)"
  else
    printf ' %s\n' "${nodes[@]}"
  fi
  if [[ ! -e /dev/nvidia0 ]]; then
    echo
    echo "NOTE: /dev/nvidia0 is missing. Some stacks expect it; nvidia-smi can still work." >&2
    echo "      Try: sudo bash cv/scripts/ensure_nvidia0_alias.sh (ephemeral; one GPU node only)" >&2
    echo "      Or: export NVIDIA_VISIBLE_DEVICES=all && re-run; else new pod / GPU template." >&2
  fi
else
  echo "No /dev/nvidia* — this pod almost certainly is not GPU-enabled, or the runtime did not inject devices."
fi
echo

echo "=== nvidia-smi ==="
if ! nvidia-smi; then
  echo "nvidia-smi failed — fix GPU passthrough / pod template before PyTorch can use CUDA." >&2
  exit 1
fi
echo

echo "=== libcuda (driver user-space library) ==="
python3 <<'PY'
import ctypes
import sys

try:
    ctypes.CDLL("libcuda.so.1")
    print("libcuda.so.1: load OK")
except OSError as e:
    print("libcuda.so.1: FAILED —", e, file=sys.stderr)
    sys.exit(1)
PY
echo

echo "=== Python / PyTorch CUDA probe ==="
python3 <<'PY'
import sys

import torch

ver = torch.__version__.split("+")[0]
major, minor, *_ = ver.split(".", 2)
if (int(major), int(minor)) < (2, 8):
    raise SystemExit(
        f"Expected PyTorch >= 2.8 for RTX 5090 class GPUs; got {torch.__version__}"
    )

print("torch:", torch.__version__)
print("torch.version.cuda:", torch.version.cuda)
print("torch.cuda.is_available():", torch.cuda.is_available())
if not torch.cuda.is_available():
    print(
        "\nPyTorch reports CUDA unavailable. If nvidia-smi worked above, common causes:\n"
        "  - Stale pod: stop and start a fresh GPU pod.\n"
        "  - Empty CUDA_VISIBLE_DEVICES: unset CUDA_VISIBLE_DEVICES or set to 0 (not '').\n"
        "  - Host driver too old for this PyTorch build: upgrade template / contact RunPod.\n"
        "  - Mixed installs: ensure `which python3` matches the env where torch was installed.\n"
        "  - Odd /dev nodes: symlink e.g. ln -sf /dev/nvidia7 /dev/nvidia0 (if /dev writable).\n"
        "  - If symlink exists but CUDA still fails: python3 cv/scripts/diagnose_cuda_driver.py\n"
        "    (cuInit vs PyTorch) and try unset LD_LIBRARY_PATH or a different RunPod GPU image.",
        file=sys.stderr,
    )
    raise SystemExit(1)

print("device:", torch.cuda.get_device_name(0))
print("CUDA capability:", torch.cuda.get_device_capability(0))
x = torch.randn(64, 64, device="cuda")
y = x @ x
print("matmul ok:", float(y[0, 0]))
PY

echo "=== OK ==="
