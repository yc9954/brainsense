"""Muse Spark as the page generator. Produces complete single-file HTML; takes the brain-score
feedback of previous rounds as design critique."""
from __future__ import annotations

import os
import re

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(".env")

SYSTEM = """You are a senior product designer who writes production-quality single-file HTML pages
(inline CSS, no external assets except Google Fonts). Output ONLY the HTML document, nothing else.
Design for a 1280x800 first screen: strong visual hierarchy, one clear focal element, real copy
(no lorem ipsum), accessible contrast, 16px+ body text. Avoid stock-photo placeholders; use CSS
gradients, shapes, emoji or SVG for imagery."""


def _client() -> OpenAI:
    return OpenAI(base_url=os.environ["BRAINSENSE_LLM_BASE_URL"], api_key=os.environ["BRAINSENSE_LLM_API_KEY"])


def _extract_html(text: str) -> str:
    m = re.search(r"```(?:html)?\s*(<!doctype.*?|<html.*?)```", text, re.S | re.I)
    if m:
        return m.group(1).strip()
    i = text.lower().find("<!doctype")
    if i < 0:
        i = text.lower().find("<html")
    return text[i:].strip() if i >= 0 else text.strip()


def generate_page(brief: str, history: list[dict], variant: int, temperature: float = 0.9) -> str:
    """history: [{"round": r, "variant": v, "ui_score": s, "explanation": str, "html_excerpt": str}, ...]"""
    critique = ""
    if history:
        best = max(history, key=lambda h: h["ui_score"])
        worst = min(history, key=lambda h: h["ui_score"])
        critique = (
            "\n\nEvaluation so far (a brain-response model scores screenshots; percentiles are vs. real "
            "photos people rated):\n"
            f"- BEST so far (ui_score {best['ui_score']:.3f}): {best['explanation']}\n"
            f"  excerpt: {best['html_excerpt'][:600]}\n"
            f"- WORST (ui_score {worst['ui_score']:.3f}): {worst['explanation']}\n"
            "Keep what the best one does right, change what the brain signals flag (e.g. if '시각 주의' "
            "is low, strengthen the focal element and contrast; if '얼굴·사람' is low and the brief is "
            "about people, add a human element; if '보상·가치' is low, make the offer/benefit visible)."
        )
    user = (f"Brief: {brief}\n\nThis is variant #{variant}: explore a distinctly different layout and palette "
            f"from other variants.{critique}")
    r = _client().chat.completions.create(
        model=os.environ.get("BRAINSENSE_LLM_MODEL", "muse-spark-1.3"),
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        temperature=temperature, max_tokens=6000)
    return _extract_html(r.choices[0].message.content or "")
