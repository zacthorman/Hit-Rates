#!/usr/bin/env python3
"""
Train, test and export the team-stats model (teamstyle.py features).

    python teammodel_train.py --cache cache --out teammodel           # full fit, split as below
    python teammodel_train.py --cache cache --out teammodel --weekly  # small-step weekly update

Needs lightgbm, numpy, pandas, scipy, statsmodels (the Mac page does not:
it scores the exported trees with fmodel/fmodel_trees.py).

Full fit: per stat, LightGBM (Poisson) on every teamstyle.py feature against
the linear model gs_backtest.py fitted (own, opponent concedes, home, ball).
Train before 1 April 2026, choose on April to June, score from 1 July. The
winner on validation is refitted on train plus validation and exported.

Weekly (--weekly): continue each kept model from its saved booster with a
few trees at a low learning rate on recency-weighted data, score old and new
on the latest three weeks (which the update did not train on), and adopt the
new one only if it is no worse. A chance moving by more than MAX_SHIFT on
average is pulled halfway back, and every week is written to CHANGELOG.md.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import probability  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import teamstyle as TS  # noqa: E402

TRAIN_END = pd.Timestamp("2026-04-01").timestamp()
VAL_END = pd.Timestamp("2026-07-01").timestamp()
PARAMS = dict(objective="poisson", learning_rate=0.03, num_leaves=15, min_data_in_leaf=100,
              feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0, verbose=-1, seed=7)
WEEKLY = dict(PARAMS, learning_rate=0.01)
WEEKLY_TREES = 40
HALF_LIFE_DAYS = 120
HOLDOUT_DAYS = 21
MAX_SHIFT = 0.03


def slug(s):
    return s.lower().replace(" ", "_")


def feats_for(R, s):
    base = ["own_" + s, "opp_conc_" + s, "home"]
    rest = [c for c in R.columns if c.startswith(("tk_", "ok_", "x_", "own_", "conc_", "opp_own_", "opp_conc_"))
            or c in ("elo_diff", "n")]
    return base + [c for c in rest if c not in base]


def lin_X(Z, s):
    return np.column_stack([np.ones(len(Z)), np.log(np.clip(Z["own_" + s], .05, None)),
                            np.log(np.clip(Z["opp_conc_" + s], .05, None)), Z.home,
                            np.log(np.clip(Z.x_ball.fillna(1), .5, 2))])


alpha_of = probability.nb_alpha


def tail_ll(y, mu, own, a):
    from scipy.stats import nbinom, poisson
    k = np.floor(own).astype(int) + 1
    if a < 1e-6:
        p = poisson.sf(k - 1, mu)
    else:
        r = 1 / a
        p = nbinom.sf(k - 1, r, r / (r + mu))
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return float(-np.mean(np.where(y >= k, np.log(p), np.log(1 - p))))


def rows(cache):
    S = TS.State.from_cache(Path(cache))
    R = pd.DataFrame(S.rows)
    R["split"] = np.where(R.ts < TRAIN_END, "train", np.where(R.ts < VAL_END, "val", "oos"))
    return R


def full(cache, out):
    import lightgbm as lgb
    import statsmodels.api as sm
    R = rows(cache)
    out.mkdir(parents=True, exist_ok=True)
    meta = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rows": len(R), "stats": {}}
    for s in TS.STATS:
        X = R[R["own_" + s].notna() & R["opp_conc_" + s].notna() & R["y_" + s].notna()]
        y = X["y_" + s].astype(float).values
        tr, va, te = [(X.split == z).values for z in ("train", "val", "oos")]
        if tr.sum() < 500 or te.sum() < 200:
            continue
        glm = sm.GLM(y[tr], lin_X(X[tr], s), family=sm.families.Poisson()).fit()
        mu_l = {z: glm.predict(lin_X(X[m], s)) for z, m in (("tr", tr), ("va", va), ("te", te))}
        f = feats_for(X, s)
        dtr = lgb.Dataset(X.loc[tr, f], y[tr]); dva = lgb.Dataset(X.loc[va, f], y[va], reference=dtr)
        m = lgb.train(PARAMS, dtr, 3000, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])
        mu_g = {"tr": m.predict(X.loc[tr, f]), "va": m.predict(X.loc[va, f]), "te": m.predict(X.loc[te, f])}
        res = {}
        for name, mu in (("linear", mu_l), ("gbm", mu_g)):
            a = alpha_of(y[tr], mu["tr"])
            res[name] = {"alpha": a, "val": tail_ll(y[va], mu["va"], X.loc[va, "own_" + s].values, a),
                         "oos": tail_ll(y[te], mu["te"], X.loc[te, "own_" + s].values, a)}
        use = "gbm" if res["gbm"]["val"] < res["linear"]["val"] else "linear"
        # refit the chosen one on train + validation, for the page
        trva = tr | va
        glm2 = sm.GLM(y[trva], lin_X(X[trva], s), family=sm.families.Poisson()).fit()
        entry = {"use": use, "linear": [float(c) for c in glm2.params],
                 "alpha_linear": alpha_of(y[trva], glm2.predict(lin_X(X[trva], s))),
                 "val": {k: v["val"] for k, v in res.items()}, "oos": {k: v["oos"] for k, v in res.items()},
                 "n_oos": int(te.sum())}
        if use == "gbm":
            d2 = lgb.Dataset(X.loc[trva, f], y[trva])
            m2 = lgb.train(PARAMS, d2, m.best_iteration or 200)
            entry.update({"features": f, "alpha_gbm": alpha_of(y[trva], m2.predict(X.loc[trva, f])),
                          "trees": m2.num_trees()})
            m2.save_model(str(out / f"{slug(s)}.txt"))
            with gzip.open(out / f"{slug(s)}.json.gz", "wt") as fh:
                json.dump(m2.dump_model(), fh)
        meta["stats"][s] = entry
        print(json.dumps({"stat": s, "use": use, "val": entry["val"], "oos": entry["oos"]}), flush=True)
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    log = out / "CHANGELOG.md"
    lines = [f"\n## {meta['generated'][:10]}: full fit\n"]
    for s, e in meta["stats"].items():
        lines.append(f"- {s}: {e['use']} (out of sample: linear {e['oos']['linear']:.4f}, "
                     f"tactics model {e['oos']['gbm']:.4f})")
    with open(log, "a") as fh:
        fh.write("\n".join(lines) + "\n")


def weekly(cache, out):
    import lightgbm as lgb
    R = rows(cache)
    meta = json.loads((out / "meta.json").read_text())
    now = R.ts.max()
    hold = R.ts >= now - HOLDOUT_DAYS * 86400
    age_days = (now - R.ts) / 86400
    w = np.power(0.5, age_days / HALF_LIFE_DAYS)
    lines = [f"\n## {datetime.now(timezone.utc).strftime('%Y-%m-%d')}: weekly update\n"]
    for s, e in meta["stats"].items():
        if e.get("use") != "gbm":
            continue
        f = e["features"]
        X = R[R["own_" + s].notna() & R["opp_conc_" + s].notna() & R["y_" + s].notna()]
        y = X["y_" + s].astype(float).values
        h = hold.loc[X.index].values
        if h.sum() < 50 or (~h).sum() < 500:
            lines.append(f"- {s}: too few new matches, unchanged")
            continue
        old = lgb.Booster(model_file=str(out / f"{slug(s)}.txt"))
        d = lgb.Dataset(X.loc[~h, f], y[~h], weight=w.loc[X.index][~h].values)
        new = lgb.train(WEEKLY, d, WEEKLY_TREES, init_model=old, keep_training_booster=True)
        mo, mn = old.predict(X.loc[h, f]), new.predict(X.loc[h, f])
        a = e.get("alpha_gbm", 0.05)
        own = X.loc[h, "own_" + s].values
        llo, lln = tail_ll(y[h], mo, own, a), tail_ll(y[h], mn, own, a)
        shift = float(np.mean(np.abs(mn - mo) / np.maximum(mo, 1e-6)))
        if lln > llo + 1e-4:
            lines.append(f"- {s}: update rejected (latest {HOLDOUT_DAYS} days: {llo:.4f} before, {lln:.4f} after)")
            continue
        note = ""
        if shift > MAX_SHIFT:
            # Too big a jump for one week: keep half of it.
            new = lgb.train(dict(WEEKLY, learning_rate=WEEKLY["learning_rate"] / 2), d, WEEKLY_TREES,
                            init_model=old, keep_training_booster=True)
            note = f" (moved {shift * 100:.1f}% on average, halved)"
        new.save_model(str(out / f"{slug(s)}.txt"))
        with gzip.open(out / f"{slug(s)}.json.gz", "wt") as fh:
            json.dump(new.dump_model(), fh)
        e["trees"] = new.num_trees()
        lines.append(f"- {s}: updated, {WEEKLY_TREES} trees added{note} (latest {HOLDOUT_DAYS} days: "
                     f"{llo:.4f} before, {lln:.4f} after)")
    meta["weekly"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    with open(out / "CHANGELOG.md", "a") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="cache")
    ap.add_argument("--out", default="teammodel")
    ap.add_argument("--weekly", action="store_true")
    a = ap.parse_args(argv)
    (weekly if a.weekly else full)(a.cache, Path(a.out))


if __name__ == "__main__":
    main()
