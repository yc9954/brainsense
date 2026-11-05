// Renders the demo's title cards and overlays (1920x1080 PNG) with Chrome.
// node <playwright>/_cards.mjs <outdir> <repo root>
import { chromium } from "./index.mjs";
import fs from "node:fs";

const OUT = process.argv[2];
const ROOT = process.argv[3];
const img = (p) => "data:image/png;base64," + fs.readFileSync(ROOT + "/" + p).toString("base64");
const NEURO = img("docs/img/neuro.png");

const CSS = `
*{box-sizing:border-box;margin:0}
body{width:1920px;height:1080px;background:#000;color:#fff;font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display','Helvetica Neue',Helvetica,Arial,sans-serif;overflow:hidden;-webkit-font-smoothing:antialiased}
.k{color:#9AA0A6;font-size:22px;letter-spacing:6px;text-transform:uppercase}
.red{color:#C0504D}
.c{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center}
.transparent{background:transparent}
`;

const cards = {
  title: `<div class="c"><img src="${NEURO}" style="width:430px;margin-bottom:28px">
    <div style="font-size:112px;font-weight:700;letter-spacing:-3px">NeuroMuse</div>
    <div style="font-size:44px;font-weight:500;color:#D9D9D9;margin-top:14px">The Muse with a cortex.</div></div>`,
  problem: `<div class="c" style="gap:34px">
    <div class="k">Every assistant, today</div>
    <div style="font-size:64px;font-weight:600;color:#9AA0A6">"What do you think of this photo?"</div>
    <div style="font-size:120px;font-weight:700;letter-spacing:-2px">"Looks great!"</div>
    <div style="font-size:48px;font-weight:500"><span class="red">It never looked.</span> And it cannot say why.</div></div>`,
  idea: `<div class="c" style="gap:30px">
    <div class="k">The idea</div>
    <div style="font-size:84px;font-weight:700;letter-spacing:-2px;line-height:1.1">Give the Muse a cortex.</div>
    <div style="font-size:40px;color:#D9D9D9;line-height:1.45;max-width:1350px">Meta's <b>TRIBE v2</b> predicts how a human cortex responds,<br>20,484 points, every second. <b>Muse Spark</b> speaks only from that.</div></div>`,
  sec_glasses: `<div class="c" style="gap:22px"><div class="k">01 · On your face</div><div style="font-size:92px;font-weight:700;letter-spacing:-2px">It sees what you see.</div></div>`,
  sec_lab: `<div class="c" style="gap:22px"><div class="k">02 · Looks first, then speaks</div><div style="font-size:92px;font-weight:700;letter-spacing:-2px">Evidence before opinion.</div></div>`,
  sec_loop: `<div class="c" style="gap:22px"><div class="k">03 · The brain directs the craft</div><div style="font-size:92px;font-weight:700;letter-spacing:-2px">It critiques. Then it makes.</div></div>`,
  sec_memory: `<div class="c" style="gap:22px"><div class="k">04 · Memory in brain states</div><div style="font-size:92px;font-weight:700;letter-spacing:-2px">It remembers how things felt.</div></div>`,
  numbers: `<div class="c" style="gap:40px">
    <div class="k">Honest numbers</div>
    <div style="font-size:30px;color:#D9D9D9;max-width:1500px;line-height:1.4">Why a cortex is a sound choice: on 2,500 rated photos, <b>360 cortical areas → 54 dims score 0.753 AUROC</b> vs the raw vision embedding 0.728 and 9 pooled regions 0.669. Same accuracy class, and every score names the areas behind it.</div>
    <div style="display:grid;grid-template-columns:repeat(3,480px);gap:28px">
      ${[
        ["0.88", "Human-likeness head", "holdout AUROC, HC3 text"],
        ["14 s", "per 6-second clip", "TRIBE v2 on a Modal L40S"],
        ["11 / 16", "human blind vote", "for the brain loop"],
        ["0.90", "blind judge, real site", "Algonauts: the one change accepted"],
        ["5 / 6", "live pages kept", "the gates refused worse redesigns"],
        ["0", "invented facts shipped", "every round is fact-checked"],
      ].map(([n, a, b]) => `<div style="border:1px solid #2A2D31;border-radius:22px;padding:30px 30px 28px;text-align:left;background:#0E0F11">
          <div style="font-size:72px;font-weight:700;letter-spacing:-2px" class="${n === "0" || n === "5 / 6" ? "red" : ""}">${n}</div>
          <div style="font-size:28px;font-weight:600;margin-top:8px">${a}</div>
          <div style="font-size:22px;color:#9AA0A6;margin-top:6px">${b}</div></div>`).join("")}
    </div></div>`,
  close: `<div class="c"><img src="${NEURO}" style="width:330px;margin-bottom:26px">
    <div style="font-size:84px;font-weight:700;letter-spacing:-2px">An opinion it can justify.</div>
    <div style="font-size:34px;color:#9AA0A6;margin-top:22px">NeuroMuse · TRIBE v2 × Muse Spark · github.com/yc9954/brainsense</div>
    <div style="font-size:24px;color:#5f6368;margin-top:14px">Meta Global AI Developer Hackathon 2026 · Indie track</div></div>`,
};

