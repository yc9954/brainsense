"""Download + normalize the three head datasets into manifests.

    python -m brainsense.data.prepare aadb      --n 2000     # aesthetic (130 MB, minutes)
    python -m brainsense.data.prepare unsplash  --n 2000     # appeal (views/downloads, 618 MB meta)
    python -m brainsense.data.prepare snapugc   --n 1500     # attention (ECR; CSV on Drive, mp4 on Snap CDN)
    python -m brainsense.data.prepare stills                 # wrap images as 6 s stills for TRIBE

Sources (verified 2026-10-27):
  AADB      github.com/aimerykong/deepImageAestheticsAnalysis  (10K Flickr, mean score + 11 attrs)
  Unsplash  HF 1aurent/unsplash-lite (25K photos, views/downloads, commercial-OK)
  SnapUGC   github.com/dasongli1/SnapUGC_Engagement (90K+ 5-60 s UGC, NAWP/ECR; Drive links)
  TAD66K / AVA / CreativeRanking are larger upgrades once the pipeline runs end-to-end.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pandas as pd
import typer
from rich import print

from .manifest import write_manifest

app = typer.Typer(add_completion=False)
DATA = Path("data")


def _hf_download(repo: str, filename: str | None = None, repo_type: str = "dataset") -> Path:
    from huggingface_hub import hf_hub_download, snapshot_download
    if filename:
        return Path(hf_hub_download(repo, filename, repo_type=repo_type))
    return Path(snapshot_download(repo, repo_type=repo_type))


@app.command()
def aadb(n: int = 2000, split: str = "train"):
    """AADB: labels from the authors' AADBinfo.mat (GitHub, 180 KB), images from the HF mirror
    Iceclear/AADB (AADB.zip, 2.5 GB, Apache-2.0). Score is the mean aesthetic rating in [0, 1]."""
    import zipfile

    import httpx
    from scipy.io import loadmat

    out_dir = DATA / "aadb"; (out_dir / "img").mkdir(parents=True, exist_ok=True)
    mat = out_dir / "AADBinfo.mat"
    if not mat.exists():
        mat.write_bytes(httpx.get("https://raw.githubusercontent.com/aimerykong/deepImageAestheticsAnalysis/master/AADBinfo.mat",
                                  follow_redirects=True, timeout=60).content)
    m = loadmat(mat)
    names = [str(x[0]) for x in m[f"{split}NameList"][0]]
    scores = [float(x) for x in m[f"{split}Score"][0]]
    wanted = dict(list(zip(names, scores))[:n])
    # 2.5 GB; hf_hub_download stalled repeatedly, so use curl with resume (-C -) against the resolve URL.
    zpath = out_dir / "AADB.zip"
    subprocess.run(["curl", "-L", "-C", "-", "--retry", "5", "--retry-all-errors", "-o", str(zpath),
                    "https://huggingface.co/datasets/Iceclear/AADB/resolve/main/AADB.zip"], check=True)
    rows = []
    with zipfile.ZipFile(zpath) as z:
        members = {Path(i.filename).name: i for i in z.infolist() if i.filename.lower().endswith(".jpg")}
        for name, score in wanted.items():
            info = members.get(name)
            if info is None:
                continue
            dst = out_dir / "img" / name
            if not dst.exists():
                dst.write_bytes(z.read(info))
            rows.append({"item_id": f"aadb_{Path(name).stem}", "path": str(dst), "kind": "image",
                         "label": score, "source": "aadb"})
    mf = write_manifest(rows, out_dir / "manifest.csv")
    print(f"[green]wrote {len(mf)} rows -> {out_dir/'manifest.csv'} (matched {len(rows)}/{len(wanted)})")


@app.command()
def unsplash(n: int = 2000, min_views: int = 1000):
    """Unsplash Lite (HF 1aurent/unsplash-lite, 3 parquet shards, images by URL).
    Label = log(downloads/views): downloads per view is 'appeal given exposure'."""
    import httpx
    import numpy as np
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download

    out_dir = DATA / "unsplash"; (out_dir / "img").mkdir(parents=True, exist_ok=True)
    rows = []
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        for shard in range(3):
            if len(rows) >= n:
                break
            p = hf_hub_download("1aurent/unsplash-lite", f"data/train-0000{shard}-of-00003.parquet",
                                repo_type="dataset", cache_dir=str(DATA / "hf_cache"))
            t = pq.read_table(p, columns=["photo", "stats"]).to_pylist()
            for ex in t:
                if len(rows) >= n:
                    break
                ph, st = ex["photo"] or {}, ex["stats"] or {}
                pid, url, views, downloads = ph.get("id"), ph.get("image_url"), st.get("views"), st.get("downloads")
                if not (pid and url and views and downloads) or views < min_views:
                    continue
                dst = out_dir / "img" / f"{pid}.jpg"
                if not dst.exists():
                    r = c.get(f"{url}?w=640&q=80&fm=jpg")
                    if r.status_code != 200:
                        continue
                    dst.write_bytes(r.content)
                rows.append({"item_id": f"uns_{pid}", "path": str(dst), "kind": "image",
                             "label": float(np.log((downloads + 1) / (views + 1))), "source": "unsplash"})
    mf = write_manifest(rows, out_dir / "manifest.csv")
    print(f"[green]wrote {len(mf)} rows -> {out_dir/'manifest.csv'}")


@app.command()
def snapugc(n: int = 1500, seed: int = 0, max_mb: float = 12.0):
    """SnapUGC train set: the Google Drive 'train set' link is a 31 MB CSV
    (Id, Title, Description, Download_link, ECR) with videos hosted on Snap's CDN.
    ~17% of links were still live on 2026-10-28, so we shuffle and keep downloading until n.
    Label = ECR (engagement continuation rate, 0-1), binarized at the median of what we got."""
    import httpx

    out_dir = DATA / "snapugc"; (out_dir / "mp4").mkdir(parents=True, exist_ok=True)
    csv = out_dir / "train.csv"
    if not csv.exists():
        csv.write_bytes(httpx.get("https://drive.google.com/uc?export=download&id=1Mv5Esq5gGuxRTayabRUb5NmHwEN3JdbD",
                                  follow_redirects=True, timeout=120).content)
    df = pd.read_csv(csv).sample(frac=1.0, random_state=seed)
    rows, tried = [], 0
    with httpx.Client(follow_redirects=True, timeout=60) as c:
        for r in df.itertuples():
            if len(rows) >= n:
                break
            dst = out_dir / "mp4" / f"{r.Id}.mp4"
            if not dst.exists():
                tried += 1
                try:
                    resp = c.get(r.Download_link)
                except httpx.HTTPError:
                    continue
                if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("video") \
                        or len(resp.content) > max_mb * 1e6:
                    continue
                dst.write_bytes(resp.content)
            rows.append({"item_id": f"snap_{r.Id}", "path": str(dst), "kind": "video",
                         "label": float(r.ECR), "source": "snapugc"})
            if len(rows) % 50 == 0:
                print(f"  {len(rows)}/{n} (tried {tried})")
    mf = write_manifest(rows, out_dir / "manifest.csv")
    print(f"[green]wrote {len(mf)} rows -> {out_dir/'manifest.csv'} (live rate {len(rows)/max(tried,1):.0%})")


@app.command()
def stills(manifests: list[Path] = typer.Argument(None), seconds: int = 6):
    """TRIBE takes video; wrap each image as a `seconds`-long silent still (ffmpeg).
    Note for the ablation write-up: on stills the temporal module contributes nothing, so any
    brain-bottleneck gain on image heads comes only from the spatial prior."""
    manifests = manifests or [DATA / "aadb" / "manifest.csv", DATA / "unsplash" / "manifest.csv"]
    for mp in manifests:
        if not mp.exists():
            continue
        df = pd.read_csv(mp)
        out_dir = mp.parent / "stills"; out_dir.mkdir(exist_ok=True)
        for i, r in df.iterrows():
            if r["kind"] != "image":
                continue
            dst = out_dir / f"{r['item_id']}.mp4"
            if not dst.exists():
                subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-loop", "1", "-i", r["path"],
                                "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", str(seconds),
                                "-vf", "scale=512:-2,format=yuv420p", "-r", "8", "-c:v", "libx264",
                                "-c:a", "aac", "-shortest", str(dst)], check=False)
            df.loc[i, "path"] = str(dst); df.loc[i, "kind"] = "video"
        df.to_csv(mp, index=False)
        print(f"[green]{mp}: {len(df)} stills -> {out_dir}")


if __name__ == "__main__":
    app()
