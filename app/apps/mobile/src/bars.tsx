import { Text, View } from "react-native";
import { colors } from "./ui";

/**
 * The TRIBE v2 site's bar chart: a category label on the left, one bar per series with the value
 * printed at its end, a small legend at the top right. White / grey / red only.
 */
export type BarSeries = { key: string; label: string; color: string };
export type BarRow = { label: string; sub?: string; values: Record<string, number | undefined> };

export const SERIES_WHITE = "#FFFFFF";
export const SERIES_GREY = colors.grey;
export const SERIES_RED = colors.red;

export function BarChart({
  series,
  rows,
  max = 1,
  format = (v: number) => v.toFixed(2),
  title,
  signed = false,
}: {
  series: BarSeries[];
  rows: BarRow[];
  max?: number;
  format?: (v: number) => string;
  title?: string;
  /** diverging bars around a centre axis (z-scores) */
  signed?: boolean;
}) {
  return (
    <View style={{ gap: 14 }}>
      <View style={{ flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        {title ? <Text style={{ color: colors.text, fontSize: 15, fontWeight: "600" }}>{title}</Text> : <View />}
        <View style={{ gap: 6, alignItems: "flex-end" }}>
          {series.map((sr) => (
            <View key={sr.key} style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
              <Text style={{ color: colors.text, fontSize: 12.5 }}>{sr.label}</Text>
              <View style={{ width: 44, height: 14, backgroundColor: sr.color }} />
            </View>
          ))}
        </View>
      </View>
      <View style={{ borderLeftWidth: 1, borderLeftColor: colors.text, paddingLeft: 12, gap: 18 }}>
        {rows.map((row) => (
          <View key={row.label} style={{ flexDirection: "row", gap: 12 }}>
            <View style={{ width: 64, justifyContent: "center" }}>
              <Text style={{ color: colors.text, fontSize: 14, fontWeight: "600" }}>{row.label}</Text>
              {row.sub ? <Text style={{ color: colors.muted, fontSize: 11 }}>{row.sub}</Text> : null}
            </View>
            <View style={{ flex: 1, gap: 6 }}>
              {series.map((sr) => {
                const v = row.values[sr.key];
                if (v === undefined || Number.isNaN(v)) return null;
                const pct = Math.max(0, Math.min(1, Math.abs(v) / max));
                if (signed) {
                  const half = Math.max(1, pct * 50);
                  return (
                    <View key={sr.key} style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
                      <View style={{ flex: 1, height: 18, justifyContent: "center" }}>
                        <View style={{ position: "absolute", left: "50%", top: 0, bottom: 0, width: 1, backgroundColor: colors.grey }} />
                        <View
                          style={{
                            position: "absolute",
                            height: 18,
                            backgroundColor: sr.color,
                            ...(v >= 0 ? { left: "50%", width: `${half}%` } : { right: "50%", width: `${half}%` }),
                          }}
                        />
                      </View>
                      <Text style={{ width: 52, color: colors.text, fontSize: 13, fontVariant: ["tabular-nums"] }}>{format(v)}</Text>
                    </View>
                  );
                }
                return (
                  <View key={sr.key} style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
                    <View style={{ flex: 1, height: 18, justifyContent: "center" }}>
                      <View style={{ width: `${Math.max(1.5, pct * 100)}%`, height: 18, backgroundColor: sr.color }} />
                    </View>
                    <Text style={{ width: 46, color: colors.text, fontSize: 13, fontVariant: ["tabular-nums"] }}>{format(v)}</Text>
                  </View>
                );
              })}
            </View>
          </View>
        ))}
      </View>
    </View>
  );
}

/** The site's icon tile: a rounded square outline with a glyph, label underneath. */
export function Tile({
  icon,
  label,
  note,
  active,
  onPress,
}: {
  icon: React.ReactNode;
  label: string;
  note?: string;
  active?: boolean;
  onPress?: () => void;
}) {
  const Wrapper = onPress ? require("react-native").Pressable : View;
  return (
    <Wrapper onPress={onPress} accessibilityRole={onPress ? "button" : undefined} style={{ alignItems: "center", gap: 10, width: 104 }}>
      <View
        style={{
          width: 88,
          height: 88,
          borderRadius: 22,
          borderWidth: 1,
          borderColor: active ? colors.text : colors.line,
          backgroundColor: active ? "#16181B" : "transparent",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {icon}
      </View>
      <Text style={{ color: colors.text, fontSize: 14, fontWeight: "600", textAlign: "center" }}>{label}</Text>
      {note ? <Text style={{ color: colors.muted, fontSize: 11, textAlign: "center" }}>{note}</Text> : null}
    </Wrapper>
  );
}
