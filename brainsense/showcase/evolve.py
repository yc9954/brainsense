"""Evolve a real page with a brain-directed art director. Per round the cortex critique + an intent brief
drive Muse (as art director) to pick 1–2 tools — keep/restyle a harvested real asset, fetch + process a CC photo,
RENDER a product/set in Blender in the brand's colours, change typography/grid, re-flow copy — then Muse rebuilds
the page keeping brand, copy, nav and every must_keep element (fidelity gate), the brain + judge score it, and
only improvements are kept. A decision trail with thumbnails records "the brain said X → the agent did Y → Δ".

    uv run python -m brainsense.showcase.evolve https://www.sweetspot.co.kr --name sweetspot --rounds 3
"""
from __future__ import annotations

import base64
import html as _html
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import typer

from ..loop.generate import GenerationError, _body_text, _client, _extract_html
from .ab import _eval, _score_with_retry
from .harness import photo_gate, source_images
from .harvest import harvest
from .pairwise import judge_pair
from .pro import DESIGN, render
from .redesign import _page_copy
from .skills import read_brain
from .studio import assets as PH

app = typer.Typer(add_completion=False)
MODEL = os.environ.get("BRAINSENSE_LLM_MODEL", "muse-spark-1.3")
BLENDER = os.environ.get("BLENDER", "/Applications/Blender.app/Contents/MacOS/Blender")
PRODUCT_SCENE = Path(__file__).with_name("studio") / "product_scene.py"
JUDGE_W = 0.7
PROPS = ["potted_plant_01", "potted_plant_02", "ceramic_vase_01", "ceramic_vase_02", "brass_vase_01", "brass_vase_02", "antique_ceramic_vase_01", "calathea_orbifolia_01", "anthurium_botany_01"]
TOOLBOX = """TOOLS you may pick (1–2 per round, each with params):
- {"tool":"blender_render","params":{"preset":"popup_booth|display_table|plinth_bottle","camera":"hero_34|front|topdown|macro","tagline":"short line for the signage","props":[2–5 ids from PROPS],"backdrop":"studio|warm","exposure":-0.5..0.3}}  → a photoreal hero image in the brand colours (Cycles). ONLY when the brief has a physical_subject that the harvested assets do not show (a product, booth, space or object whose shape/material/scale a flat graphic cannot convey) — 3D must have a purpose; it is refused for software, news, docs, directories and finance pages. Never render people.
- {"tool":"photo","params":{"query":"English Commons search","treatment":"duotone|overlay|crop"}}  → a real CC photo, processed. A fetched person is anonymous scene imagery: never presented as team/founders/customers/testimonials, no name or role beside it. Faces/people quiet on a people brief → fetch a portrait (never render one).
- {"tool":"restyle_asset","params":{"path":"assets/...","treatment":"crop|grayscale|overlay|frame"}}  → keep a harvested real asset (logo, map, chart, product shot) and restyle AROUND it; never redraw it.
- {"tool":"typography","params":{"display":"font name","body":"font name","scale":"headline px","grid":"12-col/8pt"}}
- {"tool":"reflow","params":{"move":"which block goes where, keeping every word"}}"""


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return {}


def _img(path: Path) -> dict:
    ext = "png" if str(path).lower().endswith(".png") else "jpeg"
    return {"type": "image_url", "image_url": {"url": f"data:image/{ext};base64,{base64.b64encode(Path(path).read_bytes()).decode()}"}}


def _screen_emit(path: Path) -> float:
    """Emission strength for the device_mockup screen: bright (white) pages must not blow out, dark pages need more glow."""
    try:
        from PIL import Image, ImageStat
        im = Image.open(path).convert("L")
        im.thumbnail((256, 256))
        lum = ImageStat.Stat(im).mean[0] / 255
    except Exception:  # noqa: BLE001
        return 1.0
    return round(max(0.55, min(1.8, 1.9 - 1.5 * lum)), 2)


def thumb(src: Path, dst: Path, width: int = 360) -> Path:
    from PIL import Image
    try:
        im = Image.open(src).convert("RGB")
    except Exception:  # noqa: BLE001  (svg or odd file: keep the original as its own thumbnail)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)
        return dst
    im.thumbnail((width, width * 2))
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, quality=85)
    return dst


def process_photo(src: Path, dst: Path, aspect: float = 1.5, max_w: int = 1600) -> Path:
    from PIL import Image, ImageEnhance
    im = Image.open(src).convert("RGB")
    w, h = im.size
    if w / h > aspect:
        nw = int(h * aspect)
        im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = int(w / aspect)
        im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)))
    im = ImageEnhance.Contrast(im).enhance(1.05)
    im.save(dst, quality=88)
    return dst


