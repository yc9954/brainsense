# BrainSense — a grounded-opinion agent for Meta glasses

**Pitch:** "이거 어때?" → the glasses look → **TRIBE v2** predicts how an average brain responds → small **calibrated heads** turn that into *pretty / attention-grabbing / appealing* with percentiles and confidence → a **Muse Spark** agent speaks an opinion it can justify with numbers, and learns *your* taste from 👍/👎.

Meta stack: Wearables Device Access Toolkit (glasses) · TRIBE v2 (open weights, brain encoder) · Meta Model API `muse-spark-1.3` (agent, tool calling) · optional SAM 3.1 (isolate the product in view).

```
glasses/phone ─clip(≤6s)─▶ Modal: TRIBE v2 ─▶ ROI time series (9 groups × 1 Hz)
                                              └▶ 54-d pooled features ─▶ heads: aesthetic · attention · appeal · personal
                                                                             └▶ Muse Spark agent (tools: brain_eval, compare, web_lookup, record_feedback) ─▶ TTS
```

## Status (2026-10-27)
| piece | state |
|---|---|
| ROI groups + pooled features (`brainsense/tribe/rois.py`) | done, tested offline |
| TRIBE v2 Modal service + latency benchmark (`brainsense/tribe/modal_app.py`) | **running on L40S**. Honest per-clip latency on a *new* clip: events (ffmpeg+WhisperX+spaCy) ~14 s + TRIBE predict ~28 s + raw embed ~0.5 s ≈ **43 s for a 6 s still**, ~105 s for a 12 s UGC video. The 3.4 s 'warm' number in `results/latency.json` was a neuralset feature-cache hit on the same file, not real inference. Optimization is now a day-1 task (see below). |
| Heads: calibrated head, personal head, ablation CLI (`brainsense/heads/`) | **trained on real features** (`heads/`), ablation done on 3 datasets (see below) |
| Agent: tools, system prompt, OpenAI-compatible loop, FastAPI server (`brainsense/agent/`) | **live on Muse Spark 1.3** (2026-11-01): glasses clip → Modal TRIBE → heads → tool-calling agent → Korean reply citing head scores; feedback updates the personal head |
| Dataset prep (`brainsense/data/prepare.py`) | **run**: AADB 500 imgs (+6 s stills), Unsplash 300 imgs (+stills), SnapUGC 150 live videos; manifests under `data/*/manifest.csv` |
| Feature extraction (`scripts/extract_features.py`) | **done**: 947/950 items → `features/{aadb,unsplash,snapugc}.npz` |
| **App UI (OpenMuse / CopilotKit React Native)** | **done, verified in the browser** (2026-11-02): `../openmuse/apps/mobile` — "Look" tab with photo/clip picker, bundled samples, BrainCard (3 head gauges, confidence, top regions in Korean, crowd-vs-you), 1 Hz ROI sparkline, chat with quick chips and 👍👎. Runs standalone against the FastAPI server; iOS/Android via Expo (needs Xcode / Android Studio to build natively). |
| Glasses capture (SwiftUI skeleton, `app/ios/`) | DAT SDK ring buffer + TTS; superseded as the UI by the OpenMuse app, kept for the glasses capture path |
| Demo video + write-up | script in `docs/demo_script.md` |

## Ablation results (real TRIBE features; AADB updated to 2,500 images on 2026-11-02)
**Shipped aesthetic head (2026-11-03):** 360 HCP-MMP1 area means → PCA-54 → logistic, trained on the full 2,500-image AADB area-feature store (`features/aadb_area.npz`, `heads_area2500/`): holdout AUROC **0.721**, ECE 0.041 (temperature 1.30), n_train 1,492. The 600-image version scored 0.718 on its smaller holdout; the extra data mostly buys calibration, not accuracy, which is consistent with the ablation below.

Linear heads, AUROC on a fixed 25% test split, mean over seeds. `raw_pca54` compresses the raw V-JEPA2 embedding to the same width as the brain features (the fair control).

| dataset (label) | n_train | TRIBE ROI (54-d) | raw V-JEPA2 (1408-d) | raw PCA-54 |
|---|---|---|---|---|
| AADB (human aesthetic rating, median split) | 100 | 0.61 | 0.65 | 0.62 |
| | 400 | 0.67 | 0.69 | 0.70 |
| | 1,875 | 0.69 | 0.69 | **0.73** |
| AADB, one split, more controls | 1,875 | 0.69 | — | PCA-54 0.73 · **hybrid (TRIBE + PCA-54) 0.75** · PCA-108 0.76 |
| Unsplash (log downloads/views), 1,500 items | 1,125 | 0.57 | 0.55 | 0.58 |
| Unsplash (log views, median split) → `popularity` head | 1,125 | **0.60** | 0.55 | 0.59 |
| SnapUGC (ECR watch retention), 587 videos | 440 | **0.62** | 0.66 | 0.60 |

