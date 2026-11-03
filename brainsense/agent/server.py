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
from .engram import EngramStore
from .service import HEADS_BY_KIND, FeatureCache, build_registry

load_dotenv()  # .env in the project root (never committed)

HEADS_DIR = Path(os.environ.get("BRAINSENSE_HEADS_DIR", "heads"))
PERSONAL_STORE = Path(os.environ.get("BRAINSENSE_PERSONAL_STORE", "state/personal.json"))
TRIBE_URL = os.environ.get("BRAINSENSE_TRIBE_URL", "")

app = FastAPI(title="BrainSense agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])  # web demo (Expo on :8081)
cache = FeatureCache()
roi_ts: dict[str, dict[str, list[float]]] = {}   # item_id -> {group: [T]} for the UI sparklines (mirrored to disk)
_ROI_DIR = cache.store_dir / "roi_ts"
_META: dict[str, dict[str, Any]] = {}   # item_id -> {"kind": image|video|audio|text, "stimulus_text": ...}


def _save_meta(item_id: str, **meta: Any) -> None:
    _META[item_id] = {**_META.get(item_id, {}), **meta}
    _ROI_DIR.mkdir(parents=True, exist_ok=True)
    import json as _json
    (_ROI_DIR / f"{item_id}.meta.json").write_text(_json.dumps(_META[item_id], ensure_ascii=False))


def _load_meta(item_id: str) -> dict[str, Any]:
    if item_id not in _META:
        f = _ROI_DIR / f"{item_id}.meta.json"
        if f.exists():
            import json as _json
            _META[item_id] = _json.loads(f.read_text())
    return _META.get(item_id, {})


def _store_result(item_id: str, res: dict[str, Any], **meta: Any) -> dict[str, Any]:
    """Cache features + time series + frames + vertices for one analyzed item (any stimulus kind)."""
    import json as _json
    cache.put(item_id, np.asarray(res["roi_feats"], dtype=np.float32),
              area=np.asarray(res.get("roi_area_feats") or [], dtype=np.float32))
    roi_ts[item_id] = res.get("roi_ts") or {}
    _ROI_DIR.mkdir(parents=True, exist_ok=True)
    (_ROI_DIR / f"{item_id}.json").write_text(_json.dumps(roi_ts[item_id]))
    if res.get("brain_frames"):
        (_ROI_DIR / f"{item_id}.frames.json").write_text(_json.dumps(res["brain_frames"]))
    if res.get("vertex_ts"):
        (_ROI_DIR / f"{item_id}.vertices.json").write_text(_json.dumps(res["vertex_ts"]))
    _save_meta(item_id, **meta)
    _remember(item_id, meta.get("kind", "image"), np.asarray(res.get("roi_area_feats") or [], dtype=np.float32),
              roi_ts[item_id], meta.get("stimulus_text"))
    return {"item_id": item_id, "timing": res.get("timing"), "roi_ts": roi_ts[item_id],
            "brain_frames": res.get("brain_frames") or [], "vertex_ts": res.get("vertex_ts"), **meta}
if _ROI_DIR.exists():
    import json as _json
    for _f in _ROI_DIR.glob("*.json"):
        roi_ts[_f.stem] = _json.loads(_f.read_text())
registry = build_registry(HEADS_DIR, cache, PERSONAL_STORE)
agents: dict[str, Agent] = {}          # one conversation per session id

# ---- L2 engram store: every percept as a brain state + what happened to it ----------------------
ENGRAMS = EngramStore(os.environ.get("BRAINSENSE_ENGRAM_DB", "state/engrams.sqlite"))


def _pca_key(cortex360: np.ndarray) -> np.ndarray | None:
    """Shared similarity key: the aesthetic head's StandardScaler → PCA-54 (same space every head's
    PCA was fit in). Falls back to None when the head is not a PCA head."""
    try:
        from .service import CROWD_HEADS  # noqa: F401
        from ..heads.head import Head
        global _PCA_HEAD
        if "_PCA_HEAD" not in globals():
            _PCA_HEAD = Head.load(HEADS_DIR / "aesthetic") if (HEADS_DIR / "aesthetic").exists() else None
        h = _PCA_HEAD
        if h is None or not h.cfg.pca_dim:
            return None
        sc = h.model.steps[0][1]; pca = h.model.steps[1][1]
        return pca.transform(sc.transform(np.asarray(cortex360, np.float32)[None, :360]))[0].astype(np.float32)
    except Exception:
        return None


def _remember(item_id: str, kind: str, area: np.ndarray | None, roi: dict[str, list[float]] | None,
              stimulus_ref: str | None = None, owner: str = "local-user") -> None:
    if area is None or len(area) < 360:
        return
    c = np.asarray(area, np.float32)[:360]
    ENGRAMS.upsert(item_id, kind, c, _pca_key(c), owner=owner, stimulus_ref=stimulus_ref, roi_ts=roi)


def _migrate_engrams() -> int:
    """Everything already analyzed in this workspace becomes an engram (idempotent, startup)."""
    n = 0
    for item_id in cache.ids():
        if ENGRAMS.has(item_id):
            continue
        try:
            area = cache.get_area(item_id)
        except KeyError:
            continue
        meta = _load_meta(item_id)
        _remember(item_id, meta.get("kind", "image"), area, roi_ts.get(item_id), meta.get("stimulus_text"))
        n += 1
    # historical 👍/👎 from the personal store become outcomes
    if PERSONAL_STORE.exists():
        import json as _json
        st = _json.loads(PERSONAL_STORE.read_text())
        have = {r["engram_id"] for r in ENGRAMS.db.execute("SELECT engram_id FROM outcomes WHERE kind='liked'").fetchall()} if False else set(
            x[0] for x in ENGRAMS.db.execute("SELECT engram_id FROM outcomes WHERE kind='liked'").fetchall())
        for item_id, y in zip(st.get("ids", []), st.get("y", [])):
            if item_id not in have and ENGRAMS.has(item_id):
                ENGRAMS.add_outcome(item_id, "liked", float(y))
    return n


_migrated = _migrate_engrams()


class AnalyzeIn(BaseModel):
    video_b64: str
    filename: str = "clip.mp4"
    item_id: str
    session: str = "default"
    transcribe: bool = False   # set True only when the clip contains speech
    render_frames: bool = False  # server-rendered PNG frames are only the native fallback; the web card uses vertex_ts (saves ~2 s + 300 KB)


class AnalyzeTextIn(BaseModel):
    text: str
    item_id: str | None = None
    session: str = "default"
    render_frames: bool = False


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


AUDIO_EXT = {"mp3", "wav", "m4a", "aac", "flac", "ogg", "opus"}
IMAGE_EXT = {"jpg", "jpeg", "png", "webp", "heic"}


@app.post("/analyze")
def analyze(inp: AnalyzeIn) -> dict[str, Any]:
    """Photo, clip or audio file → TRIBE. Photos become 6 s stills; audio goes in as an Audio event."""
    ext = inp.filename.lower().rsplit(".", 1)[-1]
    kind = "audio" if ext in AUDIO_EXT else "image" if ext in IMAGE_EXT else "video"
    if kind == "image":
        inp.video_b64, inp.filename = _image_to_still_b64(inp.video_b64), inp.filename.rsplit(".", 1)[0] + ".mp4"
    res = _tribe_call({"video_b64": inp.video_b64, "filename": inp.filename,
                       "item_id": inp.item_id, "with_raw_embed": False,
                       "transcribe": inp.transcribe, "bf16": True, "render_brain": inp.render_frames})
    return _store_result(inp.item_id, res, kind=kind)


@app.post("/analyze_text")
def analyze_text(inp: AnalyzeTextIn) -> dict[str, Any]:
    """Text-only stimulus: TRIBE reads it through its Llama pathway (Word events at reading pace)."""
    import hashlib
    text = inp.text.strip()
    if len(text.split()) < 3:
        raise HTTPException(422, "text too short (need at least 3 words)")
    item_id = inp.item_id or f"txt_{hashlib.sha1(text.encode()).hexdigest()[:16]}"
    if item_id not in cache.ids():
        res = _tribe_call({"text": text, "item_id": item_id, "bf16": True, "render_brain": inp.render_frames})
        out = _store_result(item_id, res, kind="text", stimulus_text=text[:600])
    else:
        out = {"item_id": item_id, "roi_ts": roi_ts.get(item_id, {}), "cached": True, **_load_meta(item_id)}
    return out


@app.post("/agent")
def ask(inp: AskIn) -> dict[str, Any]:
    if inp.item_id not in cache.ids():
        raise HTTPException(404, f"no features for {inp.item_id}; call /analyze first")
    agent = agents.setdefault(inp.session, Agent(registry=registry))
    return {"item_id": inp.item_id, "text": agent.ask(inp.item_id, inp.text)}


@app.post("/agent/feedback")
def feedback(inp: FeedbackIn) -> dict[str, Any]:
    out = registry.call("record_feedback", item_id=inp.item_id, liked=inp.liked)
    if ENGRAMS.has(inp.item_id):
        ENGRAMS.add_outcome(inp.item_id, "liked", 1.0 if inp.liked else 0.0)
    out["engram_outcomes"] = ENGRAMS.count()["outcomes"]
    return out


class OutcomeIn(BaseModel):
    item_id: str
    kind: str = "liked"          # liked | chosen_over | rejected | dwell_s | sold | replies
    value: float = 1.0
    against: str | None = None


@app.post("/outcome")
def outcome(inp: OutcomeIn) -> dict[str, Any]:
    """Any real-world consequence of a percept, not only 👍/👎 (chosen_over B, sold, replies...)."""
    if not ENGRAMS.has(inp.item_id):
        raise HTTPException(404, f"no engram for {inp.item_id}")
    oid = ENGRAMS.add_outcome(inp.item_id, inp.kind, inp.value, inp.against)
    if inp.kind in ("liked", "chosen_over", "rejected") and inp.item_id in cache.ids():
        registry.call("record_feedback", item_id=inp.item_id, liked=bool(inp.value if inp.kind == "liked" else inp.kind == "chosen_over"))
    return {"stored": oid, **ENGRAMS.count()}


@app.get("/recall/{item_id}")
def recall(item_id: str, k: int = 5, kinds: str | None = None, with_outcomes: bool = False) -> dict[str, Any]:
    """Nearest engrams in cortex space: what did this brain see before that felt like this?"""
    e = ENGRAMS.get(item_id)
    if e is None:
        raise HTTPException(404, f"no engram for {item_id}")
    key = e["pca"] if e["pca"] is not None else e["cortex"]
    hits = ENGRAMS.recall(key, k=k, exclude=item_id, kinds=[x for x in (kinds or "").split(",") if x] or None,
                          with_outcomes_only=with_outcomes)
    return {"item_id": item_id, "kind": e["kind"],
            "recalled": [{"item_id": h.id, "kind": h.kind, "similarity": round(h.similarity, 3), "stimulus_ref": h.stimulus_ref,
                          "note": h.note, "outcomes": h.outcomes,
                          "age_days": round((__import__("time").time() - h.created_at) / 86400, 1)} for h in hits],
            "memory": ENGRAMS.count()}


@app.post("/sleep")
def sleep_now(owner: str = "local-user") -> dict[str, Any]:
    """L3 consolidation: surprise-weighted personal refit, rule mining, USER_TASTE.md, AUROC report."""
    from .sleep import sleep as _sleep
    personal = getattr(registry, "_personal", None)
    return _sleep(ENGRAMS, personal, owner=owner)


@app.get("/rules")
def rules(owner: str = "local-user") -> dict[str, Any]:
    return {"owner": owner, "rules": ENGRAMS.rules(owner), "memory": ENGRAMS.count(owner),
            "consolidations": ENGRAMS.consolidations(owner)[-3:]}


class NoteIn(BaseModel):
    item_id: str
    note: str


@app.post("/note")
def note(inp: NoteIn) -> dict[str, Any]:
    """The one sentence the voice said about a percept, kept with the engram for later recall."""
    if not ENGRAMS.has(inp.item_id):
        raise HTTPException(404, f"no engram for {inp.item_id}")
    ENGRAMS.set_note(inp.item_id, inp.note)
    return {"ok": True}


def text_critique(series: dict[str, list[float]], heads: dict[str, Any]) -> dict[str, Any]:
    """Expert reading of the cortex pattern for a piece of writing (kind=text): which networks the
    text engages while being read, and what a writer would change. Relative within the item (z-scored
    group means), so it says what is quiet *for this text*, not absolute truth."""
    if not series:
        return {}
    means = {g: float(np.mean(v)) for g, v in series.items() if v}
    if len(means) < 4:
        return {}
    vals = np.array(list(means.values()))
    mu, sd = vals.mean(), vals.std() or 1.0
    rel = {g: (m - mu) / sd for g, m in means.items()}
    lo = lambda g: rel.get(g, 0.0) < -0.6
    hi = lambda g: rel.get(g, 0.0) > 0.6
    diag: list[str] = []
    todo: list[str] = []
    if lo("value_vmpfc"):
        diag.append("보상·가치 회로가 조용함: 읽는 사람에게 이 글이 왜 중요한지, 어떤 감정을 건드리는지가 없음")
        todo.append("첫 두 문장 안에 독자의 이해관계나 감정을 하나 박아라 (잃는 것, 바라는 것, 놀라운 것)")
    if lo("face_body") and lo("scene_place"):
        diag.append("사람·장면 영역이 둘 다 꺼져 있음: 구체적인 인물·장소·감각이 없는 추상적인 글")
        todo.append("실명이든 가명이든 한 사람, 한 장소, 한 감각(냄새·소리·촉감)을 넣어라")
    elif lo("face_body"):
        diag.append("사람 영역이 조용함: 글에 사람이 등장하지 않음")
        todo.append("누가 겪은 일인지 한 사람을 등장시켜라")
    elif lo("scene_place"):
        diag.append("장면 영역이 조용함: 어디서 벌어지는 일인지 그림이 안 그려짐")
        todo.append("장소나 상황을 한 줄로 그려라")
    if lo("default_mode"):
        diag.append("이야기·상상 네트워크(디폴트 모드)가 조용함: 설명은 되는데 이야기가 없음")
        todo.append("시간 순서가 있는 작은 에피소드 하나로 바꿔라 (그때 → 그래서 → 결국)")
    if hi("language") and all(lo(g) for g in ("value_vmpfc", "default_mode")):
        diag.append("언어 영역만 균일하게 높음: 문장은 매끈한데 아무 데도 닿지 않는 기계적 문체의 전형")
        todo.append("접속사·나열·'또한/뿐만 아니라'류를 걷어내고 문장 길이를 들쭉날쭉하게 만들어라")
    if hi("control_dlpfc") or hi("attention_dorsal"):
        diag.append("집중·통제 영역이 높음: 읽는 데 힘이 드는 문장(길이, 밀도, 전문용어)")
        todo.append("긴 문장을 둘로 쪼개고 전문용어 하나당 비유 하나를 붙여라")
    if hi("default_mode") and hi("value_vmpfc"):
        diag.append("이야기 몰입과 보상 반응이 함께 높음: 사람이 쓴 글의 전형적 패턴")
    ranked = sorted(rel.items(), key=lambda kv: -kv[1])
    out = {"kind": "text", "ranking": [g for g, _ in ranked], "relative_z": {g: round(v, 2) for g, v in rel.items()},
           "diagnosis": diag[:4], "directives": todo[:3]}
    h = heads.get("humanlike") if isinstance(heads, dict) else None
    if isinstance(h, dict) and isinstance(h.get("percentile"), (int, float)):
        out["humanlike_percentile"] = h["percentile"]
    return out


@app.get("/eval/{item_id}")
def eval_item(item_id: str, heads: str | None = None) -> dict[str, Any]:
    """Head outputs for an analyzed item (what the BrainCard renders). `heads` = comma list to
    restrict; default = the heads that make sense for the item's stimulus kind."""
    if item_id not in cache.ids():
        raise HTTPException(404, f"no features for {item_id}")
    meta = _load_meta(item_id)
    kind = meta.get("kind", "image")
    wanted = [h.strip() for h in heads.split(",") if h.strip()] if heads else list(HEADS_BY_KIND.get(kind, HEADS_BY_KIND["image"]))
    out = registry.call("brain_eval", item_id=item_id, heads=wanted)
    out["kind"] = kind
    if meta.get("stimulus_text"):
        out["stimulus_text"] = meta["stimulus_text"]
    out["roi_ts"] = roi_ts.get(item_id, {})
    if kind == "text":
        out["critique"] = text_critique(out["roi_ts"], out.get("heads", {}))
    import json as _json
    f = _ROI_DIR / f"{item_id}.frames.json"
    if f.exists():
        out["brain_frames"] = _json.loads(f.read_text())
    f = _ROI_DIR / f"{item_id}.vertices.json"
    if f.exists():
        out["vertex_ts"] = _json.loads(f.read_text())
    return out


@app.get("/compare")
def compare_items(item_id: str, against: str) -> dict[str, Any]:
    """Head scores for one item vs others (e.g. two music hooks): `against` = comma-separated ids."""
    others = [a.strip() for a in against.split(",") if a.strip()]
    for i in [item_id, *others]:
        if i not in cache.ids():
            raise HTTPException(404, f"no features for {i}")
    out = registry.call("compare", item_id=item_id, against=others)
    # 1 Hz region series side by side so the agent can point at the hook moment
    out["roi_ts"] = {i: roi_ts.get(i, {}) for i in [item_id, *others]}
    return out


_ASSETS = Path(__file__).resolve().parents[2] / "assets"


@app.get("/assets/{name}")
def asset(name: str):
    """Static assets for the app (fsaverage5 pial mesh for the live 3D cortex)."""
    from fastapi.responses import FileResponse
    p = _ASSETS / Path(name).name
    if not p.exists():
        raise HTTPException(404, name)
    return FileResponse(p, media_type="application/octet-stream",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/items")
def items() -> dict[str, Any]:
    return {"items": cache.ids()}


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "memory": ENGRAMS.count(), "heads": sorted(p.name for p in HEADS_DIR.glob("*") if (p / "head.joblib").exists()),
            "cached_items": len(cache.ids())}
