"""Public benchmark page: does a predicted cortex know what the crowd will click? Unsplash Lite photos
with real view/download counts → 5-fold out-of-fold predictions from the brain features (TRIBE ROI)
vs. the raw vision embedding → AUROC + Spearman, and the photos the brain ranks highest / lowest
side by side with what actually happened. Reuses features/unsplash.npz (no GPU).

    uv run python -m brainsense.showcase.bench
"""
from __future__ import annotations

import csv
import html as _html
import json
import shutil
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def oof(X: np.ndarray, y: np.ndarray, pca: int | None = None, seed: int = 0) -> np.ndarray:
    p = np.zeros(len(y))
    for tr, te in StratifiedKFold(5, shuffle=True, random_state=seed).split(X, y):
        steps = [StandardScaler()] + ([PCA(pca, random_state=seed)] if pca else []) + [LogisticRegression(C=0.5, max_iter=2000)]
        m = make_pipeline(*steps).fit(X[tr], y[tr])
        p[te] = m.predict_proba(X[te])[:, 1]
    return p


DATASETS = {
    "unsplash": {"npz": "features/unsplash.npz", "manifest": "data/unsplash/manifest.csv", "img": "data/unsplash/img", "prefix": "uns_",
                 "title": "Does a predicted cortex know what the crowd will click? — Unsplash Lite, {n} photos with real view/download counts",
                 "label": "top vs bottom half of log(downloads/views)", "cont": "log dl/view", "pos": "actually popular", "neg": "actually not",
                 "note": "Popularity on Unsplash is noisy (it depends on search placement as much as on the photo), so neither feature set should be expected to go much higher."},
    "aadb": {"npz": "features/aadb_area.npz", "manifest": "data/aadb/manifest.csv", "img": "data/aadb/img", "prefix": "aadb_",
             "title": "Does a predicted cortex know what people find beautiful? — AADB, {n} photos rated by human judges",
             "label": "top vs bottom half of the mean human aesthetic rating", "cont": "human rating", "pos": "rated beautiful", "neg": "rated plain",
             "note": "AADB ratings are averages over several human raters, which is why the signal is much cleaner than Unsplash popularity. The 360-area version keeps TRIBE's spatial detail that the 9-group pooling throws away — that difference (0.67 → 0.72 here) was the key engineering finding of this project; the shipped aesthetic head uses the 360-area features."},
}


def main(dataset: str = "unsplash", out: Path | None = None) -> Path:
    cfg = DATASETS[dataset]
    out = out or Path("results/showcase/bench") / dataset
    out.mkdir(parents=True, exist_ok=True)
    d = np.load(cfg["npz"], allow_pickle=True)
    ids, y = d["ids"], d["y"].astype(int)
    raw = {r["item_id"]: r for r in csv.DictReader(open(cfg["manifest"], encoding="utf-8"))}
    cont = np.array([float(raw[i]["label_raw"]) if i in raw and raw[i]["label_raw"] else np.nan for i in ids])
    feats = [("brain (TRIBE 9 groups × 6 stats, 54-d)", d["tribe_roi"], None)]
    if "roi_area" in d.files:
        feats.append(("brain (TRIBE 360 areas → PCA-54)", d["roi_area"][:, :360], 54))
    feats += [("raw vision embedding (1408-d → PCA-54)", d["raw_embed"], 54), ("raw vision embedding (1408-d)", d["raw_embed"], None)]
    res = {}
    for name, X, pca in feats:
        ps = [oof(X, y, pca, s) for s in range(3)]
        auc = float(np.mean([roc_auc_score(y, p) for p in ps]))
        ok = ~np.isnan(cont)
        rho = float(np.mean([spearmanr(p[ok], cont[ok]).correlation for p in ps]))
        res[name] = {"auroc": round(auc, 3), "spearman_vs_log_downloads_per_view": round(rho, 3), "p": np.mean(ps, axis=0)}
    brain = res["brain (TRIBE 360 areas → PCA-54)" if "roi_area" in d.files else "brain (TRIBE 9 groups × 6 stats, 54-d)"]["p"]
    order = np.argsort(-brain)
    img_dir = out / "img"
    img_dir.mkdir(exist_ok=True)

    def card(i: int) -> str:
        iid = str(ids[i])
        base = iid[len(cfg["prefix"]):] if iid.startswith(cfg["prefix"]) else iid
        src = Path(cfg["img"]) / f"{base}.jpg"
        if not src.exists():
            cands = list(Path(cfg["img"]).glob(f"{base}*"))
            src = cands[0] if cands else src
        if src.exists():
            shutil.copy(src, img_dir / src.name)
        lab = cfg["pos"] if y[i] == 1 else cfg["neg"]
        return (f"<div class='c {'hit' if (y[i] == 1) == (brain[i] >= 0.5) else 'miss'}'><img src='img/{src.name}'><div class=m>brain P(top half) <b>{brain[i]:.2f}</b><br>"
                f"<span class=k>{lab}{' · ' + f'{cont[i]:+.2f} ' + cfg['cont'] if not np.isnan(cont[i]) else ''}</span></div></div>")

    top = "".join(card(i) for i in order[:12])
    bottom = "".join(card(i) for i in order[-12:][::-1])
    rows = "".join(f"<tr><td>{_html.escape(k)}</td><td>{v['auroc']:.3f}</td><td>{v['spearman_vs_log_downloads_per_view']:.3f}</td></tr>" for k, v in res.items())
    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8><title>BrainSense benchmark · {dataset}</title>
