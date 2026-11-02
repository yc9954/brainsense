"""The full BrainSense build harness: same brief → Muse's first draft (= the plain-Muse baseline) →
then it KEEPS GOING: every round the cortex is read, an issue ledger is updated (opened / fixed /
still open after N tries), free CC-licensed reference images are sourced when an issue calls for a
real photo, Muse revises the *current* page (not a rewrite from zero), the result is scored and only
kept if it beats the best so far. Stops on budget or when nothing improves for `patience` rounds.

    uv run python -m brainsense.showcase.harness --only popup --rounds 6
    uv run python -m brainsense.showcase.harness --rounds 6            # all briefs
Outputs results/showcase/harness/<run>/<brief>/index.html: baseline vs harness, ledger, credits.
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
import typer

from ..loop.generate import SYSTEM as GEN_SYSTEM
from ..loop.generate import GenerationError, _body_text, _client, _extract_html
from ..loop.render import chrome_path
from .ab import BRIEFS, _eval, _score_with_retry
from .ab import generate as generate_oneshot
from .skills import read_brain

app = typer.Typer(add_completion=False)
UA = "BrainSense/0.1 (Meta hackathon demo; contact: alexlee@sweetspot.co.kr)"
MODEL = os.environ.get("BRAINSENSE_LLM_MODEL", "muse-spark-1.3")


# ----------------------------------------------------------------------------- free image sourcing
def source_images(query: str, out_dir: Path, n: int = 4, width: int = 1000) -> list[dict]:
    """Wikimedia Commons search (no key; CC0 / CC BY / CC BY-SA only). Saves thumbnails locally and
    returns [{path, title, license, author, source}] — the author/license strings are what the page credits."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # Commons search is literal: fall back from the full query to its first words until something comes back
    words = query.split()
    pages: dict = {}
    for q in [query, " ".join(words[:3]), " ".join(words[:2]), words[0] if words else query]:
        try:
            r = httpx.get("https://commons.wikimedia.org/w/api.php", headers={"User-Agent": UA}, timeout=40,
                          params={"action": "query", "generator": "search", "gsrsearch": f"{q} filetype:bitmap", "gsrnamespace": 6,
                                  "gsrlimit": 20, "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime", "iiurlwidth": width, "format": "json"})
            pages = r.json().get("query", {}).get("pages", {})
        except Exception as e:  # noqa: BLE001
            print(f"    [source] commons failed: {type(e).__name__}: {str(e)[:80]}")
            return []
        if len(pages) >= 3:
            break
    out = []
    for p in sorted(pages.values(), key=lambda x: x.get("index", 99)):
        ii = (p.get("imageinfo") or [{}])[0]
        md = ii.get("extmetadata", {})
        lic = md.get("LicenseShortName", {}).get("value", "")
        if not re.match(r"^(CC0|CC BY( \d\.\d)?|CC BY-SA( \d\.\d)?|Public domain)", lic, re.I):
            continue
        if ii.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
            continue
        if re.search(r"lingerie|nude|naked|bikini|sex|erotic|porn|corpse|gore|weapon", p["title"], re.I):
            continue   # Commons is unfiltered; keep brand pages safe
        if (ii.get("width") or 0) < 500:
            continue
        url = ii.get("thumburl") or ii.get("url")
        try:
            img = httpx.get(url, headers={"User-Agent": UA}, timeout=40, follow_redirects=True)
            if img.status_code != 200 or not img.headers.get("content-type", "").startswith("image/"):
                continue
        except Exception:  # noqa: BLE001
            continue
        ext = ".png" if "png" in img.headers.get("content-type", "") else ".jpg"
        name = re.sub(r"[^a-z0-9]+", "-", p["title"].replace("File:", "").lower())[:40].strip("-") + ext
        (out_dir / name).write_bytes(img.content)
        author = re.sub(r"<[^>]+>", "", md.get("Artist", {}).get("value", "")).strip()[:60] or "unknown"
        out.append({"path": f"assets/{name}", "title": p["title"].replace("File:", "")[:80], "license": lic, "author": author,
                    "source": ii.get("descriptionurl", ""), "query": query, "w": ii.get("thumbwidth") or ii.get("width"), "h": ii.get("thumbheight") or ii.get("height")})
        if len(out) >= n:
            break
    return out


