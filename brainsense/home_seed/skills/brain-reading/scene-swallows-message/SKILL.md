---
name: scene-swallows-message
description: "Scene/place regions (PPA, RSC) dominate while attention is low: the background eats the message."
version: 0.1.0
author: BrainSense
license: MIT
metadata:
  brainsense:
    kind: image
    heads: [attention]
    tags: [visual, layout, attention]
---

# Scene swallows the message

## When to use
- 장소·배경 is the hottest group and 주목 is below the 50th percentile.

## Procedure
1. Crop or blur the environment; put the copy on a solid panel; one object silhouette larger than anything else.
2. If a person is in frame, aim their gaze at the headline or CTA (face regions then lead attention there).
3. Re-run `brain_eval`; expect 주목 up and 장소·배경 down in the ranking.

## Done when
- 주목 percentile rose by at least ten points; if not, the problem is contrast, not layout: try `reward-quiet-visual`.
