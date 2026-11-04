/**
 * Read the agent's newest reply aloud while it streams: every time a sentence completes, speak it.
 * Only messages that arrive after voice mode was switched on are read (no replaying history).
 */
import { useEffect, useRef } from "react";
import { speak, stopSpeaking } from "./voice";

type Msg = { id: string; role: string; content?: unknown };
const SENTENCE = /[^.!?。！？\n]+[.!?。！？\n]+|[^.!?。！？\n]+$/g;

function textOf(m: Msg): string {
  const c = m.content;
  if (typeof c === "string") return c;
  if (Array.isArray(c))
    return c
      .map((p) => (typeof p === "string" ? p : ((p as { text?: string }).text ?? "")))
      .join("");
  return "";
}

const ACK = {
  ko: ["잠깐만, 보고 있어.", "음, 내 뇌가 읽는 중이야."],
  en: ["One sec, I'm looking.", "Hmm, my brain is reading it."],
};
const STILL = { ko: "거의 다 됐어.", en: "Almost there." };

export function useSpokenReplies(messages: Msg[], enabled: boolean, running: boolean): void {
  const seenAtEnable = useRef<Set<string>>(new Set());
  const spoken = useRef<Record<string, number>>({}); // message id → chars already spoken
  const wasEnabled = useRef(false);
  const wasRunning = useRef(false);
  const ackTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // Voice mode: acknowledge immediately when a turn starts (the model takes 5–15 s to its first
  // token), and say "almost there" if nothing has been spoken after 8 s — silence feels broken.
  useEffect(() => {
    if (!enabled) return;
    if (running && !wasRunning.current) {
      const lastUser = [...messages].reverse().find((m) => m.role === "user");
      const ko = /[가-힣]/.test(textOf(lastUser ?? { id: "", role: "" }));
      const lang = ko ? "ko" : "en";
      speak(ACK[lang][Math.floor(Math.random() * ACK[lang].length)], ko ? "ko-KR" : "en-US");
      clearTimeout(ackTimer.current);
      ackTimer.current = setTimeout(() => {
        const last = [...messages]
          .reverse()
          .find((m) => m.role === "assistant" && !seenAtEnable.current.has(m.id));
        if (!last || !textOf(last).trim()) speak(STILL[lang], ko ? "ko-KR" : "en-US");
      }, 8000);
    }
    if (!running && wasRunning.current) clearTimeout(ackTimer.current);
    wasRunning.current = running;
  }, [running, enabled, messages]);
  useEffect(() => {
    if (enabled && !wasEnabled.current) {
      seenAtEnable.current = new Set(messages.map((m) => m.id));
      spoken.current = {};
    }
    if (!enabled && wasEnabled.current) stopSpeaking();
    wasEnabled.current = enabled;
  }, [enabled, messages]);
  useEffect(() => {
    if (!enabled) return;
    const last = [...messages]
      .reverse()
      .find((m) => m.role === "assistant" && !seenAtEnable.current.has(m.id));
    if (!last) return;
    const text = textOf(last);
    const done = spoken.current[last.id] ?? 0;
    if (text.length <= done) return;
    const rest = text.slice(done);
    const parts = rest.match(SENTENCE) ?? [];
    // speak completed sentences now; keep a trailing fragment until it completes or the run ends
    let consumed = 0;
    for (let i = 0; i < parts.length; i++) {
      const p = parts[i];
      const complete = /[.!?。！？\n]\s*$/.test(p) || (!running && i === parts.length - 1);
      if (!complete) break;
      speak(p.trim());
      consumed += p.length;
    }
    if (consumed) spoken.current[last.id] = done + consumed;
  }, [messages, enabled, running]);
}
