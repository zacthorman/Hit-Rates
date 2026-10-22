"""Backtest the NBA / NFL player model against the site's current one.

    python3 evaluate_us.py nba|nfl ablate     # feature groups, one at a time (validation picks)
    python3 evaluate_us.py nba|nfl auto       # final fit with the chosen groups, out-of-sample report

Same method as the football model (fmodel/training/evaluate.py):
  train       fit the trees
  validation  early stopping, which feature groups to keep, the spread around
              the prediction, and the final calibration
  oos         never touched until the report: the honest number

A US prop is an over/under at a line that moves with the player, so the
model predicts his expected number (LightGBM, Poisson) and the spread around
it is fitted on validation (negative binomial for counts, the empirical
ratio for yards). That gives a chance for any line. Scored at three lines per
player-game, built only from his own earlier games the way a bookmaker's
would be: his last-10 median, and 30% either side of it (the ladder rungs).

Baseline "site": model.price_player on his last 20 games, exactly what the
page quotes today. "site_fair": the same recalibrated on train, so that a
calibration fix alone is not counted as the new model's gain.
"""
import json
import math
import sys
import warnings
from collections import defaultdict

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy import stats as sst
from sklearn.linear_model import LogisticRegression

warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/claude/usbt/src")
import model  # noqa: E402

D = "/home/claude/usbt/data"
SPORT, MODE = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "auto")
SITE_SPORT = {"nba": "basketball", "nfl": "american-football"}[SPORT]

# Which rows are a market for each target: position and a floor on his median.
if SPORT == "nba":
    TARGETS = {"points": 4, "rebounds": 2, "assists": 1.5, "threes": 0.8, "steals": 0.8,
               "blocks": 0.8, "turnovers": 0.8, "pra": 8, "pr": 6, "pa": 6, "ra": 3}
    POS = {}
    YARDS = set()
else:
    TARGETS = {"pass_yds": 120, "pass_cmp": 10, "pass_att": 15, "pass_td": 0.5, "rush_yds": 15,
               "rush_att": 5, "rec_yds": 15, "rec": 1.5, "rush_rec_yds": 20, "pass_rush_yds": 140,
               "tackles": 2.5, "td": 0}
    POS = {"pass_yds": {"QB"}, "pass_cmp": {"QB"}, "pass_att": {"QB"}, "pass_td": {"QB"},
           "pass_rush_yds": {"QB"}, "rush_yds": {"RB", "QB"}, "rush_att": {"RB", "QB"},
           "rec_yds": {"WR", "TE", "RB"}, "rec": {"WR", "TE", "RB"}, "rush_rec_yds": {"RB", "WR"},
           "tackles": {"LB", "DB", "DL"}, "td": {"RB", "WR", "TE"}}
    YARDS = {"pass_yds", "rush_yds", "rec_yds", "rush_rec_yds", "pass_rush_yds"}

F = pd.read_parquet(f"{D}/{SPORT}_features.parquet").sort_values("ts").reset_index(drop=True)
P = pd.read_parquet(f"{D}/{SPORT}_players.parquet")

# Splits by date. Set for the full seasons; until the backfill lands the NBA
# file only covers March to June 2026, so it falls back to 60/20/20 by time.
if SPORT == "nfl":
    TRAIN_END, VAL_END = pd.Timestamp("2025-09-01").timestamp(), pd.Timestamp("2025-12-01").timestamp()
else:
    TRAIN_END, VAL_END = pd.Timestamp("2026-02-01").timestamp(), pd.Timestamp("2026-04-01").timestamp()
    if (F.ts < TRAIN_END).mean() < 0.3:
        TRAIN_END, VAL_END = F.ts.quantile(0.6), F.ts.quantile(0.8)
F["split"] = np.where(F.ts < TRAIN_END, "train", np.where(F.ts < VAL_END, "val", "oos"))

