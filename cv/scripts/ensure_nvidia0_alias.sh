#!/usr/bin/env bash
# Some GPU pods (partial device injection) expose only /dev/nvidiaN with N>0.
# NVML/nvidia-smi may still show "GPU 0", but CUDA can fail to init without /dev/nvidia0.
# This creates /dev/nvidia0 as the SAME character device (same major/minor as the lone GPU node).
# Ephemeral: redo after pod restart. Skip if multiple /dev/nvidia[0-9] (ambiguous).
set -euo pipefail

if [[ -e /dev/nvidia0 ]]; then
  echo "/dev/nvidia0 already exists — nothing to do."
  exit 0
fi

shopt -s nullglob
nodes=(/dev/nvidia[0-9])
shopt -u nullglob

if ((${#nodes[@]} == 0)); then
  echo "No /dev/nvidia[0-9] found — cannot create alias." >&2
  exit 1
fi

if ((${#nodes[@]} > 1)); then
  echo "Multiple GPU nodes: ${nodes[*]}" >&2
  echo "Refusing to pick nvidia0; use a multi-GPU-aware setup or fix the template." >&2
  exit 1
fi

src=${nodes[0]}
read -r hex_maj hex_min < <(stat -c '%t %T' "$src")
maj=$((16#$hex_maj))
min=$((16#$hex_min))

mknod /dev/nvidia0 c "$maj" "$min"
chmod 666 /dev/nvidia0
echo "Created /dev/nvidia0 (char $maj $min) — same device as $src"
echo "Next: bash cv/scripts/verify_runpod_gpu.sh"
