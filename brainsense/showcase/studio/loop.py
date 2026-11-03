"""Photoreal interior loop: brief → Muse writes a scene spec (real Poly Haven furniture, PBR floor/walls,
HDRI + sun through a window, DOF camera) → Blender renders → TRIBE cortex + an interior judge + render QA
→ Muse revises the spec → keep only if better. Final best is re-rendered at high samples.

    uv run python -m brainsense.showcase.studio.loop --rounds 6 --name living1
"""
from __future__ import annotations

import base64
import html as _html
import json
import os
import re
import subprocess
import time
from pathlib import Path

import typer

from ...loop.generate import _client
from ..ab import _eval, _score_with_retry
from ..skills import read_brain
from . import assets as A

app = typer.Typer(add_completion=False)
BLENDER = os.environ.get("BLENDER", "/Applications/Blender.app/Contents/MacOS/Blender")
SCENE = Path(__file__).with_name("scene.py")
MODEL = os.environ.get("BRAINSENSE_LLM_MODEL", "muse-spark-1.3")
BRIEF = ("A photoreal living-room corner for a furniture catalogue hero shot: warm, calm, inviting, one clear focal composition "
         "(sofa + coffee table), natural daylight through a window plus one warm practical light, Scandinavian/Japandi taste, no clutter.")
SPEC_DOC = (Path(__file__).with_name("scene.py").read_text(encoding="utf-8").split('"""')[1])   # the spec docstring from scene.py
BAD = set(json.loads((A.ROOT / "unavailable.json").read_text())) if (A.ROOT / "unavailable.json").exists() else set()


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {}


def plan(brief: str, catalog: str) -> dict:
    prompt = (f"You are an interior designer + Blender technical director. Write a scene spec JSON for this brief:\n{brief}\n\n"
              f"SPEC FORMAT:\n{SPEC_DOC}\n\nAVAILABLE ASSETS (use ONLY these ids):\n{catalog}\n\n"
              "Rules: 5–8 objects; keep footprints inside the room and non-overlapping (use the given dimensions); sofa against or near the back wall "
              "(y ≈ d/2 − depth/2 − 0.1), coffee table 0.6–0.9 m in front of it, a plant and a side/floor lamp as secondary points; window on the left wall; "
              "camera at seated-eye level 1.1–1.4 m, 2.6–3.2 m in front of the sofa (y ≈ −d/2 + 0.4), 28–35 mm lens, looking at the sofa seat (look_at z ≈ 0.6), so the sofa fills the middle third and the coffee table sits in the lower third without dominating; seats face the camera at rot_deg 0 (a sofa against the back wall keeps rot_deg 0; never 180); art gets a tex (e.g. fabric_pattern_07 or marble_01) or a muted colour, never plain white; HDRI strength 1–3 + sun 2–6 through the window; "
              "one warm area light (2700–3500 K, 60–200 W) as practical fill; add a `rug` under the coffee table, a `floor_lamp` beside the sofa and `art` on the back wall "
              "(parametric fixtures, see format). render: samples 64, w 1280, h 800, exposure 0.4. Reply ONLY with the JSON spec.")
    r = _client().chat.completions.create(model=MODEL, messages=[{"role": "user", "content": prompt}], temperature=0.6, max_tokens=6000)
    return _json(r.choices[0].message.content or "")


