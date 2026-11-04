"""Showcase, text: does a brain in the loop make Muse's writing read like a person's?

Same task, same model (Muse Spark), same budget. Only the feedback differs:
  source      Muse's plain draft of the task (what "just ask the model" gives you)
  oneshot     Muse asked once to rewrite the draft so a real person seems to have written it
  brain_loop  rounds x variants; between rounds the predicted cortex of a *reader* is read back:
              Human-likeness head (HC3-calibrated, holdout AUROC 0.88), attention head, and the
              region critique (/eval kind=text) as directives; pick by the Human-likeness head
Then a BLIND pairwise judge (Muse, both orders) picks between finalists, and both the source and the
brain winner are read aloud (macOS `say`) and sent through the audio pathway, so the same brain
hears them too.

    uv run python -m brainsense.showcase.text run --rounds 3 --variants 2
    uv run python -m brainsense.showcase.text run --only dating_bio --rounds 1 --variants 1   # smoke
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
from pathlib import Path

import httpx
import typer
from rich import print
from rich.markup import escape

from ..loop.generate import _client

app = typer.Typer(add_completion=False)
SERVER = os.environ.get("BRAINSENSE_SERVER_URL", "http://localhost:8000").rstrip("/")
MODEL = os.environ.get("BRAINSENSE_LLM_MODEL", "muse-spark-1.3")

BRIEFS: dict[str, dict] = {
    "popup_caption": {"reader": "Instagram followers of a Seoul dessert brand",
                      "task": "an Instagram caption (under 90 words) announcing a 3-day pop-up, 'Sweetspot x Local Roastery', in Seongsu, Seoul, 14-16 November: strawberry desserts and specialty coffee, first 50 visitors each day get a free tart"},
    "cold_email": {"reader": "a busy head of marketing at a mid-size direct-to-consumer brand",
                   "task": "a cold email (under 120 words) from a small creative studio that designs pop-up stores, asking for a 15-minute call next week; mention one past project (a 9-day sneaker pop-up that drew 11,000 visitors)"},
    "support_reply": {"reader": "a customer whose order arrived nine days late",
                      "task": "a customer-support reply (under 110 words) that apologises, explains the delay honestly (a warehouse move), gives a 20% refund without being asked, and does not ask the customer to do anything"},
    "dating_bio": {"reader": "people browsing a dating app",
                   "task": "a dating-app bio (under 70 words) for a 31-year-old pastry chef who climbs on weekends, collects old film cameras and cannot cook rice properly"},
    "founder_post": {"reader": "LinkedIn",
                     "task": "a LinkedIn post (under 130 words) from a solo founder whose meeting-notes app just passed 1,000 paying users after 14 months, with one lesson she learned the hard way"},
}

DRAFT_SYSTEM = "You are a helpful assistant."
REWRITE_SYSTEM = ("You are an experienced writer. Rewrite the given text so that a real person seems to have written it, "
                  "for the stated reader. Keep every fact. Output ONLY the rewritten text, no preamble, no quotes, no title.")
REVIEW_PROMPT = """You are a strict editor. Rate this text, written for the reader below, on how much it reads like a real person wrote it AND how well it would land with that reader (clear, specific, right tone, not generic, not forced).
Reader: {reader}
Task: {task}
Text:
{text}
Reply ONLY with JSON: {{"score": 0.0-1.0, "reason": "one sentence"}}"""
JUDGE_PROMPT = """Two versions of the same piece were written for this reader: {reader}.
Task: {task}
Which version reads more like a real person wrote it AND would land better with that reader (clear, specific, not generic, right tone)?
Reply ONLY with JSON: {{"winner": "A" or "B", "confidence": 0.5-1.0, "reason": "one sentence"}}

Version A:
{a}

