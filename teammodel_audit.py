#!/usr/bin/env python3
"""
Week-by-week audit of teammodel_train.py --weekly over the cached history.

    python teammodel_audit.py --cache cache --out teammodel_audit.json

Replays the Monday job as it would have run: at each Monday 05:34 UTC only
matches that had finished are known, the weekly rule updates (or keeps) each
stat's model, and the model in force is then scored on the following seven
days, which nobody had seen. Four paths per stat:

  frozen    the starting full fit, never touched again
  as_run    the weekly rule as it shipped, run as the Mac ran it: its
            halving step raised, ending that week's run for the stat and
            every stat after it in meta.json order
  shipped   the same rule as intended (the crash mended, nothing else)
  fixed     teammodel_train.weekly_step, the rule as it is now
  refit     a full refit from scratch every week (early stopping on the last
            90 days, then refitted on everything known)

Two starting points: "A" is the production one (train before 1 April 2026,
validate April to June, weekly from July) and "B" starts in December 2025 so
the rule runs for 46 weeks. Scenario "B-bad" corrupts one week of cached
statistics (every count doubled, a plausible feed fault) to see whether the
rule locks a bad week in; it is still scored on the true counts.

Needs lightgbm, numpy, pandas, scipy (like teammodel_train.py).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import teammodel_train as T  # noqa: E402

DAY = 86400
WEEK = 7 * DAY
REFIT_VAL_DAYS = 90
# Monday 05:34 UTC, when football-models-weekly-mac runs; a match counts as
# known once it kicked off three hours before.
RUN_OFFSET = 5 * 3600 + 34 * 60
FINISHED = 3 * 3600

SCENARIOS = {
    "A": dict(train_end="2026-04-01", val_end="2026-07-01", first="2026-07-06", last="2026-10-12"),
    "B": dict(train_end="2025-10-01", val_end="2025-12-01", first="2025-12-01", last="2026-10-12"),
    "B-bad": dict(train_end="2025-10-01", val_end="2025-12-01", first="2025-12-01", last="2026-10-12",
                  bad_week="2026-02-09"),
}


def shipped_step(lgb, old, Xtr, ytr, wtr, Xh, yh, own_h, alpha, as_run=True):
    """The weekly rule exactly as it shipped (teammodel_train.weekly before this
    audit). as_run=True keeps its reuse of the Dataset for the halving, which
    raises LightGBMError on LightGBM 4; as_run=False gives it a fresh Dataset,
    i.e. the shipped rule as intended (slack of 1e-4, halved model untested)."""
    d = lgb.Dataset(Xtr, ytr, weight=wtr)
    new = lgb.train(T.WEEKLY, d, T.WEEKLY_TREES, init_model=old, keep_training_booster=True)
    mo, mn = old.predict(Xh), new.predict(Xh)
    llo, lln = T.tail_ll(yh, mo, own_h, alpha), T.tail_ll(yh, mn, own_h, alpha)
    shift = float(np.mean(np.abs(mn - mo) / np.maximum(mo, 1e-6)))
    if lln > llo + 1e-4:
        return None, {"decision": "rejected", "before": llo, "after": lln, "shift": shift}
    halved = False
    if shift > T.MAX_SHIFT:
        if not as_run:
            d = lgb.Dataset(Xtr, ytr, weight=wtr)
        new = lgb.train(dict(T.WEEKLY, learning_rate=T.WEEKLY["learning_rate"] / 2), d, T.WEEKLY_TREES,
                        init_model=old, keep_training_booster=True)
        halved = True
    mf = new.predict(Xh)
    return new, {"decision": "adopted", "before": llo, "after": lln, "shift": shift, "halved": halved,
                 "adopted_score": T.tail_ll(yh, mf, own_h, alpha),
                 "adopted_shift": float(np.mean(np.abs(mf - mo) / np.maximum(mo, 1e-6)))}


def fixed_step(lgb, old, Xtr, ytr, wtr, Xh, yh, own_h, alpha):
    new, rep = T.weekly_step(lgb, old, Xtr, ytr, wtr, Xh, yh, own_h, alpha)
    return new, dict(rep, decision="rejected" if new is None else "adopted")


STEPS = {"as_run": lambda *a: shipped_step(*a, as_run=True),
         "shipped": lambda *a: shipped_step(*a, as_run=False),
         "fixed": fixed_step}
PATHS = ("frozen", "as_run", "shipped", "fixed", "refit")


def full_fit(lgb, X, y, f, tr, va):
    """teammodel_train.full for one stat: early stop on va, refit on tr | va."""
    dtr = lgb.Dataset(X.loc[tr, f], y[tr])
    dva = lgb.Dataset(X.loc[va, f], y[va], reference=dtr)
    m = lgb.train(T.PARAMS, dtr, 3000, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])
    both = tr | va
    m2 = lgb.train(T.PARAMS, lgb.Dataset(X.loc[both, f], y[both]), m.best_iteration or 200)
    return m2, T.alpha_of(y[both], m2.predict(X.loc[both, f]))


def mondays(first, last):
    t = pd.Timestamp(first).timestamp() + RUN_OFFSET
    end = pd.Timestamp(last).timestamp() + RUN_OFFSET
    while t <= end:
        yield t
        t += WEEK


class Stat:
    """One stat's rows and its models along each path."""

    def __init__(self, lgb, R, s, sc):
        X = R[R["own_" + s].notna() & R["opp_conc_" + s].notna() & R["y_" + s].notna()].reset_index(drop=True)
        self.s, self.X, self.f = s, X, T.feats_for(X, s)
        self.y_true = X["y_" + s].astype(float).values
        self.y_seen = self.y_true.copy()
        if sc.get("bad_week"):
            b0 = pd.Timestamp(sc["bad_week"]).timestamp()
            self.y_seen[((X.ts >= b0) & (X.ts < b0 + WEEK)).values] *= 2
        self.ts, self.own = X.ts.values, X["own_" + s].values
        tr = self.ts < pd.Timestamp(sc["train_end"]).timestamp()
        va = ~tr & (self.ts < pd.Timestamp(sc["val_end"]).timestamp())
        self.m0, self.a0 = full_fit(lgb, X, self.y_seen, self.f, tr, va)
        self.m = {p: self.m0 for p in STEPS}
        self.weeks = []

    def F(self, mask):
        return self.X.loc[mask, self.f]


