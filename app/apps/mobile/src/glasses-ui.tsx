import { Mic, RefreshCw, X } from "lucide-react-native";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { Animated, Easing, Pressable, ScrollView, Text, TextInput, useWindowDimensions, View } from "react-native";
import Svg, { Circle, Defs, LinearGradient, RadialGradient, Rect, Stop } from "react-native-svg";
import { canListen, listenOnce, speak, stopSpeaking } from "./speech";

/**
 * The glasses chrome, shared by the phone and web cameras: a landscape first-person frame, the way
 * the Meta glasses see, with a Meta-AI-style overlay. On a phone held upright the whole view turns
 * 90°, so you turn the phone and look through it like the glasses. Nothing here looks like a chat:
 * a device pill, the Meta AI orb that breathes while idle, spins while the brain looks and ripples
 * while it speaks, captions in the lower left, quick asks, and the answer spoken aloud. The
 * transcript still lands in the chat behind.
 */
export type GlassesState = "starting" | "watching" | "capturing" | "thinking" | "speaking" | "error";
export const QUICK_ASKS = ["What do you think?", "Is this text good?", "How is this video?", "Should I buy it?", "Why?"];

export function Orb({ state, size = 76 }: { state: GlassesState; size?: number }) {
  const pulse = useRef(new Animated.Value(0)).current;
  const spin = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    const slow = state === "watching" || state === "starting";
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: slow ? 2200 : state === "speaking" ? 700 : 1100, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
        Animated.timing(pulse, { toValue: 0, duration: slow ? 2200 : state === "speaking" ? 700 : 1100, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
      ]),
    );
    loop.start();
    const rot = Animated.loop(Animated.timing(spin, { toValue: 1, duration: state === "thinking" || state === "capturing" ? 1400 : 9000, easing: Easing.linear, useNativeDriver: true }));
    rot.start();
    return () => {
      loop.stop();
      rot.stop();
    };
  }, [pulse, spin, state]);
  const scale = pulse.interpolate({ inputRange: [0, 1], outputRange: [1, state === "speaking" ? 1.12 : 1.06] });
  const rotate = spin.interpolate({ inputRange: [0, 1], outputRange: ["0deg", "360deg"] });
  const glow = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.35, 0.8] });
  return (
    <View style={{ width: size * 1.8, height: size * 1.8, alignItems: "center", justifyContent: "center" }}>
      <Animated.View style={{ position: "absolute", width: size * 1.8, height: size * 1.8, opacity: glow, transform: [{ scale }] }}>
        <Svg width="100%" height="100%" viewBox="0 0 100 100">
          <Defs>
            <RadialGradient id="halo" cx="50%" cy="50%" r="50%">
              <Stop offset="0%" stopColor="#7C5CFF" stopOpacity={0.55} />
              <Stop offset="55%" stopColor="#1D8CFF" stopOpacity={0.18} />
              <Stop offset="100%" stopColor="#000" stopOpacity={0} />
            </RadialGradient>
          </Defs>
          <Circle cx={50} cy={50} r={50} fill="url(#halo)" />
        </Svg>
      </Animated.View>
      <Animated.View style={{ width: size, height: size, transform: [{ scale }, { rotate }] }}>
        <Svg width="100%" height="100%" viewBox="0 0 100 100">
          <Defs>
            <LinearGradient id="ring" x1="0%" y1="0%" x2="100%" y2="100%">
              <Stop offset="0%" stopColor="#0866FF" />
              <Stop offset="45%" stopColor="#7A4DFF" />
              <Stop offset="100%" stopColor="#FF4FA8" />
            </LinearGradient>
            <RadialGradient id="core" cx="40%" cy="35%" r="70%">
              <Stop offset="0%" stopColor="#FFFFFF" stopOpacity={0.95} />
              <Stop offset="45%" stopColor="#9DB8FF" stopOpacity={0.9} />
              <Stop offset="100%" stopColor="#2B1A6B" stopOpacity={1} />
            </RadialGradient>
          </Defs>
          <Circle cx={50} cy={50} r={48} fill="url(#ring)" />
          <Circle cx={50} cy={50} r={36} fill="url(#core)" />
        </Svg>
      </Animated.View>
    </View>
  );
}

function Vignette() {
  return (
    <Svg pointerEvents="none" width="100%" height="100%" style={{ position: "absolute", inset: 0 }} viewBox="0 0 100 100" preserveAspectRatio="none">
      <Defs>
        <LinearGradient id="top" x1="0" y1="0" x2="0" y2="1">
          <Stop offset="0%" stopColor="#000" stopOpacity={0.55} />
          <Stop offset="100%" stopColor="#000" stopOpacity={0} />
        </LinearGradient>
        <LinearGradient id="bottom" x1="0" y1="0" x2="0" y2="1">
          <Stop offset="0%" stopColor="#000" stopOpacity={0} />
          <Stop offset="100%" stopColor="#000" stopOpacity={0.82} />
        </LinearGradient>
      </Defs>
      <Rect x={0} y={0} width={100} height={20} fill="url(#top)" />
      <Rect x={0} y={55} width={100} height={45} fill="url(#bottom)" />
    </Svg>
  );
}