ID = {"match", "ts", "pid", "name", "team", "opp", "pos", "season", "split"}
POS_CODES = {p: i for i, p in enumerate(sorted(F.pos.dropna().unique()))}
F["pos_c"] = F.pos.map(POS_CODES).fillna(-1)
cols = [c for c in F.columns if c not in ID and not c.startswith(("y_", "line_"))]
G = {
    "form": [c for c in cols if c.endswith(("_m3", "_m5", "_m10", "_m20", "_ew", "_sd10", "_med10", "_p36"))
             and not c.startswith(("t_", "ot_", "oc_", "miss_", "h2h_"))]
            + ["n", "days_rest", "start_rate", "b2b", "home", "starter", "pos_c", "playoff"],
    "team_style": [c for c in cols if c.startswith("t_")],
    "opp_style": [c for c in cols if c.startswith("ot_")],
    "strength": ["elo_me", "elo_op", "elo_diff"],
    "pos_concession": [c for c in cols if c.startswith("oc_")],
    "partners": [c for c in cols if c.startswith("miss_")],
    "h2h": [c for c in cols if c.startswith("h2h_")],
}
G = {k: [c for c in v if c in F.columns] for k, v in G.items()}
ORDER = list(G)
PARAMS = dict(objective="poisson", learning_rate=0.03, num_leaves=15, min_data_in_leaf=100,
              feature_fraction=0.7, bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0,
              verbose=-1, seed=7)


# ------------------------------------------------------------------ lines

def lines_for(s):
    """Three lines per row from his own earlier games: median, and 30% either side."""
    med = F[f"{s}_med10"].astype(float)
    if s == "td":
        return [pd.Series(0.5, index=F.index)]
    base = np.floor(med) + 0.5
    lo = np.maximum(0.5, np.floor(med * 0.7) + 0.5)
    hi = np.floor(med * 1.3) + 0.5
    if s in YARDS:
        base, lo, hi = np.floor(med) + 0.5, np.floor(med * 0.75) + 0.5, np.floor(med * 1.25) + 0.5
    return [base, lo, hi]


def eligible(s):
    ok = F[f"{s}_med10"].astype(float) >= TARGETS[s]
    if s == "td":
        ok = F["rec_m10"].astype(float) + F["rush_att_m10"].astype(float) >= 3
    if POS.get(s):
        ok &= F.pos.isin(POS[s])
    return ok & F[f"y_{s}"].notna()


# ------------------------------------------------------------------ baseline

def site_probs():
    """model.price_player on his last 20 games, per (row, target, line)."""
    mm = model.min_minutes_for(SITE_SPORT) if SPORT == "nba" else 0
    Pp = P[(P.mins > 0) if SPORT == "nba" else (P.has_stats == 1)].sort_values("ts")
    if SPORT == "nfl":
        Pp = Pp.assign(mins=60.0, td=Pp.rush_td + Pp.rec_td)
    hist = defaultdict(list)
    by_key = {}
    want = set(zip(F.match, F.pid))
    for r in Pp.itertuples(index=False):
        if (r.match, r.pid) in want:
            by_key[(r.match, r.pid)] = list(hist[r.pid][-20:])
        if r.mins >= mm:
            hist[r.pid].append(r)
    out = {}
    for s in TARGETS:
        ok = eligible(s)
        for li, L in enumerate(lines_for(s)):
            vals = np.full(len(F), np.nan)
            for i in np.where(ok)[0]:
                prev = by_key.get((F.match[i], F.pid[i]))
                if not prev or len(prev) < 3:
                    continue
                apps = [{"value": float(getattr(x, s)), "minutes": float(x.mins)} for x in prev]
                try:
                    vals[i] = model.price_player(apps, float(L[i]), True, 1.0, None, SITE_SPORT)["p"]
                except Exception:
                    pass
            out[(s, li)] = vals
    return out


# ------------------------------------------------------------------ model

BASE = {}  # target -> column the model scales: his own weighted average


def base_of(s, mask=None):
    """The player's exponentially weighted average for this market, floored.
    Trees cannot extrapolate: modelled raw, Wembanyama's blocks came out at
    1.2 against a usual 3.7 because no leaf holds enough players like him.
    Modelled as a multiple of his own number (a Poisson offset), the trees
    only learn the adjustments. 21 Oct 2026."""
    col = f"{s}_ew"
    v = np.clip(F[col].astype(float).fillna(0).values, 0.05, None)
    return v if mask is None else v[mask]


