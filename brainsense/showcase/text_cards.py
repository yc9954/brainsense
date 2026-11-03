"""Turn a text showcase run into README material: one dark before/after card per brief (HTML, rendered
to PNG by the caller) and a Markdown snippet with the numbers.

    uv run python -m brainsense.showcase.text_cards results/showcase/text/en-text1
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

CSS = """
body{margin:0;background:#000;color:#fff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}
.card{width:1180px;padding:28px 32px;box-sizing:border-box;background:#000}
.k{color:#9AA0A6;font-size:12px;letter-spacing:2px;text-transform:uppercase}
h1{font-size:22px;font-weight:600;margin:6px 0 18px;letter-spacing:-.3px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:22px}
.col{border:1px solid #2A2D31;border-radius:18px;padding:18px 20px;background:#0E0F11;display:flex;flex-direction:column;gap:12px}
.col.win{border-color:#C0504D}
.t{font-size:15.5px;line-height:1.5;white-space:pre-wrap;flex:1}
.bars{display:flex;flex-direction:column;gap:7px;margin-top:4px}
.row{display:grid;grid-template-columns:150px 1fr 54px;align-items:center;gap:10px;font-size:12.5px;color:#9AA0A6}
.bar{height:9px;background:#2A2D31;border-radius:5px;overflow:hidden}.bar i{display:block;height:100%}
.w i{background:#fff}.r i{background:#C0504D}
.v{color:#fff;text-align:right;font-variant-numeric:tabular-nums}
.foot{margin-top:16px;color:#9AA0A6;font-size:12.5px;line-height:1.5}
.diag{color:#9AA0A6;font-size:12.5px;line-height:1.45;border-top:1px solid #2A2D31;padding-top:10px}
"""


def bar(label: str, v: float, cls: str) -> str:
    return f'<div class="row"><span>{label}</span><span class="bar {cls}"><i style="width:{max(2, min(100, v)):.0f}%"></i></span><span class="v">{v:.0f}%</span></div>'


def card(rec: dict) -> str:
    src, br = rec["source"], rec["brain_loop"]
    cfg = rec["cfg"]
    pj = rec["pairwise"]["brain_vs_source"]["p_first"]
    d = src.get("critique", {}).get("diagnosis", [])[:2]
    def col(title: str, r: dict, win: bool, extra: str) -> str:
        return (f'<div class="col{" win" if win else ""}"><div class="k">{title}</div><div class="t">{html.escape(r["text"])}</div>'
                f'<div class="bars">{bar("Human-likeness", r["humanlike_pct"], "r" if win else "w")}{bar("Attention", r["attention_pct"], "r" if win else "w")}</div>{extra}</div>')
    left = col("Before · the draft, as a chatbot wrote it", src, False, f'<div class="diag">What the reader\'s cortex said: {html.escape(" / ".join(d)) if d else "nothing missing"}</div>')
    right = col("After · brain in the loop, round " + br["best"].split("_r")[1][0], br, True, "")
    foot = (f"Percentiles against 1,200 human and machine texts (Human-likeness head, holdout AUROC 0.88) and against rated photos (attention). "
            f"Blind pairwise judge: P(after is better) = {pj:.2f}.")
    return f'<!doctype html><meta charset="utf-8"><style>{CSS}</style><div class="card"><div class="k">{html.escape(cfg["reader"])}</div><h1>{html.escape(cfg["task"].split(" (")[0].capitalize())}</h1><div class="cols">{left}{right}</div><div class="foot">{foot}</div></div>'


def main(run: Path) -> None:
    recs = [json.loads(p.read_text()) for p in sorted(run.glob("*/result.json"))]
    rows = ["| brief | Human-likeness pct: draft → one-shot → brain | Attention pct: draft → brain | judge P(brain > one-shot) | judge P(brain > draft) |", "|---|---|---|---|---|"]
    for r in recs:
        (run / r["key"] / "card.html").write_text(card(r), encoding="utf-8")
        hl = {a: r[a]["humanlike_pct"] for a in ("source", "oneshot", "brain_loop")}
        at = {a: r[a]["attention_pct"] for a in ("source", "brain_loop")}
        rows.append(f"| {r['key'].replace('_', ' ')} | {hl['source']:.0f} → {hl['oneshot']:.0f} → **{hl['brain_loop']:.0f}** | {at['source']:.0f} → {at['brain_loop']:.0f} | "
                    f"{r['pairwise']['brain_vs_oneshot']['p_first']:.2f} | {r['pairwise']['brain_vs_source']['p_first']:.2f} |")
    (run / "TABLE.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print("\n".join(rows))
    for r in recs:
        a = r.get("audio") or {}
        if a.get("source") and a.get("brain_loop"):
            print(r["key"], "audio heads:", a["source"]["heads"], "→", a["brain_loop"]["heads"], "| top regions:", a["source"]["ranking"][:2], "→", a["brain_loop"]["ranking"][:2])


if __name__ == "__main__":
    main(Path(sys.argv[1]))
