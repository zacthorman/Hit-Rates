#!/usr/bin/env python3
"""Tables for TEAM-MODEL-CHECK.md from teammodel_audit.py's output.

    python teammodel_audit_report.py teammodel_audit.json > tables.md

Scores are the tail log loss teammodel_train.py selects on (lower is better),
on the seven days after each Monday run, pooled over matches.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict

import pandas as pd

PATHS = ("frozen", "as_run", "shipped", "fixed", "refit")


def frame(res):
    out = []
    for r in res:
        for w in r["weeks"]:
            if "next" not in w:
                continue
            for p, v in w["next"].items():
                out.append({"scenario": r["scenario"], "stat": r["stat"], "t": w["t"], "n": w["n_next"],
                            "path": p, **v})
    D = pd.DataFrame(out)
    D["week"] = pd.to_datetime(D.t, unit="s").dt.strftime("%Y-%m-%d")
    return D


def pooled(D, by):
    g = D.assign(w=D.tail_ll * D.n).groupby(by)
    return g.w.sum() / g.n.sum()


def md(df, fmt="{:.4f}"):
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join([df.index.name or ""] + cols) + " |",
             "|" + "---|" * (len(cols) + 1)]
    for i, row in df.iterrows():
        cells = [fmt.format(v) if isinstance(v, float) else str(v) for v in row]
        lines.append("| " + " | ".join([str(i)] + cells) + " |")
    return "\n".join(lines)


def decisions(res):
    rows = []
    for r in res:
        for p in ("as_run", "shipped", "fixed"):
            c = defaultdict(int)
            for w in r["weeks"]:
                d = w.get(p, {})
                c[d.get("decision", "?")] += 1
                if d.get("halved"):
                    c["halved"] += 1
                if "alt_next" in d and d.get("decision") == "adopted":
                    c["adopt_helped"] += d["alt_next"] < d["old_next"]
                if "alt_next" in d and d.get("decision") == "rejected":
                    c["reject_helped"] += d["alt_next"] >= d["old_next"]
                if d.get("decision") == "adopted" and "adopted_score" in d:
                    c["halved_worse_than_old"] += d["halved"] and d["adopted_score"] > d["before"]
                    c["slack_used"] += d["after"] > d["before"]
            rows.append({"scenario": r["scenario"], "stat": r["stat"], "path": p, **c})
    return pd.DataFrame(rows).fillna(0)


def shifts(res):
    """How far the weekly candidate moved the holdout's chances (MAX_SHIFT is 3%)."""
    out = {}
    for sc in sorted({r["scenario"] for r in res}):
        x = [w["fixed"]["shift"] for r in res if r["scenario"] == sc for w in r["weeks"] if "shift" in w["fixed"]]
        out[sc] = {"weeks with a candidate": float(len(x)), "median move": float(pd.Series(x).median()),
                   "largest move": float(max(x)), "over 3% (halved)": float(sum(v > 0.03 for v in x))}
    t = pd.DataFrame(out).T
    t.index.name = "scenario"
    return t


def main(path):
    res = json.loads(open(path).read())
    D = frame(res)
    for sc in sorted(D.scenario.unique()):
        X = D[D.scenario == sc]
        print(f"\n### Scenario {sc}: pooled score on the next seven days, per stat\n")
        t = pooled(X, ["stat", "path"]).unstack()[list(PATHS)]
        t.loc["all stats"] = pooled(X, ["path"])[list(PATHS)]
        t.index.name = "stat"
        print(md(t))
        print(f"\n### Scenario {sc}: score path, all stats pooled, week by week\n")
        wk = pooled(X, ["week", "path"]).unstack()[list(PATHS)]
        wk["n"] = X[X.path == "refit"].groupby("week").n.sum()
        wk["fixed - refit"] = wk["fixed"] - wk["refit"]
        wk["fixed - frozen"] = wk["fixed"] - wk["frozen"]
        wk.index.name = "Monday"
        print(md(wk.assign(n=wk.n.astype(int).astype(str))))
        print(f"\n### Scenario {sc}: drift checks (mean over stats)\n")
        drift = X.groupby(["week", "path"])[["calib", "dist_to_refit", "trees"]].mean().unstack()
        first, last = drift.index[:4], drift.index[-4:]
        rows = {}
        for p in PATHS:
            rows[p] = {"calibration first 4 weeks": drift.loc[first, ("calib", p)].mean(),
                       "calibration last 4 weeks": drift.loc[last, ("calib", p)].mean(),
                       "gap to refit first 4 weeks": drift.loc[first, ("dist_to_refit", p)].mean(),
                       "gap to refit last 4 weeks": drift.loc[last, ("dist_to_refit", p)].mean(),
                       "trees at the end": drift.loc[drift.index[-1], ("trees", p)]}
        t = pd.DataFrame(rows).T
        t.index.name = "path"
        print(md(t))
    dec = decisions(res)
    print("\n### Decisions over all weeks (summed over stats)\n")
    cols = [c for c in ("adopted", "rejected", "too few", "crashed", "skipped (earlier stat crashed)", "halved",
                        "adopt_helped", "reject_helped", "slack_used", "halved_worse_than_old") if c in dec]
    t = dec.groupby(["scenario", "path"])[cols].sum().astype(int).astype(str)
    # the as_run path is not given the counterfactual (it equals shipped unless a crash happened)
    for c in ("adopt_helped", "reject_helped"):
        if c in t:
            t.loc[t.index.get_level_values(1) == "as_run", c] = "n/a"
    t.index = [f"{a} {b}" for a, b in t.index]
    t.index.name = "scenario, path"
    print(md(t, "{}"))
    print("\n### Size of the weekly move\n")
    print(md(shifts(res), "{:.4f}"))
    if {"B", "B-bad"} <= set(D.scenario):
        print("\n### Bad week (B-bad minus B, all stats pooled; positive is worse)\n")
        a = pooled(D[D.scenario == "B-bad"], ["week", "path"]).unstack()[list(PATHS)]
        b = pooled(D[D.scenario == "B"], ["week", "path"]).unstack()[list(PATHS)]
        diff = (a - b).loc["2026-02-02":"2026-04-27"]
        diff.index.name = "Monday"
        print(md(diff, "{:+.4f}"))


if __name__ == "__main__":
    main(sys.argv[1])