Reading: aesthetics is learnable (0.69–0.76). With enough data the brain bottleneck **saturates below** a width-matched PCA of the raw embedding (0.69 vs 0.73), i.e. pooling predicted cortex into 9 regions discards information the embedding keeps; adding the brain features on top of PCA still helps a little (0.75 vs 0.73). So the honest claim is: **the brain prior buys interpretability, not accuracy**; the shipped `aesthetic` head is the TRIBE 54-d one because every chip it shows ("▲ 보상·가치 후반") is a real coefficient on a named region. A hybrid head is the obvious next step if accuracy matters more than explanation. **Richer brain features:** the service now also returns per-area means and slopes for all 360 HCP-MMP1 areas (720-d, `roi_area_feats`), to test whether the information loss is the 9-group pooling rather than the brain prior itself Result on 600 AADB images, 5-fold CV, linear heads:

| features | AUROC |
|---|---|
| TRIBE 9 groups × 6 stats (54-d, shipped so far) | 0.669 |
| TRIBE 360 area means (360-d) | 0.708 |
| TRIBE 360 areas mean+slope (720-d) | 0.711 |
| **TRIBE area means → PCA-54** | **0.753** |
| raw V-JEPA2 (1408-d) | 0.728 |
| raw → PCA-54 | 0.722 |
| raw → PCA-108 | 0.717 |

So the loss was the pooling: per-area brain features compressed to 54 dims **beat the raw embedding** at the same width and even the full embedding. The brain prior earns accuracy *and* interpretability once we stop averaging 180 areas into 9 buckets. Confirmation on all 2,500 images is paused at 600/2,500 (Modal usage limit reached); the heads are being switched to area-PCA features with contributions back-projected to named areas. With 4× more data, watch retention became learnable (0.62 brain / 0.66 raw) and here the 9-region brain features beat the width-matched PCA (0.62 vs 0.60), consistent with attention-related cortex carrying temporal information a static embedding pools away. Downloads-per-view stays weak (0.57–0.58). Heads are calibrated, so the agent's confidence tracks these numbers.

