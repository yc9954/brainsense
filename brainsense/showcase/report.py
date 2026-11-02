"""Aggregate one or more showcase runs into the numbers the README/demo quote:
win rate of brain_loop in the blind pairwise judge, brain score by arm, and the round-by-round
learning curve (does the brain critique actually move the score between rounds?).

    uv run python -m brainsense.showcase.report results/showcase/suite1 [results/showcase/ad-1 ...]
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def summarize(run_dirs: list[Path]) -> dict:
    wins = defaultdict(lambda: [0, 0.0, 0])   # key -> [wins, sum p, n]
    brain_by_arm = defaultdict(list)
    curve = defaultdict(lambda: defaultdict(list))   # arm -> round -> select scores
    rows = []
    for rd in run_dirs:
        s = json.loads((rd / "summary.json").read_text(encoding="utf-8"))
        for key, b in s["briefs"].items():
            for k, p in b.get("pairwise", {}).items():
                w = wins[k]
                w[0] += p["p_first"] > 0.5
                w[1] += p["p_first"]
                w[2] += 1
            for arm, f in b["final"].items():
                brain_by_arm[arm].append(f["brain_ui_score"])
            for arm, r in b["arms"].items():
                for h in r["history"]:
                    # judge-only score so the two loops are on the same scale (brain arm stores it under heads.judge)
                    j = h.get("judge", {}).get("judge_score") if "judge" in h else h.get("heads", {}).get("judge", {}).get("judge_score")
                    if j is not None:
                        curve[arm][h["round"]].append(j)
            rows.append((rd.name, key, {a: round(f["brain_ui_score"], 3) for a, f in b["final"].items()},
                         {k: p["p_first"] for k, p in b.get("pairwise", {}).items()}))
    return {"pairwise": {k: {"win_rate": v[0] / v[2], "mean_p": v[1] / v[2], "n": v[2]} for k, v in wins.items()},
            "brain_score_by_arm": {a: sum(v) / len(v) for a, v in brain_by_arm.items()},
            "curve": {a: {r: sum(v) / len(v) for r, v in rs.items()} for a, rs in curve.items()},
            "rows": rows}


def main(argv: list[str]) -> None:
    out = summarize([Path(a) for a in argv] or [Path("results/showcase/suite1")])
    print("## blind pairwise (brain_loop vs …)")
    for k, v in out["pairwise"].items():
        print(f"  {k}: wins {v['win_rate']:.0%} of {v['n']} · mean P(brain better) {v['mean_p']:.2f}")
    print("## mean brain ui_score of finalists by arm")
    for a, v in out["brain_score_by_arm"].items():
        print(f"  {a}: {v:.3f}")
    print("## learning curve (mean independent judge score per round, same scale for every arm)")
    for a, rs in out["curve"].items():
        print(f"  {a}: " + " → ".join(f"r{r} {v:.3f}" for r, v in sorted(rs.items())))
    print("## per brief")
    for run, key, brain, pw in out["rows"]:
        print(f"  {run}/{key}: brain {brain} · pairwise {pw}")


if __name__ == "__main__":
    main(sys.argv[1:])
