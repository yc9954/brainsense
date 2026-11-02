"""Static gallery for a showcase run: per brief, the three finalists side by side with the blind
pairwise verdict, brain score and the cortex diagnosis. Open results/showcase/<run>/index.html."""
from __future__ import annotations

import html
import json
from pathlib import Path

ARM_KO = {"oneshot": "Muse 한 번 (베이스라인)", "muse_loop": "Muse 자기평가 루프", "brain_loop": "BrainSense 루프 (뇌만)", "hybrid_loop": "BrainSense 루프 (뇌 + 리뷰, 출시 하네스)"}


def build(run_dir: Path) -> Path:
    s = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    parts = [f"""<!doctype html><html lang=ko><head><meta charset=utf-8><title>BrainSense showcase · {run_dir.name}</title>
<style>body{{font-family:-apple-system,Pretendard,sans-serif;background:#0b0b0f;color:#eee;margin:0;padding:32px}}
h1{{font-weight:600;font-size:22px}} h2{{font-size:16px;font-weight:600;margin:40px 0 6px}} .brief{{color:#aaa;font-size:13px;max-width:900px}}
.row{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;margin-top:14px}} .card{{background:#15151b;border-radius:14px;overflow:hidden;border:1px solid #23232b}}
.card.win{{border-color:#ff6a2b;box-shadow:0 0 0 1px #ff6a2b}} .card img{{width:100%;display:block;aspect-ratio:1.6;object-fit:cover;object-position:top}}
.meta{{padding:12px 14px;font-size:12.5px;line-height:1.5}} .arm{{font-weight:600;font-size:13px}} .k{{color:#8b8b96}} .diag{{color:#c9c9d2;margin-top:6px}}
.verdict{{margin-top:10px;font-size:13px;color:#ffb38a}} .tiny{{font-size:11px;color:#777}}</style></head><body>
<h1>BrainSense showcase — 같은 브리프, 같은 생성 예산, 피드백만 다르게</h1>
<p class=brief>rounds {s['rounds']} × variants {s['variants']}. oneshot = Muse Spark 한 번. muse_loop = Muse가 자기 스크린샷을 스스로 평가해 고치는 루프. brain_loop = TRIBE v2 예측 피질 반응 → 전문가 비평(skills) → Muse가 고치는 루프. 최종 비교는 순서를 바꿔 두 번 묻는 블라인드 판정.</p>"""]
    for key, b in s["briefs"].items():
        pw = b.get("pairwise", {})
        parts.append(f"<h2>{html.escape(key)}</h2><div class=brief>{html.escape(b['brief'])}</div><div class=row>")
        champ = next((k.split("_vs_")[0] for k in pw), "brain_loop")
        for arm in [a for a in ("oneshot", "muse_loop", "brain_loop", "hybrid_loop") if a in b["final"]]:
            f = b["final"][arm]
            rel = Path(f["png"]).relative_to(run_dir) if Path(f["png"]).is_absolute() else Path(f["png"]).relative_to(run_dir) if str(f["png"]).startswith(str(run_dir)) else Path(key) / Path(f["png"]).name
            p = pw.get(f"{champ}_vs_{arm}")
            win = arm == champ and all(v["p_first"] > 0.5 for v in pw.values()) if pw else False
            heads = f.get("heads", {})
            hs = " · ".join(f"{k} top {100 - v.get('percentile', 50):.0f}%" for k, v in heads.items() if isinstance(v, dict) and "percentile" in v)
            diag = "<br>".join(html.escape(d) for d in f["critique"]["diagnosis"][:3])
            verdict = f"<div class=verdict>블라인드 판정 P({champ} 승) = {p['p_first']:.2f}</div><div class=tiny>{html.escape(p['reason'][:220])}</div>" if p else ""
            parts.append(f"<div class='card{' win' if win else ''}'><a href='{rel}' target=_blank><img src='{rel}'></a><div class=meta>"
                         f"<div class=arm>{ARM_KO[arm]}</div><div class=k>brain ui_score {f['brain_ui_score']:.3f} · {hs}</div>"
                         f"<div class=diag>{diag}</div>{verdict}</div></div>")
        parts.append("</div>")
    parts.append("</body></html>")
    out = run_dir / "index.html"
    out.write_text("\n".join(parts), encoding="utf-8")
    return out