Version B:
{b}"""


def _chat(system: str, user: str, temperature: float = 0.9, max_tokens: int = 3000) -> str:
    r = _client().chat.completions.create(model=MODEL, temperature=temperature, max_tokens=max_tokens,
                                          messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    text = (r.choices[0].message.content or "").strip()
    text = re.sub(r"^```[a-z]*\n|\n```$", "", text).strip()
    return text.strip('"').strip()


def brain_read(text: str, item_id: str, attempts: int = 3) -> dict:
    """analyze_text + eval → heads, critique. Retries because the dev server restarts now and then."""
    for i in range(attempts):
        try:
            with httpx.Client(timeout=900) as c:
                c.post(f"{SERVER}/analyze_text", json={"text": text, "item_id": item_id}).raise_for_status()
                ev = c.get(f"{SERVER}/eval/{item_id}", params={"heads": "humanlike,attention"}).json()
            h = ev["heads"]
            hl, at = h["humanlike"], h["attention"]
            sel = 0.5 + (hl["percentile"] / 100 - 0.5) * hl["confidence"]      # shrink toward 0.5 by confidence
            return {"humanlike_pct": round(hl["percentile"], 1), "humanlike_conf": round(hl["confidence"], 3),
                    "attention_pct": round(at["percentile"], 1), "select_score": round(sel, 4),
                    "critique": ev.get("critique", {}), "top_features": hl.get("top_features", [])[:3]}
        except Exception as e:  # noqa: BLE001
            if i == attempts - 1:
                raise
            print(f"[yellow]brain retry {i + 1} for {item_id}: {escape(str(e)[:120])}[/]")
            time.sleep(15)
    raise RuntimeError("unreachable")


def _critique_block(history: list[dict]) -> str:
    best = max(history, key=lambda h: h["select_score"])
    worst = min(history, key=lambda h: h["select_score"])
    c = best["critique"]
    lines = [f"A model of a reader's brain read your previous rounds. BEST so far: Human-likeness top {100 - best['humanlike_pct']:.0f}% "
             f"(percentile {best['humanlike_pct']:.0f} vs 1,200 human and machine texts), attention percentile {best['attention_pct']:.0f}.",
             "Its text:", best["text"], ""]
    if c.get("diagnosis"):
        lines.append("What the reader's cortex says is missing in the best one: " + " / ".join(c["diagnosis"]))
    if c.get("directives"):
        lines.append("Do this next: " + " / ".join(c["directives"]))
    lines.append(f"The WORST round (Human-likeness percentile {worst['humanlike_pct']:.0f}) started: {worst['text'][:160]}...")
    lines.append("Rewrite again from the best one. Keep every fact, keep the length limit.")
    return "\n".join(lines)


def judge_pair(a: str, b: str, cfg: dict) -> dict:
    def ask(x: str, y: str) -> tuple[float, str]:
        r = _client().chat.completions.create(model=MODEL, temperature=0, max_tokens=2500,
                                              messages=[{"role": "user", "content": JUDGE_PROMPT.format(reader=cfg["reader"], task=cfg["task"], a=x, b=y)}])
        t = r.choices[0].message.content or ""
        m = re.search(r"\{.*\}", t, re.S)
        try:
            d = json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            d = {}
        conf = max(0.5, min(1.0, float(d.get("confidence", 0.5))))
        return (conf if str(d.get("winner", "A")).upper().startswith("A") else 1 - conf), str(d.get("reason", t[:200]))
    p1, r1 = ask(a, b)
    p2, r2 = ask(b, a)
    return {"p_first": round((p1 + (1 - p2)) / 2, 3), "order_ab": round(p1, 3), "order_ba": round(1 - p2, 3), "reason": f"{r1} | swapped: {r2}"}


def review(text: str, cfg: dict) -> dict:
    """Muse's own single-text review (0-1), used only for selection in --select blend, never as the verdict."""
    r = _client().chat.completions.create(model=MODEL, temperature=0, max_tokens=2000,
                                          messages=[{"role": "user", "content": REVIEW_PROMPT.format(reader=cfg["reader"], task=cfg["task"], text=text)}])
    t = r.choices[0].message.content or ""
    m = re.search(r"\{.*\}", t, re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        d = {}
    return {"score": max(0.0, min(1.0, float(d.get("score", 0.5)))), "reason": str(d.get("reason", t[:200]))}


def speak_and_hear(text: str, out: Path, item_id: str, voice: str = "Samantha") -> dict | None:
    """Read the text aloud with the system voice, send the audio through TRIBE's audio pathway."""
    aiff, wav = out.with_suffix(".aiff"), out.with_suffix(".wav")
    try:
        subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True, timeout=120)
        # the TRIBE service's audio path wants plain PCM (16 kHz mono wav); aac/m4a comes back as a 500
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff), "-ar", "16000", "-ac", "1", str(wav)], check=True, timeout=120)
        aiff.unlink(missing_ok=True)
        with httpx.Client(timeout=900) as c:
            c.post(f"{SERVER}/analyze", json={"video_b64": base64.b64encode(wav.read_bytes()).decode(), "filename": wav.name,
                                               "item_id": item_id, "transcribe": True}).raise_for_status()
            ev = c.get(f"{SERVER}/eval/{item_id}", params={"heads": "attention,appeal"}).json()
        roi = ev.get("roi_ts", {})
        means = {g: sum(v) / len(v) for g, v in roi.items() if v}
        mu = sum(means.values()) / max(1, len(means))
        sd = (sum((m - mu) ** 2 for m in means.values()) / max(1, len(means))) ** 0.5 or 1.0
        rel = {g: round((m - mu) / sd, 2) for g, m in means.items()}
        heads = {k: {"percentile": round(v["percentile"], 1), "confidence": round(v["confidence"], 3)} for k, v in ev.get("heads", {}).items() if isinstance(v, dict) and "percentile" in v}
        return {"file": str(wav), "seconds": round(len(next(iter(roi.values()), [])), 1), "heads": heads, "relative_z": rel,
                "ranking": [g for g, _ in sorted(rel.items(), key=lambda kv: -kv[1])]}
    except Exception as e:  # noqa: BLE001
        print(f"[yellow]audio skipped for {item_id}: {escape(str(e)[:160])}[/]")
        return None


