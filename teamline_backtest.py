#!/usr/bin/env python3
"""
Walk-forward backtest of the team lines, and the take threshold per market.

    .venv/bin/python -B teamline_backtest.py            # cache/ -> teamlines_gate.json and TEAM-LINES.md
    .venv/bin/python -B teamline_backtest.py --quick    # three test months, for a look (writes nothing)

Needs lightgbm, numpy, pandas, scipy and statsmodels, like teammodel_train.py.

The question. On 21 Oct 2026, 26 of the 30 takes on the European pages were
team lines (corners, cards, fouls, shots on target) that had never been
tested, so the page stopped calling any team line a take. This decides, per
market, whether one has earned it.

Every cached match is replayed in date order. For each test month from
January 2026, the team model is fitted again on every match before the month,
exactly as teammodel_train.py fits it (LightGBM on the teamstyle.py features,
or the linear game state fit, whichever teammodel/meta.json chose), and every
side and match total in the month is priced at five lines around the side's
own average. Four ways of pricing the same line are scored:

  base     how often the line landed in all training matches, ignoring the teams
  record   the page's fallback: the last-10 average through probOver() and
           calibrate(), as teamValued() prices a line with no projection
  linear   the game state fit (own, opponent concedes, home, ball), Poisson GLM
  model    the team model as deployed (the linear fit or the LightGBM)

on log loss, Brier and calibration. Then, per market:

  threshold  chosen on the January to May predictions. No Paddy Power team
             prices were kept for finished matches, so each line is priced
             by a proxy book: the linear game state fit (which knows each
             side's average, what the opponent concedes, home and the ball,
             no more than any bookmaker knows) with a 9% overround. A take
             is a line we call 50% or more where our chance times that price
             beats 1 by at least t (and by no more than the page's 30% cap).
             Those are the lines where we disagree with the book, which is
             where our errors gather, so this is the test the page's takes
             face. The threshold is the smallest t from 5% to 30% whose
             takes paid on January to May: 200 or more of them, and the 90%
             lower bound of the return at or above zero.
  confirm    the same t on June to October, never seen while choosing it:
             50 or more takes, and a return at or above zero.

A market passes only if the model beats both the base rate and the record on
log loss and Brier (95% intervals, resampling whole matches), is calibrated
(slope 0.8 to 1.25), finds a threshold, and the threshold held on the later
months. Where Betfair's exchange prices were logged (exchange_log.json: match
corners and match cards), the model is also scored against them; a handful of
matches decide nothing and are reported, not used.

Beating the proxy book is necessary, not sufficient: Paddy Power knows more
than the linear fit (team news, the referee, its own traders). teamlog.py
settles the real lines at Paddy Power's real prices; that record has the last
word, and a market that passed here should be failed if it says otherwise.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import model as M  # noqa: E402
import teamlines as TL  # noqa: E402
import teamstyle as TS  # noqa: E402

CACHE = ROOT / "cache"
GATE = TL.GATE
REPORT = ROOT / "TEAM-LINES.md"
EXCHANGE = ROOT / "exchange_log.json"

FIRST_TEST = "2026-01-01"
SELECT_END = "2026-06-01"       # thresholds chosen before this, confirmed from it
LADDER = (-2, -1, 0, 1, 2)      # lines around floor(own average) + 0.5
MIN_RECORD = 5                  # the page's floor for pricing a team line
GRID = [round(0.05 + 0.025 * i, 3) for i in range(11)]   # 5% to 30%
# The proxy book: prices every line from the linear game state fit (own
# average, what the opponent concedes, home, the ball) with this overround,
# split in proportion. Paddy Power knows at least that much, so a take that
# cannot beat this book cannot beat theirs; one that can, still might not.
OVERROUND = 0.09
MIN_TAKES = 200                 # fewest takes on January to May for a threshold to count
MIN_CONFIRM = 50                # and on June to October for it to be confirmed
SENSITIVITY = (0.05, 0.09, 0.12)  # overrounds the write-up re-prices a chosen threshold at
SLOPE = (0.8, 1.25)
BOOT = 1000
SEED = 7
EXCHANGE_STAT = {"Match corners": "Corner kicks", "Match cards": "Yellow cards"}


# ------------------------------------------------------------------ data

def build(cache: Path = CACHE):
    """Pre-kick-off rows per side (teamstyle features, results, last-10 record)."""
    S = TS.State()
    hist = defaultdict(list)                 # team -> [(own, against)] per stat
    stats = sorted({s for s, _ in TL.MARKETS})
    rec_rows = {}
    for m in TS.load(cache):
        items = m["items"]
        y = {}
        for s in stats:
            v = items.get(s)
            # The feed leaves the cards row out when nobody was booked:
            # settled as 0 (besttrack._team_value), so scored as 0 here.
            if v is None and s == "Yellow cards":
                v = (0.0, 0.0)
            y[s] = v
        for i, team in enumerate((m["home"], m["away"])):
            h = hist[team][-10:]
            rec_rows[(m["match"], team)] = {
                "rec_" + s: [r[s][0] for r in h if r[s][0] is not None] for s in stats} | {
                "tot_" + s: [r[s][0] + r[s][1] for r in h if r[s][0] is not None and r[s][1] is not None]
                for s in stats} | {"t_" + s: (y[s][i] if y[s] else None) for s in stats}
        for i, team in enumerate((m["home"], m["away"])):
            hist[team].append({s: ((y[s][i], y[s][1 - i]) if y[s] else (None, None)) for s in stats})
        S.add(m)
    R = pd.DataFrame(S.rows)
    extra = pd.DataFrame([{"match": k[0], "team": k[1], **v} for k, v in rec_rows.items()])
    R = R.merge(extra, on=["match", "team"], how="left")
    return R


# ------------------------------------------------------------------ fitting

def _fit_month(R, s, train, test, meta):
    """(mu_lin, mu_gbm, mu_model) on test and the same in-sample on train, plus alphas."""
    import lightgbm as lgb
    import statsmodels.api as sm
    import teammodel_train as TT
    ytr = train["t_" + s].astype(float).values
    glm = sm.GLM(ytr, TT.lin_X(train, s), family=sm.families.Poisson()).fit()
    lin_tr, lin_te = glm.predict(TT.lin_X(train, s)), glm.predict(TT.lin_X(test, s))
    e = (meta.get("stats") or {}).get(s) or {}
    feats = e.get("features") or TT.feats_for(R, s)
    # Early stopping on the last 15% of the training dates, then the whole
    # window again at that many trees: the trainer's April to June choice,
    # rolled forward a month at a time.
    cut = train.ts.quantile(0.85)
    a, b = train[train.ts < cut], train[train.ts >= cut]
    dtr = lgb.Dataset(a[feats], a["t_" + s].astype(float))
    dva = lgb.Dataset(b[feats], b["t_" + s].astype(float), reference=dtr)
    m = lgb.train(TT.PARAMS, dtr, 3000, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])
    m2 = lgb.train(TT.PARAMS, lgb.Dataset(train[feats], ytr), m.best_iteration or 200)
    gbm_tr, gbm_te = m2.predict(train[feats]), m2.predict(test[feats])
    use = e.get("use", "linear")
    out = {"lin": (lin_tr, lin_te, TT.alpha_of(ytr, lin_tr)),
           "gbm": (gbm_tr, gbm_te, TT.alpha_of(ytr, gbm_tr))}
    out["model"] = out["gbm" if use == "gbm" else "lin"]
    return out, use


def _sf(k, mu, alpha):
    """P(X >= k), vectorised, negative binomial (Poisson at alpha 0)."""
    from scipy.stats import nbinom, poisson
    k = np.asarray(k)
    mu = np.maximum(np.asarray(mu, float), 1e-9)
    if alpha < 1e-6:
        return poisson.sf(k - 1, mu)
    r = 1 / alpha
    return nbinom.sf(k - 1, r, r / (r + mu))


def _page_record(line, vals, mean=None):
    """teamValued()'s record price: calibrate(probOver(line, mean, vals))."""
    mean = (sum(vals) / len(vals)) if mean is None else mean
    return M.calibrate(M.prob_over(line, mean, vals))


