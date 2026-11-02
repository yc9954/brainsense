#!/bin/zsh
# Text ("humanlike") head, end to end. GPU: ~1,200 short texts through TRIBE's text pathway (no video
# backbone) ≈ 1 s each on L40S → well under $3. Run only after the budget is approved.
set -e
cd "$(dirname "$0")/.."
PYTHONPATH=. .venv/bin/modal run scripts/extract_text_features.py::extract \
  --manifest data/hc3/manifest.csv --out features/hc3_text.npz --cache-dir features/cache_text
PYTHONPATH=. uv run python scripts/train_heads.py --humanlike features/hc3_text.npz --out heads_text
rm -rf heads/humanlike && cp -r heads_text/humanlike heads/humanlike
echo "humanlike head installed in heads/; restart the FastAPI server to load it"
