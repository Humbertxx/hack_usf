#!/usr/bin/env bash
set -euo pipefail

echo "=== nvidia-smi ==="
nvidia-smi

echo "=== Python / PyTorch CUDA probe ==="
python3 <<'PY'
import torch

ver = torch.__version__.split("+")[0]
major, minor, *_ = ver.split(".", 2)
if (int(major), int(minor)) < (2, 8):
    raise SystemExit(
        f"Expected PyTorch >= 2.8 for RTX 5090 class GPUs; got {torch.__version__}"
    )

print("torch:", torch.__version__)
print("torch.cuda.is_available():", torch.cuda.is_available())
if torch.cuda.is_available():
    print("device:", torch.cuda.get_device_name(0))
    print("CUDA capability:", torch.cuda.get_device_capability(0))
    x = torch.randn(64, 64, device="cuda")
    y = x @ x
    print("matmul ok:", float(y[0, 0]))
else:
    raise SystemExit("CUDA not visible to PyTorch — check drivers / pod template.")
PY

echo "=== OK ==="
