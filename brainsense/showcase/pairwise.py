"""Blind pairwise judge: Muse Spark sees two first screens side by side (both orders) and picks one.
Position bias is cancelled by averaging A-then-B with B-then-A. Returns P(first image better)."""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path

from openai import OpenAI

PROMPT = """You are a strict senior product designer and growth marketer. Two candidate first screens were made for the brief below. Which one would perform better with real visitors (visual quality, clarity in 3 seconds, one focal point, desirability of the offer, fit to the brief)?
Brief: {brief}
Reply ONLY with JSON: {{"winner": "A" or "B", "confidence": 0.5-1.0, "reason": "one sentence"}}"""


def _img(p: Path) -> dict:
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64.b64encode(p.read_bytes()).decode()}"}}


def _ask(client: OpenAI, a: Path, b: Path, brief: str) -> tuple[float, str]:
    r = client.chat.completions.create(
        model=os.environ.get("BRAINSENSE_LLM_MODEL", "muse-spark-1.3"),
        messages=[{"role": "user", "content": [{"type": "text", "text": PROMPT.format(brief=brief)},
                                               {"type": "text", "text": "Candidate A:"}, _img(a),
                                               {"type": "text", "text": "Candidate B:"}, _img(b)]}],
        temperature=0, max_tokens=4000)
    text = r.choices[0].message.content or ""
    m = re.search(r"\{.*\}", text, re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        d = {}
    conf = max(0.5, min(1.0, float(d.get("confidence", 0.5))))
    p_a = conf if str(d.get("winner", "A")).upper().startswith("A") else 1 - conf
    return p_a, str(d.get("reason", text[:200]))


def judge_pair(first: Path, second: Path, brief: str) -> dict:
    client = OpenAI(base_url=os.environ["BRAINSENSE_LLM_BASE_URL"], api_key=os.environ["BRAINSENSE_LLM_API_KEY"])
    p1, r1 = _ask(client, first, second, brief)
    p2, r2 = _ask(client, second, first, brief)      # swapped: P(second better) → convert
    p_first = (p1 + (1 - p2)) / 2
    return {"p_first": round(p_first, 3), "order_ab": round(p1, 3), "order_ba": round(1 - p2, 3), "reason": f"{r1} | swapped: {r2}"}