def validate(spec: dict) -> tuple[dict, list[str]]:
    """Download assets; drop unknown/unavailable ones; clamp positions into the room."""
    notes = []
    room = spec.setdefault("room", {})
    W, D = float(room.get("w", 5)), float(room.get("d", 5))
    known = {m["id"] for m in A.indoor_models()}
    kept = []
    for ob in spec.get("objects", []):
        aid = ob.get("asset")
        if aid not in known or aid in BAD:
            notes.append(f"dropped unknown/unavailable asset {aid}")
            continue
        try:
            A.fetch_model(aid)
        except Exception as e:  # noqa: BLE001
            BAD.add(aid)
            (A.ROOT / "unavailable.json").write_text(json.dumps(sorted(BAD)))
            notes.append(f"dropped {aid}: no glTF ({type(e).__name__})")
            continue
        x, y = ob.get("pos", [0, 0])
        ob["pos"] = [max(-W / 2 + 0.3, min(W / 2 - 0.3, float(x))), max(-D / 2 + 0.3, min(D / 2 - 0.3, float(y)))]
        kept.append(ob)
    spec["objects"] = kept[:9]
    for key in ("floor_tex", "wall_tex"):
        if room.get(key):
            try:
                A.fetch_texture(room[key])
            except Exception:  # noqa: BLE001
                notes.append(f"texture {room[key]} unavailable → flat colour")
                room[key] = None
    if spec.get("world", {}).get("hdri"):
        try:
            A.fetch_hdri(spec["world"]["hdri"])
        except Exception:  # noqa: BLE001
            notes.append(f"hdri {spec['world']['hdri']} unavailable → sky colour")
            spec["world"]["hdri"] = None
    cam = spec.setdefault("camera", {})
    cam.setdefault("pos", [0.6, -2.7, 1.25])
    cam.setdefault("look_at", [0.0, 1.2, 0.6])
    cam.setdefault("lens_mm", 30)
    cam.setdefault("fstop", 5.6)
    # lighting guard-rails: a blown-out window is the #1 realism killer
    w = spec.setdefault("world", {})
    if w.get("strength") is not None:
        w["strength"] = max(0.5, min(1.3, float(w["strength"])))
    if spec.get("sun"):
        spec["sun"]["strength"] = max(2.0, min(9.0, float(spec["sun"].get("strength", 5))))
    rd = spec.setdefault("render", {})
    rd.update({"w": 1280, "h": 800})
    rd["samples"] = max(int(rd.get("samples", 96)), 96)
    rd["exposure"] = max(-0.5, min(1.0, float(rd.get("exposure", 0.3))))
    # defaults that keep "CG" tells out: a textured rug and a textured canvas instead of flat white slabs
    if spec.get("rug") and not spec["rug"].get("tex") and not spec["rug"].get("color"):
        spec["rug"]["tex"] = "fabric_pattern_07"
    if spec.get("art") and not spec["art"].get("tex"):
        c = (spec["art"].get("color") or "#ffffff").lstrip("#")
        try:
            r_, g_, b_ = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
            pale = min(r_, g_, b_) > 200     # near-white canvas → give it a texture
        except ValueError:
            pale = True
        if pale:
            spec["art"]["tex"] = "marble_01"
    if spec.get("rug") and spec["rug"].get("tex"):
        try:
            A.fetch_texture(spec["rug"]["tex"])
        except Exception:  # noqa: BLE001
            spec["rug"]["tex"] = None
    if spec.get("art") and spec["art"].get("tex"):
        try:
            A.fetch_texture(spec["art"]["tex"])
        except Exception:  # noqa: BLE001
            spec["art"]["tex"] = None
    return spec, notes


def render(spec: dict, out_png: Path, samples: int | None = None) -> tuple[Path, list[dict]]:
    sp = json.loads(json.dumps(spec))
    if samples:
        sp["render"]["samples"] = samples
    pj = out_png.with_suffix(".spec.json")
    pj.write_text(json.dumps(sp, indent=1))
    r = subprocess.run([BLENDER, "-b", "--python", str(SCENE), "--", str(pj), str(out_png.resolve()), str(A.ROOT)], capture_output=True, text=True, timeout=1800)
    for m in re.finditer(r"(?:IMPORT_FAILED|MISSING_ASSET) (\S+)", r.stdout or ""):
        BAD.add(m.group(1))
        (A.ROOT / "unavailable.json").write_text(json.dumps(sorted(BAD)))
        print(f"  asset {m.group(1)} failed to import → blocked")
    if not out_png.exists():
        raise RuntimeError("render failed: " + (r.stdout + r.stderr)[-600:])
    placed = json.loads(out_png.with_suffix(".placed.json").read_text()) if out_png.with_suffix(".placed.json").exists() else []
    return out_png, placed


