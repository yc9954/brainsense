import { useEffect, useMemo, useState } from "react";
import { Image, Pressable, Text, View } from "react-native";
import Svg, { Circle, Defs, Ellipse, G, Path, RadialGradient, Stop } from "react-native-svg";
import { ROI_KO } from "./brainsense-api";
import { colors, s } from "./ui";

/**
 * Lateral view of the left hemisphere with the nine BrainSense regions placed anatomically.
 * Heat = predicted response (z-scored TRIBE output). With `series` it plays back at 1 Hz.
 */
const REGIONS: { id: string; cx: number; cy: number; r: number }[] = [
  { id: "visual_early", cx: 292, cy: 118, r: 22 }, // occipital pole (V1-V4)
  { id: "visual_motion", cx: 262, cy: 132, r: 16 }, // MT/LO, lateral occipital
  { id: "scene_place", cx: 270, cy: 158, r: 14 }, // ventral occipito-temporal
  { id: "face_body", cx: 228, cy: 150, r: 16 }, // fusiform / STS
  { id: "language", cx: 150, cy: 132, r: 16 }, // Broca/temporal
  { id: "attention_dorsal", cx: 212, cy: 72, r: 20 }, // IPS / FEF parietal
  { id: "control_dlpfc", cx: 120, cy: 78, r: 18 }, // dlPFC
  { id: "value_vmpfc", cx: 78, cy: 128, r: 16 }, // vmPFC / OFC
  { id: "default_mode", cx: 170, cy: 100, r: 12 }, // PCC/precuneus (medial, drawn centrally)
];

function heat(v: number, lo: number, hi: number) {
  const t = Math.max(0, Math.min(1, (v - lo) / (hi - lo || 1)));
  // cool grey → amber → red → yellow-white, like an fMRI overlay
  if (t < 0.35) return { color: "#B9C4CC", opacity: 0.25 + t };
  if (t < 0.7) return { color: "#E8893A", opacity: 0.55 + (t - 0.35) };
  if (t < 0.9) return { color: "#D7302F", opacity: 0.9 };
  return { color: "#FFE27A", opacity: 1 };
}

