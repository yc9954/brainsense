"""Run texts (HC3 manifest) through the Modal TRIBE service as Word events and build the .npz store.

    modal run scripts/extract_text_features.py::extract --manifest data/hc3/manifest.csv --out features/hc3_text.npz

Same output layout as extract_features.py (ids, y, tribe_roi, roi_area, roi_area_names, split) minus
raw_embed, so train_heads.py / ablation work unchanged. Per-item JSON cached under features/cache_text/.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from brainsense.tribe.modal_app import Tribe, app


@app.local_entrypoint()
def extract(manifest: str, out: str, cache_dir: str = "features/cache_text", limit: int = 0, bf16: bool = True):
    df = pd.read_csv(manifest)
    df = df.head(limit) if limit else df
    cache = Path(cache_dir); cache.mkdir(parents=True, exist_ok=True)
    todo = [r for r in df.itertuples() if not (cache / f"{r.item_id}.json").exists()]
    print(f"{len(df)} texts, {len(todo)} to compute")

    def job(r):
        # positional order of Tribe.predict: video_bytes, filename, item_id, with_raw_embed,
        # save_vertices, transcribe, bf16, render_brain, text
        return (b"", "text.txt", r.item_id, False, False, False, bf16, False, str(r.text))

    svc = Tribe()
    for i, res in enumerate(svc.predict.starmap((job(r) for r in todo), order_outputs=False, return_exceptions=True)):
        if isinstance(res, Exception):
            print("ERR", res); continue
        res.pop("vertex_ts", None)
        (cache / f"{res['item_id']}.json").write_text(json.dumps(res))
        if i % 25 == 0:
            print(f"{i}/{len(todo)} last timing={res['timing']}")

    ids, y, roi, split, area = [], [], [], [], []
    area_names: list[str] = []
    for r in df.itertuples():
        p = cache / f"{r.item_id}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        ids.append(r.item_id); y.append(r.label); roi.append(d["roi_feats"]); split.append(r.split)
        area.append(d.get("roi_area_feats") or [])
        area_names = area_names or d.get("roi_area_names") or []
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    np.savez(out, ids=np.array(ids), y=np.array(y, dtype=np.float32), tribe_roi=np.array(roi, dtype=np.float32),
             split=np.array(split),
             roi_area=np.array(area, dtype=np.float32) if area and all(len(a) == len(area[0]) and len(a) for a in area) else np.zeros((len(ids), 0), np.float32),
             roi_area_names=np.array(area_names))
    print(f"wrote {out}: N={len(ids)}")