def intent_brief(url: str, d: Path, copy: str, manifest: dict) -> dict:
    assets_desc = "\n".join(f"- {i['path']} ({i['w']}×{i['h']}, alt: {i.get('alt', '')[:40]}, {'header' if i.get('inHeader') else 'body'})" for i in manifest["images"][:25])
    widgets = "\n".join(f"- {w['path']} ({w['tag']}, {w['w']}×{w['h']})" for w in manifest.get("widgets", []))
    prompt = (f"You are the creative director briefed to EVOLVE {url} (not replace it). Read the full-page screenshot, the copy and the harvested assets.\n"
              f"Copy:\n{copy[:2000]}\n\nOutline: {json.dumps(manifest.get('outline', {}), ensure_ascii=False)[:1200]}\n\nHarvested images:\n{assets_desc}\nWidgets (element screenshots):\n{widgets or '-'}\nLogo: {manifest.get('logo')}\n\n"
              "Reply ONLY with JSON: {\"audience\": \"...\", \"primary_task\": \"what a visitor must be able to do in 3 s\", \"tone\": \"...\", \"lang\": one of " + json.dumps(list(DESIGN)) + ", "
              "\"brand\": {\"primary\": \"#hex\", \"secondary\": \"#hex\", \"accent\": \"#hex\", \"text\": \"brand wordmark text\"}, "
              "\"must_keep\": [{\"id\": \"k1\", \"kind\": \"logo|asset|widget|nav|number|offer|text\", \"ref\": \"asset path or exact text\", \"why\": \"...\"}] (8–14 items: the logo, every data element (maps, charts, product shots), every nav item group, offers, key numbers), "
              "\"missing_imagery\": [{\"what\": \"...\", \"why\": \"...\"}] (what a top agency would add), \"weak_imagery\": [\"asset paths that look poor and may be replaced\"], "
              "\"page_class\": \"utility\" (news, docs, directories, dashboards, tools — visitors come to scan and find) or \"marketing\" (landing pages that sell or explain), "
              "\"physical_subject\": null or {\"what\": \"the physical product, space or object this page sells or explains\", \"why_3d\": \"why a photo or flat graphic cannot show it (shape, material, scale, assembly, interior)\", \"shown_by_assets\": true|false} — null for software, news, docs, directories, finance and anything a real photo already shows}")
    r = _client().chat.completions.create(model=MODEL, temperature=0.2, max_tokens=4000, messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, _img(d / "before_full.png")]}])
    b = _json(r.choices[0].message.content or "")
    b.setdefault("lang", "saas")
    if b["lang"] not in DESIGN:
        b["lang"] = "saas"
    b.setdefault("brand", {"primary": "#2456ff", "secondary": "#ffffff", "accent": "#9fe1cf", "text": "brand"})
    b.setdefault("must_keep", [])
    return b


def art_direct(brief: dict, critique: str, judge_reason: str, manifest: dict, trail: list[dict], round_no: int) -> dict:
    hist = "\n".join(f"- r{t['round']}: {t['tool']} ({t['why'][:70]}) → brain {t.get('brain_delta', 0):+.2f}, judge {t.get('judge_delta', 0):+.2f}, {'kept' if t.get('accepted') else 'rejected'}" for t in trail)
    prompt = ((f"MODE: stylesheet-only evolution of the live DOM (tools act through CSS: typography, spacing, colour, grid/reflow via CSS, background imagery from photo/render outputs; restyle_asset does not apply).\n" if brief.get("_mode_css") else "")
              + f"You are the art director of round {round_no}. Intent brief: {json.dumps(brief, ensure_ascii=False)[:2500]}\n\nBRAIN CRITIQUE of the current best page:\n{critique}\n\nDesigner review: {judge_reason or '-'}\n\n"
              f"Harvested real assets: logo {manifest.get('logo')}, {len(manifest['images'])} images, {len(manifest.get('widgets', []))} widget screenshots, {len(manifest.get('svgs', []))} svgs.\n"
              f"{TOOLBOX}\nPROPS: {PROPS}\nPrevious rounds:\n{hist or '-'}\n\n"
              "The brain critique says WHERE perception is weak; answer it without sacrificing the page's primary task or information density — on a utility page use type, rhythm, real logos and colour, never a hero panel. Pick the 1–2 tools that answer the critique (do not repeat a rejected move). Reply ONLY with JSON: {\"actions\": [{\"tool\": \"...\", \"params\": {...}, \"why\": \"one sentence\", \"critique_line\": \"the diagnosis line this answers\"}], \"hero\": \"what the hero imagery should be after this round\"}")
    r = _client().chat.completions.create(model=MODEL, temperature=0.4, max_tokens=3000, extra_body={"reasoning_effort": "low"}, messages=[{"role": "user", "content": prompt}])
    d = _json(r.choices[0].message.content or "")
    d.setdefault("actions", [])
    return d


