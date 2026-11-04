import { CameraView, useCameraPermissions, useMicrophonePermissions } from "expo-camera";
import * as FileSystem from "expo-file-system/legacy";
import { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, Text, View } from "react-native";
import type { Artifact } from "../../../packages/domain/src";
import { API_URL, type MuseApi } from "./api";
import { GlassesChrome, type GlassesState } from "./glasses-ui";
import { colors } from "./ui";

/**
 * Glasses emulator (phone): the phone camera stands in for Ray-Ban Meta. Keeps a rolling 6 s
 * clip of what you are looking at; a question uploads the latest clip as a glasses_ attachment
 * so the agent can look_at it and run brain_eval; the answer comes back as captions over the
 * POV and is spoken aloud. Same clip-per-question flow as the Mock Device Kit path, no SDK.
 */
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
  const cam = useRef<CameraView>(null);
  const [camPerm, requestCam] = useCameraPermissions();
  const [micPerm, requestMic] = useMicrophonePermissions();
  const lastClip = useRef<{ uri: string; at: number } | null>(null);
  const segmentStart = useRef(0);
  const alive = useRef(true);
  const replyAtAsk = useRef<string | undefined>(undefined);
  const [state, setState] = useState<GlassesState>("starting");
  const [status, setStatus] = useState("Starting camera…");
  const [error, setError] = useState("");
  const [question, setQuestion] = useState<string | undefined>();
  const [shown, setShown] = useState<string | undefined>();
  const [clipAge, setClipAge] = useState<number | null>(null);
  const [facing, setFacing] = useState<"back" | "front">("back");

  useEffect(() => {
    if (!camPerm?.granted) void requestCam();
    if (!micPerm?.granted) void requestMic();
  }, [camPerm?.granted, micPerm?.granted, requestCam, requestMic]);

  // rolling 6 s segments; recordAsync resolves when maxDuration hits or stopRecording() is called
  const loop = useCallback(async () => {
    while (alive.current && cam.current) {
      try {
        segmentStart.current = Date.now();
        const rec = await cam.current.recordAsync({ maxDuration: 6 });
        if (rec?.uri && Date.now() - segmentStart.current >= 1500) lastClip.current = { uri: rec.uri, at: Date.now() };
      } catch (e) {
        if (!alive.current) break;
        setError(`Recording error: ${e instanceof Error ? e.message : String(e)}`);
        await new Promise((r) => setTimeout(r, 800));
      }
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    const tick = setInterval(() => {
      setClipAge(lastClip.current ? Math.round((Date.now() - lastClip.current.at) / 1000) : null);
    }, 1000);
    return () => {
      alive.current = false;
      clearInterval(tick);
      cam.current?.stopRecording();
    };
  }, []);

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

  const onCameraReady = useCallback(() => {
    setState("watching");
    setStatus("Watching · 6 s buffer");
    void loop();
  }, [loop]);

  const ask = useCallback(
    async (text: string) => {
      setError("");
      setQuestion(text);
      setShown(undefined);
      replyAtAsk.current = reply;
      setState("capturing");
      try {
        if (Date.now() - segmentStart.current >= 2500) {
          cam.current?.stopRecording();
          await new Promise((r) => setTimeout(r, 600));
        }
        const clip = lastClip.current;
        if (!clip) throw new Error("Nothing captured yet. Point the camera for 2–3 more seconds.");
        const ext = clip.uri.split(".").pop()?.toLowerCase() || "mp4";
        const up = await FileSystem.uploadAsync(`${API_URL}/api/glasses/clip`, clip.uri, {
          httpMethod: "POST",
          uploadType: FileSystem.FileSystemUploadType.MULTIPART,
          fieldName: "file",
          mimeType: ext === "mov" ? "video/quicktime" : "video/mp4",
          headers: { Authorization: `Bearer ${api.token}` },
        });
        const payload = JSON.parse(up.body) as Artifact & { error?: string };
        if (up.status < 200 || up.status >= 300) throw new Error(payload.error || "Upload failed");
        setState("thinking");
        await onAsk(text, payload);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setState("watching");
      }
    },
    [api.token, onAsk, reply],
  );

  if (!camPerm?.granted)
    return (
      <View style={{ flex: 1, backgroundColor: "#000", alignItems: "center", justifyContent: "center", padding: 24, gap: 12 }}>
        <Text style={{ color: "#fff", fontSize: 16, textAlign: "center" }}>Glasses mode needs camera access.</Text>
        <Pressable onPress={() => void requestCam()} style={{ backgroundColor: colors.blue, paddingHorizontal: 18, paddingVertical: 10, borderRadius: 999 }}>
          <Text style={{ color: colors.blueDark, fontWeight: "700" }}>Allow</Text>
        </Pressable>
        <Pressable onPress={onClose} style={{ padding: 10 }}>
          <Text style={{ color: "rgba(255,255,255,0.7)" }}>Close</Text>
        </Pressable>
      </View>
    );

  return (
    <GlassesChrome
      state={state}
      status={`${status}${clipAge !== null && state === "watching" ? ` · last clip ${clipAge} s ago` : ""}`}
      question={question}
      reply={shown}
      error={error}
      onAsk={ask}
      onClose={onClose}
      onFlip={() => setFacing((f) => (f === "back" ? "front" : "back"))}
    >
      <CameraView ref={cam} style={{ flex: 1 }} facing={facing} mode="video" mute videoQuality="720p" onCameraReady={onCameraReady} />
    </GlassesChrome>
  );
}
