---
name: humanize-copy
description: "Rewrite copy so it reads like a person wrote it, using the 사람다움 head and the text critique."
version: 0.1.0
author: BrainSense
license: MIT
metadata:
  brainsense:
    kind: text
    heads: [humanlike, attention]
    tags: [copy, writing, humanlike]
---

# Humanize copy

## When to use
- "사람처럼 써줘", "자연스럽게", "광고 카피 다듬어줘", or a paragraph scores below the 30th percentile on 사람다움.

## Procedure
1. Run `brain_eval(kind=text, heads=[humanlike, attention])` on the current draft. Keep the item_id.
2. Read `critique.diagnosis`. Map each line to one edit:
   - reward/value quiet → give the reader a stake or a feeling in the first two sentences (what they lose, want, or did not expect).
   - people area quiet → one named or unnamed person doing something.
   - scene area quiet → one place, one sense (smell, sound, touch).
   - story network quiet → turn the explanation into a small episode with time order (그때 → 그래서 → 결국).
   - only language areas high → delete connectives (Additionally, Furthermore, 또한, 뿐만 아니라), lists and "something for everyone"; vary sentence length.
   - control/attention high → split long sentences, one metaphor per technical term.
3. Rewrite. Run `brain_eval` again. Present before → after with both 사람다움 percentiles and say what the head measures (reads like a person wrote it, not quality).

## Done when
- 사람다움 rose and the text still says what the user needed it to say. If it fell, keep the draft that scored higher and say so.
