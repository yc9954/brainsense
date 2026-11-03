# BrainSense "Engram" architecture — an agent with a cortex and a hippocampus

*Draft 2026-11-04. Design target for the last day of the hackathon and the roadmap after it.*

## 0. The one-line difference

Every agent framework people are copying right now remembers in **words**.
OpenClaw keeps memory as Markdown files in a workspace and consolidates logs into long-term storage
during idle "memory dreaming"; Hermes keeps `MEMORY.md` / `USER.md` and writes its own skills as
Markdown when it solves something; Instinct keeps git-tracked Markdown found with grep and turns each
failure into a written self-reflection (Reflexion). All three learn by *writing better notes to
themselves*. The model never changes, the world is stored as text, and "taste" is whatever the LLM
can verbalize.

BrainSense remembers in **brain states**. Every photo, clip, track or paragraph the agent has ever
looked at is stored as the human cortex TRIBE v2 predicts for it (360 cortical areas at 1 Hz), together
with what happened afterwards (the user said 좋아/별로, picked A over B, the popup sold, the copy got
replies). The agent learns by fitting small organs — *heads* — on those states, not by retraining the
LLM and not by accumulating prose. The LLM (Muse Spark) is the **voice and the router**, never the
memory. Three things fall out of that which a text-memory agent cannot do:

1. **Perceptual recall.** "What have I seen before that *felt* like this to a brain?" is a nearest-
   neighbour query in cortex space, which groups a poster and a storefront that share a reward +
   scene pattern even though no caption would link them.
2. **Learning without drift.** Feedback changes a logistic head in milliseconds; nothing is appended
   to a prompt, so a thousand feedbacks cost the same context as none, and the agent cannot talk
   itself into a false rule.
3. **Explanations by construction.** Every score is a weighted sum of named cortical areas, so "why"
   is a back-projection, not a confabulation.

## 1. Layers (each is a real component, most already exist)

```
                 ┌──────────────────────────────────────────────────────────────┐
  stimulus ───▶  │ L0  SENSES   TRIBE v2 on Modal  (image · video · audio · text)│  exists
                 │     → 20,484-vertex cortex @1 Hz → 360 HCP-MMP1 area features │
                 └───────────────┬──────────────────────────────────────────────┘
                                 ▼
                 ┌──────────────────────────────────────────────────────────────┐
                 │ L1  ORGANS   calibrated heads on area features              │  exists
                 │     crowd: 예쁨 주목 끌림 인기 사람다움   personal: your taste   │
                 └───────────────┬──────────────────────────────────────────────┘
                                 ▼
                 ┌──────────────────────────────────────────────────────────────┐
                 │ L2  ENGRAM STORE  (the memory DB)                             │  NEW
                 │     one row per percept: cortex vector, time course, stimulus,│
                 │     context, outcomes, surprise, verbal note                  │
                 │     ops: recall(k) · contrast(A,B) · drift(user vs crowd)      │
                 └──────┬───────────────────────────────────────┬───────────────┘
                        ▼                                       ▼
   ┌────────────────────────────────┐            ┌──────────────────────────────┐
   │ L3  SLEEP (consolidation)      │            │ L4  CORTEX-IN-THE-LOOP        │ exists
   │  refit heads · mine taste rules│   NEW      │  anything the agent makes is  │ (loop/,
   │  into USER_TASTE.md · decay    │            │  read by L0–L1 before it is   │ showcase/,
   │  · surprise-weighted retention │            │  shown; critique → revision   │ rewrite loop)
   └────────────────────────────────┘            └──────────────────────────────┘
                        ▲                                       ▲
                        └──────────────────┬────────────────────┘
                                           ▼
                 ┌──────────────────────────────────────────────────────────────┐
                 │ L5  VOICE + ROUTER   Muse Spark (OpenMuse agent loop)         │  exists
                 │   decides which sense and which heads; speaks as the brain    │
                 │   tools: brain_eval · brain_compare · brain_recall · brain_rules │ (+2 new)
                 │   REFLEX: confident personal head + matching rule → answer     │  NEW
                 │           without a reasoning pass                            │
                 └──────────────────────────────────────────────────────────────┘
```