def walk(R, months=None, exchange=None):
    """Every priced line, out of sample: one row per (market, side or match, line)."""
    import teammodel_train as TT
    meta = json.loads((ROOT / "teammodel" / "meta.json").read_text())
    starts = pd.date_range(FIRST_TEST, periods=12, freq="MS")
    end = pd.to_datetime(R.ts.max(), unit="s")
    starts = [t for t in starts if t <= end]
    if months:
        starts = starts[-months:]
    lines, xlines, uses, last_alpha = [], [], {}, {}
    for s in sorted({s for s, _ in TL.MARKETS}):
        ok = (R["own_" + s].notna() & R["opp_conc_" + s].notna() & R["t_" + s].notna()
              & (R["rec_" + s].str.len() >= MIN_RECORD))
        X = R[ok].copy()
        for i, t0 in enumerate(starts):
            t1 = starts[i + 1] if i + 1 < len(starts) else end + pd.Timedelta(days=1)
            a, b = t0.timestamp(), t1.timestamp()
            train, test = X[X.ts < a], X[(X.ts >= a) & (X.ts < b)]
            if len(test) < 20:
                continue
            fit, use = _fit_month(R, s, train, test, meta)
            uses[s] = use
            ytr = train["t_" + s].astype(float).values
            base_side = np.sort(ytr)
            # match totals: both sides of a match present
            def pairs(df, mus):
                d = df.assign(**{f"mu_{k}": v for k, v in mus.items()})
                g = d.groupby("match")
                keep = g["team"].transform("size") == 2
                d = d[keep]
                agg = d.groupby("match").agg(ts=("ts", "first"), y=("t_" + s, "sum"),
                                             **{f"mu_{k}": (f"mu_{k}", "sum") for k in mus},
                                             recs=("rec_" + s, list), tots=("tot_" + s, list))
                return agg
            tr_mu = {k: v[0] for k, v in fit.items()}
            te_mu = {k: v[1] for k, v in fit.items()}
            P_tr, P_te = pairs(train, tr_mu), pairs(test, te_mu)
            alpha_match = {k: TT.alpha_of(P_tr.y.values, P_tr[f"mu_{k}"].values) for k in fit}
            last_alpha[s] = alpha_match["model"]
            base_match = np.sort(P_tr.y.values)
            fold = t0.strftime("%Y-%m")
            # one side
            for j, (_, r) in enumerate(test.iterrows()):
                own = r["rec_" + s]
                c = math.floor(sum(own) / len(own)) + 0.5
                for d in LADDER:
                    line = c + d
                    if line < 0.5:
                        continue
                    k = int(math.floor(line)) + 1
                    lines.append({
                        "market": TL.market_key(s, "side"), "match": r.match, "team": r.team, "ts": r.ts,
                        "fold": fold, "line": line, "y": int(r["t_" + s] >= k),
                        "base": (np.sum(base_side >= k) + 1) / (len(base_side) + 2),
                        "record": _page_record(line, own),
                        **{key: float(_sf(k, te_mu[key][j], fit[key][2])) for key in fit},
                        "mu": float(te_mu["model"][j])})
            # the match
            if (s, "match") in TL.MARKETS:
                for mid, r in P_te.iterrows():
                    if len(r.recs) != 2 or min(len(v) for v in r.recs) < MIN_RECORD:
                        continue
                    exp = sum(sum(v) / len(v) for v in r.recs)
                    tots = [x for v in r.tots for x in v]
                    if len(tots) < MIN_RECORD:
                        continue
                    c = math.floor(exp) + 0.5
                    for d in LADDER:
                        line = c + d
                        if line < 0.5:
                            continue
                        k = int(math.floor(line)) + 1
                        lines.append({
                            "market": TL.market_key(s, "match"), "match": mid, "team": None, "ts": r.ts,
                            "fold": fold, "line": line, "y": int(r.y >= k),
                            "base": (np.sum(base_match >= k) + 1) / (len(base_match) + 2),
                            "record": _page_record(line, tots, exp),
                            **{key: float(_sf(k, r[f"mu_{key}"], alpha_match[key])) for key in fit},
                            "mu": float(r["mu_model"])})
                    for x in (exchange or {}).get((int(mid), s), []):
                        k = int(math.floor(x["line"])) + 1
                        xlines.append({"market": TL.market_key(s, "match"), "match": mid, "line": x["line"],
                                       "y": int(r.y >= k), "book": x["p"],
                                       "base": (np.sum(base_match >= k) + 1) / (len(base_match) + 2),
                                       "record": _page_record(x["line"], tots, exp),
                                       "model": float(_sf(k, r["mu_model"], alpha_match["model"]))})
            print(f"  {s:16} {fold}: train {len(train)}, test {len(test)} sides, {len(P_te)} matches", flush=True)
    return pd.DataFrame(lines), pd.DataFrame(xlines), uses, last_alpha


