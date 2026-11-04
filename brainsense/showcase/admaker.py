"""Ad maker: the brain-directed loop taken all the way to a finished 12-second ad.

brief → creative brief (Muse) → one-shot ad (baseline) → rounds of: the predicted cortex watches the
clip (1 Hz), the brain critique says what is weak and when (hook, hold, CTA), an art director picks a
craft tool to answer it (Blender product render in the brand colours, a real CC photo, typography,
pacing, copy), Muse rebuilds the clip around it, the cortex watches again. Facts are gated against
the brief (no invented numbers, names, dates). Every round is logged as a decision trail that the
brain narrates (showcase/trail.py).

    uv run python -m brainsense.showcase.admaker run --brief serum --rounds 3
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path

import typer

from ..loop.generate import GenerationError, _client
from .evolve import _json, fact_check, run_tool
from .pairwise import judge_pair
from .video import _ad_judge, _extract_html, contact_sheet, generate_ad, render_video, score_video

app = typer.Typer(add_completion=False)
MODEL = os.environ.get("BRAINSENSE_LLM_MODEL", "muse-spark-1.3")

BRIEFS = {
    "serum": "A 12-second feed ad for 'Noon', a vitamin-C and ceramide serum in a frosted amber glass bottle (30 ml) from a premium direct-to-consumer skincare brand. "
             "Launch offer: 20% off for the first week. Audience: women 25 to 35 who read ingredient lists. Tone: calm, precise, expensive. Brand colours: deep amber, bone white, a thin black line.",
    "coffee": "A 12-second ad for 'Standpoint', a matte-black ceramic pour-over coffee set (dripper, server, two cups) from a small design studio. Price 89 dollars, ships in 3 days. "
              "Audience: people who already own a grinder. Tone: quiet, exact, a little dry. Brand colours: charcoal, warm white, one copper accent.",
    "popup": "A 12-second story ad for a 3-day pop-up store 'Sweetspot x Local Roastery' in Seongsu, Seoul, 14 to 16 November: strawberry desserts and specialty coffee, "
             "first 50 visitors each day get a free tart. Audience: women in their late 20s. Tone: warm, fast, specific. Brand colours: strawberry red, cream, dark green.",
}

AD_TOOLBOX = """TOOLS you may pick (1 or 2 per round, each with params):
- {"tool":"blender_render","params":{"preset":"plinth_bottle|display_table","camera":"hero_34|front|macro","props":[0-3 ids from PROPS],"backdrop":"studio|warm","exposure":-0.5..0.3}} → a photoreal hero of the physical product in the brand colours (Cycles). Use when the brain's object or reward regions are quiet and the clip has no real product to look at.
- {"tool":"photo","params":{"query":"English Commons search","treatment":"duotone|overlay|crop"}} → a real CC photo, processed. Faces/people quiet → a portrait, never a rendered one.
- {"tool":"pacing","params":{"hook_s":"0-1","reveal_s":"4-6","cta_s":"8-10","motion":"what moves and when"}} → re-time the three beats; use when attention peaks late or fades after the peak.
- {"tool":"typography","params":{"display":"font","body":"font","headline_px":120,"max_words_on_screen":5}} → one focal element per moment; use when language regions are busy and attention is low.
- {"tool":"copy","params":{"hook":"3-6 words","benefit":"one line","cta":"2-4 words"}} → sharper words, same facts."""


def _brand_brief(brief_text: str) -> dict:
    prompt = (f"You are the creative director. Brief: {brief_text}\n\nReply ONLY with JSON: "
              "{\"product\": {\"name\": \"...\", \"what\": \"...\", \"form\": \"bottle|jar|box|set|space\", \"colour\": \"...\"}, \"audience\": \"...\", \"promise\": \"one line\", "
              "\"must_say\": [\"facts that must appear, verbatim from the brief\"], \"tone\": \"...\", "
              "\"brand\": {\"primary\": \"#hex\", \"secondary\": \"#hex\", \"accent\": \"#hex\", \"text\": \"brand wordmark text\"}, "
              "\"physical_subject\": {\"what\": \"the physical product\", \"why_3d\": \"what a flat graphic cannot show (material, shape, scale)\", \"shown_by_assets\": false}}")
    r = _client().chat.completions.create(model=MODEL, temperature=0.2, max_tokens=3000, messages=[{"role": "user", "content": prompt}])
    b = _json(r.choices[0].message.content or "")
    b.setdefault("brand", {"primary": "#B5651D", "secondary": "#F5F0E6", "accent": "#111111", "text": "brand"})
    b.setdefault("physical_subject", {"what": "the product", "why_3d": "material and shape", "shown_by_assets": False})
    b["_allowed_text"] = brief_text
    return b


def _art_direct(brief: dict, critique: str, judge_reason: str, trail: list[dict], round_no: int) -> dict:
    hist = "\n".join(f"- r{t['round']}: {t['tool']} ({t.get('why', '')[:70]}) → brain {t.get('brain_delta', 0):+.2f}, judge {t.get('judge_delta', 0):+.2f}, {'kept' if t.get('accepted') else 'rejected'}" for t in trail)
    prompt = (f"You are the art director of round {round_no} of a 12-second ad. Creative brief: {json.dumps({k: v for k, v in brief.items() if not k.startswith('_')}, ensure_ascii=False)[:1800]}\n\n"
              f"BRAIN CRITIQUE of the current best clip (a model of a viewer's cortex watched it, 1 Hz):\n{critique}\n\nDesigner review: {judge_reason or '-'}\n\n{AD_TOOLBOX}\n"
              "PROPS: ['potted_plant_01', 'ceramic_vase_01', 'brass_vase_01']\nPrevious rounds:\n" + (hist or "-") + "\n\n"
              "Answer the critique with the 1 or 2 tools that address it; do not repeat a rejected move. Reply ONLY with JSON: "
              "{\"actions\": [{\"tool\": \"...\", \"params\": {...}, \"why\": \"one sentence\", \"critique_line\": \"the diagnosis line this answers\"}], \"hero\": \"what the hero imagery should be after this round\"}")
    d: dict = {}
    for attempt in range(3):   # Muse counts reasoning against max_tokens: an empty or cut reply just means ask again
        r = _client().chat.completions.create(model=MODEL, temperature=0.4, max_tokens=6000, messages=[{"role": "user", "content": prompt}])
        d = _json(r.choices[0].message.content or "")
        if d.get("actions"):
            break
    d.setdefault("actions", [])
    if not d["actions"]:   # last resort: the one move the time course always justifies
        d["actions"] = [{"tool": "pacing", "params": {"hook_s": "0-1", "reveal_s": "4-6", "cta_s": "8-10", "motion": "product enters in the first second"}, "why": "art director returned nothing; re-time the beats", "critique_line": "hook"}]
    return d


def _inline_assets(html: str, d: Path) -> str:
    """The clip renderer loads pages from a temp dir, so local assets become data URIs."""
    def sub(m: re.Match) -> str:
        p = d / m.group(2)
        if not p.exists():
            return m.group(0)
        mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
        return f'{m.group(1)}data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}{m.group(3)}'
    return re.sub(r'(src=["\']|url\(["\']?)(assets/[^"\')]+)(["\']|\))', sub, html)


def _brain_score(sc: dict) -> float:
    h = sc.get("heads") or {}
    def pct(k: str, w: float) -> float:
        v = h.get(k) or {}
        p = float(v.get("percentile", 50)) / 100
        c = float(v.get("confidence", 0))
        return w * (0.5 + (p - 0.5) * max(0.3, c))     # shrink toward 0.5 by confidence
    return round(pct("attention", 0.45) + pct("aesthetic", 0.3) + pct("appeal", 0.25), 4)


def _critique_text(sc: dict) -> str:
    c = sc["critique"]
    return (f"{c.get('prompt_block', '')}\n- TIME COURSE: attention front-load {sc['hook_delta']:+.2f} (positive = the hook lands early), attention peak at {sc['attention_peak_s']} s of 12. "
            "If the peak is after 4 s the hook is too slow; if attention falls after the peak, the product scene lacks a reveal.")


def _round(d: Path, stamp: str, key: str, html: str, round_no: int, brief_text: str, judge_w: float) -> dict:
    html = _inline_assets(html, d)
    (d / f"r{round_no}.html").write_text(html, encoding="utf-8")
    mp4 = render_video(html, d / f"r{round_no}.mp4")
    sheet = contact_sheet(mp4, d / f"r{round_no}.png")
    sc = None
    for attempt in range(4):   # the brain server and the GPU endpoint are shared and restart now and then
        try:
            sc = score_video(mp4, f"ad_{stamp}_{key}_r{round_no}")
            break
        except Exception as e:  # noqa: BLE001
            typer.echo(f"  score retry {attempt + 1}: {str(e)[:100]}")
            time.sleep(30)
    if sc is None:
        raise RuntimeError("brain scoring failed four times")
    jd = _ad_judge(sheet, brief_text)
    brain = _brain_score(sc)
    sel = round((1 - judge_w) * brain + judge_w * float(jd.get("judge_score", 0.5)), 4)
    return {"round": round_no, "html": str(d / f"r{round_no}.html"), "mp4": str(mp4), "png": str(sheet), "brain": sc, "judge": jd,
            "brain_score": brain, "ui_score": sel, "critique": sc["critique"].get("diagnosis", []),
            "attention_peak_s": sc["attention_peak_s"], "hook_delta": sc["hook_delta"]}


@app.command()
def run(brief: str = typer.Option("serum"), rounds: int = typer.Option(3), name: str = typer.Option(""), judge_w: float = typer.Option(0.5),
        out: Path = typer.Option(Path("results/showcase/admaker"))):
    brief_text = BRIEFS.get(brief, brief)
    key = brief if brief in BRIEFS else "custom"
    stamp = name or time.strftime("%m%d-%H%M")
    d = out / f"{key}-{stamp}"
    (d / "assets").mkdir(parents=True, exist_ok=True)
    cb = _brand_brief(brief_text)
    (d / "brief.json").write_text(json.dumps(cb, indent=1, ensure_ascii=False))
    typer.echo(f"▶ {key}: {cb.get('product', {}).get('name')} · brand {cb['brand']}")

    # round 0: the one-shot ad, what "just ask the model" gives you
    html0 = generate_ad(brief_text, "", 1)
    steps = [_round(d, stamp, key, html0, 0, brief_text, judge_w)]
    steps[0]["why"] = "one shot: Muse wrote the ad once, no feedback"
    steps[0]["accepted"] = True
    steps[0]["facts"] = fact_check(html0, brief_text + " " + json.dumps(cb.get("must_say", [])))   # reported, not gated: this is the baseline as the model gives it
    if not steps[0]["facts"].get("ok", True):
        typer.echo(f"  r0 one-shot invents facts: numbers {steps[0]['facts'].get('numbers')} names {steps[0]['facts'].get('names')}")
    best = steps[0]
    trail: list[dict] = []
    typer.echo(f"  r0 one-shot: brain {best['brain_score']:.2f} judge {best['judge'].get('judge_score', 0):.2f} select {best['ui_score']:.2f} · peak {best['attention_peak_s']} s")

    for r in range(1, rounds + 1):
        crit = _critique_text(best["brain"])
        ad = _art_direct(cb, crit, best["judge"].get("reason", ""), trail, r)
        actions = []
        for i, a in enumerate(ad.get("actions", [])[:2]):
            if a.get("tool") == "blender_render":
                a.setdefault("params", {})
                a["params"].setdefault("camera", "macro")          # the ad needs the product large; macro fills the frame
                a["params"].setdefault("glass", "frosted")
            res = run_tool(a, cb, d, r, i)
            actions.append(res)
            typer.echo(f"  r{r} tool {res.get('tool')}: {res.get('desc') or res.get('error') or json.dumps(res.get('params'))[:80]}")
        direction = "\n".join(f"- {a['tool']}: {a.get('desc') or json.dumps(a.get('params'), ensure_ascii=False)} — because {a.get('why', '')}"
                              + (f" → USE <img src=\"{a['output']}\"> as the HERO: full-bleed or cropped with object-fit: cover and a transform scale so the product fills at least 60% of the frame height in the product beat; never a small inset or a framed thumbnail; never redrawn" if a.get("output") else "") for a in actions)
        critique_in = (f"{crit}\n\nART DIRECTION FOR THIS ROUND (apply exactly):\n{direction}\nHero after this round: {ad.get('hero', '')}\n"
                       "Keep every fact from the brief and ADD NONE: no new numbers, names, dates, awards, counts or badges. Local image files listed above are the only imagery; no placeholders.")
        try:
            html = generate_ad(brief_text, critique_in, r)
        except GenerationError as e:
            typer.echo(f"  r{r} generation failed: {e}")
            continue
        fc = fact_check(html, brief_text + " " + json.dumps(cb.get("must_say", [])))
        step = _round(d, stamp, key, html, r, brief_text, judge_w)
        step["why"] = "; ".join(a.get("desc") or a.get("why", "") for a in actions) or ad.get("hero", "")
        step["actions"] = actions
        step["facts"] = fc
        step["accepted"] = bool(fc.get("ok", True)) and step["ui_score"] > best["ui_score"]
        for a in actions:
            trail.append({"round": r, "tool": a.get("tool"), "why": a.get("why", ""), "critique_line": a.get("critique_line", ""), "output": a.get("output"),
                          "thumbnail": step["png"], "brain_delta": round(step["brain_score"] - best["brain_score"], 3),
                          "judge_delta": round(float(step["judge"].get("judge_score", 0)) - float(best["judge"].get("judge_score", 0)), 3), "accepted": step["accepted"]})
        typer.echo(f"  r{r}: brain {step['brain_score']:.2f} judge {step['judge'].get('judge_score', 0):.2f} select {step['ui_score']:.2f} · peak {step['attention_peak_s']} s · facts {'ok' if fc.get('ok', True) else 'REJECT ' + str(fc.get('numbers'))} · {'KEPT' if step['accepted'] else 'not kept'}")
        steps.append(step)
        if step["accepted"]:
            best = step

    pw = judge_pair(Path(best["png"]), Path(steps[0]["png"]), brief_text) if best is not steps[0] else None
    rep = {"source": None, "brief": brief_text, "creative_brief": {k: v for k, v in cb.items() if not k.startswith("_")}, "steps": steps, "trail": trail,
           "best_round": best["round"], "pairwise_best_vs_oneshot": pw, "kind": "ad"}
    (d / "report.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False, default=str))
    typer.echo(f"  best r{best['round']}: select {steps[0]['ui_score']:.2f} → {best['ui_score']:.2f}" + (f" · P(best better than one-shot) {pw['p_first']:.2f}" if pw else " · one-shot kept") + f" → {d}")


if __name__ == "__main__":
    app()
