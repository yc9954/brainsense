"""Static gallery for a showcase run: per brief, the three finalists side by side with the blind
pairwise verdict, brain score and the cortex diagnosis. Open results/showcase/<run>/index.html."""
from __future__ import annotations

import html
import json
from pathlib import Path

ARM_KO = {"oneshot": "Muse 한 번 (베이스라인)", "muse_loop": "Muse 자기평가 루프", "brain_loop": "BrainSense 루프 (우리)"}


def build(run_dir: Path) -> Path:
    s = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    parts = [f"""<!doctype html><html lang=ko><head><meta charset=utf-8><title>BrainSense showcase · {run_dir.name}</title>
<style>body{{font-family:-apple-system,Pretendard,sans-serif;background:#0b0b0f;color:#eee;margin:0;padding:32px}}
h1{{font-weight:600;font-size:22px}} h2{{font-size:16px;font-weight:600;margin:40px 0 6px}} .brief{{color:#aaa;font-size:13px;max-width:900px}}
.row{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:14px}} .card{{background:#15151b;border-radius:14px;overflow:hidden;border:1px solid #23232b}}
.card.win{{border-color:#ff6a2b;box-shadow:0 0 0 1px #ff6a2b}} .card img{{width:100%;display:block;aspect-ratio:1.6;object-fit:cover;object-position:top}}
.meta{{padding:12px 14px;font-size:12.5px;line-height:1.5}} .arm{{font-weight:600;font-size:13px}} .k{{color:#8b8b96}} .diag{{color:#c9c9d2;margin-top:6px}}
.verdict{{margin-top:10px;font-size:13px;color:#ffb38a}} .tiny{{font-size:11px;color:#777}}</style></head><body>
<h1>BrainSense showcase — 같은 브리프, 같은 생성 예산, 피드백만 다르게</h1>
<p class=brief>rounds {s['rounds']} × variants {s['variants']}. oneshot = Muse Spark 한 번. muse_loop = Muse가 자기 스크린샷을 스스로 평가해 고치는 루프. brain_loop = TRIBE v2 예측 피질 반응 → 전문가 비평(skills) → Muse가 고치는 루프. 최종 비교는 순서를 바꿔 두 번 묻는 블라인드 판정.</p>"""]
    for key, b in s["briefs"].items():
        pw = b.get("pairwise", {})
        parts.append(f"<h2>{html.escape(key)}</h2><div class=brief>{html.escape(b['brief'])}</div><div class=row>")
        for arm in ("oneshot", "muse_loop", "brain_loop"):
            f = b["final"].get(arm)
            if not f:
                continue
            rel = Path(f["png"]).relative_to(run_dir) if Path(f["png"]).is_absolute() else Path(f["png"]).relative_to(run_dir) if str(f["png"]).startswith(str(run_dir)) else Path(key) / Path(f["png"]).name
            p = pw.get(f"brain_loop_vs_{arm}")
            win = arm == "brain_loop" and all(v["p_first"] > 0.5 for v in pw.values()) if pw else False
            heads = f.get("heads", {})
            hs = " · ".join(f"{k} top {100 - v.get('percentile', 50):.0f}%" for k, v in heads.items() if isinstance(v, dict) and "percentile" in v)
            diag = "<br>".join(html.escape(d) for d in f["critique"]["diagnosis"][:3])
            verdict = f"<div class=verdict>블라인드 판정 P(brain_loop 승) = {p['p_first']:.2f}</div><div class=tiny>{html.escape(p['reason'][:220])}</div>" if p else ""
            parts.append(f"<div class='card{' win' if win else ''}'><a href='{rel}' target=_blank><img src='{rel}'></a><div class=meta>"
                         f"<div class=arm>{ARM_KO[arm]}</div><div class=k>brain ui_score {f['brain_ui_score']:.3f} · {hs}</div>"
                         f"<div class=diag>{diag}</div>{verdict}</div></div>")
        parts.append("</div>")
    parts.append("</body></html>")
    out = run_dir / "index.html"
    out.write_text("\n".join(parts), encoding="utf-8")
    return out
