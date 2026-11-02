"""Short ad clips: Muse writes a 6-second CSS-animated HTML ad, headless Chrome samples it frame by
frame under virtual time, ffmpeg makes an mp4, TRIBE v2 watches it (1 Hz cortex), and the brain
critique reads the *time course* (hook in the first 2 s, hold, CTA) — the one thing a still image
can never tell you.

    uv run python -m brainsense.showcase.video render demo.html out.mp4      # frames → mp4
    uv run python -m brainsense.showcase.video score out.mp4 --brief "..."    # TRIBE time course + hook critique
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import typer

from ..loop.generate import GenerationError, _body_text, _client, _extract_html
from ..loop.render import chrome_path
from .skills import GROUP_KO, read_brain

app = typer.Typer(add_completion=False)
SERVER = os.environ.get("BRAINSENSE_SERVER_URL", "http://localhost:8000").rstrip("/")

AD_SYSTEM = """You are a senior motion designer. You write a single-file HTML ad that plays as a 6-second
looping video at 1280x720: pure CSS keyframe animations (no JavaScript, no external assets except
Google Fonts), all text real (no lorem ipsum). Structure the 6 seconds as scenes using animation-delay:
0-2 s HOOK (the single strongest visual, big, immediate), 2-4 s PRODUCT/BENEFIT, 4-6 s OFFER + CTA.
Use transforms/opacity for motion, keep contrast high, one focal element per moment. Output ONLY the HTML."""


def render_video(html: str, out_mp4: Path, seconds: float = 6.0, fps: int = 6, width: int = 1280,
                 height: int = 720, parallel: int = 4) -> Path:
    """Sample the page at t = 0, 1/fps, 2/fps … under Chrome's virtual time and encode with a silent track
    (TRIBE's audio extractor expects one)."""
    out_mp4 = Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    n = int(seconds * fps)
    with tempfile.TemporaryDirectory() as d:
        def shot(i: int) -> None:
            t_ms = int(i * 1000 / fps)
            # Chrome's virtual time does not drive CSS animations reliably, so each frame is a page that
            # seeks every animation (Web Animations API) to t and pauses it before the screenshot.
            seek = ("<script>function __bsSeek(){try{document.getAnimations({subtree:true}).forEach(a=>{"
                    f"a.pause();a.currentTime={t_ms};}});}}catch(e){{}}}}"
                    "addEventListener('load',()=>{__bsSeek();requestAnimationFrame(__bsSeek);});</script>")
            page = Path(d) / f"ad{i}.html"
            page.write_text(html.replace("</body>", seek + "</body>", 1) if "</body>" in html else html + seek, encoding="utf-8")
            prof = Path(d) / f"p{i}"
            subprocess.run([chrome_path(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                            "--no-default-browser-check", f"--user-data-dir={prof}", f"--window-size={width},{height}",
                            "--force-device-scale-factor=1", "--virtual-time-budget=2500",
                            f"--screenshot={d}/f{i:03d}.png", page.as_uri()], check=True, capture_output=True, timeout=90)

        with ThreadPoolExecutor(max_workers=parallel) as ex:
            list(ex.map(shot, range(n)))
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(fps), "-i", f"{d}/f%03d.png",
                        "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", str(seconds),
                        "-vf", "scale=1280:-2,format=yuv420p", "-c:v", "libx264", "-c:a", "aac", "-shortest",
                        str(out_mp4)], check=True)
    return out_mp4


def contact_sheet(mp4: Path, out_png: Path, cols: int = 3) -> Path:
    """0 s / 2.5 s / 5 s frames side by side — what the multimodal judge sees."""
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(mp4), "-vf",
                    f"fps=1/2.5,scale=640:-1,tile={cols}x1", "-frames:v", "1", str(out_png)], check=True)
    return out_png


def score_video(mp4: Path, item_id: str) -> dict:
    data = base64.b64encode(Path(mp4).read_bytes()).decode()
    with httpx.Client(timeout=900) as c:
        r = c.post(f"{SERVER}/analyze", json={"video_b64": data, "filename": Path(mp4).name, "item_id": item_id})
        r.raise_for_status()
        ev = c.get(f"{SERVER}/eval/{item_id}")
        ev.raise_for_status()
    ev = ev.json()
    crit = read_brain(ev, "video")
    ts = ev.get("roi_ts") or {}
    att = ts.get("attention_dorsal") or []
    vis = ts.get("visual_early") or []
    # hook = how much of the clip's attention drive lands in the first 2 s; hold = late/early ratio
    hook = (sum(att[:2]) / 2 - sum(att) / max(1, len(att))) if att else 0.0
    peak_s = (max(range(len(att)), key=lambda i: att[i]) + 1) if att else None
    heads = {k: {x: v[x] for x in ("score", "percentile", "confidence")} for k, v in (ev.get("heads") or {}).items()
             if isinstance(v, dict) and "percentile" in v}
    return {"item_id": item_id, "heads": heads, "roi_ts": ts, "hook_delta": round(hook, 3), "attention_peak_s": peak_s,
            "visual_peak_s": (max(range(len(vis)), key=lambda i: vis[i]) + 1) if vis else None,
            "critique": crit.to_dict() | {"prompt_block": crit.prompt_block}}


def generate_ad(brief: str, critique: str, variant: int, temperature: float = 0.9, max_tokens: int = 16000, retries: int = 2) -> str:
    compact, last = "", "unknown"
    for _ in range(retries + 1):
        user = (f"Brief: {brief}\n\nThis is variant #{variant}: a distinctly different concept, palette and motion from "
                f"other variants.{(chr(10) * 2 + critique) if critique else ''}{compact}")
        r = _client().chat.completions.create(model=os.environ.get("BRAINSENSE_LLM_MODEL", "muse-spark-1.3"),
                                              messages=[{"role": "system", "content": AD_SYSTEM}, {"role": "user", "content": user}],
                                              temperature=temperature, max_tokens=max_tokens)
        ch = r.choices[0]
        html = _extract_html(ch.message.content or "")
        if ch.finish_reason == "length" or "</html>" not in html.lower():
            last = f"truncated ({len(html)} chars)"
            compact = "\n\nIMPORTANT: your previous answer was cut off. Keep the whole document under 220 lines."
            continue
        if len(_body_text(html)) < 60 or "@keyframes" not in html:
            last = "no visible content or no @keyframes"
            compact = "\n\nIMPORTANT: the previous answer had no visible content/animation. Real headline, product, CTA and @keyframes are required."
            continue
        return html
    raise GenerationError(f"ad variant {variant}: {last}")


@app.command()
def render(html_file: Path, out: Path, fps: int = 6):
    t = time.time()
    p = render_video(Path(html_file).read_text(encoding="utf-8"), out, fps=fps)
    print(f"{p} ({time.time() - t:.1f}s)")


@app.command()
def score(mp4: Path, item_id: str = typer.Option("", help="defaults to the file stem")):
    res = score_video(mp4, item_id or f"vid_{Path(mp4).stem}_{int(time.time())}")
    print(json.dumps({k: v for k, v in res.items() if k != "roi_ts"}, ensure_ascii=False, indent=1))
    for g, v in res["roi_ts"].items():
        print(f"{GROUP_KO.get(g, g):>18}: " + " ".join(f"{x:+.2f}" for x in v))


if __name__ == "__main__":
    app()
