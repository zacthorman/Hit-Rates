#!/usr/bin/env python3
"""
Walk-forward audit of the football player legs the page leans on most:
anytime goalscorer, shots and shots on target.

    python -B scorer_audit.py build    # cache/ -> cache/scorer_audit.pkl (about 15 minutes)
    python -B scorer_audit.py test     # scores, diagnoses, tests fixes -> SCORER-AUDIT.md, fmodel/tonight_blend.json

Every starter in every cached match is replayed in date order with only what
was known before kick-off, and each of the chances the page can show for a
leg is worked out exactly as the page works it out:

  record    hits over appearances of 45+ minutes in his last 38 (the record
            behind every player leg on tonight.html and the Players tab)
  shrunk    the record pulled to 50% by weekend.player_shrink() phantom hits
            and misses (pShrunk, what tonight.html ranks player legs on)
  site      model.price_player, the Players tab's own chance where fmodel has
            none (per 90 times expected minutes, calibrated), adjustment 1;
            for to score the profile's scoreCase (60% xG, 40% goals per 90)
  fmodel    the backtested player model (fmodel_live.py, the trees in
            fmodel/), the Players tab's chance for any starter it covers
  gs        the game-state model of gs_backtest.py, refitted before each
            month on every earlier row from mid-December 2025, priced as
            context.py prices it
  tonight   what tonight.html shows as "With the record": shrunk and fmodel
            averaged for shots and shots on target, shrunk alone for goals

fmodel was trained on data to the end of June 2026, so everything is scored
on 1 July 2026 on, where every source is out of sample. The months are the
walk-forward windows: a calibration fix is chosen on the months before a
window and scored on it, and is only wired in if it beats leaving the chances
alone on every later window. Two kinds are tried: maps on fmodel's own chance
(Platt, with pre-match minutes, rotation, penalty and position terms), and the
weight tonight.html gives fmodel against the shrunk record, which is written
to fmodel/tonight_blend.json for context.py when it holds.
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"
DATA = CACHE / "scorer_audit.pkl"
REPORT = ROOT / "SCORER-AUDIT.md"
BLEND = ROOT / "fmodel" / "tonight_blend.json"
SITE = ROOT / "fmodel" / "site_calib.json"

OOS_FROM = int(datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp())
RECORD_WINDOW = 38       # appearances behind the record (update.json "games")
RECORD_MIN_MINUTES = 45  # weekend.MIN_MINUTES, model.MIN_MINUTES
TONIGHT_MIN_SAMPLE = 10  # weekend.MIN_PLAYER_SAMPLE: fewer and tonight.html shows no leg
PEN_XG = (0.755, 0.79)   # SofaScore's xG for a penalty (0.7884, 0.76 in a few leagues)

# leg -> (stat, k): "over k - 0.5"
LEGS = {"Anytime goalscorer": ("goals", 1), "Shots 1+": ("shots", 1), "Shots 2+": ("shots", 2),
        "Shots 3+": ("shots", 3), "Shots on target 1+": ("sot", 1), "Shots on target 2+": ("sot", 2)}
COVERED = {"shots", "sot"}           # stats with a per-match coverage flag
GS_STAT = {"shots": "Shots", "sot": "Shots on target"}
GS_TEAM = {"shots": "Total shots", "sot": "Shots on target"}
# leg -> the key context.py looks the weight up by: "<site stat>|<k>"
LEG_KEY = {"Anytime goalscorer": "Goals|1", "Shots 1+": "Shots|1", "Shots 2+": "Shots|2", "Shots 3+": "Shots|3",
           "Shots on target 1+": "Shots on target|1", "Shots on target 2+": "Shots on target|2"}
# leg -> the key report.py looks the Players tab's fallback map up by
SITE_KEY = {**LEG_KEY, "Anytime goalscorer": "score|1"}
SOURCES = ["record", "shrunk", "site", "gs", "fmodel", "tonight"]
MARKER = "<!-- tables below are written by scorer_audit.py test -->"
BANDS = [0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.0001]


# =================================================================== build

def _leagues():
    """uniqueTournament id -> name, from the cached fixture lists."""
    import glob
    out = {}
    for f in glob.glob(str(CACHE / "team_*_events_*.json")):
        try:
            evs = json.loads(Path(f).read_text()).get("events") or []
        except (OSError, ValueError):
            continue
        for e in evs:
            ut = (e.get("tournament") or {}).get("uniqueTournament") or {}
            if ut.get("id") and ut.get("name"):
                out[ut["id"]] = ut["name"]
    return out


def is_penalty_game(shots, xg) -> bool:
    """One shot worth a penalty's xG: a penalty taken. Misses multi-shot games, so a floor."""
    return shots == 1 and PEN_XG[0] <= (xg or 0) <= PEN_XG[1]


