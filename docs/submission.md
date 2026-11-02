# BrainSense — submission write-up (draft, 2026-11-03)

**Track:** Indie · **Theme:** Push the Frontier · **Team:** Yuchan Lee (solo)

## Problem
AI taste advice is ungrounded: ask any assistant "is this nice?" and it improvises. People who make visual decisions for a living (popup-store operators, creative marketers, shoppers) want an opinion that can say *why*, admit when it doesn't know, and learn what *you* like.

## What we built
A grounded-opinion agent for Meta AI glasses. You look at something and ask "이거 어때?". The 6-second clip goes to a Modal GPU service running **TRIBE v2**, Meta's open-weights brain foundation model, which predicts how an average human cortex responds (20,484 vertices, 1 Hz). We pool that into 9 functional regions (visual attention, reward/value, faces, scenes, language, ...), feed small **calibrated heads** trained on real outcome data (AADB human aesthetic ratings; Snap watch-retention; Unsplash downloads-per-view), and hand only the head outputs, percentiles, confidences and top contributing regions to a **Muse Spark 1.3** agent with tool calling. The agent speaks a 2–3 sentence opinion in Korean through the glasses, cites the numbers when asked "why", and refits a **personal head** from your 👍/👎 so it can say "the crowd would like it, you wouldn't".

**Where it lives:** inside [OpenMuse](https://github.com/CopilotKit/openmuse) (CopilotKit's open personal-agent app) running on Muse Spark. The brain is a tool the agent reaches for on its own mid-conversation when you attach a photo or ask "이거 어때?"; it answers *as its own brain* ("내 안와전두피질이 상위 12%로 켜졌어…") and shows a live 3D cortex, Meta's fsaverage5 surface with TRIBE's per-vertex predictions lighting up second by second, in the chat.

## Meta tooling
- **Meta Model API — Muse Spark 1.3** with tool calling (`brain_eval`, `compare`, `web_lookup`, `record_feedback`). Opinions are constrained to tool outputs by the system prompt; low confidence → "잘 모르겠어".
- **TRIBE v2** (open weights, CC-BY-NC) as the perception prior, with its V-JEPA2 / DINOv2 / w2v-BERT / Llama-3.2-3B backbones.
- **Wearables Device Access Toolkit** for capture on Ray-Ban Meta; the Mock Device Kit streams the phone camera or a video file through the same SDK for judging without hardware.
- **OpenMuse (CopilotKit)** as the agent shell: tool calling, agent context and inline tool cards; our `brain_eval` tool and brain persona are additions, the rest is upstream.
- Modal for the GPU service (L40S) and batch feature extraction.

## What's measured (not claimed)
- **Latency:** 43 s → **14 s** per fresh 6 s clip on L40S by skipping transcription on speech-free clips and bf16 autocast; fusion model alone is 2.4 s; backbone extraction is the remaining cost.
- **Ablation (brain features vs. raw V-JEPA2 embedding), linear heads, 10 seeds:** AADB aesthetics AUROC 0.72 (TRIBE 54-d) vs 0.69 (raw 1408-d) vs **0.71 (raw PCA-54)**. The brain prior does **not** buy accuracy once dimensionality is matched; what it buys is **interpretability**: the agent explains with "시각 주의가 2초 뒤 떨어져" rather than "embedding dim 731". Popularity and watch-retention labels are not learnable from either feature set at 150–300 items, and the heads are calibrated to say so.
- **Live transcript** with real Muse Spark and real TRIBE features is in the README.

## Built during the hackathon
Everything in this repo: Modal service, ROI pooling, heads + calibration + ablation harness, agent + server, data pipelines for three datasets (947 items extracted), iOS skeleton, docs.

## Limits
TRIBE v2 is an *encoder* trained on passive viewing (no decisions), predicts an average subject, and is CC-BY-NC. Image inputs are stills, so its temporal module adds nothing there. Our outcome datasets are small; the aesthetic head is the only one with signal today.

## Next
Sweetspot popup-store outcomes as real-world appeal labels; SAM 3.1 to isolate the product in view; keep the backbones resident to get under 8 s; on-lens percentile bars on Ray-Ban Display.
