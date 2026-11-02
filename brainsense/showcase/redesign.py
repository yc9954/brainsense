"""Brain-guided redesign of a real page: screenshot the live site → TRIBE cortex → expert critique →
Muse rebuilds the first screen keeping the brand and copy → score again → one more round → a
before/after page with the diagnosis, the directives, what changed and the score deltas.

    uv run python -m brainsense.showcase.redesign https://www.sweetspot.co.kr --rounds 2
    uv run python -m brainsense.showcase.redesign page.html --name mysite
"""
from __future__ import annotations

import base64
import html as _html
import json
import os
import re
import time
from pathlib import Path

import typer

from ..loop.ab import _render_any
from ..loop.generate import GenerationError, _body_text, _client, _extract_html
from ..loop.judge import judge_image
from ..loop.render import render_html
from .ab import _eval, _score_with_retry
from .skills import read_brain

app = typer.Typer(add_completion=False)

SYSTEM = """You are a senior product designer redesigning the FIRST SCREEN (1280x800) of an existing website.
You get: a screenshot of the current page, its visible copy, and a BRAIN CRITIQUE — how a predicted human
cortex (TRIBE v2) responded to the current page, with prioritized directives. Rebuild the first screen as a
single-file HTML page (inline CSS, Google Fonts allowed, no external images: use CSS shapes, gradients, SVG,
emoji). KEEP the brand name, product, language and the real copy/offer (you may tighten wording, never invent
products or prices). APPLY the directives in order of priority; keep what the critique does not flag.
Start the document with an HTML comment on ONE line: <!-- CHANGES: [{"directive": "...", "change": "..."}, ...] -->
listing each directive you applied and the concrete change. Then output ONLY the HTML document."""


def _page_copy(src: str, max_chars: int = 2500) -> str:
    """Visible text of the live page (title/headings first) so the redesign keeps the real copy."""
    try:
        if src.startswith(("http://", "https://")):
            import httpx
            raw = httpx.get(src, follow_redirects=True, timeout=30, headers={"User-Agent": "Mozilla/5.0"}).text
        else:
            raw = Path(src).read_text(encoding="utf-8", errors="ignore")
    except Exception as e:  # noqa: BLE001
        return f"(copy unavailable: {e})"
    title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
    heads = re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", raw, re.S | re.I)
    heads = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h)).strip() for h in heads]
    text = _body_text(raw)
    out = (f"TITLE: {title.group(1).strip() if title else ''}\nHEADINGS: {' | '.join(h for h in heads if h)[:600]}\nTEXT: {text}")
    return out[:max_chars]


def _generate(copy: str, png: Path, critique: str, round_no: int, retries: int = 2) -> tuple[str, list[dict]]:
    img = base64.b64encode(Path(png).read_bytes()).decode()
    compact, last = "", "unknown"
    for _ in range(retries + 1):
        user = [{"type": "text", "text": f"Round {round_no}. Current page copy:\n{copy}\n\n{critique}{compact}"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}}]
        r = _client().chat.completions.create(model=os.environ.get("BRAINSENSE_LLM_MODEL", "muse-spark-1.3"),
                                              messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                                              temperature=0.7, max_tokens=16000)
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
            compact = "\n\nIMPORTANT: your previous answer was cut off. Keep the whole document under 250 lines."
            continue
        if len(_body_text(html)) < 120:
            last = "empty body"
            compact = "\n\nIMPORTANT: the previous answer had no visible content."
            continue
        return html, changes
    raise GenerationError(f"redesign round {round_no}: {last}")


def _score(png: Path, item_id: str, brief: str, kind: str) -> dict:
    sc = _score_with_retry(png, item_id, brief, 0.5)
    ev = _eval(item_id)
    crit = read_brain(ev, kind)
    j = sc.heads.get("judge", {})
    return {"ui_score": sc.ui_score, "heads": {k: v for k, v in sc.heads.items() if k != "judge"}, "judge": j,
            "brain_only": round(sum(0.5 * (sc.heads[h]["percentile"] / 100) for h in ("aesthetic", "attention") if h in sc.heads), 3),
            "critique": crit.to_dict() | {"prompt_block": crit.prompt_block}}


