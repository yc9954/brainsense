import { createContext, type ReactNode, useContext, useMemo, useState } from "react";
import type { BrainEval } from "./brainsense-api";

/** What the user is currently looking at in the Look tab, shared with the chat agent context. */
export type CurrentItem = { id: string; name: string; evalData?: BrainEval };

const Ctx = createContext<{
  current?: CurrentItem;
  setCurrent: (item?: CurrentItem) => void;
  voice: boolean; // voice mode: spoken replies, answer in one turn from the cached summary
  setVoice: (on: boolean) => void;
}>({ setCurrent: () => {}, voice: false, setVoice: () => {} });

export function BrainSenseProvider({ children }: { children: ReactNode }) {
  const [current, setCurrent] = useState<CurrentItem>();
  const [voice, setVoice] = useState(false);
  const value = useMemo(() => ({ current, setCurrent, voice, setVoice }), [current, voice]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useBrainSense = () => useContext(Ctx);

/** Compact, model-facing summary of an evaluation (what the chat agent sees as context). */
export function summarize(evalData?: BrainEval): string {
  if (!evalData) return "";
  const parts: string[] = [];
  for (const [name, h] of Object.entries(evalData.heads)) {
    if (!h || name === "personal" || !("percentile" in h)) continue;
    parts.push(
      `${name}: top ${Math.round(100 - h.percentile)}% (confidence ${h.confidence.toFixed(2)}; ${h.top_features
        .slice(0, 2)
        .map((f) => `${f.contribution >= 0 ? "▲" : "▼"}${f.name}`)
        .join(", ")})`,
    );
  }
  return parts.join(" · ");
}
