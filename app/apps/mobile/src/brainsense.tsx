import * as DocumentPicker from "expo-document-picker";
import {
  ArrowUp,
  Brain,
  HelpCircle,
  ImagePlus,
  RefreshCw,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react-native";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Platform,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";

import { BarChart, type BarRow, type BarSeries, SERIES_GREY, SERIES_RED, SERIES_WHITE } from "./bars";
import { BrainLive } from "./brain-live";
import { BrainMap } from "./brain-map";
import {
  type BrainEval,
  brainsense,
  featureLabel,
  HEAD_KO,
  type HeadOutput,
  type PersonalOutput,
  ROI_KO,
} from "./brainsense-api";
import { useBrainSense } from "./brainsense-state";
import { Button, Card, Chip, colors, ErrorNotice, s } from "./ui";

type Item = {
  id: string;
  name: string;
  uri: string;
  kind: "image" | "video";
  evalData?: BrainEval;
};
type Message = { id: number; role: "user" | "assistant"; text: string };

const QUICK = ["What do you think of this?", "Why?", "Compare with the last one"];
/** Bundled samples: an AADB photo rated 1.0 by humans, one rated 0.0, and an Unsplash shot. */
/** Things you would actually point the glasses at. Real photos, CC licensed: see assets/CREDITS.md. */
export const SAMPLES: { name: string; label: string; source: number | { uri: string } }[] = [
  { name: "popup-store.jpg", label: "Pop-up store", source: require("../assets/sample-popup.jpg") },
  { name: "cafe-menu-board.jpg", label: "Cafe menu board", source: require("../assets/sample-menu.jpg") },
  { name: "bakery-display.jpg", label: "Bakery display", source: require("../assets/sample-bakery.jpg") },
  { name: "shop-window.jpg", label: "Shop window", source: require("../assets/sample-window.jpg") },
  { name: "supermarket-shelf.jpg", label: "Supermarket shelf", source: require("../assets/sample-shelf.jpg") },
  { name: "poster-wall.jpg", label: "Poster wall", source: require("../assets/sample-posters.jpg") },
];
const STRIP_GROUPS = ["attention_dorsal", "value_vmpfc", "face_body"];
const STRIP_COLORS: Record<string, string> = {
  attention_dorsal: "#FFFFFF",
  value_vmpfc: colors.red,
  face_body: colors.grey,
};

export async function readBase64(uri: string): Promise<string> {
  if (Platform.OS === "web") {
    const blob = await (await fetch(uri)).blob();
    return await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error("Could not read the file."));
      reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
      reader.readAsDataURL(blob);
    });
  }
  const fs = await import("expo-file-system/legacy");
  return fs.readAsStringAsync(uri, { encoding: fs.EncodingType.Base64 });
}

function confidenceLabel(c: number) {
  return c >= 0.6 ? "high confidence" : c >= 0.3 ? "moderate confidence" : "low confidence";
}
function topLabel(pct: number) {
  const top = Math.round(100 - pct);
  return top <= 50 ? `top ${Math.max(1, top)}%` : `bottom ${Math.max(1, 100 - top)}%`;
}

const HEAD_ORDER = ["aesthetic", "attention", "appeal", "popularity", "humanlike", "hook"] as const;
const SERIES: BarSeries[] = [
  { key: "score", label: "Crowd score", color: SERIES_WHITE },
  { key: "confidence", label: "Confidence", color: SERIES_GREY },
  { key: "percentile", label: "Percentile", color: SERIES_RED },
];

/** Heads as the site's bar chart: one category per head, three bars (score / confidence / percentile). */
function HeadBars({ heads, data }: { heads: readonly string[]; data: BrainEval }) {
  const rows: BarRow[] = heads.map((k) => {
    const h = data.heads[k as keyof BrainEval["heads"]] as HeadOutput;
    const meta = HEAD_KO[k] || { title: k, question: k };
    return {
      label: meta.title,
      sub: meta.question,
      values: { score: h.score, confidence: h.confidence, percentile: h.percentile / 100 },
    };
  });
  return <BarChart series={SERIES} rows={rows} max={1} format={(v) => v.toFixed(2)} />;
}

