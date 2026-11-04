"""Decision-trail strip for a brain-directed redesign: one column per round, "the brain said X, the
agent did Y, the score moved Z", with the round's thumbnail. Reads a redesign report.json tolerantly
(a `trail` list, else `steps`) and writes trail.html next to it; render the .card to PNG with Chrome.

    uv run python -m brainsense.showcase.trail results/showcase/redesign-pro/sweetspot
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import sys
from pathlib import Path

TOOL_WORDS = {
    "blender_render": "Modelled it in 3D", "render": "Modelled it in 3D", "typography": "Reset the type", "reflow": "Moved things around",
    "photo": "Found a real photo", "restyle_asset": "Kept the real one, restyled it", "keep_asset": "Kept the real one",
    "copy": "Re-flowed the words", "rebuild": "Rebuilt the page", "rerender": "Re-modelled the room", "live page": "The page as it is", "first plan": "The first plan",
}


def _tool_words(tool: str) -> str:
    return " + ".join(TOOL_WORDS.get(t.strip(), t.strip().replace("_", " ")) for t in str(tool).split("+"))


NARRATE_PROMPT = """You are the brain inside NeuroMuse, a model of a human viewer's cortex, narrating one step of a design loop for a general reader.
Write STRICT JSON with three short sentences, plain everyday words, no brain-area codes, no emoji, a little wit, each under 22 words. "said" and "read" are in the brain's first person; "did" is about the agent:
"said": what I (the brain) said about the page before this step, based on: {before}
"did": what the agent then did, in the third person, starting with a past-tense verb (e.g. "Modelled a sofa and a rug in 3D and lit it with real sun"), based on the tool "{tool}" and this note: {did}
"read": what I (the brain) felt when I looked at the result, based on: {after}
If a field has no basis, return "" for it."""


def _narrate(before: str, tool: str, did: str, after: str, cache: dict) -> dict:
    """Muse rewrites the technical trail into the brain's own voice; cached next to the report, regex fallback."""
    key = hashlib.sha1(f"{before}|{tool}|{did}|{after}".encode()).hexdigest()[:16]
    if key in cache:
        return cache[key]
    out = {"said": "", "did": "", "read": ""}
    try:
        from ..loop.generate import _client
        d: dict = {}
        for attempt in range(3):   # Muse counts reasoning against max_tokens; an empty reply just means try again
            r = _client().chat.completions.create(model=os.environ.get("BRAINSENSE_LLM_MODEL", "muse-spark-1.3"), temperature=0.4, max_tokens=4000,
                                                  messages=[{"role": "user", "content": NARRATE_PROMPT.format(before=before[:400] or "(nothing)", tool=tool, did=did[:400] or "(nothing)", after=after[:400] or "(nothing)")}])
            t = r.choices[0].message.content or ""
            m = re.search(r"\{.*\}", t, re.S)
            try:
                d = json.loads(m.group(0)) if m else {}
            except json.JSONDecodeError:
                d = {}
            if any(str(d.get(k, "")).strip() for k in out):
                break
        out = {k: str(d.get(k, "")).strip() for k in out}
        if not any(out.values()):
            out = {"said": _plain(before), "did": did, "read": _plain(after)}
    except Exception:  # noqa: BLE001
        out = {"said": _plain(before), "did": did, "read": _plain(after)}
    cache[key] = out
    return out


def _plain(diag: str) -> str:
    """Regex fallback for the most common read_brain lines."""
    d = diag
    d = re.sub(r"Object-shape \(LO\) and motion \(MT\) areas are low", "my object and motion sense stayed quiet", d)
    d = re.sub(r"Reward/value areas \(OFC/vmPFC\) are low", "my reward circuit stayed flat", d)
    d = re.sub(r"Reward circuit \(OFC/vmPFC\) is on", "my reward circuit lit up", d)
    d = re.sub(r"\((LO|MT|OFC/vmPFC|FFA|PPA|V1|V1-V4)\)", "", d)
    return d.strip()