const g = (p) => img(p);
const tile = (src, cls = "") => `<div class="t ${cls}"><img src="${src}"></div>`;
const GRID_CSS = `.grid{position:absolute;inset:0;padding:30px 44px;display:flex;flex-direction:column;gap:10px}
 .h{font-size:30px;font-weight:700;font-style:italic;text-align:center;letter-spacing:-.3px}
 .row{display:flex;gap:14px;align-items:stretch;flex:none;min-height:0}
 .side{flex:none;width:210px;align-self:center;border:1.5px solid #3a3d42;border-radius:14px;padding:12px;font-size:18px;line-height:1.25;color:#D9D9D9;text-align:center;background:#0E0F11;overflow-wrap:anywhere}
 .side b{color:#fff}.side .r{color:#C0504D;font-weight:700}
 .cells{display:flex;gap:4px;flex:1;min-width:0;min-height:0;height:100%}
 .t{flex:1;position:relative;min-width:0;border:1px solid #2A2D31;background:#111;overflow:hidden;border-radius:4px}
 .t img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block}
 .win{outline:3px solid #C0504D;outline-offset:-3px;z-index:1}
 .sub{display:flex;flex-direction:column;gap:4px;flex:1;min-width:0;height:100%}
 .sub .cells{flex:1;height:auto}
 .tag{position:absolute;font-size:15px;letter-spacing:2px;color:#9AA0A6}`;
const SAMPLES = ["popup", "menu", "bakery", "window", "shelf", "posters"].map((n) => g(`app/apps/mobile/assets/sample-${n}.jpg`));
const L5 = (n) => g(`results/showcase/studio/living5/${n}.png`);
const AD = (t, i) => "data:image/png;base64," + fs.readFileSync(`${OUT}/g/ad_${t}_${i}.png`).toString("base64");
cards.grid = `<div class="grid">
  <div class="h">Real-world site · evolved, not replaced</div>
  <div class="row" style="height:200px"><div class="side"><b>algonauts&shy;project.com</b><br>live page → one round</div>
    <div class="cells">${tile(g("docs/img/algonauts-before.png"))}${tile(g("docs/img/algonauts-after.png"), "win")}</div>
    <div class="side">blind judge<br><span class="r">0.90</span><br>facts unchanged</div></div>
  <div class="h">3D room · modelled in Blender, round by round</div>
  <div class="row" style="height:170px"><div class="side"><b>"nothing to hold"</b><br>empty first plan</div>
    <div class="cells">${tile(L5("r0"))}${tile(L5("r1"))}${tile(L5("r3"))}${tile(L5("r5"))}${tile(L5("best_hero"), "win")}</div>
    <div class="side">brain<br><span class="r">0.32 → 0.49</span><br>judge 0.13 → 0.40</div></div>
  <div class="h">12-second ad · one shot vs brain-directed, second by second</div>
  <div class="row" style="height:230px"><div class="side"><b>serum brief</b><br>top: one shot<br>bottom: Blender hero</div>
    <div class="sub"><div class="cells" style="height:113px">${[0, 1, 2].map((i) => tile(AD("r0", i))).join("")}</div>
      <div class="cells" style="height:113px">${[0, 1, 2].map((i) => tile(AD("r1", i))).join("")}</div></div>
    <div class="side">one shot kept<br><span class="r">0 invented facts</span><br>in the loop's clip</div></div>
  <div class="h">Everyday scenes · what it is asked about through the glasses</div>
  <div class="row" style="height:150px"><div class="side"><b>"What do you think?"</b><br>six real scenes</div>
    <div class="cells">${SAMPLES.map((s) => tile(s)).join("")}</div>
    <div class="side">one brain<br><span class="r">five heads</span><br>each with a confidence</div></div>
</div>`;

