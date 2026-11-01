#!/usr/bin/env bash
# Runs the brain-vs-raw ablation for every feature store, then trains + calibrates the heads.
set -euo pipefail
cd "$(dirname "$0")/.."
for d in unsplash aadb snapugc; do
  [ -f features/$d.npz ] || { echo "skip $d (no features)"; continue; }
  echo "=== ablation: $d"
  uv run python -m brainsense.heads.ablation features/$d.npz --out results/ablation_$d --sizes 25,50,100,200,all --seeds 5
done
args=()
[ -f features/unsplash.npz ] && args+=(--appeal features/unsplash.npz)
[ -f features/aadb.npz ]     && args+=(--aesthetic features/aadb.npz)
[ -f features/snapugc.npz ]  && args+=(--attention features/snapugc.npz)
echo "=== heads"; PYTHONPATH=. uv run python scripts/train_heads.py "${args[@]}" --out heads
