import { Platform } from "react-native";

/** BrainSense agent server (FastAPI, `uv run uvicorn brainsense.agent.server:app --port 8000`). */
function lanBrainUrl(): string | undefined {
  // the web build on a phone over Wi-Fi: /assets go through the LAN proxy (scripts/lan-proxy.mjs)
  if (Platform.OS !== "web" || typeof window === "undefined") return undefined;
  const loc = window.location;
  const h = loc?.hostname;
  if (!h || h === "localhost" || h === "127.0.0.1") return undefined;
  return loc.protocol === "https:" ? loc.origin : `http://${h}:8788`;
}
export const BRAINSENSE_URL = (
  process.env.EXPO_PUBLIC_BRAINSENSE_URL ||
  lanBrainUrl() ||
  (Platform.OS === "android" ? "http://10.0.2.2:8000" : "http://localhost:8000")
).replace(/\/$/, "");

export type HeadOutput = {
  head: string;
  score: number;
  percentile: number;
  confidence: number;
  top_features: { name: string; contribution: number }[];
  n_train: number;
  calibrated: boolean;
};
export type PersonalOutput = {
  crowd: HeadOutput;
  personal: {
    score: number;
    confidence: number;
    nearest_feedback: { item_id: string; liked: boolean; distance: number };
  } | null;
  n_feedback: number;
  disagreement?: number;
  note?: string;
};
export type BrainEval = {
  item_id: string;
  heads: {
    aesthetic?: HeadOutput;
    attention?: HeadOutput;
    appeal?: HeadOutput;
    popularity?: HeadOutput;
    humanlike?: HeadOutput;
    hook?: HeadOutput;
    personal?: PersonalOutput | null;
  };
  roi_ts?: Record<string, number[]>;
  brain_frames?: string[]; // base64 PNGs, one per second: fsaverage5 cortex heatmap (lateral + medial)
  vertex_ts?: VertexTs; // per-vertex activation for the live 3D cortex
  stimulus_url?: string; // what the brain was looking at (signed artifact URL)
  stimulus_text?: string; // what the brain was reading (kind=text)
  kind?: "image" | "video" | "audio" | "text";
};
/** TRIBE v2 per-vertex z-scores, uint8-quantized between lo and hi; row-major (t, n), fsaverage5 lh+rh. */
export type VertexTs = { t: number; n: number; lo: number; hi: number; u8: string };
export type AnalyzeResult = {
  item_id: string;
  timing?: Record<string, number>;
  roi_ts?: Record<string, number[]>;
  brain_frames?: string[];
};