CUR = {"s": None}


def fit(feats, y, tr, va):
    s = CUR["s"]
    dtr = lgb.Dataset(F.loc[tr, feats], y[tr], init_score=np.log(base_of(s, tr)))
    dva = lgb.Dataset(F.loc[va, feats], y[va], init_score=np.log(base_of(s, va)), reference=dtr)
    m = lgb.train(PARAMS, dtr, 3000, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])
    m._us_target = s
    return m


def predict(m, mask, feats):
    """Expected number: his own average times exp(the trees)."""
    return base_of(m._us_target, mask) * np.exp(m.predict(F.loc[mask, feats], raw_score=True))


def poisson_dev(y, mu):
    mu = np.clip(mu, 1e-6, None)
    return float(np.mean(2 * (np.where(y > 0, y * np.log(np.where(y > 0, y, 1) / mu), 0) - (y - mu))))


class Spread:
    """P(Y > line) around a predicted mean, fitted on validation residuals."""

    def __init__(self, y, mu, yards):
        self.yards = yards
        if yards:
            r = y / np.clip(mu, 1e-6, None)
            q = np.quantile(mu, [0, .25, .5, .75, 1])
            self.edges = q
            self.ratios = [r[(mu >= q[i]) & (mu <= q[i + 1])] for i in range(4)]
        else:
            # negative binomial size by maximum likelihood (one per target), or
            # binomial-like if underdispersed: then fall back to Poisson
            best, bestll = None, -np.inf
            for size in [0.5, 1, 2, 3, 5, 8, 12, 20, 35, 60, 100, 1e4]:
                p = size / (size + mu)
                ll = sst.nbinom.logpmf(y, size, p).sum()
                if ll > bestll:
                    best, bestll = size, ll
            self.size = best

    def p_over(self, mu, line):
        if self.yards:
            out = np.empty(len(mu))
            for i, (m, L) in enumerate(zip(mu, line)):
                b = min(3, max(0, np.searchsorted(self.edges, m) - 1))
                out[i] = np.mean(m * self.ratios[b] > L)
            return out
        k = np.floor(line)
        p = self.size / (self.size + mu)
        return 1 - sst.nbinom.cdf(k, self.size, p)