def run_tool(action: dict, brief: dict, d: Path, round_no: int, idx: int) -> dict:
    tool, params = action.get("tool"), action.get("params") or {}
    out = {"tool": tool, "params": params, "why": action.get("why", ""), "critique_line": action.get("critique_line", "")}
    if tool == "blender_render":
        ps = brief.get("physical_subject")
        if not isinstance(ps, dict) or not ps.get("what") or ps.get("shown_by_assets"):
            out["error"] = "refused: no physical subject that the real assets fail to show — 3D has no purpose on this page"
            return out
        props = [p for p in (params.get("props") or PROPS[:4]) if p in PROPS] or PROPS[:4]
        for pid in props:
            try:
                PH.fetch_model(pid)
            except Exception:  # noqa: BLE001
                pass
        for h in ("brown_photostudio_02", "studio_small_09"):
            try:
                PH.fetch_hdri(h)
            except Exception:  # noqa: BLE001
                pass
        tag = params.get("tagline", "") or ""
        if tag and tag.lower() not in (brief.get("_allowed_text") or "").lower():
            tag = ""          # no invented store names / dates on the signage
        screen = params.get("screen", "live") or "live"
        screen_path = d / "before_full.png" if screen == "live" or not (d / screen).exists() else d / screen
        spec = {"preset": params.get("preset", "popup_booth"), "camera": params.get("camera", "hero_34"), "brand": brief["brand"], "tagline": tag,
                "props": props, "backdrop": params.get("backdrop", "studio"), "exposure": params.get("exposure", -0.25), "samples": 96, "w": 1600, "h": 1000,
                "screen_image": str(screen_path.resolve()), "screen_emit": _screen_emit(screen_path)}
        pj = d / "assets" / f"render_r{round_no}_{idx}.json"
        png = d / "assets" / f"render_r{round_no}_{idx}.png"
        pj.write_text(json.dumps(spec))
        subprocess.run([BLENDER, "-b", "--python", str(PRODUCT_SCENE), "--", str(pj), str(png.resolve()), str(PH.ROOT)], capture_output=True, text=True, timeout=1200)
        if png.exists():
            out["output"] = f"assets/{png.name}"
            out["desc"] = f"Blender {spec['preset']} render, camera {spec['camera']}, brand colours {brief['brand'].get('primary')}/{brief['brand'].get('accent')}"
        else:
            out["error"] = "render failed"
    elif tool == "photo":
        q = params.get("query") or "modern interior"
        kept = None
        for a in source_images(q, d / "assets", n=4, width=1600):
            ok, why = photo_gate(d / a["path"], f"{brief.get('audience', '')} · {brief.get('tone', '')}", f"hero photography for: {q}")
            m = re.match(r"(\d+)", why)
            if ok or (m and int(m.group(1)) >= 6):
                kept = a
                kept["gate"] = why
                break
            (d / a["path"]).unlink(missing_ok=True)
        if kept:
            src = d / kept["path"]
            dst = d / "assets" / f"photo_r{round_no}_{idx}.jpg"
            process_photo(src, dst)
            out["output"] = f"assets/{dst.name}"
            out["credit"] = {k: kept.get(k) for k in ("title", "author", "license", "source")}
            out["desc"] = f"CC photo '{kept['title'][:40]}' ({kept['license']}), treatment {params.get('treatment', 'crop')}"
        else:
            out["error"] = "no photo passed the gate"
    elif tool == "restyle_asset":
        out["output"] = params.get("path")
        out["desc"] = f"keep real asset {params.get('path')} and restyle around it ({params.get('treatment', '')})"
    else:
        out["desc"] = json.dumps(params, ensure_ascii=False)[:160]
    return out


EVOLVE_RULES = """
EVOLVE, DON'T REPLACE: rebuild the FULL page from the outline (same sections in the same order, every nav item, every offer, number and piece of copy — tighten words only).
PRIMARY TASK FIRST: the first screen must let a visitor do the brief's primary_task at least as fast as the live page, keeping most of the live first screen's items (stories, links, sections, versions) above the fold — never less than ~60% and never dropping a category. On a UTILITY page (page_class utility) there is NO marketing hero, spotlight, feature panel or decorative terminal: answer the brain critique with typographic hierarchy, rhythm, rules, numerals, real logos/favicons, colour accents and spacing instead. Decorative labels, fake counters and status chips are invented facts.
NO INVENTED FACTS (hard reject): no clients, logos, numbers, dates, places, prices, counts, badges, testimonials or awards that are not in the page copy. No version strings, release badges, changelog links, build numbers, map/data credits, region codes or abbreviations the page does not use. If a slot needs proof and the page has none, leave the slot out. Write names exactly as the copy writes them (Korean stays Korean).
MUST_KEEP elements must appear, legible, using the exact harvested file for anything visual (logo, map, chart, product shot) — never redraw them.
PEOPLE: a fetched CC photo of a person is anonymous scene imagery only — never captioned or placed as the site's team, founders, staff, customers, speakers or testimonials, and no name, role or quote may sit next to a fetched face. Harvested portraits keep their own names/roles from the page; any caption near a face must be a verbatim line from the page.
IMAGERY: use the listed local files only (harvested assets, processed CC photos, Blender renders) as <img src="assets/..."> or background-image; crop with object-fit, add scrims for text; credit only CC photos (author · licence) in a small footer line — never list file names, never add map/data credits the page does not have; credit CC photos in a small footer line.
Apply THIS ROUND'S ART DIRECTION exactly. Start with ONE line: <!-- CHANGES: [{"directive": "...", "change": "..."}] --> then output ONLY the HTML document."""


def generate(brief: dict, copy: str, manifest: dict, actions: list[dict], critique: str, base_png: Path, round_no: int, retries: int = 2) -> tuple[str, list[dict]]:
    from .pro import pro_system
    files = [{"path": i["path"], "w": i["w"], "h": i["h"], "title": i.get("alt") or "harvested image", "license": "site asset", "author": "site"} for i in manifest["images"][:20]]
    files += [{"path": w["path"], "w": w["w"], "h": w["h"], "title": f"real {w['tag']} element screenshot", "license": "site asset", "author": "site"} for w in manifest.get("widgets", [])]
    for a in actions:
        if a.get("output") and a["tool"] in ("blender_render", "photo"):
            files.append({"path": a["output"], "w": 1600, "h": 1000, "title": a.get("desc", ""), "license": a.get("credit", {}).get("license", "render"), "author": a.get("credit", {}).get("author", "NeuroMuse/Blender")})
    system = pro_system(brief["lang"], files) + EVOLVE_RULES
    direction = "\n".join(f"- {a['tool']}: {a.get('desc') or json.dumps(a.get('params'), ensure_ascii=False)} — because {a.get('why', '')}" + (f" → USE {a['output']} as the hero" if a.get("output") and a["tool"] in ("blender_render", "photo") else "") for a in actions)
    compact, last = "", "unknown"
    for _ in range(retries + 1):
        user = [{"type": "text", "text": (f"Round {round_no}. Brand: {json.dumps(brief['brand'])}. Audience: {brief.get('audience')}. Primary task: {brief.get('primary_task')}. Tone: {brief.get('tone')}.\n"
                                           f"MUST_KEEP: {json.dumps(brief['must_keep'], ensure_ascii=False)}\nLogo file: {manifest.get('logo')}\n"
                                           f"OUTLINE (keep this structure): {json.dumps(manifest.get('outline', {}), ensure_ascii=False)[:1500]}\n\nPage copy:\n{copy[:2600]}\n\n"
                                           f"ART DIRECTION THIS ROUND:\n{direction}\n\n{critique}{compact}")},
                _img(base_png)]
        r = _client().chat.completions.create(model=MODEL, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], temperature=0.6, max_tokens=16000)
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
            compact = "\n\nIMPORTANT: your previous answer was cut off. Keep the whole document under 340 lines; compact CSS."
            continue
        if len(_body_text(html)) < 200:
            last = "empty body"
            compact = "\n\nIMPORTANT: the previous answer had no visible content."
            continue
        return html, changes
    raise GenerationError(f"round {round_no}: {last}")


