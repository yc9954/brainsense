import { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, Text, View } from "react-native";
import type { Artifact } from "../../../packages/domain/src";
import type { MuseApi } from "./api";
import { SAMPLES } from "./brainsense";
import { GlassesChrome, type GlassesState } from "./glasses-ui";

/**
 * Glasses emulator (web): the webcam stands in for Ray-Ban Meta. Keeps a rolling 6 s clip of
 * what you are looking at; a question uploads the latest clip and hands it to the agent as a
 * glasses_ attachment (look_at + brain_eval run from there). The answer comes back as captions
 * over the POV and is spoken aloud.
 */
const SEGMENT_MS = 6000;

/** No camera at all (CI, a desktop without webcam): a canvas slideshow of the bundled samples. */
/** While the brain is looking at a clip and speaking about it, the demo feed stays on the frame it was asked about. */
let demoHold = false;
let heldFrame = -1;
export function holdDemoFeed(hold: boolean) {
  demoHold = hold;
  if (!hold) heldFrame = -1;
}

async function demoFeed(): Promise<MediaStream> {
  const canvas = document.createElement("canvas");
  canvas.width = 960;
  canvas.height = 540;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("canvas unavailable");
  const imgs = await Promise.all(
    SAMPLES.map(
      (sm) =>
        new Promise<HTMLImageElement | null>((resolve) => {
          const im = new Image();
          im.onload = () => resolve(im);
          im.onerror = () => resolve(null);
          im.src = typeof sm.source === "object" ? sm.source.uri : "";
        }),
    ),
  );
  const t0 = Date.now();
  const draw = () => {
    let i = Math.floor((Date.now() - t0) / 7000) % Math.max(1, imgs.length);
    if (demoHold) {
      if (heldFrame < 0) heldFrame = i;
      i = heldFrame;
    }
    const im = imgs[i];
    ctx.fillStyle = "#0a0a0c";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (im) {
      const k = Math.max(canvas.width / im.width, canvas.height / im.height);
      const w = im.width * k;
      const h = im.height * k;
      ctx.drawImage(im, (canvas.width - w) / 2, (canvas.height - h) / 2, w, h);
    }
    ctx.fillStyle = "rgba(0,0,0,0.45)";
    ctx.fillRect(canvas.width / 2 - 92, 8, 184, 24);
    ctx.fillStyle = "rgba(255,255,255,0.85)";
    ctx.font = "600 12px -apple-system, system-ui, sans-serif";
    ctx.fillText("DEMO FEED · no camera", canvas.width / 2 - 78, 25);
    if (!(canvas as unknown as { __stopped?: boolean }).__stopped) requestAnimationFrame(draw);
  };
  draw();
  const stream = (canvas as HTMLCanvasElement & { captureStream: (fps?: number) => MediaStream }).captureStream(8);
  return stream;
}

