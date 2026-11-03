# Demo video script (≤ 3 min) + write-up outline

## 0:00–0:20 Hook
Phone-camera POV (or glasses POV) walking a popup store. Voice: "이거 어때?" → BrainSense answers in 2 sentences, with a reason.
Caption: *An opinion the agent can justify — because it ran your view through a predicted brain.*

## 0:20–0:50 How it works (one diagram, 30 s)
glasses → TRIBE v2 (Meta's brain foundation model, predicted fMRI for an average viewer) → ROI time series → calibrated heads (pretty / attention / appeal) → Muse Spark agent with tools → speech.
Say explicitly: TRIBE is an *encoder*; heads are trained on real outcome data (AADB ratings, Snap watch-retention, Unsplash downloads/views). The LLM never sees raw brain vectors.

## 0:50–1:30 Live demo, 3 items (OpenMuse chat on the web build, or the phone with Mock Device Kit)
Attach a photo with "+" (or pick a sample) and type "이거 어때?". The agent calls `brain_eval` by itself, the live 3D cortex card appears (hot spots moving at 1 Hz), then the brain speaks in first person.
1. Item A: "별로야" + why ("주의 신호가 2초 뒤에 떨어져, 하위 30%").  Show the ROI strip + percentile bars on the phone UI.
2. Item B: "꽤 좋아 보여" + compare with A ("A보다 보상 반응이 높아").
3. "왜?" → the agent cites the numbers. "좋아" → record_feedback → personal head updates.

## 1:30–2:10 Crowd vs you — the memory loop (Engram)
1. Reset memory (`POST /memory/reset`) so the taste starts at zero. 실험 tab: rate 8–10 photos with 좋아/별로 (10 outcomes trigger a sleep automatically, or press "자면서 정리하기" → `POST /sleep`).
2. Show `USER.md`'s taste section appearing: 2–4 falsifiable rules with effect sizes ("보상·가치 영역이 더 켜질 때 네가 좋아할 확률이 높다, d=1.2"), and the learning-curve point (personal LOO AUROC vs crowd).
3. Attach a photo close to one you rated: the card shows the **reflex** banner and the brain says it in one breath — "3일 전 네가 좋아라고 했던 것과 내 피질엔 거의 같은 패턴이야(유사도 0.97). 네 취향 모델은 92%로 좋아할 쪽" — no reasoning pass, sub-5 s in voice mode.
4. Ask "나에 대해 뭘 배웠어?" → `brain_rules` quotes the rules with confidence; "이거 전에 본 것 중에 뭐랑 비슷해?" → `brain_recall` cites the precedent by date and outcome.
5. Open `state/brain_home/` on screen: SOUL.md, MEMORY.md, USER.md, skills/ — the whole agent is readable files plus one SQLite of brain states (the Hermes convention, applied to a cortex).
After ~8 feedbacks: "대중은 좋아할 것 같은데 네 취향은 아닐 듯. 채도 높은 거 별로라고 했잖아."
Caption: personal head warm-started from the crowd head; refits in milliseconds on cached features.

## 2:10–2:45 Evidence (the honest slide)
Ablation table from `results/ablation_*/summary.csv`: AUROC vs training size, raw V-JEPA2 embedding head vs brain-bottleneck head. State the result whichever way it goes:
- brain wins at small n → "the fMRI-trained prior buys sample efficiency";
- no win → "the brain gives interpretability, not accuracy; here is what it costs".
One line: latency from `results/latency.json` (TRIBE predict s / end-to-end s).

## 2:45–3:00 What's next
Sweetspot popup data as outcome labels (real-world appeal); SAM 3.1 to isolate the product; Ray-Ban Display for on-lens percentile bars.

---
## Write-up outline (submission form)
- Problem: taste advice from AI is ungrounded; people want "why".
- Who: shoppers, marketers testing creatives, popup-store operators.
- Meta tooling: Wearables DAT (glasses capture), TRIBE v2 (open weights), Meta Model API `muse-spark-1.3` with tool calling, optional SAM 3.1 / Muse Image for "what if" variants.
- Technical depth: neuroforecasting precedent (Knutson/Genevsky); DPI caveat and the ablation design; calibration (temperature scaling, ECE).
- Built during the event: everything in this repo (commit history as evidence).
- Limits: TRIBE is passive-viewing, average-subject, CC-BY-NC; value regions weak by construction.
- Next: personal heads at scale, popup outcome labels, on-device ROI summaries.
