# NeuroMuse — submission text

Copy each block into the matching field. Every number below comes from a saved run in the repository.

---

## Project name
NeuroMuse

## Track
Indie

## Tagline (short, ≤ 60 characters)
The Muse with a cortex: opinions it can justify.

## Tagline (≤ 140 characters)
NeuroMuse puts Meta's TRIBE v2, a model of the human cortex, in front of Muse Spark, so every opinion comes with the brain regions behind it.

## Links
- Code: https://github.com/yc9954/brainsense
- Demo video (2:53): https://github.com/yc9954/brainsense/blob/main/docs/video/neuromuse-demo.mp4

---

## Elevator pitch (≈ 80 words)
Ask any assistant what it thinks of your photo and it says "looks great". It never looked, and it cannot say why. NeuroMuse looks first. Meta's TRIBE v2 predicts how a human cortex responds, 20,484 points every second; calibrated heads turn that response into scores with a confidence; Muse Spark speaks only from those scores, in the first person. It works through glasses, learns your personal taste as readable rules, and can direct real creative work, from a website to a 3D room to a 12-second ad.

---

## Inspiration
People who make visual decisions for a living, pop-up store operators, marketers, creators, ask AI for taste every day and get improvised answers. A language model has no eyes of its own; its taste is words about a picture, not a response to it. Meta released TRIBE v2, a foundation model that predicts human brain activity from video, audio and text. We wanted to know what an assistant becomes when its opinions have to come from a predicted human brain instead of from prose.

## What it does
NeuroMuse is an agent with a cortex and a hippocampus.

- **It looks before it speaks.** A photo, a 6-second glasses clip, a paragraph or a sound goes through TRIBE v2 first. Five calibrated heads score the predicted cortex: Aesthetic appeal, Attention capture, Desirability, Reach, and Human-likeness for text. Each score carries a percentile and a confidence.
- **It answers as its own brain, in plain words.** "My place-mapping side lights up first: I'm mapping the room, not the bottles. My desirability sits at the very bottom, and I'm 93% sure of that." Below a confidence of 0.3 it says the signal is faint and asks you instead of guessing. Raw brain vectors never reach the language model.
- **It works like glasses.** A landscape first-person view keeps a rolling 6-second clip; you ask by voice and the answer is spoken back.
- **It tunes to your brain.** Every like or dislike is stored with its cortex state. A sleep pass replays the answers the model got most wrong, refits a personal head, and writes your taste as falsifiable rules with effect sizes ("when your posterior insula is more active, you tend to like it", d = 1.26). The Lab shows every memory write live.
- **It directs real work.** In a design loop the cortex critiques each version, an art director picks a craft tool (keep and restyle a real asset, fetch a real photo, model the product or room in Blender, reset the type, re-time an ad), and the agent rebuilds. It has evolved real websites, furnished a 3D room and made a 12-second ad.
- **It refuses to cheat.** Nothing counts as a win unless the facts are the page's or brief's own, the page keeps its density, and a blind judge that wrote neither side prefers the result. Refusals are logged with the reason.

## How we built it
- **Perception (L0).** TRIBE v2 runs on a Modal L40S behind a FastAPI service. It returns the per-vertex cortex time course (20,484 fsaverage5 vertices at 1 Hz) and 360 HCP-MMP1 area features. Image, video, audio and text pathways are all wired in. Latency for a never-seen 6-second clip went from 43 s to 14 s (no transcription for silent clips, bf16).
- **Organs (L1).** 360 area means are reduced to 54 dimensions and fed to logistic heads calibrated on real outcomes: AADB aesthetic ratings, SnapUGC watch retention, Unsplash downloads per view, and HC3 human-versus-model text. Every score is a weighted sum of named cortical areas, so "why" is a back-projection, not a story.
- **Memory (L2, L3).** An engram store keeps one row per percept (cortex vector, 1 Hz series, stimulus, outcomes, surprise) in SQLite; recall is cosine similarity in cortex space. Sleep is the only writer: prioritized replay, a personal-head refit, area-contrast rule mining with bootstrap confidence intervals, and a rule ledger that is retired, never edited. The agent's workspace follows Hermes Agent's conventions (SOUL.md, budgeted MEMORY.md and USER.md, on-demand skills).
- **Voice and router (L5).** Muse Spark 1.3 on the Meta Model API, with tool calling (brain_eval, look_at, brain_recall, brain_rules, skills), runs inside an agent app built on CopilotKit's open-source OpenMuse. It decides which sense and which heads to use and holds no memory itself.
- **Cortex in the loop (L4).** Generators for pages, 12-second ad clips, Blender scenes (Poly Haven assets, Cycles) and writing, each scored by the brain, gated for invented facts and density, and judged blind in both orders. Every run writes a decision trail that the brain narrates in its own words.
- **Client.** A React Native and Expo app (web, iOS, Android): chat with a live 3D cortex card, a landscape glasses mode, a Lab for testing your own brain, and an About tab with the measured numbers.

