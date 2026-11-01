"""Server smoke test: fake TRIBE endpoint + mock LLM, real heads trained on synthetic features."""
import base64
import importlib

import numpy as np
from fastapi.testclient import TestClient

from brainsense.heads.head import Head, HeadConfig
from brainsense.tribe.rois import feature_names


def test_server_roundtrip(tmp_path, monkeypatch):
    rng = np.random.default_rng(0)
    d = len(feature_names())
    X = rng.standard_normal((300, d)).astype(np.float32); y = (X[:, 1] > 0).astype(float)
    for name in ("aesthetic", "attention", "appeal"):
        Head(HeadConfig(name=name, feature_names=feature_names())).fit(X[:240], y[:240], X[240:], y[240:]).save(tmp_path / "heads" / name)

    monkeypatch.setenv("BRAINSENSE_HEADS_DIR", str(tmp_path / "heads"))
    monkeypatch.setenv("BRAINSENSE_PERSONAL_STORE", str(tmp_path / "personal.json"))
    monkeypatch.setenv("BRAINSENSE_LLM_MOCK", "1")
    import brainsense.agent.server as server
    importlib.reload(server)

    def fake_tribe(payload):
        return {"roi_feats": X[0].tolist(), "roi_ts": {"visual_early": [0.1, 0.3, -0.2]},
                "timing": {"predict_s": 1.2, "total_s": 2.0}}
    monkeypatch.setattr(server, "_tribe_call", fake_tribe)

    c = TestClient(server.app)
    assert c.get("/health").json()["heads"] == ["aesthetic", "appeal", "attention"]
    r = c.post("/analyze", json={"video_b64": base64.b64encode(b"fake").decode(), "item_id": "it1"})
    assert r.status_code == 200 and r.json()["timing"]["total_s"] == 2.0
    r = c.post("/agent", json={"item_id": "it1", "text": "이거 어때?"})
    assert r.status_code == 200 and "상위" in r.json()["text"]
    assert c.post("/agent", json={"item_id": "missing", "text": "?"}).status_code == 404
    r = c.post("/agent/feedback", json={"item_id": "it1", "liked": True})
    assert r.json()["stored"] is True
