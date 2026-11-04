"""Agency-grade redesign of REAL pages: live site (full page + first screen) → cortex critique → Muse
picks a reference design language and photo keywords → CC photography (Commons, photo-gated) → Muse
rebuilds the page keeping brand, copy and information architecture → render → brain + judge → 2–3 rounds,
live page kept if nothing beats it → before/after at identical width, blind P(after better), credits.

    uv run python -m brainsense.showcase.redesign_pro https://www.sweetspot.co.kr --name sweetspot --rounds 3
"""
from __future__ import annotations

import base64
import html as _html
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import typer

from ..loop.generate import GenerationError, _body_text, _client, _extract_html
from ..loop.render import chrome_path
from .ab import _eval, _score_with_retry
from .harness import photo_gate, source_images
from .pairwise import judge_pair
from .pro import DESIGN, pro_system, render
from .redesign import _page_copy
from .skills import read_brain

app = typer.Typer(add_completion=False)
MODEL = os.environ.get("BRAINSENSE_LLM_MODEL", "muse-spark-1.3")


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {}


def capture_live(url: str, out_png: Path, height: int = 800, scale: int = 1) -> Path:
    out_png.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as d:
        subprocess.run([chrome_path(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
                        f"--user-data-dir={d}/p", f"--window-size=1280,{height}", f"--force-device-scale-factor={scale}", "--virtual-time-budget=8000",
                        f"--screenshot={out_png.resolve()}", url], check=True, capture_output=True, timeout=120)
    return out_png


def plan(url: str, copy: str, first_png: Path) -> dict:
    img = base64.b64encode(first_png.read_bytes()).decode()
    prompt = (f"You are a creative director at a top-tier agency briefed to redesign {url} without changing what it says.\n"
              f"Visible copy of the page:\n{copy[:2200]}\n\nFrom the screenshot and copy, reply ONLY with JSON: "
              "{\"lang\": one of " + json.dumps(list(DESIGN)) + ", \"queries\": [3 English photo-search queries for Wikimedia Commons that would give this page real, relevant, tasteful photography], "
              "\"keep\": [\"the 5–8 pieces of information architecture / copy that must survive (nav items, offers, numbers)\"], \"audience\": \"one line\"}")
    r = _client().chat.completions.create(model=MODEL, temperature=0.3, max_tokens=2500, extra_body={"reasoning_effort": "low"},
                                          messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}}]}])
    d = _json(r.choices[0].message.content or "")
    if d.get("lang") not in DESIGN:
        d["lang"] = "editorial"
    return d


SYSTEM_TAIL = """
REDESIGN RULES: this is an existing site. KEEP the brand name, the real copy (you may tighten wording), every nav item, offer, price and number listed under KEEP — never invent products, numbers or claims.
CHANGE layout, type, hierarchy, imagery, spacing and colour so the FIRST SCREEN reads in 3 seconds and the whole page feels designed by a top agency. Build the full page (hero + 3–5 sections + footer), not only the hero.
A logo / "trusted by" / client strip may ONLY list names that appear in the page copy, written exactly as the copy writes them (Korean stays Korean); if the copy has none, omit the strip. No invented testimonials, press quotes or awards.
Start the document with ONE line: <!-- CHANGES: [{"directive": "...", "change": "..."}] --> then output ONLY the HTML document."""

STOP = set("The And For With From Your You Our About Contact Home Live Open Now New Free Pro Team Plan Plans Learn More Get Start Book See View All Read Sign Log In Up Menu Close Next Prev Back Top Studio Service Services Projects Project Work Works Blog News Shop Store Price Pricing Rooms Room Search Guests Check Checkin Checkout Email Subscribe Submit Apply Share Save Edit Terms Privacy Policy Cookie Cookies Rights Reserved Copyright Inc LLC Ltd Co KST UTC AM PM Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May June July August September October November December Series Seed Round Beta Alpha Enterprise Growth Starter Business Basic Standard Premium Ultimate Max Mini Lite Plus".split())


