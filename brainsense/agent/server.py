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
from .home import Home
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
HOME = Home()   # SOUL.md / MEMORY.md / USER.md / skills — the inspectable half of the agent


def _after_sleep(report: dict[str, Any], owner: str) -> None:
    """Mirror the mined rules into USER.md's taste section (the prompt reads it from there)."""
    rules_ = ENGRAMS.rules(owner)
    line = ""
    if report.get("loo_auroc") is not None or report.get("auroc_after") is not None:
        line = (f"_{report.get('n_labeled', 0)} labeled brain states · personal head leave-one-out AUROC "
                f"{report.get('loo_auroc')} vs crowd {report.get('crowd_loo_auroc')}_")
    HOME.set_taste_section(rules_, line)


class _AutoSleep:
    """Hermes-style cron, minimal: consolidate after every N new outcomes, checked in the background."""
    EVERY = int(os.environ.get("BRAINSENSE_SLEEP_EVERY", "10"))

    def __init__(self) -> None:
        import threading
        self.lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        import time as _t
        while True:
            _t.sleep(120)
            try:
                pending = ENGRAMS.db.execute("SELECT COUNT(*) FROM outcomes WHERE consolidated=0").fetchone()[0]
                if pending >= self.EVERY and self.lock.acquire(blocking=False):
                    try:
                        from .sleep import sleep as _sleep
                        rep = _sleep(ENGRAMS, getattr(registry, "_personal", None))
                        _after_sleep(rep, "local-user")
                    finally:
                        self.lock.release()
            except Exception as e:  # never kill the server from a cron
                print(f"[auto-sleep] {type(e).__name__}: {e}")


_AUTO_SLEEP = _AutoSleep()


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


def _audio_to_wav_b64(audio_b64: str, ext: str) -> str:
    """Any audio container → mono 16 kHz 16-bit PCM wav (ffmpeg), the shape the service was validated on."""
    import base64
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"in.{ext}"
        dst = Path(td) / "out.wav"
        src.write_bytes(base64.b64decode(audio_b64))
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-ac", "1", "-ar", "16000",
                        "-sample_fmt", "s16", str(dst)], check=True)
        return base64.b64encode(dst.read_bytes()).decode()


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
    elif kind == "audio" and ext != "wav":
        # Normalize every container (m4a/aac/mp3/ogg) to the shape validated on 2026-11-03: mono 16 kHz PCM wav.
        inp.video_b64, inp.filename = _audio_to_wav_b64(inp.video_b64, ext), inp.filename.rsplit(".", 1)[0] + ".wav"
    payload = {"video_b64": inp.video_b64, "filename": inp.filename, "item_id": inp.item_id, "with_raw_embed": False,
               "transcribe": inp.transcribe, "bf16": True, "render_brain": inp.render_frames}
    try:
        res = _tribe_call(payload)
    except httpx.HTTPStatusError:
        if not inp.transcribe:
            raise
        # Transcription (WhisperX + spaCy + Llama on speech) is the fragile stage; the cortex still
        # hears the clip without it. Degrade rather than fail, and say so in the response.
        res = _tribe_call({**payload, "transcribe": False})
        res["transcribed"] = False
        res["note"] = "transcription failed on the TRIBE service; analyzed as sound only"
    return _store_result(inp.item_id, res, kind=kind, **({"note": res["note"]} if res.get("note") else {}))


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
    rep = _sleep(ENGRAMS, personal, owner=owner)
    _after_sleep(rep, owner)
    return rep


def _reflex(item_id: str, heads: dict[str, Any], owner: str = "local-user") -> dict[str, Any] | None:
    """L5 reflex: a precedent within radius + a confident personal head + an applicable rule → a
    ready-made sentence the voice can read without a reasoning pass. Returns None when any leg is missing."""
    e = ENGRAMS.get(item_id)
    if e is None:
        return None
    key = e["pca"] if e["pca"] is not None else e["cortex"]
    hits = ENGRAMS.recall(key, k=1, exclude=item_id, with_outcomes_only=True)
    if not hits or hits[0].similarity < 0.9:
        return None
    hit = hits[0]
    personal = (heads.get("personal") or {}).get("personal") if isinstance(heads.get("personal"), dict) else None
    if not personal or abs(float(personal.get("score", 0.5)) - 0.5) < 0.35:
        return None
    last = hit.outcomes[-1]
    liked_then = (last["kind"] == "liked" and last["value"] >= 0.5) or last["kind"] == "chosen_over"
    rules_ = [r for r in ENGRAMS.rules(owner) if r["confidence"] >= 0.3]
    rule = rules_[0] if rules_ else None
    verdict = "like it" if personal["score"] >= 0.5 else "pass on it"
    days = round((__import__("time").time() - hit.created_at) / 86400) if hit.created_at else None
    when = "today" if not days else f"{days} day{'s' if days > 1 else ''} ago"
    sentence = (f"Nearly the same cortical pattern as the one you {'liked' if liked_then else 'passed on'} {when} "
                f"(similarity {hit.similarity:.2f}); your taste model says {int(personal['score'] * 100)}% you will {verdict}."
                + (f" It follows your rule: {rule['text'][:110]}" if rule else ""))
    return {"reflex": True, "sentence": sentence, "precedent": {"item_id": hit.id, "similarity": round(hit.similarity, 3),
                                                               "outcome": last, "note": hit.note},
            "personal_score": round(float(personal["score"]), 3), "rule": rule["text"] if rule else None}


