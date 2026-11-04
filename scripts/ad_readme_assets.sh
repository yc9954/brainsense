#!/usr/bin/env bash
# README assets for an ad-maker run: narrated trail PNG, per-second figure, best clip as GIF/MP4, contact sheets.
#   scripts/ad_readme_assets.sh results/showcase/admaker/serum-try4
set -euo pipefail
RUN="$1"; NAME=$(basename "$RUN")
ROOT=/Users/yuchanlee/brainsense-hackathon/brainsense; O=/Users/yuchanlee/brainsense-hackathon/openmuse
cd "$ROOT"
uv run python -m brainsense.showcase.trail "$RUN" >/dev/null
uv run python -m brainsense.showcase.ad_timecourse "$RUN" >/dev/null
BEST=$(python3 -c "import json;r=json.load(open('$RUN/report.json'));print(r['best_round'])")
mkdir -p docs/img docs/video
d=$(find $O/node_modules/.pnpm -maxdepth 1 -name "playwright@*" | head -1)
cat > $d/node_modules/playwright/_t.mjs <<JS
import { chromium } from "./index.mjs";
const browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" });
let page = await (await browser.newContext({ viewport: { width: 1180, height: 950 }, deviceScaleFactor: 1.5 })).newPage();
await page.goto("file://$ROOT/$RUN/trail.html"); await page.waitForTimeout(400);
await page.locator(".card").screenshot({ path: "$ROOT/docs/img/trail-ad.png" });
page = await (await browser.newContext({ viewport: { width: 1200, height: 420 }, deviceScaleFactor: 1.5 })).newPage();
await page.goto("file://$ROOT/$RUN/timecourse.svg"); await page.waitForTimeout(300);
await page.screenshot({ path: "$ROOT/docs/img/ad-timecourse.png" });
await browser.close();
JS
node $d/node_modules/playwright/_t.mjs >/dev/null 2>&1; rm -f $d/node_modules/playwright/_t.mjs
cp "$RUN/r0.png" docs/img/ad-oneshot-sheet.png
cp "$RUN/r$BEST.png" docs/img/ad-brain-sheet.png
ffmpeg -y -loglevel error -i "$RUN/r$BEST.mp4" -vf "fps=6,scale=720:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer:bayer_scale=4" docs/video/ad-brain.gif
ffmpeg -y -loglevel error -i "$RUN/r0.mp4" -vf "fps=6,scale=720:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer:bayer_scale=4" docs/video/ad-oneshot.gif
cp "$RUN/r$BEST.mp4" docs/video/ad-brain.mp4; cp "$RUN/r0.mp4" docs/video/ad-oneshot.mp4
ls -la docs/img/trail-ad.png docs/img/ad-timecourse.png docs/video/ad-brain.gif docs/video/ad-oneshot.gif | awk '{print $5,$9}'
echo "best round $BEST"
