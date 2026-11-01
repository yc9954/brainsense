"""Render an HTML page to a screenshot with the local Chrome (headless). No extra installs."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

CHROME_CANDIDATES = [
    os.environ.get("BRAINSENSE_CHROME", ""),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    shutil.which("google-chrome") or "",
    shutil.which("chromium") or "",
]


def chrome_path() -> str:
    for c in CHROME_CANDIDATES:
        if c and Path(c).exists():
            return c
    raise RuntimeError("no Chrome/Chromium found; set BRAINSENSE_CHROME")


def render_html(html: str, out_png: Path, width: int = 1280, height: int = 800, timeout_s: int = 60) -> Path:
    """Write `html` to a temp file and screenshot it at width x height (device scale 1)."""
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as d:
        page = Path(d) / "page.html"
        # Generated pages love entrance animations (opacity 0 → 1 on scroll/load); a screenshot at
        # virtual time 0 would capture an empty hero. Force everything visible and static.
        # (forcing opacity/visibility would also reveal intentionally hidden modals, so we only let
        # animations finish quickly under virtual time)
        freeze = ("<style id=\"brainsense-freeze\">*,*::before,*::after{animation-duration:.01s!important;"
                  "animation-delay:0s!important;animation-iteration-count:1!important;"
                  "transition-duration:.01s!important}</style>")
        html = html.replace("</head>", freeze + "</head>", 1) if "</head>" in html else html + freeze
        page.write_text(html, encoding="utf-8")
        profile = Path(d) / "profile"
        cmd = [chrome_path(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
               "--no-default-browser-check", f"--user-data-dir={profile}", f"--window-size={width},{height}",
               "--force-device-scale-factor=1", "--virtual-time-budget=12000",
               f"--screenshot={out_png}", page.as_uri()]
        subprocess.run(cmd, check=True, capture_output=True, timeout=timeout_s)
    if not out_png.exists():
        raise RuntimeError("Chrome produced no screenshot")
    return out_png