CSS_RULES = """You are evolving a LIVE page by stylesheet only. The DOM, every word, link, image and its order stay exactly as they are.
Reply with ONE line <!-- CHANGES: [{"directive": "...", "change": "..."}] --> and then ONLY a <style> element (you may start it with one @import of Google Fonts). Nothing else.
Rules: never hide text, links, images or form controls (no display:none / visibility:hidden / opacity:0 / zero font-size on content; purely decorative spacers may go); never inject text (no content: with words);
keep information density: body/list font sizes within +15% of the live page, first-screen item count must stay close to the live page; selectors must target the real DOM (use the ids/classes/tags in the DOM SAMPLE; table-based layouts stay tables);
improve hierarchy, rhythm, spacing, type pairing, colour system, link and hover affordance, header/footer, focus states; respect the brand colours; keep contrast ≥ 4.5:1; max ~220 lines of CSS."""


def _dom_sample(live_html: str, limit: int = 9000) -> str:
    t = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", "", live_html, flags=re.S | re.I)
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    m = re.search(r"<body[^>]*>(.*)", t, re.S | re.I)
    body = m.group(1) if m else t
    body = re.sub(r"\s+", " ", body)
    body = re.sub(r">([^<]{80})[^<]*<", r">\1…<", body)      # long text nodes trimmed, tags kept
    return body[:limit]


def generate_css(brief: dict, manifest: dict, actions: list[dict], critique: str, base_png: Path, live_html: str, d: Path, round_no: int, retries: int = 2) -> tuple[str, list[dict]]:
    files = [f"{(d / a['output']).resolve().as_uri()} ({a.get('desc', '')[:60]})" for a in actions if a.get("output") and a["tool"] in ("blender_render", "photo")]
    direction = "\n".join(f"- {a['tool']}: {a.get('desc') or json.dumps(a.get('params'), ensure_ascii=False)} — because {a.get('why', '')}" for a in actions) or "- none"
    compact, last = "", "unknown"
    for _ in range(retries + 1):
        user = [{"type": "text", "text": (f"Round {round_no}. Brand: {json.dumps(brief['brand'])}. Audience: {brief.get('audience')}. Primary task: {brief.get('primary_task')}. Tone: {brief.get('tone')}. Page class: {brief.get('page_class')}.\n"
                                           f"OUTLINE: {json.dumps(manifest.get('outline', {}), ensure_ascii=False)[:1200]}\n\nDOM SAMPLE (real selectors):\n{_dom_sample(live_html)}\n\n"
                                           + (f"Image files you may use as background-image (absolute URLs):\n" + "\n".join(files) + "\n\n" if files else "")
                                           + f"ART DIRECTION THIS ROUND:\n{direction}\n\n{critique}{compact}")}, _img(base_png)]
        r = _client().chat.completions.create(model=MODEL, messages=[{"role": "system", "content": CSS_RULES}, {"role": "user", "content": user}], temperature=0.5, max_tokens=9000)
        ch = r.choices[0]
        text = ch.message.content or ""
        m = re.search(r"<!--\s*CHANGES:\s*(\[.*?\])\s*-->", text, re.S)
        try:
            changes = json.loads(m.group(1)) if m else []
        except json.JSONDecodeError:
            changes = []
        sm = re.search(r"<style[^>]*>(.*?)</style>", text, re.S | re.I)
        css = sm.group(1) if sm else re.sub(r"<!--.*?-->", "", text, flags=re.S).strip().strip("`")
        if ch.finish_reason == "length" or len(css) < 80:
            last = f"no usable stylesheet ({len(css)} chars)"
            compact = "\n\nIMPORTANT: answer with the CHANGES line and ONE complete <style> element under 220 lines."
            continue
        if re.search(r"content\s*:\s*[\"'][^\"']*[A-Za-z0-9]{3,}", css):
            last = "stylesheet injects text"
            compact = "\n\nIMPORTANT: no content: text injection."
            continue
        if re.search(r"display\s*:\s*none", css) and re.search(r"(^|[\s,}])(a|p|li|td|tr|table|img|h[1-6]|span|body|html)\s*\{[^}]*display\s*:\s*none", css):
            last = "stylesheet hides content elements"
            compact = "\n\nIMPORTANT: never display:none on content elements."
            continue
        tag = f'<style id="neuromuse-evolve">\n{css}\n</style>'
        html = live_html.replace("</body>", tag + "\n</body>", 1) if "</body>" in live_html else live_html + tag
        return html, changes
    raise GenerationError(f"round {round_no}: {last}")