/** The written analysis under the chart: which cortical areas drove each head, and the verdict line. */
function Analysis({ heads, data }: { heads: readonly string[]; data: BrainEval }) {
  // /eval critique (text items): { diagnosis: string[], directives: string[], ... }
  const critique = (data as { critique?: unknown }).critique;
  const c = critique && typeof critique === "object" ? (critique as { diagnosis?: unknown; directives?: unknown; text?: unknown }) : undefined;
  const critiqueText = typeof critique === "string" ? critique : typeof c?.text === "string" ? c.text : undefined;
  const strings = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
  const diagnosis = strings(c?.diagnosis);
  const directives = strings(c?.directives);
  return (
    <View style={{ gap: 10 }}>
      <Text style={{ color: colors.text, fontSize: 15, fontWeight: "600" }}>Analysis</Text>
      {heads.map((k) => {
        const h = data.heads[k as keyof BrainEval["heads"]] as HeadOutput;
        const meta = HEAD_KO[k] || { title: k, question: k };
        const drivers = h.top_features
          .slice(0, 2)
          .map((f) => `${f.contribution >= 0 ? "+" : "−"} ${featureLabel(f.name)}`)
          .join(" · ");
        return (
          <View key={k} style={{ flexDirection: "row", gap: 12, alignItems: "flex-start" }}>
            <Text style={{ width: 64, color: colors.text, fontSize: 13, fontWeight: "600" }}>{meta.title}</Text>
            <Text style={{ flex: 1, color: colors.muted, fontSize: 13, lineHeight: 19 }}>
              {topLabel(h.percentile)} · {confidenceLabel(h.confidence)}
              {drivers ? ` · ${drivers}` : ""}
            </Text>
          </View>
        );
      })}
      {critiqueText ? (
        <Text style={{ color: colors.text, fontSize: 14, lineHeight: 21, marginTop: 4 }}>{critiqueText}</Text>
      ) : null}
      {diagnosis.length ? (
        <View style={{ gap: 6, marginTop: 4 }}>
          <Text style={{ color: colors.muted, fontSize: 12, letterSpacing: 1, textTransform: "uppercase" }}>Diagnosis</Text>
          {diagnosis.map((d, i) => (
            <Text key={i} style={{ color: colors.text, fontSize: 14, lineHeight: 21 }}>
              {d}
            </Text>
          ))}
        </View>
      ) : null}
      {directives.length ? (
        <View style={{ gap: 6, marginTop: 4 }}>
          <Text style={{ color: colors.muted, fontSize: 12, letterSpacing: 1, textTransform: "uppercase" }}>What to change</Text>
          {directives.map((d, i) => (
            <Text key={i} style={{ color: colors.text, fontSize: 14, lineHeight: 21 }}>
              {i + 1}. {d}
            </Text>
          ))}
        </View>
      ) : null}
    </View>
  );
}

/** Crowd vs. you. Appears once the personal head has enough feedback. */
function PersonalRow({ personal }: { personal: PersonalOutput }) {
  if (!personal.personal)
    return (
      <View style={{ gap: 6, borderTopWidth: 1, borderTopColor: colors.line, paddingTop: 14 }}>
        <Text style={{ color: colors.text, fontSize: 15, fontWeight: "600" }}>Your taste model</Text>
        <Text style={{ color: colors.muted, fontSize: 13 }}>
          Turns on after {Math.max(0, 6 - personal.n_feedback)} more like / dislike answers ({personal.n_feedback} so far).
        </Text>
      </View>
    );
  const you = personal.personal.score;
  const crowd = personal.crowd.score;
  const split = Math.abs(you - crowd) >= 0.15;
  return (
    <View style={{ gap: 12, borderTopWidth: 1, borderTopColor: colors.line, paddingTop: 14 }}>
      <BarChart
        title={split ? "Your taste diverges from the crowd" : "Your taste matches the crowd"}
        series={[
          { key: "crowd", label: "Crowd", color: SERIES_WHITE },
          { key: "you", label: "You", color: SERIES_RED },
        ]}
        rows={[{ label: "Liking", values: { crowd, you } }]}
      />
      <Text style={{ color: colors.muted, fontSize: 12.5 }}>
        The closest item you rated was a {personal.personal.nearest_feedback.liked ? "like" : "dislike"}.
      </Text>
    </View>
  );
}

/** 1 Hz predicted response for three regions as the site's bar chart: one row per second, one bar per region. */
function RoiStrip({ series }: { series: Record<string, number[]> }) {
  const groups = STRIP_GROUPS.filter((g) => series[g]?.length);
  if (!groups.length) return null;
  const T = Math.max(...groups.map((g) => series[g].length));
  const maxAbs = Math.max(0.05, ...groups.flatMap((g) => series[g].map((v) => Math.abs(v))));
  const rows: BarRow[] = Array.from({ length: T }, (_, i) => ({
    label: `${i + 1}s`,
    values: Object.fromEntries(groups.map((g) => [g, series[g][i]])),
  }));
  return (
    <View style={{ borderTopWidth: 1, borderTopColor: colors.line, paddingTop: 14 }}>
      <BarChart
        title="Predicted brain response · z-score"
        series={groups.map((g) => ({ key: g, label: ROI_KO[g] ?? g, color: STRIP_COLORS[g] }))}
        rows={rows}
        max={maxAbs}
        signed
        format={(v) => (v >= 0 ? `+${v.toFixed(2)}` : v.toFixed(2))}
      />
    </View>
  );
}

