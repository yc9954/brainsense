---
name: hook-too-slow
description: "A clip or track whose attention/auditory peak comes after the first 4 s: move the hook earlier."
version: 0.1.0
author: BrainSense
license: MIT
metadata:
  brainsense:
    kind: video
    heads: [attention, appeal]
    tags: [video, audio, hook, timing]
---

# Hook too slow

## When to use
- In `roi_ts`, the 시각 주의 (or auditory) peak is at second 4 or later, or the first two seconds are flat.

## Procedure
1. Quote the second of the peak and what region peaked.
2. Directive: start on the peak frame or sound (cut the setup), put the product/face in the first second, keep the CTA where attention is still high.
3. For two candidates, run `brain_compare` and point at the second where the series diverge.

## Done when
- The peak moves into the first 3 s and 주목 does not drop later.