// evidence panels: the right third of the frame, next to each example (paper-figure style)
const panel = (k, title, rows) => `<div style="position:absolute;top:0;right:0;width:610px;height:1080px;background:#050506;border-left:1px solid #1f2125;padding:58px 46px 40px;display:flex;flex-direction:column;gap:22px">
  <div style="font-size:19px;letter-spacing:4px;text-transform:uppercase;color:#C0504D">${k}</div>
  <div style="font-size:40px;font-weight:700;letter-spacing:-1px;line-height:1.12">${title}</div>
  ${rows.map(([h, t]) => `<div><div style="font-size:16px;letter-spacing:3px;text-transform:uppercase;color:#9AA0A6;margin-bottom:6px">${h}</div><div style="font-size:24px;line-height:1.38;color:#E6E6E6">${t}</div></div>`).join("")}
</div>`;
const panels = {
  pn_glasses: panel("01 · Glasses", "It looks before it speaks.", [
    ["What happens", "The last 6 s of what you see go to <b>TRIBE v2</b>: a predicted human cortex, 20,484 points, every second. Calibrated heads score it; Muse Spark speaks from the scores."],
    ["Why it is new", "The opinion is a <b>measurement</b>, not a caption. It names the region that fired and its percentile, and says when the signal is faint."],
    ["Result", "<b>14 s</b> per clip on an L40S (from 43 s). Five heads, holdout AUROC <b>0.58–0.88</b>, each with a confidence."],
    ["Why a cortex", "One representation for video, sound and text, and an answer that can say <i>why</i>."],
  ]),
  pn_phones: panel("02 · Chat and Lab", "Evidence first, then opinion.", [
    ["What happens", "The cortex plays second by second, then the heads score it. Every like is stored as a brain state and your taste model refits."],
    ["Why it is new", "Memory in <b>brain states, not words</b>: recall is cosine similarity in cortex space, and learning costs zero prompt tokens."],
    ["Result", "Aesthetic head AUROC <b>0.72</b> (ECE 0.04). Personal head so far: 12 synthetic answers, 0.56 vs crowd 0.67, reported as is."],
    ["Why a cortex", "Features are <b>360 named cortical areas</b>, so every score back-projects to regions a person can understand."],
  ]),
  pn_room: panel("03 · Blender", "The brain directs the craft.", [
    ["What happens", "The agent builds a room in Blender. The cortex reads each render and says what it felt; the agent changes the scene."],
    ["Why it is new", "Perception in the loop for 3D: the critique is a brain pattern (\u201cobject regions quiet\u201d), turned into a concrete edit."],
    ["Result", "Brain score <b>0.32 → 0.49</b>, designer judge <b>0.13 → 0.40</b> over 8 rounds."],
    ["Why a cortex", "A reward that is the same signal people's brains give, not the model grading its own taste."],
  ]),
  pn_site: panel("04 · A real website", "Evolve, don't replace.", [
    ["What happens", "The live page is harvested (real logo, map, photos), critiqued by the cortex and rebuilt around its own assets."],
    ["Why it is new", "Three gates before any win: <b>no invented facts</b>, density kept, and a <b>blind judge</b> that wrote neither side."],
    ["Result", "Six real sites: <b>one accepted</b> (blind P = 0.90), five refused. Human blind vote on generated pages and ads: <b>11 / 16</b> for the brain loop."],
    ["Why a cortex", "The brain is the critic, the blind judge the verdict, so the loop cannot game its own score."],
  ]),
  pn_ad: panel("05 · A 12-second ad", "Second by second.", [
    ["What happens", "Brief → one-shot ad → the cortex watches each clip at 1 Hz → an art director picks a tool (a Blender product render, pacing, type) → rebuild."],
    ["Why it is new", "Only a brain model gives a <b>time course</b>: when attention peaks, when it fades, where the hook lands."],
    ["Result", "Ad clips vs one shot: <b>3 / 3</b> blind wins (P ≥ 0.85). Serum maker: attention peak <b>12 s → 8 s</b>, zero invented facts; the one-shot was still kept, and we say so."],
    ["Why a cortex", "A stills judge cannot see time. The cortex can."],
  ]),
};