def qa(png: Path) -> dict:
    from PIL import Image
    im = Image.open(png).convert("L").resize((320, 200))
    px = list(im.get_flattened_data()) if hasattr(im, "get_flattened_data") else list(im.getdata())
    n = len(px)
    return {"blown_pct": round(100 * sum(p >= 250 for p in px) / n, 1), "black_pct": round(100 * sum(p <= 6 for p in px) / n, 1), "mean_lum": round(sum(px) / n, 1)}


def overlaps(placed: list[dict]) -> list[str]:
    out = []
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            a, b = placed[i], placed[j]
            ix = min(a["max"][0], b["max"][0]) - max(a["min"][0], b["min"][0])
            iy = min(a["max"][1], b["max"][1]) - max(a["min"][1], b["min"][1])
            if ix > 0.12 and iy > 0.12:
                out.append(f"{a['asset']} overlaps {b['asset']} by {ix:.2f}×{iy:.2f} m")
    return out


JUDGE = """You are a demanding interior photographer and art director. Score this rendered interior 1–10 on each:
realism (materials, light bounce, shadows — does it pass as a photo?), composition (focal group, framing, camera height),
light (believable window daylight + warm practical, no blown-out or muddy areas), desirability (would a buyer want to sit here?),
artifacts (10 = none: no floating/clipping furniture, no empty voids, no texture seams). Brief: {brief}
Reply ONLY with JSON: {{"realism": n, "composition": n, "light": n, "desirability": n, "artifacts": n, "fix": "the ONE most important change, concrete"}}"""


def judge(png: Path, brief: str) -> dict:
    img = base64.b64encode(png.read_bytes()).decode()
    try:
        r = _client().chat.completions.create(model=MODEL, temperature=0, max_tokens=3000, extra_body={"reasoning_effort": "low"},
                                              messages=[{"role": "user", "content": [{"type": "text", "text": JUDGE.format(brief=brief)}, {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}}]}])
        d = _json(r.choices[0].message.content or "")
    except Exception as e:  # noqa: BLE001
        d = {"error": str(e)[:80]}
    keys = ("realism", "composition", "light", "desirability", "artifacts")
    vals = [max(0.0, min(1.0, (float(d.get(k, 5)) - 1) / 9)) for k in keys]
    return {**{k: round(v, 3) for k, v in zip(keys, vals)}, "judge_score": round(sum(vals) / len(vals), 3), "fix": str(d.get("fix", ""))[:300]}


def score(png: Path, item_id: str, brief: str) -> dict:
    sc = _score_with_retry(png, item_id, None, 0.5)      # brain only
    ev = _eval(item_id)
    crit = read_brain(ev, "poster")
    j = judge(png, brief)
    q = qa(png)
    brain = sc.ui_score
    total = 0.45 * brain + 0.55 * j["judge_score"] - (0.1 if q["blown_pct"] > 6 else 0) - (0.1 if q["black_pct"] > 8 else 0)
    return {"ui_score": round(total, 4), "brain_only": round(brain, 3), "judge": j, "qa": q, "heads": {k: v for k, v in sc.heads.items() if k != "judge"},
            "critique": crit.to_dict() | {"prompt_block": crit.prompt_block}}


