"""Unified manifest format for all head datasets.

Every dataset is reduced to one CSV with columns:
    item_id, path (local media file), kind (image|video), label (float), split (train|test), source
Heads never see dataset-specific formats; the TRIBE service consumes `path`, the ablation
consumes `label`. Binary tasks use label in {0,1}; we binarize at the median per source unless
the dataset has a natural threshold."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = ["item_id", "path", "kind", "label", "split", "source"]


def write_manifest(rows: list[dict], out: Path, binarize: bool = True, seed: int = 0,
                   test_frac: float = 0.25) -> pd.DataFrame:
    if not rows:
        raise ValueError("no rows to write; check filters/download")
    df = pd.DataFrame(rows)
    if binarize and df["label"].nunique() > 2:
        df["label_raw"] = df["label"]
        df["label"] = (df["label"] > df["label"].median()).astype(int)
    rng = np.random.default_rng(seed)
    df["split"] = np.where(rng.random(len(df)) < test_frac, "test", "train")
    df = df[[c for c in COLUMNS if c in df.columns] + [c for c in df.columns if c not in COLUMNS]]
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    return df