export function BrainCard({ data }: { data: BrainEval }) {
  const heads = HEAD_ORDER.filter((k) => data.heads[k]);
  const best = heads
    .map((k) => [k, data.heads[k] as HeadOutput] as const)
    .filter(([, h]) => h.confidence >= 0.3)
    .sort((a, b) => b[1].percentile - a[1].percentile)[0];
  const mode = data.kind === "text" ? "read" : data.kind === "audio" ? "listen" : "look";
  return (
    <Card style={{ gap: 18, padding: 18 }}>
      <View style={{ gap: 4 }}>
        <Text style={s.label}>Brain {mode} · TRIBE v2 → calibrated heads</Text>
        <Text style={{ color: colors.text, fontSize: 18, fontWeight: "600", letterSpacing: -0.3 }}>
          What my brain saw first
        </Text>
        <Text style={{ color: best ? colors.text : colors.muted, fontSize: 13 }}>
          {best ? `Strongest signal: ${HEAD_KO[best[0]]?.title}, ${topLabel(best[1].percentile)}` : "Weak signal on every head"}
        </Text>
      </View>
      {data.vertex_ts || (data.brain_frames && data.brain_frames.length > 0) ? (
        <BrainLive
          vertexTs={data.vertex_ts}
          frames={data.brain_frames}
          series={data.roi_ts}
          stimulusUri={data.stimulus_url}
          stimulusText={data.stimulus_text}
          kind={data.kind}
        />
      ) : (
        data.roi_ts && Object.keys(data.roi_ts).length > 0 && <BrainMap series={data.roi_ts} />
      )}
      {heads.length > 0 && <HeadBars heads={heads} data={data} />}
      {heads.length > 0 && <Analysis heads={heads} data={data} />}
      {data.heads.personal && <PersonalRow personal={data.heads.personal} />}
      {data.roi_ts && Object.keys(data.roi_ts).length > 0 && <RoiStrip series={data.roi_ts} />}
      <Text style={{ color: colors.muted, fontSize: 11.5 }}>
        Percentiles are positions against real rated data (AADB, Unsplash, SnapUGC). Every number is the model output as is.
      </Text>
    </Card>
  );
}

