"""
NBA game state: pace, ratings, expected total and margin, blowout risk,
schedule and altitude, strictly from earlier games.

    import usgame
    G = usgame.team_features(M, T, P)          # one row per (match, team), pre-game
    X = usgame.player_features(F, P, G)        # adds the player-level interactions to F

Shared by the backtest and usmodel_live.py through usfeatures.features, so the
live chances use exactly what was trained on.

Possessions per team-game: FGA + 0.44 FTA - offensive rebounds + turnovers,
summed from the player box scores (the team table keeps makes, not attempts).
A game's pace is the mean of both sides' possessions.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque

import numpy as np
import pandas as pd

WINDOW = 10
BLOWOUT = 15          # final margin that counts as a blowout
ALTITUDE = {"Denver Nuggets", "Utah Jazz"}


def _poss(P: pd.DataFrame) -> pd.DataFrame:
    need = ["fga", "fta", "oreb", "turnovers", "points", "mins"]
    have = [c for c in need if c in P.columns]
    g = P[P.mins.fillna(0) > 0].groupby(["match", "team"])[have].sum().reset_index()
    g["poss"] = g.fga + 0.44 * g.fta - g.oreb + g.turnovers
    return g[["match", "team", "poss", "points"]]


def _m(hh, k):
    v = [x[k] for x in hh if x.get(k) is not None and not (isinstance(x[k], float) and math.isnan(x[k]))]
    return float(np.mean(v)) if v else np.nan


def _feat(hist, last_games, team, opp, ts) -> dict:
    """One side's game state before a game, from the histories so far."""
    h, ho = list(hist[team]), list(hist[opp])
    pace_me, pace_op = _m(h, "pace"), _m(ho, "pace")
    ortg_me = 100 * _m(h, "pts_for") / pace_me if pace_me else np.nan
    drtg_me = 100 * _m(h, "pts_against") / pace_me if pace_me else np.nan
    ortg_op = 100 * _m(ho, "pts_for") / pace_op if pace_op else np.nan
    drtg_op = 100 * _m(ho, "pts_against") / pace_op if pace_op else np.nan
    exp_pace = np.nanmean([pace_me, pace_op]) if not (np.isnan(pace_me) and np.isnan(pace_op)) else np.nan
    exp_for = exp_pace * np.nanmean([ortg_me, drtg_op]) / 100 if exp_pace == exp_pace else np.nan
    exp_against = exp_pace * np.nanmean([ortg_op, drtg_me]) / 100 if exp_pace == exp_pace else np.nan
    both = exp_for == exp_for and exp_against == exp_against
    recent = [t for t in last_games[team] if ts - t <= 4 * 86400]
    recent_o = [t for t in last_games[opp] if ts - t <= 4 * 86400]
    rest_me = (ts - last_games[team][-1]) / 86400 if last_games[team] else np.nan
    rest_op = (ts - last_games[opp][-1]) / 86400 if last_games[opp] else np.nan
    margins = [x["margin"] for x in h if x.get("margin") == x.get("margin")]
    margins_o = [x["margin"] for x in ho if x.get("margin") == x.get("margin")]
    return {
        "g_pace_me": pace_me, "g_pace_op": pace_op, "g_exp_pace": exp_pace,
        "g_pace_ratio": exp_pace / pace_me if pace_me else np.nan,
        "g_ortg_me": ortg_me, "g_drtg_me": drtg_me, "g_ortg_op": ortg_op, "g_drtg_op": drtg_op,
        "g_exp_for": exp_for, "g_exp_against": exp_against,
        "g_exp_total": exp_for + exp_against if both else np.nan,
        "g_exp_margin": exp_for - exp_against if both else np.nan,
        "g_exp_margin_abs": abs(exp_for - exp_against) if both else np.nan,
        "g_blowout_rate_me": float(np.mean([abs(x) >= BLOWOUT for x in margins])) if margins else np.nan,
        "g_blowout_rate_op": float(np.mean([abs(x) >= BLOWOUT for x in margins_o])) if margins_o else np.nan,
        "g_games_4d": len(recent), "g_games_4d_op": len(recent_o),
        "g_rest_diff": (rest_me - rest_op) if rest_me == rest_me and rest_op == rest_op else np.nan,
        "g_lead_time_me": _m(h, "f_Time spent in lead"), "g_lead_time_op": _m(ho, "f_Time spent in lead"),
    }


