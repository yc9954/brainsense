import { createHash, randomUUID } from "node:crypto";
import { link, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { join, resolve, sep } from "node:path";
import type { Artifact } from "../../../packages/domain/src/index.ts";
import { fillPdf, inspectPdf } from "../../../packages/integrations/src/pdf.ts";
import type { Auth } from "./auth.ts";
import type { Config } from "./config.ts";
import type { Store } from "./db.ts";
import { AppError } from "./errors.ts";

/** Sniff images/videos by magic bytes so BrainSense can look at photos, not only PDFs. */
export function sniffMime(bytes: Uint8Array, name = ""): string {
  const b = bytes;
  const ascii = (o: number, n: number) => String.fromCharCode(...b.subarray(o, o + n));
  if (b.length >= 4 && b[0] === 0x25 && b[1] === 0x50 && b[2] === 0x44 && b[3] === 0x46)
    return "application/pdf";
  if (b.length >= 3 && b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) return "image/jpeg";
  if (b.length >= 8 && b[0] === 0x89 && ascii(1, 3) === "PNG") return "image/png";
  if (b.length >= 6 && (ascii(0, 6) === "GIF87a" || ascii(0, 6) === "GIF89a")) return "image/gif";
  if (b.length >= 12 && ascii(0, 4) === "RIFF" && ascii(8, 4) === "WEBP") return "image/webp";
  if (b.length >= 4 && b[0] === 0x1a && b[1] === 0x45 && b[2] === 0xdf && b[3] === 0xa3)
    return "video/webm";
  if (b.length >= 3 && ((b[0] === 0xff && (b[1] & 0xe0) === 0xe0) || ascii(0, 3) === "ID3"))
    return "audio/mpeg";
  if (b.length >= 12 && ascii(0, 4) === "RIFF" && ascii(8, 4) === "WAVE") return "audio/wav";
  if (b.length >= 4 && ascii(0, 4) === "fLaC") return "audio/flac";
  if (b.length >= 4 && ascii(0, 4) === "OggS") return "audio/ogg";
  if (b.length >= 12 && ascii(4, 4) === "ftyp") {
    const brand = ascii(8, 4);
    if (/^(heic|heix|hevc|mif1|msf1)/.test(brand)) return "image/heic";
    if (/^(M4A|M4B)/.test(brand)) return "audio/mp4";
    if (/^qt/.test(brand)) return "video/quicktime";
    return "video/mp4";
  }
  const ext = name.toLowerCase().split(".").at(-1) ?? "";
  if (["jpg", "jpeg"].includes(ext)) return "image/jpeg";
  if (ext === "png") return "image/png";
  if (["mp4", "m4v"].includes(ext)) return "video/mp4";
  if (ext === "mov") return "video/quicktime";
  if (ext === "webm") return "video/webm";
  if (ext === "mp3") return "audio/mpeg";
  if (ext === "wav") return "audio/wav";
  if (ext === "m4a") return "audio/mp4";
  return "application/pdf";
}
export const isMedia = (mime: string) => /^(image|video|audio)\//.test(mime);

const BRAINSENSE_URL = (process.env.BRAINSENSE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
/**
 * Pre-analyze a photo/clip the moment it is attached, in the background, so brain_eval finds the
 * result already cached (its HEAD /eval check) instead of paying the ~25 s TRIBE round trip while the
 * user waits. Failures are silent: brain_eval falls back to analyzing on demand.
 */
export function prewarmBrain(artifactId: string, name: string, bytes: Uint8Array): void {
  const body = JSON.stringify({
    video_b64: Buffer.from(bytes).toString("base64"),
    filename: name,
    item_id: `om_${artifactId}`,
  });
  void fetch(`${BRAINSENSE_URL}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  })
    .then((r) => console.log(`[BrainSense] prewarm ${name} → ${r.status}`))
    .catch((e) =>
      console.log(`[BrainSense] prewarm failed: ${e instanceof Error ? e.message : e}`),
    );
}

const FILE_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function sanitizeFileName(name: string): string {
  const base = name.split(/[\\/]/).at(-1) ?? "document.pdf";
  // Slice code points, not UTF-16 units, so a surrogate pair is never split in half.
  const cleaned = Array.from(base)
    .filter((character) => character.charCodeAt(0) >= 32 && character.charCodeAt(0) !== 127)
    .slice(0, 180)
    .join("");
  return cleaned || "document.pdf";
}

function assertFileId(id: string): void {
  if (!FILE_ID.test(id)) throw new AppError("File not found", 404);
}

// Keyed operations need the same ID on every retry, so the ID is derived from the
// owner and operation key instead of random. It is shaped as a version 5 UUID
// (first 128 bits of a SHA-256 hash, version and variant bits set) so it is
// accepted anywhere a random file UUID is.
export function deterministicFileId(owner: string, operationKey: string): string {
  const bytes = createHash("sha256")
    .update(JSON.stringify([owner, operationKey]))
    .digest()
    .subarray(0, 16);
  bytes[6] = (bytes[6] & 0x0f) | 0x50;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export class Files {
  constructor(
    private readonly db: Store,
    private readonly config: Config,
    private readonly auth: Auth,
  ) {}
  async import(
    owner: string,
    name: string,
    bytes: Uint8Array,
    source: string,
    parentId?: string,
    operationKey?: string,
  ): Promise<Artifact> {
    const id = operationKey === undefined ? randomUUID() : deterministicFileId(owner, operationKey);
    if (operationKey !== undefined) {
      const existing = await this.db.get<Artifact>(owner, "files", id);
      if (existing) return this.signed(owner, existing);
    }
    const mimeType = sniffMime(bytes, name);
    const media = isMedia(mimeType);
    if (bytes.length > (media ? 60 : 10) * 1024 * 1024)
      throw new AppError(
        media ? "Photos and clips must be 60 MB or smaller" : "PDFs must be 10 MB or smaller",
        413,
      );
    let metadata = media ? { pageCount: 0, fields: [] as never[] } : await inspectPdf(bytes);
    if (metadata.pageCount > 500) throw new AppError("PDFs must have 500 pages or fewer", 422);
    const directory = join(this.config.dataDir, "files");
    await mkdir(directory, { recursive: true, mode: 0o700 });
    const path = this.pathFor(id);
    if (operationKey === undefined) {
      await writeFile(path, bytes, { mode: 0o600, flag: "wx" });
    } else {
      const temporary = `${path}.${randomUUID()}.tmp`;
      try {
        await writeFile(temporary, bytes, { mode: 0o600, flag: "wx" });
        try {
          await link(temporary, path);
        } catch (error) {
          if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
          bytes = await readFile(path);
          metadata = media ? { pageCount: 0, fields: [] as never[] } : await inspectPdf(bytes);
        }
      } finally {
        await rm(temporary, { force: true });
      }
    }
    const safeName = sanitizeFileName(name);
    const artifact: Artifact = {
      id,
      name: safeName,
      mimeType,
      size: bytes.length,
      pageCount: metadata.pageCount,
      fields: metadata.fields,
      url: "",
      createdAt: new Date().toISOString(),
      source,
      parentId,
    };
    if (operationKey === undefined) {
      await this.db.put(owner, "files", artifact);
      if (/^(image|video)\//.test(mimeType)) prewarmBrain(id, safeName, bytes);
      return this.signed(owner, artifact);
    }
    const persisted = await this.db.insertIfAbsent(owner, "files", artifact);
    return this.signed(owner, persisted ?? (await this.get(owner, id)));
  }
  signed(owner: string, file: Artifact): Artifact {
    return { ...file, url: this.auth.sign(owner, `/api/files/${file.id}/content`) };
  }
  async list(owner: string) {
    return (await this.db.list<Artifact>(owner, "files")).map((file) => this.signed(owner, file));
  }
  async get(owner: string, id: string) {
    assertFileId(id);
    const file = await this.db.get<Artifact>(owner, "files", id);
    if (!file) throw new AppError("File not found", 404);
    return file;
  }
  private pathFor(id: string): string {
    assertFileId(id);
    const directory = resolve(this.config.dataDir, "files");
    const resolved = resolve(directory, `${id}.pdf`);
    if (!resolved.startsWith(`${directory}${sep}`)) throw new AppError("File not found", 404);
    return resolved;
  }
  async bytes(owner: string, id: string) {
    await this.get(owner, id);
    return readFile(this.pathFor(id));
  }
  async fill(
    owner: string,
    id: string,
    values: Record<string, string | boolean>,
    operationKey?: string,
  ) {
    const file = await this.get(owner, id);
    const bytes = await this.bytes(owner, id);
    const output = await fillPdf(bytes, values);
    return this.import(
      owner,
      `${file.name.replace(/\.pdf$/i, "")} — filled.pdf`,
      output,
      `Filled from ${file.name}`,
      id,
      operationKey === undefined
        ? undefined
        : JSON.stringify([
            "fill",
            operationKey,
            id,
            Object.keys(values)
              .sort()
              .map((name) => [name, values[name]]),
          ]),
    );
  }
}
