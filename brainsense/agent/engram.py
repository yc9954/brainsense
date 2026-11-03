"""Engram store (architecture layer L2): the agent's memory is a table of predicted brain states.

One row per percept (photo, clip, track, paragraph): the 360 HCP-MMP1 area means TRIBE v2 predicts
for it, a shared PCA-54 key for similarity, the 1 Hz region series the voice cites, what the stimulus
was, and what happened afterwards (outcomes: liked, chosen_over, sold, ...). Similarity is cosine in
cortex space — "what have I seen that *felt* like this to a brain" — not caption search.

SQLite + numpy blobs, so it is inspectable with any sqlite client (the Markdown-memory frameworks'
transparency, applied to brain states). Only `sleep()` (L3) writes head weights and verbal rules.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS engrams (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, owner TEXT NOT NULL DEFAULT 'local-user',
  thread_id TEXT, created_at REAL NOT NULL, stimulus_ref TEXT, cortex BLOB NOT NULL, pca BLOB,
  roi_ts TEXT, surprise REAL DEFAULT 0, note TEXT);
CREATE TABLE IF NOT EXISTS outcomes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, engram_id TEXT NOT NULL, kind TEXT NOT NULL,
  value REAL NOT NULL, against TEXT, created_at REAL NOT NULL, consolidated INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, text TEXT NOT NULL, evidence TEXT,
  confidence REAL NOT NULL, created_at REAL NOT NULL, retired_at REAL);
CREATE TABLE IF NOT EXISTS consolidations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, started_at REAL NOT NULL,
  n_engrams INTEGER, n_outcomes INTEGER, auroc_before REAL, auroc_after REAL, report TEXT);
CREATE INDEX IF NOT EXISTS idx_outcomes_engram ON outcomes(engram_id);
CREATE INDEX IF NOT EXISTS idx_engrams_owner ON engrams(owner, kind);
"""


@dataclass
class Recall:
    id: str
    kind: str
    similarity: float
    stimulus_ref: str | None
    note: str | None
    outcomes: list[dict[str, Any]]
    created_at: float


