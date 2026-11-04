import { defineTool } from "@copilotkit/runtime/v2";
import { z } from "zod";
import { frameFromVideo } from "../glasses-routes.ts";
import type { AgentService } from "./service.ts";

/**
 * look_at: what the user is looking at through the glasses (or the phone standing in for them).
 * Sends one frame of the attached clip/photo to Muse Spark's vision input and returns a dense
 * description, any visible text verbatim, and a coarse kind. brain_eval tells the agent how a
 * cortex responds; look_at tells it WHAT it is responding to, so "is this text good?" can judge the text.
 */
export const glassesInstructions =
  " Glasses mode: an attached file whose name starts with 'glasses_' is a clip from the user's own camera, i.e. what they are looking at right now. For such a clip call look_at(artifact_id) first, then brain_eval(artifact_id), then answer about THAT content in the first-person brain voice. If the user asks about a text ('is this copy good?'), judge the text look_at transcribed (hook, clarity, tone, who it is for) and tie in the brain read only where it adds something; for 'how is this video?' / 'what do you think?' lead with brain_eval and use look_at to name what you saw. If look_at says the frame is blurry or empty, say so and ask them to hold the phone steady on the thing for 3 seconds.";

const VISION_PROMPT = `You are the eyes of an assistant. Describe this frame from the user's camera for someone who cannot see it.
Return STRICT JSON only, no prose, with keys:
"kind": one of "text" (a post, article, chat, document, sign), "video" (a screen playing a video), "product", "scene", "person", "screen" (other UI), "unclear";
"description": 2-4 sentences, concrete (what, where, colours, layout, what is happening);
"text": every piece of readable text, verbatim, in reading order, "" if none;
"language": language of the text or "";
"quality": "ok" | "blurry" | "dark" | "empty".`;

async function describeFrame(jpeg: Buffer, signal: AbortSignal) {
  const baseUrl = (process.env.OPENAI_BASE_URL ?? "https://api.meta.ai/v1").replace(/\/$/, "");
  const key = process.env.OPENAI_API_KEY ?? "";
  const model = (process.env.MODEL ?? "openai/muse-spark-1.3").replace(/^openai\//, "");
  const res = await fetch(`${baseUrl}/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
    body: JSON.stringify({
      model,
      max_tokens: 2500,
      reasoning_effort: "low",
      messages: [
        {
          role: "user",
          content: [
            { type: "text", text: VISION_PROMPT },
            { type: "image_url", image_url: { url: `data:image/jpeg;base64,${jpeg.toString("base64")}` } },
          ],
        },
      ],
    }),
    signal,
  });
  if (!res.ok) throw new Error(`vision ${res.status}: ${(await res.text()).slice(0, 200)}`);
  const body = (await res.json()) as { choices?: { message?: { content?: string } }[] };
  const text = body.choices?.[0]?.message?.content ?? "";
  const m = text.match(/\{[\s\S]*\}/);
  if (!m) return { kind: "unclear", description: text.slice(0, 600), text: "", language: "", quality: "ok" };
  try {
    return JSON.parse(m[0]) as { kind: string; description: string; text: string; language: string; quality: string };
  } catch {
    return { kind: "unclear", description: text.slice(0, 600), text: "", language: "", quality: "ok" };
  }
}

export function lookAtTool(service: AgentService, owner: string, signal: AbortSignal) {
  return defineTool({
    name: "look_at",
    description:
      "See what the user is looking at through the glasses/phone camera: describes the attached clip or photo, transcribes any visible text verbatim, and classifies it (text / video / product / scene / person / screen). Pass artifact_id of the attached glasses_ clip (or any image). Data only; quote the transcription when judging a text.",
    parameters: z.object({ artifact_id: z.string().trim().max(200) }),
    execute: async ({ artifact_id }) => {
      try {
        const file = await service.files.get(owner, artifact_id);
        const bytes = Buffer.from(await service.files.bytes(owner, artifact_id));
        let jpeg: Buffer;
        if (/^video\//.test(file.mimeType)) jpeg = await frameFromVideo(bytes, file.name.split(".").at(-1) || "mp4");
        else if (/^image\/jpeg$/.test(file.mimeType)) jpeg = bytes;
        else if (/^image\//.test(file.mimeType)) jpeg = await frameFromVideo(bytes, file.name.split(".").at(-1) || "png");
        else return { error: `look_at needs a clip or photo, got ${file.mimeType}` };
        const seen = await describeFrame(jpeg, signal);
        return { artifact_id, name: file.name, ...seen };
      } catch (error) {
        return { error: `look_at failed: ${error instanceof Error ? error.message : String(error)}` };
      }
    },
  });
}
