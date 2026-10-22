"""Stress test of the NBA / NFL player models: rolling-origin backtest,
bootstrap intervals, the page's betting rule, blend checks.

    python3 audit_us.py nfl --data DIR [--cache CACHE] [--out DIR] [--boot 2000]
    python3 audit_report.py DIR/nfl_audit.json > tables.md

DIR holds {sport}_features.parquet and {sport}_players.parquet, built by
rebuild.py (usfeatures.build then usfeatures.features); --cache builds them
first from a cache folder (on the Mac: --cache cache). Needs LightGBM,
scipy, scikit-learn and pyarrow, as the rest of usmodel/training/.

What it does, per market, the way train_us.py builds the live model but
repeated at every origin instead of once:

  folds      Rolling origin. Each season is a test block (each calendar
             month when the cache holds fewer than three testable
             seasons). Everything before the block is history: its last
             quarter by date is validation (early stopping, tree shape,
             spread, Platt calibration, blend and the blend-or-model
             choice), the rest is training. The test block is touched once.
  prices     site       model.price_player on his last 20 games (the page)
             site_fair  the same recalibrated on the fold's training data
             new        the model alone, calibrated on validation
             blend      the model blended with site_fair (always)
             live       blend or model alone, chosen inside validation as
                        train_us.py chooses it: what the page would show
  scoring    log loss, Brier, calibration (said v landed, intercept and
             slope, ten-bin ECE) on three lines per player-game.
  intervals  game-level (cluster) bootstrap: every line of a resampled
             game comes with it, because lines in one game move together.
  betting    the page's "take" rule (report.py verdictOf): our chance 50%+,
             edge 5% to 30% at the price, five games or more, not stale.
             No historical bookmaker prices exist for these seasons, so the
             price is a synthetic book: site_fair with a two-way margin.

The feature list for each market is the one the live model uses
(usmodel/{sport}_meta.json), so the stress test is of the deployed design.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# ------------------------------------------------------------------ markets

TARGETS = {
    "nba": {"points": 4, "rebounds": 2, "assists": 1.5, "threes": 0.8, "steals": 0.8,
            "blocks": 0.8, "turnovers": 0.8, "pra": 8, "pr": 6, "pa": 6, "ra": 3},
    "nfl": {"pass_yds": 120, "pass_cmp": 10, "pass_att": 15, "pass_td": 0.5, "rush_yds": 15,
            "rush_att": 5, "rec_yds": 15, "rec": 1.5, "rush_rec_yds": 20, "pass_rush_yds": 140,
            "tackles": 2.5, "td": 0},
}
POS = {
    "nba": {},
    "nfl": {"pass_yds": {"QB"}, "pass_cmp": {"QB"}, "pass_att": {"QB"}, "pass_td": {"QB"},
            "pass_rush_yds": {"QB"}, "rush_yds": {"RB", "QB"}, "rush_att": {"RB", "QB"},
            "rec_yds": {"WR", "TE", "RB"}, "rec": {"WR", "TE", "RB"}, "rush_rec_yds": {"RB", "WR"},
            "tackles": {"LB", "DB", "DL"}, "td": {"RB", "WR", "TE"}},
}
YARDS = {"pass_yds", "rush_yds", "rec_yds", "rush_rec_yds", "pass_rush_yds"}
SITE_SPORT = {"nba": "basketball", "nfl": "american-football"}
SHAPES = ((7, 50), (15, 100), (31, 200), (15, 300))
PARAMS = dict(objective="poisson", learning_rate=0.03, num_leaves=15, min_data_in_leaf=100,
              feature_fraction=0.7, bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0,
              verbose=-1, seed=7, num_threads=int(os.environ.get("AUDIT_THREADS", "0")))

# The page's take rule (report.py verdictOf, 21 Oct 2026)
RULE = dict(min_p=0.5, min_edge=0.05, max_edge=0.30, min_n=5, stale_days=60)


def lo(q):
    q = np.clip(np.asarray(q, float), 1e-4, 1 - 1e-4)
    return np.log(q / (1 - q))


def sig(z):
    return 1 / (1 + np.exp(-np.asarray(z, float)))


def lines_for(F, s):
    """Three lines per row from his own earlier games (as evaluate_us.py)."""
    med = F[f"{s}_med10"].astype(float)
    if s == "td":
        return [pd.Series(0.5, index=F.index)]
    if s in YARDS:
        return [np.floor(med) + 0.5, np.floor(med * 0.75) + 0.5, np.floor(med * 1.25) + 0.5]
    return [np.floor(med) + 0.5, np.maximum(0.5, np.floor(med * 0.7) + 0.5), np.floor(med * 1.3) + 0.5]


def eligible(F, sport, s):
    ok = F[f"{s}_med10"].astype(float) >= TARGETS[sport][s]
    if s == "td":
        ok = F["rec_m10"].astype(float) + F["rush_att_m10"].astype(float) >= 3
    if POS[sport].get(s):
        ok &= F.pos.isin(POS[sport][s])
    return ok & F[f"y_{s}"].notna()


# ------------------------------------------------------------------ folds

def folds(ts, season, min_history=0.15, min_rows=500, by="auto"):
    """Rolling-origin test blocks as (name, start ts, end ts).

    by="season": each season with enough history before it is a block.
    by="month": calendar months (merged forward until a block holds
    min_rows rows). by="auto": seasons, or months when fewer than three
    seasons qualify, so a one-season cache still gets several origins. A
    block qualifies once min_history of all rows lie before it."""
    ts = np.asarray(ts, float)
    season = np.asarray(season)
    n = len(ts)

    def ok(start):
        return (ts < start).mean() >= min_history

    blocks = []
    for s in sorted(set(season.tolist())):
        m = season == s
        start, end = ts[m].min(), ts[m].max() + 1
        if ok(start):
            blocks.append((str(s), float(start), float(end)))
    if by == "season" or (by == "auto" and len(blocks) >= 3):
        return blocks
    months = pd.to_datetime(ts, unit="s").to_period("M")
    blocks, cur = [], None
    for mth in sorted(set(months)):
        m = np.asarray(months == mth)
        start, end = ts[m].min(), ts[m].max() + 1
        if cur is None:
            if not ok(start):
                continue
            cur = [str(mth), start, end, int(m.sum())]
        else:
            cur[2], cur[3] = end, cur[3] + int(m.sum())
            cur[0] = cur[0].split("..")[0] + ".." + str(mth)
        if cur[3] >= min_rows:
            blocks.append((cur[0], float(cur[1]), float(cur[2])))
            cur = None
    if cur is not None and n:
        blocks.append((cur[0], float(cur[1]), float(cur[2])))
    return blocks


def split_history(ts, start, val_share=0.25):
    """Train and validation masks from everything before `start`: the last
    val_share of the history by date is validation."""
    ts = np.asarray(ts, float)
    hist = ts < start
    cut = np.quantile(ts[hist], 1 - val_share)
    return hist & (ts < cut), hist & (ts >= cut)


# ------------------------------------------------------------------ scoring

def ll(y, p):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def brier(y, p):
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def calibration(y, p, bins=10):
    """said, landed, intercept and slope of y on logit p, ten-bin ECE."""
    y, p = np.asarray(y, float), np.asarray(p, float)
    from sklearn.linear_model import LogisticRegression
    cal = LogisticRegression(C=1e6).fit(lo(p).reshape(-1, 1), y.astype(int))
    edges = np.linspace(0, 1, bins + 1)
    b = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    ece = sum(abs(p[b == k].mean() - y[b == k].mean()) * (b == k).sum() for k in range(bins) if (b == k).any()) / len(y)
    return {"said": float(p.mean()), "landed": float(y.mean()), "cal_int": float(cal.intercept_[0]),
            "cal_slope": float(cal.coef_[0][0]), "ece": float(ece)}


def cluster_bootstrap(groups, stats, fn, n_boot=2000, seed=0):
    """Game-level bootstrap. stats: dict of per-row arrays; per game they are
    summed, games are resampled with replacement and fn(sums) gives the
    statistic from the summed columns. Returns (point, low, high) at 95%
    plus the replicate array."""
    g = pd.Series(np.asarray(groups)).astype("category").cat.codes.values
    G = g.max() + 1
    sums = {k: np.bincount(g, weights=np.asarray(v, float), minlength=G) for k, v in stats.items()}
    point = fn(sums)
    rng = np.random.default_rng(seed)
    reps = np.empty(n_boot)
    for i in range(n_boot):
        w = np.bincount(rng.integers(0, G, G), minlength=G)
        reps[i] = fn({k: (v * w).sum() for k, v in sums.items()})
    return float(point), float(np.quantile(reps, 0.025)), float(np.quantile(reps, 0.975)), reps


def loss_gain_ci(y, p_ref, p_new, groups, n_boot=2000, seed=0):
    """Log-loss gain of p_new over p_ref (positive: p_new better), 95% game-level interval."""
    def nll(p):
        p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
        return -(y * np.log(p) + (1 - y) * np.log(1 - p))
    y = np.asarray(y, float)
    d = nll(p_ref) - nll(p_new)
    pt, lo_, hi, reps = cluster_bootstrap(groups, {"d": d, "n": np.ones(len(d))},
                                          lambda s: s["d"].sum() / s["n"].sum(), n_boot, seed)
    return pt, lo_, hi, float((reps <= 0).mean())


# ------------------------------------------------------------------ betting

def book_prices(q_over, margin):
    """Two-way prices from a fair chance, margin spread proportionally."""
    q = np.clip(np.asarray(q_over, float), 0.01, 0.99)
    return 1 / (q * (1 + margin)), 1 / ((1 - q) * (1 + margin))


def take_bets(p_over, price_over, price_under, n_games, days_rest, rule=RULE):
    """The page's take rule on both sides of each line.

    Returns (side, price, edge) per row: side 1 over, 0 under, -1 no bet.
    report.py verdictOf: take when our chance is 50% or more, the edge
    p * price - 1 is 5% or more but not over 30% (the NBA / NFL guard), the
    record is five games or more and the data is not stale (no game in 60
    days)."""
    p = np.asarray(p_over, float)
    po, pu = np.asarray(price_over, float), np.asarray(price_under, float)
    e_over, e_under = p * po - 1, (1 - p) * pu - 1
    base = (np.asarray(n_games) >= rule["min_n"]) & (np.asarray(days_rest) <= rule["stale_days"])
    t_over = base & (p >= rule["min_p"]) & (e_over >= rule["min_edge"]) & (e_over <= rule["max_edge"])
    t_under = base & (1 - p >= rule["min_p"]) & (e_under >= rule["min_edge"]) & (e_under <= rule["max_edge"])
    side = np.where(t_over, 1, np.where(t_under, 0, -1))
    price = np.where(t_over, po, np.where(t_under, pu, np.nan))
    edge = np.where(t_over, e_over, np.where(t_under, e_under, np.nan))
    return side, price, edge


def settle(side, price, y_over):
    """Flat one-unit stakes: profit per row (NaN where no bet)."""
    won = np.where(side == 1, y_over == 1, y_over == 0)
    return np.where(side >= 0, np.where(won, price - 1, -1.0), np.nan)


def roi_ci(profit, groups, n_boot=2000, seed=0):
    m = ~np.isnan(profit)
    if m.sum() == 0:
        return {"bets": 0, "won": 0, "pl": 0.0, "roi": float("nan"), "lo": float("nan"), "hi": float("nan"),
                "p_le0": float("nan")}
    pr = profit[m]
    pt, l, h, reps = cluster_bootstrap(np.asarray(groups)[m], {"pl": pr, "n": np.ones(m.sum())},
                                       lambda s: s["pl"].sum() / max(1, s["n"].sum()), n_boot, seed)
    return {"bets": int(m.sum()), "won": int((pr > 0).sum()), "pl": float(pr.sum()), "roi": pt,
            "lo": l, "hi": h, "p_le0": float((reps <= 0).mean())}


# ------------------------------------------------------------------ the site's price

def site_probs(F, P, sport, targets):
    """model.price_player on his last 20 games, per (target, rung), as evaluate_us.py."""
    import model
    site = SITE_SPORT[sport]
    mm = model.min_minutes_for(site) if sport == "nba" else 0
    Pp = P.sort_values("ts")
    if sport == "nfl":
        Pp = Pp.assign(mins=60.0, td=Pp.rush_td + Pp.rec_td)
    # The page's record is his games with statistics (minutes in the NBA);
    # every row still gets its price, a blank NFL game included.
    counts = (Pp.mins > 0) if sport == "nba" else (Pp.has_stats == 1)
    hist, by_key = defaultdict(list), {}
    want = set(zip(F.match, F.pid))
    for r, c in zip(Pp.itertuples(index=False), counts.values):
        if (r.match, r.pid) in want:
            by_key[(r.match, r.pid)] = list(hist[r.pid][-20:])
        if c and r.mins >= mm:
            hist[r.pid].append(r)
    out = {}
    for s in targets:
        ok = eligible(F, sport, s).values
        for li, L in enumerate(lines_for(F, s)):
            vals = np.full(len(F), np.nan)
            for i in np.where(ok)[0]:
                prev = by_key.get((F.match.iat[i], F.pid.iat[i]))
                if not prev or len(prev) < 3:
                    continue
                apps = [{"value": float(getattr(x, s)), "minutes": float(x.mins)} for x in prev]
                try:
                    vals[i] = model.price_player(apps, float(L.iat[i]), True, 1.0, None, site)["p"]
                except Exception:  # noqa: BLE001
                    pass
            out[(s, li)] = vals
    return out


# ------------------------------------------------------------------ one fold, one market

class Spread:
    """P(Y > line) around a predicted mean, as evaluate_us.Spread."""

    def __init__(self, y, mu, yards):
        from scipy import stats as sst
        self.yards = yards
        if yards:
            r = y / np.clip(mu, 1e-6, None)
            self.edges = np.quantile(mu, [0, .25, .5, .75, 1])
            self.ratios = [np.sort(r[(mu >= self.edges[i]) & (mu <= self.edges[i + 1])]) for i in range(4)]
        else:
            best, bestll = None, -np.inf
            for size in [0.5, 1, 2, 3, 5, 8, 12, 20, 35, 60, 100, 1e4]:
                v = sst.nbinom.logpmf(y, size, size / (size + mu)).sum()
                if v > bestll:
                    best, bestll = size, v
            self.size = best

    def p_over(self, mu, line):
        from scipy import stats as sst
        if self.yards:
            b = np.clip(np.searchsorted(self.edges, mu) - 1, 0, 3)
            out = np.empty(len(mu))
            for k in range(4):
                m = b == k
                if m.any():
                    r = self.ratios[k]
                    # share of ratios with mu * r > line, i.e. r > line / mu
                    out[m] = 1 - np.searchsorted(r, line[m] / np.clip(mu[m], 1e-9, None), side="right") / len(r)
            return out
        return 1 - sst.nbinom.cdf(np.floor(line), self.size, self.size / (self.size + mu))


def poisson_dev(y, mu):
    mu = np.clip(mu, 1e-6, None)
    return float(np.mean(2 * (np.where(y > 0, y * np.log(np.where(y > 0, y, 1) / mu), 0) - (y - mu))))


def platt(p, y):
    from sklearn.linear_model import LogisticRegression
    m = LogisticRegression(C=1e6).fit(lo(p).reshape(-1, 1), np.asarray(y, int))
    return lambda q: m.predict_proba(lo(q).reshape(-1, 1))[:, 1]


def run_fold(F, sport, s, feats, site, tr, va, te, fold):
    import lightgbm as lgb
    from sklearn.linear_model import LogisticRegression
    y = np.clip(F[f"y_{s}"].astype(float).values, 0, None)
    base = np.clip(F[f"{s}_ew"].astype(float).fillna(0).values, 0.05, None)
    X = F[feats]
    best = None
    for nl, md in SHAPES:
        prm = dict(PARAMS, num_leaves=nl, min_data_in_leaf=md)
        dtr = lgb.Dataset(X[tr], y[tr], init_score=np.log(base[tr]))
        dva = lgb.Dataset(X[va], y[va], init_score=np.log(base[va]), reference=dtr)
        m = lgb.train(prm, dtr, 3000, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])
        dv = poisson_dev(y[va], base[va] * np.exp(m.predict(X[va], raw_score=True)))
        if best is None or dv < best[0]:
            best = (dv, m)
    m = best[1]
    mu_va = base[va] * np.exp(m.predict(X[va], raw_score=True))
    mu_te = base[te] * np.exp(m.predict(X[te], raw_score=True))
    sp = Spread(y[va], mu_va, s in YARDS)
    V, T, TR = [], [], []
    for li, L in enumerate(lines_for(F, s)):
        Lv = L.values
        for mask, mu, bucket in ((va, mu_va, V), (te, mu_te, T)):
            bucket.append(pd.DataFrame({"p": sp.p_over(mu, Lv[mask]), "site": site[(s, li)][mask],
                                        "y": (y[mask] > Lv[mask]).astype(int), "line": Lv[mask],
                                        "rung": li, "row": np.where(mask)[0]}))
        TR.append(pd.DataFrame({"site": site[(s, li)][tr], "y": (y[tr] > Lv[tr]).astype(int)}))
    V, T, TR = (pd.concat(x) for x in (V, T, TR))
    V, T, TR = V[V.site.notna()], T[T.site.notna()], TR[TR.site.notna()]
    if len(V) < 100 or len(T) < 50 or len(TR) < 300:
        return None
    fsf = platt(TR.site.values, TR.y.values)
    fcal = platt(V.p.values, V.y.values)
    Xv = np.c_[lo(fcal(V.p.values)), lo(fsf(V.site.values))]
    bl = LogisticRegression(C=1.0).fit(Xv, V.y)
    vts = F.ts.values[V.row.values]
    h1, h2 = vts < np.median(vts), vts >= np.median(vts)
    bl1 = LogisticRegression(C=1.0).fit(Xv[h1], V.y.values[h1])
    use_blend = ll(V.y.values[h2], bl1.predict_proba(Xv[h2])[:, 1]) < ll(V.y.values[h2], fcal(V.p.values[h2]))
    T["p_site"] = T.site.values
    T["p_site_fair"] = fsf(T.site.values)
    T["p_new"] = fcal(T.p.values)
    T["p_blend"] = bl.predict_proba(np.c_[lo(T.p_new.values), lo(T.p_site_fair.values)])[:, 1]
    T["p_live"] = T.p_blend.values if use_blend else T.p_new.values
    T["use_blend"] = bool(use_blend)
    T["w_model"], T["w_site"] = float(bl.coef_[0][0]), float(bl.coef_[0][1])
    r = T.row.values
    T["match"], T["ts"], T["pid"] = F.match.values[r], F.ts.values[r], F.pid.values[r]
    T["n_games"], T["days_rest"] = F.n.values[r], F.days_rest.values[r]
    T["fold"], T["target"] = fold, s
    return T.drop(columns=["p", "site"])


def prepare(sport, cache, data):
    """Players table and features from a cache folder, as rebuild.py does."""
    import usfeatures as U
    Path(data).mkdir(parents=True, exist_ok=True)
    M, T, P = U.build(str(cache), sport)
    if M.empty:
        raise SystemExit(f"no finished {sport} games with box scores in {cache}")
    if sport == "nba":
        P["pra"] = P.points + P.rebounds + P.assists
        P["pr"], P["pa"], P["ra"] = P.points + P.rebounds, P.points + P.assists, P.rebounds + P.assists
    else:
        P["rush_rec_yds"], P["pass_rush_yds"] = P.rush_yds + P.rec_yds, P.pass_yds + P.rush_yds
    P.to_parquet(f"{data}/{sport}_players.parquet")
    U.features(M, T, P, sport).to_parquet(f"{data}/{sport}_features.parquet")


def run(sport, data, out, n_boot, by="auto", starter_proxy=False):
    F = pd.read_parquet(f"{data}/{sport}_features.parquet").sort_values("ts").reset_index(drop=True)
    if starter_proxy:
        # The backtest knows who started; live it is the confirmed line-up
        # when team_news has one, else his start rate (usfeatures.add_upcoming).
        # This scores the model as if no line-up were ever confirmed.
        F["starter"] = (F.start_rate >= 0.5).astype(int)
    P = pd.read_parquet(f"{data}/{sport}_players.parquet")
    meta = json.load(open(ROOT / "usmodel" / f"{sport}_meta.json"))
    F["pos_c"] = F.pos.map(meta["pos_codes"]).fillna(-1)
    targets = [s for s in TARGETS[sport] if s in meta["targets"]]
    site = site_probs(F, P, sport, targets)
    blocks = folds(F.ts.values, F.season.values, by=by)
    print("folds:", [b[0] for b in blocks], flush=True)
    preds = []
    for s in targets:
        feats = [c for c in meta["targets"][s]["features"] if c in F.columns]
        ok = eligible(F, sport, s).values
        for name, start, end in blocks:
            tr, va = split_history(F.ts.values, start)
            te = (F.ts.values >= start) & (F.ts.values < end)
            tr, va, te = tr & ok, va & ok, te & ok
            if tr.sum() < 300 or va.sum() < 100 or te.sum() < 50:
                print(f"  {s} {name}: skipped (train {tr.sum()}, val {va.sum()}, test {te.sum()})", flush=True)
                continue
            T = run_fold(F, sport, s, feats, site, tr, va, te, name)
            if T is None:
                continue
            preds.append(T)
            print(f"  {s} {name}: {len(T)} lines, site {ll(T.y, T.p_site):.4f} fair {ll(T.y, T.p_site_fair):.4f}"
                  f" new {ll(T.y, T.p_new):.4f} live {ll(T.y, T.p_live):.4f} blend={T.use_blend.iat[0]}", flush=True)
    A = pd.concat(preds, ignore_index=True)
    Path(out).mkdir(parents=True, exist_ok=True)
    A.to_parquet(f"{out}/{sport}_audit_preds.parquet")
    tables = summarise(A, sport, n_boot)
    json.dump(tables, open(f"{out}/{sport}_audit.json", "w"), indent=1)
    return tables


# ------------------------------------------------------------------ tables

VARIANTS = ("site", "site_fair", "new", "blend", "live")


def summarise(A, sport, n_boot=2000, margins=(0.05, 0.075, 0.10)):
    out = {"sport": sport, "folds": sorted(A.fold.unique().tolist()), "markets": {}, "per_fold": {}, "betting": {}}
    n_markets = A.target.nunique()
    for s, g in A.groupby("target", sort=False):
        y = g.y.values
        row = {"lines": int(len(g)), "games": int(g.match.nunique()), "folds": int(g.fold.nunique()),
               "blend_chosen_folds": int(g.groupby("fold").use_blend.first().sum())}
        for v in VARIANTS:
            p = g[f"p_{v}"].values
            row[f"ll_{v}"], row[f"brier_{v}"] = ll(y, p), brier(y, p)
            row[f"cal_{v}"] = calibration(y, p)
        for ref in ("site", "site_fair"):
            pt, l_, h_, p0 = loss_gain_ci(y, g[f"p_{ref}"].values, g.p_live.values, g.match.values, n_boot)
            row[f"gain_vs_{ref}"] = {"gain": pt, "lo": l_, "hi": h_, "p_le0": p0,
                                     "survives": l_ > 0, "survives_bonf": p0 < 0.05 / n_markets}
        pt, l_, h_, p0 = loss_gain_ci(y, g.p_new.values, g.p_blend.values, g.match.values, n_boot)
        row["blend_vs_new"] = {"gain": pt, "lo": l_, "hi": h_, "p_le0": p0}
        pt, l_, h_, p0 = loss_gain_ci(y, g.p_site_fair.values, g.p_new.values, g.match.values, n_boot)
        row["new_vs_site_fair"] = {"gain": pt, "lo": l_, "hi": h_, "p_le0": p0}
        row["fold_gains_vs_site_fair"] = {f: ll(q.y, q.p_site_fair) - ll(q.y, q.p_live) for f, q in g.groupby("fold")}
        row["weights"] = {f: [float(q.w_model.iat[0]), float(q.w_site.iat[0])] for f, q in g.groupby("fold")}
        out["markets"][s] = row
        for f, q in g.groupby("fold"):
            out["per_fold"].setdefault(s, {})[f] = {"lines": int(len(q)), **{v: ll(q.y, q[f"p_{v}"]) for v in VARIANTS}}
        bets = {}
        for book in ("site_fair", "site"):
            for mg in margins:
                po, pu = book_prices(g[f"p_{book}"].values, mg)
                for who in ("live", "site_fair"):
                    if who == book:
                        continue
                    side, price, edge = take_bets(g[f"p_{who}"].values, po, pu, g.n_games.values, g.days_rest.values)
                    prof = settle(side, price, y)
                    bets[f"{who}|{book}|{mg}"] = roi_ci(prof, g.match.values, n_boot)
                    if who == "live" and book == "site_fair" and mg == 0.075:
                        # one bet per player-game: the rung with the biggest edge
                        d = pd.DataFrame({"k": g.match.astype(str).values + "_" + g.pid.astype(str).values,
                                          "edge": edge, "prof": prof, "match": g.match.values})
                        d = d[~np.isnan(d.prof)].sort_values("edge").groupby("k").tail(1)
                        bets["live_best_rung|site_fair|0.075"] = roi_ci(d.prof.values, d.match.values, n_boot)
        out["betting"][s] = bets
    # all markets together, live v site_fair at a 7.5% margin
    po, pu = book_prices(A.p_site_fair.values, 0.075)
    side, price, _ = take_bets(A.p_live.values, po, pu, A.n_games.values, A.days_rest.values)
    out["betting_all"] = roi_ci(settle(side, price, A.y.values), A.match.values, n_boot)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("sport", choices=("nba", "nfl"))
    ap.add_argument("--data", required=True, help="folder for the parquet tables")
    ap.add_argument("--cache", help="build the tables from this cache folder first")
    ap.add_argument("--out", default=None)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--by", choices=("auto", "season", "month"), default="auto")
    ap.add_argument("--starter-proxy", action="store_true",
                    help="replace the known starter flag by start rate >= 50%%")
    a = ap.parse_args(argv)
    if a.cache:
        prepare(a.sport, a.cache, a.data)
    run(a.sport, a.data, a.out or a.data, a.boot, a.by, a.starter_proxy)
    return 0


if __name__ == "__main__":
    sys.exit(main())
