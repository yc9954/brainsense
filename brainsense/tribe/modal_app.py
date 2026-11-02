"""TRIBE v2 inference service on Modal + a latency benchmark.

Deploy / run:
    modal secret create huggingface HF_TOKEN=hf_...        # Llama-3.2-3B is gated
    modal run  brainsense/tribe/modal_app.py --video sample.mp4   # one-off benchmark
    modal deploy brainsense/tribe/modal_app.py                    # persistent endpoint

Returns, per clip:
    roi_feats   : 54-d pooled ROI-group features (what the heads consume)
    roi_ts      : {group: [T]} 1 Hz time series (what the agent cites: "drops after 2 s")
    raw_embed   : 1408-d mean-pooled V-JEPA2 embedding (ablation baseline, same backbone)
    timing      : seconds per stage
Vertex-level predictions (T x 20484 float32) are written to the Volume, not returned.

Facts baked in from the repo: output (T, 20484) fsaverage5 at 1 Hz, average subject, z-scored,
5 s hemodynamic shift already applied; backbones V-JEPA2 ViT-g, w2v-BERT 2.0, Llama-3.2-3B;
python>=3.11, torch>=2.5.1,<2.7; ffmpeg needed; ~15 GB of weights on first run.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import modal

GPU = os.environ.get("BRAINSENSE_GPU", "L40S")          # 48 GB; A10G (24 GB) reported to work with bf16
CACHE = "/cache"                                         # Modal Volume: HF weights, TRIBE ckpt, atlases
vol = modal.Volume.from_name("brainsense-cache", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "git", "libsndfile1")
    .pip_install("torch==2.6.0", "torchvision==0.21.0", "torchaudio==2.6.0",
                 index_url="https://download.pytorch.org/whl/cu124")
    .pip_install("tribev2[plotting] @ git+https://github.com/facebookresearch/tribev2.git",
                 "mne>=1.8", "nibabel", "nilearn", "einops", "fastapi[standard]", "av>=12")
    .run_commands("python -m spacy download en_core_web_sm || true")
    .env({"HF_HOME": f"{CACHE}/hf", "SUBJECTS_DIR": f"{CACHE}/subjects",
          "MNE_DATASETS_SAMPLE_PATH": f"{CACHE}/mne_data",   # tribev2 atlas helper pulls MNE sample data
          "TOKENIZERS_PARALLELISM": "false"})
    .add_local_python_source("brainsense")
)

app = modal.App("brainsense-tribe", image=image)


def _hf_secret() -> modal.Secret:
    """Use the `huggingface` secret if it exists; otherwise run without (image build + non-gated
    backbones still work, Llama-3.2-3B download will fail until the secret is created)."""
    try:
        s = modal.Secret.from_name("huggingface")
        s.hydrate()
        return s
    except Exception:
        print("[tribe] WARNING: no `huggingface` secret; create it with: "
              "modal secret create huggingface HF_TOKEN=hf_...")
        return modal.Secret.from_dict({})


# BRAINSENSE_WARM=1 keeps one GPU container resident (no 70 s cold start, ~$2/h on L40S): set it
# before `modal deploy` for a demo window, unset and redeploy afterwards.
WARM = int(os.environ.get("BRAINSENSE_WARM", "0"))


@app.cls(gpu=GPU, volumes={CACHE: vol}, secrets=[_hf_secret()],
         timeout=900, scaledown_window=300, max_containers=8, min_containers=WARM)
class Tribe:
    @modal.enter()
    def load(self) -> None:
        import torch
        from tribev2 import TribeModel

        from brainsense.tribe.rois import resolve_group_vertices

        t0 = time.time()
        Path(f"{CACHE}/subjects").mkdir(parents=True, exist_ok=True)
        self.model = TribeModel.from_pretrained("facebook/tribev2", cache_folder=f"{CACHE}/tribe")
        self.groups = resolve_group_vertices(subjects_dir=f"{CACHE}/subjects")
        from brainsense.tribe.rois import resolve_area_vertices
        self.areas = resolve_area_vertices(subjects_dir=f"{CACHE}/subjects")
        self.vjepa = None  # lazy; only needed for the ablation baseline
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        vol.commit()
        self.load_s = time.time() - t0
        print(f"[tribe] loaded in {self.load_s:.1f}s on {self.device}; "
              f"groups={{{', '.join(f'{k}:{len(v)}' for k, v in self.groups.items())}}}")

    def _raw_embed(self, video_path: str) -> list[float]:
        """Mean-pooled V-JEPA2 ViT-g features (same backbone TRIBE uses) — the no-brain baseline."""
        import av
        import numpy as np
        import torch
        from transformers import AutoModel, AutoVideoProcessor

        if self.vjepa is None:
            hf_id = "facebook/vjepa2-vitg-fpc64-256"
            self.vjepa_proc = AutoVideoProcessor.from_pretrained(hf_id)
            self.vjepa = AutoModel.from_pretrained(hf_id, torch_dtype=torch.bfloat16).to(self.device).eval()
        container = av.open(video_path)
        frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
        idx = [int(i) for i in np.linspace(0, len(frames) - 1, num=min(64, max(len(frames), 1)))]
        clip = [frames[i] for i in idx]
        inputs = self.vjepa_proc(clip, return_tensors="pt").to(self.device)
        with torch.inference_mode():
            out = self.vjepa(**{k: (v.to(torch.bfloat16) if v.is_floating_point() else v) for k, v in inputs.items()})
        return out.last_hidden_state.float().mean(dim=1)[0].cpu().tolist()

    @modal.method()
    def predict(self, video_bytes: bytes, filename: str = "clip.mp4", item_id: str | None = None,
                with_raw_embed: bool = True, save_vertices: bool = True,
                transcribe: bool = True, bf16: bool = False) -> dict:
        """transcribe=False skips WhisperX + spaCy + Llama (use for clips with no speech: product
        shots, stills). bf16=True wraps the whole predict pass in torch.autocast(bfloat16)."""
        import contextlib
        import hashlib

        import numpy as np
        import pandas as pd
        import torch

        from brainsense.tribe.rois import area_features, pool_features, roi_timeseries

        timing: dict[str, float] = {}
        work = Path("/tmp/work"); work.mkdir(exist_ok=True)
        # neuralset caches extracted features by file path: two different uploads named "clip.mp4"
        # would silently share features. Key the on-disk name by content hash instead.
        digest = hashlib.sha1(video_bytes).hexdigest()[:16]
        path = work / f"{digest}_{Path(filename).name}"
        path.write_bytes(video_bytes)

        t = time.time()
        if transcribe:
            events = self.model.get_events_dataframe(video_path=str(path))   # ffmpeg + whisperx + spacy
        else:
            from tribev2.demo_utils import get_audio_and_text_events
            ev = pd.DataFrame([{"type": "Video", "filepath": str(path), "start": 0,
                                "timeline": "default", "subject": "default"}])
            events = get_audio_and_text_events(ev, audio_only=True)       # ffmpeg only
        timing["events_s"] = time.time() - t

        t = time.time()
        if bf16 and not getattr(self, "_fp32_out_wrapped", False):
            # under autocast the fusion model returns bf16, and tribev2 calls .numpy() on it
            inner = self.model._model
            orig_forward = inner.forward
            inner.forward = lambda *a, **k: orig_forward(*a, **k).float()
            self._fp32_out_wrapped = True
        ctx = torch.autocast("cuda", dtype=torch.bfloat16) if bf16 else contextlib.nullcontext()
        with ctx:
            preds, _segments = self.model.predict(events=events, verbose=False)  # (T, 20484)
        timing["predict_s"] = time.time() - t
        preds = np.asarray(preds, dtype=np.float32)

        t = time.time()
        ts = roi_timeseries(preds, self.groups)
        feats, names = pool_features(ts)
        area_feats, area_names = area_features(preds, self.areas)
        timing["roi_s"] = time.time() - t

        raw = None
        if with_raw_embed:
            t = time.time()
            try:
                raw = self._raw_embed(str(path))
            except Exception as e:  # baseline is optional; never fail the main path
                raw = {"error": f"{type(e).__name__}: {e}"}
            timing["raw_embed_s"] = time.time() - t

        if save_vertices and item_id:
            out_dir = Path(f"{CACHE}/preds"); out_dir.mkdir(exist_ok=True)
            np.save(out_dir / f"{item_id}.npy", preds)
            vol.commit()

        timing["total_s"] = sum(v for k, v in timing.items() if k != "total_s")
        return {"item_id": item_id, "n_timesteps": int(preds.shape[0]), "n_vertices": int(preds.shape[1]),
                "roi_feats": feats.tolist(), "roi_feat_names": names,
                "roi_area_feats": area_feats.tolist(), "roi_area_names": area_names,
                "roi_ts": {g: [round(float(v), 4) for v in x] for g, x in ts.items()},
                "raw_embed": raw, "timing": {k: round(v, 2) for k, v in timing.items()},
                "load_s": round(self.load_s, 1)}

    @modal.fastapi_endpoint(method="POST", docs=True)
    def http(self, body: dict) -> dict:
        """JSON: {"video_b64": ..., "filename": "x.mp4", "item_id": "..."} — for the phone app.
        Live defaults: no transcription (product shots have no speech) + bf16 (14 s per fresh 6 s clip)."""
        import base64
        return self.predict.local(base64.b64decode(body["video_b64"]), body.get("filename", "clip.mp4"),
                                  body.get("item_id"), body.get("with_raw_embed", False),
                                  transcribe=body.get("transcribe", False), bf16=body.get("bf16", True))


@app.local_entrypoint()
def main(video: str = "", repeats: int = 2, item_id: str = "bench"):
    """Latency benchmark: first call includes container cold start; later calls are warm."""
    import json
    if not video:
        raise SystemExit("pass --video path/to/clip.mp4 (5-15 s clip recommended)")
    data = Path(video).read_bytes()
    print(f"clip: {video} ({len(data)/1e6:.1f} MB), gpu={GPU}")
    rows = []
    for i in range(repeats):
        t = time.time()
        r = Tribe().predict.remote(data, Path(video).name, item_id=f"{item_id}_{i}")
        wall = time.time() - t
        rows.append({"call": i, "wall_s": round(wall, 1), **r["timing"], "T": r["n_timesteps"]})
        print(json.dumps(rows[-1]))
        raw = r.get("raw_embed")
        print("raw_embed:", f"vector[{len(raw)}]" if isinstance(raw, list) else raw)
        if i == 0:
            print("roi_feats[:6]:", [round(v, 3) for v in r["roi_feats"][:6]], "names:", r["roi_feat_names"][:6])
    out = Path("results"); out.mkdir(exist_ok=True)
    (out / "latency.json").write_text(json.dumps({"gpu": GPU, "runs": rows}, indent=2))
    print("wrote results/latency.json")


@app.function(volumes={CACHE: vol}, timeout=3600, cpu=4)
def prefetch_weights() -> dict:
    """Download the non-gated weights into the Volume ahead of time (no HF token needed):
    TRIBE ckpt (0.7 GB), V-JEPA2 ViT-g (~4 GB), w2v-BERT 2.0 (~2.3 GB). Llama-3.2-3B is gated and
    is fetched on first model load once the `huggingface` secret holds a real token."""
    import os

    from huggingface_hub import snapshot_download

    os.environ.pop("HF_TOKEN", None)  # make sure a bogus/placeholder token never gets sent
    out = {}
    # Atlases, fetched ONCE here so 8 GPU containers never race on the Volume:
    # fsaverage surfaces + HCP-MMP1 annot into SUBJECTS_DIR, and MNE's sample dataset
    # (tribev2's HCP helper resolves fsaverage through it).
    import mne
    subjects_dir = f"{CACHE}/subjects"
    Path(subjects_dir).mkdir(parents=True, exist_ok=True)
    t = time.time()
    mne.datasets.fetch_fsaverage(subjects_dir=subjects_dir, verbose=False)
    mne.datasets.fetch_hcp_mmp_parcellation(subjects_dir=subjects_dir, accept=True, verbose=False)
    mne.datasets.sample.data_path(path=f"{CACHE}/mne_data", verbose=False)
    out["atlases"] = {"subjects_dir": subjects_dir, "seconds": round(time.time() - t, 1),
                      "lh_white": Path(f"{subjects_dir}/fsaverage/surf/lh.white").exists()}
    print(f"[prefetch] atlases -> {out['atlases']}")
    for repo in ("facebook/tribev2", "facebook/vjepa2-vitg-fpc64-256", "facebook/w2v-bert-2.0"):
        t = time.time()
        path = snapshot_download(repo, cache_dir=f"{CACHE}/hf/hub", token=False)
        out[repo] = {"path": path, "seconds": round(time.time() - t, 1)}
        print(f"[prefetch] {repo} -> {path} in {out[repo]['seconds']}s")
    vol.commit()
    return out


@app.local_entrypoint()
def prefetch():
    import json
    print(json.dumps(prefetch_weights.remote(), indent=2))


@app.local_entrypoint()
def profile(only: str = "", clips: str = ""):
    """Latency variants on fresh clips (neuralset caches per file *content* on the Volume, so every
    variant needs a never-seen clip): full / no transcription / no transcription + bf16 / 4 s clip.
    --only no_tr_bf16,4s_no_tr_bf16 --clips samples/a.mp4,samples/b.mp4 reruns a subset on new clips."""
    import json
    variants = [
        ("full",            "samples/clip6s_1.mp4", dict(transcribe=True,  bf16=False)),
        ("no_transcribe",   "samples/clip6s_2.mp4", dict(transcribe=False, bf16=False)),
        ("no_tr_bf16",      "samples/clip6s_3.mp4", dict(transcribe=False, bf16=True)),
        ("4s_no_tr_bf16",   "samples/clip4s_silent.mp4", dict(transcribe=False, bf16=True)),
    ]
    if only:
        wanted = only.split(",")
        variants = [v for v in variants if v[0] in wanted]
        if clips:
            variants = [(n, c, kw) for (n, _, kw), c in zip(variants, clips.split(","))]
    svc = Tribe()
    rows = []
    for name, clip, kw in variants:
        data = Path(clip).read_bytes()
        t = time.time()
        try:
            r = svc.predict.remote(data, Path(clip).name, item_id=f"profile_{name}", with_raw_embed=True,
                                   save_vertices=False, **kw)
            row = {"variant": name, "wall_s": round(time.time() - t, 1), **r["timing"], "T": r["n_timesteps"],
                   "roi_feats_head": [round(v, 3) for v in r["roi_feats"][:3]]}
        except Exception as e:  # keep going so the other variants still report
            row = {"variant": name, "error": f"{type(e).__name__}: {str(e)[:200]}"}
        rows.append(row)
        print(json.dumps(row))
    Path("results").mkdir(exist_ok=True)
    Path("results/profile.json").write_text(json.dumps({"gpu": GPU, "runs": rows}, indent=2))
    print("wrote results/profile.json")
