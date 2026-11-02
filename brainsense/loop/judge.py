"""Muse Spark (multimodal) as a UI judge. The photo-trained brain heads are out of distribution on
screenshots, so the loop blends them with a direct multimodal rating. Returns 0-1 scores with a
one-line rationale per criterion; deterministic-ish (temperature 0)."""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(".env")

CRITERIA = ("aesthetic", "clarity", "attention", "brief_fit")
PROMPT = """You are a strict senior product designer judging a 1280x800 first screen.
Score each criterion from 1 to 10 and give a 1-sentence reason:
- aesthetic: visual quality (type, color, spacing, polish)
- clarity: can a visitor tell in 3 seconds what this is and what to do
- attention: is there one focal element that pulls the eye; no clutter
- brief_fit: how well it serves this brief: {brief}
Reply ONLY with JSON: {{"aesthetic": n, "clarity": n, "attention": n, "brief_fit": n, "reason": "..."}}"""


_REASONING_OK: dict[str, bool] = {}


def _reasoning_extra() -> dict:
    """Ask for low reasoning effort when the endpoint accepts it (keeps the judge fast); cached per process."""
    return {"reasoning_effort": "low"} if _REASONING_OK.get("low", True) else {}


def judge_image(png: Path, brief: str) -> dict:
    client = OpenAI(base_url=os.environ["BRAINSENSE_LLM_BASE_URL"], api_key=os.environ["BRAINSENSE_LLM_API_KEY"])
    data = base64.b64encode(Path(png).read_bytes()).decode()
    def _call():
        return client.chat.completions.create(
        model=os.environ.get("BRAINSENSE_LLM_MODEL", "muse-spark-1.3"),
        messages=[{"role": "user", "content": [
            {"type": "text", "text": PROMPT.format(brief=brief)},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}},
        ]}],
        temperature=0, max_tokens=4000,   # Muse spends ~800+ reasoning tokens on an image before answering
        extra_body=_reasoning_extra())

    try:
        r = _call()
    except Exception as e:  # e.g. 400 for an unsupported reasoning_effort → retry without it
        if _REASONING_OK.get("low", True) and "reasoning" in str(e).lower():
            _REASONING_OK["low"] = False
            r = _call()
        else:
            raise
    text = r.choices[0].message.content or ""
    m = re.search(r"\{.*\}", text, re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        d = {}
    scores = {k: max(0.0, min(1.0, (float(d.get(k, 5)) - 1) / 9)) for k in CRITERIA}
    scores["judge_score"] = sum(scores.values()) / len(CRITERIA)
    scores["reason"] = str(d.get("reason", text[:200]))
    return scores
