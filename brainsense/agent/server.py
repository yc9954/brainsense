"""HTTP front door for the phone app. One process holds the heads, the feature cache and the agent.

    BRAINSENSE_TRIBE_URL=https://...modal.run uv run uvicorn brainsense.agent.server:app --port 8000

POST /analyze           {"video_b64", "filename", "item_id"}  -> forwards to the Modal TRIBE endpoint,
                                                               caches roi_feats, returns timing + roi_ts
POST /agent             {"item_id", "text"}                   -> agent reply (Korean, 2-3 sentences)
POST /agent/feedback    {"item_id", "liked"}                  -> personal head update
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .loop import Agent
from .service import FeatureCache, build_registry

load_dotenv()  # .env in the project root (never committed)

HEADS_DIR = Path(os.environ.get("BRAINSENSE_HEADS_DIR", "heads"))
PERSONAL_STORE = Path(os.environ.get("BRAINSENSE_PERSONAL_STORE", "state/personal.json"))
TRIBE_URL = os.environ.get("BRAINSENSE_TRIBE_URL", "")

app = FastAPI(title="BrainSense agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])  # web demo (Expo on :8081)
cache = FeatureCache()
roi_ts: dict[str, dict[str, list[float]]] = {}   # item_id -> {group: [T]} for the UI sparklines (mirrored to disk)
_ROI_DIR = cache.store_dir / "roi_ts"
if _ROI_DIR.exists():
    import json as _json
    for _f in _ROI_DIR.glob("*.json"):
        roi_ts[_f.stem] = _json.loads(_f.read_text())
registry = build_registry(HEADS_DIR, cache, PERSONAL_STORE)
agents: dict[str, Agent] = {}          # one conversation per session id


class AnalyzeIn(BaseModel):
    video_b64: str
    filename: str = "clip.mp4"
    item_id: str
    session: str = "default"
    transcribe: bool = False   # set True only when the clip contains speech


class AskIn(BaseModel):
    item_id: str
    text: str
    session: str = "default"


class FeedbackIn(BaseModel):
    item_id: str
    liked: bool


def _tribe_call(payload: dict[str, Any]) -> dict[str, Any]:
    """Separated so tests can monkeypatch it."""
    if not TRIBE_URL:
        raise HTTPException(503, "BRAINSENSE_TRIBE_URL not set")
    # Modal web endpoints answer 303 + an attempt token when a call exceeds ~150 s (e.g. waiting
    # for a GPU slot); following the redirect polls the result, so allow it and wait generously.
    r = httpx.post(TRIBE_URL, json=payload, timeout=httpx.Timeout(900, connect=30), follow_redirects=True)
    r.raise_for_status()
    return r.json()


def _image_to_still_b64(image_b64: str, seconds: int = 6) -> str:
    """Photos (jpg/png/webp) become a silent 6 s clip, exactly like the training stills."""
    import base64
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "img"
        src.write_bytes(base64.b64decode(image_b64))
        dst = Path(d) / "still.mp4"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-loop", "1", "-i", str(src),
                        "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", str(seconds),
                        "-vf", "scale=512:-2,format=yuv420p", "-r", "8", "-c:v", "libx264",
                        "-c:a", "aac", "-shortest", str(dst)], check=True)
        return base64.b64encode(dst.read_bytes()).decode()


@app.post("/analyze")
def analyze(inp: AnalyzeIn) -> dict[str, Any]:
    if inp.filename.lower().rsplit(".", 1)[-1] in {"jpg", "jpeg", "png", "webp", "heic"}:
        inp.video_b64, inp.filename = _image_to_still_b64(inp.video_b64), inp.filename.rsplit(".", 1)[0] + ".mp4"
    res = _tribe_call({"video_b64": inp.video_b64, "filename": inp.filename,
                       "item_id": inp.item_id, "with_raw_embed": False,
                       "transcribe": inp.transcribe, "bf16": True})
    cache.put(inp.item_id, np.asarray(res["roi_feats"], dtype=np.float32))
    roi_ts[inp.item_id] = res.get("roi_ts") or {}
    _ROI_DIR.mkdir(parents=True, exist_ok=True)
    import json as _json
    (_ROI_DIR / f"{inp.item_id}.json").write_text(_json.dumps(roi_ts[inp.item_id]))
    return {"item_id": inp.item_id, "timing": res.get("timing"), "roi_ts": roi_ts[inp.item_id]}


@app.post("/agent")
def ask(inp: AskIn) -> dict[str, Any]:
    if inp.item_id not in cache.ids():
        raise HTTPException(404, f"no features for {inp.item_id}; call /analyze first")
    agent = agents.setdefault(inp.session, Agent(registry=registry))
    return {"item_id": inp.item_id, "text": agent.ask(inp.item_id, inp.text)}


@app.post("/agent/feedback")
def feedback(inp: FeedbackIn) -> dict[str, Any]:
    return registry.call("record_feedback", item_id=inp.item_id, liked=inp.liked)


@app.get("/eval/{item_id}")
def eval_item(item_id: str) -> dict[str, Any]:
    """Head outputs for an analyzed item (what the BrainCard renders)."""
    if item_id not in cache.ids():
        raise HTTPException(404, f"no features for {item_id}")
    out = registry.call("brain_eval", item_id=item_id)
    out["roi_ts"] = roi_ts.get(item_id, {})
    return out


@app.get("/items")
def items() -> dict[str, Any]:
    return {"items": cache.ids()}


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "heads": sorted(p.name for p in HEADS_DIR.glob("*") if (p / "head.joblib").exists()),
            "cached_items": len(cache.ids())}