def ll(y, p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def platt(p_tr, y_tr):
    lo = lambda q: np.log(np.clip(q, 1e-4, 1 - 1e-4) / (1 - np.clip(q, 1e-4, 1 - 1e-4)))
    m = LogisticRegression(C=1e6).fit(lo(p_tr).reshape(-1, 1), y_tr)
    return lambda q: m.predict_proba(lo(q).reshape(-1, 1))[:, 1]


def run():
    site = site_probs()
    res, preds, imps = [], [], {}
    chosen = json.load(open(f"{D}/{SPORT}_groups.json")) if MODE == "auto" else {}
    for s in TARGETS:
        CUR["s"] = s
        ok = eligible(s).values
        y = np.clip(F[f"y_{s}"].astype(float).values, 0, None)
        tr, va, te = ok & (F.split == "train").values, ok & (F.split == "val").values, ok & (F.split == "oos").values
        if tr.sum() < 300 or va.sum() < 100 or te.sum() < 100:
            print(json.dumps({"target": s, "skipped": "too few rows", "n": [int(tr.sum()), int(va.sum()), int(te.sum())]}))
            continue
        row = {"target": s, "n_train": int(tr.sum()), "n_val": int(va.sum()), "n_oos": int(te.sum())}
        if MODE == "ablate":
            feats = []
            for g in ORDER:
                feats = feats + G[g]
                m = fit(feats, y, tr, va)
                row["val+" + g] = poisson_dev(y[va], predict(m, va, feats))
            res.append(row)
            print(json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items()}), flush=True)
            continue
        # Settings chosen on validation deviance only: feature groups (the
        # ablation pick or everything) and tree shape.
        best = None
        global PARAMS
        base = dict(PARAMS)
        for gs in (chosen.get(s, ORDER), ORDER):
            feats_ = sum((G[g] for g in gs), [])
            for nl, md in ((7, 50), (15, 100), (31, 200), (15, 300)):
                PARAMS = dict(base, num_leaves=nl, min_data_in_leaf=md)
                m_ = fit(feats_, y, tr, va)
                dv = poisson_dev(y[va], predict(m_, va, feats_))
                if best is None or dv < best[0]:
                    best = (dv, gs, feats_, m_, (nl, md))
        PARAMS = base
        _, gs, feats, m, shape = best
        row["shape"] = f"leaves {shape[0]} min {shape[1]}"
        mu_va, mu_te = predict(m, va, feats), predict(m, te, feats)
        sp = Spread(y[va], mu_va, s in YARDS)
        row["groups"] = "+".join(gs)
        row["dev_new"] = poisson_dev(y[te], mu_te)
        row["dev_m10"] = poisson_dev(y[te], np.clip(F.loc[te, f"{s}_m10"].values, 0.05, None))
        # chances at the three lines, calibrated on validation
        allv = {"new": [], "site": [], "site_fair": [], "blend": [], "y": []}
        for li, L in enumerate(lines_for(s)):
            Lv, Lt = L.values[va], L.values[te]
            pv, pt = sp.p_over(mu_va, Lv), sp.p_over(mu_te, Lt)
            yv, yt = (y[va] > Lv).astype(int), (y[te] > Lt).astype(int)
            cal = platt(pv, yv)
            pv_c, pt = cal(pv), cal(pt)
            sv, stt = site[(s, li)][va], site[(s, li)][te]
            okv, okt = ~np.isnan(sv), ~np.isnan(stt)
            trs = tr & ~np.isnan(site[(s, li)])
            sf = platt(site[(s, li)][trs], (y[trs] > L.values[trs]).astype(int))
            # the blend: logistic regression on both log-odds, fitted on validation
            lo = lambda q: np.log(np.clip(q, 1e-4, 1 - 1e-4) / (1 - np.clip(q, 1e-4, 1 - 1e-4)))
            Xv = np.c_[lo(pv_c[okv]), lo(sf(sv[okv]))]
            bl = LogisticRegression(C=1.0).fit(Xv, yv[okv])
            pb = bl.predict_proba(np.c_[lo(pt[okt]), lo(sf(stt[okt]))])[:, 1]
            allv["new"].append(pt[okt]); allv["site"].append(stt[okt]); allv["site_fair"].append(sf(stt[okt]))
            allv["blend"].append(pb)
            allv["y"].append(yt[okt])
            idx = np.where(te)[0][okt]
            preds.append(pd.DataFrame({"row": idx, "target": s, "line": Lt[okt], "y": yt[okt],
                                       "p_new": pt[okt], "p_site": stt[okt], "p_site_fair": sf(stt[okt]),
                                       "p_blend": pb, "mu": mu_te[okt], "rung": li}))
        yy = np.concatenate(allv["y"])
        for k in ("new", "site", "site_fair", "blend"):
            pp = np.concatenate(allv[k])
            row["ll_" + k] = ll(yy, pp)
            row["brier_" + k] = float(np.mean((pp - yy) ** 2))
        row["ll_coin"] = ll(yy, np.full(len(yy), yy.mean()))
        row["n_lines"] = int(len(yy))
        imp = pd.Series(m.feature_importance("gain"), index=feats)
        imps[s] = (imp / imp.sum()).sort_values(ascending=False).head(12).round(3).to_dict()
        res.append(row)
        print(json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items()}), flush=True)
    if MODE == "ablate":
        R = res
        chosen = {}
        for r in R:
            keep = ["form"]
            for i, g in enumerate(ORDER[1:], 1):
                if r["val+" + ORDER[i - 1]] - r["val+" + g] > 0:
                    keep.append(g)
            chosen[r["target"]] = keep
        json.dump(chosen, open(f"{D}/{SPORT}_groups.json", "w"), indent=1)
        print("chosen", json.dumps(chosen))
    else:
        pd.DataFrame(res).to_csv(f"{D}/{SPORT}_results.csv", index=False)
        pd.concat(preds).to_parquet(f"{D}/{SPORT}_oos_preds.parquet")
        json.dump(imps, open(f"{D}/{SPORT}_importance.json", "w"), indent=1)


if __name__ == "__main__":
    run()
