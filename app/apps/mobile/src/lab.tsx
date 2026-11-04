import * as DocumentPicker from "expo-document-picker";
import { Image as ImageIcon, Upload } from "lucide-react-native";
import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Image, Platform, Pressable, ScrollView, Text, View } from "react-native";
import { type BrainEval, BRAINSENSE_URL, brainsense } from "./brainsense-api";
import { BrainCard, readBase64, SAMPLES } from "./brainsense";
import { BarChart, SERIES_GREY, SERIES_RED, Tile } from "./bars";
import { Button, colors, ErrorNotice, s } from "./ui";

/**
 * Lab: the site's in-silico panel, for your own fine-tuned brain. Pick a stimulus, run it
 * through TRIBE v2 and the calibrated heads, read the numbers, then answer like / dislike so the personal
 * head refits and the crowd-vs-you bars move.
 */
type Run = { id: string; name: string; uri: string; data?: BrainEval; feedback?: boolean };

/** Brain-state memory on the BrainSense server (rules learned from like/dislike, learning curve, recall). */
type Rule = { id: number; text: string; evidence?: { confidence?: number } };
type Curve = { points: { n_labeled: number; loo_auroc: number | null; crowd_auroc: number | null }[]; memory?: { engrams: number; outcomes: number; rules: number } };
type Recall = { recalled: { item_id: string; similarity: number; outcomes: { liked?: boolean }[] }[] };
type Counts = { engrams: number; outcomes: number; rules: number };
type SleepReport = { n_labeled?: number; rules_new?: number; loo_auroc?: number | null; crowd_loo_auroc?: number | null; high_surprise?: number };
/** One write to the brain's memory, shown live in the feed below the counters. */
type MemoryEvent = { t: number; kind: "trace" | "outcome" | "refit" | "recall" | "sleep" | "reset" | "chat"; text: string };
const KIND_LABEL: Record<MemoryEvent["kind"], string> = {
  trace: "Trace",
  outcome: "Outcome",
  refit: "Refit",
  recall: "Recall",
  sleep: "Sleep",
  reset: "Reset",
  chat: "Chat",
};
const pct = (x: number | null | undefined) => (typeof x === "number" ? `${Math.round(x * 100)}%` : "n/a");
const clock = (t: number) => new Date(t).toLocaleTimeString("en-GB", { hour12: false });
async function mem<T>(path: string, method = "GET"): Promise<T> {
  const r = await fetch(`${BRAINSENSE_URL}${path}`, { method });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return (await r.json()) as T;
}
function confirmReset(onYes: () => void) {
  if (Platform.OS === "web") {
    if (window.confirm("Erase memory? All like/dislike answers, learned rules and your personal head will be removed.")) onYes();
    return;
  }
  Alert.alert("Erase memory", "All like/dislike answers, learned rules and your personal head will be removed.", [
    { text: "Cancel", style: "cancel" },
    { text: "Erase", style: "destructive", onPress: onYes },
  ]);
}

