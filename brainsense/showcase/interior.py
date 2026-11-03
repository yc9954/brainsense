"""Brain-guided interior design in Blender: a parametric living-room corner is rendered headless
(Cycles), TRIBE reads the render, the critique is turned into design moves (light temperature,
palette, focal object, clutter, art, plant, rug…) by Muse as a new params JSON, re-rendered, scored,
kept only if better. Before/after renders + the param diff per round.

    uv run python -m brainsense.showcase.interior --rounds 5
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import subprocess
import time
from pathlib import Path

import typer

from ..loop.generate import _client
from .ab import _eval, _score_with_retry
from .skills import read_brain

app = typer.Typer(add_completion=False)
BLENDER = os.environ.get("BLENDER", "/Applications/Blender.app/Contents/MacOS/Blender")
SCENE = Path(__file__).with_name("interior_scene.py")
MODEL = os.environ.get("BRAINSENSE_LLM_MODEL", "muse-spark-1.3")
BRIEF = "A living-room corner people want to sit in: warm, calm, one clear focal point, modern and desirable (think a Scandinavian furniture catalogue hero shot)."
BASE = {"wall_color": "#d9d9d9", "floor_color": "#b08860", "floor_roughness": 0.5, "sofa_color": "#6b6b6b", "accent_color": "#c8a04a",
        "table_color": "#3a2a1e", "rug": False, "rug_color": "#8a6f5a", "art": False, "art_color": "#2d4a6b", "plant": False, "lamp": False,
        "lamp_emit": 4.0, "light_temp_k": 5500, "key_energy": 250, "sun_strength": 6.0, "clutter": 5, "camera": "corner"}
RANGES = ("wall_color/floor_color/sofa_color/accent_color/table_color/rug_color/art_color: hex; floor_roughness 0.1–0.9; rug/art/plant/lamp: bool; "
          "lamp_emit 0–12; light_temp_k 2700–6500; key_energy 50–800; sun_strength 1–12; clutter 0–8 (small bright boxes on the floor); camera corner|front")


def render(params: dict, out_png: Path) -> Path:
    pj = out_png.with_suffix(".json")
    pj.write_text(json.dumps(params), encoding="utf-8")
    subprocess.run([BLENDER, "-b", "--python", str(SCENE), "--", str(pj), str(out_png.resolve())], check=True, capture_output=True, timeout=600)
    return out_png


def propose(params: dict, critique: str, judge_reason: str, history: list[dict], round_no: int) -> tuple[dict, str]:
    hist = "\n".join(f"- r{h['round']}: ui {h['ui_score']:.3f} {'KEPT' if h['accepted'] else 'rejected'} · changed {h.get('changed', [])}" for h in history)
    prompt = (f"You are an interior designer steering a 3D render through parameters. Brief: {BRIEF}\n"
              f"Allowed parameters and ranges: {RANGES}\nCurrent params: {json.dumps(params)}\n"
              f"BRAIN CRITIQUE of the current render (translate web terms: 'CTA/hero' = the focal object, 'copy' = clutter):\n{critique}\n"
              f"Designer review: {judge_reason or '-'}\nHistory:\n{hist or '-'}\n"
              "Change 2–5 parameters that address the critique (do not repeat a rejected change). Reply ONLY with JSON: "
              "{\"params\": {full params object}, \"why\": \"one sentence\"}")
    r = _client().chat.completions.create(model=MODEL, messages=[{"role": "user", "content": prompt}], temperature=0.5, max_tokens=2500,
                                          extra_body={"reasoning_effort": "low"})
    m = re.search(r"\{.*\}", r.choices[0].message.content or "", re.S)
    d = json.loads(m.group(0)) if m else {}
    new = {**params, **{k: v for k, v in (d.get("params") or {}).items() if k in BASE}}
    return new, str(d.get("why", ""))


def _score(png: Path, item_id: str) -> dict:
    sc = _score_with_retry(png, item_id, BRIEF, 0.5)
    ev = _eval(item_id)
    crit = read_brain(ev, "poster")
    return {"ui_score": sc.ui_score, "heads": {k: v for k, v in sc.heads.items() if k != "judge"}, "judge": sc.heads.get("judge", {}),
            "brain_only": round(sum(0.5 * (sc.heads[h]["percentile"] / 100) for h in ("aesthetic", "attention") if h in sc.heads), 3),
            "critique": crit.to_dict() | {"prompt_block": crit.prompt_block}}


@app.command()
def run(rounds: int = typer.Option(5), patience: int = typer.Option(3), name: str = typer.Option(""), out: Path = typer.Option(Path("results/showcase/interior"))):
    d = out / (name or time.strftime("%Y%m%d-%H%M%S"))
    d.mkdir(parents=True, exist_ok=True)
    stamp = d.name
    params = dict(BASE)
    png = render(params, d / "r0.png")
    s0 = _score(png, f"int_{stamp}_r0")
    best = {"round": 0, "params": params, **s0}
    hist = [{"round": 0, "accepted": True, "ui_score": s0["ui_score"], "brain_only": s0["brain_only"], "judge": s0["judge"].get("judge_score"), "params": params, "changed": [], "why": "baseline: flat light, grey sofa, clutter"}]
    print(f"  r0 baseline: ui {s0['ui_score']:.3f} · brain {s0['brain_only']:.3f} · judge {s0['judge'].get('judge_score', 0):.2f} · {' / '.join(s0['critique']['diagnosis'][:2])}")
    stale = 0
    for r in range(1, rounds + 1):
        try:
            new, why = propose(best["params"], best["critique"]["prompt_block"], best["judge"].get("reason", ""), hist, r)
        except Exception as e:  # noqa: BLE001
            print(f"  r{r} propose failed: {str(e)[:80]}")
            continue
        changed = [k for k in new if new[k] != best["params"].get(k)]
        png = render(new, d / f"r{r}.png")
        s = _score(png, f"int_{stamp}_r{r}")
        accepted = s["ui_score"] > best["ui_score"] + 0.005
        if accepted:
            best = {"round": r, "params": new, **s}
            stale = 0
        else:
            stale += 1
        hist.append({"round": r, "accepted": accepted, "ui_score": s["ui_score"], "brain_only": s["brain_only"], "judge": s["judge"].get("judge_score"), "params": new, "changed": changed, "why": why,
                     "diagnosis": s["critique"]["diagnosis"][:2]})
        print(f"  r{r}: ui {s['ui_score']:.3f} · brain {s['brain_only']:.3f} · judge {s['judge'].get('judge_score', 0):.2f} · {'ACCEPT' if accepted else 'reject'} · {changed} · {why[:70]}")
        if stale >= patience:
            break
    rep = {"brief": BRIEF, "best_round": best["round"], "best": {k: v for k, v in best.items()}, "history": hist}
    (d / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    build_page(d)
    print(f"  best r{best['round']}: ui {hist[0]['ui_score']:.3f} → {best['ui_score']:.3f} → {d / 'index.html'}")


def build_page(d: Path) -> Path:
    rep = json.loads((d / "report.json").read_text(encoding="utf-8"))
    e = _html.escape
    h0, hb = rep["history"][0], rep["best"]
    rows = "".join(f"<tr><td>r{h['round']}</td><td><img src='r{h['round']}.png' style='width:160px;border-radius:6px'></td><td>{h['ui_score']:.3f}</td><td>{h['brain_only']:.3f}</td><td>{(h['judge'] or 0):.2f}</td>"
                   f"<td>{'✓' if h['accepted'] else '·'}</td><td class=k>{e(', '.join(h['changed']))}</td><td class=k>{e(h.get('why', ''))}</td></tr>" for h in rep["history"])
    diff = "".join(f"<li><code>{e(k)}</code>: {e(str(h0['params'].get(k)))} → <b>{e(str(hb['params'].get(k)))}</b></li>" for k in hb["params"] if hb["params"].get(k) != h0["params"].get(k))
    delta = hb["ui_score"] - h0["ui_score"]
    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8><title>BrainSense · Blender interior</title>
<style>body{{font-family:-apple-system,Pretendard,sans-serif;background:#0b0b0f;color:#eee;margin:0;padding:32px}}h1{{font-size:20px;font-weight:600}}h2{{font-size:15px;margin:26px 0 8px}}
.row{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.card{{background:#15151b;border:1px solid #23232b;border-radius:14px;overflow:hidden}}.card img{{width:100%;display:block}}
.t{{padding:10px 14px;font-weight:600;font-size:13px;color:#ffb38a}}.m{{padding:8px 14px 12px;font-size:12.5px;color:#ccc;line-height:1.5}}table{{border-collapse:collapse;font-size:12.5px}}td,th{{padding:6px 10px;border-bottom:1px solid #23232b;text-align:left;vertical-align:top}}
.k{{color:#8b8b96}}.big{{font-size:26px;font-weight:700;color:{'#7ee787' if delta > 0 else '#ff7b72'}}}ul{{font-size:13px;line-height:1.6}}code{{color:#ffb38a}}</style></head><body>
<h1>A brain steering Blender — the same room, parameters chosen from the cortex critique</h1>
<div class=k style="font-size:13px">{e(rep['brief'])}</div>
<div class=big>ui_score {h0['ui_score']:.3f} → {hb['ui_score']:.3f} ({delta:+.3f}) · best round r{rep['best_round']}</div>
<div class=row><div class=card><div class=t>BEFORE · baseline render</div><img src='r0.png'><div class=m>brain {h0['brain_only']:.3f} · judge {(h0['judge'] or 0):.2f}<br><span class=k>{e(' / '.join(rep['best']['critique']['diagnosis'][:1]) if rep['best_round'] == 0 else '')}</span></div></div>
<div class=card><div class=t>AFTER · r{rep['best_round']}</div><img src='r{rep['best_round']}.png'><div class=m>brain {hb['brain_only']:.3f} · judge {hb['judge'].get('judge_score', 0):.2f}<br><span class=k>{e(' / '.join(hb['critique']['diagnosis'][:2]))}</span></div></div></div>
<h2>What changed (baseline → best)</h2><ul>{diff or '<li>nothing beat the baseline</li>'}</ul>
<h2>Per round</h2><table><tr><th>r</th><th>render</th><th>ui</th><th>brain</th><th>judge</th><th>kept</th><th>changed</th><th>why (Muse)</th></tr>{rows}</table>
</body></html>"""
    out = d / "index.html"
    out.write_text(page, encoding="utf-8")
    return out


if __name__ == "__main__":
    app()