Why this is a *well-formed* architecture and not a pile of features: each layer has exactly one
input type and one output type, and only L2 holds state. L0 is pure and content-hashed. L1 is pure
given its weights. L5 holds no memory at all; it reads L2 through tools. L3 is the only writer of
L1 weights and of the verbal rules. That is the same discipline Hermes applies to Markdown (one
writer, inspectable files), applied to brain states.

## 2. The engram store (L2)

File-based and inspectable, like the Markdown-memory frameworks, but the primary key is a brain
state, not a sentence.

```
state/engrams.sqlite
  engrams(id TEXT PK, kind TEXT, created_at, owner TEXT, thread_id TEXT,
          stimulus_ref TEXT,        -- artifact id / url / first 600 chars of text
          cortex BLOB,              -- float32[360] area means (the L1 input)
          pca BLOB,                 -- float32[54] shared PCA (the similarity key)
          roi_ts JSON,              -- 9 groups × T seconds (what the agent cites)
          surprise REAL,            -- |head prediction − outcome| at consolidation, 0 if no outcome
          note TEXT)                -- one sentence the agent said about it
  outcomes(engram_id, kind TEXT,    -- liked | chosen_over | rejected | dwell_s | sold | replies
           value REAL, against TEXT, created_at)
  rules(id, owner, text TEXT,       -- "You rate warm-toned product shots ~20 pts above the crowd"
        evidence JSON,              -- engram ids + area contrasts that produced it
        confidence REAL, created_at, retired_at)
  consolidations(id, owner, started_at, n_engrams, n_outcomes, head_auroc_before, head_auroc_after)
state/rules/<owner>/USER_TASTE.md   -- the verbal mirror of `rules` (Hermes-style, human-editable)
```

Operations exposed to L5 as tools:

- `brain_recall(item_id, k=5, kinds=[...])` — k nearest engrams by cosine in PCA-54 space, with
  their outcomes and notes. Lets the voice say *"this looks, to my cortex, like the three storefronts
  you rejected in October: same scene-dominant pattern, reward quiet."*
- `brain_rules()` — the current verbal rules with confidence and the engrams behind them.
- `record_feedback(item_id, liked|chosen_over|...)` — writes an outcome; the personal head refits
  immediately (exists); surprise is computed at the next sleep.

## 3. Sleep (L3): consolidation that does something a prompt cannot

OpenClaw's memory dreaming summarizes logs. Ours *fits*:

1. **Replay with priority.** Outcomes since the last sleep are scored by surprise (how wrong the
   current heads were). High-surprise engrams get weight > 1 in the personal refit; low-surprise
   ones decay. This is the hippocampal-replay idea (prioritized by prediction error) made literal.
2. **Refit organs.** Personal head per owner (already warm-started on the crowd head); optionally a
   per-owner PCA rotation when > 200 engrams exist.
3. **Mine verbal rules.** Contrast liked vs disliked engrams in area space (mean difference,
   bootstrap CI), keep the 3–5 largest stable contrasts, translate areas with `area_label`, and ask
   Muse to phrase each as one falsifiable sentence with its evidence. Write `USER_TASTE.md`. Rules
   whose contrast flips sign are retired, not edited — the file is a ledger.
4. **Report.** AUROC of the personal head before vs after on the held-out newest outcomes, stored
   in `consolidations`. The learning curve (AUROC vs number of feedbacks) is the product metric.

Trigger: every N=10 new outcomes, or nightly, or `POST /sleep`. Cost: CPU only; the brain states are
already cached, so a sleep over 10k engrams is seconds.

## 4. Reflex path (L5 shortcut)

A spinal reflex does not consult the cortex. When a new percept's nearest engram is within a tight
radius, the personal head is confident (|p − 0.5| > 0.35), and a rule with confidence > 0.7 applies,
the server returns a ready-made one-sentence answer (`reflex: true`) and the voice reads it without a
reasoning pass. Voice mode already does the cheap half of this (answer from the cached summary with
`reasoning_effort: low`); the reflex adds the *rule* and the *precedent*, so the sentence is
"same as the mint storefront you liked on Tuesday, your rule about warm tones holds" rather than a
generic score.