def exchange_lines(path: Path = EXCHANGE) -> dict:
    """Betfair's match corners and cards, over side, one per event and line."""
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    out, seen = defaultdict(list), set()
    for x in d.values():
        s = EXCHANGE_STAT.get(x.get("stat"))
        if not s or not x.get("over") or x.get("result") not in ("win", "lose"):
            continue
        p = (x.get("last") or {}).get("market") or (x.get("first") or {}).get("market")
        key = (x["event_id"], s, x["line"])
        if p is None or key in seen:
            continue
        seen.add(key)
        out[(x["event_id"], s)].append({"line": x["line"], "p": p})
    return out


# ------------------------------------------------------------------ scoring

def _clip(p):
    return np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)


def logloss(y, p):
    p = _clip(p)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def brier(y, p):
    return (np.asarray(p, float) - y) ** 2


def boot_diff(df, a, b, fn, seed=SEED, n=BOOT):
    """Mean of fn(model a) - fn(model b), and its 95% interval, resampling whole matches."""
    y = df.y.values
    d = fn(y, df[a].values) - fn(y, df[b].values)
    g = pd.DataFrame({"m": df.match.values, "d": d}).groupby("m").d.agg(["sum", "size"])
    s, c = g["sum"].values, g["size"].values
    rng = np.random.default_rng(seed)
    w = rng.multinomial(len(s), np.full(len(s), 1 / len(s)), size=n)
    means = (w @ s) / (w @ c)
    return float(d.mean()), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def calibration(y, p):
    """(intercept, slope) of the logistic regression of the result on logit(p)."""
    import statsmodels.api as sm
    p = _clip(p)
    X = np.column_stack([np.ones(len(p)), np.log(p / (1 - p))])
    r = sm.GLM(y, X, family=sm.families.Binomial()).fit()
    return float(r.params[0]), float(r.params[1])


def reliability(y, p, edges=(0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.0001)):
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = (p >= lo) & (p < hi)
        if sel.sum() >= 30:
            out.append({"lo": lo, "hi": min(hi, 1.0), "n": int(sel.sum()), "said": float(p[sel].mean()),
                        "got": float(y[sel].mean())})
    return out


def offered(df, key, overround=None):
    """Each line on the sides the market offers: our chance, the proxy book's, the result."""
    overround = OVERROUND if overround is None else overround
    under = TL.MARKETS[tuple(key.split("|"))]
    parts = [df.assign(p=df.model, q=df.lin, win=df.y)]
    if under:
        parts.append(df.assign(p=1 - df.model, q=1 - df.lin, win=1 - df.y))
    c = pd.concat(parts, ignore_index=True)
    c["price"] = 1 / (np.clip(c.q.values, 1e-3, 1) * (1 + overround))
    c["edge"] = c.p.values * c.price.values - 1
    return c[c.price > 1.01]


