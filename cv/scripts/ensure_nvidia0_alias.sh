#!/usr/bin/env bash
# Some GPU pods (partial device injection) expose only /dev/nvidiaN with N>0.
# NVML/nvidia-smi may still show "GPU 0", but CUDA can fail to init without /dev/nvidia0.
#
# Strategy (try in order):
#   1) Symlink /dev/nvidia0 -> the lone GPU node (no CAP_MKNOD; works on many hosts).
#   2) mknod with same major/minor as that node (needs permission; often blocked in K8s/RunPod).
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

if ln -sf "$src" /dev/nvidia0 2>/dev/null; then
  echo "Created /dev/nvidia0 -> symlink to $src"
  echo "Next: bash cv/scripts/verify_runpod_gpu.sh"
  exit 0
fi

read -r hex_maj hex_min < <(stat -c '%t %T' "$src")
maj=$((16#$hex_maj))
min=$((16#$hex_min))

if mknod /dev/nvidia0 c "$maj" "$min" 2>/dev/null; then
  chmod 666 /dev/nvidia0
  echo "Created /dev/nvidia0 (char $maj $min) — same device as $src"
  echo "Next: bash cv/scripts/verify_runpod_gpu.sh"
  exit 0
fi

cat <<'EOF' >&2
Could not create /dev/nvidia0 (symlink and mknod both failed).

Common on managed pods: /dev is read-only or CAP_MKNOD is dropped, so you cannot add nodes
from inside the container.

What to do instead:
  • Recreate the pod using a RunPod GPU template that exposes the usual /dev/nvidia0
    (official PyTorch or NVIDIA CUDA base images often do).
  • Ask RunPod support whether your template should inject nvidia0 for single-GPU pods.

Manual try (if /dev is writable):  ln -sf THE_ONLY_NODE /dev/nvidia0
  Example:  ln -sf /dev/nvidia7 /dev/nvidia0
EOF
exit 1
