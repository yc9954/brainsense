"""Build the HC3 text manifest for the "humanlike" head (human vs ChatGPT answers).

    uv run python scripts/prepare_hc3.py --n-per-class 600 --words 70

Controls the obvious confound: ChatGPT answers are ~2x longer than human ones (median 177 vs 94
words), so every text is cut to the same first-N-words window and anything shorter than 40 words is
dropped. Balanced by source (reddit_eli5 / finance / medicine / open_qa / wiki_csai) and by class;
train/test split is by question so the same prompt never appears on both sides.
Output: data/hc3/manifest.csv with item_id, text, label (1 = human), split, source, question_index.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import pandas as pd
import typer

app = typer.Typer(add_completion=False)


def _clip(text: str, words: int) -> str:
    toks = [t for t in text.replace("\n", " ").split(" ") if t.strip()]
    return " ".join(toks[:words])


@app.command()
def main(src: Path = Path("data/hc3/all.jsonl"), out: Path = Path("data/hc3/manifest.csv"),
         n_per_class: int = 600, words: int = 70, min_words: int = 40, seed: int = 0):
    rows = [json.loads(l) for l in src.open()]
    rng = random.Random(seed)
    rng.shuffle(rows)
    by_source: dict[str, list] = {}
    for r in rows:
        by_source.setdefault(r["source"], []).append(r)
    per_source = max(1, n_per_class // len(by_source))
    picked = []
    for source, items in by_source.items():
        n = 0
        for r in items:
            if not r["human_answers"] or not r["chatgpt_answers"]:
                continue
            h, c = r["human_answers"][0], r["chatgpt_answers"][0]
            if len(h.split()) < min_words or len(c.split()) < min_words:
                continue
            q = r.get("index") or hashlib.sha1(r["question"].encode()).hexdigest()[:8]
            split = "test" if (hashlib.sha1(f"{source}:{q}".encode()).digest()[0] % 5 == 0) else "train"
            for label, text in ((1, h), (0, c)):
                picked.append({"item_id": f"hc3_{source}_{q}_{'h' if label else 'c'}",
                               "text": _clip(text, words), "label": label, "split": split,
                               "source": source, "question_index": q})
            n += 1
            if n >= per_source:
                break
    df = pd.DataFrame(picked)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"wrote {out}: {len(df)} texts, {df.label.mean():.2f} human, "
          f"{(df.split == 'test').mean():.2f} test, sources={df.source.value_counts().to_dict()}")


if __name__ == "__main__":
    app()
