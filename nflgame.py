"""
NFL game script: plays, pass rate, expected margin, how a team's play-calling
moves when ahead or behind, short weeks and byes, strictly from earlier games.

    import nflgame
    G = nflgame.team_features(T, P)              # (match, team) rows, pre-game
    U = nflgame.upcoming(T, P, games)           # same, for games not yet played

Plays per team-game are pass attempts plus rushing attempts from the player
box scores. One module for the backtest and the live scorer.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque

import numpy as np
import pandas as pd

WINDOW = 10
SCRIPT_WINDOW = 24
SWING = 8


def _team_games(T: pd.DataFrame, P: pd.DataFrame) -> pd.DataFrame:
    p = P[P.has_stats == 1] if "has_stats" in P.columns else P
    g = p.groupby(["match", "team"])[["pass_att", "rush_att"]].sum().reset_index()
    T2 = T.merge(g, on=["match", "team"], how="left")
    T2["plays"] = T2.pass_att + T2.rush_att
    T2["pass_rate"] = T2.pass_att / T2.plays.where(T2.plays > 0)
    T2["margin"] = T2.pts_for - T2.pts_against
    opp = T2[["match", "team", "plays", "pass_rate"]].rename(
        columns={"team": "opp", "plays": "opp_plays", "pass_rate": "opp_pass_rate"})
    T2 = T2.merge(opp, on=["match", "opp"], how="left")
    return T2.sort_values(["ts", "match"])


def _m(h, k):
    v = [x[k] for x in h if x.get(k) is not None and not (isinstance(x[k], float) and math.isnan(x[k]))]
    return float(np.mean(v)) if v else np.nan


def _sens(h):
    lost = [x["pass_rate"] for x in h if x.get("margin", 0) <= -SWING and x.get("pass_rate") == x.get("pass_rate")]
    won = [x["pass_rate"] for x in h if x.get("margin", 0) >= SWING and x.get("pass_rate") == x.get("pass_rate")]
    if len(lost) >= 2 and len(won) >= 2:
        return float(np.mean(lost) - np.mean(won))
    return np.nan


def _feat(hist, long_hist, last, team, opp, ts, home) -> dict:
    h, ho = list(hist[team]), list(hist[opp])
    pf, pa = _m(h, "pts_for"), _m(h, "pts_against")
    opf, opa = _m(ho, "pts_for"), _m(ho, "pts_against")
    exp_for = np.nanmean([pf, opa]) if not (np.isnan(pf) and np.isnan(opa)) else np.nan
    exp_against = np.nanmean([opf, pa]) if not (np.isnan(opf) and np.isnan(pa)) else np.nan
    margin = exp_for - exp_against + (1.5 if home else -1.5) if exp_for == exp_for and exp_against == exp_against else np.nan
    sens = _sens(list(long_hist[team]))
    plays_me, plays_allowed_op = _m(h, "plays"), _m(ho, "opp_plays")
    rest = (ts - last[team]) / 86400 if team in last else np.nan
    rest_o = (ts - last[opp]) / 86400 if opp in last else np.nan
    return {
        "s_plays_me": plays_me, "s_plays_op": _m(ho, "plays"), "s_plays_allowed_op": plays_allowed_op,
        "s_exp_plays": np.nanmean([plays_me, plays_allowed_op]) if not (np.isnan(plays_me) and np.isnan(plays_allowed_op)) else np.nan,
        "s_plays_ratio": (np.nanmean([plays_me, plays_allowed_op]) / plays_me) if plays_me else np.nan,
        "s_pass_rate_me": _m(h, "pass_rate"), "s_pass_rate_faced_op": _m(ho, "opp_pass_rate"),
        "s_exp_for": exp_for, "s_exp_against": exp_against, "s_exp_margin": margin,
        "s_script_sens": sens,
        "s_script_push": (sens * -margin / 10) if sens == sens and margin == margin else np.nan,
        "s_rest": min(rest, 21) if rest == rest else np.nan,
        "s_short_week": float(rest <= 5) if rest == rest else np.nan,
        "s_bye": float(rest >= 12) if rest == rest else np.nan,
        "s_rest_diff": (min(rest, 21) - min(rest_o, 21)) if rest == rest and rest_o == rest_o else np.nan,
        "s_top_me": _m(h, "f_Time of Possession"),
    }


def _replay(T, P, rows=None):
    hist = defaultdict(lambda: deque(maxlen=WINDOW))
    long_hist = defaultdict(lambda: deque(maxlen=SCRIPT_WINDOW))
    last = {}
    for mid, g in _team_games(T, P).groupby("match", sort=False):
        recs = g.to_dict("records")
        if rows is not None:
            for r in recs:
                rows.append({"match": mid, "team": r["team"],
                             **_feat(hist, long_hist, last, r["team"], r["opp"], r["ts"], bool(r["home"]))})
        for r in recs:
            hist[r["team"]].append(r)
            long_hist[r["team"]].append(r)
            last[r["team"]] = r["ts"]
    return hist, long_hist, last


def team_features(T: pd.DataFrame, P: pd.DataFrame) -> pd.DataFrame:
    rows: list = []
    _replay(T, P, rows)
    return pd.DataFrame(rows)


def upcoming(T: pd.DataFrame, P: pd.DataFrame, games: list[dict]) -> dict:
    hist, long_hist, last = _replay(T, P)
    out = {}
    for g in games:
        for team, opp, home in ((g["home"], g["away"], True), (g["away"], g["home"], False)):
            out[(g["match"], team)] = _feat(hist, long_hist, last, team, opp, g["ts"], home)
    return out
