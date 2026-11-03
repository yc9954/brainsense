"""The pitch-critical experiment: brain-bottleneck features vs. raw-embedding features.

TRIBE's predicted fMRI is a deterministic function of the backbone embeddings, so it cannot
add information (data processing inequality). The only honest claims are
  (a) better sample-efficiency at small n (fMRI-pretrained structure acts as a prior), and/or
  (b) interpretability (ROI-level explanations).
This script measures (a) directly: for each feature set and each training size, fit the same
head, evaluate on a fixed held-out split, repeat over seeds, and report mean +- std.

Feature store format (.npz):
    ids        : (N,) str
    y          : (N,) float  (0/1 for binary, continuous for regression)
    tribe_roi  : (N, D1)  ROI x time-pooled TRIBE predictions
    raw_embed  : (N, D2)  pooled backbone embeddings (same inputs, no brain model)
    [any extra feature keys are also compared if listed with --features]
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import typer
from rich.console import Console
from rich.table import Table
from sklearn.metrics import average_precision_score, r2_score, roc_auc_score
from sklearn.model_selection import train_test_split

from .head import Head, HeadConfig, expected_calibration_error

app = typer.Typer(add_completion=False)
console = Console()


def _metric(task: str, y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    if task == "binary":
        return {"auroc": roc_auc_score(y, p), "auprc": average_precision_score(y, p),
                "ece": expected_calibration_error(p, y)}
    return {"r2": r2_score(y, p), "pearson": float(np.corrcoef(y, p)[0, 1])}


@app.command()
def run(
    store: Path = typer.Argument(..., help=".npz feature store"),
    out: Path = typer.Option(Path("results/ablation"), help="output dir"),
    task: str = typer.Option("binary"),
    arch: str = typer.Option("linear", help="linear | mlp"),
    features: str = typer.Option("tribe_roi,raw_embed", help="comma-separated keys to compare"),
    sizes: str = typer.Option("25,50,100,200,500,1000,all"),
    seeds: int = typer.Option(5),
    test_frac: float = typer.Option(0.25),
    pca_dim: int = typer.Option(54, help="width of the PCA-compressed raw baseline; 0 to disable"),
):
    d = np.load(store, allow_pickle=True)
    y = d["y"].astype(float)
    keys = [k.strip() for k in features.split(",")]
    n = len(y)
    idx_tr_full, idx_te = train_test_split(np.arange(n), test_size=test_frac, random_state=0,
                                           stratify=y if task == "binary" else None)
    size_list = [n if s == "all" else int(s) for s in sizes.split(",")]
    size_list = sorted({min(s, len(idx_tr_full)) for s in size_list})

    rows = []
    # Fair control: the brain features are 54-d, the raw embedding is 1408-d. Add a PCA-compressed
    # raw baseline of the same width so "brain wins" cannot be explained by dimensionality alone.
    feats: dict[str, np.ndarray] = {k: d[k].astype(np.float32) for k in keys}
    if pca_dim and "raw_embed" in feats:
        from sklearn.decomposition import PCA
        pca = PCA(n_components=pca_dim, random_state=0).fit(feats["raw_embed"][idx_tr_full])
        feats[f"raw_pca{pca_dim}"] = pca.transform(feats["raw_embed"]).astype(np.float32)
        keys = keys + [f"raw_pca{pca_dim}"]
    for key in keys:
        X = feats[key]
        for sz in size_list:
            for seed in range(seeds):
                rng = np.random.default_rng(seed)
                sub = rng.choice(idx_tr_full, size=sz, replace=False)
                # carve a small val split for temperature scaling when there is room
                if sz >= 80:
                    tr, va = train_test_split(sub, test_size=0.2, random_state=seed)
                else:
                    tr, va = sub, None
                h = Head(HeadConfig(name=f"{key}", task=task, arch=arch, feature_key=key, seed=seed))
                h.fit(X[tr], y[tr], None if va is None else X[va], None if va is None else y[va])
                m = _metric(task, y[idx_te], h.predict(X[idx_te]))
                rows.append({"features": key, "n_train": sz, "seed": seed, **m})
    df = pd.DataFrame(rows)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "runs.csv", index=False)
    primary = "auroc" if task == "binary" else "r2"
    summary = df.groupby(["features", "n_train"])[primary].agg(["mean", "std"]).reset_index()
    summary.to_csv(out / "summary.csv", index=False)

    tbl = Table(title=f"{primary} by training size (mean ± std over {seeds} seeds)")
    tbl.add_column("n_train", justify="right")
    for key in keys:
        tbl.add_column(key)
    for sz in size_list:
        cells = []
        for key in keys:
            r = summary[(summary.features == key) & (summary.n_train == sz)].iloc[0]
            cells.append(f"{r['mean']:.3f} ± {r['std']:.3f}")
        tbl.add_row(str(sz), *cells)
    console.print(tbl)

    # Headline: at which sizes does the brain-bottleneck win?
    if "tribe_roi" in keys and "raw_embed" in keys:
        wins = []
        for sz in size_list:
            a = summary[(summary.features == "tribe_roi") & (summary.n_train == sz)]["mean"].item()
            b = summary[(summary.features == "raw_embed") & (summary.n_train == sz)]["mean"].item()
            wins.append({"n_train": sz, "tribe_minus_raw": round(a - b, 4)})
        (out / "headline.json").write_text(json.dumps(wins, indent=2))
        console.print(wins)


if __name__ == "__main__":
    app()
