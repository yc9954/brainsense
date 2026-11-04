import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Hono } from "hono";
import { AppError } from "./errors.ts";
import type { Files } from "./files.ts";

/**
 * Glasses emulator: the phone (or the laptop webcam) keeps a rolling clip of what the user is
 * looking at. When they ask "이거 어때?", the latest clip lands here, is normalised to a short
 * H.264 MP4 (TRIBE's event pipeline wants a plain mp4; browsers record webm, iPhones mov) and
 * imported as an artifact named glasses_<ts>.mp4 so brain_eval / look_at can pick it up.
 */
export async function transcodeClip(input: Buffer, ext: string, seconds = 6): Promise<Buffer> {
  const dir = await mkdtemp(join(tmpdir(), "glasses-"));
  const src = join(dir, `in.${ext || "webm"}`);
  const dst = join(dir, "out.mp4");
  try {
    await writeFile(src, input);
    await new Promise<void>((resolve, reject) => {
      const isImage = /^(jpe?g|png|webp|heic|heif|gif)$/i.test(ext);
      const p = spawn("ffmpeg", [
        "-loglevel", "error", "-y",
        ...(isImage ? ["-loop", "1"] : []),
        "-i", src,
        "-t", String(seconds),
        "-vf", "scale=512:-2,fps=8,format=yuv420p",
        "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-movflags", "+faststart",
        dst,
      ]);
      let err = "";
      p.stderr.on("data", (d) => (err += d));
      p.on("error", reject);
      p.on("close", (code) => (code === 0 ? resolve() : reject(new Error(err || `ffmpeg exit ${code}`))));
    });
    return await readFile(dst);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/** Middle frame of a clip as JPEG (what look_at sends to the vision model). */
export async function frameFromVideo(input: Buffer, ext = "mp4"): Promise<Buffer> {
  const dir = await mkdtemp(join(tmpdir(), "glasses-frame-"));
  const src = join(dir, `in.${ext}`);
  const dst = join(dir, "frame.jpg");
  try {
    await writeFile(src, input);
    await new Promise<void>((resolve, reject) => {
      const p = spawn("ffmpeg", [
        "-loglevel", "error", "-y", "-ss", "1.5", "-i", src, "-frames:v", "1",
        "-vf", "scale=896:-2", "-q:v", "3", dst,
      ]);
      let err = "";
      p.stderr.on("data", (d) => (err += d));
      p.on("error", reject);
      p.on("close", (code) => (code === 0 ? resolve() : reject(new Error(err || `ffmpeg exit ${code}`))));
    });
    return await readFile(dst);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

export function glassesRoutes(files: Files) {
  const app = new Hono<{ Variables: { owner: string } }>();
  app.post("/clip", async (c) => {
    const data = await c.req.parseBody();
    const file = data.file;
    if (!(file instanceof File)) throw new AppError("Send the clip as multipart field 'file'");
    const raw = Buffer.from(await file.arrayBuffer());
    if (raw.length < 1024) throw new AppError("The clip is empty; keep the camera open a few seconds first");
    const ext = (file.name.split(".").at(-1) || "webm").toLowerCase().replace(/[^a-z0-9]/g, "") || "webm";
    let mp4: Buffer;
    try {
      mp4 = await transcodeClip(raw, ext);
    } catch (error) {
      throw new AppError(`Could not transcode the clip: ${error instanceof Error ? error.message : String(error)}`, 422);
    }
    const name = `glasses_${new Date().toISOString().replace(/[:.]/g, "-")}.mp4`;
    return c.json(await files.import(c.get("owner"), name, new Uint8Array(mp4), "Glasses camera"), 201);
  });
  return app;
}