def _prepared(T: pd.DataFrame, P: pd.DataFrame) -> pd.DataFrame:
    po = _poss(P)
    T2 = T.merge(po[["match", "team", "poss"]], on=["match", "team"], how="left")
    opp_poss = po.rename(columns={"team": "opp", "poss": "opp_poss"})[["match", "opp", "opp_poss"]]
    T2 = T2.merge(opp_poss, on=["match", "opp"], how="left")
    T2["pace"] = T2[["poss", "opp_poss"]].mean(axis=1)
    T2["margin"] = T2.pts_for - T2.pts_against
    return T2.sort_values(["ts", "match"])


def replay(T: pd.DataFrame, P: pd.DataFrame, rows: list | None = None):
    """Walk every finished game in order; return the histories (and pre-game rows if asked)."""
    hist = defaultdict(lambda: deque(maxlen=WINDOW))
    last_games = defaultdict(list)
    for mid, g in _prepared(T, P).groupby("match", sort=False):
        recs = g.to_dict("records")
        if rows is not None:
            for r in recs:
                rows.append({"match": mid, "team": r["team"], **_feat(hist, last_games, r["team"], r["opp"], r["ts"])})
        for r in recs:
            hist[r["team"]].append(r)
            last_games[r["team"]].append(r["ts"])
    return hist, last_games


def team_features(M: pd.DataFrame, T: pd.DataFrame, P: pd.DataFrame) -> pd.DataFrame:
    """Pre-game state for every finished (match, team): the training rows."""
    rows: list = []
    replay(T, P, rows)
    return pd.DataFrame(rows)


def upcoming(T: pd.DataFrame, P: pd.DataFrame, games: list[dict]) -> dict:
    """{(match, team): features} for games not yet played, from every finished game."""
    hist, last_games = replay(T, P)
    out = {}
    for g in games:
        for team, opp in ((g["home"], g["away"]), (g["away"], g["home"])):
            out[(g["match"], team)] = _feat(hist, last_games, team, opp, g["ts"])
    return out


def player_features(F: pd.DataFrame, P: pd.DataFrame, G: pd.DataFrame, M: pd.DataFrame | None = None) -> pd.DataFrame:
    """Merge the team game state onto player rows, plus each player's minutes in blowouts."""
    X = F.merge(G, on=["match", "team"], how="left")
    # His minutes in blowouts against close games, from earlier games only.
    po = P[P.mins.fillna(0) > 0][["match", "ts", "pid", "team", "mins"]].copy()
    T_margin = None
    if M is not None and {"hs", "as"}.issubset(M.columns):
        T_margin = None
    games = P.groupby(["match", "team"]).points.sum().reset_index()
    opp = games.rename(columns={"team": "opp_t", "points": "opp_pts"})
    gm = games.merge(opp, on="match")
    gm = gm[gm.team != gm.opp_t]
    gm["absm"] = (gm.points - gm.opp_pts).abs()
    po = po.merge(gm[["match", "team", "absm"]], on=["match", "team"], how="left").sort_values("ts")
    hist = defaultdict(list)
    out = {}
    want = set(zip(F.match, F.pid))
    for r in po.itertuples(index=False):
        if (r.match, r.pid) in want:
            h = hist[r.pid][-20:]
            blow = [x for x in h if x[1] >= 15]
            close = [x for x in h if x[1] < 8]
            mb = np.mean([x[0] for x in blow]) if len(blow) >= 2 else np.nan
            mc = np.mean([x[0] for x in close]) if len(close) >= 2 else np.nan
            out[(r.match, r.pid)] = (mb / mc if mc and mb == mb else np.nan, len(blow))
        hist[r.pid].append((r.mins, r.absm if r.absm == r.absm else 0))
    # rows with no box yet (upcoming): use his history up to now
    for (mid, pid) in want - set(out):
        h = hist[pid][-20:]
        blow = [x for x in h if x[1] >= 15]
        close = [x for x in h if x[1] < 8]
        mb = np.mean([x[0] for x in blow]) if len(blow) >= 2 else np.nan
        mc = np.mean([x[0] for x in close]) if len(close) >= 2 else np.nan
        out[(mid, pid)] = (mb / mc if mc and mb == mb else np.nan, len(blow))
    X["g_blowout_mins_ratio"] = [out.get((m, p), (np.nan, 0))[0] for m, p in zip(X.match, X.pid)]
    X["g_blowout_risk_x_mins"] = X.g_exp_margin_abs * (1 - X.g_blowout_mins_ratio.fillna(1))
    X["g_pace_x_usage"] = X.g_pace_ratio * X.get("usage_m10", pd.Series(np.nan, index=X.index))
    return X