Trained heads (`heads/`, 2026-11-02): aesthetic AUROC 0.67 / ECE 0.03 (n=1,492); attention 0.65 / ECE 0.06 (n=365); appeal 0.58 / ECE 0.04 (n=910); popularity 0.59 / ECE 0.05 (n=910). (Unsplash Lite's `featured` flag was tried as an editorial-quality label and dropped: 98% positive.) Feature stores: 4,587 items across the three datasets.

The numbers in `results/ablation_synthetic/` are from synthetic data and only prove the CLI works.

## Run
```bash
uv sync                                   # local (Mac) deps; GPU deps live in the Modal image
uv run python -m pytest -q                # offline end-to-end smoke test (no GPU/network)

# 1. TRIBE latency (the day-1 number everything depends on)
uv run modal setup                        # browser login, once
uv run modal secret create huggingface HF_TOKEN=hf_...   # accept meta-llama/Llama-3.2-3B license first
uv run modal run brainsense/tribe/modal_app.py::main --video samples/test_clip.mp4 --repeats 3
#   → results/latency.json ; first call includes ~15 GB weight download into the Volume

# 2. Data → features → heads
# (already done for a first subset — rerun with bigger --n when the TRIBE pipeline is confirmed)
uv run python -m brainsense.data.prepare unsplash --n 1500      # appeal: log(downloads/views)
uv run python -m brainsense.data.prepare aadb --n 2000          # aesthetic: AADBinfo.mat + HF zip (2.5 GB, curl resume)
uv run python -m brainsense.data.prepare snapugc --n 1500       # attention: ECR; ~17% of CDN links live
uv run python -m brainsense.data.prepare stills                 # images → 6 s silent clips for TRIBE
uv run modal run scripts/extract_features.py::extract --manifest data/unsplash/manifest.csv --out features/unsplash.npz
uv run python -m brainsense.heads.ablation features/unsplash.npz --out results/ablation_unsplash
PYTHONPATH=. uv run python scripts/train_heads.py --appeal features/unsplash.npz --aesthetic features/aadb.npz

# 3. Agent server (the phone app talks only to this)
export BRAINSENSE_LLM_BASE_URL=https://api.meta.ai/v1 BRAINSENSE_LLM_API_KEY=$MODEL_API_KEY BRAINSENSE_LLM_MODEL=muse-spark-1.3
export BRAINSENSE_TRIBE_URL=https://alexyc0506--brainsense-tribe-tribe-http.us-east.modal.run   # deployed 2026-10-30
uv run uvicorn brainsense.agent.server:app --port 8000               # POST /analyze, /agent, /agent/feedback
```

## Things only you can do (in order)
0. **Create a Meta Model API key** at dev.meta.ai → API keys and put it in `.env` as `BRAINSENSE_LLM_API_KEY=...` (then remove `BRAINSENSE_LLM_MOCK=1`). Everything else below is done.
1. ~~`uv run modal setup`~~ (done 2026-10-28). **Add a payment method on modal.com → Settings → Billing**: every GPU type (L40S, A10G tried) refuses to start without one, even on free credits. Then claim the Modal $100 hackathon credit (first 1,000). The image itself builds fine (all layers verified).
   (2026-10-30: Modal card done, weights prefetched via `modal run brainsense/tribe/modal_app.py::prefetch`, Llama access requested on HF.) Create the `huggingface` secret with a *real* token (`modal secret create --force huggingface HF_TOKEN=hf_...`) after accepting the Llama-3.2-3B license; the placeholder value currently stored will fail the Llama download.
2. Claim the $150 Model API credit via the participant-guide form (needs a card on file) and set a spend limit.
3. Try creating a Wearables Developer Center org from Korea (work.meta.com → Managed Meta Account). If blocked, go Mock Device Kit (spec has the fallback).
4. Create a Tianchi account for CreativeRanking and submit the Visuelle 2.0 form (hedges for the appeal head).
5. Track decided: **Indie** (submitted on the Modal credit form). Repo: https://github.com/yc9954/brainsense (private; run `gh repo edit yc9954/brainsense --visibility public --accept-visibility-change-consequences` right before submitting, the rules require a public repo).
6. Record the 3-minute demo video (`docs/demo_script.md`; the web build at :8081 with the sample photos is enough, or the phone with Mock Device Kit), build the iOS app in Xcode (`app/ios/README.md`), submit on the Cerebral Valley portal by **Nov 4 9:00 PM ET / Nov 5 11:00 KST** with `docs/submission.md` as the write-up. Also make https://github.com/yc9954/openmuse-brainsense public, and rotate the Modal and Hugging Face tokens that were pasted into chat.
7. Optional: a real CopilotKit Intelligence key (`npx copilotkit@latest login`) gives durable threads; without it the local stub runs everything in memory, which is fine for the demo.

## Live transcript (real Muse Spark, real TRIBE features, 2026-11-01)
```
Q: 이거 어때?
A: 잘 모르겠어 지금은 판단하기 애매해. 신호가 너무 약하게 잡혀서 대중 예측도 중간 정도에서 흔들리고 있어. 좋아 별로 알려주면 네 취향 맞춰갈게.
Q: 왜 그렇게 생각해?
A: 결론은 그대로 잘 모르겠어. 대중 매력 점수가 0.53에 상위 65퍼센트로 딱 중간인데 신뢰도가 0.05밖에 안 되고 시각 주의랑 언어 신호가 엇갈려서야. ...
Q: 음 난 별로야
A: 오케이 별로로 저장했어 다음부터 네 취향 반영해서 더 잘 맞춰줄게
```
Grounding works as designed: the number it quotes (0.53 / 상위 65% / 신뢰도 0.05) is the `appeal` head output, and it declines to opine when confidence is low. Note: Muse counts reasoning tokens against `max_tokens`; the loop uses 1024 and never stores an empty assistant turn.

## App UI (OpenMuse)
The UI *is* [CopilotKit/OpenMuse](https://github.com/CopilotKit/openmuse) (React Native + Expo + Hono, MIT), cloned to `../openmuse` with its chat home, sidebar, thinking process, activity/ideas/goals/apps tabs untouched. BrainSense is not a tab: it is a server tool the agent reaches for mid-conversation plus a prompt that makes the agent speak as its own brain (see below).
```bash
# 1. agent server (this repo): heads, TRIBE proxy, /assets/fsaverage5_pial.bin for the 3D cortex
uv run uvicorn brainsense.agent.server:app --port 8000
# 2. OpenMuse server on the Meta Model API (no CopilotKit key needed: a local in-memory Intelligence stub + SSE runtime)
cd ../openmuse && OPENAI_API_KEY=$BRAINSENSE_LLM_API_KEY CPK_INTELLIGENCE_API_KEY=dummy-local RICH_THREADS=false BRAINSENSE_URL=http://127.0.0.1:8000 pnpm dev
# 3. web UI
pnpm --dir ../openmuse/apps/mobile web          # http://localhost:8081
```
Live-demo caveat: the deployed TRIBE endpoint shares the workspace's 10-GPU cap with batch extraction; pause batch jobs before a demo. Modal web endpoints 303-redirect after 150 s; the server follows them. A fresh container needs ~70 s to load the model; `BRAINSENSE_WARM=1 modal deploy` keeps one resident during a demo (~$2/h).

**Judged loop run `judged3` (2026-11-03, 2 rounds × 3 variants, parallel):** round 2 best ui_score 0.654 vs round 1 best 0.603 (brain heads + Muse judge, 50/50). The judge's recurring critique (illustration placeholders instead of a photo hero, three competing cards) is what the next round's brief carries; the brain heads stay unsure on UI screenshots (confidence 0.02–0.26), as before.

## Evaluation-driven UI loop (the harness)
The heads double as an **evaluation metric for generated UI**. `brainsense/loop/` runs: Muse Spark writes a single-file page → headless Chrome renders 1280×800 → the screenshot goes through TRIBE + heads → `ui_score = 0.6·aesthetic + 0.4·attention` (percentiles, shrunk toward 0.5 by each head's confidence) → the per-region critique ("시각 주의 낮음 → focal element/contrast") is fed back to the next round.
```bash
uv run python -m brainsense.loop.optimize --brief "팝업 랜딩 페이지 ..." --rounds 3 --variants 3   # results/loop/<run>/LEADERBOARD.md + BEST.html
uv run python -m brainsense.loop.ab page_a.html page_b.html https://example.com                 # A/B/N by brain heads
```
Guards learned the hard way: the Modal service now names uploads by content hash, because neuralset caches extracted features by *file path* and three different pages uploaded as `r1v1.png` had scored identically (the same bug made the first 'warm 3 s' benchmark a cache hit). Muse counts reasoning tokens against `max_tokens`, so long pages get cut off and render as blank heroes; the generator now uses a 16k budget, detects `finish_reason=length` / missing `</html>` / empty body text and regenerates (the first smoke run scored two blank pages, one of them 'top 3% aesthetic' — the photo-trained heads are out of distribution on blank cream rectangles). First clean run (`results/loop/smoke4`, 2 rounds × 2 variants, re-scored with `ab`): ui_score 0.39–0.50, aesthetic percentiles 54–80 %, confidences 0.06–0.32. The loop runs end to end (generate → render → score → critique), but on UI screenshots the photo-trained heads are mostly *unsure*, so right now the harness is a working pipeline with a weak metric, not a proven optimizer. The next step that makes the metric real is UI-specific labels: 👍👎 on screenshots through the personal head (already wired), or a UI-aesthetics dataset.

**Judge blend (2026-11-02):** `optimize` now scores each page with the brain heads *and* a Muse Spark multimodal judge (aesthetic / clarity / attention / brief-fit, 1–10 with a reason; ~7 s, `reasoning_effort=low`, 4k budget because Muse spends ~800 reasoning tokens on an image) and blends them 50/50 by default (`--judge-weight`). Variants of a round run in parallel (`--parallel`). The brain heads stay in the loop for the region-level critique; the judge supplies the UI-specific quality signal the photo-trained heads lack.

Each score costs one TRIBE call (~14 s warm). The metric is honest about its limits: aesthetic AUROC 0.67, attention 0.65 on real labels, so treat `ui_score` as a tie-breaker with explanations, not ground truth. Human 👍👎 on screenshots flows into the personal head through the same server, which is how the metric gets better for *your* taste.

UI repo: https://github.com/yc9954/openmuse-brainsense (private, branch `brainsense-ui`; upstream CopilotKit/openmuse kept as `upstream`).

## OpenMuse integration (2026-11-03): the agent's own brain
BrainSense is wired into OpenMuse's own agent loop, not a side tab:
- **Server tool `brain_eval`** (`apps/server/src/engine/conversation.ts`): takes `artifact_id` of a photo/clip attached in chat (OpenMuse's file store now accepts images and video, sniffed by magic bytes) or `brain_item_id` from agent context; calls this server's `/analyze` + `/eval`; returns heads, percentiles, confidence, top cortical areas, the 1 Hz region series, the per-vertex cortex time series and a Korean summary. Muse Spark calls it on its own when the user asks "이거 어때?" / attaches an image.
- **Prompt augmentation** (`brainInstructions`): the agent then speaks *as its own brain*, first person, naming areas in plain words, quoting percentiles, witty and specific; never rating without the tool. Real turn (sample photo): "내 좌측 안와전두피질이 상위 12%로 켜졌어, 조화로움과 아름다움에 보상 점수를 매기는 곳이라는 뜻이지. 근데 초기 시각피질이랑 움직임 영역은 딱 중간이라 눈을 확 잡아채진 않아. 갤러리에 걸면 예쁘다는 말은 듣는데, 멈춰서 갖고 싶게 만들진 못하는 컷이야."
- **Live cortex card** (`brain-live.web.tsx`, three.js): the look of Meta's TRIBE v2 site (aidemos.atmeta.com/tribev2), rebuilt from its viewer's recipe: room-environment image-based lighting + ACES tone mapping, a white rough cortex, a 7 %-opacity head that reads as a dark bust on black. Geometry is ours: the fsaverage5 pial surface (20,484 vertices, `assets/fsaverage5_pial.bin`) inside the MNE fsaverage head surface (`assets/fsaverage_head.bin`), both in the same MRI frame so they line up; the bust turns a full 360° while hot spots (TRIBE's own per-vertex predictions, `vertex_ts`, uint8 per item, ~120 KB per 6 s clip) fade in and out second by second, coloured relative to the item (top ~28 % warm, red-dominant, yellow/white peaks). STIMULUS thumbnail, MODEL PREDICTION label, 1 Hz timeline. Native falls back to server-rendered nilearn frames.
- **Local runtime without CopilotKit Intelligence** (`apps/server/src/local-intelligence.ts`, `agent.ts`): a placeholder `CPK_INTELLIGENCE_API_KEY` switches the runtime to SSE mode with the in-memory runner. Lesson: passing any `intelligence` object makes CopilotRuntime v2 auto-wire the Intelligence runner, which waits on a hosted websocket forever (chat never answers, nothing logged). A real key restores durable threads.

**Demo without glasses:** the Wearables Device Access Toolkit's Mock Device Kit simulates the glasses on the phone (iOS and Android): the CameraAccess sample app's debug sheet enables the mock device and the camera source picker streams the phone's front/back camera or a video file through the same SDK calls as real hardware. The OpenMuse chat path (attach a photo → `brain_eval`) is the second, hardware-free demo.

## Latency (measured on L40S, never-seen 6 s clip, `results/profile.json`)
| variant | events | TRIBE predict | total |
|---|---|---|---|
| full pipeline (WhisperX + spaCy + Llama, fp32) | 14 s | 33 s | ~43 s |
| no transcription (`transcribe=False`), fp32 | 0.9 s | 34.7 s | 38 s |
| no transcription + **bf16 autocast** | 0.3 s | **12.9 s** | **14 s** |
| same, 4 s clip | 0.4 s | 10.3 s | 12 s |
| any clip already seen (neuralset feature cache hit) | 0.3 s | 2.4 s | 4 s |

Findings: the ~30 s is backbone feature extraction (V-JEPA2 ViT-g + DINOv2 + w2v-BERT at 2 Hz, fp32); the fusion model itself is 2.4 s. bf16 autocast gives 2.7× with ROI features unchanged to the 2nd decimal (tribev2's `.numpy()` needs the fusion output cast back to fp32, handled in `modal_app.py`). Skipping transcription is exact for clips without speech (same features) and removes WhisperX/Llama entirely. The live path (`Tribe.http`) therefore defaults to `transcribe=False, bf16=True`; batch extraction for datasets with speech keeps transcription on. Remaining floor (~10 s for 4 s) is per-call extractor setup; next candidates are keeping the backbones resident across calls and reducing the 2 Hz sampling for the live path.

## Honesty notes for the write-up
- TRIBE's output is a deterministic function of its backbone embeddings; the only claims we make are sample-efficiency (ablation) and interpretability (ROI explanations). The ablation is reported whichever way it comes out.
- TRIBE was trained on passive viewing; value-region predictions are weak by construction. The heads are what make the opinions, the brain is the prior.
- Image heads feed stills, so the temporal module contributes nothing there.

See `docs/research.md` for all verified facts and sources, `docs/glasses_app.md` for the app spec and latency budget.
