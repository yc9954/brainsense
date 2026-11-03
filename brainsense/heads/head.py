"""Small calibrated prediction heads on top of cached features.

A Head answers ONE question ("is it pretty?", "will people keep watching?") and returns
- a probability (binary) or score (regression),
- a percentile against the training distribution (so the agent can say "top 30%"),
- a confidence derived from calibrated probability distance to 0.5,
- the top contributing input dimensions (for ROI-level explanations).

Everything is deliberately tiny: features are precomputed once (TRIBE ROI summaries or raw
embeddings), so training takes seconds and the personal head can be refit on every feedback.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import joblib
import numpy as np
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.neural_network import MLPClassifier, MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

Task = Literal["binary", "regression"]
Arch = Literal["linear", "mlp"]


@dataclass
class HeadConfig:
    name: str
    task: Task = "binary"
    arch: Arch = "linear"
    feature_key: str = "tribe_roi"        # which array in the feature store to use
    feature_names: list[str] = field(default_factory=list)  # e.g. ROI names for explanations
    C: float = 1.0                         # inverse L2 strength for linear heads
    hidden: int = 64                       # MLP hidden width
    seed: int = 0
    pca_dim: int | None = None             # e.g. 54: StandardScaler → PCA → head (for 360-area inputs)


@dataclass
class HeadOutput:
    head: str
    score: float                 # calibrated probability (binary) or predicted value (regression)
    percentile: float            # 0-100 vs. training distribution of scores
    confidence: float            # 0-1; for binary: |p-0.5|*2 after calibration
    top_features: list[tuple[str, float]]   # (feature_name, signed contribution)
    n_train: int
    calibrated: bool

    def to_dict(self) -> dict:
        d = asdict(self)
        d["top_features"] = [{"name": n, "contribution": round(float(c), 4)} for n, c in self.top_features]
        return d


class TemperatureScaler:
    """Single-parameter calibration for binary logits (Guo et al. 2017)."""

    def __init__(self) -> None:
        self.T = 1.0

    def fit(self, logits: np.ndarray, y: np.ndarray) -> TemperatureScaler:
        from scipy.optimize import minimize_scalar

        def nll(t: float) -> float:
            z = logits / t
            p = 1 / (1 + np.exp(-z))
            eps = 1e-7
            return -np.mean(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps))

        res = minimize_scalar(nll, bounds=(0.05, 20.0), method="bounded")
        self.T = float(res.x)
        return self

    def __call__(self, logits: np.ndarray) -> np.ndarray:
        return 1 / (1 + np.exp(-logits / self.T))


def expected_calibration_error(p: np.ndarray, y: np.ndarray, n_bins: int = 10) -> float:
    bins = np.linspace(0, 1, n_bins + 1)
    idx = np.digitize(p, bins[1:-1])
    ece = 0.0
    for b in range(n_bins):
        m = idx == b
        if m.any():
            ece += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(ece)


class Head:
    def __init__(self, cfg: HeadConfig) -> None:
        self.cfg = cfg
        self.model = self._build()
        self.scaler = TemperatureScaler()
        self.calibrated = False
        self.train_scores: np.ndarray | None = None
        self.n_train = 0

    # ---- construction -------------------------------------------------------------------
    def _build(self):
        c = self.cfg
        if c.task == "binary":
            est = (LogisticRegression(C=c.C, max_iter=2000, random_state=c.seed)
                   if c.arch == "linear"
                   else MLPClassifier(hidden_layer_sizes=(c.hidden,), alpha=1e-2, max_iter=500,
                                      early_stopping=True, random_state=c.seed))
        else:
            est = (Ridge(alpha=1 / c.C)
                   if c.arch == "linear"
                   else MLPRegressor(hidden_layer_sizes=(c.hidden,), alpha=1e-2, max_iter=500,
                                     early_stopping=True, random_state=c.seed))
        if c.pca_dim:
            return make_pipeline(StandardScaler(), PCA(n_components=c.pca_dim, random_state=c.seed), StandardScaler(), est)
        return make_pipeline(StandardScaler(), est)

    # ---- training -----------------------------------------------------------------------
    def fit(self, X: np.ndarray, y: np.ndarray, X_val: np.ndarray | None = None,
            y_val: np.ndarray | None = None) -> Head:
        self.model.fit(X, y)
        self.n_train = len(X)
        self.train_scores = self._raw_scores(X)
        if self.cfg.task == "binary" and X_val is not None and len(X_val) >= 20:
            self.scaler.fit(self._logits(X_val), y_val)
            self.calibrated = True
        return self

    def _logits(self, X: np.ndarray) -> np.ndarray:
        return self.model.decision_function(X) if hasattr(self.model, "decision_function") \
            else np.log(np.clip(self.model.predict_proba(X)[:, 1], 1e-7, 1 - 1e-7) /
                        np.clip(self.model.predict_proba(X)[:, 0], 1e-7, 1))

    def _raw_scores(self, X: np.ndarray) -> np.ndarray:
        if self.cfg.task == "binary":
            return self.scaler(self._logits(X)) if self.calibrated else self.model.predict_proba(X)[:, 1]
        return self.model.predict(X)

    # ---- inference ----------------------------------------------------------------------
    def predict(self, X: np.ndarray) -> np.ndarray:
        return self._raw_scores(X)

    def explain(self, x: np.ndarray, k: int = 3) -> list[tuple[str, float]]:
        """Signed contribution per input feature. Exact for linear heads, gradient-free
        occlusion approximation for MLPs (set each feature to its training mean)."""
        names = self.cfg.feature_names or [f"f{i}" for i in range(len(x))]
        sc: StandardScaler = self.model.steps[0][1]
        est = self.model.steps[-1][1]
        z = (x - sc.mean_) / sc.scale_
        if hasattr(est, "coef_") and self.cfg.pca_dim:
            # back-project the linear head through PCA so contributions land on named input areas
            pca: PCA = self.model.steps[1][1]
            sc2: StandardScaler = self.model.steps[2][1]
            w_pca = np.ravel(est.coef_) / sc2.scale_
            w_orig = w_pca @ pca.components_                     # (n_features,)
            contrib = w_orig * (z - 0)                           # pca.mean_ is ~0 after the first scaler
        elif hasattr(est, "coef_"):
            coef = np.ravel(est.coef_)
            contrib = coef * z
        else:
            base = self._raw_scores(x[None])[0]
            contrib = np.zeros_like(x, dtype=float)
            for i in range(len(x)):
                xo = x.copy(); xo[i] = sc.mean_[i]
                contrib[i] = base - self._raw_scores(xo[None])[0]
        order = np.argsort(-np.abs(contrib))[:k]
        return [(names[i], float(contrib[i])) for i in order]

    def __call__(self, x: np.ndarray, k: int = 3) -> HeadOutput:
        s = float(self._raw_scores(x[None])[0])
        pct = float((self.train_scores < s).mean() * 100) if self.train_scores is not None else 50.0
        conf = abs(s - 0.5) * 2 if self.cfg.task == "binary" else float("nan")
        return HeadOutput(self.cfg.name, s, pct, conf, self.explain(x, k), self.n_train, self.calibrated)

    # ---- persistence --------------------------------------------------------------------
    def save(self, path: Path) -> None:
        path = Path(path); path.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": self.model, "T": self.scaler.T, "calibrated": self.calibrated,
                     "train_scores": self.train_scores, "n_train": self.n_train}, path / "head.joblib")
        (path / "config.json").write_text(json.dumps(asdict(self.cfg), ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path: Path) -> Head:
        path = Path(path)
        cfg = HeadConfig(**json.loads((path / "config.json").read_text()))
        h = cls(cfg)
        st = joblib.load(path / "head.joblib")
        h.model, h.scaler.T, h.calibrated = st["model"], st["T"], st["calibrated"]
        h.train_scores, h.n_train = st["train_scores"], st["n_train"]
        return h