@app.command()
def run(source: str = typer.Argument(..., help="URL or local HTML file"), rounds: int = typer.Option(2),
        kind: str = typer.Option("landing"), name: str = typer.Option(""), out: Path = typer.Option(Path("results/showcase/redesign"))):
    slug = name or re.sub(r"[^a-z0-9]+", "-", re.sub(r"^https?://(www\.)?", "", source).lower()).strip("-")[:40]
    d = out / slug
    d.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%H%M%S")
    brief = f"Redesign the first screen of {source} so it reads faster and feels more desirable, keeping brand and copy."
    print(f"▶ {source} → {d}")
    orig_png = _render_any(source, d / "r0.png")
    copy = _page_copy(source)
    (d / "copy.txt").write_text(copy, encoding="utf-8")
    steps = [{"round": 0, "png": str(orig_png), "html": None, "changes": [], **_score(orig_png, f"rd_{stamp}_{slug}_r0", brief, kind)}]
    print(f"  r0 original: ui {steps[0]['ui_score']:.3f} · brain {steps[0]['brain_only']:.3f} · judge {steps[0]['judge'].get('judge_score', 0):.2f}")
    print("  " + " / ".join(steps[0]["critique"]["diagnosis"][:3]))
    for r in range(1, rounds + 1):
        prev = max(steps, key=lambda s: s["ui_score"])
        critique = prev["critique"]["prompt_block"]
        if r > 1 and prev["round"] > 0:
            critique += f"\n(Your previous redesign scored {prev['ui_score']:.2f}; the original scored {steps[0]['ui_score']:.2f}. Keep improving on the directives above.)"
        try:
            html, changes = _generate(copy, Path(prev["png"]), critique, r)
        except GenerationError as e:
            print(f"  r{r} skipped: {e}")
            continue
        (d / f"r{r}.html").write_text(html, encoding="utf-8")
        png = render_html(html, d / f"r{r}.png")
        rec = {"round": r, "png": str(png), "html": str(d / f"r{r}.html"), "changes": changes, "based_on": prev["round"],
               **_score(png, f"rd_{stamp}_{slug}_r{r}", brief, kind)}
        steps.append(rec)
        print(f"  r{r}: ui {rec['ui_score']:.3f} · brain {rec['brain_only']:.3f} · judge {rec['judge'].get('judge_score', 0):.2f} · {len(changes)} changes")
    best = max(steps[1:], key=lambda s: s["ui_score"]) if len(steps) > 1 else steps[0]
    report = {"source": source, "brief": brief, "kind": kind, "steps": steps, "best_round": best["round"]}
    (d / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    if best["html"]:
        (d / "BEST.html").write_text(Path(best["html"]).read_text(encoding="utf-8"), encoding="utf-8")
    build_page(d)
    print(f"  best: r{best['round']} ui {best['ui_score']:.3f} (original {steps[0]['ui_score']:.3f}) → {d / 'index.html'}")


def build_page(d: Path) -> Path:
    rep = json.loads((d / "report.json").read_text(encoding="utf-8"))
    steps = rep["steps"]
    o, b = steps[0], next(s for s in steps if s["round"] == rep["best_round"])
    e = _html.escape

    def pct(s: dict, h: str) -> str:
        v = s["heads"].get(h, {}).get("percentile")
        return f"상위 {100 - v:.0f}%" if v is not None else "—"

    def card(s: dict, title: str) -> str:
        diag = "<br>".join(e(x) for x in s["critique"]["diagnosis"][:3])
        return (f"<div class=card><div class=t>{title}</div><a href='{Path(s['png']).name}' target=_blank><img src='{Path(s['png']).name}'></a>"
                f"<div class=m>ui_score <b>{s['ui_score']:.3f}</b> · 예쁨 {pct(s, 'aesthetic')} · 주목 {pct(s, 'attention')} · 심사위원 {s['judge'].get('judge_score', 0):.2f}</div>"
                f"<div class=d>{diag}</div></div>")

    changes = "".join(f"<li><span class=k>{e(c.get('directive', ''))[:140]}</span><br>→ {e(c.get('change', ''))}</li>" for c in b.get("changes", []))
    directives = "".join(f"<li>{e(x)}</li>" for x in o["critique"]["directives"])
    delta = b["ui_score"] - o["ui_score"]
    page = f"""<!doctype html><html lang=ko><head><meta charset=utf-8><title>BrainSense redesign · {e(rep['source'])}</title>
<style>body{{font-family:-apple-system,Pretendard,sans-serif;background:#0b0b0f;color:#eee;margin:0;padding:32px}}h1{{font-size:20px;font-weight:600}}
.row{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.card{{background:#15151b;border:1px solid #23232b;border-radius:14px;overflow:hidden}}.card img{{width:100%;display:block}}
.t{{padding:10px 14px;font-weight:600;font-size:13px;color:#ffb38a}}.m{{padding:8px 14px;font-size:12.5px;color:#ccc}}.d{{padding:0 14px 12px;font-size:12.5px;color:#9a9aa6;line-height:1.5}}
h2{{font-size:15px;margin:28px 0 8px}}ul{{font-size:13px;line-height:1.6;color:#ddd}}.k{{color:#8b8b96}}.big{{font-size:28px;font-weight:700;color:{'#7ee787' if delta > 0 else '#ff7b72'}}}</style></head><body>
<h1>뇌가 고친 첫 화면 — {e(rep['source'])}</h1>
<div class=big>ui_score {o['ui_score']:.3f} → {b['ui_score']:.3f} ({delta:+.3f})</div>
<div class=row>{card(o, 'BEFORE · 지금 사이트')}{card(b, f'AFTER · BrainSense 루프 r{b["round"]}')}</div>
<h2>뇌가 원본에서 읽은 것 → 지시</h2><ul>{directives}</ul>
<h2>Muse가 실제로 바꾼 것 (지시 ↔ 변경)</h2><ul>{changes or '<li>(변경 목록 없음)</li>'}</ul>
<h2>라운드별</h2><ul>{''.join(f"<li>r{s['round']}: ui {s['ui_score']:.3f} · 뇌 {s['brain_only']:.3f} · 심사위원 {s['judge'].get('judge_score', 0):.2f}</li>" for s in steps)}</ul>
</body></html>"""
    out = d / "index.html"
    out.write_text(page, encoding="utf-8")
    return out


if __name__ == "__main__":
    app()
