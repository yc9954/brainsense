"""Personal head: 'your brain' vs 'the crowd's brain'.

Same cached TRIBE features, but fit on the user's own 👍/👎 feedback. Warm-started towards
the crowd head's decision function so that with 0 feedback it equals the crowd prediction and
drifts towards the user as feedback accumulates. Refit on every feedback (features are cached,
so this is milliseconds)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

from .head import Head, HeadOutput


class PersonalHead:
    MIN_FEEDBACK = 6   # below this, defer to the crowd head entirely

    def __init__(self, crowd: Head, store_path: Path, prior_strength: float = 4.0) -> None:
        self.crowd = crowd
        self.store_path = Path(store_path)
        self.prior_strength = prior_strength   # pseudo-count weight of crowd prior
        self.X: list[list[float]] = []
        self.y: list[int] = []
        self.ids: list[str] = []
        self.model: LogisticRegression | None = None
        if self.store_path.exists():
            st = json.loads(self.store_path.read_text())
            self.X, self.y, self.ids = st["X"], st["y"], st["ids"]
            self._refit()

    def add_feedback(self, item_id: str, x: np.ndarray, liked: bool) -> None:
        self.ids.append(item_id); self.X.append([float(v) for v in x]); self.y.append(int(liked))
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(json.dumps({"X": self.X, "y": self.y, "ids": self.ids}))
        self._refit()

    def _embed(self, X: np.ndarray) -> np.ndarray:
        """The crowd head's own feature space (scaler, or scaler → PCA-54 → scaler for area heads):
        a handful of 👍/👎 should move 54 well-conditioned dimensions, not 360 raw areas."""
        return self.crowd.model[:-1].transform(np.asarray(X, dtype=np.float32))

    def _refit(self) -> None:
        if len(self.y) < self.MIN_FEEDBACK or len(set(self.y)) < 2:
            self.model = None
            return
        X = np.asarray(self.X, dtype=np.float32)
        y = np.asarray(self.y)
        # Prior: augment with crowd-labelled copies of the same items, weighted by prior_strength/n.
        crowd_p = self.crowd.predict(X)
        Xa = np.vstack([X, X, X])
        ya = np.concatenate([y, np.ones_like(y), np.zeros_like(y)])
        w = np.concatenate([np.ones(len(y)),
                            self.prior_strength / len(y) * crowd_p,
                            self.prior_strength / len(y) * (1 - crowd_p)])
        self.model = LogisticRegression(C=0.5, max_iter=2000).fit(self._embed(Xa), ya, sample_weight=w)

    def __call__(self, x: np.ndarray) -> dict:
        crowd_out: HeadOutput = self.crowd(x)
        if self.model is None:
            return {"crowd": crowd_out.to_dict(), "personal": None,
                    "n_feedback": len(self.y), "note": "not enough personal feedback yet"}
        p = float(self.model.predict_proba(self._embed(x[None]))[0, 1])
        # nearest past feedback item, for 'you said X about something similar' explanations
        X = np.asarray(self.X, dtype=np.float32)
        d = np.linalg.norm(self._embed(X) - self._embed(x[None]), axis=1)
        j = int(np.argmin(d))
        return {"crowd": crowd_out.to_dict(),
                "personal": {"score": p, "confidence": abs(p - 0.5) * 2,
                             "nearest_feedback": {"item_id": self.ids[j], "liked": bool(self.y[j]),
                                                  "distance": float(d[j])}},
                "n_feedback": len(self.y),
                "disagreement": round(p - crowd_out.score, 3)}
