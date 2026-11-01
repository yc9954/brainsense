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
    X, y, split = d["tribe_roi"], d["y"].astype(float), d["split"]
    tr, te = split == "train", split == "test"
    n_val = max(20, int(tr.sum() * 0.2))
    idx = np.flatnonzero(tr); va, fit = idx[:n_val], idx[n_val:]
    h = Head(HeadConfig(name=name, task="binary", arch=arch, feature_key="tribe_roi",
                        feature_names=feature_names()))
    h.fit(X[fit], y[fit], X[va], y[va])
    p = h.predict(X[te])
    print(f"[bold]{name}[/]: n_train={len(fit)} auroc={roc_auc_score(y[te], p):.3f} "
          f"ece={expected_calibration_error(p, y[te]):.3f} T={h.scaler.T:.2f}")
    h.save(out / name)


@app.command()
def main(aesthetic: Path | None = None, attention: Path | None = None, appeal: Path | None = None,
         out: Path = Path("heads"), arch: str = "linear"):
    for name, store in (("aesthetic", aesthetic), ("attention", attention), ("appeal", appeal)):
        if store is not None:
            _train_one(name, store, out, arch)
    print(f"[green]heads saved under {out}/")


if __name__ == "__main__":
    app()
