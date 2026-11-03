# Demo storyline (3:00) — NeuroMuse / BrainSense

**Logline.** An AI that looks before it speaks: every photo, clip or line of copy goes through a predicted human cortex (Meta TRIBE v2), small calibrated heads turn that into four scores, and a Muse Spark agent gives an opinion it can justify, in the first person, as its own brain. Say like or dislike and it learns your taste, in rules you can read.

## The three wow moments (in this order)

1. **The brain lights up before the answer.** A photo goes in, the 3D cortex inside the glass bust warms up red and yellow second by second, the bar chart fills, and then the agent speaks: "My early visual cortex lit up in the top 12%…". Visual proof, then words.
2. **It learns you, and tells you the rule.** Six likes and dislikes, one "Consolidate", and the Lab shows a rule in plain English ("When the right posterior insula is more active, you tend to like it") plus a learning curve of your head against the crowd. The next photo gets a one-line reflex verdict instantly.
3. **The same brain can steer a design.** Showcase: a Blender interior climbs from 0.26 to 0.47 in six brain-guided rounds (timelapse GIF), and a shop curated by the brain. Judging and making use the same signal.

## Timeline

| time | on screen | voice-over (English) |
|---|---|---|
| 0:00–0:15 | iPhone POV in a store (glasses mode, Ray-Ban Meta pill). Tap "What do you think?". Caption answer appears and is spoken. Cut to title card. | "What if your assistant had a brain, and looked before it answered?" |
| 0:15–0:40 | About tab, pipeline figure (video/audio/text → V-JEPA2, wav2vec, Llama → TRIBE v2 transformer → predicted cortex → calibrated heads → Muse Spark). | "NeuroMuse runs what you see through Meta's TRIBE v2, a model of the human brain. Small heads trained on real ratings turn the cortex into aesthetic appeal, attention capture, desirability and reach. The agent speaks only from those numbers." |
| 0:40–1:20 | Chat. "+" → Sample B. Close-up: the bust rotating, hot spots moving. Bars fill (Desirability top 1%). Agent reply in first person. Type "Why?" → it quotes percentiles and regions in everyday words. | "Watch the cortex first. Reward and value light up, attention stays flat. Then it tells me, as its own brain, and when I ask why it cites the numbers, not vibes." |
| 1:20–1:50 | Lab tab, memory reset beforehand. Time-lapse: like/dislike on six photos → Consolidate (sleep) → rules appear → learning curve (crowd vs you). Then a new photo: reflex banner + instant one-line verdict. | "Rate a few. It sleeps, consolidates, and writes rules about you in plain English. The next time it sees something similar, it answers from memory in one breath." |
| 1:50–2:20 | Split: (a) "Is this copy good?" on a paragraph → Human-likeness head and a rewrite suggestion. (b) Showcase: Blender interior before/after and the timelapse GIF; one brain-curated shop row. | "It reads text and audio through the same brain. And the signal that judges can also steer: six rounds of brain-guided changes take this room from 0.26 to 0.47." |
| 2:20–2:45 | About tab charts: AADB AUROC 0.75 vs raw 0.73 vs pooled 0.67; heads 0.72 / 0.65 / 0.58 / 0.59; latency 43 s → 14 s. One line of limits. | "Honest numbers. The brain features do not beat a raw embedding on accuracy; they buy explanation. Every head reports confidence, and the agent says when it is unsure." |
| 2:45–3:00 | Back to the glasses POV, one more answer. End card: "An opinion it can justify." + stack: Meta Model API (Muse Spark), TRIBE v2, OpenMuse, Modal, Wearables DAT flow. | "An opinion it can justify. Built on Meta's models, end to end, during the hackathon." |

## Recording checklist (do these in order)

1. Start `node openmuse/scripts/lan-https.mjs` (phone) and keep `:8787`, `:8000`, Metro `:8081` running.
2. `POST /memory/reset` on `:8000` so the Lab starts with zero outcomes (the current 12 are synthetic test data). In the app: ☰ → New conversation.
3. Warm the GPU two minutes before: run Sample A once in the Lab (first call is ~70 s cold, later calls ~14 s).
4. Pick three photos with contrasting results beforehand (Sample B: desirability top 1%; Sample A: aesthetic top 7%; one bland photo) so the demo shows a spread.
5. iPhone: same Wi-Fi, open `https://<laptop-ip>:8443`, accept the certificate once, "+" → Glasses mode, allow camera. Record the iPhone screen with the built-in recorder; record the Mac with QuickTime.
6. Speed up waiting (TRIBE 14 s, consolidation) to 2–4× in the edit; never cut the moment the cortex lights up.
7. English voice everywhere; keep the agent's spoken lines, they are the proof.

## Backup plan

- No Wi-Fi or camera trouble on the phone: the web build on the Mac has a demo feed and the same glasses overlay.
- GPU cold or Modal down: the Lab shows the last cached result instantly; narrate over it.
- Agent slow: the Lab tab never calls the LLM, only TRIBE + heads, so the brain, bars and memory loop still work.

## Say this, not that

- Say "an AI model of the human brain" and "predicted cortex"; never "it reads your mind".
- Say "calibrated on real ratings" and show the confidence bar; never claim accuracy we did not measure.
- The head bust comes from Meta's TRIBE v2 demo (non-commercial use); the brain mesh is fsaverage5.
