"""Score a rendered screenshot with the BrainSense server (TRIBE → heads) and turn it into one number.

ui_score = 0.6 * aesthetic percentile + 0.4 * attention percentile, each scaled 0-1 and down-weighted
by the head's confidence so an uncertain head cannot dominate. The components are kept so the
generator gets *which region moved* as feedback, not just a scalar."""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path

import httpx

SERVER = os.environ.get("BRAINSENSE_SERVER_URL", "http://localhost:8000").rstrip("/")
WEIGHTS = {"aesthetic": 0.6, "attention": 0.4}


@dataclass
class Score:
    item_id: str
    ui_score: float
    heads: dict            # name -> {"score","percentile","confidence","top_features"}
    explanation: str       # one paragraph the generator can act on

    def to_dict(self) -> dict:
        return {"item_id": self.item_id, "ui_score": round(self.ui_score, 4), "heads": self.heads,
                "explanation": self.explanation}


def _feature_ko(name: str) -> str:
    from ..agent.prompt import SYSTEM_PROMPT  # noqa: F401  (keeps the Korean labels in one place)
    group, _, stat = name.partition("__")
    ko = {"visual_early": "기본 시각", "visual_motion": "움직임·형태", "face_body": "얼굴·사람",
          "scene_place": "장소·배경", "attention_dorsal": "시각 주의", "value_vmpfc": "보상·가치",
          "language": "언어", "default_mode": "딴생각", "control_dlpfc": "집중·통제"}
    st = {"mean": "평균", "max": "최대", "early": "초반", "late": "후반", "slope": "변화", "std": "변동"}
    return f"{ko.get(group, group)} {st.get(stat, stat)}".strip()


def score_image(png: Path, item_id: str, timeout_s: int = 900) -> Score:
    data = base64.b64encode(Path(png).read_bytes()).decode()
    with httpx.Client(timeout=timeout_s) as c:
        r = c.post(f"{SERVER}/analyze", json={"video_b64": data, "filename": Path(png).name, "item_id": item_id})
        r.raise_for_status()
        ev = c.get(f"{SERVER}/eval/{item_id}")
        ev.raise_for_status()
    heads = ev.json()["heads"]
    parts, total, wsum = [], 0.0, 0.0
    out_heads = {}
    for name, w in WEIGHTS.items():
        h = heads.get(name)
        if not h:
            continue
        conf = max(0.0, min(1.0, h["confidence"]))
        pct = h["percentile"] / 100
        total += w * (0.5 + (pct - 0.5) * (0.5 + 0.5 * conf))   # shrink toward 0.5 when unsure
        wsum += w
        tops = ", ".join(f"{'▲' if f['contribution'] >= 0 else '▼'} {_feature_ko(f['name'])}" for f in h["top_features"][:2])
        out_heads[name] = {k: h[k] for k in ("score", "percentile", "confidence")} | {"top": tops}
        parts.append(f"{name}: 상위 {100 - h['percentile']:.0f}% (확신 {conf:.2f}; {tops})")
    ui = total / wsum if wsum else 0.5
    return Score(item_id, ui, out_heads, " · ".join(parts))
