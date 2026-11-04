import { Brain } from "lucide-react-native";
import { useEffect, useState } from "react";
import { Pressable, Text, View } from "react-native";
import { brainsense } from "./brainsense-api";
import { colors, s } from "./ui";
import { useWorkspace } from "./workspace";

/** Header chip: is the brain (TRIBE v2 server + heads) reachable? Polls /health every 20 s. */
export function BrainEntry() {
  const { navigate } = useWorkspace();
  const [state, setState] = useState<{ ok: boolean; heads?: number; items?: number } | null>(null);
  useEffect(() => {
    let alive = true;
    const tick = () =>
      brainsense
        .health()
        .then((h) => alive && setState({ ok: h.ok, heads: h.heads?.length, items: h.cached_items }))
        .catch(() => alive && setState({ ok: false }));
    tick();
    const id = setInterval(tick, 20000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);
  const ok = state?.ok === true;
  const label =
    state === null
      ? "Brain · connecting"
      : ok
        ? `Brain · online · ${state.heads ?? 0} heads`
        : "Brain · offline";
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={() => navigate("lab")}
      style={[
        s.row,
        {
          alignSelf: "center",
          gap: 6,
          paddingHorizontal: 12,
          paddingVertical: 7,
          borderRadius: 20,
          backgroundColor: colors.sky,
        },
      ]}
    >
      <Brain size={13} color={colors.muted} />
      <Text style={{ fontSize: 12, color: colors.muted }}>{label}</Text>
      <View
        style={{
          width: 5,
          height: 5,
          borderRadius: 3,
          backgroundColor: ok ? "#57AD85" : state === null ? "#D9A441" : "#ACB0B5",
        }}
      />
    </Pressable>
  );
}