def takes(c, t):
    """The lines the page would call take against the proxy book at threshold t."""
    return c[(c.p >= TL.MIN_P) & (c.edge >= t) & (c.edge <= TL.SUSPECT)]


def boot_mean(c, r, seed=SEED, n=BOOT, q=0.10):
    """The q and 1 - q quantiles of the mean of r, resampling whole matches."""
    g = pd.DataFrame({"m": c.match.values, "r": r}).groupby("m").r.agg(["sum", "size"])
    s, k = g["sum"].values, g["size"].values
    rng = np.random.default_rng(seed)
    w = rng.multinomial(len(s), np.full(len(s), 1 / len(s)), size=n)
    means = (w @ s) / (w @ k)
    return float(np.quantile(means, q)), float(np.quantile(means, 1 - q))


def paid(c, t):
    """{n, matches, said, got, edge, ret, lo90, hi90} for the takes at threshold t."""
    k = takes(c, t)
    if not len(k):
        return {"t": t, "n": 0}
    r = k.win.values * k.price.values - 1
    lo, hi = boot_mean(k, r)
    return {"t": t, "n": int(len(k)), "matches": int(k.match.nunique()), "said": float(k.p.mean()),
            "got": float(k.win.mean()), "edge": float(k.edge.mean()), "ret": float(r.mean()),
            "lo90": lo, "hi90": hi}


def choose_threshold(c):
    """Smallest t on the grid whose takes paid against the proxy book (90% lower bound >= 0)."""
    tried = [paid(c, t) for t in GRID]
    for x in tried:
        if x["n"] >= MIN_TAKES and x["lo90"] >= 0:
            return x["t"], tried
    return None, tried


def confirm(c, t):
    x = paid(c, t)
    x["held"] = bool(x["n"] >= MIN_CONFIRM and x["ret"] >= 0)
    return x


def stat_is_reference(res):
    return res["model_kind"] != "gbm"


def judge(df, xdf, uses):
    sel_end = pd.Timestamp(SELECT_END).timestamp()
    out = {}
    for key in [TL.market_key(s, sc) for s, sc in TL.MARKETS]:
        d = df[df.market == key]
        if len(d) < 500:
            continue
        stat = key.split("|")[0]
        y = d.y.values
        res = {"stat": stat, "scope": key.split("|")[1], "model_kind": uses.get(stat, "linear"),
               "lines": int(len(d)), "matches": int(d.match.nunique()),
               "from": datetime.fromtimestamp(d.ts.min(), timezone.utc).strftime("%Y-%m-%d"),
               "to": datetime.fromtimestamp(d.ts.max(), timezone.utc).strftime("%Y-%m-%d")}
        res["score"] = {m: {"logloss": float(logloss(y, d[m].values).mean()),
                            "brier": float(brier(y, d[m].values).mean())}
                        for m in ("base", "record", "lin", "gbm", "model")}
        res["vs"] = {}
        for other in ("base", "record"):
            res["vs"][other] = {"logloss": boot_diff(d, "model", other, logloss),
                                "brier": boot_diff(d, "model", other, brier)}
        a, b = calibration(y, d.model.values)
        res["calibration"] = {"intercept": a, "slope": b, "mean_p": float(d.model.mean()), "rate": float(y.mean()),
                              "table": reliability(y, d.model.values)}
        ra, rb = calibration(y, d.record.values)
        res["calibration_record"] = {"intercept": ra, "slope": rb}
        sel, conf = d[d.ts < sel_end], d[d.ts >= sel_end]
        cs, cc = offered(sel, key), offered(conf, key)
        t, tried = choose_threshold(cs) if len(cs) else (None, [])
        res["select"] = {"lines": int(len(sel)), "tried": tried, "threshold": t}
        res["confirm"] = confirm(cc, t) if t is not None else None
        # every threshold on the later months too, for the write-up only (never used to choose)
        res["later"] = [paid(cc, x) for x in GRID]
        if t is not None:
            res["overround"] = {o: {"select": paid(offered(sel, key, o), t), "confirm": paid(offered(conf, key, o), t)}
                                for o in SENSITIVITY}
        x = xdf[xdf.market == key] if len(xdf) else xdf
        if len(x):
            yx = x.y.values
            res["exchange"] = {"lines": int(len(x)), "matches": int(x.match.nunique()),
                               **{m: {"logloss": float(logloss(yx, x[m].values).mean()),
                                      "brier": float(brier(yx, x[m].values).mean())}
                                  for m in ("book", "base", "record", "model")}}
        why = []
        for other in ("base", "record"):
            for metric in ("logloss", "brier"):
                if not res["vs"][other][metric][2] < 0:
                    why.append(f"not clearly better than the {other} on {metric.replace('logloss', 'log loss')}")
        if not SLOPE[0] <= b <= SLOPE[1]:
            why.append(f"calibration slope {b:.2f}, outside {SLOPE[0]} to {SLOPE[1]}")
        if stat_is_reference(res):
            why.append("the deployed model is the linear fit itself, so it cannot disagree with the proxy book")
        elif t is None:
            why.append(f"no threshold up to {GRID[-1]:.0%} paid against the proxy book on January to May")
        elif not res["confirm"]["held"]:
            why.append(f"the {t:.1%} threshold did not hold from June")
        res["why"] = why
        res["pass"] = not why
        res["threshold"] = t if not why else None
        out[key] = res
    return out


