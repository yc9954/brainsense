import { Ear, Eye, Heart, Palette, TrendingUp, User } from "lucide-react-native";
import { useState } from "react";
import { ScrollView, Text, View } from "react-native";
import Svg, { Line, Path, Rect, Text as SvgText } from "react-native-svg";
import { BarChart, SERIES_GREY, SERIES_RED, SERIES_WHITE, Tile } from "./bars";
import { colors, s } from "./ui";

/**
 * About: what BrainSense is, the architecture, and the measured numbers, in the layout of
 * the TRIBE v2 site: a heading, a paragraph, icon tiles, a pipeline figure, a bar chart.
 */
function H({ children }: { children: string }) {
  return (
    <Text style={{ color: colors.text, fontSize: 26, fontWeight: "600", letterSpacing: -0.6, lineHeight: 32 }}>{children}</Text>
  );
}
function P({ children }: { children: string }) {
  return <Text style={{ color: colors.muted, fontSize: 15, lineHeight: 23 }}>{children}</Text>;
}

/** The pipeline figure: inputs → pretrained encoders → transformer → subject block → cortex → heads → agent. */
const FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Apple SD Gothic Neo', sans-serif";
function Pipeline() {
  const W = 760;
  const H = 312;
  // measure the column: scale the figure down to fit when the column is wide enough (tablet,
  // desktop), keep it full size with sideways scrolling on phones so the labels stay legible
  const [cw, setCw] = useState(0);
  const scaled = cw >= 560 && cw < W;
  const fitW = scaled ? cw : W;
  const fitH = scaled ? Math.round((H * cw) / W) : H;
  const box = (x: number, y: number, w: number, h: number, label: string, sub?: string, fill = "transparent") => (
    <>
      <Rect x={x} y={y} width={w} height={h} rx={14} fill={fill} stroke={colors.text} strokeWidth={1} />
      <SvgText x={x + w / 2} y={y + h / 2 + (sub ? -4 : 5)} fill={colors.text} fontSize={14} fontWeight="600" fontFamily={FONT} textAnchor="middle">
        {label}
      </SvgText>
      {sub ? (
        <SvgText x={x + w / 2} y={y + h / 2 + 14} fill={colors.muted} fontSize={11} fontFamily={FONT} textAnchor="middle">
          {sub}
        </SvgText>
      ) : null}
    </>
  );
  const arrow = (x1: number, y1: number, x2: number, y2: number) => (
    <>
      <Line x1={x1} y1={y1} x2={x2} y2={y2} stroke={colors.text} strokeWidth={1} />
      <Path d={`M ${x2 - 6} ${y2 - 4} L ${x2} ${y2} L ${x2 - 6} ${y2 + 4}`} fill="none" stroke={colors.text} strokeWidth={1} />
    </>
  );
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} onLayout={(e) => setCw(e.nativeEvent.layout.width)}>
      <Svg width={fitW} height={fitH} viewBox={`0 0 ${W} ${H}`}>
        {/* inputs */}
        <Rect x={10} y={20} width={150} height={190} rx={16} fill="transparent" stroke={colors.text} strokeWidth={1} />
        {box(20, 30, 130, 52, "Video", "glasses clip · photo")}
        {box(20, 90, 130, 52, "Audio", "speech · music")}
        {box(20, 150, 130, 52, "Text", "copy · captions")}
        {/* encoders */}
        {box(200, 30, 130, 52, "V-JEPA2", "", "#3A3D42")}
        {box(200, 90, 130, 52, "wav2vec-BERT", "", "#4A4F55")}
        {box(200, 150, 130, 52, "Llama 3.2", "", "#2A2D31")}
        {arrow(150, 56, 198, 56)}
        {arrow(150, 116, 198, 116)}
        {arrow(150, 176, 198, 176)}
        {/* transformer + subject */}
        {box(370, 30, 120, 172, "Transformer", "TRIBE v2")}
        {arrow(330, 56, 368, 70)}
        {arrow(330, 116, 368, 116)}
        {arrow(330, 176, 368, 162)}
        {box(520, 30, 100, 172, "Subject", "block")}
        {arrow(490, 116, 518, 116)}
        {/* cortex */}
        {box(650, 30, 100, 80, "Predicted cortex", "20,484 vertices · 1 Hz", "#0E0F11")}
        {arrow(620, 70, 648, 70)}
        {/* ours */}
        {box(650, 122, 100, 80, "Calibrated heads", "aesthetic · attention · …", "#2A1614")}
        {arrow(700, 110, 700, 120)}
        {/* return path runs in the gap between the two rows, then drops into the agent box */}
        <Line x1={700} y1={202} x2={700} y2={222} stroke={colors.text} strokeWidth={1} />
        <Line x1={700} y1={222} x2={115} y2={222} stroke={colors.text} strokeWidth={1} />
        <Line x1={115} y1={222} x2={115} y2={238} stroke={colors.text} strokeWidth={1} />
        <Path d={`M 111 232 L 115 238 L 119 232`} fill="none" stroke={colors.text} strokeWidth={1} />
        {box(20, 240, 190, 56, "Muse Spark agent", "brain_eval · look_at tools, first-person brain")}
        {arrow(214, 268, 248, 268)}
        {box(252, 240, 230, 56, "A spoken opinion", "glasses captions · voice")}
        <SvgText x={500} y={272} fill={colors.muted} fontSize={11} fontFamily={FONT}>
          grey: Meta open models · red: this project
        </SvgText>
      </Svg>
    </ScrollView>
  );
}