STOP = set("The And For With From Your You Our About Contact Home Live Open Now New Free Pro Team Plan Plans Learn More Get Start Book See View All Read Sign Log In Up Menu Close Next Prev Back Top Studio Service Services Projects Project Work Works Blog News Shop Store Price Pricing Rooms Room Search Guests Check Email Subscribe Submit Apply Share Save Edit Terms Privacy Policy Cookie Cookies Rights Reserved Copyright Inc LLC Ltd Co KST UTC AM PM Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May June July August September October November December Series Seed Round Beta Alpha Enterprise Growth Starter Business Basic Standard Premium Ultimate Max Mini Lite Plus Photo Image Credit Credits License Licence Wikimedia Commons Render Blender Hero Section Footer Header Nav Menu Overview Features Feature FAQ Faq Step Steps Why How What When Where Who".split())
try:
    _WORDS = {w.strip().lower() for w in open("/usr/share/dict/words", encoding="utf-8", errors="ignore")}
except OSError:
    _WORDS = set()


def _body_text(html: str) -> str:
    """Visible text of a candidate: scripts, styles, comments, tags and attributes removed."""
    import html as _h
    t = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", _h.unescape(t))


def claim_check(html: str, allowed_text: str) -> list[str]:
    """Muse reads the candidate's visible copy against the live page text and lists invented FACTUAL claims
    (dates, counts, founders, status like 'live'/'open to all', credentials, awards, guarantees). Slogans and tightened
    rephrasings of existing copy are allowed."""
    text = re.sub(r"assets/\S+", " ", _body_text(html))[:9000]
    prompt = ("LIVE PAGE TEXT (the only source of truth):\n" + allowed_text[:80000] +
              "\n\nCANDIDATE PAGE TEXT:\n" + text +
              "\n\nList every sentence or label in the CANDIDATE that asserts a FACT not supported by the live page text: founding dates, 'EST.', counts "
              "('3 founders', '700+ sites'), status claims ('live', 'open to all', 'trusted by', 'official'), credentials, awards, guarantees, partnerships, locations, prices, "
              "or attributions. Do NOT list pure slogans, section labels, calls to action, or rephrasings of claims the live text already makes. Be conservative: list a string ONLY if you are sure the live text does not support it — names, descriptions and numbers that appear anywhere in the live text are supported. "
              "Reply ONLY with a JSON array of the offending strings (empty array if none).")
    try:
        r = _client().chat.completions.create(model=MODEL, temperature=0, max_tokens=3000, extra_body={"reasoning_effort": "low"}, messages=[{"role": "user", "content": prompt}])
        m = re.search(r"\[.*?\]", r.choices[0].message.content or "", re.S)
        return [str(x)[:120] for x in json.loads(m.group(0))][:10] if m else []
    except Exception:  # noqa: BLE001
        return []


def fact_check(html: str, allowed_text: str) -> dict:
    """Every number and every proper name in the candidate must exist in the live page's text (copy + DOM outline)."""
    text = re.sub(r"assets/\S+", " ", _body_text(html))     # file names in a credit line are not claims
    allowed = allowed_text.lower()
    allowed_nums = set(re.findall(r"\d[\d,.]*", allowed_text))
    allowed_nums_norm = {n.replace(",", "") for n in allowed_nums}
    bad_nums = []
    for n in sorted(set(re.findall(r"\d[\d,.]*\d|\d", text))):
        if n in allowed_nums or n.replace(",", "") in allowed_nums_norm:
            continue
        if re.fullmatch(r"\d{1,2}", n):       # small ordinals / step numbers are layout, not claims
            continue
        bad_nums.append(n)
    bad_names = []
    for w in sorted(set(re.findall(r"\b[A-Z][A-Za-z0-9&+]{2,}\b", text))):
        lw = w.lower()
        if w in STOP or w.capitalize() in STOP or lw in allowed or len(w) < 4:
            continue
        stems = {lw, lw.rstrip("s"), lw[:-2], lw.replace("ies", "y")}
        for suf in ("ed", "d", "ing", "ly", "er", "ers", "ment", "ments", "tion", "ness"):
            if lw.endswith(suf):
                stems.add(lw[: -len(suf)]); stems.add(lw[: -len(suf)] + "e")
        if any(st in _WORDS for st in stems if len(st) >= 3):
            continue   # ordinary English words set in caps (BRANDS, CASES, CURATED) are typography, not claims
        bad_names.append(w)
    if bad_names:   # second pass: only proper nouns (brands, people, places, products) count as invented facts
        try:
            r = _client().chat.completions.create(model=MODEL, temperature=0, max_tokens=2500, extra_body={"reasoning_effort": "low"},
                                                  messages=[{"role": "user", "content": "Which of these tokens are PROPER NOUNS naming a brand, company, person, place or product (not ordinary English words, section labels or design jargon)? "
                                                             f"Tokens: {bad_names}\nReply ONLY with a JSON array of the proper nouns."}])
            content = r.choices[0].message.content or ""
            m = re.search(r"\[.*?\]", content, re.S)
            if m:   # classifier answered: only its proper nouns survive; a silent/garbled answer keeps the heuristic list
                keep = {str(k).lower() for k in json.loads(m.group(0))}
                bad_names = [w for w in bad_names if w.lower() in keep]
            else:
                print(f"    fact_check: classifier gave no list (finish={r.choices[0].finish_reason}); keeping heuristic names")
        except Exception:  # noqa: BLE001
            pass
    return {"numbers": bad_nums[:12], "names": bad_names[:12], "ok": not bad_nums and not bad_names}