class EngramStore:
    def __init__(self, path: Path | str = "state/engrams.sqlite") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ---- writes -------------------------------------------------------------------------------
    def upsert(self, item_id: str, kind: str, cortex: np.ndarray, pca: np.ndarray | None = None, *,
               owner: str = "local-user", thread_id: str | None = None, stimulus_ref: str | None = None,
               roi_ts: dict[str, list[float]] | None = None, note: str | None = None) -> None:
        c = np.asarray(cortex, dtype=np.float32)[:360]
        p = None if pca is None else np.asarray(pca, dtype=np.float32)
        self.db.execute(
            "INSERT INTO engrams(id, kind, owner, thread_id, created_at, stimulus_ref, cortex, pca, roi_ts, note) "
            "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, cortex=excluded.cortex, "
            "pca=COALESCE(excluded.pca, engrams.pca), roi_ts=COALESCE(excluded.roi_ts, engrams.roi_ts), "
            "stimulus_ref=COALESCE(excluded.stimulus_ref, engrams.stimulus_ref), note=COALESCE(excluded.note, engrams.note)",
            (item_id, kind, owner, thread_id, time.time(), stimulus_ref, c.tobytes(),
             None if p is None else p.tobytes(), json.dumps(roi_ts) if roi_ts else None, note))
        self.db.commit()

    def set_note(self, item_id: str, note: str) -> None:
        self.db.execute("UPDATE engrams SET note=? WHERE id=?", (note[:400], item_id))
        self.db.commit()

    def add_outcome(self, item_id: str, kind: str, value: float, against: str | None = None) -> int:
        cur = self.db.execute("INSERT INTO outcomes(engram_id, kind, value, against, created_at) VALUES(?,?,?,?,?)",
                              (item_id, kind, float(value), against, time.time()))
        self.db.commit()
        return int(cur.lastrowid)

    # ---- reads --------------------------------------------------------------------------------
    def has(self, item_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM engrams WHERE id=?", (item_id,)).fetchone() is not None

    def get(self, item_id: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT id, kind, owner, stimulus_ref, cortex, pca, roi_ts, note, created_at, surprise "
                              "FROM engrams WHERE id=?", (item_id,)).fetchone()
        if not row:
            return None
        return {"id": row[0], "kind": row[1], "owner": row[2], "stimulus_ref": row[3],
                "cortex": np.frombuffer(row[4], dtype=np.float32), "pca": None if row[5] is None else np.frombuffer(row[5], dtype=np.float32),
                "roi_ts": json.loads(row[6]) if row[6] else {}, "note": row[7], "created_at": row[8], "surprise": row[9]}

    def outcomes_for(self, item_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT kind, value, against, created_at FROM outcomes WHERE engram_id=? ORDER BY created_at",
                               (item_id,)).fetchall()
        return [{"kind": k, "value": v, "against": a, "created_at": t} for k, v, a, t in rows]

    def count(self, owner: str | None = None) -> dict[str, int]:
        q = "SELECT COUNT(*) FROM engrams" + (" WHERE owner=?" if owner else "")
        n = self.db.execute(q, (owner,) if owner else ()).fetchone()[0]
        m = self.db.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
        r = self.db.execute("SELECT COUNT(*) FROM rules WHERE retired_at IS NULL").fetchone()[0]
        return {"engrams": int(n), "outcomes": int(m), "rules": int(r)}

    def _matrix(self, owner: str | None, kinds: list[str] | None, exclude: str | None):
        q = "SELECT id, kind, pca, cortex, stimulus_ref, note, created_at FROM engrams WHERE 1=1"
        args: list[Any] = []
        if owner:
            q += " AND owner=?"; args.append(owner)
        if kinds:
            q += f" AND kind IN ({','.join('?' * len(kinds))})"; args.extend(kinds)
        if exclude:
            q += " AND id<>?"; args.append(exclude)
        rows = self.db.execute(q, args).fetchall()
        return rows

    def recall(self, query: np.ndarray, *, k: int = 5, owner: str | None = None, kinds: list[str] | None = None,
               exclude: str | None = None, use_pca: bool = True, with_outcomes_only: bool = False) -> list[Recall]:
        """k nearest engrams by cosine similarity in PCA-54 space (falls back to the 360 cortex vector)."""
        rows = self._matrix(owner, kinds, exclude)
        if not rows:
            return []
        q = np.asarray(query, dtype=np.float32)
        keys, meta = [], []
        for rid, kind, pca, cortex, ref, note, created in rows:
            v = np.frombuffer(pca, dtype=np.float32) if (use_pca and pca is not None and len(q) != 360) else np.frombuffer(cortex, dtype=np.float32)
            if v.shape != q.shape:
                continue
            keys.append(v); meta.append((rid, kind, ref, note, created))
        if not keys:
            return []
        M = np.vstack(keys)
        sims = (M @ q) / (np.linalg.norm(M, axis=1) * np.linalg.norm(q) + 1e-8)
        order = np.argsort(-sims)
        out: list[Recall] = []
        seen: list[np.ndarray] = []
        for j in order:
            rid, kind, ref, note, created = meta[j]
            # the same photo re-analyzed under another id is one percept, not a precedent: collapse
            # near-identical brain states, keeping the one that has outcomes
            if any(float(keys[j] @ s_) / (np.linalg.norm(keys[j]) * np.linalg.norm(s_) + 1e-8) > 0.995 for s_ in seen):
                continue
            oc = self.outcomes_for(rid)
            if with_outcomes_only and not oc:
                continue
            seen.append(keys[j])
            out.append(Recall(rid, kind, float(sims[j]), ref, note, oc, created))
            if len(out) >= k:
                break
        return out

    # ---- rules --------------------------------------------------------------------------------
    def rules(self, owner: str = "local-user", include_retired: bool = False) -> list[dict[str, Any]]:
        q = "SELECT id, text, evidence, confidence, created_at, retired_at FROM rules WHERE owner=?"
        if not include_retired:
            q += " AND retired_at IS NULL"
        rows = self.db.execute(q + " ORDER BY confidence DESC, created_at DESC", (owner,)).fetchall()
        return [{"id": i, "text": t, "evidence": json.loads(e) if e else None, "confidence": c,
                 "created_at": ca, "retired_at": ra} for i, t, e, c, ca, ra in rows]

    def add_rule(self, owner: str, text: str, evidence: dict[str, Any], confidence: float) -> int:
        cur = self.db.execute("INSERT INTO rules(owner, text, evidence, confidence, created_at) VALUES(?,?,?,?,?)",
                              (owner, text, json.dumps(evidence, ensure_ascii=False), float(confidence), time.time()))
        self.db.commit()
        return int(cur.lastrowid)

    def update_rule(self, rule_id: int, text: str, confidence: float, evidence: dict[str, Any]) -> None:
        self.db.execute("UPDATE rules SET text=?, confidence=?, evidence=? WHERE id=?",
                        (text, float(confidence), json.dumps(evidence, ensure_ascii=False), rule_id))
        self.db.commit()

    def retire_rule(self, rule_id: int) -> None:
        self.db.execute("UPDATE rules SET retired_at=? WHERE id=?", (time.time(), rule_id))
        self.db.commit()

    # ---- consolidation bookkeeping -------------------------------------------------------------
    def labeled(self, owner: str = "local-user") -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray]:
        """Engrams with a like/choice outcome → (ids, X[360], y, created_at). chosen_over counts as liked,
        rejected as disliked; the latest outcome wins."""
        rows = self.db.execute(
            "SELECT e.id, e.cortex, o.kind, o.value, o.created_at FROM engrams e JOIN outcomes o ON o.engram_id=e.id "
            "WHERE e.owner=? AND o.kind IN ('liked','chosen_over','rejected') ORDER BY o.created_at", (owner,)).fetchall()
        latest: dict[str, tuple[float, np.ndarray, float]] = {}
        for rid, cortex, kind, value, t in rows:
            y = float(value) if kind == "liked" else (1.0 if kind == "chosen_over" else 0.0)
            latest[rid] = (y, np.frombuffer(cortex, dtype=np.float32), t)
        ids = list(latest)
        if not ids:
            return [], np.zeros((0, 360), np.float32), np.zeros(0), np.zeros(0)
        X = np.vstack([latest[i][1] for i in ids]); y = np.array([latest[i][0] for i in ids]); t = np.array([latest[i][2] for i in ids])
        return ids, X, y, t

    def set_surprise(self, item_id: str, surprise: float) -> None:
        self.db.execute("UPDATE engrams SET surprise=? WHERE id=?", (float(surprise), item_id))

    def log_consolidation(self, owner: str, n_engrams: int, n_outcomes: int, before: float | None, after: float | None,
                          report: dict[str, Any]) -> int:
        cur = self.db.execute("INSERT INTO consolidations(owner, started_at, n_engrams, n_outcomes, auroc_before, auroc_after, report) "
                              "VALUES(?,?,?,?,?,?,?)", (owner, time.time(), n_engrams, n_outcomes, before, after,
                                                        json.dumps(report, ensure_ascii=False)))
        self.db.execute("UPDATE outcomes SET consolidated=1 WHERE consolidated=0")
        self.db.commit()
        return int(cur.lastrowid)

    def consolidations(self, owner: str = "local-user") -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT id, started_at, n_engrams, n_outcomes, auroc_before, auroc_after, report FROM consolidations "
                               "WHERE owner=? ORDER BY started_at", (owner,)).fetchall()
        return [{"id": i, "started_at": s, "n_engrams": ne, "n_outcomes": no, "auroc_before": b, "auroc_after": a,
                 "report": json.loads(r) if r else None} for i, s, ne, no, b, a, r in rows]