def run_scenario(args):
    rows_path, stats, name = args
    import lightgbm as lgb
    sc = SCENARIOS[name]
    R = pd.read_pickle(rows_path)
    st = [Stat(lgb, R, s, sc) for s in stats]
    for t in mondays(sc["first"], sc["last"]):
        crashed = False  # as_run: the first crash ends that week's run for every later stat
        for S in st:
            ts = S.ts
            known = ts < t - FINISHED
            nxt = (ts >= t) & (ts < t + WEEK)
            now = ts[known].max()
            hold = known & (ts >= now - T.HOLDOUT_DAYS * DAY)
            trn = known & ~hold
            w = np.power(0.5, (now - ts) / DAY / T.HALF_LIFE_DAYS)
            wk = {"t": int(t), "n_next": int(nxt.sum()), "n_hold": int(hold.sum())}
            for p, step in STEPS.items():
                if hold.sum() < 50 or trn.sum() < 500:
                    wk[p] = {"decision": "too few"}
                    continue
                if p == "as_run" and crashed:
                    wk[p] = {"decision": "skipped (earlier stat crashed)"}
                    continue
                args_ = (lgb, S.m[p], S.F(trn), S.y_seen[trn], w[trn], S.F(hold), S.y_seen[hold], S.own[hold], S.a0)
                try:
                    new, info = step(*args_)
                except lgb.basic.LightGBMError as exc:
                    crashed = True
                    wk[p] = {"decision": "crashed", "error": str(exc)[:80]}
                    continue
                if p != "as_run" and nxt.sum():
                    # what the other choice would have scored on the next week
                    alt = new if new is not None else T.weekly_candidate(lgb, S.m[p], *args_[2:6])[0]
                    info["alt_next"] = T.tail_ll(S.y_true[nxt], alt.predict(S.F(nxt)), S.own[nxt], S.a0)
                    info["old_next"] = T.tail_ll(S.y_true[nxt], S.m[p].predict(S.F(nxt)), S.own[nxt], S.a0)
                if new is not None:
                    S.m[p] = new
                wk[p] = info
            rv = known & (ts >= t - REFIT_VAL_DAYS * DAY)
            mr, ar = full_fit(lgb, S.X, S.y_seen, S.f, known & ~rv, rv)
            if nxt.sum():
                models = {"frozen": (S.m0, S.a0), "refit": (mr, ar), **{p: (S.m[p], S.a0) for p in STEPS}}
                lr = np.log(mr.predict(S.F(nxt)))
                wk["next"] = {}
                for p, (m, a) in models.items():
                    mu = m.predict(S.F(nxt))
                    wk["next"][p] = {"tail_ll": T.tail_ll(S.y_true[nxt], mu, S.own[nxt], a),
                                     "calib": float(mu.mean() / max(1e-9, S.y_true[nxt].mean())),
                                     "trees": m.num_trees(), "dist_to_refit": float(np.mean(np.abs(np.log(mu) - lr)))}
            S.weeks.append(wk)
        print(name, pd.Timestamp(t, unit="s").date(), flush=True)
    return [{"scenario": name, "stat": S.s, "weeks": S.weeks} for S in st]


def gbm_stats(meta_path):
    meta = json.loads(Path(meta_path).read_text())
    return [s for s, e in meta["stats"].items() if e.get("use") == "gbm"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="cache")
    ap.add_argument("--rows", help="pickle of teammodel_train.rows(cache), to skip the replay")
    ap.add_argument("--meta", default="teammodel/meta.json")
    ap.add_argument("--scenarios", default="A,B,B-bad")
    ap.add_argument("--out", default="teammodel_audit.json")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args(argv)
    rows_path = a.rows
    if not rows_path:
        rows_path = str(Path(a.out).with_suffix(".rows.pkl"))
        T.rows(a.cache).to_pickle(rows_path)
    # meta order matters: the shipped run stopped at its first crash
    work = [(rows_path, gbm_stats(a.meta), n) for n in a.scenarios.split(",")]
    t0 = time.time()
    with ProcessPoolExecutor(a.jobs) as ex:
        res = [r for rs in ex.map(run_scenario, work) for r in rs]
    Path(a.out).write_text(json.dumps(res))
    print(f"{len(res)} runs in {time.time() - t0:.0f}s -> {a.out}")


if __name__ == "__main__":
    main()
