"""Train + calibrate the three crowd heads from feature stores and save them for the agent.

    python scripts/train_heads.py --aesthetic features/aadb.npz --attention features/snapugc.npz \
        --appeal features/unsplash.npz --out heads/
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import typer
from rich import print
from sklearn.metrics import roc_auc_score

from brainsense.heads.head import Head, HeadConfig, expected_calibration_error
from brainsense.tribe.rois import feature_names

app = typer.Typer(add_completion=False)


def _train_one(name: str, store: Path, out: Path, arch: str) -> None:
    d = np.load(store, allow_pickle=True)
    y, split = d["y"].astype(float), d["split"]
    use_area = "roi_area" in d and d["roi_area"].shape[1] >= 360
    if use_area:   # 360 per-area means → PCA-54 → linear head (AADB-600: 0.753 vs 0.669 for the 54-d groups)
        X = d["roi_area"][:, :360]
        names = [str(n).replace("__mean", "") for n in d["roi_area_names"][:360]] if "roi_area_names" in d else [f"area{i}" for i in range(360)]
        cfg = HeadConfig(name=name, task="binary", arch=arch, feature_key="roi_area_mean", feature_names=names, pca_dim=54, C=0.1)
    else:
        X = d["tribe_roi"]
        cfg = HeadConfig(name=name, task="binary", arch=arch, feature_key="tribe_roi", feature_names=feature_names())
    tr, te = split == "train", split == "test"
    n_val = max(20, int(tr.sum() * 0.2))
    idx = np.flatnonzero(tr); va, fit = idx[:n_val], idx[n_val:]
    h = Head(cfg)
    h.fit(X[fit], y[fit], X[va], y[va])
    p = h.predict(X[te])
    print(f"[bold]{name}[/] ({cfg.feature_key}): n_train={len(fit)} auroc={roc_auc_score(y[te], p):.3f} "
          f"ece={expected_calibration_error(p, y[te]):.3f} T={h.scaler.T:.2f}")
    h.save(out / name)


@app.command()
def main(aesthetic: Path | None = None, attention: Path | None = None, appeal: Path | None = None,
         popularity: Path | None = None, humanlike: Path | None = None, hook: Path | None = None,
         out: Path = Path("heads"), arch: str = "linear"):
    for name, store in (("aesthetic", aesthetic), ("attention", attention), ("appeal", appeal), ("popularity", popularity),
                        ("humanlike", humanlike), ("hook", hook)):
        if store is not None:
            _train_one(name, store, out, arch)
    print(f"[green]heads saved under {out}/")


if __name__ == "__main__":
    app()
