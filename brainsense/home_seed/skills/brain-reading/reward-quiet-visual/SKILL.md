---
name: reward-quiet-visual
description: "A photo, poster or page whose reward/value regions (OFC, vmPFC) stay quiet: make the benefit concrete."
version: 0.1.0
author: BrainSense
license: MIT
metadata:
  brainsense:
    kind: image
    heads: [appeal, aesthetic]
    tags: [visual, reward, cta]
---

# Reward-quiet visual

## When to use
- 끌림 below the 40th percentile, or the value group (보상·가치) ranks in the bottom three groups for the item.

## Procedure
1. Say what the brain saw: early visual high with reward quiet means "pretty, not wanted".
2. Directives, in this order: one concrete outcome in the headline (what changes for the viewer), a price or a scarcity cue, social proof (a face reacting, a count), and a single CTA with nothing competing beside it.
3. If the user is iterating, run `brain_eval` on the next version and compare 끌림 percentiles; cite the item_id of the better one.

## Done when
- 끌림 rose or the reward group climbed in the ranking; otherwise say the change did not reach the brain and try the next directive.
