#!/bin/zsh
cd /Users/yuchanlee/brainsense-hackathon/brainsense
until grep -q "^EXIT" results/extract_aadb_area3.log; do sleep 60; done
echo "extract finished: $(grep -h '^EXIT' results/extract_aadb_area3.log)"
uv run python -c "import numpy as np;d=np.load('features/aadb_area.npz',allow_pickle=True);print({k:d[k].shape for k in d.files})"
uv run python scripts/train_heads.py --aesthetic features/aadb_area.npz --out heads_area2500
echo "RETRAIN_EXIT $?"
