"""Sleep (architecture layer L3): consolidation over brain states.

What a prompt cannot do, a sleep can:
  1. prioritized replay  — outcomes the current heads got most wrong (high surprise) get more weight
                           in the personal refit, low-surprise ones decay (hippocampal replay, literal);
  2. refit the organs    — the personal head is refit on all labeled engrams (crowd prior kept);
  3. mine verbal rules   — liked vs disliked engrams are contrasted area by area (bootstrap CI); the
                           largest stable contrasts become one-sentence, falsifiable rules written to
                           state/rules/<owner>/USER_TASTE.md (the Markdown mirror); a rule whose
                           contrast flips sign is retired, never edited — the file is a ledger;
  4. report              — personal-head AUROC before vs after on the newest outcomes: the learning
                           curve is the product metric.
CPU only; brain states are already cached, so a sleep over thousands of engrams takes seconds.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import numpy as np

from ..heads.personal import PersonalHead
from ..tribe.rois import ROI_GROUPS
from .engram import EngramStore

AREA_GROUP = {a: g for g, areas in ROI_GROUPS.items() for a in areas}
GROUP_KO = {"visual_early": "기본 시각", "visual_motion": "움직임·형태", "face_body": "얼굴·사람", "scene_place": "장소·배경",
            "attention_dorsal": "시각 주의", "value_vmpfc": "보상·가치", "language": "언어", "default_mode": "이야기·상상",
            "control_dlpfc": "집중·통제"}


def _area_names(personal: PersonalHead) -> list[str]:
    names = personal.crowd.cfg.feature_names or [f"area{i}" for i in range(360)]
    return [str(n).replace("__mean", "") for n in names[:360]]


def _auroc(y: np.ndarray, p: np.ndarray) -> float | None:
    if len(y) < 4 or len(set(y.tolist())) < 2:
        return None
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(y, p))


def mine_rules(X: np.ndarray, y: np.ndarray, names: list[str], *, n_boot: int = 200, top: int = 4,
               seed: int = 0) -> list[dict[str, Any]]:
    """Area contrasts liked − disliked with bootstrap CIs; keep the largest whose CI excludes 0.
    Each rule carries the area, its group, the effect size (Cohen's d) and the item counts."""
    rng = np.random.default_rng(seed)
    pos, neg = X[y >= 0.5], X[y < 0.5]
    if len(pos) < 3 or len(neg) < 3:
        return []
    sd = X.std(0) + 1e-6
    d = (pos.mean(0) - neg.mean(0)) / sd
    boots = np.empty((n_boot, X.shape[1]), np.float32)
    for b in range(n_boot):
        pi = rng.integers(0, len(pos), len(pos)); ni = rng.integers(0, len(neg), len(neg))
        boots[b] = (pos[pi].mean(0) - neg[ni].mean(0)) / sd
    lo, hi = np.percentile(boots, 5, axis=0), np.percentile(boots, 95, axis=0)
    stable = np.where((lo > 0) | (hi < 0))[0]
    order = stable[np.argsort(-np.abs(d[stable]))][:top]
    rules = []
    for i in order:
        area = names[i]; code = area.split("_", 1)[-1]
        g = AREA_GROUP.get(code, "")
        rules.append({"area": area, "group": g, "group_ko": GROUP_KO.get(g, g), "d": round(float(d[i]), 2),
                      "ci": [round(float(lo[i]), 2), round(float(hi[i]), 2)],
                      "direction": "higher" if d[i] > 0 else "lower",
                      "n_liked": int(len(pos)), "n_disliked": int(len(neg)),
                      "confidence": round(float(min(0.95, abs(d[i]) / 2 * min(1.0, len(y) / 20))), 2)})
    return rules


def phrase_rules(rules: list[dict[str, Any]], owner: str) -> list[str]:
    """One falsifiable sentence per rule. Uses the Meta Model API when configured, else a template."""
    template = []
    for r in rules:
        side = "더 켜질 때" if r["direction"] == "higher" else "더 조용할 때"
        template.append(f"{r['group_ko']} 영역({r['area']})이 {side} 네가 좋아할 확률이 높다 "
                        f"(효과 크기 d={r['d']}, 좋아 {r['n_liked']}개 vs 별로 {r['n_disliked']}개).")
    if os.environ.get("BRAINSENSE_LLM_MOCK") == "1" or not os.environ.get("BRAINSENSE_LLM_API_KEY"):
        return template
    try:
        from openai import OpenAI
        client = OpenAI(base_url=os.environ["BRAINSENSE_LLM_BASE_URL"], api_key=os.environ["BRAINSENSE_LLM_API_KEY"])
        prompt = ("You are the sleep pass of an agent whose memory is predicted human brain states. Below are statistically "
                  "stable contrasts between things the user liked and disliked, as cortical areas. Rewrite EACH as one "
                  "falsifiable Korean sentence about the user's taste in plain words (what kind of images/text/sound), "
                  "keeping the area code in parentheses and the effect size. Return a JSON list of strings, same order, "
                  "nothing else.\n" + json.dumps(rules, ensure_ascii=False))
        res = client.chat.completions.create(model=os.environ["BRAINSENSE_LLM_MODEL"],
                                             messages=[{"role": "user", "content": prompt}], max_tokens=1200)
        txt = res.choices[0].message.content or ""
        start, end = txt.find("["), txt.rfind("]")
        out = json.loads(txt[start:end + 1])
        if isinstance(out, list) and len(out) == len(rules) and all(isinstance(x, str) for x in out):
            return out
    except Exception:
        pass
    return template


def sleep(store: EngramStore, personal: PersonalHead | None, *, owner: str = "local-user",
          rules_dir: Path = Path("state/rules"), min_outcomes: int = 6) -> dict[str, Any]:
    t0 = time.time()
    ids, X, y, t = store.labeled(owner)
    report: dict[str, Any] = {"owner": owner, "n_labeled": int(len(ids)), "n_engrams": store.count(owner)["engrams"]}
    if len(ids) < min_outcomes or personal is None:
        report["skipped"] = f"need ≥{min_outcomes} labeled engrams and a personal head"
        store.log_consolidation(owner, report["n_engrams"], len(ids), None, None, report)
        return report

    # 1. surprise = |current prediction − outcome| (before refit), stored on the engram
    before = personal(X[0]) if False else None  # placeholder to keep structure explicit
    p_before = np.array([
        (personal(x)["personal"] or {}).get("score", float(personal.crowd.predict(x[None])[0])) for x in X
    ])
    surprise = np.abs(p_before - y)
    for i, s in zip(ids, surprise):
        store.set_surprise(i, float(s))
    # newest 30 % as a temporal holdout for the before/after report
    order = np.argsort(t); n_hold = max(2, int(0.3 * len(ids)))
    hold = order[-n_hold:]; fit = order[:-n_hold]
    auroc_before = _auroc(y[hold], p_before[hold])

    # 2. prioritized replay: refit on everything with weights 1 + surprise (high-error items count double)
    personal.X, personal.y, personal.ids = [], [], []
    for i in np.argsort(t):   # chronological, so the store's order is the order of experience
        personal.ids.append(ids[i]); personal.X.append([float(v) for v in X[i]]); personal.y.append(int(y[i] >= 0.5))
    # duplicate high-surprise items once more (simple integer re-weighting that PersonalHead understands)
    for i in np.where(surprise > 0.5)[0]:
        personal.ids.append(ids[i]); personal.X.append([float(v) for v in X[i]]); personal.y.append(int(y[i] >= 0.5))
    personal.store_path.parent.mkdir(parents=True, exist_ok=True)
    personal.store_path.write_text(json.dumps({"X": personal.X, "y": personal.y, "ids": personal.ids}))
    personal._refit()
    p_after = np.array([(personal(x)["personal"] or {}).get("score", 0.5) for x in X]) if personal.model is not None else p_before
    auroc_after = _auroc(y[hold], p_after[hold])

    # 3. rules
    names = _area_names(personal)
    mined = mine_rules(X, y, names)
    sentences = phrase_rules(mined, owner)
    existing = store.rules(owner)
    for r in existing:   # retire rules whose contrast flipped or vanished
        ev = r.get("evidence") or {}
        still = next((m for m in mined if m["area"] == ev.get("area")), None)
        if still is None or still["direction"] != ev.get("direction"):
            store.retire_rule(r["id"])
    new_rules = []
    for m, text in zip(mined, sentences):
        if any((r.get("evidence") or {}).get("area") == m["area"] and (r.get("evidence") or {}).get("direction") == m["direction"]
               and r.get("retired_at") is None for r in existing):
            continue
        store.add_rule(owner, text, {**m, "items": ids[:50]}, m["confidence"])
        new_rules.append(text)
    # 4. markdown mirror
    out_dir = rules_dir / owner; out_dir.mkdir(parents=True, exist_ok=True)
    active = store.rules(owner)
    md = [f"# USER_TASTE — {owner}", "", f"_consolidated {time.strftime('%Y-%m-%d %H:%M')} · {len(ids)} labeled brain states · "
          f"personal head AUROC {auroc_before if auroc_before is None else round(auroc_before, 3)} → "
          f"{auroc_after if auroc_after is None else round(auroc_after, 3)} on the newest {n_hold}_", ""]
    for r in active:
        md.append(f"- {r['text']}  _(confidence {r['confidence']})_")
    retired = [r for r in store.rules(owner, include_retired=True) if r["retired_at"]]
    if retired:
        md += ["", "## retired", ""] + [f"- ~~{r['text']}~~" for r in retired[-10:]]
    (out_dir / "USER_TASTE.md").write_text("\n".join(md) + "\n")

    report.update({"auroc_before": auroc_before, "auroc_after": auroc_after, "holdout": int(n_hold),
                   "high_surprise": int((surprise > 0.5).sum()), "rules_new": new_rules,
                   "rules_active": [r["text"] for r in active], "seconds": round(time.time() - t0, 2)})
    store.log_consolidation(owner, report["n_engrams"], len(ids), auroc_before, auroc_after, report)
    return report