@app.get("/learning_curve")
def learning_curve(owner: str = "local-user") -> dict[str, Any]:
    """Personal-head quality as feedback accumulates: one point per sleep (LOO AUROC vs crowd)."""
    pts = [{"n_labeled": c["n_outcomes"], "loo_auroc": (c["report"] or {}).get("loo_auroc"),
            "crowd_auroc": (c["report"] or {}).get("crowd_loo_auroc"), "at": c["started_at"]}
           for c in ENGRAMS.consolidations(owner) if c.get("report") and not (c["report"] or {}).get("skipped")]
    return {"owner": owner, "points": pts, "memory": ENGRAMS.count(owner)}


@app.get("/prompt")
def prompt() -> dict[str, Any]:
    """The top of the voice's system prompt: SOUL + memory + user + taste + skills index (cached 60 s)."""
    return HOME.prompt({"memory_counts": ENGRAMS.count()})


class MemoryIn(BaseModel):
    action: str                 # add | replace | remove
    target: str = "memory"      # memory | user
    content: str | None = None
    old_text: str | None = None


@app.post("/memory")
def memory_write(inp: MemoryIn) -> dict[str, Any]:
    return HOME.memory(inp.action, inp.target, inp.content, inp.old_text)


@app.get("/skills")
def skills_list() -> dict[str, Any]:
    return {"skills": HOME.skills_index()}


@app.get("/skills/{name}")
def skill_view(name: str) -> dict[str, Any]:
    return HOME.skill_view(name)


class SkillIn(BaseModel):
    action: str                 # create | patch | archive
    name: str
    content: str | None = None
    category: str = "learned"
    old_text: str | None = None


@app.post("/skills/manage")
def skill_manage(inp: SkillIn) -> dict[str, Any]:
    return HOME.skill_manage(inp.action, inp.name, inp.content, inp.category, inp.old_text)


@app.post("/memory/reset")
def memory_reset(owner: str = "local-user", keep_engrams: bool = True) -> dict[str, Any]:
    """Start a taste from zero: drop outcomes, rules, consolidations and the personal head (engrams stay)."""
    ENGRAMS.db.execute("DELETE FROM outcomes"); ENGRAMS.db.execute("DELETE FROM rules WHERE owner=?", (owner,))
    ENGRAMS.db.execute("DELETE FROM consolidations WHERE owner=?", (owner,)); ENGRAMS.db.execute("UPDATE engrams SET surprise=0")
    if not keep_engrams:
        ENGRAMS.db.execute("DELETE FROM engrams WHERE owner=?", (owner,))
    ENGRAMS.db.commit()
    personal = getattr(registry, "_personal", None)
    if personal is not None:
        personal.X, personal.y, personal.ids, personal.model = [], [], [], None
        if personal.store_path.exists():
            personal.store_path.unlink()
    f = Path("state/rules") / owner / "USER_TASTE.md"
    if f.exists():
        f.unlink()
    return {"ok": True, **ENGRAMS.count()}


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
        diag.append("Reward and value circuits stay quiet: the reader is never told why this matters to them or what to feel")
        todo.append("Put one stake or feeling for the reader in the first two sentences (what they lose, want, or did not expect)")
    if lo("face_body") and lo("scene_place"):
        diag.append("Both the people and the scene regions are off: abstract writing with no person, place or sense in it")
        todo.append("Add one person, one place and one sense (a smell, a sound, a texture)")
    elif lo("face_body"):
        diag.append("The people region is quiet: nobody appears in the text")
        todo.append("Put one person in it and say what happened to them")
    elif lo("scene_place"):
        diag.append("The scene region is quiet: the reader cannot picture where this happens")
        todo.append("Sketch the place or situation in one line")
    if lo("default_mode"):
        diag.append("The story and imagination network (default mode) is quiet: it explains but never tells a story")
        todo.append("Turn it into one small episode with a time order (then, so, in the end)")
    if hi("language") and all(lo(g) for g in ("value_vmpfc", "default_mode")):
        diag.append("Only the language regions run high: smooth sentences that touch nothing, the signature of machine prose")
        todo.append("Cut the connectives and lists (Additionally, Furthermore, not only) and vary the sentence length")
    if hi("control_dlpfc") or hi("attention_dorsal"):
        diag.append("Focus and control regions run high: the sentences take effort to read (length, density, jargon)")
        todo.append("Split the long sentences and give every technical term one plain comparison")
    if hi("default_mode") and hi("value_vmpfc"):
        diag.append("Story immersion and reward both run high: the typical pattern of writing by a person")
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
    try:
        rf = _reflex(item_id, out.get("heads", {}))
        if rf:
            out["reflex"] = rf
    except Exception as e:   # a reflex is a shortcut, never a failure
        out["reflex_error"] = f"{type(e).__name__}: {e}"
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
