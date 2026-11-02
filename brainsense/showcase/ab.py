"""Showcase A/B: does the brain-in-the-loop harness beat plain Muse Spark on the same brief?

Three arms, same generation budget per brief:
  oneshot     Muse Spark once, no feedback (what "just ask the model" gives you)
  muse_loop   rounds × variants, feedback = Muse's own multimodal self-critique, pick by self-judge
  brain_loop  rounds × variants, feedback = brain critique (skills.read_brain), pick by brain+judge blend
Then a BLIND pairwise judge (Muse multimodal, both orders) compares the finalists, every finalist gets
a brain score, and gallery.py turns it into results/showcase/<run>/index.html.

    uv run python -m brainsense.showcase.ab run --rounds 2 --variants 2            # full suite
    uv run python -m brainsense.showcase.ab run --only popup --rounds 1 --variants 2  # smoke
"""
from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import typer
from rich import print
from rich.markup import escape

from ..loop.generate import SYSTEM, GenerationError, _body_text, _client, _extract_html
from ..loop.judge import judge_image
from ..loop.render import render_html
from ..loop.score import score_image
from .pairwise import judge_pair
from .skills import read_brain

app = typer.Typer(add_completion=False)

BRIEFS: dict[str, dict] = {
    "popup": {"kind": "landing", "brief": "서울 성수동 3일 한정 팝업스토어 '스윗스팟 x 로컬 로스터리' 랜딩 첫 화면. 날짜·장소·사전예약 CTA. 20대 후반 여성 타깃, 감각적이지만 정보가 바로 읽혀야 함."},
    "skincare_ad": {"kind": "ad", "brief": "비타민C 세럼 신제품 인스타그램 피드 광고(정사각형 느낌의 1280x800 첫 화면). 한 문장 헤드라인, 제품이 주인공, 런칭 30% 할인 배지, '지금 구매' CTA."},
    "saas_pricing": {"kind": "app", "brief": "AI 회의록 SaaS의 가격 페이지 첫 화면. Free / Pro(월 12,000원) / Team 3단, Pro 강조, 신뢰 요소(고객 로고 자리, 환불 보장) 포함."},
    "festival_poster": {"kind": "poster", "brief": "11월 재즈 페스티벌 웹 포스터 첫 화면. 라인업 5팀, 날짜·장소, 얼리버드 티켓 CTA. 밤·네온·따뜻한 금관악기 느낌."},
    "fintech_onboarding": {"kind": "app", "brief": "주식 소수점 투자 앱의 첫 온보딩 화면(웹 미리보기 1280x800). 핵심 가치 한 줄, 1,000원부터 시작 가능 강조, '3분 만에 시작' CTA, 신뢰·안전 신호."},
}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def generate(brief: str, critique: str, variant: int, temperature: float = 0.9, max_tokens: int = 16000, retries: int = 2) -> str:
    """Same generator as the loop (Muse Spark, single-file HTML) but the critique text is arm-specific."""
    compact, last = "", "unknown"
    for _ in range(retries + 1):
        user = (f"Brief: {brief}\n\nThis is variant #{variant}: explore a distinctly different layout and palette "
                f"from other variants.{(chr(10) * 2 + critique) if critique else ''}{compact}")
        r = _client().chat.completions.create(
            model=os.environ.get("BRAINSENSE_LLM_MODEL", "muse-spark-1.3"),
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            temperature=temperature, max_tokens=max_tokens)
        ch = r.choices[0]
        html = _extract_html(ch.message.content or "")
        if ch.finish_reason == "length" or "</html>" not in html.lower():
            last = f"truncated ({len(html)} chars)"
            compact = "\n\nIMPORTANT: your previous answer was cut off. Keep the whole document under 250 lines."
            continue
        if len(_body_text(html)) < 120:
            last = "empty body"
            compact = "\n\nIMPORTANT: the previous answer had no visible content. Put real headline, copy and a CTA in <body>."
            continue
        return html
    raise GenerationError(f"variant {variant}: {last}")


def _muse_critique(history: list[dict]) -> str:
    if not history:
        return ""
    best = max(history, key=lambda h: h["select_score"])
    worst = min(history, key=lambda h: h["select_score"])
    return ("DESIGN REVIEW of your previous rounds (a senior designer rated screenshots 0-1):\n"
            f"- BEST so far ({best['select_score']:.2f}): {best['judge']['reason']}\n"
            f"- WORST ({worst['select_score']:.2f}): {worst['judge']['reason']}\n"
            "Keep what the best does right and fix what the review flags.")


def _brain_critique(history: list[dict]) -> str:
    if not history:
        return ""
    best = max(history, key=lambda h: h["select_score"])
    worst = min(history, key=lambda h: h["select_score"])
    return (f"Your BEST round so far scored {best['select_score']:.2f} (brain+judge blend); the WORST {worst['select_score']:.2f}.\n"
            f"{best['critique']['prompt_block']}\n\n"
            f"(For contrast, the worst render's brain diagnosis: {' / '.join(worst['critique']['diagnosis'][:2])})")