def unverified_names(html: str, copy: str, keep: list[str]) -> list[str]:
    """Capitalised tokens in the rendered text that occur nowhere in the source copy — invented brands/claims."""
    text = _body_text(html)
    allowed = (copy + " " + " ".join(keep)).lower()
    try:
        words = {w.strip().lower() for w in open("/usr/share/dict/words", encoding="utf-8", errors="ignore")}
    except OSError:
        words = set()
    out = []
    for w in sorted(set(re.findall(r"\b[A-Z][A-Za-z0-9&+]{2,}\b", text))):
        if w in STOP or w.lower() in allowed or len(w) < 4 or w.lower() in words or w.capitalize() in STOP:
            continue
        out.append(w)
    return out[:8]


def generate(brief: str, system: str, copy: str, keep: list[str], critique: str, first_png: Path, round_no: int, retries: int = 2) -> tuple[str, list[dict]]:
    img = base64.b64encode(first_png.read_bytes()).decode()
    compact, last = "", "unknown"
    for _ in range(retries + 1):
        user = [{"type": "text", "text": f"Round {round_no}. {brief}\n\nKEEP: {json.dumps(keep, ensure_ascii=False)}\n\nPage copy:\n{copy[:2400]}\n\n{critique}{compact}"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}}]
        r = _client().chat.completions.create(model=MODEL, messages=[{"role": "system", "content": system + SYSTEM_TAIL}, {"role": "user", "content": user}], temperature=0.7, max_tokens=16000)
        ch = r.choices[0]
        text = ch.message.content or ""
        html = _extract_html(text)
        m = re.search(r"<!--\s*CHANGES:\s*(\[.*?\])\s*-->", text, re.S)
        try:
            changes = json.loads(m.group(1)) if m else []
        except json.JSONDecodeError:
            changes = []
        if ch.finish_reason == "length" or "</html>" not in html.lower():
            last = f"truncated ({len(html)} chars)"
            compact = "\n\nIMPORTANT: your previous answer was cut off. Keep the whole document under 320 lines; compact CSS."
            continue
        if len(_body_text(html)) < 200:
            last = "empty body"
            compact = "\n\nIMPORTANT: the previous answer had no visible content."
            continue
        return html, changes
    raise GenerationError(f"round {round_no}: {last}")


JUDGE_W = 0.7   # selection: judge 0.7 / brain 0.3 — the brain is the critic, the judge decides "would an agency ship this"


def score(png: Path, item_id: str, brief: str, kind: str) -> dict:
    sc = _score_with_retry(png, item_id, brief, JUDGE_W)
    ev = _eval(item_id)
    crit = read_brain(ev, kind)
    j = sc.heads.get("judge", {})
    return {"ui_score": sc.ui_score, "heads": {k: v for k, v in sc.heads.items() if k != "judge"}, "judge": j,
            "brain_only": round(sum(0.5 * (sc.heads[h]["percentile"] / 100) for h in ("aesthetic", "attention") if h in sc.heads), 3),
            "critique": crit.to_dict() | {"prompt_block": crit.prompt_block}}