export function AboutScreen() {
  return (
    <View style={{ gap: 36 }}>
      <View style={{ gap: 10 }}>
        <H>An AI model of the human brain looks before it gives an opinion</H>
        <P>
          BrainSense first predicts how a typical human cortex responds to what you are looking at, using Meta's brain
          foundation model TRIBE v2. Small heads calibrated on real rated data turn that response into aesthetic appeal,
          attention capture, desirability and reach. The Muse Spark agent then speaks only from those numbers: it says
          when it does not know, and names the brain regions and percentiles when you ask why.
        </P>
      </View>

      <View style={{ gap: 14 }}>
        <Text style={s.label}>Heads</Text>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 16 }}>
          <Tile icon={<Palette size={30} color={colors.text} strokeWidth={1.4} />} label="Aesthetic appeal" note="AADB, 2,500 photos" />
          <Tile icon={<Eye size={30} color={colors.text} strokeWidth={1.4} />} label="Attention capture" note="SnapUGC watch retention" />
          <Tile icon={<Heart size={30} color={colors.text} strokeWidth={1.4} />} label="Desirability" note="Unsplash downloads per view" />
          <Tile icon={<TrendingUp size={30} color={colors.text} strokeWidth={1.4} />} label="Reach" note="Unsplash views" />
          <Tile icon={<User size={30} color={colors.text} strokeWidth={1.4} />} label="Human-likeness" note="text · HC3" />
          <Tile icon={<Ear size={30} color={colors.text} strokeWidth={1.4} />} label="Hook" note="audio" />
        </View>
      </View>

      <View style={{ gap: 14 }}>
        <H>Architecture</H>
        <P>
          Video, audio and text are embedded by V-JEPA2, wav2vec-BERT and Llama 3.2; TRIBE v2's transformer and subject
          block predict the 1 Hz response of 20,484 cortical vertices on fsaverage5. That far is Meta's open model; the
          rest is this project: 360 cortical-area means reduced by PCA and calibrated by linear heads, and the agent sees
          only the head outputs. Raw brain vectors never reach the LLM.
        </P>
        <Pipeline />
      </View>

      <View style={{ gap: 14 }}>
        <H>What we measured</H>
        <P>
          On the same 2,500 AADB aesthetic ratings, brain features are not more accurate than the raw embedding. At matched
          dimensionality they are on par, and area means pull slightly ahead. What the brain features buy is not accuracy
          but explanation: the agent can say "visual attention drops after two seconds", not "embedding dimension 731".
        </P>
        <BarChart
          title="AADB aesthetics · AUROC (5-fold)"
          series={[
            { key: "linear", label: "Raw embedding, linear", color: SERIES_WHITE },
            { key: "pooled", label: "9 regions pooled", color: SERIES_GREY },
            { key: "tribe", label: "360 areas → PCA", color: SERIES_RED },
          ]}
          rows={[{ label: "Aesthetic", sub: "n = 2,500", values: { linear: 0.728, pooled: 0.669, tribe: 0.753 } }]}
          max={1}
        />
        <BarChart
          title="Holdout AUROC per head"
          series={[{ key: "auroc", label: "TRIBE head", color: SERIES_RED }]}
          rows={[
            { label: "Aesthetic", values: { auroc: 0.721 } },
            { label: "Attention", values: { auroc: 0.65 } },
            { label: "Desirability", values: { auroc: 0.58 } },
            { label: "Reach", values: { auroc: 0.59 } },
          ]}
          max={1}
        />
        <BarChart
          title="Latency · one 6 s clip (L40S, seconds)"
          series={[
            { key: "before", label: "Before", color: SERIES_GREY },
            { key: "after", label: "Now", color: SERIES_RED },
          ]}
          rows={[{ label: "TRIBE", values: { before: 43, after: 14 } }]}
          max={45}
          format={(v) => `${v.toFixed(0)}s`}
        />
      </View>

      <View style={{ gap: 10 }}>
        <H>Limits</H>
        <P>
          TRIBE v2 is an encoder trained on passive viewing and predicts an average subject; it has never seen a choice
          or a purchase. Photos go in as 6-second stills, so the temporal module has little to do, and the outcome
          datasets are small. That is why every head reports a confidence, and the agent says so when it is low.
        </P>
      </View>

      <View style={{ gap: 6, borderTopWidth: 1, borderTopColor: colors.line, paddingTop: 16 }}>
        <Text style={{ color: colors.muted, fontSize: 12.5, lineHeight: 18 }}>
          Meta Model API (Muse Spark 1.3, tool calling) · TRIBE v2 (open weights) · CopilotKit runtime (MIT) · Modal (L40S) ·
          the Wearables Device Access Toolkit flow reproduced by the glasses emulator. Head bust: Meta TRIBE v2 demo
          (non-commercial use). Brain mesh: fsaverage5 (FreeSurfer).
        </Text>
      </View>
    </View>
  );
}
