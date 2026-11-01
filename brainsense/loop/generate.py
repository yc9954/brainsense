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


def _body_text(html: str) -> str:
    body = html[html.lower().find("<body"):] if "<body" in html.lower() else html
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()


class GenerationError(RuntimeError):
    pass


def generate_page(brief: str, history: list[dict], variant: int, temperature: float = 0.9,
                  max_tokens: int = 16000, retries: int = 2) -> str:
    """history: [{"round": r, "variant": v, "ui_score": s, "explanation": str, "html_excerpt": str}, ...]
    Retries when the model truncates (Muse counts reasoning tokens against max_tokens) or returns a
    page with no real body content; a blank page must never reach the scorer."""
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
    compact = ""
    last_err = "unknown"
    for attempt in range(retries + 1):
        user = (f"Brief: {brief}\n\nThis is variant #{variant}: explore a distinctly different layout and "
                f"palette from other variants.{critique}{compact}")
        r = _client().chat.completions.create(
            model=os.environ.get("BRAINSENSE_LLM_MODEL", "muse-spark-1.3"),
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            temperature=temperature, max_tokens=max_tokens)
        choice = r.choices[0]
        html = _extract_html(choice.message.content or "")
        text = _body_text(html)
        if choice.finish_reason == "length" or "</html>" not in html.lower():
            last_err = f"truncated (finish_reason={choice.finish_reason}, {len(html)} chars)"
            compact = ("\n\nIMPORTANT: your previous answer was cut off. Keep the whole document under "
                       "250 lines: compact CSS, no decorative animations, no long comments.")
            continue
        if len(text) < 120:
            last_err = f"empty body ({len(text)} chars of text)"
            compact = "\n\nIMPORTANT: the previous answer had no visible content. Put real headline, copy and a CTA in <body>."
            continue
        return html
    raise GenerationError(f"variant {variant}: {last_err} after {retries + 1} attempts")