export function LabScreen() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [currentId, setCurrentId] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const current = runs.find((r) => r.id === currentId);
  const [rules, setRules] = useState<Rule[]>([]);
  const [curve, setCurve] = useState<Curve | undefined>();
  const [recall, setRecall] = useState<Recall | undefined>();
  const [sleeping, setSleeping] = useState(false);
  // live memory: counters that flash when they change, and a feed of every write as it happens
  const [counts, setCounts] = useState<Counts | undefined>();
  const [flash, setFlash] = useState<Partial<Record<keyof Counts, boolean>>>({});
  const [events, setEvents] = useState<MemoryEvent[]>([]);
  const countsRef = useRef<Counts | undefined>(undefined);
  const localWrite = useRef(false);
  const recalledFor = useRef<string>("");
  const pushEvent = useCallback((kind: MemoryEvent["kind"], text: string) => {
    setEvents((ev) => [{ t: Date.now(), kind, text }, ...ev].slice(0, 14));
  }, []);
  const refreshMemory = useCallback(async () => {
    try {
      const [r, c] = await Promise.all([mem<{ rules: Rule[] }>("/rules"), mem<Curve>("/learning_curve")]);
      setRules(r.rules ?? []);
      setCurve(c);
      const next = c.memory;
      if (!next) return;
      const prev = countsRef.current;
      if (prev) {
        const changed: Partial<Record<keyof Counts, boolean>> = {};
        (["engrams", "outcomes", "rules"] as const).forEach((k) => {
          if (next[k] !== prev[k]) changed[k] = true;
        });
        if (Object.keys(changed).length) {
          setFlash(changed);
          setTimeout(() => setFlash({}), 1600);
          // writes that did not come from this screen (the chat, glasses mode, the agent's own tools)
          if (!localWrite.current) {
            const d = next.engrams - prev.engrams;
            const o = next.outcomes - prev.outcomes;
            const parts = [d > 0 ? `${d} new trace${d > 1 ? "s" : ""}` : "", o > 0 ? `${o} new outcome${o > 1 ? "s" : ""}` : ""].filter(Boolean);
            if (parts.length) pushEvent("chat", `${parts.join(" and ")} written from the chat`);
          }
        }
      }
      localWrite.current = false;
      countsRef.current = next;
      setCounts(next);
    } catch {}
  }, [pushEvent]);
  useEffect(() => {
    void refreshMemory();
    const id = setInterval(() => void refreshMemory(), 6000);
    return () => clearInterval(id);
  }, [refreshMemory]);
  useEffect(() => {
    if (!current?.data) return;
    mem<Recall>(`/recall/${encodeURIComponent(current.id)}?k=4`)
      .then((rc) => {
        setRecall(rc);
        const top = rc.recalled?.[0];
        if (top && recalledFor.current !== current.id) {
          recalledFor.current = current.id;
          pushEvent("recall", `Recalled ${rc.recalled.length} similar traces for ${current.name} · nearest ${top.similarity.toFixed(2)}`);
        }
      })
      .catch(() => setRecall(undefined));
  }, [current?.id, current?.data, current?.name, pushEvent]);

  const analyze = useCallback(async (name: string, uri: string) => {
    setBusy(true);
    setError("");
    setStatus("TRIBE v2 is looking (about 15 s)");
    const id = `lab_${Date.now().toString(36)}`;
    try {
      const b64 = await readBase64(uri);
      await brainsense.analyze(id, name, b64);
      setStatus("Scoring the heads");
      const data = await brainsense.eval(id);
      setRuns((rs) => [{ id, name, uri, data }, ...rs]);
      setCurrentId(id);
      setStatus("");
      localWrite.current = true;
      pushEvent("trace", `Trace stored · ${name} · 20,484 vertices → 360 areas → PCA-54, kept with its outcome slot`);
      void refreshMemory();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStatus("");
    } finally {
      setBusy(false);
    }
  }, [pushEvent, refreshMemory]);

  const pick = useCallback(async () => {
    const result = await DocumentPicker.getDocumentAsync({ type: ["image/*", "video/*"], copyToCacheDirectory: true, multiple: false });
    if (result.canceled || !result.assets?.[0]) return;
    const asset = result.assets[0];
    await analyze(asset.name, asset.uri);
  }, [analyze]);

  const feedback = useCallback(
    async (liked: boolean) => {
      if (!current) return;
      setBusy(true);
      setError("");
      try {
        await brainsense.feedback(current.id, liked);
        const data = await brainsense.eval(current.id);
        setRuns((rs) => rs.map((r) => (r.id === current.id ? { ...r, data, feedback: liked } : r)));
        localWrite.current = true;
        pushEvent("outcome", `Outcome written · you ${liked ? "liked" : "disliked"} ${current.name}`);
        const p = data.heads.personal;
        if (p?.personal) {
          const gap = Math.abs(p.personal.score - p.crowd.score);
          pushEvent(
            "refit",
            `Your head refit on ${p.n_feedback} answers · you ${pct(p.personal.score)} vs crowd ${pct(p.crowd.score)}${gap >= 0.15 ? " · you disagree with the crowd here" : ""}`,
          );
        } else if (p) {
          pushEvent("refit", `Your head refit · ${p.n_feedback} of 6 answers before it switches on`);
        }
        void refreshMemory();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [current, refreshMemory, pushEvent],
  );

  const personalN = current?.data?.heads.personal?.n_feedback;

  return (
    <View style={{ gap: 26 }}>
      <View style={{ gap: 8 }}>
        <Text style={{ color: colors.text, fontSize: 26, fontWeight: "600", letterSpacing: -0.6, lineHeight: 32 }}>
          Test your brain
        </Text>
        <Text style={{ color: colors.muted, fontSize: 15, lineHeight: 22 }}>
          Pick a stimulus to see the cortical response TRIBE v2 predicts and the calibrated head scores. Every like or
          dislike refits your personal head, and below you watch the memory being written: traces, outcomes, refits and
          rules, live.
        </Text>
      </View>

      <View style={{ gap: 12 }}>
        <Text style={s.label}>Stimulus</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 14 }}>
          {SAMPLES.map((sm) => {
            const uri = typeof sm.source === "object" ? sm.source.uri : "";
            return (
              <Tile
                key={sm.name}
                label={sm.label}
                note="photo"
                active={current?.name === sm.name}
                onPress={() => {
                  if (!busy) void analyze(sm.name, uri);
                }}
                icon={
                  uri ? (
                    <Image source={{ uri }} style={{ width: 86, height: 86, borderRadius: 21 }} resizeMode="cover" />
                  ) : (
                    <ImageIcon size={30} color={colors.text} strokeWidth={1.4} />
                  )
                }
              />
            );
          })}
          <Tile label="Upload" note="photo · video" onPress={() => void pick()} icon={<Upload size={30} color={colors.text} strokeWidth={1.4} />} />
        </ScrollView>
        {status ? <Text style={{ color: colors.muted, fontSize: 13 }}>{status}</Text> : null}
        <ErrorNotice error={error} />
      </View>

      {current?.data ? (
        <View style={{ gap: 14 }}>
          <View style={[s.between, { alignItems: "center" }]}>
            <Text style={s.label}>Result · {current.name}</Text>
            <View style={[s.row, { gap: 8 }]}>
              <Button small disabled={busy} primary={current.feedback === true} onPress={() => void feedback(true)}>
                Like
              </Button>
              <Button small disabled={busy} primary={current.feedback === false} onPress={() => void feedback(false)}>
                Dislike
              </Button>
            </View>
          </View>
          {(() => {
            const reflex = (current.data as { reflex?: { sentence?: string } }).reflex;
            return reflex?.sentence ? (
              <View style={{ borderWidth: 1, borderColor: colors.red, borderRadius: 14, padding: 12 }}>
                <Text style={s.label}>Reflex</Text>
                <Text style={{ color: colors.text, fontSize: 14, lineHeight: 20, marginTop: 4 }}>{reflex.sentence}</Text>
              </View>
            ) : null;
          })()}
          <BrainCard data={current.data} />
          {recall?.recalled?.length ? (
            <View style={{ gap: 10 }}>
              <Text style={s.label}>Similar things my cortex remembers</Text>
              <BarChart
                series={[{ key: "sim", label: "Similarity", color: SERIES_GREY }]}
                rows={recall.recalled.map((r) => ({
                  label: r.outcomes?.length ? (r.outcomes.at(-1)?.liked ? "Liked" : "Disliked") : "Unrated",
                  sub: r.item_id.slice(0, 14),
                  values: { sim: r.similarity },
                }))}
                max={1}
              />
            </View>
          ) : null}
          <Text style={{ color: colors.muted, fontSize: 12.5 }}>
            The personal head turns on after 6 answers{typeof personalN === "number" ? ` (${personalN} so far)` : ""}. It starts from the
            crowd head and refits in milliseconds on cached features.
          </Text>
        </View>
      ) : (
        <View style={{ borderWidth: 1, borderColor: colors.line, borderRadius: 20, padding: 20, gap: 6 }}>
          <Text style={{ color: colors.text, fontSize: 15, fontWeight: "600" }}>No experiments yet</Text>
          <Text style={{ color: colors.muted, fontSize: 13.5, lineHeight: 20 }}>
            Pick or upload a photo above. The first run can take an extra minute while the GPU wakes up.
          </Text>
        </View>
      )}

      <View style={{ gap: 14, borderTopWidth: 1, borderTopColor: colors.line, paddingTop: 20 }}>
        <View style={[s.between, { alignItems: "center" }]}>
          <Text style={{ color: colors.text, fontSize: 18, fontWeight: "600", flexShrink: 1 }}>Memory</Text>
          <View style={[s.row, { gap: 8 }]}>
            <Button
              small
              busy={sleeping}
              onPress={() => {
                setSleeping(true);
                mem<SleepReport>("/sleep", "POST")
                  .then((rep) => {
                    localWrite.current = true;
                    const you = typeof rep.loo_auroc === "number" ? rep.loo_auroc.toFixed(2) : "n/a";
                    const crowd = typeof rep.crowd_loo_auroc === "number" ? rep.crowd_loo_auroc.toFixed(2) : "n/a";
                    pushEvent(
                      "sleep",
                      `Consolidated ${rep.n_labeled ?? 0} rated traces · ${rep.rules_new ?? 0} new rule${(rep.rules_new ?? 0) === 1 ? "" : "s"} · your head AUROC ${you} vs crowd ${crowd}`,
                    );
                    return refreshMemory();
                  })
                  .catch((e) => setError(e instanceof Error ? e.message : String(e)))
                  .finally(() => setSleeping(false));
              }}
            >
              Consolidate (sleep)
            </Button>
            <Button
              small
              onPress={() =>
                confirmReset(() => {
                  mem("/memory/reset", "POST")
                    .then(() => {
                      localWrite.current = true;
                      pushEvent("reset", "Memory erased · personal head back to the crowd head, rules retired");
                      return refreshMemory();
                    })
                    .catch((e) => setError(e instanceof Error ? e.message : String(e)));
                })
              }
            >
              Erase memory
            </Button>
          </View>
        </View>
        <View style={[s.row, { gap: 10 }]}>
          {(
            [
              ["engrams", "Traces", "brain states kept"],
              ["outcomes", "Outcomes", "like / dislike / chosen"],
              ["rules", "Rules", "learned in plain English"],
            ] as const
          ).map(([k, label, note]) => (
            <View key={k} style={{ flex: 1, borderWidth: 1, borderColor: flash[k] ? colors.red : colors.line, borderRadius: 16, padding: 12, gap: 2 }}>
              <Text style={{ color: flash[k] ? colors.red : colors.text, fontSize: 24, fontWeight: "600", fontVariant: ["tabular-nums"] }}>
                {counts ? counts[k] : "–"}
              </Text>
              <Text style={{ color: colors.text, fontSize: 12.5, fontWeight: "600" }}>{label}</Text>
              <Text style={{ color: colors.muted, fontSize: 11 }}>{note}</Text>
            </View>
          ))}
        </View>
        <View style={{ gap: 6 }}>
          <Text style={s.label}>Writes as they happen</Text>
          {events.length ? (
            events.map((e, i) => (
              <View key={e.t + e.kind} style={{ flexDirection: "row", gap: 10, alignItems: "flex-start", opacity: i === 0 ? 1 : 0.78 }}>
                <Text style={{ color: colors.muted, fontSize: 11.5, width: 58, fontVariant: ["tabular-nums"] }}>{clock(e.t)}</Text>
                <Text style={{ color: e.kind === "refit" || e.kind === "sleep" ? colors.red : colors.text, fontSize: 11.5, width: 54, fontWeight: "600" }}>
                  {KIND_LABEL[e.kind]}
                </Text>
                <Text style={{ flex: 1, color: colors.text, fontSize: 13, lineHeight: 18 }}>{e.text}</Text>
              </View>
            ))
          ) : (
            <Text style={{ color: colors.muted, fontSize: 13 }}>
              Run a stimulus, answer like or dislike, or ask the chat about a photo: every trace, outcome, refit and rule appears here the moment it is written.
            </Text>
          )}
        </View>
        {(() => {
          const pts = (curve?.points ?? []).filter((p) => p.loo_auroc !== null && p.crowd_auroc !== null);
          const byN = new Map<number, (typeof pts)[number]>();
          for (const p of pts) byN.set(p.n_labeled, p);
          const rows = [...byN.values()].sort((a, b) => a.n_labeled - b.n_labeled).slice(-6);
          return rows.length ? (
            <BarChart
              title="Learning curve · AUROC"
              series={[
                { key: "crowd", label: "Crowd head", color: SERIES_GREY },
                { key: "you", label: "Your head", color: SERIES_RED },
              ]}
              rows={rows.map((p) => ({ label: `${p.n_labeled}`, sub: "answers", values: { crowd: p.crowd_auroc ?? 0, you: p.loo_auroc ?? 0 } }))}
              max={1}
            />
          ) : (
            <Text style={{ color: colors.muted, fontSize: 13 }}>As answers accumulate, the accuracy of your head versus the crowd head is drawn here.</Text>
          );
        })()}
        {rules.length ? (
          <View style={{ gap: 8 }}>
            <Text style={s.label}>Rules my brain has learned</Text>
            {rules.slice(0, 4).map((r) => (
              <View key={r.id} style={{ flexDirection: "row", gap: 10, alignItems: "flex-start" }}>
                <Text style={{ color: colors.red, fontSize: 12, width: 34, fontVariant: ["tabular-nums"] }}>
                  {typeof r.evidence?.confidence === "number" ? r.evidence.confidence.toFixed(2) : ""}
                </Text>
                <Text style={{ flex: 1, color: colors.text, fontSize: 13.5, lineHeight: 19 }}>{r.text}</Text>
              </View>
            ))}
          </View>
        ) : null}
      </View>

      {runs.length > 1 ? (
        <View style={{ gap: 10 }}>
          <Text style={s.label}>Past experiments</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 10 }}>
            {runs.map((r) => (
              <Pressable
                key={r.id}
                accessibilityRole="button"
                onPress={() => setCurrentId(r.id)}
                style={{ borderWidth: 1, borderColor: r.id === currentId ? colors.text : colors.line, borderRadius: 14, padding: 4 }}
              >
                <Image source={{ uri: r.uri }} style={{ width: 72, height: 54, borderRadius: 10 }} resizeMode="cover" />
              </Pressable>
            ))}
          </ScrollView>
        </View>
      ) : null}
    </View>
  );
}