// lower-third labels drawn over footage (transparent PNG)
const label = (k, t) => `<div style="position:absolute;left:0;right:0;bottom:0;height:128px;display:flex;align-items:center;gap:26px;padding:0 64px;background:#000">
  <div style="display:inline-flex;flex:none;align-items:center;gap:12px;border:1px solid rgba(255,255,255,.22);border-radius:999px;padding:10px 20px">
    <div style="width:11px;height:11px;border-radius:6px;background:#C0504D"></div><div style="font-size:21px;letter-spacing:3px;text-transform:uppercase;color:#D9D9D9">${k}</div></div>
  <div style="font-size:33px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${t}</div></div>`;
const labels = {
  lb_glasses: label("Glasses mode · live", "“What do you think?” The clip goes to TRIBE v2, the answer comes back spoken."),
  lb_phones: `<div style="position:absolute;top:34px;left:0;right:0;display:flex;justify-content:center;gap:140px">
     ${[["Chat · brain card", "Cortex first, then the heads"], ["Lab · memory, live", "Every like becomes a brain state"]].map(([k, t]) => `<div style="width:470px;text-align:center">
     <div style="font-size:21px;letter-spacing:3px;text-transform:uppercase;color:#C0504D">${k}</div><div style="font-size:30px;font-weight:600;margin-top:6px">${t}</div></div>`).join("")}</div>`,
  lb_trail: label("Decision trail · Blender", "Neuro says what it felt. The agent changes the room. Repeat."),
  lb_ad: label("Ad maker · 12-second clip", "Facts gated. Losing rounds thrown away, even when they look good."),
  lb_algo: label("A real site · blind judge 0.90", "Evolved, not replaced: the real emblem kept, the mission brought forward."),
  lb_arch: label("Architecture", "Only the engram store holds state. Only sleep writes. The voice holds no memory."),
};

const browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" });
const page = await (await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 })).newPage();
for (const [name, body] of Object.entries(cards)) {
  await page.setContent(`<html><head><style>${CSS}${GRID_CSS}</style></head><body>${body}</body></html>`);
  await page.waitForTimeout(150);
  await page.screenshot({ path: `${OUT}/${name}.png` });
}
for (const [name, body] of Object.entries({ ...labels, ...panels })) {
  await page.setContent(`<html><head><style>${CSS} body{background:transparent}</style></head><body>${body}</body></html>`);
  await page.waitForTimeout(100);
  await page.screenshot({ path: `${OUT}/${name}.png`, omitBackground: true });
}
// figures rendered large
for (const [name, file, w, h] of [["layers", "docs/layers.svg", 1240, 660], ["arch", "docs/architecture.svg", 1320, 620]]) {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.setContent(`<html><body style="margin:0;background:#000;display:flex;align-items:center;justify-content:center;width:1920px;height:1080px"><img src="data:image/svg+xml;base64,${fs.readFileSync(ROOT + "/" + file).toString("base64")}" style="width:${Math.round(1800)}px"></body></html>`);
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/${name}.png` });
}
await browser.close();
console.log("cards ok");
