# showcase — does a brain in the loop make Muse's work better?

Same brief, same model (Muse Spark), same generation budget. Only the feedback differs.

| arm | feedback between rounds | picks the winner by |
|---|---|---|
| `oneshot` | none (ask once) | — |
| `muse_loop` | Muse's own multimodal review of its screenshot | Muse self-judge |
| `brain_loop` | **TRIBE v2 predicted cortex → `skills.read_brain` expert critique** | brain heads + judge blend |

Final comparison is a **blind pairwise judge** (Muse multimodal, both image orders, averaged), so the
arm that wrote the page never grades itself. Every finalist also gets a brain score and a diagnosis.

```bash
uv run python -m brainsense.showcase.ab --rounds 3 --variants 2            # 5 page briefs → results/showcase/<run>/index.html
uv run python -m brainsense.showcase.video ab --rounds 2 --variants 2      # 3 ad-clip briefs (12 s CSS animations → mp4 → TRIBE time course)
uv run python -m brainsense.showcase.video score clip.mp4                  # per-second cortex readout + hook analysis for any clip
```

## skills.py — reading the cortex like a designer

`read_brain(eval_json, kind)` ranks the nine region groups *within the item* (a still only moves the
cortex a few tenths of a z-score), looks at the first-2 s hook vs. the rest, and turns the pattern into
a diagnosis + prioritized directives, e.g.

* V1–V4 hottest but aesthetic head low → *clutter*: one background tone, two accents, whitespace
* FFA/STS silent on a people brief → add a face whose gaze points at the CTA
* PPA/RSC dominant → the scene swallows the message: crop/blur, copy on a solid panel
* OFC/vmPFC quiet or appeal < 50 → make the benefit concrete: outcome, price, scarcity, social proof
* language areas busy + attention low → cut copy to ≤ 7 words
* attention peak after 4 s in a clip → the hook is too slow

The area codes the heads cite (HCP-MMP1, e.g. `L_pOFC`, `R_IP1`) are translated by `area_label`.

## honest notes

* The heads were calibrated on photos; screenshots are out of distribution, which is why selection
  blends the brain score with a judge and why the final verdict is the blind pairwise judge.
* Muse's one-shot pages are already strong; wins come from rounds 2–3, where the brain directives
  change *what* gets fixed (object silhouette, face/gaze, reward cues), not from the first draft.
* Clips shorter than ~10 s give a flat cortex time course (hemodynamic lag), hence 12 s ads.
