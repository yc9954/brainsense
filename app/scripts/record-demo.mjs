// Records a demo of the BrainSense chat (sample photo → "이거 어때?" → live cortex card → first-person
// brain reply → "왜?") with Playwright's built-in video recorder.
//   node scripts/record-demo.mjs [outDir]
import { chromium } from "/Users/yuchanlee/brainsense-hackathon/openmuse/node_modules/.pnpm/playwright@1.62.1/node_modules/playwright/index.mjs";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const out = process.argv[2] || join(process.cwd(), "..", "brainsense", "results", "demo");
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_EXE, args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const ctx = await browser.newContext({
  viewport: { width: 1280, height: 800 },
  recordVideo: { dir: out, size: { width: 1280, height: 800 } },
  locale: "ko-KR",
});
const page = await ctx.newPage();
const log = (m) => console.log(new Date().toISOString().slice(11, 19), m);
try {
  await page.goto("http://localhost:8081", { waitUntil: "load" });
  await page.getByPlaceholder("Message…").waitFor({ timeout: 60000 });
  await page.waitForTimeout(3000);
  log("open attach card");
  await page.getByRole("button", { name: "Attach a document" }).click();
  await page.getByLabel("샘플 A 사진 첨부").click();
  await page.waitForTimeout(2500);
  await page.getByText("Done", { exact: true }).click();
  const box = page.getByPlaceholder("Message…");
  await box.click();
  await box.pressSequentially("이거 어때?", { delay: 90 });
  await page.waitForTimeout(600);
  const cardsBefore = await page.evaluate(() => document.body.innerText.split("MODEL PREDICTION").length - 1);
  await page.getByRole("button", { name: "Send message" }).click();
  log("sent; waiting for a NEW cortex card");
  // the main thread persists server-side, so count cards before sending and wait for one more
  await page.waitForFunction(
    (n) => document.body.innerText.split("MODEL PREDICTION").length - 1 > n,
    cardsBefore,
    { timeout: 180000 },
  );
  log("card up");
  await page.waitForTimeout(2500);
  // let the bust turn and the reply stream in
  for (let i = 0; i < 6; i++) {
    await page.mouse.wheel(0, 120);
    await page.waitForTimeout(1500);
  }
  await page.waitForTimeout(8000);
  await page.mouse.wheel(0, 1200);
  await page.waitForTimeout(4000);
  log("follow-up: wait until the reply finished streaming");
  await page.getByRole("button", { name: "Send message" }).waitFor({ timeout: 150000 });
  await page.waitForTimeout(1500);
  await box.click();
  await box.pressSequentially("왜 그렇게 생각해? 어디가 제일 켜졌어?", { delay: 70 });
  await page.getByRole("button", { name: "Send message" }).click();
  await page.getByRole("button", { name: "Send message" }).waitFor({ timeout: 150000 });
  await page.waitForTimeout(6000);
  await page.mouse.wheel(0, 1200);
  await page.waitForTimeout(5000);
} catch (e) {
  log(`error: ${e instanceof Error ? e.message : e}`);
} finally {
  const video = page.video();
  await ctx.close();
  const path = video ? await video.path() : null;
  await browser.close();
  log(`video: ${path}`);
}