# ------------------------------------------------------------ live team model

TEAM_STATS = {"pts_for": "Points", "f_Rebounds": "Rebounds", "f_Assists": "Assists", "f_3 pointers": "3 pointers",
              "f_Steals": "Steals", "f_Blocks": "Blocks", "f_Turnovers": "Turnovers", "f_Free throws": "Free throws"}
TEAM_OPP = {"pts_for": "pts_against", **{k: "a_" + k[2:] for k in TEAM_STATS if k.startswith("f_")}}


def _nb_ge(k: int, mu: float, a: float) -> float:
    if k <= 0:
        return 1.0
    if a < 1e-6:
        cdf, term = 0.0, math.exp(-mu)
        for i in range(k):
            cdf += term
            term *= mu / (i + 1)
        return max(0.0, 1 - cdf)
    r = 1 / a
    p = r / (r + mu)
    cdf, term = 0.0, p ** r
    for i in range(k):
        cdf += term
        term *= (i + r) / (i + 1) * (1 - p)
    return max(0.0, 1 - cdf)


def nba_teams(T: pd.DataFrame, P: pd.DataFrame, games: list[dict], names: dict, models_dir) -> dict:
    """{match: {"state": {team name: game state}, "teams": {team name: {stat: {"mu", "lines"}}}}}.

    Linear or game-state model per stat as nba_team_train.py chose; NB spread.
    Same features as training: usgame.upcoming for the game state, and each
    side's last-10 own and the opponent's last-10 conceded from T.
    """
    import gzip
    import json as _json
    from pathlib import Path as _P
    models_dir = _P(models_dir)
    meta = _json.loads((models_dir / "nba_team.json").read_text())
    trees = {}
    for k, e in meta["stats"].items():
        if e.get("use") == "gbm":
            from fmodel.fmodel_trees import Tree
            with gzip.open(models_dir / f"nba_team_{e['page_stat'].lower().replace(' ', '_')}.json.gz", "rt") as fh:
                d = _json.load(fh)
            trees[k] = [Tree(t["tree_structure"]) for t in d["tree_info"]]
    gs = upcoming(T, P, games)
    Ts = T.sort_values("ts")
    by_team = {t: g for t, g in Ts.groupby("team")}
    out = {}
    for g in games:
        ev = out.setdefault(str(g["match"]), {"state": {}, "teams": {}})
        for team, opp, home in ((g["home"], g["away"], 1), (g["away"], g["home"], 0)):
            name = names.get(team, str(team))
            st = gs.get((g["match"], team), {})
            ev["state"][name] = {k: (None if v != v else round(float(v), 3)) for k, v in st.items()}
            mine = by_team.get(team)
            theirs = by_team.get(opp)
            if mine is None or theirs is None:
                continue
            mine, theirs = mine[mine.ts < g["ts"]].tail(10), theirs[theirs.ts < g["ts"]].tail(10)
            tm = {}
            for k, e in meta["stats"].items():
                v, a = mine[k].dropna(), theirs[TEAM_OPP[k]].dropna()
                if len(v) < 5 or len(a) < 5:
                    continue
                own, allow = float(v.mean()), float(a.mean())
                if e["use"] == "gbm":
                    row = {"own_" + k: own, "allow_" + k: allow, "home": float(home), **st}
                    X = np.array([[float(row.get(f, np.nan)) if row.get(f) is not None else np.nan for f in e["features"]]])
                    mu = own * math.exp(sum(t.predict(X)[0] for t in trees[k]))
                else:
                    c = e["coef"]
                    eta = c[0] + c[1] * math.log(own) + c[2] * math.log(allow) + c[3] * home
                    if e.get("pace"):
                        pr = st.get("g_pace_ratio")
                        eta += c[4] * math.log(min(1.2, max(0.8, pr if pr == pr and pr else 1.0)))
                    mu = math.exp(eta)
                lo, hi = max(1, int(mu * 0.6)), int(mu * 1.4) + 3
                tm[e["page_stat"]] = {"mu": round(mu, 2), "model": e["use"],
                                      "lines": {str(kk): round(_nb_ge(kk, mu, e["alpha"]), 4) for kk in range(lo, hi + 1)}}
            ev["teams"][name] = tm
    return out