export function BrainMap({
  values,
  series,
  size = 320,
}: {
  values?: Record<string, number>;
  series?: Record<string, number[]>;
  size?: number;
}) {
  const T = series ? Math.max(0, ...Object.values(series).map((v) => v.length)) : 0;
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(true);
  useEffect(() => {
    if (!series || T < 2 || !playing) return;
    const id = setInterval(() => setT((x) => (x + 1) % T), 900);
    return () => clearInterval(id);
  }, [series, T, playing]);
  const frame = useMemo(() => {
    if (series && T)
      return Object.fromEntries(
        Object.entries(series).map(([k, v]) => [k, v[Math.min(t, v.length - 1)] ?? 0]),
      );
    return values || {};
  }, [series, values, t, T]);
  const all = Object.values(
    series
      ? Object.fromEntries(Object.entries(series).map(([k, v]) => [k, Math.max(...v)]))
      : frame,
  );
  const lo = Math.min(0, ...Object.values(frame), ...all);
  const hi = Math.max(0.05, ...all);
  const top = Object.entries(frame).sort((a, b) => b[1] - a[1])[0];
  const w = size;
  const h = size * 0.62;
  return (
    <View style={{ gap: 6 }}>
      <Svg width="100%" height={h} viewBox="0 0 340 210" accessibilityLabel="Brain activation map">
        <Defs>
          {REGIONS.map((r) => (
            <RadialGradient key={r.id} id={`g-${r.id}`} cx="50%" cy="50%" r="50%">
              <Stop
                offset="0%"
                stopColor={heat(frame[r.id] ?? 0, lo, hi).color}
                stopOpacity={heat(frame[r.id] ?? 0, lo, hi).opacity}
              />
              <Stop
                offset="100%"
                stopColor={heat(frame[r.id] ?? 0, lo, hi).color}
                stopOpacity={0}
              />
            </RadialGradient>
          ))}
        </Defs>
        {/* hemisphere silhouette + a few sulci */}
        <Path
          d="M62 118 C58 70 110 36 170 34 C236 32 300 60 312 108 C322 146 290 184 240 184 C212 184 196 170 176 170 C150 170 134 182 108 170 C78 158 64 142 62 118 Z"
          fill="#F1F2F4"
          stroke="#D6DADF"
          strokeWidth={2}
        />
        <Path d="M120 60 C150 70 180 68 212 56" stroke="#DADEE3" strokeWidth={2} fill="none" />
        <Path d="M96 112 C140 118 200 112 250 100" stroke="#DADEE3" strokeWidth={2} fill="none" />
        <Path d="M150 150 C190 150 230 146 268 134" stroke="#DADEE3" strokeWidth={2} fill="none" />
        <Ellipse cx={92} cy={188} rx={30} ry={11} fill="#E5E8EC" />
        {REGIONS.map((r) => (
          <G key={r.id}>
            <Circle cx={r.cx} cy={r.cy} r={r.r * 1.9} fill={`url(#g-${r.id})`} />
            <Circle
              cx={r.cx}
              cy={r.cy}
              r={3}
              fill={heat(frame[r.id] ?? 0, lo, hi).color}
              opacity={0.9}
            />
          </G>
        ))}
      </Svg>
      <View style={[s.between, { alignItems: "center" }]}>
        <Text style={s.small}>
          {top
            ? `Most active now: ${ROI_KO[top[0]] || top[0]} (${top[1] >= 0 ? "+" : ""}${top[1].toFixed(2)})`
            : "no signal"}
          {T > 1 ? ` · ${t + 1}/${T} s` : ""}
        </Text>
        {T > 1 && (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={playing ? "Pause" : "Play"}
            onPress={() => setPlaying((p) => !p)}
            style={[s.chip, { backgroundColor: colors.sky }]}
          >
            <Text style={s.chipText}>{playing ? "Playing" : "Play"}</Text>
          </Pressable>
        )}
      </View>
    </View>
  );
}

/** Real cortex heatmaps rendered server-side from the TRIBE v2 vertex predictions, played at 1 Hz. */
export function BrainFrames({
  frames,
  series,
}: {
  frames: string[];
  series?: Record<string, number[]>;
}) {
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(true);
  useEffect(() => {
    if (frames.length < 2 || !playing) return;
    const id = setInterval(() => setT((x) => (x + 1) % frames.length), 900);
    return () => clearInterval(id);
  }, [frames.length, playing]);
  const hottest = useMemo(() => {
    if (!series) return undefined;
    const idx = Math.min(t, Math.max(0, ...Object.values(series).map((v) => v.length - 1)));
    const e = Object.entries(series)
      .map(([k, v]) => [k, v[Math.min(idx, v.length - 1)] ?? 0] as const)
      .sort((a, b) => b[1] - a[1])[0];
    return e;
  }, [series, t]);
  return (
    <View style={{ gap: 6 }}>
      <View
        style={{
          borderRadius: 16,
          overflow: "hidden",
          backgroundColor: "#FFFFFF",
          aspectRatio: 2.1,
        }}
      >
        <Image
          source={{ uri: `data:image/png;base64,${frames[t]}` }}
          resizeMode="contain"
          style={{ width: "100%", height: "100%" }}
          accessibilityLabel={`Cortex activation map, second ${t + 1}`}
        />
      </View>
      <View style={[s.between, { alignItems: "center" }]}>
        <Text style={s.small}>
          Left hemisphere, lateral and medial · {t + 1}/{frames.length} s
          {hottest ? ` · most active: ${ROI_KO[hottest[0]] || hottest[0]}` : ""}
        </Text>
        {frames.length > 1 && (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={playing ? "Pause" : "Play"}
            onPress={() => setPlaying((p) => !p)}
            style={[s.chip, { backgroundColor: colors.sky }]}
          >
            <Text style={s.chipText}>{playing ? "Playing" : "Play"}</Text>
          </Pressable>
        )}
      </View>
    </View>
  );
}