def revise(spec: dict, s: dict, placed: list[dict], notes: list[str], history: list[dict], catalog: str, round_no: int) -> tuple[dict, str]:
    hist = "\n".join(f"- r{h['round']}: score {h['ui_score']:.3f} ({'kept' if h['accepted'] else 'rejected'}) · {h.get('why', '')[:100]}" for h in history)
    ov = overlaps(placed)
    prompt = (f"You are revising a Blender interior scene (round {round_no}). Brief: {BRIEF}\n\nCURRENT SPEC:\n{json.dumps(spec)}\n\n"
              f"Placed footprints (metres, after grounding): {json.dumps(placed)}\nOverlaps: {ov or 'none'}\nValidation notes: {notes or 'none'}\n"
              f"Render QA: {s['qa']} (blown_pct > 6 or black_pct > 8 is a defect)\n"
              f"Interior judge (0–1): realism {s['judge']['realism']}, composition {s['judge']['composition']}, light {s['judge']['light']}, desirability {s['judge']['desirability']}, artifacts {s['judge']['artifacts']} — FIX FIRST: {s['judge']['fix']}\n"
              f"{s['critique']['prompt_block']}\n(translate web terms: 'CTA/hero' = the sofa group focal point, 'copy' = clutter)\n\nHistory:\n{hist or '-'}\n\n"
              f"AVAILABLE ASSETS (ids only from here):\n{catalog}\n\nSPEC FORMAT:\n{SPEC_DOC}\n\n"
              "Make 2–5 decisive changes that address the judge's fix, overlaps/QA defects and the brain critique (you may swap/add/remove objects, move the camera, "
              "change textures, HDRI, sun, lights, exposure). Do not repeat a rejected change. Reply ONLY with JSON: {\"spec\": {full spec}, \"why\": \"one sentence\"}")
    r = _client().chat.completions.create(model=MODEL, messages=[{"role": "user", "content": prompt}], temperature=0.5, max_tokens=7000)
    d = _json(r.choices[0].message.content or "")
    return (d.get("spec") or spec), str(d.get("why", ""))