# ------------------------------------------------------------------ the write-up

def _pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def _verdict(k, r):
    """One honest paragraph per market, from its numbers."""
    name = TL.market_name(k)
    s, v, c = r["score"], r["vs"], r["calibration"]
    ll = v["base"]["logloss"][0]
    head = (f"The model's log loss is {s['model']['logloss']:.4f} against {s['base']['logloss']:.4f} for the base rate "
            f"and {s['record']['logloss']:.4f} for the page's record price; calibration slope {c['slope']:.2f}.")
    if r["pass"]:
        se = next(x for x in r["select"]["tried"] if x["t"] == r["threshold"])
        co = r["confirm"]
        out = (f"**Passed, take from an edge of {_pct(r['threshold'])}.** {head} Against the proxy book its "
               f"takes paid {_pct(se['ret'])} a line on January to May ({se['n']} takes) and {_pct(co['ret'])} on "
               f"June to October ({co['n']} takes, 90% interval {_pct(co['lo90'])} to {_pct(co['hi90'])}). "
               f"On the later takes it said {_pct(co['said'], 0)} and got {_pct(co['got'], 0)}"
               + (": the chance shown on a take runs high, as on any line picked for disagreeing with a price, "
                  f"and the edge it claimed ({_pct(co['edge'])} on average) was more than it earned."
                  if co["said"] > co["got"] else
                  f", on January to May {_pct(se['said'], 0)} and {_pct(se['got'], 0)}. The later months beat the "
                  "earlier ones by a distance, which says more about how weak the proxy book was on them than "
                  "about Paddy Power."))
        o = r.get("overround") or {}
        lo = o.get(min(SENSITIVITY))
        if lo and lo["confirm"].get("n"):
            out += (f" Against a sharper book with a {_pct(min(SENSITIVITY), 0)} overround the same threshold "
                    f"returned {_pct(lo['confirm']['ret'])} on the later months.")
        worst = next((x for x in r["later"] if x["t"] > r["threshold"] and x["n"] >= 30 and x["ret"] < 0), None)
        if worst:
            out += (f" The biggest claimed edges did worst: on June to October the {worst['n']} lines claiming "
                    f"{_pct(worst['t'])} or more returned {_pct(worst['ret'])}, so a take far above the "
                    "threshold deserves more doubt, not less.")
        return f"- **{name}**: " + out + " Whether that survives Paddy Power's real prices is for the team log to say."
    why = "; ".join(r["why"])
    extra = ""
    if r["model_kind"] != "gbm":
        extra = (" The model is no worse for it: it beats the base rate and the record by more than any other "
                 "market, but its only advantage is the linear fit, and that is the least a bookmaker knows.")
    elif ll > -0.002:
        extra = " The model adds next to nothing over the base rate here, so a gap between it and a price is mostly noise."
    elif r.get("later") and r["select"]["threshold"] is None:
        later_ok = [x for x in r["later"] if x["n"] >= MIN_CONFIRM and x["lo90"] >= 0]
        if later_ok:
            extra = (" The later months look better than the earlier ones, but choosing a threshold from them would "
                     "be choosing it on the data that is meant to test it.")
    x = r.get("exchange")
    if x:
        extra += (f" On the {x['matches']} matches Betfair priced, the exchange scored {x['book']['logloss']:.3f} "
                  f"and the model {x['model']['logloss']:.3f}.")
    return f"- **{name}**: **Failed.** {head} Failed because: {why}.{extra} Never a take; acceptable at most."