def photo_gate(path: Path, brief: str, issue: str) -> tuple[bool, str]:
    """Muse (multimodal) looks at a sourced photo before the generator may use it: relevant to the brief,
    fit for a commercial first screen, no watermark/text/clutter. Keeps the Commons noise out of the page."""
    import base64
    if not Path(path).exists():
        return False, "missing file"
    img = base64.b64encode(Path(path).read_bytes()).decode()
    ext = "png" if str(path).lower().endswith(".png") else "jpeg"
    prompt = (f"Brief: {brief}\nThe photo is meant to fix: {issue}\n"
              "Rate 1-10 how usable this photo is as a hero/supporting image on that first screen (relevance to the brief, "
              "looks like a modern commercial product/brand photo, no watermark or heavy text, no odd subject). "
              "Reply ONLY with JSON: {\"score\": n, \"reason\": \"...\"}")
    try:
        r = _client().chat.completions.create(model=MODEL, temperature=0, max_tokens=2500,
                                              messages=[{"role": "user", "content": [{"type": "text", "text": prompt},
                                                                                      {"type": "image_url", "image_url": {"url": f"data:image/{ext};base64,{img}"}}]}])
        m = re.search(r"\{.*\}", r.choices[0].message.content or "", re.S)
        d = json.loads(m.group(0)) if m else {}
        score = float(d.get("score", 0))
        return score >= 7, f"{score:.0f}/10 {str(d.get('reason', ''))[:70]}"
    except Exception as e:  # noqa: BLE001
        return False, f"gate error {type(e).__name__}"


def plan_queries(brief: str, issues: list[str]) -> list[str]:
    """Muse turns the brief + open issues into 2-3 English image-search queries (JSON list)."""
    msg = (f"Brief: {brief}\nOpen issues from the brain critique: {' | '.join(issues) or 'none'}\n"
           "Give 2-3 short English search queries for free stock photos (Wikimedia Commons) that would fix the issues "
           "(e.g. a person's face looking to one side, the product on a clean background, the venue). Reply ONLY with a JSON array of strings.")
    try:
        r = _client().chat.completions.create(model=MODEL, messages=[{"role": "user", "content": msg}], temperature=0.3, max_tokens=800)
        m = re.search(r"\[.*\]", r.choices[0].message.content or "", re.S)
        qs = json.loads(m.group(0)) if m else []
        return [q for q in qs if isinstance(q, str)][:3]
    except Exception:  # noqa: BLE001
        return []