@app.command()
def run(source: str = typer.Argument(...), name: str = typer.Option(""), rounds: int = typer.Option(3), kind: str = typer.Option("landing"),
        out: Path = typer.Option(Path("results/showcase/redesign-pro"))):
    slug = name or re.sub(r"[^a-z0-9]+", "-", re.sub(r"^https?://(www\.)?", "", source).lower()).strip("-")[:40]
    d = out / slug
    (d / "assets").mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%H%M%S")
    print(f"▶ {source} → {d}")
    before = capture_live(source, d / "before.png")
    capture_live(source, d / "before@2x.png", scale=2)
    capture_live(source, d / "before_full.png", height=2600)
    copy = _page_copy(source)
    (d / "copy.txt").write_text(copy, encoding="utf-8")
    p = plan(source, copy, before)
    print(f"  language {p['lang']} · keep {len(p.get('keep', []))} items · queries {p.get('queries')}")
    assets = []
    for q in (p.get("queries") or [])[:3]:
        for a in source_images(q, d / "assets", n=3, width=1600):
            ok, why = photo_gate(d / a["path"], f"redesign of {source}: {p.get('audience', '')}", f"tasteful hero photography for: {q}")
            a["gate"] = why
            if ok:
                assets.append(a)
            else:
                (d / a["path"]).unlink(missing_ok=True)
            if sum(1 for x in assets if x["query"] == q) >= 2:
                break
    if not assets:
        fallback = {"saas": ["modern office interior", "laptop desk workspace"], "editorial": ["architecture interior daylight", "city street black and white"],
                    "luxury": ["cosmetics product studio", "portrait natural light"], "hospitality": ["hotel interior", "coastal landscape"],
                    "brutalist": ["retail store interior", "Seoul street night", "shopping crowd"]}.get(p["lang"], ["city street", "interior"])
        for q in fallback:
            for a in source_images(q, d / "assets", n=4, width=1600):
                ok, why = photo_gate(d / a["path"], f"redesign of {source}: {p.get('audience', '')}", f"supporting photography for: {q}")
                m = re.match(r"(\d+)", why)
                ok = ok or (bool(m) and int(m.group(1)) >= 6)
                a["gate"] = why
                if ok:
                    assets.append(a)
                else:
                    (d / a["path"]).unlink(missing_ok=True)
                if sum(1 for x in assets if x["query"] == q) >= 2:
                    break
    print(f"  photos kept {len(assets)}: " + "; ".join(f"{a['title'][:26]} ({a['gate'][:4]})" for a in assets))
    brief = f"Redesign {source} for: {p.get('audience', 'its visitors')}. Make the first screen read in 3 seconds and the page feel like a top agency built it, keeping brand, copy and information architecture."
    s0 = score(before, f"rp_{stamp}_{slug}_r0", brief, kind)
    steps = [{"round": 0, "png": str(d / "before.png"), "html": None, "changes": [], **s0}]
    print(f"  r0 live: ui {s0['ui_score']:.3f} · brain {s0['brain_only']:.3f} · judge {s0['judge'].get('judge_score', 0):.2f} · {' / '.join(s0['critique']['diagnosis'][:2])}")
    system = pro_system(p["lang"], assets)
    for r in range(1, rounds + 1):
        prev = max(steps, key=lambda s: s["ui_score"])
        critique = prev["critique"]["prompt_block"] + (f"\nDesigner review of the current page: {prev['judge'].get('reason', '')}" if prev.get("judge") else "")
        if prev["round"] > 0:
            critique += f"\n(Your previous redesign scored {prev['ui_score']:.2f}; the live page scored {steps[0]['ui_score']:.2f}. Improve on it, do not restart from zero.)"
        try:
            html, changes = generate(brief, system, copy, p.get("keep", []), critique, Path(prev["png"]), r)
        except GenerationError as e:
            print(f"  r{r} skipped: {e}")
            continue
        (d / f"r{r}.html").write_text(html, encoding="utf-8")
        render(d / f"r{r}.html", d / f"r{r}.png")
        s = score(d / f"r{r}.png", f"rp_{stamp}_{slug}_r{r}", brief, kind)
        bad = unverified_names(html, copy, p.get("keep", []))
        if bad:   # advisory only (the heuristic has false positives on Korean-sourced names): the next round is told to check them
            s["critique"]["prompt_block"] += f"\nFACT CHECK: these capitalised names were not found in the source copy — keep only the ones the copy really contains (in its own language), remove the rest: {', '.join(bad)}"
        steps.append({"round": r, "png": str(d / f"r{r}.png"), "html": str(d / f"r{r}.html"), "changes": changes, "based_on": prev["round"], "unverified_names": bad, **s})
        print(f"  r{r}: ui {s['ui_score']:.3f} · brain {s['brain_only']:.3f} · judge {s['judge'].get('judge_score', 0):.2f} · {len(changes)} changes" + (f" · unverified {bad}" if bad else ""))
    best = max(steps, key=lambda s: s["ui_score"])
    pair = None
    if best["round"] > 0:
        render(d / f"r{best['round']}.html", d / "after@2x.png", scale=2)
        render(d / f"r{best['round']}.html", d / "after_full.png", height=2600)
        (d / "after.png").write_bytes(Path(best["png"]).read_bytes())
        (d / "BEST.html").write_text(Path(best["html"]).read_text(encoding="utf-8"), encoding="utf-8")
        pair = judge_pair(d / "after.png", d / "before.png", brief)
    rep = {"source": source, "brief": brief, "plan": p, "photos": assets, "steps": steps, "best_round": best["round"], "pairwise_after_vs_before": pair}
    (d / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    build_page(d)
    print(f"  best r{best['round']}: ui {steps[0]['ui_score']:.3f} → {best['ui_score']:.3f}" + (f" · P(after better) {pair['p_first']:.2f}" if pair else " · live page kept") + f" → {d / 'index.html'}")


def build_page(d: Path) -> Path:
    rep = json.loads((d / "report.json").read_text(encoding="utf-8"))
    e = _html.escape
    steps = rep["steps"]
    o = steps[0]
    b = next(s for s in steps if s["round"] == rep["best_round"])
    pw = rep.get("pairwise_after_vs_before")
    credits = "".join(f"<li>{e(a['title'])} — {e(a['author'])} · {e(a['license'])} · <a href='{e(a['source'])}'>source</a></li>" for a in rep["photos"])
    changes = "".join(f"<li><span class=k>{e(str(c.get('directive', ''))[:140])}</span><br>→ {e(str(c.get('change', '')))}</li>" for c in b.get("changes", []))
    rows = "".join(f"<li>r{s['round']}: ui {s['ui_score']:.3f} · brain {s['brain_only']:.3f} · judge {s['judge'].get('judge_score', 0):.2f}</li>" for s in steps)
    after_img = "after_full.png" if (d / "after_full.png").exists() else f"r{b['round']}.png"
    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8><title>NeuroMuse redesign · {e(rep['source'])}</title>
<style>body{{font-family:-apple-system,Pretendard,sans-serif;background:#0b0b0f;color:#eee;margin:0;padding:32px}}h1{{font-size:20px;font-weight:600}}h2{{font-size:15px;margin:26px 0 8px}}
.row{{display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:start}}.card{{background:#15151b;border:1px solid #23232b;border-radius:14px;overflow:hidden}}.card img{{width:100%;display:block}}
.t{{padding:10px 14px;font-weight:600;font-size:13px;color:#ffb38a}}.m{{padding:8px 14px 12px;font-size:12.5px;color:#ccc;line-height:1.5}}.k{{color:#8b8b96}}.big{{font-size:26px;font-weight:700;color:#7ee787}}ul{{font-size:13px;line-height:1.6}}</style></head><body>
<h1>Agency-grade redesign by a brain in the loop — {e(rep['source'])}</h1>
<div class=k style="font-size:13px">{e(rep['brief'])} · design language: {e(rep['plan'].get('lang', ''))}</div>
<div class=big>ui_score {o['ui_score']:.3f} → {b['ui_score']:.3f}{' · blind judge P(after better) ' + format(pw['p_first'], '.2f') if pw else ' · live page kept'}</div>
<div class=row><div class=card><div class=t>BEFORE · live site (full page, 1280 wide)</div><img src='before_full.png'><div class=m>brain {o['brain_only']:.3f} · judge {o['judge'].get('judge_score', 0):.2f}<br><span class=k>{e(' / '.join(o['critique']['diagnosis'][:2]))}</span></div></div>
<div class=card><div class=t>AFTER · round {b['round']} (full page, 1280 wide)</div><img src='{after_img}'><div class=m>brain {b['brain_only']:.3f} · judge {b['judge'].get('judge_score', 0):.2f}<br><span class=k>{e(' / '.join(b['critique']['diagnosis'][:2]))}</span></div></div></div>
<h2>What the brain read on the live page → directives</h2><ul>{''.join(f'<li>{e(x)}</li>' for x in o['critique']['directives'])}</ul>
<h2>What changed (directive ↔ change)</h2><ul>{changes or '<li>(none)</li>'}</ul>
<h2>Per round</h2><ul>{rows}</ul>
<h2>Photo credits (Wikimedia Commons)</h2><ul>{credits or '<li>none used</li>'}</ul></body></html>"""
    (d / "index.html").write_text(page, encoding="utf-8")
    return d / "index.html"


if __name__ == "__main__":
    app()