def run_arm(arm: str, key: str, cfg: dict, out: Path, rounds: int, variants: int, parallel: int, judge_weight: float) -> dict:
    brief, kind = cfg["brief"], cfg["kind"]
    history: list[dict] = []
    stamp = out.parent.name

    def one(r: int, v: int) -> dict | None:
        tag = f"{arm}_r{r}v{v}"
        t0 = time.time()
        critique = (_muse_critique(history) if arm == "muse_loop"
                    else _brain_critique(history) if arm == "brain_loop" else "")
        try:
            html = generate(brief, critique, v)
        except GenerationError as e:
            print(f"[red]{key}/{tag} skipped: {escape(str(e))}[/]")
            return None
        (out / f"{tag}.html").write_text(html, encoding="utf-8")
        png = render_html(html, out / f"{tag}.png")
        rec: dict = {"arm": arm, "round": r, "variant": v, "tag": tag, "png": str(png), "critique_in": critique,
                     "seconds_gen": round(time.time() - t0, 1)}
        if arm == "brain_loop":
            sc = score_image(png, f"sc_{stamp}_{key}_{tag}", brief=brief, judge_weight=judge_weight)
            rec |= {"select_score": sc.ui_score, "heads": sc.heads, "explanation": sc.explanation}
            ev = _eval(f"sc_{stamp}_{key}_{tag}")
            rec["critique"] = read_brain(ev, kind).to_dict() | {"prompt_block": read_brain(ev, kind).prompt_block}
        else:
            j = judge_image(png, brief)
            rec |= {"select_score": j["judge_score"], "judge": j}
        rec["seconds"] = round(time.time() - t0, 1)
        return rec

    n_rounds, n_vars = (1, 1) if arm == "oneshot" else (rounds, variants)
    for r in range(1, n_rounds + 1):
        with ThreadPoolExecutor(max_workers=max(1, min(n_vars, parallel))) as ex:
            recs = [x for x in ex.map(lambda v: one(r, v), range(1, n_vars + 1)) if x]
        for rec in sorted(recs, key=lambda x: x["variant"]):
            history.append(rec)
            print(f"[bold]{key}/{rec['tag']}[/] select={rec['select_score']:.3f} ({rec['seconds']}s)")
    if not history:
        raise RuntimeError(f"{arm}: every generation failed")
    best = max(history, key=lambda h: h["select_score"])
    return {"arm": arm, "best": best["tag"], "best_png": best["png"], "history": history}


def _eval(item_id: str) -> dict:
    import httpx
    server = os.environ.get("BRAINSENSE_SERVER_URL", "http://localhost:8000").rstrip("/")
    return httpx.get(f"{server}/eval/{item_id}", timeout=120).json()


@app.command()
def run(rounds: int = typer.Option(2), variants: int = typer.Option(2), parallel: int = typer.Option(2),
        only: str = typer.Option("", help="comma-separated brief keys"), out: Path = typer.Option(Path("results/showcase")),
        name: str = typer.Option(""), judge_weight: float = typer.Option(0.5),
        arms: str = typer.Option("oneshot,muse_loop,brain_loop")):
    run_dir = out / (name or time.strftime("%Y%m%d-%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)
    keys = [k for k in BRIEFS if not only or k in only.split(",")]
    arm_list = arms.split(",")
    summary: dict = {"rounds": rounds, "variants": variants, "briefs": {}}
    for key in keys:
        cfg = BRIEFS[key]
        bdir = run_dir / key
        bdir.mkdir(exist_ok=True)
        print(f"\n[bold cyan]▶ {key}[/] {escape(cfg['brief'])}")
        results = {}
        for arm in arm_list:
            results[arm] = run_arm(arm, key, cfg, bdir, rounds, variants, parallel, judge_weight)
        # final: brain score for every finalist (same item ids → cached when already scored) + blind pairwise
        final = {}
        for arm, res in results.items():
            sc = score_image(Path(res["best_png"]), f"final_{run_dir.name}_{key}_{arm}")
            ev = _eval(f"final_{run_dir.name}_{key}_{arm}")
            final[arm] = {"tag": res["best"], "png": res["best_png"], "brain_ui_score": sc.ui_score, "heads": sc.heads,
                          "critique": read_brain(ev, cfg["kind"]).to_dict()}
        pairs = {}
        if "brain_loop" in results:
            for other in [a for a in arm_list if a != "brain_loop"]:
                pairs[f"brain_loop_vs_{other}"] = judge_pair(Path(final["brain_loop"]["png"]), Path(final[other]["png"]), cfg["brief"])
        summary["briefs"][key] = {"brief": cfg["brief"], "kind": cfg["kind"], "arms": {a: {k: v for k, v in r.items() if k != "history"} | {"history": r["history"]} for a, r in results.items()},
                                  "final": final, "pairwise": pairs}
        (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        for k, p in pairs.items():
            print(f"  {k}: P(brain_loop better) = {p['p_first']:.2f}  · {escape(p['reason'][:160])}")
    from .gallery import build
    build(run_dir)
    print(f"\ngallery → {run_dir / 'index.html'}")


if __name__ == "__main__":
    app()
