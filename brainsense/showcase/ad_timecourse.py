"""Per-second cortex figure for an ad run: the one-shot clip against the kept clip, dorsal attention
and early visual cortex, second by second (the thing a still can never show).

    uv run python -m brainsense.showcase.ad_timecourse results/showcase/admaker/serum-try1   # → <run>/timecourse.svg
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

GROUPS = [("attention_dorsal", "Visual attention (dorsal)"), ("visual_early", "Early visual cortex")]
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"


def render(run: Path, title: str | None = None) -> Path:
    rep = json.loads((run / "report.json").read_text())
    steps = {s["round"]: s for s in rep["steps"]}
    best = steps[rep["best_round"]]
    base = steps[0]
    arms = [(base, "One shot, no feedback", "#9AA0A6"), (best, f"Brain in the loop, round {best['round']}", "#C0504D")]
    W, H = 1180, 400
    L, R, T = 190, 40, 70
    pw = W - L - R
    rh = (H - T - 80) / len(GROUPS)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}"><rect width="{W}" height="{H}" fill="#000"/>',
         f'<text x="{L}" y="30" fill="#fff" font-size="16" font-weight="600">{title or "Predicted cortex while watching the 12-second ad · z-score per second"}</text>']
    x0 = L + pw - 330
    for i, (_, label, col) in enumerate(arms):
        o.append(f'<rect x="{x0 + i * 170}" y="42" width="14" height="10" fill="{col}"/><text x="{x0 + i * 170 + 20}" y="51" fill="#9AA0A6" font-size="12">{label}</text>')
    n = 12
    for ri, (g, gl) in enumerate(GROUPS):
        y0 = T + ri * rh
        series = [(s["brain"]["roi_ts"].get(g) or [])[:n] for s, _, _ in arms]
        vals = [x for ts in series for x in ts] + [0.0]
        lo, hi = min(vals), max(vals)
        scale = (rh - 30) / ((hi - lo) or 1)
        zy = y0 + 15 + (hi - 0) * scale
        o.append(f'<text x="{L - 12}" y="{y0 + rh / 2}" fill="#fff" font-size="13" font-weight="600" text-anchor="end">{gl}</text>')
        o.append(f'<line x1="{L}" y1="{zy:.1f}" x2="{L + pw}" y2="{zy:.1f}" stroke="#2A2D31"/>')
        bw = pw / n
        for ai, ts in enumerate(series):
            col = arms[ai][2]
            for s_, v in enumerate(ts):
                x = L + s_ * bw + 6 + ai * ((bw - 12) / 2)
                h = abs(v) * scale
                y = zy - h if v >= 0 else zy
                o.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{(bw - 12) / 2 - 2:.1f}" height="{max(h, 1):.1f}" fill="{col}"/>')
    ya = T + len(GROUPS) * rh + 8
    for s_ in range(n):
        o.append(f'<text x="{L + s_ * pw / n + pw / (2 * n):.0f}" y="{ya}" fill="#9AA0A6" font-size="11" text-anchor="middle">{s_ + 1}s</text>')
    pb, pk = base["brain"], best["brain"]
    pw_ = rep.get("pairwise_best_vs_oneshot") or {}
    foot1 = (f"Attention peak: one shot at {pb.get('attention_peak_s')} s → brain loop at {pk.get('attention_peak_s')} s; "
             f"front-load {pb.get('hook_delta', 0):+.2f} → {pk.get('hook_delta', 0):+.2f} (positive = the hook lands early).")
    foot2 = (f"Brain score {base['brain_score']:.2f} → {best['brain_score']:.2f} · designer judge {float(base['judge'].get('judge_score', 0)):.2f} → {float(best['judge'].get('judge_score', 0)):.2f}"
             + (f" · blind pairwise P(brain loop better) = {pw_.get('p_first'):.2f}" if pw_.get("p_first") is not None else ""))
    o.append(f'<text x="{L}" y="{H - 36}" fill="#9AA0A6" font-size="11.5">{foot1}</text>')
    o.append(f'<text x="{L}" y="{H - 18}" fill="#9AA0A6" font-size="11.5">{foot2}</text>')
    o.append("</svg>")
    out = run / "timecourse.svg"
    out.write_text("".join(o), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(render(Path(sys.argv[1])))