export function LookScreen() {
  const [items, setItems] = useState<Item[]>([]);
  const [current, setCurrent] = useState<string>();
  const [analyzing, setAnalyzing] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [replying, setReplying] = useState(false);
  const [error, setError] = useState("");
  const [online, setOnline] = useState<boolean>();
  const session = useMemo(() => `look-${Date.now()}`, []);
  const scroller = useRef<ScrollView>(null);
  const item = items.find((i) => i.id === current);
  const shared = useBrainSense();
  useEffect(() => {
    shared.setCurrent(item ? { id: item.id, name: item.name, evalData: item.evalData } : undefined);
  }, [item, shared.setCurrent]);

  useEffect(() => {
    brainsense
      .health()
      .then(() => setOnline(true))
      .catch(() => setOnline(false));
  }, []);

  const say = useCallback((role: Message["role"], text: string) => {
    setMessages((m) => [...m, { id: Date.now() + Math.random(), role, text }]);
    setTimeout(() => scroller.current?.scrollToEnd({ animated: true }), 50);
  }, []);

  const analyze = useCallback(
    async (name: string, uri: string, kind: Item["kind"]) => {
      const id = `look_${Date.now().toString(36)}`;
      setItems((list) => [{ id, name, uri, kind }, ...list]);
      setCurrent(id);
      setMessages([]);
      setAnalyzing(true);
      try {
        const base64 = await readBase64(uri);
        const analyzed = await brainsense.analyze(id, name, base64);
        const evaluated = await brainsense.eval(id);
        evaluated.roi_ts = analyzed.roi_ts || evaluated.roi_ts;
        evaluated.brain_frames = analyzed.brain_frames?.length
          ? analyzed.brain_frames
          : evaluated.brain_frames;
        setItems((list) => list.map((i) => (i.id === id ? { ...i, evalData: evaluated } : i)));
        say("assistant", "Got it. Ask me anything, e.g. what do you think?");
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setAnalyzing(false);
      }
    },
    [say],
  );

  const pick = useCallback(async () => {
    setError("");
    const result = await DocumentPicker.getDocumentAsync({
      type: ["image/*", "video/*"],
      copyToCacheDirectory: true,
      multiple: false,
    });
    if (result.canceled || !result.assets?.[0]) return;
    const asset = result.assets[0];
    await analyze(asset.name, asset.uri, asset.mimeType?.startsWith("video") ? "video" : "image");
  }, [analyze]);

  const trySample = useCallback(
    async (sample: (typeof SAMPLES)[number]) => {
      setError("");
      // Metro gives a {uri} object on web and a numeric asset id on native.
      const uri =
        typeof sample.source === "object"
          ? sample.source.uri
          : Image.resolveAssetSource(sample.source).uri;
      await analyze(sample.name, uri, "image");
    },
    [analyze],
  );

  const ask = useCallback(
    async (text: string) => {
      if (!item || !text.trim() || replying) return;
      setDraft("");
      setError("");
      say("user", text);
      setReplying(true);
      try {
        const reply = await brainsense.ask(item.id, text, session);
        say("assistant", reply.text);
        // the personal head may have changed (feedback phrased in chat), refresh the card quietly
        const evaluated = await brainsense.eval(item.id).catch(() => undefined);
        if (evaluated)
          setItems((list) =>
            list.map((i) =>
              i.id === item.id
                ? { ...i, evalData: { ...evaluated, roi_ts: i.evalData?.roi_ts } }
                : i,
            ),
          );
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setReplying(false);
      }
    },
    [item, replying, say, session],
  );

  const feedback = useCallback(
    async (liked: boolean) => {
      if (!item) return;
      setError("");
      try {
        const r = await brainsense.feedback(item.id, liked);
        if (r.error) throw new Error(r.error);
        say("user", liked ? "Like" : "Dislike");
        say("assistant", `Saved. That is answer ${r.n_feedback}.`);
        const evaluated = await brainsense.eval(item.id);
        setItems((list) =>
          list.map((i) =>
            i.id === item.id
              ? {
                  ...i,
                  evalData: {
                    ...evaluated,
                    roi_ts: i.evalData?.roi_ts,
                    brain_frames: evaluated.brain_frames ?? i.evalData?.brain_frames,
                  },
                }
              : i,
          ),
        );
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [item, say],
  );

  return (
    <View style={{ gap: 18 }}>
      <Card style={{ gap: 14, backgroundColor: colors.sky }}>
        <View style={[s.between, { alignItems: "flex-start" }]}>
          <View style={{ flex: 1, gap: 4 }}>
            <Text style={[s.title, { fontSize: 21 }]}>What do you think?</Text>
            <Text style={s.muted}>
              Show a photo or a short clip and get an honest opinion grounded in a predicted brain response.
            </Text>
          </View>
          <Chip tint={online === false ? "#FBEFED" : online ? colors.green : "#F3F5F6"}>
            {online === false ? "server off" : online ? "connected" : "checking"}
          </Chip>
        </View>
        <View style={[s.row, { gap: 10, flexWrap: "wrap" }]}>
          <Button primary icon={ImagePlus} onPress={() => void pick()} busy={analyzing}>
            {analyzing ? "Computing the brain response… about 14 s" : "Choose a photo or clip"}
          </Button>
          {SAMPLES.map((sample) => (
            <Button
              key={sample.name}
              small
              disabled={analyzing}
              onPress={() => void trySample(sample)}
            >
              {sample.label}
            </Button>
          ))}
          {item && !analyzing && (
            <Button
              small
              icon={RefreshCw}
              onPress={() => {
                setMessages([]);
                void ask("What do you think?");
              }}
            >
              Ask again
            </Button>
          )}
        </View>
      </Card>

      {items.length > 0 && (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ gap: 10 }}
        >
          {items.map((i) => (
            <Pressable
              key={i.id}
              accessibilityRole="button"
              accessibilityLabel={`Select ${i.name}`}
              accessibilityState={{ selected: i.id === current }}
              onPress={() => setCurrent(i.id)}
              style={{
                width: 84,
                height: 84,
                borderRadius: 18,
                overflow: "hidden",
                borderWidth: 2,
                borderColor: i.id === current ? colors.blueDark : "transparent",
                backgroundColor: colors.line,
              }}
            >
              {i.kind === "image" ? (
                <Image source={{ uri: i.uri }} style={{ width: "100%", height: "100%" }} />
              ) : (
                <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
                  <Text style={s.small}>clip</Text>
                </View>
              )}
            </Pressable>
          ))}
        </ScrollView>
      )}

      <ErrorNotice error={error} />

      {item?.evalData ? (
        <BrainCard data={item.evalData} />
      ) : analyzing ? (
        <Card style={{ ...s.row, gap: 12 }}>
          <ActivityIndicator color={colors.blueDark} />
          <View style={{ flex: 1 }}>
            <Text style={s.text}>TRIBE v2 is looking</Text>
            <Text style={s.small}>V-JEPA2 → predicted fMRI → 9 regions → heads</Text>
          </View>
        </Card>
      ) : null}

      {item && (
        <Card style={{ gap: 14, padding: 16 }}>
          <View style={{ gap: 10 }}>
            {messages.map((m) => (
              <View
                key={m.id}
                style={{
                  alignSelf: m.role === "user" ? "flex-end" : "flex-start",
                  maxWidth: "88%",
                  backgroundColor: m.role === "user" ? colors.blue : "#F3F5F6",
                  borderRadius: 18,
                  paddingHorizontal: 14,
                  paddingVertical: 9,
                }}
              >
                <Text style={s.text}>{m.text}</Text>
              </View>
            ))}
            {replying && (
              <View style={[s.row, { gap: 8 }]}>
                <ActivityIndicator size="small" color={colors.blueDark} />
                <Text style={s.small}>Checking the evidence…</Text>
              </View>
            )}
          </View>
          <View style={[s.row, { gap: 8, flexWrap: "wrap" }]}>
            {QUICK.map((q) => (
              <Pressable
                key={q}
                accessibilityRole="button"
                onPress={() => void ask(q)}
                style={({ pressed }) => [
                  s.chip,
                  {
                    paddingVertical: 7,
                    paddingHorizontal: 12,
                    backgroundColor: pressed ? colors.sky : "#F3F5F6",
                  },
                ]}
              >
                <Text style={[s.chipText, { fontSize: 12, color: colors.text }]}>{q}</Text>
              </Pressable>
            ))}
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Like"
              onPress={() => void feedback(true)}
              style={[s.chip, { paddingVertical: 7, backgroundColor: colors.green }]}
            >
              <ThumbsUp size={14} color={colors.text} />
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Dislike"
              onPress={() => void feedback(false)}
              style={[s.chip, { paddingVertical: 7, backgroundColor: colors.orange }]}
            >
              <ThumbsDown size={14} color={colors.text} />
            </Pressable>
          </View>
          <View
            style={[
              s.row,
              {
                gap: 7,
                borderWidth: 1,
                borderColor: colors.line,
                borderRadius: 28,
                paddingLeft: 16,
                paddingRight: 5,
                paddingVertical: 4,
                backgroundColor: "#FFF",
              },
            ]}
          >
            <TextInput
              accessibilityLabel="Ask BrainSense"
              value={draft}
              onChangeText={setDraft}
              placeholder="Ask… e.g. is it pleasing?"
              placeholderTextColor="#949B9F"
              style={{ flex: 1, color: colors.text, fontSize: 16, minHeight: 40 }}
              onSubmitEditing={() => void ask(draft)}
              returnKeyType="send"
            />
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Send"
              disabled={!draft.trim() || replying}
              onPress={() => void ask(draft)}
              style={({ pressed }) => ({
                width: 40,
                height: 40,
                borderRadius: 20,
                backgroundColor: draft.trim() ? colors.blue : "#F3F5F6",
                alignItems: "center",
                justifyContent: "center",
                transform: [{ scale: pressed ? 0.94 : 1 }],
              })}
            >
              <ArrowUp size={22} strokeWidth={1.8} color={draft.trim() ? colors.text : "#9CB5C5"} />
            </Pressable>
          </View>
        </Card>
      )}

      {!item && !analyzing && (
        <Card style={{ gap: 10 }}>
          <View style={[s.row, { gap: 10 }]}>
            <HelpCircle size={18} color={colors.blueDark} />
            <Text style={s.heading}>How it looks</Text>
          </View>
          <Text style={s.muted}>
            A clip passes through Meta's TRIBE v2 (a brain-response model) and becomes signals from nine brain
            regions; small heads trained on real rated data turn them into aesthetic appeal, attention capture and
            desirability. The agent (Muse Spark) speaks only from those numbers and says so when its confidence is
            low. Like and dislike grow a separate head for your own taste.
          </Text>
        </Card>
      )}
    </View>
  );
}