def scorecase_p(apps_recent, apps_all) -> float | None:
    """report.py scoreCase, neutral: 60% xG and 40% goals per 90 over the median
    minutes of 45+ appearances, half last ten and half everything."""
    def lam(apps):
        apps = [a for a in apps if a["mins"] >= RECORD_MIN_MINUTES]
        if len(apps) < 3:
            return None
        mins = sum(a["mins"] for a in apps)
        if mins <= 0:
            return None
        g90 = sum(a["goals"] for a in apps) / mins * 90
        xg90 = sum(a["xg"] for a in apps) / mins * 90
        rate = 0.6 * xg90 + 0.4 * g90
        m = sorted(a["mins"] for a in apps)
        return rate * min(90, m[len(m) // 2]) / 90
    r, f = lam(apps_recent), lam(apps_all)
    if r is None or f is None:
        return None
    return 1 - math.exp(-(r + f) / 2)


def _team_hist_feed(T):
    """Per match, per team: (own stats, stats against) dicts for the game state."""
    out = {}
    for r in T.to_dict("records"):
        own = {k[2:]: r[k] for k in r if k.startswith("f_") and r[k] is not None and not pd.isna(r[k])}
        ag = {k[2:]: r[k] for k in r if k.startswith("a_") and r[k] is not None and not pd.isna(r[k])}
        out[(r["match"], r["team"])] = (own, ag)
    return out


def tree_predict(tree, X):
    """fmodel_trees.Tree.predict, a level at a time over every row at once.

    Same rules (missing types, default directions, categorical splits); a test
    holds it equal to Tree.predict. The original walks one row at a time,
    fine for a few hundred starters, hours for the whole cache.
    """
    X = np.asarray(X, float)
    node = np.zeros(len(X), dtype=int)
    rows = np.arange(len(X))
    is_cat = np.array([c is not None for c in tree.cats], bool)
    while True:
        live = tree.feat[node] >= 0
        if not live.any():
            break
        r, nd = rows[live], node[live]
        v = X[r, tree.feat[nd]]
        nan = np.isnan(v)
        mt = tree.mtype[nd]
        v0 = np.where(nan, 0.0, v)
        left = np.where((mt == 2) & nan, tree.dleft[nd],
                        np.where((mt == 1) & (v0 == 0.0), tree.dleft[nd], v0 <= tree.thr[nd]))
        for c in np.unique(nd[is_cat[nd]]):
            sel = nd == c
            left[sel] = [(not math.isnan(x)) and x >= 0 and int(x) in tree.cats[c] for x in v[sel]]
        node[live] = np.where(left, tree.left[nd], tree.right[nd])
    return tree.leaf[node]


def score_fast(F, names=("goals_1", "shots_1", "shots_2", "shots_3", "sot_1", "sot_2")):
    """fmodel_live.score for the lines audited, with tree_predict."""
    sys.path.insert(0, str(ROOT / "fmodel"))
    from fmodel_trees import Model
    meta = json.loads((ROOT / "fmodel" / "meta.json").read_text())
    cats = meta["comp_categories"]
    F = F.copy()
    F["pos_c"] = F.pos.map({"G": 0, "D": 1, "M": 2, "F": 3})
    F["comp_c"] = [float(cats.index(int(c))) if c is not None and not pd.isna(c) and int(c) in cats
                   else np.nan for c in F["comp"]]
    out = {}
    for name in names:
        X = F.reindex(columns=meta["lines"][name]["features"]).astype(float).values
        raw = np.zeros(len(X))
        for t in Model(ROOT / "fmodel" / f"{name}.json").trees:
            raw += tree_predict(t, X)
        out[name] = 1 / (1 + np.exp(-raw))
    return out


def build() -> None:
    import fmodel_live as FL
    t0 = datetime.now()
    M, T, P = FL.history()
    print(f"history: {len(M)} matches, {len(P)} player rows")
    feats = CACHE / "scorer_audit_features.pkl"
    if feats.exists() and feats.stat().st_mtime > max(f.stat().st_mtime for f in CACHE.glob("event_*_lineups.json")):
        F = pd.read_pickle(feats)
    else:
        F = FL.features(M, T, P, set(), emit=set(M.match))
        F.to_pickle(feats)
    print(f"features: {len(F)} starter rows ({(datetime.now() - t0).seconds}s)")
    # fmodel is only scored where it is out of sample (July on); the 200 days before
    # are kept as the game-state model's first training set
    F = F[F.ts >= OOS_FROM - 200 * 86400].reset_index(drop=True)
    probs = score_fast(F)
    keep = ["match", "ts", "pid", "name", "team", "opp", "home", "pos", "comp", "n", "start_rate",
            "mins_avg5", "shots_p90_10", "goals_p90_10", "xg_p90_10"]
    D = F[keep].copy()
    for name in ("goals_1", "shots_1", "shots_2", "shots_3", "sot_1", "sot_2"):
        D["fm_" + name] = probs[name]
    # outcomes, and who came off the bench
    y = P[["match", "pid", "shots", "sot", "goals", "xg", "mins", "starter", "cov_shots", "cov_sot"]]
    D = D.merge(y.rename(columns={"shots": "y_shots", "sot": "y_sot", "goals": "y_goals", "xg": "y_xg",
                                  "mins": "y_mins"}), on=["match", "pid"], how="left")
    # substitutes: the same record for players who came on, for the minutes table
    subs = P[(P.starter == 0) & (P.mins > 0)][["match", "ts", "pid", "name", "team", "opp", "home", "pos",
                                              "shots", "sot", "goals", "xg", "mins", "starter",
                                              "cov_shots", "cov_sot"]]
    subs = subs.rename(columns={"shots": "y_shots", "sot": "y_sot", "goals": "y_goals", "xg": "y_xg",
                                "mins": "y_mins"})
    subs = subs[subs.ts >= OOS_FROM - 200 * 86400]
    comp = dict(zip(M.match, M.comp_id))
    subs["comp"] = subs.match.map(comp)
    D = pd.concat([D, subs], ignore_index=True)
    # team histories into P order for the game state
    feed = _team_hist_feed(T)
    R = _records_with_teams(P, set(zip(D.match, D.pid)), feed)
    D = D.merge(R, on=["match", "pid"], how="left")
    lg = _leagues()
    D["league"] = [lg.get(int(c), str(c)) if c is not None and not pd.isna(c) else "?" for c in D.comp]
    D.to_pickle(DATA)
    print(f"{len(D)} rows -> {DATA} ({(datetime.now() - t0).seconds}s)")


def _records_with_teams(P, wanted, feed):
    """Record, site price, scoreCase, penalty flag and game-state inputs per (match, pid)."""
    P = P[P.mins > 0].sort_values(["ts", "match"], kind="stable")
    matches = list(dict.fromkeys(P.match))
    by_match = {m: g for m, g in P.groupby("match", sort=False)}
    return _records_core(by_match, matches, wanted, feed)


def _records_core(by_match, matches, wanted, feed):
    import model
    import gs_backtest as G
    hist = defaultdict(list)
    team_hist = defaultdict(list)
    out = []
    for mid in matches:
        pm = by_match[mid]
        teams = list(dict.fromkeys(pm.team))
        home_rows = pm[pm.home == 1]
        h_id = home_rows.team.iloc[0] if len(home_rows) else teams[0]
        a_id = next((t for t in teams if t != h_id), None)
        prior_team = {t: team_hist[t][-G.WINDOW:] for t in teams}
        usual = {}
        for t in teams:
            pos = [h[0].get("Ball possession") for h in prior_team[t] if h[0].get("Ball possession") is not None]
            usual[t] = float(np.mean(pos)) if len(pos) >= G.MIN_PRIOR else None
        here = {}
        if a_id is not None and usual.get(h_id) is not None and usual.get(a_id) is not None:
            ph, pa = G.predicted_possession(usual[h_id], usual[a_id])
            here = {h_id: ph, a_id: pa}
        for r in pm.itertuples(index=False):
            if (mid, r.pid) not in wanted:
                continue
            h = hist[r.pid]
            last = h[-RECORD_WINDOW:]
            row = {"match": mid, "pid": r.pid}
            for s, ks in (("goals", (1,)), ("shots", (1, 2, 3)), ("sot", (1, 2))):
                apps = [{"value": x[s], "minutes": x["mins"]} for x in last
                        if x["mins"] >= RECORD_MIN_MINUTES and (s not in COVERED or x["cov_" + s])]
                vals = [a["value"] for a in apps]
                for k in ks:
                    row[f"rec_{s}_{k}_h"] = sum(v >= k for v in vals)
                    row[f"rec_{s}_{k}_n"] = len(vals)
                    if s != "goals":
                        row[f"site_{s}_{k}"] = (model.price_player(apps, k - 0.5, True, 1.0, None, "football")["p"]
                                                if len(apps) >= 3 else np.nan)
            sc = scorecase_p(h[-10:], last)
            row["site_goals_1"] = sc if sc is not None else np.nan
            row["pen_seen"] = any(is_penalty_game(x["shots"], x["xg"]) for x in last)
            row["prior_apps"] = len(h)
            row["prior_starts10"] = sum(x["starter"] for x in h[-10:])
            row["med_mins5"] = float(np.median([x["mins"] for x in h[-5:]])) if h else np.nan
            g60 = [x for x in h if x["mins"] >= G.MIN_MINUTES and x["pos"] != "G"][-G.WINDOW:]
            for s in ("shots", "sot"):
                row[f"gs_{s}_own"] = np.nan
                if len(g60) < G.MIN_PLAYER or r.team not in here:
                    continue
                avg = float(np.mean([x[s] for x in g60]))
                tst = GS_TEAM[s]
                allow = [x[1].get(tst) for x in team_hist[r.opp][-G.WINDOW:] if x[1].get(tst) is not None]
                mine = [x[0].get(tst) for x in prior_team[r.team] if x[0].get(tst) is not None]
                if avg <= 0 or len(allow) < G.MIN_PRIOR or len(mine) < G.MIN_PRIOR:
                    continue
                al, us = float(np.mean(allow)), float(np.mean(mine))
                row[f"gs_{s}_own"] = max(0.05, avg)
                row[f"gs_{s}_allow"] = max(0.2, min(5, al / us if us > 0 and al > 0 else 1.0))
                row[f"gs_{s}_f"] = G.ball_factor(here[r.team], usual[r.team], +1)
            out.append(row)
        for r in pm.itertuples(index=False):
            d = {s: getattr(r, s) for s in ("shots", "sot", "goals", "xg")}
            d.update(mins=r.mins, starter=r.starter, pos=r.pos,
                     **{"cov_" + s: bool(getattr(r, "cov_" + s)) for s in COVERED})
            hist[r.pid].append(d)
        for t in teams:
            if (mid, t) in feed:
                team_hist[t].append(feed[(mid, t)])
    return pd.DataFrame(out)


# ================================================================= scoring

CLIP = 0.005   # a raw record of 0/10 or 10/10 is clipped here for log loss


def log_loss(p, y) -> float:
    p = np.clip(np.asarray(p, float), CLIP, 1 - CLIP)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def brier(p, y) -> float:
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def bands(p, y, edges=BANDS, min_n=1):
    """(lo, hi, n, mean said, share landed) per chance band."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = (p >= lo) & (p < hi)
        if sel.sum() >= min_n:
            out.append((lo, min(hi, 1.0), int(sel.sum()), float(p[sel].mean()), float(y[sel].mean())))
    return out


def ece(p, y) -> float:
    """Expected calibration error: the n-weighted gap between said and landed over the bands."""
    b = bands(p, y)
    n = sum(x[2] for x in b)
    return sum(x[2] * abs(x[3] - x[4]) for x in b) / n if n else float("nan")


def _logit(p):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def fit_logistic(X, y, ridge=1e-3, iters=50):
    """Logistic regression by Newton steps (no scikit-learn on the Mac)."""
    X, y = np.asarray(X, float), np.asarray(y, float)
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        q = 1 / (1 + np.exp(-np.clip(X @ b, -30, 30)))
        w = q * (1 - q)
        g = X.T @ (y - q) - ridge * b
        H = (X * w[:, None]).T @ X + ridge * np.eye(X.shape[1])
        step = np.linalg.solve(H, g)
        b += step
        if np.abs(step).max() < 1e-9:
            break
    return b


def _sig(z):
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


def month_of(ts) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m")


# ----------------------------------------------------------- the sources

def gs_chances(D: pd.DataFrame) -> pd.DataFrame:
    """gs_backtest's M2 fitted before each month on every earlier 60+ minute row
    (the population the page's fit uses), scored on every starter that month."""
    import gs_backtest as G
    out = {}
    months = sorted({month_of(t) for t in D.ts[D.ts >= OOS_FROM]})
    for s in ("shots", "sot"):
        rows = D[D[f"gs_{s}_own"].notna() & D[f"cov_{s}"].fillna(False).astype(bool)]
        for m in months:
            start = int(datetime.strptime(m, "%Y-%m").replace(tzinfo=timezone.utc).timestamp())
            tr = rows[(rows.ts < start) & (rows.y_mins >= G.MIN_MINUTES) & (rows.starter == 1)]
            te = rows[rows.ts.map(month_of) == m]
            if len(tr) < 300 or te.empty:
                continue

            def design(R):
                return np.column_stack([np.ones(len(R)), np.log(R[f"gs_{s}_own"]),
                                        np.log(R[f"gs_{s}_allow"]), np.log(R[f"gs_{s}_f"])])
            b = G.fit_poisson(design(tr), tr[f"y_{s}"].astype(float).values)
            alpha = G.nb_alpha(tr[f"y_{s}"].astype(float).values, np.exp(design(tr) @ b))
            mu = np.exp(design(te) @ b)
            for k in (1, 2, 3) if s == "shots" else (1, 2):
                for idx, x in zip(te.index, mu):
                    out.setdefault(f"gs_{s}_{k}", {})[idx] = G.p_at_least(k, float(x), alpha)
    return pd.DataFrame(out).reindex(D.index)


def sources(D: pd.DataFrame, shrink: float, G: pd.DataFrame) -> dict:
    """leg -> DataFrame of (y, every source's chance) on starters from July (G: gs_chances)."""
    G = G.reindex(D.index)
    out = {}
    for leg, (s, k) in LEGS.items():
        h, n = D[f"rec_{s}_{k}_h"], D[f"rec_{s}_{k}_n"]
        X = pd.DataFrame({
            "y": (D[f"y_{s}"] >= k).astype(float),
            "record": h / n.where(n > 0),
            "shrunk": (h + shrink) / (n + 2 * shrink),
            "site": D[f"site_{s}_{k}"],
            "gs": G.get(f"gs_{s}_{k}", pd.Series(np.nan, index=D.index)) if s != "goals" else np.nan,
            "fmodel": D[f"fm_{s}_{k}"],
        })
        X["tonight"] = X.shrunk if s == "goals" else (X.shrunk + X.fmodel) / 2
        X["n"] = n
        X["ok"] = True if s == "goals" else D[f"cov_{s}"].fillna(False).astype(bool)
        out[leg] = X
    return out


# ----------------------------------------------------------- the fixes

def segments(D: pd.DataFrame) -> pd.DataFrame:
    """Pre-match features a calibration fix may use: minutes risk, rotation,
    penalties, position, sample size. Every one is known before kick-off."""
    return pd.DataFrame({
        "short_mins": (D.mins_avg5 < 70).astype(float),
        "rotation": (D.start_rate < 0.7).astype(float),
        "pen": D.pen_seen.fillna(False).astype(float),
        "fwd": (D.pos == "F").astype(float),
        "def": (D.pos == "D").astype(float),
        "thin": (D.n < 10).astype(float),
    }, index=D.index)


FIXES = {
    "none": None,
    "platt": [],
    "platt+minutes": ["short_mins", "rotation"],
    "platt+penalty": ["pen"],
    "platt+position": ["fwd", "def"],
    "platt+all": ["short_mins", "rotation", "pen", "fwd", "def", "thin"],
}


def _design(p, S, cols):
    z = _logit(p)
    return np.column_stack([np.ones(len(z)), z] + [S[c].values for c in cols])


def fit_fix(p, y, S, cols):
    return fit_logistic(_design(p, S, cols), y)


def apply_fix(b, p, S, cols):
    return _sig(_design(p, S, cols) @ b)


def walk_forward_fix(X, S, months, src="fmodel", fixes=None):
    """Each fix fitted on the months before each window and scored on it."""
    res = {}
    fixes = fixes or FIXES
    for i, m in enumerate(months):
        if i == 0:
            continue
        tr, te = X[X.month.isin(months[:i])], X[X.month == m]
        if len(tr) < 500 or len(te) < 200:
            continue
        for name, cols in fixes.items():
            if cols is None:
                p = te[src].values
            else:
                b = fit_fix(tr[src].values, tr.y.values, S.loc[tr.index], cols)
                p = apply_fix(b, te[src].values, S.loc[te.index], cols)
            res.setdefault(name, {})[m] = (log_loss(p, te.y), brier(p, te.y), len(te))
    return res



def blend_fix(X, months):
    """tonight.html's blend of shrunk record and fmodel: weight chosen on earlier months."""
    res = {}
    grid = np.linspace(0, 1, 11)
    for i, m in enumerate(months):
        if i == 0:
            continue
        tr, te = X[X.month.isin(months[:i])], X[X.month == m]
        if len(tr) < 500 or len(te) < 200:
            continue
        w = min(grid, key=lambda w: log_loss(w * tr.fmodel + (1 - w) * tr.shrunk, tr.y))
        for name, p in (("the page now", te.tonight), ("fitted weight", w * te.fmodel + (1 - w) * te.shrunk),
                        ("fmodel alone", te.fmodel)):
            res.setdefault(name, {})[m] = (log_loss(p, te.y), brier(p, te.y), len(te), w)
    return res


# =================================================================== report

def _f(x, d=4):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{d}f}"


def _pct(x):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{100 * x:.1f}%"


def _said_got(X, src, mask):
    sel = X[mask]
    if len(sel) == 0:
        return "", 0
    return f"{_pct(sel[src].mean())} / {_pct(sel.y.mean())}", len(sel)


def live_record(shrink):
    """Settled football player legs in best_bets.json: what the page said and what landed."""
    try:
        items = json.loads((ROOT / "best_bets.json").read_text())
    except (OSError, ValueError):
        return []
    uniq = {}
    for b in items:
        for leg in b.get("legs") or []:
            if (leg.get("sport") == "football" and leg.get("player") and leg.get("over", True)
                    and leg.get("stat") in ("Shots", "Shots on target", "Goals")
                    and leg.get("result") in ("win", "lose") and leg.get("fair")):
                uniq[(leg["event_id"], leg["player"], leg["stat"], leg["line"])] = leg
    rows = []
    for (_, _, stat, line), leg in uniq.items():
        rows.append({"stat": stat, "line": line, "said": 1 / leg["fair"],
                     "record": leg["hits"] / leg["total"],
                     "shrunk": (leg["hits"] + shrink) / (leg["total"] + 2 * shrink),
                     "y": 1.0 if leg["result"] == "win" else 0.0})
    return rows


def test() -> None:
    import weekend
    shrink = weekend.player_shrink()
    D = pd.read_pickle(DATA)
    # the game state is refitted before each month on everything earlier, so it sees the whole file
    G = gs_chances(D[D.starter == 1])
    D = D[D.ts >= OOS_FROM].copy()
    D["month"] = D.ts.map(month_of)
    starters = D[(D.starter == 1) & D.fm_shots_1.notna()]
    subs = D[D.starter == 0]
    S = segments(starters)
    src = sources(starters, shrink, G)
    months = sorted(starters.month.unique())
    L = []
    w = L.append
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    w("# Scorer audit: anytime goalscorer, shots and shots on target\n")
    w(f"Generated {gen} by `scorer_audit.py test`. Branch `scorer-audit`.\n")
    w(f"Every starter in every cached match from 1 July 2026 (when fmodel's training ended) to "
      f"{datetime.fromtimestamp(int(D.ts.max()), tz=timezone.utc):%d %B %Y}, replayed with only what "
      f"was known before kick-off: {starters.match.nunique():,} matches, {len(starters):,} starter rows, "
      f"plus {len(subs):,} substitute appearances. Months {', '.join(months)} are the walk-forward windows.\n")
    w("## What the page shows for each leg\n")
    w("| Source | What it is | Where the page uses it |\n|---|---|---|")
    w("| record | hits over his appearances of 45+ minutes in the last 38 | the 'k/n' beside every leg |")
    w(f"| shrunk | record pulled to 50% by {shrink:g} phantom hits and misses (weekend.player_shrink) | "
      "tonight.html rank (pShrunk) |")
    w("| site | model.price_player per 90 x minutes, calibrated; for to score the profile's scoreCase "
      "(60% xG, 40% goals per 90) | Players tab where fmodel has no chance |")
    w("| gs | gs_backtest.py's game-state model, refitted before each month on earlier 60+ minute rows | "
      "'Backtested model X%' where fmodel has none |")
    w("| fmodel | the backtested player model (fmodel/) | Players tab, Paddy Power value, every starter it covers |")
    w("| tonight | shrunk and fmodel averaged (shots, shots on target); shrunk alone for goals | "
      "tonight.html 'With the record' and its ranking |\n")
    w("Log loss and Brier: lower is better. Raw records of 0/n or n/n are clipped to 0.5% and 99.5% "
      "for log loss. ECE is the n-weighted gap between said and landed across ten-point bands. "
      "Shots and shots on target are only scored where the match carries player shot numbers.\n")

    # ------------------------------------------------- 1. head to head
    w("## 1. Head to head, same rows\n")
    w(f"Starters with a record of {TONIGHT_MIN_SAMPLE}+ appearances (the floor tonight.html uses) and, "
      "for shots, the inputs the game-state model needs, so every source is scored on identical rows.\n")
    w("| Leg | n | landed | metric | record | shrunk | site | gs | fmodel | tonight |\n|---|---|---|---|---|---|---|---|---|---|")
    head = {}
    for leg, X in src.items():
        cols = [c for c in SOURCES if not (leg == "Anytime goalscorer" and c == "gs")]
        Xc = X[X.ok & (X.n >= TONIGHT_MIN_SAMPLE)].dropna(subset=cols)
        head[leg] = Xc
        for mname, fn in (("log loss", log_loss), ("Brier", brier), ("ECE", ece)):
            cells = []
            for c in SOURCES:
                cells.append(_f(fn(Xc[c], Xc.y)) if c in cols else "n/a")
            w(f"| {leg if mname == 'log loss' else ''} | {len(Xc) if mname == 'log loss' else ''} | "
              f"{_pct(Xc.y.mean()) if mname == 'log loss' else ''} | {mname} | " + " | ".join(cells) + " |")
    w("")
    w("### fmodel on every starter it covers\n")
    w("The Players tab shows fmodel for any starter with three 45-minute appearances, not only those with ten.\n")
    w("| Leg | n | landed | said | log loss | Brier | ECE | base-rate log loss |\n|---|---|---|---|---|---|---|---|")
    for leg, X in src.items():
        Xc = X[X.ok & X.fmodel.notna()]
        base = np.full(len(Xc), Xc.y.mean())
        w(f"| {leg} | {len(Xc):,} | {_pct(Xc.y.mean())} | {_pct(Xc.fmodel.mean())} | {_f(log_loss(Xc.fmodel, Xc.y))} | "
          f"{_f(brier(Xc.fmodel, Xc.y))} | {_f(ece(Xc.fmodel, Xc.y))} | {_f(log_loss(base, Xc.y))} |")
    w("")

    # ------------------------------------------------- 2. calibration bands
    w("## 2. Calibration by chance band\n")
    w("Said / landed (n) per band, on the head-to-head rows. A band where landed is below said is overconfident.\n")
    for leg, Xc in head.items():
        w(f"### {leg}\n")
        w("| Band | fmodel | tonight | shrunk | record | site |\n|---|---|---|---|---|---|")
        for lo, hi in zip(BANDS[:-1], BANDS[1:]):
            cells = []
            for c in ("fmodel", "tonight", "shrunk", "record", "site"):
                sel = (Xc[c] >= lo) & (Xc[c] < hi)
                cells.append(f"{_pct(Xc[c][sel].mean())} / {_pct(Xc.y[sel].mean())} ({sel.sum()})" if sel.sum() >= 30 else "")
            if any(cells):
                w(f"| {lo:.0%}-{min(hi, 1):.0%} | " + " | ".join(cells) + " |")
        w("")

    # ------------------------------------------------- 3. segments
    def seg_table(title, note, groups, legs=LEGS):
        w(f"## {title}\n")
        if note:
            w(note + "\n")
        w("| Leg | Group | n | fmodel said / landed | gap | tonight said / landed | gap | fmodel log loss |\n"
          "|---|---|---|---|---|---|---|---|")
        for leg in legs:
            X = src[leg]
            X = X[X.ok & X.fmodel.notna()]
            for gname, mask in groups(X):
                sel = X[mask.reindex(X.index).fillna(False).astype(bool)]
                if len(sel) < 100:
                    continue
                tn = sel.dropna(subset=["tonight"])
                gap_f = sel.y.mean() - sel.fmodel.mean()
                gap_t = tn.y.mean() - tn.tonight.mean() if len(tn) else float("nan")
                w(f"| {leg} | {gname} | {len(sel):,} | {_pct(sel.fmodel.mean())} / {_pct(sel.y.mean())} | "
                  f"{100 * gap_f:+.1f} | {_pct(tn.tonight.mean()) if len(tn) else 'n/a'} / {_pct(tn.y.mean()) if len(tn) else 'n/a'} | "
                  f"{'n/a' if math.isnan(gap_t) else f'{100 * gap_t:+.1f}'} | {_f(log_loss(sel.fmodel, sel.y))} |")
        w("")

    pos_name = {"D": "defender", "M": "midfielder", "F": "forward"}
    seg_table("3. By position", "Gap is landed minus said, in points: negative means the page was too high.",
              lambda X: [(pos_name[p], starters.pos == p) for p in "DMF"])
    seg_table("4. By minutes expectation",
              "Average minutes over his last five appearances (all appearances, cameos included), known before kick-off.",
              lambda X: [("under 60", starters.mins_avg5 < 60),
                         ("60 to 74", (starters.mins_avg5 >= 60) & (starters.mins_avg5 < 75)),
                         ("75 to 84", (starters.mins_avg5 >= 75) & (starters.mins_avg5 < 85)),
                         ("85 plus", starters.mins_avg5 >= 85)])
    top = starters.league.value_counts()
    top = [lg for lg in top.index if top[lg] >= 600][:14]
    seg_table("5. By league", "Leagues with 600+ starter rows since July.",
              lambda X: [(lg, starters.league == lg) for lg in top],
              legs=["Anytime goalscorer", "Shots 1+", "Shots on target 1+"])

    # ------------------------------------------------- 6. why
    w("## 6. Where the misses come from\n")
    w("### Minutes risk, after the event\n")
    w("Not usable before kick-off: this splits the same rows by the minutes he actually played, "
      "to show how much of the miss rate is an early substitution or injury rather than a bad read of the player.\n")
    w("| Leg | Played | share of starts | fmodel said / landed | gap |\n|---|---|---|---|---|")
    for leg in LEGS:
        X = src[leg]
        X = X[X.ok & X.fmodel.notna()]
        mins = starters.y_mins.reindex(X.index)
        for gname, mask in (("under 45", mins < 45), ("45 to 69", (mins >= 45) & (mins < 70)),
                            ("70 to 84", (mins >= 70) & (mins < 85)), ("85 plus", mins >= 85)):
            sel = X[mask]
            if len(sel) < 50:
                continue
            w(f"| {leg} | {gname} | {_pct(len(sel) / len(X))} | {_pct(sel.fmodel.mean())} / {_pct(sel.y.mean())} | "
              f"{100 * (sel.y.mean() - sel.fmodel.mean()):+.1f} |")
    w("")
    seg_table("Rotation risk before kick-off",
              "Share of his last ten appearances that were starts. A starter who usually comes off the bench "
              "is more likely to be taken off early.",
              lambda X: [("started under 70% of last ten", starters.start_rate < 0.7),
                         ("started 70%+", starters.start_rate >= 0.7)])
    seg_table("Penalties", "A penalty seen in his last 38 appearances: one shot worth a penalty's xG (0.76 or 0.79). "
              "This catches only penalties taken in one-shot games, so it marks a subset of takers.",
              lambda X: [("penalty seen", starters.pen_seen.fillna(False).astype(bool)),
                         ("none seen", ~starters.pen_seen.fillna(False).astype(bool))],
              legs=["Anytime goalscorer", "Shots on target 1+"])

    w("### Small samples\n")
    w("By the number of 45-minute appearances behind the record. fmodel needs three; tonight.html needs ten.\n")
    w("| Leg | Record n | rows | record said / landed | shrunk said / landed | fmodel said / landed | "
      "record LL | shrunk LL | fmodel LL |\n|---|---|---|---|---|---|---|---|---|")
    for leg in LEGS:
        X = src[leg]
        X = X[X.ok & X.fmodel.notna() & X.record.notna()]
        for gname, lo, hi in (("3 to 5", 3, 6), ("6 to 9", 6, 10), ("10 to 19", 10, 20), ("20 plus", 20, 999)):
            sel = X[(X.n >= lo) & (X.n < hi)]
            if len(sel) < 100:
                continue
            w(f"| {leg} | {gname} | {len(sel):,} | {_pct(sel.record.mean())} / {_pct(sel.y.mean())} | "
              f"{_pct(sel.shrunk.mean())} / {_pct(sel.y.mean())} | {_pct(sel.fmodel.mean())} / {_pct(sel.y.mean())} | "
              f"{_f(log_loss(sel.record, sel.y))} | {_f(log_loss(sel.shrunk, sel.y))} | {_f(log_loss(sel.fmodel, sel.y))} |")
    w("")

    w("### Substitutes\n")
    w("Players who came off the bench, priced on the same record tonight.html uses for any player with ten "
      "appearances (fmodel scores starters only). Paddy Power voids a non-starter's bet; a book that lets it "
      "stand is settling it at these rates.\n")
    w("| Leg | n | record said | shrunk said | landed | median minutes |\n|---|---|---|---|---|---|")
    for leg, (s, k) in LEGS.items():
        h, n = subs[f"rec_{s}_{k}_h"], subs[f"rec_{s}_{k}_n"]
        ok = (n >= TONIGHT_MIN_SAMPLE) & (True if s == "goals" else subs[f"cov_{s}"].fillna(False).astype(bool))
        sel = subs[ok]
        if len(sel) < 50:
            continue
        rec = (h / n)[ok]
        sh = ((h + shrink) / (n + 2 * shrink))[ok]
        y = (sel[f"y_{s}"] >= k).astype(float)
        w(f"| {leg} | {len(sel):,} | {_pct(rec.mean())} | {_pct(sh.mean())} | {_pct(y.mean())} | {sel.y_mins.median():.0f} |")
    w("")

    # ------------------------------------------------- 7. the fix
    w("## 7. Calibration fixes, walk-forward\n")
    w("Each fix is fitted on every month before a window and scored on that window. A fix is chosen on "
      "August (fitted on July alone) and must then beat leaving fmodel alone on both September and October, "
      "on log loss and Brier, to be wired in. Fixes: Platt (logit a + b logit p), and Platt with "
      "pre-match terms for minutes and rotation, penalties, position, or all of them plus a thin record.\n")
    w("Log loss by window (Brier in brackets):\n")
    decisions = {}
    for leg in LEGS:
        X = src[leg]
        X = X[X.ok & X.fmodel.notna()].copy()
        X["month"] = starters.month.reindex(X.index)
        Sx = S.loc[X.index]
        res = walk_forward_fix(X, Sx, months)
        wins = [m for m in months[1:] if m in res.get("none", {})]
        if len(wins) < 3:
            continue
        sel_m, later = wins[0], wins[1:]
        w(f"### {leg}\n")
        w("| Fix | " + " | ".join(wins) + " | chosen on " + sel_m + " | holds later |\n|---|" + "---|" * (len(wins) + 2))
        pick = min((nm for nm in res if nm != "none"), key=lambda nm: res[nm][sel_m][0])
        beats_sel = res[pick][sel_m][0] < res["none"][sel_m][0] - 1e-4
        holds = beats_sel and all(res[pick][m][0] < res["none"][m][0] and res[pick][m][1] <= res["none"][m][1]
                                  for m in later)
        for nm, r in res.items():
            cells = [f"{r[m][0]:.4f} ({r[m][1]:.4f})" for m in wins]
            w(f"| {nm} | " + " | ".join(cells) + f" | {'picked' if nm == pick else ''} | "
              f"{('yes' if holds else 'no') if nm == pick else ''} |")
        decisions[leg] = {"pick": pick, "beats_on_selection": bool(beats_sel), "holds": bool(holds),
                          "ll_none": {m: res["none"][m][0] for m in wins},
                          "ll_pick": {m: res[pick][m][0] for m in wins}}
        w("")
        w(f"Decision: {'wire in ' + pick if holds else 'leave fmodel as it is'} "
          f"({'it beat no fix on ' + sel_m + ' and on every later window' if holds else ('nothing beat no fix on ' + sel_m if not beats_sel else pick + ' did not hold on every later window')}).\n")

    w("### tonight.html's blend\n")
    w("tonight.html averages the shrunk record and fmodel half and half for shots and shots on target, and "
      "shows the shrunk record alone for to score. The weight on fmodel is chosen on the months before each "
      "window (grid of tenths) and scored on the window, against the page now and fmodel alone. It is wired in "
      "only if the fitted weight beats the page on every window. Log loss:\n")
    blend_dec = {}
    w("| Leg | Blend | " + " | ".join(months[1:]) + " | weight chosen |\n|---|---|" + "---|" * len(months))
    for leg in LEGS:
        Xc = head[leg].copy()
        Xc["month"] = starters.month.reindex(Xc.index)
        res = blend_fix(Xc, months)
        wins = [m for m in months[1:] if m in res.get("fitted weight", {})]
        for nm, r in res.items():
            ws = ", ".join(f"{r[m][3]:.1f}" for m in wins) if nm == "fitted weight" else ""
            w(f"| {leg} | {nm} | " + " | ".join(f"{r[m][0]:.4f} ({r[m][1]:.4f})" if m in r else "" for m in months[1:])
              + f" | {ws} |")
        holds = bool(wins) and all(res["fitted weight"][m][0] < res["the page now"][m][0] and
                                   res["fitted weight"][m][1] <= res["the page now"][m][1] for m in wins)
        grid = np.linspace(0, 1, 11)
        w_all = float(min(grid, key=lambda x: log_loss(x * Xc.fmodel + (1 - x) * Xc.shrunk, Xc.y)))
        blend_dec[leg] = {"windows": wins, "holds": holds, "weight": round(w_all, 1),
                          "ll_now": {m: res["the page now"][m][0] for m in wins},
                          "ll_fitted": {m: res["fitted weight"][m][0] for m in wins}}
    w("")
    w("| Leg | beats the page on every window | weight on fmodel, fitted on July to October |\n|---|---|---|")
    for leg, d in blend_dec.items():
        w(f"| {leg} | {'yes' if d['holds'] else 'no'} | {d['weight']:.1f} |")
    w("")
    w("Scored on the same rows with the weight fitted on July to October (in sample, for the record):\n")
    w("| Leg | n | the page now: said / landed, log loss | fitted weight: said / landed, log loss |\n|---|---|---|---|")
    for leg, d in blend_dec.items():
        Xc = head[leg]
        p = d["weight"] * Xc.fmodel + (1 - d["weight"]) * Xc.shrunk
        w(f"| {leg} | {len(Xc):,} | {_pct(Xc.tonight.mean())} / {_pct(Xc.y.mean())}, {_f(log_loss(Xc.tonight, Xc.y))} | "
          f"{_pct(p.mean())} / {_pct(Xc.y.mean())}, {_f(log_loss(p, Xc.y))} |")
    w("")

    w("### The Players tab's own chance, where fmodel has none\n")
    w("For a player fmodel cannot see (not in the predicted or confirmed XI, under three full games, or before "
      "any line-up is out) the Players tab prices shots and shots on target with pricePlayer and to score with "
      "scoreCase. Section 2 shows both run high on every line but shots 1+. The fix tried is a Platt map per line, "
      "fitted on starters (Paddy Power settles a player bet only if he starts), chosen on August and wired in "
      "only if it beats the page on September and October on log loss and Brier. A position term helps a "
      "little more but the page's fallback does not carry the position, so it is not offered. Log loss (Brier):\n")
    site_dec = {}
    w("| Leg | Fix | " + " | ".join(months[1:]) + " | holds |\n|---|---|" + "---|" * len(months))
    for leg in LEGS:
        X = src[leg]
        X = X[X.ok & X.site.notna()].copy()
        X["month"] = starters.month.reindex(X.index)
        Sx = S.loc[X.index]
        res = walk_forward_fix(X, Sx, months, src="site", fixes={"none": None, "platt": []})
        wins = [m for m in months[1:] if m in res.get("none", {})]
        holds = bool(wins) and all(res["platt"][m][0] < res["none"][m][0] and res["platt"][m][1] <= res["none"][m][1]
                                   for m in wins)
        for nm, r in res.items():
            w(f"| {leg} | {nm} | " + " | ".join(f"{r[m][0]:.4f} ({r[m][1]:.4f})" for m in wins)
              + f" | {('yes' if holds else 'no') if nm == 'platt' else ''} |")
        b = fit_fix(X.site.values, X.y.values, Sx, [])
        site_dec[leg] = {"holds": holds, "coef": [round(float(x), 4) for x in b], "n": int(len(X))}
    w("")
    w("| Leg | wired | a | b | said / landed before | after, same rows (in sample) |\n|---|---|---|---|---|---|")
    for leg, d in site_dec.items():
        X = src[leg]
        X = X[X.ok & X.site.notna()]
        after = _sig(d["coef"][0] + d["coef"][1] * _logit(X.site))
        w(f"| {leg} | {'yes' if d['holds'] else 'no'} | {d['coef'][0]:+.4f} | {d['coef'][1]:.4f} | "
          f"{_pct(X.site.mean())} / {_pct(X.y.mean())} | {_pct(after.mean())} / {_pct(X.y.mean())} |")
    w("")

    # ------------------------------------------------- 8. live
    live = live_record(shrink)
    w("## 8. The live record\n")
    w("Settled football player legs the page picked (best_bets.json), one per player, stat and line. These are "
      "chosen legs, so the best-looking of many: expect them to land below what was said.\n")
    if live:
        Lv = pd.DataFrame(live)
        w("| Leg | n | page said | record | shrunk | landed |\n|---|---|---|---|---|---|")
        for (stat, line), g in Lv.groupby(["stat", "line"]):
            if len(g) < 5:
                continue
            w(f"| {stat} {line + 0.5:.0f}+ | {len(g)} | {_pct(g.said.mean())} | {_pct(g.record.mean())} | "
              f"{_pct(g.shrunk.mean())} | {_pct(g.y.mean())} |")
        w(f"| all | {len(Lv)} | {_pct(Lv.said.mean())} | {_pct(Lv.record.mean())} | {_pct(Lv.shrunk.mean())} | "
          f"{_pct(Lv.y.mean())} |")
    w("")

    # ------------------------------------------------- save
    (CACHE / "scorer_audit_result.json").write_text(json.dumps(
        {"generated": gen, "fmodel_fixes": decisions, "blend": blend_dec, "site": site_dec}, indent=1))
    site = {SITE_KEY[leg]: d["coef"] for leg, d in site_dec.items() if d["holds"]}
    if site:
        SITE.write_text(json.dumps({
            "generated": gen, "source": "scorer_audit.py test",
            "note": "Platt map (logit p' = a + b logit p) on the Players tab's own chance where fmodel has none: "
                    "pricePlayer for 'Shots|k' and 'Shots on target|k', scoreCase for 'score|1'. Only lines where "
                    "a map chosen on earlier months beat the page on every later month.",
            "maps": site}, indent=1) + "\n")
    wired = {LEG_KEY[leg]: d["weight"] for leg, d in blend_dec.items() if d["holds"]}
    if wired:
        BLEND.write_text(json.dumps({
            "generated": gen, "source": "scorer_audit.py test",
            "note": "Weight on fmodel in tonight.html's player chance (the rest on the shrunk record). "
                    "Only legs where a weight chosen on earlier months beat the half and half on every later month.",
            "weights": wired}, indent=1) + "\n")
    # the written verdict above the marker is kept; the tables below it are regenerated
    head_text = ""
    if REPORT.exists() and MARKER in REPORT.read_text():
        head_text = REPORT.read_text().split(MARKER)[0]
    REPORT.write_text(head_text + MARKER + "\n\n" + "\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    {"build": build, "test": test}[cmd]()