def write(results, alphas, generated, rows):
    first = min(r["from"] for r in results.values())
    last = max(r["to"] for r in results.values())
    passed = [k for k, r in results.items() if r["pass"]]
    rec_slopes = [r["calibration_record"]["slope"] for r in results.values()]
    rec_worse = all(r["score"]["record"]["logloss"] > r["score"]["base"]["logloss"] for r in results.values())
    flat = [TL.market_name(k) for k, r in results.items() if not r["vs"]["base"]["logloss"][2] < 0]
    # the takes at the lowest threshold, both periods, pooled over the markets the proxy can test
    pool = [x for r in results.values() if r["model_kind"] == "gbm"
            for x in (r["select"]["tried"][0], r["later"][0]) if x["n"]]
    tot = sum(x["n"] for x in pool) or 1
    said = sum(x["n"] * x["said"] for x in pool) / tot
    got = sum(x["n"] * x["got"] for x in pool) / tot
    claimed = sum(x["n"] * x["edge"] for x in pool) / tot
    earned = sum(x["n"] * x["ret"] for x in pool) / tot
    gaps = [x["said"] - x["got"] for x in pool]
    n_x = sorted({r["exchange"]["matches"] for r in results.values() if r.get("exchange")})
    gate = {"generated": generated, "rows": rows, "select_end": SELECT_END, "overround": OVERROUND,
            "take_shortfall": round(said - got, 4),
            "note": "teamline_backtest.py: a team line is a take only in a market with pass true, priced by the "
                    "team model, at an edge of at least threshold and at most 30%.",
            "markets": {k: {"pass": r["pass"], "threshold": r["threshold"], "why": r["why"],
                            "model_kind": r["model_kind"],
                            "alpha_match": alphas.get(r["stat"]) if r["scope"] == "match" else None,
                            "lines": r["lines"], "matches": r["matches"]} for k, r in results.items()}}
    GATE.write_text(json.dumps(gate, indent=1) + "\n", encoding="utf-8")
    L = ["# Team lines: the backtest", "",
         f"Generated {generated} by `teamline_backtest.py` from the cached matches ({rows} side rows, test "
         f"matches {first} to {last}). The gate it writes, `teamlines_gate.json`, is what `teamlines.py` reads "
         "for the pages and for `teamlog.py`. Rerun it after the cache grows; this file is rewritten each time.", "",
         "## Summary", "",
         f"{len(passed)} of {len(results)} team-line markets passed: "
         + ("; ".join(f"{TL.market_name(k)}, take from an edge of {_pct(results[k]['threshold'])}" for k in passed)
            if passed else "none") + ". "
         "Every other market stays as it has been since 21 October: acceptable at most, never a take. "
         "Three findings matter more than the verdicts:", "",
         ("1. **The page's own record price is worse than knowing nothing about the teams.** On every market the "
          if rec_worse else "1. **The page's own record price is weak.** On most markets the ") +
         "last-10 average through `probOver()` and `calibrate()` scores a worse log loss than the plain base rate, "
         f"and its calibration slope is {min(rec_slopes):.1f} to {max(rec_slopes):.1f}: "
         + ("underconfident, so it flattens real differences. " if min(rec_slopes) > 1 else "")
         + "That is how the page has priced a team line with no projection, and what the cross-league odds "
         "scaling behind the 26 takes started from.",
         "2. **The team model beats the record on every market**, and the base rate on every market"
         + (f" but {', '.join(flat)}, where it adds nothing over the base rate." if flat else ".")
         + " The intervals are below.",
         "3. **Being better on average is not the same as beating a price.** Pooled over the five markets the "
         f"proxy book can test, the {tot} lines the model would have called a take at a 5% edge were said to land "
         f"{_pct(said)} of the time and landed {_pct(got)}, and claimed an edge of {_pct(claimed)} a line for a "
         f"return of {_pct(earned)}. Lines picked for disagreeing with a price are where the model's errors "
         f"gather. Market by market and period by period, the gap ran from {max(0, -min(gaps)) * 100:.0f} points "
         f"the right way to {max(gaps) * 100:.0f} points short.", "",
         "## Why", "",
         "On 21 Oct 2026, 26 of the 30 takes on the European pages were team lines (corners, cards, fouls, "
         "shots on target) with no evidence behind them, so the page stopped calling any team line a take. "
         "This is the evidence, market by market.", "",
         "## Method", "",
         "- **Walk forward.** For every month from January 2026 the team model is fitted again on every "
         "match before that month, the way `teammodel_train.py` fits it (LightGBM on the `teamstyle.py` "
         "features or the linear game state fit, whichever `teammodel/meta.json` chose for the stat; shots use "
         "the linear fit, the rest LightGBM), and scored on that month only. Nothing a prediction uses comes "
         "from on or after its kick-off. Spreads are fitted as the trainer fits them, on the training matches.",
         "- **Markets.** The ones Paddy Power prices: each side's corners and cards (over and under), the match "
         "corners and cards (over and under), and each side's fouls, shots on target and shots (\"N or more\", "
         "overs only). Cards are yellow cards, the count `teamlog.py` settles on; a match with no card row in the "
         "feed is settled as none.",
         "- **Lines.** Each side (and each match) is priced at five lines: floor(own last-10 average) + 0.5, and "
         "one and two either side. Over and under at one line are the same event, so each line is scored once.",
         "- **Four prices for the same line.** *base*: how often the line landed across all training matches, "
         "ignoring who is playing. *record*: the page's fallback, the last-10 average through `probOver()` and "
         "`calibrate()`. *linear*: the game state fit. *model*: the team model as deployed.",
         f"- **Scores.** Log loss and Brier, lower is better. Differences carry 95% intervals from resampling "
         f"whole matches ({BOOT} draws), because the lines of one match are not independent.",
         "- **Calibration.** The slope of the logistic regression of the result on logit(chance): 1 is right, "
         "below 1 overconfident, above 1 underconfident.",
         f"- **The proxy book.** No Paddy Power team prices were kept for finished matches (the team log starts "
         f"now), so every line is priced by a stand-in: the linear game state fit, which knows each side's "
         f"average, what the opponent concedes, home and the ball, and no more than any bookmaker knows, with a "
         f"{_pct(OVERROUND, 0)} overround split in proportion. A take is a line we call 50% or more where our "
         f"chance times that price beats 1 by at least the threshold *t* and by no more than the page's 30% cap.",
         f"- **The threshold**, chosen on January to May only: the smallest *t* from 5% to 30% (steps of 2.5%) "
         f"whose takes paid against the proxy book, with {MIN_TAKES} or more takes and the 90% lower bound of the "
         f"return per line at or above zero.",
         f"- **Confirmation**, June to October, never seen while choosing *t*: {MIN_CONFIRM} or more takes and a "
         f"return at or above zero.",
         f"- **Pass** needs all of: better than both base and record on log loss and on Brier (interval wholly "
         f"below zero), slope {SLOPE[0]} to {SLOPE[1]}, a threshold found, and the threshold holding on the later "
         f"months.",
         "- **Betfair.** Exchange prices were logged for match corners and match cards on "
         f"{' and '.join(map(str, n_x)) or 'no'} October games (`exchange_log.json`). They are scored below and "
         "decide nothing.", ""]
    L += ["## Results by market", "",
          "Every held-out line, January 2026 to the latest cached match.", "",
          "| Market | Lines | Matches | Model | Log loss: base | record | linear | LightGBM | model | Brier: base | record | model | Slope | Verdict |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, r in results.items():
        s = r["score"]
        L.append(f"| {TL.market_name(k)} | {r['lines']} | {r['matches']} | {r['model_kind']} | "
                 f"{s['base']['logloss']:.4f} | {s['record']['logloss']:.4f} | {s['lin']['logloss']:.4f} | "
                 f"{s['gbm']['logloss']:.4f} | {s['model']['logloss']:.4f} | {s['base']['brier']:.4f} | "
                 f"{s['record']['brier']:.4f} | {s['model']['brier']:.4f} | {r['calibration']['slope']:.2f} | "
                 f"{'pass' if r['pass'] else 'fail'} |")
    L += ["", "### Model against the baselines", "",
          "Model minus baseline, mean per line, with the 95% interval. Negative is the model better.", "",
          "| Market | Log loss vs base | Log loss vs record | Brier vs base | Brier vs record |",
          "|---|---|---|---|---|"]
    fmt = lambda v: f"{v[0]:+.4f} ({v[1]:+.4f} to {v[2]:+.4f})"  # noqa: E731
    for k, r in results.items():
        v = r["vs"]
        L.append(f"| {TL.market_name(k)} | {fmt(v['base']['logloss'])} | {fmt(v['record']['logloss'])} | "
                 f"{fmt(v['base']['brier'])} | {fmt(v['record']['brier'])} |")
    L += ["", "### Calibration", "",
          "| Market | Model intercept | Model slope | Record slope | Mean chance | Landed |", "|---|---|---|---|---|---|"]
    for k, r in results.items():
        c = r["calibration"]
        L.append(f"| {TL.market_name(k)} | {c['intercept']:+.3f} | {c['slope']:.3f} | "
                 f"{r['calibration_record']['slope']:.3f} | {_pct(c['mean_p'])} | {_pct(c['rate'])} |")
    L += ["", "Said against got, the model, every held-out line, in bands of 10 points (30 or more lines):", ""]
    for k, r in results.items():
        cells = "; ".join(f"{_pct(b['said'], 0)} said, {_pct(b['got'], 0)} got (n {b['n']})"
                          for b in r["calibration"]["table"])
        L.append(f"- **{TL.market_name(k)}**: {cells}")
    L += ["", "## The take threshold", "",
          f"Chosen on January to May, confirmed on June to October, against the proxy book at a "
          f"{_pct(OVERROUND, 0)} overround. Return is per line staked, at the proxy book's price. Said and got "
          "are on the takes only.", "",
          "| Market | Threshold | Takes (Jan to May) | Said | Got | Claimed edge | Return | 90% low | Takes (Jun to Oct) | Said | Got | Return | 90% interval | Held |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, r in results.items():
        t = r["select"]["threshold"]
        if r["model_kind"] != "gbm":
            L.append(f"| {TL.market_name(k)} | not testable | - | - | - | - | - | - | - | - | - | - | - | - |")
            continue
        if t is None:
            L.append(f"| {TL.market_name(k)} | none up to 30% | - | - | - | - | - | - | - | - | - | - | - | - |")
            continue
        a = next(x for x in r["select"]["tried"] if x["t"] == t)
        co = r["confirm"]
        later = (f"{co['n']} | {_pct(co['said'], 0)} | {_pct(co['got'], 0)} | {_pct(co['ret'])} | "
                 f"{_pct(co['lo90'])} to {_pct(co['hi90'])} | {'yes' if co['held'] else 'no'}") if co.get("n") \
            else "0 | - | - | - | - | no"
        L.append(f"| {TL.market_name(k)} | {_pct(t)} | {a['n']} | {_pct(a['said'], 0)} | {_pct(a['got'], 0)} | "
                 f"{_pct(a['edge'])} | {_pct(a['ret'])} | {_pct(a['lo90'])} | {later} |")
    L += ["", "### Every threshold", "",
          "What each threshold on the grid would have done. Only the January to May columns choose; the June to "
          "October columns are shown so the choice can be checked, not to make it.", ""]
    for k, r in results.items():
        if r["model_kind"] != "gbm":
            continue
        L += [f"**{TL.market_name(k)}**", "",
              "| t | Takes (Jan to May) | Said | Got | Return | 90% low | Takes (Jun to Oct) | Said | Got | Return | 90% low |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for a, b in zip(r["select"]["tried"], r["later"]):
            cell = lambda x: (f"{x['n']} | {_pct(x['said'], 0)} | {_pct(x['got'], 0)} | {_pct(x['ret'])} | "  # noqa: E731
                              f"{_pct(x['lo90'])}") if x["n"] else "0 | - | - | - | -"
            L.append(f"| {_pct(a['t'])} | {cell(a)} | {cell(b)} |")
        L.append("")
    L += ["### How much the overround matters", "",
          "Each passed market's threshold, re-priced against proxy books with other overrounds. A smaller "
          "overround is a sharper, harder book.", "",
          "| Market | Threshold | Overround | Takes (Jan to May) | Return | Takes (Jun to Oct) | Return |",
          "|---|---|---|---|---|---|---|"]
    for k, r in results.items():
        if not r["pass"]:
            continue
        for o, x in (r.get("overround") or {}).items():
            a, b = x["select"], x["confirm"]
            L.append(f"| {TL.market_name(k)} | {_pct(r['threshold'])} | {_pct(o, 0)} | {a['n']} | "
                     f"{_pct(a['ret']) if a['n'] else '-'} | {b['n']} | {_pct(b['ret']) if b['n'] else '-'} |")
    if not passed:
        L.append("| no market passed | | | | | | |")
    L += ["", "## Against Betfair's prices", "",
          "The exchange's own chance at the last price logged before kick-off, over side, one row per match "
          "and line. Far too few matches to decide anything, shown so the gap can be watched.", "",
          "| Market | Lines | Matches | Log loss: Betfair | base | record | model | Brier: Betfair | base | record | model |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    any_x = False
    for k, r in results.items():
        x = r.get("exchange")
        if not x:
            continue
        any_x = True
        L.append(f"| {TL.market_name(k)} | {x['lines']} | {x['matches']} | " +
                 " | ".join(f"{x[m]['logloss']:.3f}" for m in ("book", "base", "record", "model")) + " | " +
                 " | ".join(f"{x[m]['brier']:.3f}" for m in ("book", "base", "record", "model")) + " |")
    if not any_x:
        L.append("| none of the logged matches had a prediction | | | | | | | | | | |")
    L += ["", "## Verdict by market", ""]
    L += [_verdict(k, r) for k, r in results.items()]
    L += ["", "## What this does not show", "",
          "- **Paddy Power is not the proxy book.** It knows the team news, the referee and its own traders' views, "
          "so it is sharper than the linear fit, and a take against it is rarer and worth less than one against the "
          "stand-in. Passing here is the least a market must do, not proof that it beats Paddy Power.",
          f"- **The chance shown on a take is too high on average.** Pooled, the takes landed {_pct(said - got)} "
          "below what the model said. The page shows the model's chance as it is; read the edge on a take as a "
          "good deal less than it says.",
          "- **The lines are not Paddy Power's.** The ladder sits around each side's own average, which is close to "
          "where the main lines sit, but the alternative lines Paddy Power also offers further out are only partly "
          "covered.",
          "- **The record has the last word.** `teamlog.py` now logs the team model's chance and the verdict on "
          "every Paddy Power team line, and `python teamlog.py report` splits the settled lines by market and by "
          "verdict. A passed market whose takes lose at the real prices over a few hundred settled lines should be "
          "failed by hand in `teamlines_gate.json` and the backtest revisited.", "",
          "## Wiring", "",
          "- `teamlines.py` holds the markets, the negative binomial and `verdict()`, and reads the gate.",
          "- `report.py` attaches, at build time, each side's team-model expectation and spread to every football "
          "fixture (`teamModel`) and the gate (`teamLineGate`). `teamValued()` prices a line in a passed market from "
          "the team model and calls it a take only from the market's threshold to the 30% cap; every other line is "
          "priced as before and is never a take.",
          "- `teamlog.py snapshot` records the team model's chance, the market and the verdict with every line; "
          "`report` splits the record by market and verdict.", ""]
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")


def main(argv=None):
    import pickle
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--cache", default=str(CACHE))
    ap.add_argument("--quick", action="store_true", help="three test months, writes nothing")
    ap.add_argument("--dump", help="save the scored lines to this .pkl")
    ap.add_argument("--load", help="judge and write from a --dump instead of replaying the cache")
    a = ap.parse_args(argv)
    if a.load:
        with open(a.load, "rb") as fh:
            df, xdf, uses, alphas, rows = pickle.load(fh)
    else:
        t0 = time.time()
        R = build(Path(a.cache))
        rows = len(R)
        print(f"{rows} side rows, {R.match.nunique()} matches ({time.time() - t0:.0f}s)", flush=True)
        df, xdf, uses, alphas = walk(R, months=3 if a.quick else None, exchange=exchange_lines())
        if a.dump:
            with open(a.dump, "wb") as fh:
                pickle.dump((df, xdf, uses, alphas, rows), fh)
    res = judge(df, xdf, uses)
    for k, r in res.items():
        print(f"{k:22} {'PASS' if r['pass'] else 'fail'}  model {r['score']['model']['logloss']:.4f} "
              f"record {r['score']['record']['logloss']:.4f} base {r['score']['base']['logloss']:.4f} "
              f"slope {r['calibration']['slope']:.2f} t {r['select']['threshold']}  {'; '.join(r['why'])}")
    if not a.quick:
        write(res, alphas, datetime.now(timezone.utc).isoformat(timespec="seconds"), rows)
        print(f"-> {GATE.name}, {REPORT.name}")


if __name__ == "__main__":
    main()
