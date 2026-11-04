/** Native voice I/O: text-to-speech via expo-speech; speech recognition is web-only for now. */
import * as Speech from "expo-speech";

export const voiceSupport = () => ({ stt: false, tts: true });
export function startListening(
  _lang: string,
  _onText: (text: string) => void,
  _onFinal: (text: string) => void,
  _onEnd: (error?: string) => void,
): boolean {
  return false;
}
export function stopListening(): void {}
export function speak(text: string, lang?: string): void {
  if (!text.trim()) return;
  Speech.speak(text.replace(/[*_`#>]/g, ""), {
    language: lang ?? (/[가-힣]/.test(text) ? "ko-KR" : "en-US"),
    rate: 1.05,
  });
}
export function stopSpeaking(): void {
  Speech.stop();
}
