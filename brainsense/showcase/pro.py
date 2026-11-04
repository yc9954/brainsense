"""Professional pairs: plain one-shot Muse vs the brain loop given what real design teams use —
a reference design language per brief (type pairing, grid, palette rule, hero pattern), CC photography
fetched from Wikimedia Commons and passed through the multimodal photo gate, and the cortex critique
deciding which rules to apply each round. Blind pairwise verdict, 1280×800 @2× first screens plus a
full-page capture of every finalist. Same summary.json schema as ab.py (report / vote / gallery work).

    uv run python -m brainsense.showcase.pro --rounds 3 --variants 2 --name pro-1
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import typer
from rich import print
from rich.markup import escape

from ..loop.generate import SYSTEM as BASE_SYSTEM
from ..loop.generate import GenerationError, _body_text, _client, _extract_html
from ..loop.render import chrome_path
from .ab import _brain_critique, _eval, _score_with_retry
from .harness import photo_gate, source_images
from .pairwise import judge_pair
from .skills import read_brain

app = typer.Typer(add_completion=False)
MODEL = os.environ.get("BRAINSENSE_LLM_MODEL", "muse-spark-1.3")

DESIGN = {
    "saas": ("Reference design language — modern SaaS (Linear / Stripe / Vercel): Inter or Geist from Google Fonts; 12-column grid on an 8-pt spacing scale; "
             "one hero product frame (a UI mock built from real HTML/CSS: cards, tables, charts as divs) tilted or framed on a muted field; neutrals (#0B0B0F / #F6F6F7) + ONE accent; "
             "56–72 px tracking-tight headline, 18 px lede, primary + ghost button; a social-proof strip (6 grey logotypes set in text), feature bento of 3–4 cells with 1-line copy; no gradients blobs, no emoji, no stock-icon clip-art."),
    "editorial": ("Reference design language — editorial / architecture studio (Dezeen, Norm Architects, Studio Olafur): Fraunces or Playfair Display for a 3–5 word display headline + a grotesk (Inter) for body; "
                  "full-bleed or 2/3-width photography with generous whitespace, hairline rules, small caps labels, a numbered project index; black on off-white, no accent colour except one; typographic hierarchy does the work."),
    "luxury": ("Reference design language — premium DTC beauty (Aesop, Glossier, Augustinus Bader): warm off-white (#F4EFE8) or deep ink, serif display (Cormorant Garamond / Fraunces) + a quiet sans; "
               "product photo isolated or on skin with a soft gradient overlay; 3-word headline, 1 sentence of benefit with a clinical number, one CTA, ingredient strip; nothing cute, no badges screaming discounts (a discreet 'launch offer' line only)."),
    "hospitality": ("Reference design language — boutique hotel (Aman, Ace, The Hoxton): full-bleed photography with a dark gradient scrim, elegant serif headline, a compact booking bar (dates / guests / search) pinned in the hero, "
                    "warm palette from the photo, a 3-column strip of rooms with price-from; no icons soup."),
    "brutalist": ("Reference design language — modern changelog / developer tool (Linear changelog, Raycast, Vercel): Space Grotesk or Geist Mono labels + Inter; black/white with one accent; oversized version number, hairline rules, "
                  "dated entries in a two-column timeline, inline code chips, keyboard-key styling; dense but calm."),
}

BRIEFS: dict[str, dict] = {
    "fintech_landing": {"kind": "landing", "lang": "saas", "brief": "Landing page first screen for a Series-A fintech, 'Ledger' — a treasury platform that lets finance teams see every bank account, card and payout in one place. Audience: CFOs and controllers at 50–500 person companies. Must feel trustworthy, precise, fast.",
                        "photos": ["modern glass office building", "finance professional portrait office", "city skyline dusk"]},
    "architecture_portfolio": {"kind": "landing", "lang": "editorial", "brief": "Portfolio homepage first screen for 'Atelier Norr', a Copenhagen architecture studio known for quiet concrete houses and timber interiors. Show the studio's taste in one screen; a project index and a 'Studio' link.",
                               "photos": ["modern concrete house architecture exterior", "minimalist timber interior daylight", "architecture model white"]},
    "skincare_launch": {"kind": "ad", "lang": "luxury", "brief": "Launch page first screen for 'Noon', a vitamin-C + ceramide serum from a premium DTC skincare brand. One headline, one clinical claim (e.g. 94% saw brighter skin in 4 weeks), launch offer, 'Shop the serum' CTA.",
                        "photos": ["serum bottle cosmetic studio photography", "woman face natural light skin portrait", "botanical leaf macro"]},
    "analytics_pricing": {"kind": "app", "lang": "saas", "brief": "Pricing page first screen for 'Prism', a B2B product-analytics platform. Three tiers: Starter $0, Growth $249/mo (highlighted), Enterprise (talk to sales); annual toggle; trust row (SOC 2, GDPR, 99.9% SLA); logos of 6 customers.",
                          "photos": ["data analytics dashboard screen", "team meeting modern office"]},
    "hotel_booking": {"kind": "landing", "lang": "hospitality", "brief": "Booking page first screen for 'Casa Mira', a 14-room boutique hotel on the Amalfi coast. Hero photography, a booking bar (check-in, check-out, guests, search), rooms from €320, one line of promise.",
                      "photos": ["boutique hotel room sea view interior", "amalfi coast terrace sunset", "hotel breakfast terrace mediterranean"]},
    "changelog": {"kind": "app", "lang": "brutalist", "brief": "Changelog first screen for 'Mono', a design tool for product teams. Latest release 2.14 with 3 entries (multiplayer cursors, variables panel, export to code), dates, a 'Subscribe' input, and the previous release collapsed.",
                  "photos": []},
}


def pro_system(lang: str, assets: list[dict]) -> str:
    photo_rules = ("\nPHOTOGRAPHY: use the local photos listed below as real imagery (<img src=\"assets/...\"> or CSS background-image: url('assets/...')) — crop with object-fit: cover, add a gradient scrim or duotone "
                   "(filter: grayscale(1) contrast(1.1) + mix-blend-mode / a tinted overlay) when text sits on them; never stretch; credit author + licence in a 10 px footer line.\n"
                   + "\n".join(f"- {a['path']} ({a['w']}×{a['h']}) — {a['title']} · {a['license']} · {a['author']}" for a in assets)) if assets else ""
    return (BASE_SYSTEM + "\n\n" + DESIGN[lang] + photo_rules +
            "\n\nQUALITY BAR: this must look like a page a senior designer at a funded company shipped — real copy, real hierarchy, consistent spacing, no placeholder blobs, no emoji, no clip-art.")


def generate_pro(brief: str, system: str, critique: str, variant: int, retries: int = 2) -> str:
    compact, last = "", "unknown"
    for _ in range(retries + 1):
        user = (f"Brief: {brief}\n\nThis is variant #{variant}: explore a distinctly different layout from other variants while staying inside the design language."
                f"{(chr(10) * 2 + critique) if critique else ''}{compact}")
        r = _client().chat.completions.create(model=MODEL, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], temperature=0.8, max_tokens=16000)
        ch = r.choices[0]
        html = _extract_html(ch.message.content or "")
        if ch.finish_reason == "length" or "</html>" not in html.lower():
            last = f"truncated ({len(html)} chars)"
            compact = "\n\nIMPORTANT: your previous answer was cut off. Keep the whole document under 280 lines."
            continue
        if len(_body_text(html)) < 120:
            last = "empty body"
            compact = "\n\nIMPORTANT: the previous answer had no visible content."
            continue
        return html
    raise GenerationError(f"variant {variant}: {last}")


def render(html_path: Path, out_png: Path, width: int = 1280, height: int = 800, scale: int = 1) -> Path:
    html_path, out_png = Path(html_path).resolve(), Path(out_png).resolve()
    html = html_path.read_text(encoding="utf-8")
    freeze = ("<style id=\"brainsense-freeze\">*,*::before,*::after{animation-duration:.01s!important;animation-delay:0s!important;"
              "animation-iteration-count:1!important;transition-duration:.01s!important}</style>")
    tmp = html_path.with_name(f"._render_{html_path.stem}_{scale}x.html")
    tmp.write_text(html.replace("</head>", freeze + "</head>", 1) if "</head>" in html else html + freeze, encoding="utf-8")
    with tempfile.TemporaryDirectory() as d:
        subprocess.run([chrome_path(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
                        f"--user-data-dir={d}/p", f"--window-size={width},{height}", f"--force-device-scale-factor={scale}",
                        "--virtual-time-budget=15000", "--allow-file-access-from-files", f"--screenshot={out_png}", tmp.as_uri()],
                       check=True, capture_output=True, timeout=120)
    tmp.unlink(missing_ok=True)
    return out_png


def fetch_photos(cfg: dict, bdir: Path) -> list[dict]:
    assets: list[dict] = []
    for q in cfg.get("photos", []):
        for a in source_images(q, bdir / "assets", n=3, width=1600):
            ok, why = photo_gate(bdir / a["path"], cfg["brief"], f"professional hero photography for: {q}")
            a["gate"] = why
            if ok:
                assets.append(a)
            else:
                (bdir / a["path"]).unlink(missing_ok=True)
            if sum(1 for x in assets if x["query"] == q) >= 2:
                break
    return assets


@app.command()
def run(rounds: int = typer.Option(3), variants: int = typer.Option(2), parallel: int = typer.Option(2), only: str = typer.Option(""),
        out: Path = typer.Option(Path("results/showcase")), name: str = typer.Option("pro-1"), judge_weight: float = typer.Option(0.5)):
    run_dir = out / name
    run_dir.mkdir(parents=True, exist_ok=True)
    summary: dict = {"rounds": rounds, "variants": variants, "briefs": {}}
    for key in [k for k in BRIEFS if not only or k in only.split(",")]:
        cfg = BRIEFS[key]
        bdir = run_dir / key
        (bdir / "assets").mkdir(parents=True, exist_ok=True)
        print(f"\n[bold cyan]▶ {key}[/] {escape(cfg['brief'][:110])}")
        assets = fetch_photos(cfg, bdir)
        print(f"  photos kept: {len(assets)} " + "; ".join(f"{a['title'][:28]} ({a['gate'][:5]})" for a in assets))
        results: dict = {}
        # --- arm 1: plain one-shot (the "just ask the model" baseline)
        html = generate_pro(cfg["brief"], BASE_SYSTEM, "", 1)
        (bdir / "oneshot_r1v1.html").write_text(html, encoding="utf-8")
        render(bdir / "oneshot_r1v1.html", bdir / "oneshot_r1v1.png")
        render(bdir / "oneshot_r1v1.html", bdir / "oneshot_r1v1@2x.png", scale=2)
        results["oneshot"] = {"arm": "oneshot", "best": "oneshot_r1v1", "best_png": str(bdir / "oneshot_r1v1.png"), "history": [{"arm": "oneshot", "round": 1, "variant": 1, "tag": "oneshot_r1v1", "png": str(bdir / "oneshot_r1v1.png"), "select_score": None}]}
        print("  oneshot rendered")
        # --- arm 2: brain loop with design language + photography + cortex critique
        system = pro_system(cfg["lang"], assets)
        history: list[dict] = []

        def one(r: int, v: int) -> dict | None:
            tag = f"brain_loop_r{r}v{v}"
            t0 = time.time()
            try:
                h = generate_pro(cfg["brief"], system, _brain_critique(history), v)
            except GenerationError as e:
                print(f"  {tag} skipped: {escape(str(e))}")
                return None
            (bdir / f"{tag}.html").write_text(h, encoding="utf-8")
            render(bdir / f"{tag}.html", bdir / f"{tag}.png")
            png = bdir / f"{tag}.png"          # keep paths relative so the gallery can link them
            sc = _score_with_retry(png, f"pro_{name}_{key}_{tag}", cfg["brief"], judge_weight)
            ev = _eval(f"pro_{name}_{key}_{tag}")
            crit = read_brain(ev, cfg["kind"])
            return {"arm": "brain_loop", "round": r, "variant": v, "tag": tag, "png": str(png), "select_score": sc.ui_score, "heads": sc.heads,
                    "explanation": sc.explanation, "critique": crit.to_dict() | {"prompt_block": crit.prompt_block}, "seconds": round(time.time() - t0, 1)}

        for r in range(1, rounds + 1):
            with ThreadPoolExecutor(max_workers=max(1, min(variants, parallel))) as ex:
                recs = [x for x in ex.map(lambda v: one(r, v), range(1, variants + 1)) if x]
            for rec in sorted(recs, key=lambda x: x["variant"]):
                history.append(rec)
                print(f"  {rec['tag']} select={rec['select_score']:.3f} ({rec['seconds']}s)")
        if not history:
            print("  brain arm produced nothing; skipping brief")
            continue
        best = max(history, key=lambda h: h["select_score"])
        render(bdir / f"{best['tag']}.html", bdir / f"{best['tag']}@2x.png", scale=2)
        for tag in ("oneshot_r1v1", best["tag"]):
            render(bdir / f"{tag}.html", bdir / f"{tag}_full.png", height=2600)
        results["brain_loop"] = {"arm": "brain_loop", "best": best["tag"], "best_png": best["png"], "history": history}
        final = {}
        for arm, res in results.items():
            sc = _score_with_retry(Path(res["best_png"]), f"final_{name}_{key}_{arm}", None, judge_weight)
            ev = _eval(f"final_{name}_{key}_{arm}")
            final[arm] = {"tag": res["best"], "png": res["best_png"], "png_2x": str(bdir / f"{res['best']}@2x.png"), "png_full": str(bdir / f"{res['best']}_full.png"),
                          "brain_ui_score": sc.ui_score, "heads": sc.heads, "critique": read_brain(ev, cfg["kind"]).to_dict()}
        pairs = {"brain_loop_vs_oneshot": judge_pair(Path(final["brain_loop"]["png"]), Path(final["oneshot"]["png"]), cfg["brief"])}
        summary["briefs"][key] = {"brief": cfg["brief"], "kind": cfg["kind"], "lang": cfg["lang"], "photos": assets, "arms": results, "final": final, "pairwise": pairs}
        (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  P(brain_loop better) = {pairs['brain_loop_vs_oneshot']['p_first']:.2f} · {escape(pairs['brain_loop_vs_oneshot']['reason'][:150])}")
    from .gallery import build
    build(run_dir)
    print(f"\ngallery → {run_dir / 'index.html'}")


if __name__ == "__main__":
    app()