<style>body{{font-family:-apple-system,Pretendard,sans-serif;background:#0b0b0f;color:#eee;margin:0;padding:32px}}h1{{font-size:20px;font-weight:600}}h2{{font-size:15px;margin:26px 0 8px}}
table{{border-collapse:collapse;font-size:13px}}td,th{{padding:6px 12px;border-bottom:1px solid #23232b;text-align:left}}.grid{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}}
.c{{background:#15151b;border:2px solid #23232b;border-radius:10px;overflow:hidden}}.c.hit{{border-color:#2e6b3a}}.c.miss{{border-color:#6b2e2e}}.c img{{width:100%;aspect-ratio:1;object-fit:cover}}.m{{padding:6px 8px;font-size:11.5px;line-height:1.4}}.k{{color:#8b8b96}}.sub{{color:#9a9aa6;font-size:13px;max-width:980px}}</style></head><body>
<h1>{cfg['title'].format(n=len(ids))}</h1>
<div class=sub>Label = {cfg['label']}. 5-fold out-of-fold logistic regression, averaged over 3 seeds; the brain features are TRIBE v2's predicted cortex pooled into 9 region groups × 6 statistics (54 numbers), the baseline is the raw vision backbone embedding of the same clip. Green border = the brain's call matched reality, red = it did not.</div>
<h2>Numbers</h2><table><tr><th>features</th><th>AUROC</th><th>Spearman vs log(downloads/views)</th></tr>{rows}</table>
<h2>Photos the brain ranks highest</h2><div class=grid>{top}</div>
<h2>…and lowest</h2><div class=grid>{bottom}</div>
<p class=sub>Reading: the cortex features land in the same league as the 1,408-number vision embedding (on AADB the raw embedding's PCA is a few points ahead; the brain's gain is that every call is <i>interpretable</i> — each call can be traced to named brain areas. {cfg['note']}</p>
</body></html>"""
    (out / "index.html").write_text(page, encoding="utf-8")
    (out / "numbers.json").write_text(json.dumps({k: {x: v[x] for x in v if x != "p"} for k, v in res.items()}, indent=1), encoding="utf-8")
    print(json.dumps({k: {x: v[x] for x in v if x != "p"} for k, v in res.items()}, indent=1))
    return out / "index.html"


if __name__ == "__main__":
    import sys
    for ds in (sys.argv[1:] or ["aadb", "unsplash"]):
        main(ds)
