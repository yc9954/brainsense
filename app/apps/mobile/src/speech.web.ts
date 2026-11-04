/** Say the brain's answer out loud (web: SpeechSynthesis) and listen for a question (Web Speech API). */
export function speak(text: string, lang = "en-US") {
  try {
    const synth = window.speechSynthesis;
    if (!synth) return;
    synth.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = lang;
    u.rate = 1.02;
    const voice = synth.getVoices().find((v) => v.lang.replace("_", "-").startsWith(lang.slice(0, 2)) && /Samantha|Google|Premium|Enhanced|Siri/i.test(v.name)) ??
      synth.getVoices().find((v) => v.lang.replace("_", "-").startsWith(lang.slice(0, 2)));
    if (voice) u.voice = voice;
    synth.speak(u);
  } catch {}
}
export function stopSpeaking() {
  try {
    window.speechSynthesis?.cancel();
  } catch {}
}
type Recognition = {
  lang: string;
  interimResults: boolean;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
};
const Ctor = (globalThis as unknown as { webkitSpeechRecognition?: new () => Recognition; SpeechRecognition?: new () => Recognition });
export const canListen = Boolean(Ctor.SpeechRecognition || Ctor.webkitSpeechRecognition);
/** "Hey Meta"-style one-shot dictation; resolves with the transcript. */
export function listenOnce(lang = "en-US"): Promise<string> {
  const C = Ctor.SpeechRecognition || Ctor.webkitSpeechRecognition;
  if (!C) return Promise.reject(new Error("This browser does not support speech recognition"));
  return new Promise((resolve, reject) => {
    const r = new C();
    r.lang = lang;
    r.interimResults = false;
    r.maxAlternatives = 1;
    let done = false;
    r.onresult = (e) => {
      done = true;
      resolve(e.results[0]?.[0]?.transcript ?? "");
    };
    r.onerror = (e) => {
      if (!done) reject(new Error(e.error === "not-allowed" ? "Microphone access is needed" : `Speech recognition error: ${e.error}`));
    };
    r.onend = () => {
      if (!done) resolve("");
    };
    r.start();
  });
}
