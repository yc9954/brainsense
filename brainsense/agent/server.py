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
from pydantic import BaseModel

from .loop import Agent
from .service import FeatureCache, build_registry

load_dotenv()  # .env in the project root (never committed)

HEADS_DIR = Path(os.environ.get("BRAINSENSE_HEADS_DIR", "heads"))
PERSONAL_STORE = Path(os.environ.get("BRAINSENSE_PERSONAL_STORE", "state/personal.json"))
TRIBE_URL = os.environ.get("BRAINSENSE_TRIBE_URL", "")

app = FastAPI(title="BrainSense agent")
cache = FeatureCache()
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
    r = httpx.post(TRIBE_URL, json=payload, timeout=300)
    r.raise_for_status()
    return r.json()


@app.post("/analyze")
def analyze(inp: AnalyzeIn) -> dict[str, Any]:
    res = _tribe_call({"video_b64": inp.video_b64, "filename": inp.filename,
                       "item_id": inp.item_id, "with_raw_embed": False,
                       "transcribe": inp.transcribe, "bf16": True})
    cache.put(inp.item_id, np.asarray(res["roi_feats"], dtype=np.float32))
    return {"item_id": inp.item_id, "timing": res.get("timing"), "roi_ts": res.get("roi_ts")}


@app.post("/agent")
def ask(inp: AskIn) -> dict[str, Any]:
    if inp.item_id not in cache.ids():
        raise HTTPException(404, f"no features for {inp.item_id}; call /analyze first")
    agent = agents.setdefault(inp.session, Agent(registry=registry))
    return {"item_id": inp.item_id, "text": agent.ask(inp.item_id, inp.text)}


@app.post("/agent/feedback")
def feedback(inp: FeedbackIn) -> dict[str, Any]:
    return registry.call("record_feedback", item_id=inp.item_id, liked=inp.liked)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "heads": sorted(p.name for p in HEADS_DIR.glob("*") if (p / "head.joblib").exists()),
            "cached_items": len(cache.ids())}