def fidelity(html: str, png: Path, brief: dict, live_png: Path | None = None, first_png: Path | None = None) -> dict:
    """Hard check: every must_keep asset path is referenced. Vision check: must_keep elements visible and legible."""
    missing_paths = [k["ref"] for k in brief["must_keep"] if k.get("kind") in ("logo", "asset", "widget") and k.get("ref", "").startswith("assets/") and k["ref"] not in html]
    body = re.sub(r"[^a-z0-9가-힣]+", " ", _body_text(html).lower())
    missing_text = []
    visual = []
    for k in brief["must_keep"]:
        ref = (k.get("ref") or "").strip()
        if k.get("kind") in ("logo", "asset", "widget") or ref.startswith("assets/"):
            visual.append(k)
            continue
        probe = re.sub(r"[^a-z0-9가-힣]+", " ", ref.lower()).strip()
        words = probe.split()
        if not words:
            continue
        head = " ".join(words[:6])      # the first six words of a long list / sentence are enough to prove the block is there
        if head not in body and not all(w in body for w in words[:12]):
            missing_text.append(k.get("id"))
    prompt = ("Image 1 is the candidate FULL page; image 2 is the candidate FIRST SCREEN; image 3 is the LIVE page's first screen. "
              "(a) Check the candidate against the MUST_KEEP list (visual items only): present and legible? "
              "(b) DEFECTS: list any overlapping text, clipped or cut-off text, garbled characters, elements covering other elements, or empty broken image boxes. Also a defect: a stock/CC photo of a person (not one of the site's own harvested portraits) presented as the site's team, founders, staff, customers, speakers or testimonial, or with a name, role or quote beside it. "
              f"(c) DENSITY: primary task is '{brief.get('primary_task', '')}'. Count the distinct task items (stories, links, sections, versions, products) in the candidate's first screen and in the live first screen. density_ok is false only if the candidate shows fewer than 60% of the live count or drops a whole category of items; larger, more legible type that still shows most of the list is fine. "
              f"MUST_KEEP: {json.dumps(visual, ensure_ascii=False)}\nReply ONLY with JSON: {{\"missing\": [ids], \"illegible\": [ids], \"defects\": [\"...\"], \"density_ok\": true|false, \"density_note\": \"...\"}}")
    content = [{"type": "text", "text": prompt}, _img(png)]
    if first_png and Path(first_png).exists():
        content.append(_img(first_png))
    if live_png and Path(live_png).exists():
        content.append(_img(live_png))
    try:
        r = _client().chat.completions.create(model=MODEL, temperature=0, max_tokens=3000, extra_body={"reasoning_effort": "low"}, messages=[{"role": "user", "content": content}])
        v = _json(r.choices[0].message.content or "")
    except Exception:  # noqa: BLE001
        v = {}
    missing = list(dict.fromkeys(list(v.get("missing", [])) + missing_text))
    defects = [str(x) for x in (v.get("defects") or []) if str(x).strip() and str(x).strip().lower() not in ("none", "no", "n/a")]
    density_ok = bool(v.get("density_ok", True))
    return {"missing_paths": missing_paths, "missing": missing, "missing_text": missing_text, "illegible": v.get("illegible", []), "defects": defects,
            "density_ok": density_ok, "density_note": v.get("density_note", ""), "ok": not missing_paths and not missing and not defects and density_ok}


def score(png: Path, item_id: str, brief_text: str, kind: str) -> dict:
    sc = _score_with_retry(png, item_id, brief_text, JUDGE_W)
    ev = _eval(item_id)
    crit = read_brain(ev, kind)
    return {"ui_score": sc.ui_score, "heads": {k: v for k, v in sc.heads.items() if k != "judge"}, "judge": sc.heads.get("judge", {}),
            "brain_only": round(sum(0.5 * (sc.heads[h]["percentile"] / 100) for h in ("aesthetic", "attention") if h in sc.heads), 3),
            "critique": crit.to_dict() | {"prompt_block": crit.prompt_block}}