CSS = """
body{margin:0;background:#000;color:#fff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}
.card{width:1180px;padding:26px 30px 24px;box-sizing:border-box;background:#000}
.k{color:#9AA0A6;font-size:12px;letter-spacing:2px;text-transform:uppercase}
h1{font-size:20px;font-weight:600;margin:6px 0 16px;letter-spacing:-.3px}
.row{display:grid;grid-auto-flow:column;grid-auto-columns:1fr;gap:14px}
.col{border:1px solid #2A2D31;border-radius:16px;background:#0E0F11;padding:12px;display:flex;flex-direction:column;gap:9px;min-width:0}
.col.win{border-color:#C0504D}
.th{width:100%;aspect-ratio:16/10;object-fit:cover;object-position:top;border-radius:10px;background:#1a1b1e;display:block}
.r{color:#9AA0A6;font-size:11px;letter-spacing:1.5px;text-transform:uppercase}
.tool{display:inline-block;align-self:flex-start;border:1px solid #C0504D;color:#fff;border-radius:999px;padding:3px 9px;font-size:11.5px;font-weight:600}
.tool.keep{border-color:#4A4F55;color:#9AA0A6}
.said{font-size:12.5px;line-height:1.4;color:#fff}
.said b{color:#9AA0A6;font-weight:600}
.sc{margin-top:auto;display:grid;grid-template-columns:auto 1fr auto;gap:8px;align-items:center;font-size:11.5px;color:#9AA0A6}
.bar{height:7px;background:#2A2D31;border-radius:4px;overflow:hidden}.bar i{display:block;height:100%;background:#fff}
.win .bar i{background:#C0504D}
.v{color:#fff;font-variant-numeric:tabular-nums}
.foot{margin-top:14px;color:#9AA0A6;font-size:12px;line-height:1.5}
"""


def _img(p: Path | None) -> str:
    if not p or not p.exists():
        return '<div class="th"></div>'
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return f'<img class="th" src="data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}">'


def _read_of(s: dict) -> str:
    d = s.get("diagnosis")
    if not d and isinstance(s.get("critique"), dict):
        d = s["critique"].get("diagnosis")
    if isinstance(d, list):
        return str(d[0]) if d else ""
    return str(d or "")


def _verdict_of(s: dict) -> str:
    """Why a round was not kept, in a few words (evolve/admaker reports)."""
    if s.get("accepted") is not False:
        return ""
    f = s.get("fidelity") or {}
    facts = f.get("facts") or s.get("facts") or {}
    if facts.get("numbers") or facts.get("names"):
        return "rejected: invented " + ", ".join([*map(str, (facts.get("numbers") or [])[:2]), *map(str, (facts.get("names") or [])[:2])])
    if f.get("missing"):
        return "rejected: lost " + ", ".join(map(str, f["missing"][:3]))
    if f.get("density_ok") is False:
        return "rejected: fewer items than the live page"
    p = s.get("p_vs_best") or s.get("pairwise", {}).get("p_first") if isinstance(s.get("pairwise"), dict) else s.get("p_vs_best")
    if isinstance(p, (int, float)) and p < 0.5:
        return f"not kept: the judge preferred the live page ({p:.2f})"
    return "not kept: did not beat the best so far"


def _rounds(rep: dict, root: Path) -> list[dict]:
    raw = rep.get("trail") or rep.get("steps") or rep.get("rounds") or rep.get("history") or []
    if rep.get("trail") and rep.get("steps"):
        # evolve.py: `steps` carry the scores per round, `trail` the art-director decisions (several per round)
        by_round: dict = {}
        for st in rep["steps"]:
            by_round[st.get("round")] = dict(st)
        for t in rep["trail"]:
            d = by_round.setdefault(t.get("round"), {"round": t.get("round")})
            d["tool"] = " + ".join([x for x in [d.get("tool"), t.get("tool")] if x])
            d["why"] = " ".join([x for x in [d.get("why"), t.get("why")] if x])
            if t.get("critique_line") or t.get("critique"):
                d["critique_line"] = t.get("critique_line") or t.get("critique")
        raw = [by_round[k] for k in sorted(by_round, key=lambda r: int(r or 0))]
    out = []
    for i, s in enumerate(raw):
        thumb = s.get("thumbnail") or s.get("thumb") or s.get("png")
        p = (root / thumb) if thumb and not Path(thumb).is_absolute() else (Path(thumb) if thumb else None)
        if p and not p.exists():   # paths in reports are usually repo-relative
            alt = Path.cwd() / thumb
            p = alt if alt.exists() else p
        if not p or not p.exists():   # studio/redesign runs name renders by round
            rn = s.get("round", i)
            for cand in (root / f"r{rn}.png", root / ("before.png" if int(rn or 0) == 0 else f"r{rn}.png"), root / f"round{rn}.png"):
                if cand.exists():
                    p = cand
                    break
        score = s.get("ui_score", s.get("score", s.get("brain")))
        judge = s.get("judge", {})
        jscore = judge.get("judge_score") if isinstance(judge, dict) else judge
        out.append({
            "round": s.get("round", i),
            "tool": s.get("tool") or s.get("action") or (("live page" if rep.get("source") else "first plan") if i == 0 else ("rebuild" if rep.get("source") else "rerender")),
            "why": s.get("why") or s.get("reason") or "",
            "critique": s.get("critique_line") or s.get("critique") or "",   # what the cortex said BEFORE this round (v2 trail)
            "read": _read_of(s),   # what the cortex says about this round's result
            "verdict": _verdict_of(s),
            "score": float(score) if isinstance(score, (int, float)) else None,
            "judge": float(jscore) if isinstance(jscore, (int, float)) else None,
            "thumb": p,
        })
    return out


