---
name: compare-two-hooks
description: "Which of two tracks or clips grabs more: brain_eval both, brain_compare, name the second they diverge."
version: 0.1.0
author: BrainSense
license: MIT
metadata:
  brainsense:
    kind: audio
    heads: [attention, appeal]
    tags: [audio, music, compare]
---

# Compare two hooks

## Procedure
1. `brain_eval(kind=audio, heads=[attention, appeal])` on each file; keep both item_ids.
2. `brain_compare(item_id=A, against=[B])`.
3. Report: which one is higher per head, and at what second the 시각 주의/보상 series separate. Say if the difference is inside the confidence margin.

## Done when
- A verdict with one number per head and one timestamp, and an honest "too close" when it is.
