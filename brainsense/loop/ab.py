"""A/B(/N) comparison of pages with the brain heads: HTML files or URLs → screenshots → scores.

    uv run python -m brainsense.loop.ab page_a.html page_b.html https://example.com
"""
from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path

import typer
from rich import print
from rich.table import Table

from .render import chrome_path, render_html
from .score import score_image

app = typer.Typer(add_completion=False)


def _render_any(src: str, out_png: Path) -> Path:
    if src.startswith(("http://", "https://")):
        out_png.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as d:
            subprocess.run([chrome_path(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                            f"--user-data-dir={d}/p", "--window-size=1280,800", "--force-device-scale-factor=1",
                            "--virtual-time-budget=6000", f"--screenshot={out_png}", src],
                           check=True, capture_output=True, timeout=90)
        return out_png
    return render_html(Path(src).read_text(encoding="utf-8"), out_png)


@app.command()
def compare(sources: list[str] = typer.Argument(...), out: Path = typer.Option(Path("results/loop/ab"))):
    stamp = time.strftime("%H%M%S")
    rows = []
    for i, src in enumerate(sources):
        png = _render_any(src, out / f"{stamp}_{i}.png")
        sc = score_image(png, f"ab_{stamp}_{i}")
        rows.append((src, sc))
        print(f"[bold]{src}[/] → ui_score {sc.ui_score:.3f} · {sc.explanation}")
    tbl = Table(title="A/B by brain heads")
    for c in ("source", "ui_score", "aesthetic", "attention"):
        tbl.add_column(c)
    for src, sc in sorted(rows, key=lambda r: -r[1].ui_score):
        tbl.add_row(src[-48:], f"{sc.ui_score:.3f}",
                    f"top {100 - sc.heads.get('aesthetic', {}).get('percentile', 50):.0f}%",
                    f"top {100 - sc.heads.get('attention', {}).get('percentile', 50):.0f}%")
    print(tbl)


if __name__ == "__main__":
    app()
