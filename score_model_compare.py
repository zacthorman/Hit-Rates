#!/usr/bin/env python3
"""
The case's predicted score: the team ratings (CASE-SCORE.md) against main's
style model (23 Oct, research/open_eval.py), walk-forward, out of sample.

    python score_model_compare.py [--cache DIR] [--from 2026-07-01]

Both are scored on the same matches: every domestic league match in the
cache from FROM on where both give a prediction. That is where they compete
on the page: context.score() asks one of them for every same-league fixture.

  ratings   scoremodels.TeamGoals with context's live settings (SCORE_KIND,
            SCORE_HALF_LIFE, SCORE_RIDGE), refitted before each week on every
            competitive result before it, as context._score_model() fits on
            everything before now.
  style     context.open_mu_from_features on teamstyle.State features taken
            before each match is added (the same features it was trained on,
            known before kick-off), both sides' goals independent Poisson, as
            open_eval.py and the page turn them into a scoreline grid. Its
            trees are fixed; they were fitted on fmodel's split, whose
            out-of-sample period starts in July 2026, hence FROM.

Scored by log loss on the exact score (the cell of the 11 x 11 grid that
happened, goals over 10 folded into the last cell) and on the 90-minute 1X2,
with 95% intervals resampling matches, overall and month by month. Writes
nothing.
"""

from __future__ import annotations

import argparse
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
WEEK = 7 * 86400


def _ll(p: float) -> float:
    return -math.log(max(p, 1e-12))


def cell(grid, hg: int, ag: int) -> float:
    n = grid.shape[0] - 1
    return float(grid[min(hg, n), min(ag, n)])


def outcome_ll(grid, hg: int, ag: int) -> float:
    import scoremodels
    ph, pd_, pa = scoremodels.outcome_probs(grid)
    return _ll(ph if hg > ag else pa if hg < ag else pd_)


def rows(cache: Path, start: float, log=print) -> list[dict]:
    import context
    import scoremodels
    import strength
    import teamstyle

    events = {e["id"]: e for e in strength.load_events(cache)}
    results = [{"home": e["home"], "away": e["away"], "hg": e["hg"], "ag": e["ag"], "ts": e["ts"]}
               for e in events.values()
               if e["kind"] != "friendly" and e["home"] is not None and e["away"] is not None
               and e["hg"] is not None and e["ag"] is not None]
    fits = {}

    def ratings(ts):
        week = int(ts // WEEK)
        if week not in fits:
            before = [r for r in results if r["ts"] < week * WEEK]
            fits[week] = scoremodels.TeamGoals(context.SCORE_KIND, context.SCORE_HALF_LIFE,
                                               context.SCORE_RIDGE).fit(before, week * WEEK)
        return fits[week]

    S = teamstyle.State()
    out = []
    counts = defaultdict(int)
    for m in teamstyle.load(cache):
        e = events.get(m["match"])
        if (m["ts"] >= start and e is not None and e["kind"] == "league"
                and m["hg"] is not None and m["ag"] is not None):
            counts["league matches"] += 1
            xh = S.features_for(m["home"], m["away"], True, m["form"][0], m["form"][1])
            xa = S.features_for(m["away"], m["home"], False, m["form"][1], m["form"][0])
            lh, la = context.open_mu_from_features(xh, True), context.open_mu_from_features(xa, False)
            R = ratings(m["ts"])
            have_s = bool(lh and la)
            have_r = R.knows(m["home"]) and R.knows(m["away"])
            counts["style has a prediction"] += have_s
            counts["ratings have a prediction"] += have_r
            if have_s and have_r:
                gs = scoremodels.poisson_grid(lh, la)
                gr = R.grid(m["home"], m["away"])
                hg, ag = int(m["hg"]), int(m["ag"])
                out.append({"match": m["match"], "ts": m["ts"], "tid": e["tid"], "comp": e["comp"],
                            "month": datetime.fromtimestamp(m["ts"], timezone.utc).strftime("%Y-%m"),
                            "score_ratings": _ll(cell(gr, hg, ag)), "score_style": _ll(cell(gs, hg, ag)),
                            "x12_ratings": outcome_ll(gr, hg, ag), "x12_style": outcome_ll(gs, hg, ag)})
        S.add(m, keep_rows=False)
    log(", ".join(f"{k}: {v}" for k, v in counts.items()) + f", both: {len(out)}")
    return out


def paired(rows_, a: str, b: str, n_boot: int = 2000, seed: int = 20261024):
    """Mean of a minus b (negative: a scored better) with a 95% interval."""
    d = np.array([r[a] - r[b] for r in rows_])
    if len(d) < 2:
        return float(d.mean()) if len(d) else None, None, None
    rng = np.random.default_rng(seed)
    boot = d[rng.integers(0, len(d), size=(n_boot, len(d)))].mean(1)
    return float(d.mean()), float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))


def table(rs: list[dict]) -> str:
    head = ("| Matches | When | Score LL ratings | Score LL style | Ratings minus style (95%) "
            "| 1X2 LL ratings | 1X2 LL style | Ratings minus style (95%) |")
    out = [head, "|" + "---|" * 2 + "---:|" * 6]
    groups = [("all", rs)] + [(m, [r for r in rs if r["month"] == m]) for m in sorted({r["month"] for r in rs})]
    for label, g in groups:
        if not g:
            continue
        s = paired(g, "score_ratings", "score_style")
        x = paired(g, "x12_ratings", "x12_style")
        mean = lambda k: sum(r[k] for r in g) / len(g)  # noqa: E731
        iv = lambda t: f"{t[0]:+.4f} ({t[1]:+.4f} to {t[2]:+.4f})" if t[1] is not None else f"{t[0]:+.4f}"  # noqa: E731
        out.append(f"| {len(g)} | {label} | {mean('score_ratings'):.4f} | {mean('score_style'):.4f} | {iv(s)} "
                   f"| {mean('x12_ratings'):.4f} | {mean('x12_style'):.4f} | {iv(x)} |")
    return "\n".join(out)


def main(argv=None):
    a = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    a.add_argument("--cache", default=str(HERE / "cache"))
    a.add_argument("--from", dest="start", default="2026-07-01")
    args = a.parse_args(argv)
    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    rs = rows(Path(args.cache), start)
    print(table(rs))
    REPORT = {17, 18, 8, 23, 35, 34, 242, 325}
    rep = [r for r in rs if r["tid"] in REPORT]
    print(f"\nThe site's own leagues only ({len(rep)} matches):\n")
    print(table(rep))


if __name__ == "__main__":
    main()