def render(root: Path, narrate: bool = True) -> Path:
    rep = json.loads((root / "report.json").read_text())
    rounds = _rounds(rep, root)
    cache_p = root / "trail_text.json"
    cache = json.loads(cache_p.read_text()) if cache_p.exists() else {}
    if not rounds:
        raise SystemExit("no rounds in report.json")
    best_i = rep.get("best_round")
    if best_i is None:
        scored = [(r["score"] or -1, i) for i, r in enumerate(rounds)]
        best_i = max(scored)[1]
    smax = max([r["score"] or 0 for r in rounds] + [0.01])
    # keep the strip readable: live page, the kept round, and evenly spaced rounds between, at most 6 columns
    if len(rounds) > 6:
        keep = {0, best_i if best_i < len(rounds) else len(rounds) - 1}
        mids = [i for i in range(1, len(rounds)) if i not in keep]
        step = max(1, len(mids) // (6 - len(keep)))
        keep.update(mids[::step][: 6 - len(keep)])
        rounds = [r for i, r in enumerate(rounds) if i in keep]
        best_i = [i for i, r in enumerate(rounds) if r["round"] == rep.get("best_round", best_i)]
        best_i = best_i[0] if best_i else max(range(len(rounds)), key=lambda i: rounds[i]["score"] or -1)
    cols = []
    for i, r in enumerate(rounds):
        win = (r["round"] == best_i) or (i == best_i)
        c = r["critique"]
        if isinstance(c, dict):   # a full read_brain critique: take its diagnosis
            c = c.get("diagnosis") or c.get("prompt_block") or ""
        crit = c if isinstance(c, str) else " / ".join(str(x) for x in c)
        read = r["read"] if isinstance(r["read"], str) else " / ".join(r["read"])
        # the live page / first plan has no "before" and no agent action: only what the brain read
        if i == 0:
            crit = ""
        n = _narrate(crit, str(r["tool"]), str(r["why"]), read, cache) if narrate else {"said": crit, "did": str(r["why"]), "read": read}
        before = f'<div class="said"><b>The brain said</b> {html.escape(n["said"][:170])}</div>' if n["said"] else ""
        did = f'<div class="said"><b>So the agent</b> {html.escape(n["did"][:170])}</div>' if n["did"] and i > 0 else ""
        after = f'<div class="said"><b>Then the brain read</b> {html.escape(n["read"][:170])}</div>' if n["read"] else ""
        if r.get("verdict"):
            after += f'<div class="said" style="color:#9AA0A6">{html.escape(r["verdict"])}</div>'
        sc = ""
        if r["score"] is not None:
            sc = f'<div class="sc"><span>brain</span><span class="bar"><i style="width:{min(100, r["score"] / smax * 100):.0f}%"></i></span><span class="v">{r["score"]:.2f}</span></div>'
        if r["judge"] is not None:
            sc += f'<div class="sc"><span>judge</span><span class="bar"><i style="width:{min(100, r["judge"] * 100):.0f}%"></i></span><span class="v">{r["judge"]:.2f}</span></div>'
        tool_cls = "tool keep" if i == 0 else "tool"
        r["tool"] = _tool_words(r["tool"])
        cols.append(f'<div class="col{" win" if win else ""}"><div class="r">{("live page" if rep.get("source") else "first plan") if i == 0 else f"round {r["round"]}"}</div>'
                    f'<span class="{tool_cls}">{html.escape(str(r["tool"]))}</span>{before}{did}{_img(r["thumb"])}{after}{sc}</div>')
    src = rep.get("source", root.name)
    first, last = rounds[0], rounds[best_i if best_i < len(rounds) else -1]
    delta = f'brain score {first["score"]:.2f} → {last["score"]:.2f}' if first["score"] is not None and last["score"] is not None else ""
    page = (f'<!doctype html><meta charset="utf-8"><style>{CSS}</style><div class="card"><div class="k">brain-directed redesign · decision trail</div>'
            f'<h1>{html.escape(str(src))}</h1><div class="row">{"".join(cols)}</div>'
            f'<div class="foot">Read left to right: what the brain said about the page, what the agent did about it, the result, what the brain felt when it looked again, and the brain and judge scores. The red column is the one that was kept. {html.escape(delta)}</div></div>')
    out = root / "trail.html"
    out.write_text(page, encoding="utf-8")
    if narrate:
        cache_p.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(render(Path(sys.argv[1])))
