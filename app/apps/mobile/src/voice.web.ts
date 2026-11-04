/**
 * Voice I/O for the web build: browser speech recognition (instant, free) and speech synthesis that
 * reads the agent's reply sentence by sentence while it is still streaming, so the first spoken words
 * land within a couple of seconds of the first token. Native uses ./voice.ts (expo-speech, no STT).
 */
type Recognition = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult:
    | ((e: {
        results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }>;
      }) => void)
    | null;
  onend: (() => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};

export const voiceSupport = () => {
  const w = globalThis as unknown as {
    SpeechRecognition?: unknown;
    webkitSpeechRecognition?: unknown;
    speechSynthesis?: unknown;
  };
  return {
    stt: Boolean(w.SpeechRecognition || w.webkitSpeechRecognition),
    tts: Boolean(w.speechSynthesis),
  };
};

let active: Recognition | undefined;

/** Listen once; calls onText with the interim transcript as it forms and onFinal with the committed one. */
export function startListening(
  lang: string,
  onText: (text: string) => void,
  onFinal: (text: string) => void,
  onEnd: (error?: string) => void,
): boolean {
  const w = globalThis as unknown as {
    SpeechRecognition?: new () => Recognition;
    webkitSpeechRecognition?: new () => Recognition;
  };
  const Ctor = w.SpeechRecognition || w.webkitSpeechRecognition;
  if (!Ctor) return false;
  stopSpeaking();
  const rec = new Ctor();
  rec.lang = lang;
  rec.interimResults = true;
  rec.continuous = false;
  let finalText = "";
  rec.onresult = (e) => {
    let interim = "";
    for (let i = 0; i < e.results.length; i++) {
      const r = e.results[i];
      if (r.isFinal) finalText += r[0].transcript;
      else interim += r[0].transcript;
    }
    onText((finalText + interim).trim());
  };
  rec.onerror = (e) => onEnd(e.error);
  rec.onend = () => {
    active = undefined;
    if (finalText.trim()) onFinal(finalText.trim());
    onEnd();
  };
  active = rec;
  rec.start();
  return true;
}

export function stopListening(): void {
  active?.stop();
  active = undefined;
}

const pickVoice = (lang: string) => {
  const synth = globalThis.speechSynthesis;
  const voices = synth?.getVoices?.() ?? [];
  const pref = lang.startsWith("ko")
    ? ["유나", "Yuna", "지안", "Jian", "소라", "Sora", "Google 한국의"]
    : ["Samantha", "Ava", "Google US English", "Daniel"];
  return (
    pref.map((n) => voices.find((v) => v.name.includes(n))).find(Boolean) ||
    voices.find((v) => v.lang.toLowerCase().startsWith(lang.slice(0, 2))) ||
    undefined
  );
};

export function speak(text: string, lang?: string): void {
  const synth = globalThis.speechSynthesis;
  if (!synth || !text.trim()) return;
  const l = lang ?? (/[가-힣]/.test(text) ? "ko-KR" : "en-US");
  const u = new SpeechSynthesisUtterance(text.replace(/[*_`#>]/g, ""));
  u.lang = l;
  const v = pickVoice(l);
  if (v) u.voice = v;
  u.rate = l.startsWith("ko") ? 1.08 : 1.05;
  synth.speak(u);
}

export function stopSpeaking(): void {
  globalThis.speechSynthesis?.cancel?.();
}