## Meta tools used
- **Meta Model API, Muse Spark 1.3**: the agent's voice and router, tool calling, multimodal judging.
- **TRIBE v2** (open weights): the perception layer, with its V-JEPA2, DINOv2, wav2vec-BERT and Llama 3.2 backbones.
- **Wearables Device Access Toolkit flow**: the glasses capture path, emulated on a phone over HTTPS for judging without hardware.

## Results (measured, including the losses)
- **Why a cortex:** on 2,500 AADB photos (5-fold), 360 cortical areas reduced to 54 dimensions score 0.753 AUROC, against 0.728 for the raw vision embedding and 0.669 for 9 pooled regions. A second, out-of-fold protocol puts the raw embedding slightly ahead; either way the cortex features are in the same accuracy class, and every score names the areas behind it.
- **Heads, holdout AUROC:** Human-likeness 0.88 (n = 230, HC3); Aesthetic appeal 0.72 (ECE 0.041); Attention 0.65; Desirability 0.58; Reach 0.59.
- **Brain loop versus one shot, blind pairwise judge:** 12-second ad clips 3 of 3 (P ≥ 0.85); pages 3 of 5 plus a tie.
- **Human blind vote:** 11 of 16 pairs for the brain loop (6 of 8 against Muse's own self-critique loop, 5 of 8 against one shot; one voter).
- **Real websites:** of six live sites, the loop accepted one change (Algonauts Project, blind P = 0.90) and refused five where the original was better. Zero invented facts shipped.
- **3D room:** brain score 0.32 → 0.49 and designer judge 0.13 → 0.40 over eight Blender rounds.
- **Limits we report:** Reach is barely predictable from any features, cortex or raw (≈ 0.56 AUROC). The personal head has only 12 synthetic answers so far and is not yet better than the crowd head (0.56 vs 0.67). On the serum ad, the one-shot version still won.

## Challenges we ran into
- **A good-looking score is easy to fake.** Our first redesigns raised the brain score while inventing client logos, version badges and counts. We built three gates (a fact check against the page's own text, a density check, and blind pairwise acceptance) and reran everything; most "wins" disappeared, and the one that survived is real.
- **The judge rewards invented specifics.** Muse's one-shot ad scored higher partly because it made up a price, a pH and a guarantee. We now fact-check the baseline too and report it.
- **Text heads can be gamed.** Selecting rewrites by Human-likeness alone produced hesitant, forced-casual prose; the head is now a critic and never the only judge.
- **Infrastructure.** Our Modal workspace was disabled overnight by a spend limit; the cached analyses kept the demo working, and every run resumed once it was re-enabled.

## Accomplishments we're proud of
- An assistant whose opinions are measurements, with a confidence it actually respects.
- Memory in brain states rather than words: a thousand memories cost zero prompt tokens, and taste is written as rules a person can read and dispute.
- A creative loop where the brain is the critic, a blind judge is the verdict, and refusals are shown as plainly as wins.
- Every number in the README and the demo traces to a saved run in the repository.

## What we learned
The brain buys explanation more than accuracy. At matched width, cortex features land beside the raw embedding, but they turn "embedding dimension 731" into "your reward circuit stayed quiet", which is what a person can act on. Honest gates matter more than clever generators: a loop that cannot invent facts or game its own score is the only kind worth trusting.

## What's next
- Real outcome labels from pop-up store sales to train the Desirability and Reach heads on the decisions that matter.
- More personal answers per user, to show the personal head overtaking the crowd head.
- Keeping the backbones resident to bring a clip under 8 seconds, and running on Ray-Ban Display with on-lens percentile bars.

## Built with
Meta Model API (Muse Spark 1.3) · TRIBE v2 · V-JEPA2 · DINOv2 · Llama 3.2 · wav2vec-BERT · Wearables Device Access Toolkit · Modal · FastAPI · Python · scikit-learn · SQLite · React Native · Expo · TypeScript · Hono · CopilotKit (OpenMuse) · three.js · Blender (Cycles) · Poly Haven · Playwright · ffmpeg

## Credits
TRIBE v2 (Meta, open weights). Head bust from the Meta TRIBE v2 demo (non-commercial use). Brain mesh fsaverage5 (FreeSurfer). The app runtime builds on CopilotKit's MIT-licensed OpenMuse. Sample photos are Creative Commons; Blender assets are Poly Haven CC0. Demo narration voiced with ElevenLabs v4 and the first-person store clip generated with Seedance 2.0, both through Higgsfield.
