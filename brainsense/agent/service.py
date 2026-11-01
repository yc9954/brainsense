"""Wires heads + feature cache + agent into the tools the LLM can call."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..heads.head import Head
from ..heads.personal import PersonalHead
from .tools import ToolRegistry

CROWD_HEADS = ("aesthetic", "attention", "appeal")


class FeatureCache:
    """item_id -> feature vector. In production this is filled by the TRIBE service."""

    def __init__(self) -> None:
        self._d: dict[str, np.ndarray] = {}

    def put(self, item_id: str, x: np.ndarray) -> None:
        self._d[item_id] = np.asarray(x, dtype=np.float32)

    def get(self, item_id: str) -> np.ndarray:
        if item_id not in self._d:
            raise KeyError(f"no features cached for {item_id}; run the TRIBE service first")
        return self._d[item_id]

    def ids(self) -> list[str]:
        return list(self._d)


def build_registry(heads_dir: Path, cache: FeatureCache, personal_store: Path) -> ToolRegistry:
    heads = {n: Head.load(heads_dir / n) for n in CROWD_HEADS if (heads_dir / n).exists()}
    personal = PersonalHead(heads["appeal"], personal_store) if "appeal" in heads else None
    reg = ToolRegistry()

    @reg.register("brain_eval")
    def brain_eval(item_id: str, heads_: list[str] | None = None, **kw: Any) -> dict:
        wanted = kw.get("heads") or heads_ or [*CROWD_HEADS, "personal"]
        x = cache.get(item_id)
        out: dict[str, Any] = {"item_id": item_id, "heads": {}}
        for n in wanted:
            if n == "personal":
                out["heads"]["personal"] = personal(x) if personal else None
            elif n in heads:
                out["heads"][n] = heads[n](x).to_dict()
        return out

    @reg.register("compare")
    def compare(item_id: str, against: list[str] | None = None) -> dict:
        others = against or [i for i in cache.ids() if i != item_id]
        rows = {}
        for n, h in heads.items():
            cur = h(cache.get(item_id)).score
            rows[n] = {"current": round(cur, 3),
                       "others": {o: round(h(cache.get(o)).score, 3) for o in others}}
        return {"item_id": item_id, "by_head": rows}

    @reg.register("web_lookup")
    def web_lookup(query: str) -> dict:
        # Placeholder: wire to a search API during the hackathon (or the Meta Model API's
        # own browsing if available). Keep it factual-only.
        return {"query": query, "results": [], "note": "web lookup not configured"}

    @reg.register("record_feedback")
    def record_feedback(item_id: str, liked: bool) -> dict:
        if personal is None:
            return {"error": "personal head unavailable (appeal head missing)"}
        personal.add_feedback(item_id, cache.get(item_id), liked)
        return {"stored": True, "n_feedback": len(personal.y)}

    return reg
