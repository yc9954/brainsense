# Research notes (verified 2026-10-27)

## TRIBE v2
- Repo `github.com/facebookresearch/tribev2`, weights `facebook/tribev2` (HF, not gated, 709 MB ckpt). Paper arXiv:2605.04326. **License CC-BY-NC-4.0.**
- Install: `pip install "tribev2[plotting] @ git+https://github.com/facebookresearch/tribev2.git"`. Python ≥3.11, torch ≥2.5.1,<2.7, ffmpeg. Known install breakage on 3.12 (issues #65/#69) → the Modal image uses 3.11.
- API: `TribeModel.from_pretrained("facebook/tribev2")` → `get_events_dataframe(video_path=…)` → `predict(events)` → `(T, 20484)`.
- Output space: **fsaverage5 cortex**, lh 0–10241 / rh 10242–20483, **1 Hz**, average subject (n=25 across 4 studies), z-scored, **5 s hemodynamic shift already applied**. No subcortex in the release.
- Backbones: `facebook/vjepa2-vitg-fpc64-256` (4 s clips), `facebook/w2v-bert-2.0`, `meta-llama/Llama-3.2-3B` (**gated → HF_TOKEN required**). Transcription via WhisperX, sentence annotation via spaCy. ~15 GB weights total.
- Hardware: OOM on 15 GB T4 (issue #28); community Space runs on A10G 24 GB with bf16, ~140–175 s per 1-min clip incl. cold start. We default to L40S 48 GB.
- Parcellation: repo ships Glasser HCP-MMP1 helpers in `tribev2/utils.py` (`get_hcp_roi_indices`, `summarize_by_roi`, `get_topk_rois`) built on `mne.datasets.fetch_hcp_mmp_parcellation` (needs fsaverage + license accept). `brainsense/tribe/rois.py` uses them with an MNE fallback.
- Gotcha: text-only input uses gTTS (network call). Always pass video/audio.

## Meta Model API (hackathon)
- Base URL `https://api.meta.ai/v1`, `Authorization: Bearer $MODEL_API_KEY`, **OpenAI-SDK drop-in** (`/chat/completions`, `/responses`, `/images/*`) plus Anthropic-compatible `/messages`.
- Chat models: `muse-spark-1.3` ($1.25/$4.25 per 1M), `muse-wonder-1.0` ($4/$20, frontier). Multimodal in, 1M context, **tool calling + structured output supported; only `tool_choice: "auto"` accepted**; parallel tool calls on by default.
- `muse-image-1.0` ($0.01/img), `sam-3.1` (image/video segmentation via `/v1/responses`), `muse-voice-transcribe-1.0`. Muse Code = CLI coding agent, not an API model.
- Open weights: Muse Spark Open (816B MoE / 42B active), Muse Glimmer — count for "Best Open-Weight Build" ($10K).
- Rate limits per team: 3,000 RPM / 4M TPM. $150 credit claimed per participant via a form in the (gated) participant guide by Nov 4 9 PM ET; needs a card on file.
- Partner credits: **Modal $100** (first 1,000), Baseten $100, Fireworks $25 (shortlisted).
- Gate (participant guide, unverified mirror): must genuinely use Model API and/or Meta open weights; themes "Build for Your World" / "Push the Frontier". Rubric: Impact 30 · Meta tooling 25 · Demo 25 · Depth 20. Deliverables: public repo, ~3 min video, writeup, all contributors; only work built during the event.
- **TRIBE v2 is not on the Model API and not mentioned in hackathon materials** → it is an "open-weights add-on"; the Model API gate is satisfied by the Muse agent.
- Deadline Nov 4 9:00 PM ET = **Nov 5 11:00 KST**. Prizes: Indie $400K, Startup $550K, bonus $50K (Best Agentic $5K is a natural fit).

## Wearables Device Access Toolkit (DAT)
- v1.0.1 stable (Sept 30 2026). iOS `meta-wearables-dat-ios` (iOS 17.2+, Xcode 26.4+), Android `com.meta.wearable:mwdat-*` 1.0.1.
- Supported-country list (17) **does not include Korea**, but glasses launched in Korea May 25 2026 (SKT/KT/LG U+ July 22). Meta staff on GitHub issue #355: "no account-region restrictions on voice launches"; assistant language must be English. → **Try signup from Korea; needs a Managed Meta Account org via work.meta.com.**
- Video stream over BT: 720×1280 / 504×896 (default) / 360×640, 2–30 fps, raw or HEVC. Photo capture. Audio in: PCM via camera stream (dev/beta channels only) or HFP mic. Audio out: plain OS A2DP (AVAudioPlayer/AVSpeechSynthesizer) — no SDK API, no published latency; camera stream and TTS compete for BT bandwidth.
- Triggers: "Hey Meta, open <app>" + on-device ASR (firmware V128+). Button/touchpad via mwdat-inputs. No custom wake words.
- **Mock Device Kit**: debug-build toggle; virtual glasses; camera stream from phone camera or H.265 file; simulated taps. Enough for the whole demo without hardware.
- Samples: `facebook/meta-wearables-dat-ios/samples` (CameraAccess, BirdSpotter); community `Ex8-ca/hermes-glasses` (STT→LLM→TTS on glasses).

## Datasets (chosen, formats verified 2026-10-28 by downloading)
| Head | Dataset | Label | How we get it |
|---|---|---|---|
| Aesthetic | **AADB** (Kong et al. 2016) | mean rating in [0,1], 8,458 train / 1,000 test | labels: `AADBinfo.mat` from the authors' GitHub (180 KB; `trainNameList/trainScore`, `testNameList/testScore`); images: HF `Iceclear/AADB` → `AADB.zip` (2.56 GB, Apache-2.0, not gated). `prepare aadb` joins by filename. |
| Attention | **SnapUGC** train set | **ECR** (engagement continuation rate, 0–1, mean 0.50, uniform-ish) | the Drive "train set" link is a 31 MB CSV (`Id,Title,Description,Download_link,ECR`, 106,192 rows); videos are Snap CDN URLs, **~17% still live** (7/40 probed) → ~18K obtainable. `prepare snapugc` shuffles and downloads live ones. Val CSV (6,000 rows) has no labels. |
| Appeal | **Unsplash Lite** (HF `1aurent/unsplash-lite`, 3 parquet shards, 25K rows) | log(downloads/views) | columns are nested: `photo.id`, `photo.image_url`, `stats.views`, `stats.downloads`; images fetched from `images.unsplash.com` at w=640. |
| Aesthetic (upgrade) | TAD66K (HF `Shuai1995/TAD66K_…`) / AVA (HF `Iceclear/AVA`, 33 GB) | 1–10 votes | open |
| Appeal (upgrade) | CreativeRanking (Tianchi 93585, 1.7M ad creatives, impressions+clicks) | CTR | free Tianchi login |
| Hedge | Visuelle 2.0 (5,355 fashion images → 12-week sales) | sales | Google Form |