## 5. What exists today vs what this adds

| piece | status |
|---|---|
| L0 senses: image/video/audio/text through TRIBE, cached by content hash | done |
| L1 crowd heads (aesthetic 0.72, attention 0.65, appeal 0.58, popularity 0.59, humanlike 0.88 AUROC) | done |
| L1 personal head, ms refit on 👍/👎, crowd prior | done (per-process JSON store) |
| L4 cortex-in-the-loop: UI loop, showcase A/B (brain loop beats one-shot), text rewrite loop | done |
| L5 routing (kind + heads), first-person voice, compare tool, voice reflex-lite | done |
| L2 engram store (SQLite + PCA index), `brain_recall`, `brain_rules` | **to build** |
| L3 sleep: surprise-weighted refit, rule mining, USER_TASTE.md, learning-curve report | **to build** |
| L5 reflex with precedent + rule | **to build** |
| world outcomes importer (Sweetspot popup sales as labels) | after the hackathon |

## 6. Build plan for the remaining day (owner: this session, all CPU-only)

| step | hours | deliverable |
|---|---|---|
| A. Engram store + migration of every cached item/outcome into it; `/recall`, `/rules` endpoints; `brain_recall`/`brain_rules` tools + prompt rule ("cite a precedent when one is within radius") | 3 | the agent says "like the X you rejected" with real ids |
| B. `/sleep`: surprise-weighted refit, area-contrast rule mining, Muse phrasing, `USER_TASTE.md`, consolidation report | 2 | a learning curve chart (AUROC vs feedbacks) for the README and the 실험 tab |
| C. Reflex path in `/eval` + voice-mode use | 1 | sub-5 s spoken answers that quote a precedent |
| D. Demo script: 8 feedbacks live → sleep → rules appear → next photo answered by reflex | 1 | video segment |

## 7. How to evaluate it honestly

- Personal head AUROC as a function of feedback count, per owner (the curve must rise; if it does not,
  the memory is decoration).
- Rule precision: fraction of mined rules a human confirms as true of their taste (we can only measure
  this on ourselves before the deadline; say so).
- Reflex hit rate and its error rate vs the full path.
- Recall usefulness: does citing a precedent change user agreement? (A/B in the showcase harness.)

## 8. Comparison, stated plainly

| | OpenClaw | Hermes | Instinct | BrainSense Engram |
|---|---|---|---|---|
| memory unit | Markdown note | Markdown note + skill file | git-tracked Markdown | predicted cortex state + outcome |
| learns by | consolidating logs ("dreaming") | writing/refining skills | written self-reflection | fitting heads; rules are a *derived* mirror |
| similarity | vector/text search | FTS5 full-text | grep | cosine in cortex space |
| explanation | whatever the LLM says | whatever the LLM says | whatever the LLM says | named cortical areas, back-projected |
| cost of 1,000 memories | context tokens | context tokens | context tokens | 0 tokens; one ms refit |
| failure mode | prompt drift, stale notes | skill rot | reflection loops | heads need labels; TRIBE is passive-viewing, average-subject |

Sources on the three frameworks: [OpenClaw architecture](https://cenrax.substack.com/p/understanding-openclaw-architecture),
[OpenClaw 2026 update](https://www.clawbot.blog/blog/openclaw-the-ai-agent-framework-explained-2026-update/),
[Hermes 5-pillar architecture](https://www.mindstudio.ai/blog/hermes-agent-5-pillar-architecture-memory-skills-soul-crons),
[What is Hermes Agent](https://www.truefoundry.com/blog/what-is-hermes-agent),
[Instinct memory teardown](https://supermemory.ai/blog/reverse-engineering-instinct-memory/),
[Instinct 2026 guide](https://a2aprotocol.ai/insights/2026-what-is-instinct-ai).
