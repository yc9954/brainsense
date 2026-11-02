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

AD_LEN = 12.0   # seconds: TRIBE's hemodynamic lag (~5 s) flattens anything shorter
AD_SYSTEM = """You are a senior motion designer. You write a single-file HTML ad that plays as a 12-second
looping video at 1280x720: pure CSS keyframe animations (no JavaScript, no external assets except
Google Fonts), all text real (no lorem ipsum). Every animation must use `animation-duration: 12s` and
scenes are placed with keyframe percentages: 0-4 s HOOK (the single strongest visual, big, immediate),
4-8 s PRODUCT/BENEFIT, 8-12 s OFFER + CTA.
Use transforms/opacity for motion, keep contrast high, one focal element per moment. Output ONLY the HTML."""


def render_video(html: str, out_mp4: Path, seconds: float = AD_LEN, fps: int = 4, width: int = 1280,
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
    """Frames at 1 s, 5 s, 9 s (hook / product / CTA) side by side — what the multimodal judge sees."""
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", "1", "-i", str(mp4), "-vf",
                    f"fps=1/4,scale=640:-1,tile={cols}x1", "-frames:v", "1", str(out_png)], check=True)
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
    # hook = attention drive in the first third of the clip relative to the clip mean (positive = front-loaded)
    third = max(1, len(att) // 3)
    hook = (sum(att[:third]) / third - sum(att) / max(1, len(att))) if att else 0.0
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
def render(html_file: Path, out: Path, fps: int = 4):
    t = time.time()
    p = render_video(Path(html_file).read_text(encoding="utf-8"), out, fps=fps)
    print(f"{p} ({time.time() - t:.1f}s)")


@app.command()
def score(mp4: Path, item_id: str = typer.Option("", help="defaults to the file stem")):
    res = score_video(mp4, item_id or f"vid_{Path(mp4).stem}_{int(time.time())}")
    print(json.dumps({k: v for k, v in res.items() if k != "roi_ts"}, ensure_ascii=False, indent=1))
    for g, v in res["roi_ts"].items():
        print(f"{GROUP_KO.get(g, g):>18}: " + " ".join(f"{x:+.2f}" for x in v))



# ----------------------------------------------------------------------------------------------
# Ad-clip A/B: same three arms as the page showcase, but the artifact is a 12 s animated clip and the
# brain critique reads the time course (hook / hold / CTA) that no screenshot judge can see.
AD_BRIEFS: dict[str, str] = {
    "serum": "비타민C 세럼 신제품 12초 피드 광고. 한 문장 헤드라인, 제품이 주인공, 런칭 30% 할인, '지금 구매' CTA. 20대 후반 여성.",
    "popup_ad": "성수동 3일 한정 팝업스토어 '스윗스팟 x 로컬 로스터리' 12초 스토리 광고. 날짜·장소·사전예약 CTA, 딸기 디저트 비주얼.",
    "fintech_ad": "소수점 주식 투자 앱 12초 광고. '1,000원부터' 한 줄, 3분 가입, 안전·신뢰 신호, '지금 시작' CTA.",
}


def _ad_judge(sheet: Path, brief: str) -> dict:
    from ..loop.judge import judge_image
    return judge_image(sheet, brief + " (세 장은 같은 12초 광고의 1초/5초/9초 프레임: 훅 → 제품 → CTA)")


def _brain_ad_critique(history: list[dict]) -> str:
    if not history:
        return ""
    best = max(history, key=lambda h: h["select_score"])
    c = best["brain"]["critique"]
    hook = best["brain"]["hook_delta"]
    peak = best["brain"]["attention_peak_s"]
    return (f"Your BEST clip so far scored {best['select_score']:.2f}. {c['prompt_block']}\n"
            f"- TIME COURSE: attention front-load {hook:+.2f} (positive = hook lands early), attention peak at {peak} s "
            f"of 12. If the peak is after 4 s the hook is too slow; if attention falls after the peak, the product scene lacks a reveal.")


def _muse_ad_critique(history: list[dict]) -> str:
    if not history:
        return ""
    best = max(history, key=lambda h: h["select_score"])
    worst = min(history, key=lambda h: h["select_score"])
    return (f"DESIGN REVIEW (a senior designer rated contact sheets 0-1): BEST {best['select_score']:.2f}: {best['judge']['reason']} "
            f"| WORST {worst['select_score']:.2f}: {worst['judge']['reason']}. Keep what works, fix what is flagged.")


@app.command()
def ab(rounds: int = typer.Option(2), variants: int = typer.Option(2), only: str = typer.Option(""),
       out: Path = typer.Option(Path("results/showcase")), name: str = typer.Option(""), judge_weight: float = typer.Option(0.5),
       arms: str = typer.Option("oneshot,muse_loop,brain_loop")):
    from .pairwise import judge_pair
    run_dir = out / (name or time.strftime("ad-%Y%m%d-%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)
    summary: dict = {"rounds": rounds, "variants": variants, "kind": "ad", "briefs": {}}
    for key in [k for k in AD_BRIEFS if not only or k in only.split(",")]:
        brief = AD_BRIEFS[key]
        bdir = run_dir / key
        bdir.mkdir(exist_ok=True)
        print(f"\n▶ {key} {brief}")
        results: dict = {}
        for arm in arms.split(","):
            history: list[dict] = []
            n_rounds, n_vars = (1, 1) if arm == "oneshot" else (rounds, variants)
            for r in range(1, n_rounds + 1):
                for v in range(1, n_vars + 1):
                    tag = f"{arm}_r{r}v{v}"
                    t0 = time.time()
                    critique = (_muse_ad_critique(history) if arm == "muse_loop"
                                else _brain_ad_critique(history) if arm == "brain_loop" else "")
                    try:
                        html = generate_ad(brief, critique, v)
                    except GenerationError as e:
                        print(f"  {tag} skipped: {e}")
                        continue
                    (bdir / f"{tag}.html").write_text(html, encoding="utf-8")
                    mp4 = render_video(html, bdir / f"{tag}.mp4")
                    sheet = contact_sheet(mp4, bdir / f"{tag}.png")
                    rec: dict = {"arm": arm, "round": r, "variant": v, "tag": tag, "mp4": str(mp4), "png": str(sheet), "critique_in": critique}
                    j = _ad_judge(sheet, brief)
                    rec["judge"] = j
                    if arm == "brain_loop":
                        b = score_video(mp4, f"ad_{run_dir.name}_{key}_{tag}")
                        rec["brain"] = b
                        h = b["heads"]
                        brain_score = 0.5 * (h.get("attention", {}).get("percentile", 50) / 100) + 0.3 * (h.get("aesthetic", {}).get("percentile", 50) / 100) \
                            + 0.2 * max(0.0, min(1.0, 0.5 + b["hook_delta"]))
                        rec["select_score"] = (1 - judge_weight) * brain_score + judge_weight * j["judge_score"]
                    else:
                        rec["select_score"] = j["judge_score"]
                    rec["seconds"] = round(time.time() - t0, 1)
                    history.append(rec)
                    print(f"  {key}/{tag} select={rec['select_score']:.3f} ({rec['seconds']}s)")
            if history:
                best = max(history, key=lambda h: h["select_score"])
                results[arm] = {"arm": arm, "best": best["tag"], "best_png": best["png"], "best_mp4": best["mp4"], "history": history}
        final = {}
        for arm, res in results.items():
            b = score_video(Path(res["best_mp4"]), f"adfinal_{run_dir.name}_{key}_{arm}")
            final[arm] = {"tag": res["best"], "png": res["best_png"], "mp4": res["best_mp4"], "brain": b,
                          "brain_ui_score": round(0.5 * b["heads"].get("attention", {}).get("percentile", 50) / 100
                                                  + 0.5 * b["heads"].get("aesthetic", {}).get("percentile", 50) / 100, 3),
                          "heads": b["heads"], "critique": b["critique"]}
        pairs = {}
        if "brain_loop" in final:
            for other in [a for a in final if a != "brain_loop"]:
                pairs[f"brain_loop_vs_{other}"] = judge_pair(Path(final["brain_loop"]["png"]), Path(final[other]["png"]),
                                                             brief + " (각 후보는 같은 12초 광고의 1초/5초/9초 프레임)")
        summary["briefs"][key] = {"brief": brief, "kind": "ad", "arms": results, "final": final, "pairwise": pairs}
        (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        for k, p in pairs.items():
            print(f"  {k}: P(brain_loop better) = {p['p_first']:.2f} · {p['reason'][:160]}")
    from .gallery import build
    build(run_dir)
    print(f"\ngallery → {run_dir / 'index.html'}")


if __name__ == "__main__":
    app()
