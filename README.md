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
| Glasses app | SwiftUI skeleton in `app/ios/` (DAT SDK, 6 s ring buffer, HTTP client, TTS); not compiled here (no Xcode); SDK signup from Korea unverified |
| Demo video + write-up | script in `docs/demo_script.md` |

## Ablation results (real TRIBE features, 2026-10-30)
Linear heads, AUROC on a fixed 25% test split, mean over 10 seeds. `raw_pca54` is the raw V-JEPA2 embedding compressed to the same width as the brain features (the fair control).

| dataset (label) | n_train | TRIBE ROI (54-d) | raw V-JEPA2 (1408-d) | raw PCA-54 |
|---|---|---|---|---|
| AADB (human aesthetic rating, median split) | 25 | 0.59 | 0.60 | 0.59 |
| | 100 | 0.62 | 0.62 | 0.59 |
| | 200 | 0.68 | 0.67 | 0.68 |
| | 375 | **0.72** | 0.69 | **0.71** |
| Unsplash (log downloads/views) | 225 | 0.51 | 0.50 | 0.51 |
| SnapUGC (ECR watch retention) | 110 | 0.49 | 0.56 | 0.45 |

Reading: aesthetics is learnable from both (0.72 AUROC with 375 images); the brain bottleneck beats the *full* raw embedding at n≥200 only because 54 dims overfit less than 1408, and the same-width PCA control matches it. **No accuracy advantage from the brain prior; the claim that survives is interpretability** (ROI-level explanations the agent can voice). Popularity and watch-retention labels are not learnable from either feature set at this data size, so the `appeal` and `attention` heads are calibrated to low confidence (temperature 20 and 10) and the agent will say "잘 모르겠다" on them.

Trained heads (`heads/`): aesthetic AUROC 0.70 / ECE 0.12; attention 0.54; appeal 0.53.

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
5. Decide the track. CC-BY-NC on TRIBE v2 argues for **Indie**; the "Best Agentic" bonus fits either.

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