/** Viewfinder corners, the way the glasses' capture indicator frames the shot. */
function Corners() {
  const c = { position: "absolute" as const, width: 22, height: 22, borderColor: "rgba(255,255,255,0.55)" };
  return (
    <View pointerEvents="none" style={{ position: "absolute", inset: 14 }}>
      <View style={[c, { top: 0, left: 0, borderTopWidth: 1.5, borderLeftWidth: 1.5, borderTopLeftRadius: 8 }]} />
      <View style={[c, { top: 0, right: 0, borderTopWidth: 1.5, borderRightWidth: 1.5, borderTopRightRadius: 8 }]} />
      <View style={[c, { bottom: 0, left: 0, borderBottomWidth: 1.5, borderLeftWidth: 1.5, borderBottomLeftRadius: 8 }]} />
      <View style={[c, { bottom: 0, right: 0, borderBottomWidth: 1.5, borderRightWidth: 1.5, borderBottomRightRadius: 8 }]} />
    </View>
  );
}

const glass = { backgroundColor: "rgba(255,255,255,0.14)", borderColor: "rgba(255,255,255,0.22)", borderWidth: 1 } as const;

export function GlassesChrome({
  state,
  status,
  question,
  reply,
  error,
  onAsk,
  onClose,
  onFlip,
  children,
}: {
  state: GlassesState;
  status: string;
  question?: string;
  reply?: string;
  error?: string;
  onAsk: (text: string) => void | Promise<void>;
  onClose: () => void;
  onFlip?: () => void;
  children?: ReactNode; // the camera view
}) {
  const [draft, setDraft] = useState("");
  const [typing, setTyping] = useState(false);
  const [listening, setListening] = useState(false);
  const spoken = useRef<string | undefined>(undefined);
  const busy = state === "capturing" || state === "thinking";
  const win = useWindowDimensions();
  // the glasses see landscape; on an upright phone the whole view turns so you hold it sideways
  const portrait = win.height > win.width;
  const W = portrait ? win.height : win.width;
  const H = portrait ? win.width : win.height;

  // speak each new reply once, like the glasses would
  useEffect(() => {
    if (reply && reply !== spoken.current && state === "speaking") {
      spoken.current = reply;
      speak(reply);
    }
  }, [reply, state]);
  useEffect(() => () => stopSpeaking(), []);

  const ask = (t: string) => {
    const q = t.trim();
    if (!q || busy) return;
    stopSpeaking();
    setDraft("");
    setTyping(false);
    void onAsk(q);
  };
  const dictate = async () => {
    if (listening || busy) return;
    setListening(true);
    try {
      const t = await listenOnce("en-US");
      if (t) ask(t);
    } catch {
      setTyping(true);
    } finally {
      setListening(false);
    }
  };

  const caption = reply ? (
    <Text
      style={{
        color: "#fff",
        fontSize: H < 420 ? 16 : 19,
        lineHeight: H < 420 ? 22 : 27,
        fontWeight: "500",
        textShadowColor: "rgba(0,0,0,0.7)",
        textShadowRadius: 10,
        textShadowOffset: { width: 0, height: 1 },
      }}
      numberOfLines={H < 420 ? 4 : 6}
    >
      {reply}
    </Text>
  ) : (
    <Text style={{ color: "rgba(255,255,255,0.75)", fontSize: 15 }}>
      {state === "thinking" ? "My brain is looking…" : state === "capturing" ? "Capturing what you just saw…" : "Ask about what you are looking at"}
    </Text>
  );

  const recording = state === "capturing" || state === "thinking";

  return (
    <View style={{ flex: 1, backgroundColor: "#000", alignItems: "center", justifyContent: "center", overflow: "hidden" }}>
      <View style={{ width: W, height: H, transform: portrait ? [{ rotate: "90deg" }] : undefined, backgroundColor: "#000" }}>
        <View style={{ flex: 1 }}>{children}</View>
        <Vignette />
        <Corners />

        {/* top bar: device pill left, status + controls right */}
        <View style={{ position: "absolute", top: 22, left: 26, right: 26, flexDirection: "row", alignItems: "center", gap: 10 }}>
          <View style={[{ flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999 }, glass]}>
            <View style={{ width: 7, height: 7, borderRadius: 4, backgroundColor: state === "error" ? "#FF5A5F" : "#3DDC84" }} />
            <Text style={{ color: "#fff", fontSize: 12.5, fontWeight: "600", letterSpacing: 0.2 }}>Ray-Ban Meta</Text>
            <Text style={{ color: "rgba(255,255,255,0.6)", fontSize: 12 }}>· emulator</Text>
          </View>
          <View style={{ flex: 1 }} />
          <View style={{ flexDirection: "row", alignItems: "center", gap: 7 }}>
            <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: recording ? "#FF3B30" : "rgba(255,255,255,0.35)" }} />
            <Text style={{ color: "rgba(255,255,255,0.75)", fontSize: 12, maxWidth: 260 }} numberOfLines={1}>
              {status}
            </Text>
          </View>
          {onFlip ? (
            <Pressable accessibilityRole="button" accessibilityLabel="Switch camera" onPress={onFlip} style={[{ width: 34, height: 34, borderRadius: 17, alignItems: "center", justifyContent: "center" }, glass]}>
              <RefreshCw size={14} color="#fff" />
            </Pressable>
          ) : null}
          <Pressable accessibilityRole="button" accessibilityLabel="Close glasses mode" onPress={onClose} style={[{ width: 34, height: 34, borderRadius: 17, alignItems: "center", justifyContent: "center" }, glass]}>
            <X size={15} color="#fff" />
          </Pressable>
        </View>

        {/* bottom: captions left, orb right, quick asks underneath */}
        <View style={{ position: "absolute", left: 26, right: 26, bottom: 18, gap: 10 }}>
          <View style={{ flexDirection: "row", alignItems: "flex-end", gap: 16 }}>
            <View style={{ flex: 1, gap: 6, paddingBottom: 6 }}>
              {error ? <Text style={{ color: "#FFB4AB", fontSize: 13.5 }}>{error}</Text> : null}
              {question ? (
                <Text style={{ color: "rgba(255,255,255,0.7)", fontSize: 13.5 }} numberOfLines={1}>
                  “{question}”
                </Text>
              ) : null}
              {caption}
            </View>
            <View style={{ alignItems: "center", width: 112 }}>
              <Pressable accessibilityRole="button" accessibilityLabel={canListen ? "Ask by voice" : "Ask"} onPress={() => (canListen ? void dictate() : setTyping(true))} disabled={busy}>
                <Orb state={listening ? "thinking" : state} size={H < 420 ? 54 : 64} />
              </Pressable>
              <Text style={{ color: "rgba(255,255,255,0.55)", fontSize: 11, marginTop: -10, textAlign: "center" }} numberOfLines={1}>
                {listening ? "Listening…" : canListen ? "“Hey Meta”" : "Tap to type"}
              </Text>
            </View>
          </View>

          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingHorizontal: 2 }}>
            {QUICK_ASKS.map((q) => (
              <Pressable key={q} accessibilityRole="button" disabled={busy} onPress={() => ask(q)} style={({ pressed }) => [{ paddingHorizontal: 13, paddingVertical: 8, borderRadius: 999, opacity: busy ? 0.5 : pressed ? 0.7 : 1 }, glass]}>
                <Text style={{ color: "#fff", fontSize: 13, fontWeight: "600" }}>{q}</Text>
              </Pressable>
            ))}
            <Pressable accessibilityRole="button" onPress={() => setTyping((v) => !v)} style={[{ paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, flexDirection: "row", alignItems: "center", gap: 6 }, glass]}>
              <Mic size={13} color="#fff" />
              <Text style={{ color: "#fff", fontSize: 13, fontWeight: "600" }}>Type</Text>
            </Pressable>
          </ScrollView>

          {typing ? (
            <View style={[{ flexDirection: "row", alignItems: "center", gap: 8, borderRadius: 24, paddingLeft: 16, paddingRight: 6, paddingVertical: 2, maxWidth: 520 }, glass]}>
              <TextInput
                autoFocus
                value={draft}
                onChangeText={setDraft}
                placeholder="Ask about what you see…"
                placeholderTextColor="rgba(255,255,255,0.5)"
                style={{ flex: 1, fontSize: 15, color: "#fff", paddingVertical: 9 }}
                onSubmitEditing={() => ask(draft)}
                editable={!busy}
              />
              <Pressable accessibilityRole="button" accessibilityLabel="Send" disabled={busy || !draft.trim()} onPress={() => ask(draft)} style={{ width: 34, height: 34, borderRadius: 17, backgroundColor: draft.trim() ? "#fff" : "rgba(255,255,255,0.25)", alignItems: "center", justifyContent: "center" }}>
                <Text style={{ color: "#0B0B0F", fontWeight: "800" }}>↑</Text>
              </Pressable>
            </View>
          ) : null}
        </View>
      </View>
    </View>
  );
}