export function GlassesView({
  api,
  onAsk,
  onClose,
  reply,
  thinking,
}: {
  api: MuseApi;
  onAsk: (text: string, artifact: Artifact) => void | Promise<void>;
  onClose: () => void;
  reply?: string;
  thinking?: boolean;
}) {
  const host = useRef<View>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const lastClip = useRef<{ blob: Blob; at: number } | null>(null);
  const currentChunks = useRef<Blob[]>([]);
  const currentStart = useRef(0);
  const stopping = useRef<((b: Blob) => void) | null>(null);
  const replyAtAsk = useRef<string | undefined>(undefined);
  const [state, setState] = useState<GlassesState>("starting");
  useEffect(() => {
    // release the held demo frame once the brain has finished speaking
    if (state === "watching") holdDemoFeed(false);
  }, [state]);
  const [status, setStatus] = useState("Starting camera…");
  const [error, setError] = useState("");
  const [question, setQuestion] = useState<string | undefined>();
  const [shown, setShown] = useState<string | undefined>();
  const [clipAge, setClipAge] = useState<number | null>(null);
  const [facing, setFacing] = useState<"environment" | "user">("environment");

  const startSegment = useCallback(() => {
    const s = stream.current;
    if (!s) return;
    const mime = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm", "video/mp4"].find(
      (m) => typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(m),
    );
    const r = new MediaRecorder(s, mime ? { mimeType: mime, videoBitsPerSecond: 1_200_000 } : undefined);
    currentChunks.current = [];
    currentStart.current = Date.now();
    r.ondataavailable = (e) => {
      if (e.data.size) currentChunks.current.push(e.data);
    };
    r.onstop = () => {
      const blob = new Blob(currentChunks.current, { type: r.mimeType || "video/webm" });
      const dur = Date.now() - currentStart.current;
      if (dur >= 1500 && blob.size > 2048) lastClip.current = { blob, at: Date.now() };
      const waiter = stopping.current;
      stopping.current = null;
      if (waiter) waiter(blob);
      else if (stream.current) startSegment();
    };
    r.start();
    recorder.current = r;
    setTimeout(() => {
      if (recorder.current === r && r.state === "recording") r.stop();
    }, SEGMENT_MS);
  }, []);

  // iPhone Safari over plain http has no getUserMedia (needs HTTPS): use the native camera through
  // a file input instead ("shoot with the phone camera"), one clip per question.
  const captureOnly = typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia || (typeof window !== "undefined" && window.isSecureContext === false);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const pendingQuestion = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (captureOnly) {
      setState("watching");
      setStatus("Shoot with the phone camera to ask");
      return () => {
        cancelled = true;
      };
    }
    (async () => {
      try {
        // a laptop webcam has no "environment" camera: fall back to any camera, then to a demo feed
        let demo = false;
        const s = await navigator.mediaDevices
          .getUserMedia({ video: { facingMode: facing, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false })
          .catch(() => navigator.mediaDevices.getUserMedia({ video: true, audio: false }))
          .catch(async () => {
            demo = true;
            return demoFeed();
          });
        if (cancelled) {
          for (const t of s.getTracks()) t.stop();
          return;
        }
        stream.current = s;
        const el = host.current as unknown as HTMLDivElement | null;
        if (el && !videoRef.current) {
          const v = document.createElement("video");
          v.autoplay = true;
          v.muted = true;
          v.playsInline = true;
          Object.assign(v.style, { width: "100%", height: "100%", objectFit: "cover", display: "block" });
          el.appendChild(v);
          videoRef.current = v;
        }
        if (videoRef.current) {
          videoRef.current.srcObject = s;
          await videoRef.current.play().catch(() => undefined);
        }
        setState("watching");
        setStatus(demo ? "Demo feed · no camera" : "Watching · 6 s buffer");
        startSegment();
      } catch (e) {
        setState("error");
        setStatus("No camera");
        setError(`Could not open the camera: ${e instanceof Error ? e.message : String(e)}`);
      }
    })();
    const tick = setInterval(() => {
      setClipAge(lastClip.current ? Math.round((Date.now() - lastClip.current.at) / 1000) : null);
    }, 1000);
    return () => {
      cancelled = true;
      clearInterval(tick);
      const r = recorder.current;
      recorder.current = null;
      stopping.current = () => undefined;
      if (r && r.state !== "inactive") r.stop();
      for (const t of stream.current?.getTracks() ?? []) t.stop();
      stream.current = null;
      videoRef.current?.remove();
      videoRef.current = null;
    };
  }, [facing, startSegment, captureOnly]);

  // the agent's answer arrives through the chat behind us
  useEffect(() => {
    if (state !== "thinking") return;
    if (reply && reply !== replyAtAsk.current && !thinking) {
      setShown(reply);
      setState("speaking");
      setStatus("Watching · 6 s buffer");
      const t = setTimeout(() => setState((s) => (s === "speaking" ? "watching" : s)), Math.min(20000, 2500 + reply.length * 90));
      return () => clearTimeout(t);
    }
  }, [reply, thinking, state]);

  /** Stop the running segment and return the best clip we have (current if ≥2.5 s, else the last full one). */
  const grabClip = useCallback(async (): Promise<Blob | null> => {
    const r = recorder.current;
    const runningFor = Date.now() - currentStart.current;
    if (r && r.state === "recording" && runningFor >= 2500) {
      const blob = await new Promise<Blob>((resolve) => {
        stopping.current = resolve;
        r.stop();
      });
      if (stream.current) startSegment();
      return blob;
    }
    return lastClip.current?.blob ?? null;
  }, [startSegment]);

  const upload = useCallback(
    async (text: string, file: File) => {
      const form = new FormData();
      form.append("file", file, file.name || "glasses.webm");
      const artifact = await api.request<Artifact>("/api/glasses/clip", form);
      setState("thinking");
      await onAsk(text, artifact);
    },
    [api, onAsk],
  );

  const ask = useCallback(
    async (text: string) => {
      setError("");
      setQuestion(text);
      setShown(undefined);
      replyAtAsk.current = reply;
      holdDemoFeed(true);
      if (captureOnly) {
        // open the phone's own camera; the upload continues in onCaptured
        pendingQuestion.current = text;
        setStatus("Shoot, then tap Use");
        fileInput.current?.click();
        return;
      }
      setState("capturing");
      try {
        const blob = await grabClip();
        if (!blob) throw new Error("Nothing captured yet. Point the camera for 2–3 more seconds.");
        const ext = blob.type.includes("mp4") ? "mp4" : "webm";
        await upload(text, new File([blob], `glasses.${ext}`, { type: blob.type || "video/webm" }));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setState("watching");
      }
    },
    [captureOnly, grabClip, reply, upload],
  );

  const onCaptured = useCallback(
    async (file: File | undefined) => {
      const text = pendingQuestion.current;
      pendingQuestion.current = null;
      if (!file || !text) {
        setStatus("Shoot with the phone camera to ask");
        return;
      }
      setState("capturing");
      setStatus("Sending the clip…");
      try {
        const ext = (file.name.split(".").pop() || (file.type.startsWith("image/") ? "jpg" : "mov")).toLowerCase();
        await upload(text, new File([file], `glasses.${ext}`, { type: file.type }));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setState("watching");
        setStatus("Shoot with the phone camera to ask");
      }
    },
    [upload],
  );

  // a real <input type=file capture> so iOS opens the camera app
  useEffect(() => {
    if (!captureOnly) return;
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "video/*,image/*";
    input.setAttribute("capture", "environment");
    input.style.display = "none";
    input.onchange = () => {
      void onCaptured(input.files?.[0]);
      input.value = "";
    };
    document.body.appendChild(input);
    fileInput.current = input;
    return () => {
      input.remove();
      fileInput.current = null;
    };
  }, [captureOnly, onCaptured]);

  return (
    <GlassesChrome
      state={state}
      status={`${status}${clipAge !== null && state === "watching" ? ` · last clip ${clipAge} s ago` : ""}`}
      question={question}
      reply={shown}
      error={error}
      onAsk={ask}
      onClose={onClose}
      onFlip={() => setFacing((f) => (f === "user" ? "environment" : "user"))}
    >
      <View ref={host} style={{ flex: 1, backgroundColor: "#0a0a0c" }}>
        {captureOnly ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Shoot with the phone camera"
            onPress={() => void ask(question ?? "What do you think?")}
            style={{ flex: 1, alignItems: "center", justifyContent: "center", gap: 10 }}
          >
            <Text style={{ color: "#fff", fontSize: 18, fontWeight: "600" }}>Tap to shoot with the phone camera</Text>
            <Text style={{ color: "rgba(255,255,255,0.6)", fontSize: 13, textAlign: "center", paddingHorizontal: 32 }}>
              Safari only opens a live camera over HTTPS. Shoot, tap Use, and the brain looks right away.
            </Text>
          </Pressable>
        ) : null}
      </View>
    </GlassesChrome>
  );
}
