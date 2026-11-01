"""End-to-end smoke test without GPU/network: synthetic TRIBE-like outputs -> ROI features ->
ablation -> saved heads -> personal head -> agent with a mock LLM."""
from pathlib import Path

import numpy as np

from brainsense.agent.loop import Agent
from brainsense.agent.service import FeatureCache, build_registry
from brainsense.heads.head import Head, HeadConfig
from brainsense.heads.personal import PersonalHead
from brainsense.tribe.rois import (
    N_VERT_FS5,
    ROI_GROUPS,
    feature_names,
    pool_features,
    roi_timeseries,
)


def fake_groups(rng):
    verts = rng.permutation(N_VERT_FS5)
    sizes = np.full(len(ROI_GROUPS), N_VERT_FS5 // len(ROI_GROUPS))
    out, start = {}, 0
    for g, s in zip(ROI_GROUPS, sizes):
        out[g] = np.sort(verts[start:start + s]); start += s
    return out


def test_roi_features_shape():
    rng = np.random.default_rng(0)
    preds = rng.standard_normal((8, N_VERT_FS5)).astype(np.float32)
    ts = roi_timeseries(preds, fake_groups(rng))
    feats, names = pool_features(ts)
    assert feats.shape == (len(ROI_GROUPS) * 6,)
    assert names == feature_names()


def test_heads_and_agent(tmp_path: Path, monkeypatch):
    rng = np.random.default_rng(1)
    n, d = 400, len(feature_names())
    X = rng.standard_normal((n, d)).astype(np.float32)
    w = rng.standard_normal(d) * (rng.random(d) < 0.2)
    y = (X @ w + 0.5 * rng.standard_normal(n) > 0).astype(float)
    heads_dir = tmp_path / "heads"
    for name in ("aesthetic", "attention", "appeal"):
        h = Head(HeadConfig(name=name, feature_names=feature_names()))
        h.fit(X[:300], y[:300], X[300:], y[300:])
        assert h.calibrated
        out = h(X[0])
        assert 0 <= out.score <= 1 and 0 <= out.percentile <= 100 and len(out.top_features) == 3
        h.save(heads_dir / name)

    cache = FeatureCache()
    for i in range(10):
        cache.put(f"item{i}", X[i])
    reg = build_registry(heads_dir, cache, tmp_path / "personal.json")

    r = reg.call("brain_eval", item_id="item0")
    assert set(r["heads"]) == {"aesthetic", "attention", "appeal", "personal"}
    assert r["heads"]["personal"]["personal"] is None  # no feedback yet

    for i in range(8):
        reg.call("record_feedback", item_id=f"item{i}", liked=bool(y[i]))
    r = reg.call("brain_eval", item_id="item9")
    assert r["heads"]["personal"]["personal"] is not None
    assert "disagreement" in r["heads"]["personal"]

    cmp_ = reg.call("compare", item_id="item9", against=["item0", "item1"])
    assert set(cmp_["by_head"]["appeal"]["others"]) == {"item0", "item1"}

    monkeypatch.setenv("BRAINSENSE_LLM_MOCK", "1")
    agent = Agent(registry=reg)
    reply = agent.ask("item9", "이거 어때?")
    assert reply and "상위" in reply
    assert any(t.role == "tool" for t in agent.history)


def test_personal_head_prior_falls_back(tmp_path: Path):
    rng = np.random.default_rng(2)
    d = len(feature_names())
    X = rng.standard_normal((100, d)).astype(np.float32); y = (X[:, 0] > 0).astype(float)
    crowd = Head(HeadConfig(name="appeal")).fit(X, y)
    ph = PersonalHead(crowd, tmp_path / "p.json")
    assert ph(X[0])["personal"] is None
    for i in range(PersonalHead.MIN_FEEDBACK):
        ph.add_feedback(f"i{i}", X[i], liked=bool(i % 2))
    assert ph(X[0])["personal"] is not None
    # reload from disk
    ph2 = PersonalHead(crowd, tmp_path / "p.json")
    assert len(ph2.y) == PersonalHead.MIN_FEEDBACK
