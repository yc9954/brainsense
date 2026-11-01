"""Tool definitions for the grounded-opinion agent (OpenAI function-calling format).

Design rule: the LLM never sees raw brain vectors. It sees head outputs (score, percentile,
confidence, top contributing ROIs) and whatever the other tools return. Opinions must be
traceable to one of these outputs."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "brain_eval",
            "description": (
                "Run the item the user is looking at through the brain-response model and the "
                "calibrated heads. Returns, per head (aesthetic / attention / appeal), a score, "
                "a percentile vs. comparable items, a confidence (0-1), and the top contributing "
                "brain regions. Also returns the user's personal-taste head if enough feedback exists."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string", "description": "id of the captured clip/image"},
                    "heads": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["aesthetic", "attention", "appeal", "personal"]},
                        "description": "which heads to run; default all",
                    },
                },
                "required": ["item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare",
            "description": (
                "Compare the current item against items the user looked at earlier in this session "
                "on the same heads. Use when the user asks 'is this better than the last one?'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "against": {"type": "array", "items": {"type": "string"},
                                "description": "earlier item ids; default = all items this session"},
                },
                "required": ["item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_lookup",
            "description": (
                "Look up external facts about the product in view (price, reviews, brand). Only "
                "for factual questions; never for opinions."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_feedback",
            "description": "Store the user's own verdict on the item ('좋아'/'별로') to train their personal head.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "liked": {"type": "boolean"},
                },
                "required": ["item_id", "liked"],
            },
        },
    },
]

ToolFn = Callable[..., dict[str, Any]]


class ToolRegistry:
    """Maps tool names to Python callables. The agent loop dispatches through here."""

    def __init__(self) -> None:
        self._fns: dict[str, ToolFn] = {}

    def register(self, name: str) -> Callable[[ToolFn], ToolFn]:
        def deco(fn: ToolFn) -> ToolFn:
            self._fns[name] = fn
            return fn
        return deco

    def call(self, name: str, **kwargs: Any) -> dict[str, Any]:
        if name not in self._fns:
            return {"error": f"unknown tool {name}"}
        try:
            return self._fns[name](**kwargs)
        except Exception as e:  # tool errors go back to the model, not up the stack
            return {"error": f"{type(e).__name__}: {e}"}