@app.command()
def run(rounds: int = typer.Option(6), patience: int = typer.Option(3), name: str = typer.Option(""), out: Path = typer.Option(Path("results/showcase/studio")),
        final_samples: int = typer.Option(256)):
    d = out / (name or time.strftime("%Y%m%d-%H%M%S"))
    d.mkdir(parents=True, exist_ok=True)
    stamp = d.name
    catalog = A.catalog_text()
    print("▶ planning scene from brief")
    spec, notes = validate(plan(BRIEF, catalog))
    png, placed = render(spec, d / "r0.png")
    s0 = score(png, f"st_{stamp}_r0", BRIEF)
    best = {"round": 0, "spec": spec, "placed": placed, **s0}
    hist = [{"round": 0, "accepted": True, "ui_score": s0["ui_score"], "brain_only": s0["brain_only"], "judge": s0["judge"], "qa": s0["qa"], "why": "first plan", "notes": notes,
             "objects": [o["asset"] for o in spec["objects"]], "diagnosis": s0["critique"]["diagnosis"][:2]}]
    print(f"  r0: score {s0['ui_score']:.3f} · brain {s0['brain_only']:.3f} · judge {s0['judge']['judge_score']:.2f} (real {s0['judge']['realism']}, light {s0['judge']['light']}) · qa {s0['qa']} · {notes}")
    stale = 0
    for r in range(1, rounds + 1):
        try:
            new, why = revise(best["spec"], best, best["placed"], notes, hist, catalog, r)
            new, notes = validate(new)
        except Exception as e:  # noqa: BLE001
            print(f"  r{r} revise failed: {str(e)[:100]}")
            continue
        try:
            png, placed = render(new, d / f"r{r}.png")
        except Exception as e:  # noqa: BLE001
            print(f"  r{r} render failed: {str(e)[:120]}")
            continue
        s = score(png, f"st_{stamp}_r{r}", BRIEF)
        accepted = s["ui_score"] > best["ui_score"] + 0.005
        if accepted:
            best = {"round": r, "spec": new, "placed": placed, **s}
            stale = 0
        else:
            stale += 1
        hist.append({"round": r, "accepted": accepted, "ui_score": s["ui_score"], "brain_only": s["brain_only"], "judge": s["judge"], "qa": s["qa"], "why": why, "notes": notes,
                     "objects": [o["asset"] for o in new["objects"]], "diagnosis": s["critique"]["diagnosis"][:2]})
        print(f"  r{r}: score {s['ui_score']:.3f} · brain {s['brain_only']:.3f} · judge {s['judge']['judge_score']:.2f} (real {s['judge']['realism']}, light {s['judge']['light']}, art {s['judge']['artifacts']}) · {'ACCEPT' if accepted else 'reject'} · {why[:80]}")
        if stale >= patience:
            break
    # hero render of the best spec
    try:
        render(best["spec"], d / "best_hero.png", samples=final_samples)
    except Exception as e:  # noqa: BLE001
        print(f"  hero render failed: {str(e)[:100]}")
    rep = {"brief": BRIEF, "best_round": best["round"], "best": {k: v for k, v in best.items()}, "history": hist}
    (d / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    build_page(d)
    print(f"  best r{best['round']}: {hist[0]['ui_score']:.3f} → {best['ui_score']:.3f} → {d / 'index.html'}")


def build_page(d: Path) -> Path:
    rep = json.loads((d / "report.json").read_text(encoding="utf-8"))
    e = _html.escape
    h0, hb, br = rep["history"][0], rep["best"], rep["best_round"]
    hero = "best_hero.png" if (d / "best_hero.png").exists() else f"r{br}.png"
    rows = "".join(f"<tr><td>r{h['round']}</td><td><img src='r{h['round']}.png' style='width:200px;border-radius:6px'></td><td>{h['ui_score']:.3f}</td><td>{h['brain_only']:.3f}</td>"
                   f"<td>{h['judge']['judge_score']:.2f}<br><span class=k>real {h['judge']['realism']:.2f} · light {h['judge']['light']:.2f} · art {h['judge']['artifacts']:.2f}</span></td>"
                   f"<td>{'✓' if h['accepted'] else '·'}</td><td class=k>{e(h.get('why', ''))}<br>{e(', '.join(h['objects']))}</td></tr>" for h in rep["history"])
    delta = hb["ui_score"] - h0["ui_score"]
    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8><title>NeuroMuse · photoreal interior</title>
<style>body{{font-family:-apple-system,Pretendard,sans-serif;background:#0b0b0f;color:#eee;margin:0;padding:32px}}h1{{font-size:20px;font-weight:600}}h2{{font-size:15px;margin:26px 0 8px}}
.row{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.card{{background:#15151b;border:1px solid #23232b;border-radius:14px;overflow:hidden}}.card img{{width:100%;display:block}}
.t{{padding:10px 14px;font-weight:600;font-size:13px;color:#ffb38a}}.m{{padding:8px 14px 12px;font-size:12.5px;color:#ccc;line-height:1.5}}table{{border-collapse:collapse;font-size:12.5px}}td,th{{padding:6px 10px;border-bottom:1px solid #23232b;text-align:left;vertical-align:top}}
.k{{color:#8b8b96}}.big{{font-size:26px;font-weight:700;color:{'#7ee787' if delta > 0 else '#ff7b72'}}}.hero img{{width:100%;border-radius:14px;margin-top:10px}}</style></head><body>
<h1>A brain + a judge steering a photoreal Blender interior (real CC0 furniture, PBR, HDRI daylight)</h1>
<div class=k style="font-size:13px">{e(rep['brief'])}</div>
<div class=big>score {h0['ui_score']:.3f} → {hb['ui_score']:.3f} ({delta:+.3f}) · best round r{br}</div>
<div class=hero><img src='{hero}'></div>
<div class=row style="margin-top:18px"><div class=card><div class=t>FIRST PLAN · r0</div><img src='r0.png'><div class=m>brain {h0['brain_only']:.3f} · judge {h0['judge']['judge_score']:.2f} · {e(' / '.join(h0['diagnosis']))}</div></div>
<div class=card><div class=t>BEST · r{br}</div><img src='r{br}.png'><div class=m>brain {hb['brain_only']:.3f} · judge {hb['judge']['judge_score']:.2f} · {e(' / '.join(hb['critique']['diagnosis'][:2]))}</div></div></div>
<h2>Per round</h2><table><tr><th>r</th><th>render</th><th>score</th><th>brain</th><th>judge</th><th>kept</th><th>why / objects</th></tr>{rows}</table>
<h2>Best spec</h2><pre class=k style="font-size:11px;white-space:pre-wrap">{e(json.dumps(hb['spec'], indent=1))}</pre>
<p class=k>Assets: Poly Haven (CC0). Renderer: Blender {e(os.path.basename(BLENDER))} Cycles, OIDN denoise, AgX.</p></body></html>"""
    (d / "index.html").write_text(page, encoding="utf-8")
    return d / "index.html"


if __name__ == "__main__":
    app()
