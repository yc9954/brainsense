import { Brain } from "lucide-react-native";
import { useEffect, useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";
import { BrainCard } from "./brainsense";
import { BRAINSENSE_URL, type BrainEval } from "./brainsense-api";
import { Card, colors, ErrorNotice, s } from "./ui";

/** Inline card for the OpenMuse chat when the agent calls `brain_eval`. */
export function BrainToolCard({ result, loading }: { result: unknown; loading: boolean }) {
  let value = result;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch {
      value = undefined;
    }
  }
  const light = value as (BrainEval & { error?: string; summary?: string }) | undefined;
  // The tool result is deliberately small (see brainEvalTool); fetch the cortex data for the card here.
  const [heavy, setHeavy] = useState<Partial<BrainEval> | undefined>();
  const itemId = light?.item_id;
  const needHeavy = !!itemId && !light?.vertex_ts && !light?.brain_frames?.length;
  useEffect(() => {
    if (!needHeavy) return;
    let cancelled = false;
    fetch(`${BRAINSENSE_URL}/eval/${encodeURIComponent(itemId)}`)
      .then((r) => (r.ok ? r.json() : undefined))
      .then((ev: BrainEval | undefined) => {
        if (!cancelled && ev) setHeavy({ vertex_ts: ev.vertex_ts, brain_frames: ev.brain_frames });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [itemId, needHeavy]);
  const data = light && heavy ? { ...light, ...heavy } : light;
  if (loading && !data)
    return (
      <Card style={{ ...s.row, gap: 10, padding: 14, backgroundColor: "#EEEEF0", maxWidth: 440 }}>
        <ActivityIndicator size="small" color={colors.blueDark} />
        <Text style={s.text}>My brain is looking… (TRIBE v2, about 14 s)</Text>
      </Card>
    );
  if (!data || data.error || !data.heads)
    return (
      <Card style={{ padding: 14, gap: 8, backgroundColor: "#EEEEF0", maxWidth: 440 }}>
        <View style={[s.row, { gap: 10 }]}>
          <Brain size={18} color={colors.blueDark} />
          <Text style={s.text}>Could not read the brain response</Text>
        </View>
        <ErrorNotice
          error={
            data?.error || "The result is empty. Attach a photo first."
          }
        />
      </Card>
    );
  return (
    <View style={{ maxWidth: 560, width: "100%" }}>
      <BrainCard data={data} />
    </View>
  );
}