def build_index(out_dir: Path) -> Path:
    """results/showcase/index.html: one page linking every run's gallery with its headline numbers."""
    from .report import summarize
    runs = sorted((p for p in out_dir.iterdir() if (p / "summary.json").exists() and p.name not in ("harness", "redesign")), key=lambda p: p.stat().st_mtime, reverse=True)
    parts = ["""<!doctype html><html lang=ko><head><meta charset=utf-8><title>BrainSense showcase runs</title>
<style>body{font-family:-apple-system,Pretendard,sans-serif;background:#0b0b0f;color:#eee;margin:0;padding:32px}
h1{font-weight:600;font-size:22px} table{border-collapse:collapse;font-size:13px;margin-top:16px} td,th{padding:8px 12px;border-bottom:1px solid #23232b;text-align:left}
a{color:#ffb38a} .k{color:#8b8b96}</style></head><body><h1>BrainSense showcase — runs</h1>
<p class=k>brain_loop = TRIBE v2 예측 피질 → 전문가 비평 → Muse 수정. 승률은 순서를 바꿔 두 번 묻는 블라인드 판정 기준.</p>
<table><tr><th>run</th><th>briefs</th><th>vs Muse one-shot</th><th>vs Muse self-loop</th><th>brain score (oneshot / muse / brain)</th></tr>"""]
    for r in runs:
        try:
            s = summarize([r])
        except Exception:
            continue
        pw = s["pairwise"]
        b = s["brain_score_by_arm"]
        f = lambda k: f"{pw[k]['win_rate']:.0%} (P {pw[k]['mean_p']:.2f}, n={pw[k]['n']})" if k in pw else "—"   # noqa: E731
        parts.append(f"<tr><td><a href='{r.name}/index.html'>{html.escape(r.name)}</a></td><td>{len(s['rows'])}</td>"
                     f"<td>{f('brain_loop_vs_oneshot')}</td><td>{f('brain_loop_vs_muse_loop')}</td>"
                     f"<td>{b.get('oneshot', float('nan')):.3f} / {b.get('muse_loop', float('nan')):.3f} / {b.get('brain_loop', float('nan')):.3f}</td></tr>")
    parts.append("</table>")
    hz = out_dir / "harness"
    hruns = sorted((p for p in hz.iterdir() if (p / "summary.json").exists()), key=lambda p: p.stat().st_mtime, reverse=True) if hz.exists() else []
    if hruns:
        parts.append("<h1 style='margin-top:36px'>같은 브리프, 제로부터 — Muse 한 번 vs BrainSense 하네스 (문제 장부 + 사진 소싱 + 개선될 때만 채택)</h1>"
                     "<table><tr><th>run / brief</th><th>ui_score Muse 한 번 → 하네스</th><th>rounds kept</th><th>issues fixed</th><th>photos</th></tr>")
        for r in hruns:
            summ = json.loads((r / "summary.json").read_text(encoding="utf-8"))
            for key, v in summ.items():
                parts.append(f"<tr><td><a href='harness/{r.name}/{key}/index.html'>{html.escape(r.name)} / {html.escape(key)}</a></td>"
                             f"<td>{v['baseline_ui']:.3f} → <b>{v['best_ui']:.3f}</b> ({v['best_ui'] - v['baseline_ui']:+.3f})</td><td>r{v['best_round']}</td>"
                             f"<td>{v['issues_fixed']}/{v['issues']}</td><td>{v['photos']}</td></tr>")
        parts.append("</table>")
    rd = out_dir / "redesign"
    cases = sorted((p for p in rd.iterdir() if (p / "report.json").exists()), key=lambda p: p.stat().st_mtime, reverse=True) if rd.exists() else []
    if cases:
        parts.append("<h1 style='margin-top:36px'>뇌가 고친 실제 사이트 (before → after)</h1><table><tr><th>site</th><th>ui_score before → after</th><th>뇌 점수</th><th>심사위원</th><th>첫 진단</th></tr>")
        for c in cases:
            r = json.loads((c / "report.json").read_text(encoding="utf-8"))
            o = r["steps"][0]
            b = next(s for s in r["steps"] if s["round"] == r["best_round"])
            parts.append(f"<tr><td><a href='redesign/{c.name}/index.html'>{html.escape(r['source'])}</a></td>"
                         f"<td>{o['ui_score']:.3f} → <b>{b['ui_score']:.3f}</b> ({b['ui_score'] - o['ui_score']:+.3f})</td>"
                         f"<td>{o['brain_only']:.3f} → {b['brain_only']:.3f}</td><td>{o['judge'].get('judge_score', 0):.2f} → {b['judge'].get('judge_score', 0):.2f}</td>"
                         f"<td class=k>{html.escape(o['critique']['diagnosis'][0][:90]) if o['critique']['diagnosis'] else ''}</td></tr>")
        parts.append("</table>")
    parts.append("</body></html>")
    out = out_dir / "index.html"
    out.write_text("\n".join(parts), encoding="utf-8")
    return out
