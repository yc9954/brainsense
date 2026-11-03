"""Wires heads + feature cache + agent into the tools the LLM can call."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..heads.head import Head
from ..heads.personal import PersonalHead
from .tools import ToolRegistry

CROWD_HEADS = ("aesthetic", "attention", "appeal", "popularity", "humanlike", "hook")
# Which heads make sense for which stimulus; Muse can still ask for any subset explicitly.
HEADS_BY_KIND = {"image": ("aesthetic", "attention", "appeal", "popularity", "personal"),
                 "video": ("aesthetic", "attention", "appeal", "popularity", "personal"),
                 "text": ("humanlike", "attention"),
                 "audio": ("hook", "attention", "appeal")}


class FeatureCache:
    """item_id -> feature vector, filled by the TRIBE service. Mirrored to disk (`state/features/`)
    so a server restart never loses an analyzed item mid-conversation."""

    def __init__(self, store_dir: Path | None = None) -> None:
        self._d: dict[str, np.ndarray] = {}
        self._area: dict[str, np.ndarray] = {}
        self.store_dir = Path(store_dir) if store_dir is not None else Path(
            __import__("os").environ.get("BRAINSENSE_FEATURE_STORE", "state/features"))
        if self.store_dir.exists():
            for f in self.store_dir.glob("*.npy"):
                if f.name.endswith(".area.npy"):
                    self._area[f.name[: -len(".area.npy")]] = np.load(f)
                else:
                    self._d[f.stem] = np.load(f)

    def put(self, item_id: str, x: np.ndarray, area: np.ndarray | None = None) -> None:
        self._d[item_id] = np.asarray(x, dtype=np.float32)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        np.save(self.store_dir / f"{item_id}.npy", self._d[item_id])
        if area is not None and len(area):
            self._area[item_id] = np.asarray(area, dtype=np.float32)
            np.save(self.store_dir / f"{item_id}.area.npy", self._area[item_id])

    def get_area(self, item_id: str) -> np.ndarray:
        """720-d per-area features (360 means + 360 slopes); KeyError if the item predates them."""
        if item_id not in self._area:
            f = self.store_dir / f"{item_id}.area.npy"
            if not f.exists():
                raise KeyError(f"no per-area features for {item_id}")
            self._area[item_id] = np.load(f)
        return self._area[item_id]

    def get(self, item_id: str) -> np.ndarray:
        if item_id not in self._d:
            f = self.store_dir / f"{item_id}.npy"
            if f.exists():
                self._d[item_id] = np.load(f)
            else:
                raise KeyError(f"no features cached for {item_id}; run the TRIBE service first")
        return self._d[item_id]

    def ids(self) -> list[str]:
        return list(self._d)


def build_registry(heads_dir: Path, cache: FeatureCache, personal_store: Path) -> ToolRegistry:
    heads = {n: Head.load(heads_dir / n) for n in CROWD_HEADS if (heads_dir / n).exists()}
    # The personal organ grows on the strongest area head (aesthetic, 360 areas → PCA-54), the same
    # space the engram store indexes; appeal (54-d groups) is the fallback for old workspaces.
    prior = heads.get("aesthetic") if heads.get("aesthetic") and heads["aesthetic"].cfg.pca_dim else heads.get("appeal")
    personal = PersonalHead(prior, personal_store) if prior is not None else None
    reg = ToolRegistry()

    def features_for(head: Head, item_id: str) -> np.ndarray:
        """Each head declares its input: 54-d group features or 360 per-area means."""
        if head.cfg.feature_key == "roi_area_mean":
            return cache.get_area(item_id)[:360]
        return cache.get(item_id)

    @reg.register("brain_eval")
    def brain_eval(item_id: str, heads_: list[str] | None = None, **kw: Any) -> dict:
        wanted = kw.get("heads") or heads_ or [*CROWD_HEADS, "personal"]
        out: dict[str, Any] = {"item_id": item_id, "heads": {}}
        for n in wanted:
            try:
                if n == "personal":
                    out["heads"]["personal"] = personal(features_for(personal.crowd, item_id)) if personal else None
                elif n in heads:
                    out["heads"][n] = heads[n](features_for(heads[n], item_id)).to_dict()
            except KeyError as e:   # e.g. an item analyzed before per-area features existed
                out["heads"][n] = {"error": str(e)}
        return out

    @reg.register("compare")
    def compare(item_id: str, against: list[str] | None = None) -> dict:
        others = against or [i for i in cache.ids() if i != item_id]
        rows = {}
        for n, h in heads.items():
            try:
                cur = h(features_for(h, item_id)).score
                rows[n] = {"current": round(cur, 3),
                           "others": {o: round(h(features_for(h, o)).score, 3) for o in others}}
            except KeyError as e:
                rows[n] = {"error": str(e)}
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
        personal.add_feedback(item_id, features_for(personal.crowd, item_id), liked)
        return {"stored": True, "n_feedback": len(personal.y)}

    reg._personal = personal   # the sleep pass refits this organ
    return reg
