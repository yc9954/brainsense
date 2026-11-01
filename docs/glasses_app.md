# Glasses / phone app spec (iOS first; Mock Device Kit for development)

## Flow
1. User says "Hey Meta, open BrainSense" (or taps the capture button). App starts a camera stream at MEDIUM 504×896 / 15 fps.
2. On the spoken question ("이거 어때?"), the app keeps the **last 6 s** of frames (ring buffer) + the question text from on-device ASR (`mwdat-speech`) and encodes an H.264 MP4 (`AVAssetWriter`).
3. POST to the Modal endpoint (`Tribe.http`): `{"video_b64", "filename", "item_id"}`. The service returns ROI features + 1 Hz ROI time series + timing.
4. The app calls the agent service (`brainsense.agent.loop.Agent.ask`) which runs Muse Spark with tools; the reply (2–3 sentences, Korean) goes to `AVSpeechSynthesizer`, routed to the glasses over A2DP.
5. If the user answers "좋아 / 별로", the app sends `record_feedback` → personal head refits.

## Latency budget (target ≤ 8 s from question to first spoken word)
| stage | budget | note |
|---|---|---|
| clip encode + upload (≈1.5 MB) | 1 s | HEVC stream → re-mux only, do not transcode |
| TRIBE events (ffmpeg + WhisperX + spaCy) | 1–2 s | silent clip → transcript empty; keep clip ≤ 6 s |
| TRIBE predict | **2.4–2.5 s measured** (L40S, 8 s clip, warm) | cold start 228 s incl. 70 s model load; events stage 0.2 s warm |
| heads + agent (1 tool round) | 1–2 s | `muse-spark-1.3`, max_tokens 300 |
| TTS first word | <0.5 s | on-device synthesis |
If predict > 4 s: keep container warm (`min_containers=1` during demo), lower fps to 8, cap clip at 4 s (one V-JEPA window).

## Fallback if DAT signup from Korea fails
Mock Device Kit (debug build → ladybug icon → Enable MockDeviceKit): feed the camera stream from the phone camera. Same code path; the demo video shows the phone-camera view with the "glasses" label, and the pitch states the SDK integration is identical.

## What the app does NOT do
- No continuous streaming to TRIBE (cost/latency). One clip per question.
- No raw brain vectors on device; only head outputs are shown in the companion UI (percentile bars + "why" text).