# ----------------------------------------------------------------------------- rendering in place
def render_in_place(html_path: Path, out_png: Path, width: int = 1280, height: int = 800) -> Path:
    """Like loop.render.render_html but the page stays in its folder so relative assets/ resolve."""
    html_path, out_png = Path(html_path).resolve(), Path(out_png).resolve()
    html = html_path.read_text(encoding="utf-8")
    freeze = ("<style id=\"brainsense-freeze\">*,*::before,*::after{animation-duration:.01s!important;animation-delay:0s!important;"
              "animation-iteration-count:1!important;transition-duration:.01s!important}</style>")
    tmp = html_path.with_name(f"._render_{html_path.stem}.html")
    tmp.write_text(html.replace("</head>", freeze + "</head>", 1) if "</head>" in html else html + freeze, encoding="utf-8")
    with tempfile.TemporaryDirectory() as d:
        subprocess.run([chrome_path(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
                        f"--user-data-dir={d}/p", f"--window-size={width},{height}", "--force-device-scale-factor=1",
                        "--virtual-time-budget=12000", "--allow-file-access-from-files", f"--screenshot={out_png}", tmp.as_uri()],
                       check=True, capture_output=True, timeout=90)
    tmp.unlink(missing_ok=True)
    return out_png


# ----------------------------------------------------------------------------- the loop
REVISE_SYSTEM = GEN_SYSTEM + """
You are now REVISING an existing page, not starting over. You receive the current HTML, an ISSUE LEDGER (what a
predicted human cortex still flags, how many rounds it has been open, what was already tried and did not help),
a designer's review, and a list of locally available CC-licensed photos (use them with <img src="assets/..."> when
an issue calls for a real face/product/scene; credit them in a small footer line with author and license).
Fix the OPEN issues in priority order while keeping what already works (when only one issue is listed, change ONLY what that issue needs — a minimal, surgical edit; do not restyle the rest). If an attempt is listed as tried-and-failed,
do something materially different. Start with ONE line: <!-- CHANGES: [{"issue": "...", "change": "..."}] --> then
output ONLY the full revised HTML document."""


def revise(html: str, brief: str, ledger: list[dict], assets: list[dict], judge_reason: str, round_no: int, retries: int = 2,
           focus: int = 0) -> tuple[str, list[dict]]:
    open_issues = [i for i in ledger if i["resolved"] is None]
    if focus:   # small steps: only the top-priority open issue(s) this round, everything else must stay as is
        open_issues = sorted(open_issues, key=lambda i: (i["attempts"], i["opened"]))[:focus]
    led = "\n".join(f"- [{i['id']}] {i['text']} (open since r{i['opened']}, {i['attempts']} attempt(s)"
                    f"{'; tried: ' + ' / '.join(i['tried'][-2:]) if i['tried'] else ''}) → DO: {i['directive']}" for i in open_issues) or "- none open"
    fixed = ", ".join(f"[{i['id']}] fixed r{i['resolved']}" for i in ledger if i["resolved"] is not None) or "none yet"
    ass = "\n".join(f"- {a['path']} ({a['w']}x{a['h']}) — {a['title']} · {a['license']} · {a['author']}" for a in assets) or "- (no photos sourced yet; CSS/SVG only)"
    compact, last = "", "unknown"
    for _ in range(retries + 1):
        user = (f"Brief: {brief}\nRound {round_no}.\n\nISSUE LEDGER (open):\n{led}\nAlready fixed: {fixed}\n\n"
                f"Designer review of the current page: {judge_reason or '(none)'}\n\nAvailable photos:\n{ass}\n\n"
                f"CURRENT HTML:\n{html}{compact}")
        r = _client().chat.completions.create(model=MODEL, messages=[{"role": "system", "content": REVISE_SYSTEM}, {"role": "user", "content": user}],
                                              temperature=0.6, max_tokens=16000)
        ch = r.choices[0]
        text = ch.message.content or ""
        new_html = _extract_html(text)
        m = re.search(r"<!--\s*CHANGES:\s*(\[.*?\])\s*-->", text, re.S)
        try:
            changes = json.loads(m.group(1)) if m else []
        except json.JSONDecodeError:
            changes = []
        if ch.finish_reason == "length" or "</html>" not in new_html.lower():
            last = f"truncated ({len(new_html)} chars)"
            compact = "\n\nIMPORTANT: your previous answer was cut off. Keep the whole document under 260 lines."
            continue
        if len(_body_text(new_html)) < 120:
            last = "empty body"
            compact = "\n\nIMPORTANT: the previous answer had no visible content."
            continue
        return new_html, changes
    raise GenerationError(f"revise r{round_no}: {last}")


def _issue_id(text: str) -> str:
    return re.sub(r"[^a-z가-힣]+", "", text.split(":")[0].lower())[:28]


RESOLVE_DZ = 0.35   # a region group that moved this much (relative z) toward the item mean counts as fixed


def update_ledger(ledger: list[dict], crit: dict, round_no: int) -> None:
    """Open new diagnoses; close an issue when it stops being flagged OR its region group has clearly moved."""
    seen = {_issue_id(d) for d in crit["diagnosis"]}
    z = dict(crit.get("ranking", []))
    groups = crit.get("groups") or [""] * len(crit["diagnosis"])
    for d, t, g in zip(crit["diagnosis"], crit["directives"] + [""] * 5, groups):
        iid = _issue_id(d)
        cur = next((i for i in ledger if i["id"] == iid), None)
        if cur is None:
            ledger.append({"id": iid, "text": d, "directive": t, "group": g, "z_opened": z.get(g), "opened": round_no,
                           "resolved": None, "attempts": 0, "tried": []})
        elif cur["resolved"] is not None:          # came back → reopen
            cur["resolved"], cur["opened"], cur["z_opened"] = None, round_no, z.get(cur.get("group"))
    for i in ledger:
        if i["resolved"] is not None or i["opened"] >= round_no:
            continue
        gone = i["id"] not in seen
        g, z0 = i.get("group"), i.get("z_opened")
        moved = g in z and z0 is not None and abs(z[g]) < abs(z0) - RESOLVE_DZ
        if gone or moved:
            i["resolved"] = round_no


def _score(png: Path, item_id: str, brief: str, kind: str) -> dict:
    sc = _score_with_retry(png, item_id, brief, 0.5)
    ev = _eval(item_id)
    crit = read_brain(ev, kind)
    return {"ui_score": sc.ui_score, "heads": {k: v for k, v in sc.heads.items() if k != "judge"}, "judge": sc.heads.get("judge", {}),
            "brain_only": round(sum(0.5 * (sc.heads[h]["percentile"] / 100) for h in ("aesthetic", "attention") if h in sc.heads), 3),
            "critique": crit.to_dict() | {"prompt_block": crit.prompt_block}}


def run_brief(key: str, cfg: dict, run_dir: Path, rounds: int, patience: int, stamp: str, focus: int = 0) -> dict:
    brief, kind = cfg["brief"], cfg["kind"]
    d = run_dir / key
    (d / "assets").mkdir(parents=True, exist_ok=True)
    print(f"\n▶ {key}: {brief}")
    # round 0 = plain Muse, one shot: this IS the baseline the harness is compared against
    html = generate_oneshot(brief, "", 1)
    (d / "r0.html").write_text(html, encoding="utf-8")
    png = render_in_place(d / "r0.html", d / "r0.png")
    s0 = _score(png, f"hz_{stamp}_{key}_r0", brief, kind)
    best = {"round": 0, "html": html, **s0}
    rounds_log = [{"round": 0, "accepted": True, "ui_score": s0["ui_score"], "brain_only": s0["brain_only"], "judge": s0["judge"].get("judge_score"),
                   "changes": [], "sourced": [], "diagnosis": s0["critique"]["diagnosis"]}]
    print(f"  r0 (Muse alone): ui {s0['ui_score']:.3f} · brain {s0['brain_only']:.3f} · judge {s0['judge'].get('judge_score', 0):.2f}")
    ledger: list[dict] = []
    update_ledger(ledger, s0["critique"], 0)
    assets: list[dict] = []
    rejected: set[str] = set()
    stale = 0
    for r in range(1, rounds + 1):
        open_issues = [i for i in ledger if i["resolved"] is None]
        sourced = []
        # source real photos when a visual issue persists (face / object / scene) or every other round while any issue is open
        wants_photo = [i for i in open_issues if re.search(r"얼굴|물체|장소|실루엣", i["text"]) and i["attempts"] >= 1] or (open_issues if r == 1 else [])
        if wants_photo and len(assets) < 8:
            dropped = 0
            seen_paths = {a["path"] for a in assets} | rejected
            for q in plan_queries(brief, [i["text"] for i in wants_photo][:3]):
                for a in source_images(q, d / "assets", n=3):
                    if a["path"] in seen_paths:
                        continue
                    seen_paths.add(a["path"])
                    ok, why = photo_gate(d / a["path"], brief, wants_photo[0]["text"])
                    a["gate"] = why
                    if ok:
                        sourced.append(a)
                        assets.append(a)
                    else:
                        dropped += 1
                        rejected.add(a["path"])
                        (d / a["path"]).unlink(missing_ok=True)
            if sourced or dropped:
                print(f"  r{r} sourced {len(sourced)} photo(s), gate dropped {dropped}: " + "; ".join(f"{a['title'][:28]} ({a['gate'][:5]})" for a in sourced))
        try:
            new_html, changes = revise(best["html"], brief, ledger, assets, best["judge"].get("reason", ""), r, focus=focus)
        except GenerationError as e:
            print(f"  r{r} skipped: {e}")
            continue
        (d / f"r{r}.html").write_text(new_html, encoding="utf-8")
        png = render_in_place(d / f"r{r}.html", d / f"r{r}.png")
        s = _score(png, f"hz_{stamp}_{key}_r{r}", brief, kind)
        for i in open_issues:
            i["attempts"] += 1
            ch = next((c.get("change", "") for c in changes if _issue_id(str(c.get("issue", ""))) == i["id"] or i["text"][:12] in str(c.get("issue", ""))), "")
            if ch:
                i["tried"].append(f"r{r}: {ch[:90]}")
        accepted = s["ui_score"] > best["ui_score"] + 0.005
        if accepted:
            best = {"round": r, "html": new_html, **s}
            update_ledger(ledger, s["critique"], r)
            stale = 0
        else:
            stale += 1
        rounds_log.append({"round": r, "accepted": accepted, "ui_score": s["ui_score"], "brain_only": s["brain_only"], "judge": s["judge"].get("judge_score"),
                           "changes": changes, "sourced": sourced, "diagnosis": s["critique"]["diagnosis"]})
        print(f"  r{r}: ui {s['ui_score']:.3f} · brain {s['brain_only']:.3f} · judge {s['judge'].get('judge_score', 0):.2f} · "
              f"{'ACCEPT' if accepted else 'reject'} · open issues {sum(1 for i in ledger if i['resolved'] is None)}")
        if stale >= patience:
            print(f"  stop: no improvement for {patience} rounds")
            break
    (d / "BEST.html").write_text(best["html"], encoding="utf-8")
    rep = {"brief": brief, "kind": kind, "baseline": rounds_log[0], "best_round": best["round"], "best": {k: v for k, v in best.items() if k != "html"},
           "rounds": rounds_log, "ledger": ledger, "assets": assets}
    (d / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    build_page(d)
    print(f"  best r{best['round']}: ui {rounds_log[0]['ui_score']:.3f} → {best['ui_score']:.3f} → {d / 'index.html'}")
    return rep


def build_page(d: Path) -> Path:
    rep = json.loads((d / "report.json").read_text(encoding="utf-8"))
    e = _html.escape
    b0, bb = rep["baseline"], rep["best"]
    br = rep["best_round"]

    def pct(h: dict, k: str) -> str:
        v = h.get(k, {}).get("percentile")
        return f"상위 {100 - v:.0f}%" if v is not None else "—"

    led = "".join(f"<tr><td>{e(i['text'])}</td><td>r{i['opened']}</td><td>{'r' + str(i['resolved']) if i['resolved'] is not None else '<b style=color:#ff7b72>open</b>'}</td>"
                  f"<td>{i['attempts']}</td><td class=k>{e(' / '.join(i['tried'][-2:]))}</td></tr>" for i in rep["ledger"])
    rows = "".join(f"<tr><td>r{r['round']}</td><td>{r['ui_score']:.3f}</td><td>{r['brain_only']:.3f}</td><td>{(r['judge'] or 0):.2f}</td>"
                   f"<td>{'✓' if r['accepted'] else '·'}</td><td class=k>{e('; '.join(str(c.get('change', ''))[:80] for c in r['changes'][:3]))}</td>"
                   f"<td class=k>{e(', '.join(a['title'][:24] for a in r['sourced']))}</td></tr>" for r in rep["rounds"])
    credits = "".join(f"<li>{e(a['title'])} — {e(a['author'])} · {e(a['license'])} · <a href='{e(a['source'])}'>source</a></li>" for a in rep["assets"])
    delta = bb["ui_score"] - b0["ui_score"]
    page = f"""<!doctype html><html lang=ko><head><meta charset=utf-8><title>BrainSense harness · {e(d.name)}</title>
<style>body{{font-family:-apple-system,Pretendard,sans-serif;background:#0b0b0f;color:#eee;margin:0;padding:32px}}h1{{font-size:20px;font-weight:600}}h2{{font-size:15px;margin:28px 0 8px}}
.row{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.card{{background:#15151b;border:1px solid #23232b;border-radius:14px;overflow:hidden}}.card img{{width:100%;display:block}}
.t{{padding:10px 14px;font-weight:600;font-size:13px;color:#ffb38a}}.m{{padding:8px 14px 12px;font-size:12.5px;color:#ccc}}table{{border-collapse:collapse;font-size:12.5px;width:100%}}td,th{{padding:6px 10px;border-bottom:1px solid #23232b;text-align:left;vertical-align:top}}
.k{{color:#8b8b96}}.big{{font-size:26px;font-weight:700;color:{'#7ee787' if delta > 0 else '#ff7b72'}}}.brief{{color:#aaa;font-size:13px}}ul{{font-size:12px;color:#9a9aa6}}</style></head><body>
<h1>같은 브리프, 제로부터 — Muse 한 번 vs BrainSense 하네스</h1><div class=brief>{e(rep['brief'])}</div>
<div class=big>ui_score {b0['ui_score']:.3f} → {bb['ui_score']:.3f} ({delta:+.3f}) · {len(rep['rounds']) - 1} rounds · {sum(1 for i in rep['ledger'] if i['resolved'] is not None)}/{len(rep['ledger'])} issues fixed</div>
<div class=row><div class=card><div class=t>Muse 한 번 (r0)</div><a href='r0.png' target=_blank><img src='r0.png'></a><div class=m>ui {b0['ui_score']:.3f} · 뇌 {b0['brain_only']:.3f} · 심사위원 {(b0['judge'] or 0):.2f}<br><span class=k>{e(' / '.join(b0['diagnosis'][:2]))}</span></div></div>
<div class=card><div class=t>BrainSense 하네스 (r{br})</div><a href='r{br}.png' target=_blank><img src='r{br}.png'></a><div class=m>ui {bb['ui_score']:.3f} · 뇌 {bb['brain_only']:.3f} · 심사위원 {bb['judge'].get('judge_score', 0):.2f} · 예쁨 {pct(bb['heads'], 'aesthetic')} · 주목 {pct(bb['heads'], 'attention')}<br><span class=k>{e(' / '.join(bb['critique']['diagnosis'][:2]))}</span></div></div></div>
<h2>문제 장부 (뇌가 연 이슈 → 해결 라운드)</h2><table><tr><th>issue</th><th>opened</th><th>resolved</th><th>attempts</th><th>tried</th></tr>{led}</table>
<h2>라운드별</h2><table><tr><th>r</th><th>ui</th><th>뇌</th><th>심사위원</th><th>kept</th><th>changes</th><th>sourced photos</th></tr>{rows}</table>
<h2>사진 출처 (Wikimedia Commons, 무료 라이선스)</h2><ul>{credits or '<li>없음</li>'}</ul></body></html>"""
    out = d / "index.html"
    out.write_text(page, encoding="utf-8")
    return out


@app.command()
def run(rounds: int = typer.Option(6), patience: int = typer.Option(3), only: str = typer.Option(""),
        out: Path = typer.Option(Path("results/showcase/harness")), name: str = typer.Option(""),
        focus: int = typer.Option(0, help="revise only the top-N open issues per round (surgical edits); 0 = all")):
    run_dir = out / (name or time.strftime("%Y%m%d-%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)
    stamp = run_dir.name
    summary = {}
    for key in [k for k in BRIEFS if not only or k in only.split(",")]:
        rep = run_brief(key, BRIEFS[key], run_dir, rounds, patience, stamp, focus)
        summary[key] = {"baseline_ui": rep["baseline"]["ui_score"], "best_ui": rep["best"]["ui_score"], "best_round": rep["best_round"],
                        "issues_fixed": sum(1 for i in rep["ledger"] if i["resolved"] is not None), "issues": len(rep["ledger"]), "photos": len(rep["assets"])}
        (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    app()