async function call<T>(path: string, body?: unknown, method?: string): Promise<T> {
  const response = await fetch(`${BRAINSENSE_URL}${path}`, {
    method: method ?? (body === undefined ? "GET" : "POST"),
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      detail = payload.detail || detail;
    } catch {}
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export const brainsense = {
  health: () => call<{ ok: boolean; heads: string[]; cached_items: number }>("/health"),
  analyze: (itemId: string, filename: string, base64: string) =>
    call<AnalyzeResult>("/analyze", { video_b64: base64, filename, item_id: itemId }),
  eval: (itemId: string) => call<BrainEval>(`/eval/${encodeURIComponent(itemId)}`),
  ask: (itemId: string, text: string, session: string) =>
    call<{ item_id: string; text: string }>("/agent", { item_id: itemId, text, session }),
  feedback: (itemId: string, liked: boolean) =>
    call<{ stored?: boolean; n_feedback?: number; error?: string }>("/agent/feedback", {
      item_id: itemId,
      liked,
    }),
};

/** Korean labels for the 9 Glasser ROI groups and the time statistics the heads use. */
export const ROI_KO: Record<string, string> = {
  visual_early: "early visual cortex",
  visual_motion: "motion & shape",
  face_body: "faces & bodies",
  scene_place: "places & scenes",
  attention_dorsal: "visual attention",
  value_vmpfc: "reward & value",
  language: "language",
  default_mode: "mind-wandering",
  control_dlpfc: "focus & control",
};
const STAT_KO: Record<string, string> = {
  mean: "average",
  max: "peak",
  early: "early",
  late: "late",
  slope: "change",
  std: "variability",
};
const AREA_KO: Record<string, string> = {
  V1: "primary visual cortex (V1)",
  V2: "early visual cortex (V2)",
  V3: "early visual cortex (V3)",
  V4: "colour & form area (V4)",
  MT: "motion area (MT)",
  FFC: "face area (FFC)",
  PIT: "object recognition (PIT)",
  LO1: "object outline area (LO1)",
  LO2: "object outline area (LO2)",
  VVC: "ventral visual cortex",
  PHA1: "place area (PHA)",
  RSC: "scene memory (RSC)",
  "10r": "reward & value (10r)",
  "10v": "reward & value (10v)",
  OFC: "orbitofrontal cortex (OFC)",
  pOFC: "orbitofrontal cortex (pOFC)",
  a24: "anterior cingulate (a24)",
  "25": "emotion area (25)",
  "44": "language area (44)",
  "45": "language area (45)",
  STSva: "social vision (STS)",
  STSvp: "social vision (STS)",
  IP1: "visual attention (IP1)",
  IP2: "visual attention (IP2)",
  LIPv: "gaze planning (LIP)",
  FEF: "gaze planning (FEF)",
  "46": "working memory (46)",
  "9-46d": "focus (dlPFC)",
};
/** Same nine functional groups as the server's ROI_GROUPS, so any HCP-MMP1 area can be named. */
const AREA_GROUP: Record<string, string> = Object.fromEntries(
  Object.entries({
    visual_early: ["V1", "V2", "V3", "V4"],
    visual_motion: ["MT", "MST", "V3A", "V3B", "V4t", "FST", "LO1", "LO2", "LO3"],
    face_body: ["FFC", "PIT", "VVC", "STSva", "STSvp", "STSda", "TPOJ1"],
    scene_place: ["VMV1", "VMV2", "VMV3", "PHA1", "PHA2", "PHA3", "RSC", "POS1", "POS2"],
    attention_dorsal: ["IP0", "IP1", "IP2", "LIPv", "LIPd", "VIP", "AIP", "FEF", "PEF"],
    value_vmpfc: ["10r", "10v", "10d", "25", "s32", "p32", "a24", "OFC", "pOFC", "13l", "11l"],
    language: [
      "44",
      "45",
      "55b",
      "STGa",
      "A4",
      "A5",
      "TE1a",
      "TE1m",
      "TE1p",
      "STSdp",
      "PSL",
      "SFL",
    ],
    default_mode: ["31pv", "31pd", "23d", "v23ab", "d23ab", "7m", "PCV", "9m", "8BM"],
    control_dlpfc: ["46", "9-46d", "p9-46v", "a9-46v", "IFSa", "IFSp", "IFJa", "IFJp", "8C", "8Av"],
  }).flatMap(([g, areas]) => areas.map((a) => [a, g])),
);
export function featureLabel(name: string) {
  const [group, stat] = name.split("__");
  if (ROI_KO[group]) return `${ROI_KO[group]} ${STAT_KO[stat] || stat || ""}`.trim();
  const m = group.match(/^([LR])_(.+)$/); // HCP-MMP1 area code, e.g. "L_V1"
  if (m) {
    const side = m[1] === "L" ? "left" : "right";
    const code = m[2];
    const label =
      AREA_KO[code] ||
      (AREA_GROUP[code] ? `${ROI_KO[AREA_GROUP[code]]} (${code})` : `other cortex (${code})`);
    return `${side} ${label}${stat && stat !== "mean" ? `, ${STAT_KO[stat] || stat}` : ""}`;
  }
  return `${group} ${STAT_KO[stat] || stat || ""}`.trim();
}
export const HEAD_KO: Record<string, { title: string; question: string }> = {
  aesthetic: { title: "Aesthetic appeal", question: "Pleasing to look at?" },
  attention: { title: "Attention capture", question: "Does it hold the eye?" },
  appeal: { title: "Desirability", question: "Would people want it?" },
  popularity: { title: "Reach", question: "Would it get views?" },
  humanlike: { title: "Human-likeness", question: "Reads as written by a person?" },
  hook: { title: "Hook", question: "Does the sound grab?" },
};
