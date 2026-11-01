"""Evaluation-driven UI loop: generate K page variants → render → score with the brain heads →
feed the critique back → repeat. Leaves a leaderboard and every artifact under results/loop/<run>/.

    uv run python -m brainsense.loop.optimize --brief "팝업스토어 랜딩 페이지..." --rounds 3 --variants 3
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import typer
from rich import print
from rich.table import Table

from .generate import generate_page
from .render import render_html
from .score import score_image

app = typer.Typer(add_completion=False)


@app.command()
def run(brief: str = typer.Option(..., help="what to build"),
        rounds: int = typer.Option(3), variants: int = typer.Option(3),
        out: Path = typer.Option(Path("results/loop")), name: str = typer.Option("")):
    run_dir = out / (name or time.strftime("%Y%m%d-%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)
    history: list[dict] = []
    for r in range(1, rounds + 1):
        for v in range(1, variants + 1):
            tag = f"r{r}v{v}"
            t0 = time.time()
            html = generate_page(brief, history, v)
            (run_dir / f"{tag}.html").write_text(html, encoding="utf-8")
            png = render_html(html, run_dir / f"{tag}.png")
            sc = score_image(png, f"loop_{run_dir.name}_{tag}")
            rec = {"round": r, "variant": v, "tag": tag, "ui_score": sc.ui_score, "heads": sc.heads,
                   "explanation": sc.explanation, "html_excerpt": html[:800], "seconds": round(time.time() - t0, 1)}
            history.append(rec)
            (run_dir / "history.json").write_text(json.dumps(history, ensure_ascii=False, indent=1))
            print(f"[bold]{tag}[/] ui_score={sc.ui_score:.3f}  {sc.explanation}  ({rec['seconds']}s)")
    board = sorted(history, key=lambda h: -h["ui_score"])
    tbl = Table(title=f"leaderboard · {run_dir}")
    for col in ("tag", "ui_score", "aesthetic", "attention"):
        tbl.add_column(col)
    for h in board:
        tbl.add_row(h["tag"], f"{h['ui_score']:.3f}",
                    f"top {100 - h['heads'].get('aesthetic', {}).get('percentile', 50):.0f}%",
                    f"top {100 - h['heads'].get('attention', {}).get('percentile', 50):.0f}%")
    print(tbl)
    best = board[0]
    (run_dir / "BEST.html").write_text((run_dir / f"{best['tag']}.html").read_text(encoding="utf-8"), encoding="utf-8")
    md = ["# UI loop leaderboard", f"brief: {brief}", "", "| rank | tag | ui_score | aesthetic | attention | notes |", "|---|---|---|---|---|---|"]
    for i, h in enumerate(board, 1):
        md.append(f"| {i} | {h['tag']} | {h['ui_score']:.3f} | top {100 - h['heads'].get('aesthetic', {}).get('percentile', 50):.0f}% | top {100 - h['heads'].get('attention', {}).get('percentile', 50):.0f}% | {h['explanation']} |")
    (run_dir / "LEADERBOARD.md").write_text("\n".join(md), encoding="utf-8")
    print(f"best: {best['tag']} → {run_dir / 'BEST.html'}")


if __name__ == "__main__":
    app()
