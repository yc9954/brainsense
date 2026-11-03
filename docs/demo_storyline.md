# Demo storyline (3:00) — why, then contrasts in time-lapse, then why it matters

Format: a 20-second "why", then five fast contrasts (each a split screen, plain AI on the left, brain in the loop on the right, time-lapsed), then 25 seconds on why this is new, then the numbers. Nothing is walked through step by step; every segment is a before/after.

## 0:00–0:20 Why we built it
Screen: three AI chats answering "what do you think of this photo?" with "Looks great!" / "Nice composition!" / "I love it!". Freeze. Caption: *AI taste is improvised. It has no eyes and no reasons.*
VO: "Every assistant will tell you your photo looks great. None of them looked, and none can say why. So we gave ours a brain: Meta's TRIBE v2, a model of the human cortex, in front of the language model."

## 0:20–1:40 Five contrasts, 15 seconds each (split screen, time-lapsed)

| # | left: plain AI | right: with the brain | what the viewer sees |
|---|---|---|---|
| 1 Opinion | Muse Spark alone: "Nice photo!" | Same photo: the cortex in the bust lights up second by second, bars fill (Desirability top 1%), then "My reward circuit lit up… attention stayed flat". Ask "Why?" → percentiles and regions in plain words. | the answer has evidence, and the evidence came first |
| 2 Design | One-shot Muse landing page, fixed. | Brain-in-the-loop rounds: leaderboard climbing, page morphing; Blender room 0.26 → 0.47 over six rounds (timelapse GIF); a live site before/after redesign. | the same signal that judges can steer |
| 3 Taste | One model, same answer for everyone. | Lab: six likes/dislikes time-lapsed → Consolidate → rules in English ("when the right posterior insula is more active, you tend to like it") → crowd-vs-you learning curve → the next photo gets a one-line reflex instantly. | it learns you, and you can read what it learned |
| 4 Everything, one brain | Photo only. | Fast cuts: photo, video clip, a paragraph of copy (Human-likeness head, rewrite suggestion), an audio clip (Hook head). Same cortex, different heads. | one brain, four kinds of input |
| 5 Where it lives | A chat box. | iPhone glasses mode: camera POV in a store, "What do you think?" by voice, caption answer spoken back; the Ray-Ban Meta pill and the orb. | it is meant for glasses, and already behaves like them |

VO lines, one per contrast: "It looks first, then speaks." · "What judges can also build." · "It learns your taste as rules you can read." · "Photos, clips, copy, sound: one brain." · "On your face, not in a text box."

## 1:40–2:05 Why this is new (three cards, 8 s each)
1. **Grounded, not improvised.** The opinion is a measurement: a predicted human cortex, heads calibrated on real ratings, confidence included. Low confidence is said out loud.
2. **One signal to judge and to make.** The brain score that rates a photo is the same reward that steers a design loop, a Blender scene, a shop.
3. **Taste as readable memory.** Likes become falsifiable rules with effect sizes; the agent's whole memory is files you can open.

## 2:05–2:35 Honest numbers (About tab, bar charts)
AADB aesthetics AUROC: 360 areas → PCA 0.75, raw embedding 0.73, 9 regions pooled 0.67. Heads: 0.72 / 0.65 / 0.58 / 0.59. Latency per 6-second clip: 43 s → 14 s. One line: brain features buy explanation, not accuracy; TRIBE predicts an average viewer.

## 2:35–3:00 Close
Glasses POV once more, one spoken answer. End card: "An opinion it can justify." Stack: Meta Model API (Muse Spark 1.3), TRIBE v2 (open weights), OpenMuse, Modal, Wearables DAT flow. Built during the hackathon.

## Production notes
- Split screens: record the left side once (plain Muse via the chat with brain tools disabled, or a stock chat UI), the right side from the real app. Time-lapse everything 3–6× except the two seconds when the cortex lights up.
- Pre-record assets: Blender timelapse GIF (results/showcase/interior/room3), A/B leaderboard, redesign before/after, Lab rules screen after a fresh reset + 6 ratings.
- Before recording: `/memory/reset`, ☰ New conversation, warm the GPU with one Lab run, proxies and servers up, iPhone on the HTTPS address with the certificate accepted.
- Say "a model of the human brain", never "mind reading"; head bust credit: Meta TRIBE v2 demo (non-commercial).