@app.command()
def run(source: str = typer.Argument(...), name: str = typer.Option(""), rounds: int = typer.Option(3), kind: str = typer.Option("landing"),
        out: Path = typer.Option(Path("results/showcase/evolve")), mode: str = typer.Option("auto", help="auto | rebuild | css (auto: css for utility pages)")):
    slug = name or re.sub(r"[^a-z0-9]+", "-", re.sub(r"^https?://(www\.)?", "", source).lower()).strip("-")[:40]
    d = out / slug
    d.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%H%M%S")
    print(f"▶ {source} → {d}")
    manifest = harvest(source, d)
    copy = _page_copy(source)
    (d / "copy.txt").write_text(copy, encoding="utf-8")
    brief = intent_brief(source, d, copy, manifest)
    (d / "brief.json").write_text(json.dumps(brief, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  harvested {len(manifest['images'])} images, {len(manifest.get('widgets', []))} widgets, logo {manifest.get('logo')} · lang {brief['lang']} · must_keep {len(brief['must_keep'])} · missing imagery {[m.get('what') for m in brief.get('missing_imagery', [])][:3]}")
    live_html = (d / "live.html").read_text(encoding="utf-8") if (d / "live.html").exists() else ""
    mode_css = bool(live_html) and (mode == "css" or (mode == "auto" and brief.get("page_class") == "utility"))
    brief["_mode_css"] = mode_css
    print(f"  mode: {'css (live DOM + brain-directed stylesheet)' if mode_css else 'rebuild'} · page_class {brief.get('page_class')}")
    brief_text = (f"Evolve {source} for {brief.get('audience', 'its visitors')}: primary task '{brief.get('primary_task', '')}', tone {brief.get('tone', '')}. "
                  "Penalise any information or element present on the live page that is missing here.")
    allowed_text = copy + " " + (manifest.get("text") or "") + " " + json.dumps(manifest.get("outline", {}), ensure_ascii=False)
    brief["_allowed_text"] = allowed_text + " " + " ".join(i.get("alt", "") for i in manifest["images"]) + " " + brief["brand"].get("text", "")
    s0 = score(d / "before.png", f"ev_{stamp}_{slug}_r0", brief_text, kind)
    steps = [{"round": 0, "png": str(d / "before.png"), "html": None, "accepted": True, **s0}]
    best = steps[0]
    trail: list[dict] = []
    print(f"  r0 live: ui {s0['ui_score']:.3f} · brain {s0['brain_only']:.3f} · judge {s0['judge'].get('judge_score', 0):.2f} · {' / '.join(s0['critique']['diagnosis'][:2])}")
    for r in range(1, rounds + 1):
        critique = best["critique"]["prompt_block"]
        direction = art_direct(brief, critique, best["judge"].get("reason", ""), manifest, trail, r)
        actions = [run_tool(a, brief, d, r, i) for i, a in enumerate(direction.get("actions", [])[:2])]
        for a in actions:
            print(f"  r{r} tool {a['tool']}: {a.get('desc') or a.get('error') or ''}"[:160])
        try:
            if mode_css:
                html, changes = generate_css(brief, manifest, actions, critique, Path(best["png"]), live_html, d, r)
            else:
                html, changes = generate(brief, copy, manifest, actions, critique, Path(best["png"]), r)
        except GenerationError as e:
            print(f"  r{r} skipped: {e}")
            continue
        (d / f"r{r}.html").write_text(html, encoding="utf-8")
        render(d / f"r{r}.html", d / f"r{r}.png")
        render(d / f"r{r}.html", d / f"r{r}_full.png", height=2600)
        fid = fidelity(html, d / f"r{r}_full.png", brief, live_png=d / "before.png", first_png=d / f"r{r}.png")
        if mode_css:   # the live DOM references its own asset URLs, not our harvested copies
            fid["missing_paths"] = []
            fid["ok"] = not fid["missing"] and not fid["defects"] and fid["density_ok"]
        credits = " ".join(json.dumps(a.get("credit") or {}, ensure_ascii=False) for a in actions)   # CC photo title/author/licence are real facts
        fc = fact_check(html, allowed_text + " " + credits)
        if mode_css:   # the DOM is untouched: nothing can be invented
            fc = {"numbers": [], "names": [], "claims": [], "ok": True}
        else:
            fc["claims"] = claim_check(html, allowed_text + " " + credits) if fc["ok"] else []
            fc["ok"] = fc["ok"] and not fc["claims"]
        fid["facts"] = fc
        s = score(d / f"r{r}.png", f"ev_{stamp}_{slug}_r{r}", brief_text, kind)
        if not fc["ok"]:
            s["critique"]["prompt_block"] += (f"\nHARD REJECT — INVENTED FACTS: numbers {fc['numbers']}, names {fc['names']} and claims {fc.get('claims', [])} do not exist on the live page. "
                                              "Remove them; if a slot needs proof the page does not have, leave the slot out.")
        if not fid["ok"]:
            s["critique"]["prompt_block"] += (f"\nHARD REJECT — FIDELITY: missing {fid['missing']}, defects {fid['defects']}, density_ok {fid['density_ok']} ({fid.get('density_note', '')}). "
                                              "Keep every must_keep item, fix overlaps/clipping, and keep at least the live page's first-screen density.")
        pv = judge_pair(d / f"r{r}.png", Path(best["png"]), brief_text) if (fid["ok"] and fc["ok"]) else None   # blind verdict vs the current best, both orders
        s["p_vs_best"] = None if pv is None else pv["p_first"]
        s["p_vs_best_reason"] = None if pv is None else pv["reason"]
        tie_break = pv is not None and abs(pv["p_first"] - 0.5) < 1e-6 and s["ui_score"] > best["ui_score"] + 0.02   # orders disagree → brain + judge score decides
        accepted = fid["ok"] and fc["ok"] and pv is not None and (pv["p_first"] >= 0.55 or tie_break)
        step = {"round": r, "png": str(d / f"r{r}.png"), "html": str(d / f"r{r}.html"), "changes": changes, "actions": actions, "fidelity": fid, "accepted": accepted, "based_on": best["round"], **s}
        steps.append(step)
        for a in actions:
            t = {"round": r, "tool": a["tool"], "why": a.get("why", ""), "critique_line": a.get("critique_line", ""), "desc": a.get("desc", ""),
                 "brain_delta": round(s["brain_only"] - best["brain_only"], 3), "judge_delta": round(s["judge"].get("judge_score", 0) - best["judge"].get("judge_score", 0), 3),
                 "score_before": best["ui_score"], "score_after": s["ui_score"], "accepted": accepted, "fidelity": {k: fid[k] for k in ("missing_paths", "missing")}}
            if a.get("output") and (d / a["output"]).exists():
                t["thumb"] = str(Path("trail") / f"r{r}_{a['tool']}{'.svg' if a['output'].lower().endswith('.svg') else '.jpg'}")
                thumb(d / a["output"], d / t["thumb"])
            t["page_thumb"] = str(Path("trail") / f"r{r}_page.jpg")
            thumb(d / f"r{r}.png", d / t["page_thumb"])
            trail.append(t)
        if accepted:
            best = step
        print(f"  r{r}: ui {s['ui_score']:.3f} · brain {s['brain_only']:.3f} · judge {s['judge'].get('judge_score', 0):.2f} · fidelity {'ok' if fid['ok'] else 'MISSING ' + str(fid['missing'] or fid['missing_paths'])} · facts {'ok' if fc['ok'] else 'INVENTED ' + str((fc['numbers'] + fc['names'])[:6])} · {'ACCEPT' if accepted else 'reject'}")
        print(f"      fidelity: defects {fid['defects']} · density_ok {fid['density_ok']} · blind P(vs best) {s.get('p_vs_best')}")
    pair = None
    if best["round"] > 0:
        render(d / f"r{best['round']}.html", d / "after@2x.png", scale=2)
        render(d / f"r{best['round']}.html", d / "after_full.png", height=2600)
        shutil.copy(best["png"], d / "after.png")
        (d / "BEST.html").write_text(Path(best["html"]).read_text(encoding="utf-8"), encoding="utf-8")
        pair = judge_pair(d / "after.png", d / "before.png", brief_text)
    rep = {"source": source, "brief": brief, "brief_text": brief_text, "manifest": {k: v for k, v in manifest.items() if k != "outline"}, "steps": steps, "trail": trail, "best_round": best["round"], "pairwise_after_vs_before": pair}
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
    trail = "".join(
        f"<div class=tr><div class=k>round {t['round']} · brain said</div><div class=q>“{e(t.get('critique_line') or '')[:140]}”</div>"
        f"<div class=k>agent chose</div><div class=t2>{e(t['tool'])} — {e(t.get('desc') or '')[:120]}</div>"
        + (f"<img src='{t['thumb']}'>" if t.get("thumb") else "") + f"<img src='{t['page_thumb']}'>"
        f"<div class=d>brain {t['brain_delta']:+.2f} · judge {t['judge_delta']:+.2f} · {'kept' if t['accepted'] else 'rejected'}{' · fidelity: missing ' + e(str(t['fidelity']['missing'])) if t['fidelity']['missing'] or t['fidelity']['missing_paths'] else ''}</div></div>"
        for t in rep["trail"])
    after_img = "after_full.png" if (d / "after_full.png").exists() else f"r{b['round']}.png"
    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8><title>NeuroMuse evolve · {e(rep['source'])}</title>
<style>body{{font-family:-apple-system,Pretendard,sans-serif;background:#0b0b0f;color:#eee;margin:0;padding:32px}}h1{{font-size:20px;font-weight:600}}h2{{font-size:15px;margin:26px 0 8px}}
.row{{display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:start}}.card{{background:#15151b;border:1px solid #23232b;border-radius:14px;overflow:hidden}}.card img{{width:100%;display:block}}
.t{{padding:10px 14px;font-weight:600;font-size:13px;color:#ffb38a}}.m{{padding:8px 14px 12px;font-size:12.5px;color:#ccc;line-height:1.5}}.k{{color:#8b8b96;font-size:11px;letter-spacing:.08em;text-transform:uppercase}}
.big{{font-size:26px;font-weight:700;color:#7ee787}}.strip{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px}}.tr{{background:#15151b;border:1px solid #23232b;border-radius:12px;padding:12px;font-size:12.5px;line-height:1.5}}
.tr img{{width:100%;border-radius:8px;margin:6px 0}}.q{{color:#f3f3f5;margin-bottom:6px}}.t2{{color:#ffb38a;margin-bottom:4px}}.d{{color:#9a9aa6}}</style></head><body>
<h1>The brain directs, the agent crafts — {e(rep['source'])}</h1>
<div class=k style="text-transform:none;font-size:13px;letter-spacing:0">{e(rep['brief_text'])} · design language {e(rep['brief'].get('lang', ''))}</div>
<div class=big>ui_score {o['ui_score']:.3f} → {b['ui_score']:.3f}{' · blind judge P(after better) ' + format(pw['p_first'], '.2f') if pw else ' · live page kept'}</div>
<div class=row><div class=card><div class=t>BEFORE · live site (full page, 1280 wide)</div><img src='before_full.png'><div class=m>brain {o['brain_only']:.3f} · judge {o['judge'].get('judge_score', 0):.2f}<br><span class=k style="text-transform:none;letter-spacing:0">{e(' / '.join(o['critique']['diagnosis'][:2]))}</span></div></div>
<div class=card><div class=t>AFTER · round {b['round']} (full page, 1280 wide)</div><img src='{after_img}'><div class=m>brain {b['brain_only']:.3f} · judge {b['judge'].get('judge_score', 0):.2f}</div></div></div>
<h2>Decision trail — the brain said → the agent did → what moved</h2><div class=strip>{trail or '<div class=tr>no rounds</div>'}</div>
<h2>Must keep (fidelity gate)</h2><ul style="font-size:13px">{''.join(f"<li>{e(k.get('kind', ''))}: {e(str(k.get('ref', '')))[:90]}</li>" for k in rep['brief']['must_keep'])}</ul>
</body></html>"""
    (d / "index.html").write_text(page, encoding="utf-8")
    return d / "index.html"


if __name__ == "__main__":
    app()
