import * as Speech from "expo-speech";

/** Say the brain's answer out loud, the way the glasses would (native: expo-speech). */
export function speak(text: string, lang = "en-US") {
  try {
    Speech.stop();
    Speech.speak(text, { language: lang, rate: 1.02, pitch: 1.0 });
  } catch {}
}
export function stopSpeaking() {
  try {
    Speech.stop();
  } catch {}
}
export const canListen = false;
export function listenOnce(_lang = "en-US"): Promise<string> {
  return Promise.reject(new Error("voice input is web-only for now"));
}
