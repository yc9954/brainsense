"""Run every manifest item through the Modal TRIBE service and build the .npz feature store.

    modal run scripts/extract_features.py::extract --manifest data/aadb/manifest.csv --out features/aadb.npz

Caches per-item JSON under features/cache/<item_id>.json so re-runs are free. Produces
    ids, y, tribe_roi (N,54), raw_embed (N,1408), split
which is exactly what brainsense.heads.ablation expects."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from brainsense.tribe.modal_app import Tribe, app


@app.local_entrypoint()
def extract(manifest: str, out: str, with_raw: bool = True, transcribe: bool = True, bf16: bool = True):
    """--no-transcribe for stills/product shots (3x faster, identical features); keep it for UGC with speech."""
    df = pd.read_csv(manifest)
    cache = Path("features/cache"); cache.mkdir(parents=True, exist_ok=True)
    todo = [r for r in df.itertuples() if not (cache / f"{r.item_id}.json").exists()]
    print(f"{len(df)} items, {len(todo)} to compute")

    def job(r):
        # positional order must match Tribe.predict(video_bytes, filename, item_id, with_raw_embed)
        return (Path(r.path).read_bytes(), Path(r.path).name, r.item_id, with_raw)

    svc = Tribe()
    for i, res in enumerate(svc.predict.starmap((job(r) for r in todo),
                                            kwargs={"save_vertices": False, "transcribe": transcribe, "bf16": bf16}, order_outputs=False,
                                            return_exceptions=True)):
        if isinstance(res, Exception):
            print("ERR", res); continue
        (cache / f"{res['item_id']}.json").write_text(json.dumps(res))
        if i % 25 == 0:
            print(f"{i}/{len(todo)} last timing={res['timing']}")

    ids, y, roi, raw, split = [], [], [], [], []
    for r in df.itertuples():
        p = cache / f"{r.item_id}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        if not isinstance(d.get("raw_embed"), list):
            continue
        ids.append(r.item_id); y.append(r.label); roi.append(d["roi_feats"]); raw.append(d["raw_embed"]); split.append(r.split)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    np.savez(out, ids=np.array(ids), y=np.array(y, dtype=np.float32), tribe_roi=np.array(roi, dtype=np.float32),
             raw_embed=np.array(raw, dtype=np.float32), split=np.array(split))
    print(f"wrote {out}: N={len(ids)}")