def run_brief(key: str, cfg: dict, out: Path, rounds: int, variants: int, stamp: str, select: str = "head") -> dict:
    out.mkdir(parents=True, exist_ok=True)
    task = f"Write {cfg['task']}. Reader: {cfg['reader']}."
    t0 = time.time()
    source = _chat(DRAFT_SYSTEM, task, temperature=0.7)
    rewrite_user = f"Reader: {cfg['reader']}\nTask it was written for: {cfg['task']}\n\nText:\n{source}"
    oneshot = _chat(REWRITE_SYSTEM, rewrite_user)
    rec: dict = {"key": key, "cfg": cfg, "select": select, "source": {"text": source}, "oneshot": {"text": oneshot}, "brain_loop": {"history": []}}
    rec["source"] |= brain_read(source, f"tx_{stamp}_{key}_source")
    rec["oneshot"] |= brain_read(oneshot, f"tx_{stamp}_{key}_oneshot")
    history: list[dict] = []
    for r in range(1, rounds + 1):
        critique = _critique_block(history) if history else ""
        for v in range(1, variants + 1):
            tag = f"brain_loop_r{r}v{v}"
            user = rewrite_user + (f"\n\n{critique}" if critique else "") + f"\n\n(Variant {v}: take a distinctly different angle from other variants.)"
            text = _chat(REWRITE_SYSTEM, user)
            h = {"tag": tag, "round": r, "variant": v, "text": text, "critique_in": critique}
            h |= brain_read(text, f"tx_{stamp}_{key}_{tag}")
            if select == "blend":
                # brain as critic, Muse review as a sanity gate: the head alone can be gamed into forced casualness
                h["review"] = review(text, cfg)
                h["select_score"] = round(0.5 * h["select_score"] + 0.5 * h["review"]["score"], 4)
            history.append(h)
            print(f"[dim]{key}/{tag}: humanlike {h['humanlike_pct']:.0f} pct, attention {h['attention_pct']:.0f} pct[/]")
    best = max(history, key=lambda h: h["select_score"])
    rec["brain_loop"] |= {"history": history, "best": best["tag"], "text": best["text"], **{k: best[k] for k in ("humanlike_pct", "humanlike_conf", "attention_pct", "select_score", "critique")}}
    rec["pairwise"] = {"brain_vs_oneshot": judge_pair(best["text"], oneshot, cfg), "brain_vs_source": judge_pair(best["text"], source, cfg),
                       "oneshot_vs_source": judge_pair(oneshot, source, cfg)}
    rec["audio"] = {"source": speak_and_hear(source, out / "source", f"au_{stamp}_{key}_source"),
                    "brain_loop": speak_and_hear(best["text"], out / "brain_loop", f"au_{stamp}_{key}_brain")}
    rec["seconds"] = round(time.time() - t0, 1)
    (out / "result.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    for arm in ("source", "oneshot", "brain_loop"):
        (out / f"{arm}.txt").write_text(rec[arm]["text"], encoding="utf-8")
    print(f"[green]{key}: source {rec['source']['humanlike_pct']:.0f} → oneshot {rec['oneshot']['humanlike_pct']:.0f} → brain {rec['brain_loop']['humanlike_pct']:.0f} "
          f"(Human-likeness pct); judge P(brain>oneshot)={rec['pairwise']['brain_vs_oneshot']['p_first']:.2f} P(brain>source)={rec['pairwise']['brain_vs_source']['p_first']:.2f}[/]")
    return rec


@app.command()
def run(rounds: int = 3, variants: int = 2, only: str = "", name: str = "", select: str = "head") -> None:
    stamp = name or time.strftime("%m%d-%H%M")
    root = Path("results/showcase/text") / stamp
    root.mkdir(parents=True, exist_ok=True)
    keys = [k for k in BRIEFS if not only or k in only.split(",")]
    results = []
    for k in keys:
        try:
            results.append(run_brief(k, BRIEFS[k], root / k, rounds, variants, stamp, select))
        except Exception as e:  # noqa: BLE001
            print(f"[red]{k} failed: {escape(str(e)[:300])}[/]")
    summary = {"run": stamp, "rounds": rounds, "variants": variants, "select": select, "briefs": [
        {"key": r["key"], "humanlike_pct": {a: r[a]["humanlike_pct"] for a in ("source", "oneshot", "brain_loop")},
         "attention_pct": {a: r[a]["attention_pct"] for a in ("source", "oneshot", "brain_loop")},
         "p_brain_over_oneshot": r["pairwise"]["brain_vs_oneshot"]["p_first"], "p_brain_over_source": r["pairwise"]["brain_vs_source"]["p_first"],
         "p_oneshot_over_source": r["pairwise"]["oneshot_vs_source"]["p_first"],
         "audio": {a: (r["audio"][a] or {}).get("heads") for a in ("source", "brain_loop")}} for r in results]}
    (root / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    app()
