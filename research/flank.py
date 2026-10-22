"""
Flank and involvement features, strictly from earlier matches.

Sides come from each starter's formation slot: lat 0 = right, 1 = left
(Saka 0.02, Salah 0.04, Trossard 0.92, Robertson 0.97). A left player faces
the opponent's right, so facing side = mirror.

Per team, last 10 matches before kick-off:
  att_L / att_R     attacking actions by its players on that side per game
                    (crosses + dribbles + key passes + shots + fouled)
  conc_L / conc_R   attacking actions by OPPONENTS' players facing that side
  dfoul_L / dfoul_R fouls by its own defenders on that side
  dpast_L / dpast_R times its defenders on that side were dribbled past
Per player, last 10 appearances: share of team touches, shots, key passes,
fouls won (involvement, the football version of targets).
"""
from __future__ import annotations
from collections import defaultdict, deque
import numpy as np, pandas as pd

N = 10
SIDE_R, SIDE_L = 0.3, 0.7
ACT = ["crosses", "dribbles", "keypass", "shots", "fouled"]


def side_of(lat):
    if lat is None or lat != lat:
        return None
    return "R" if lat <= SIDE_R else "L" if lat >= SIDE_L else None


def match_sides(P: pd.DataFrame) -> dict:
    """{(match, team): {att_L, att_R, dfoul_L, dfoul_R, dpast_L, dpast_R}} for each match played."""
    s = P[(P.starter == 1) & (P.pos != "G")].copy()
    s["side"] = np.where(s.lat <= SIDE_R, "R", np.where(s.lat >= SIDE_L, "L", "C"))
    s["act"] = s[ACT].fillna(0).sum(axis=1)
    out = {}
    for (mid, team), g in s.groupby(["match", "team"]):
        d = {}
        for side in "LR":
            gs = g[g.side == side]
            dd = gs[gs.pos == "D"]
            d[f"att_{side}"] = float(gs.act.sum())
            d[f"dfoul_{side}"] = float(dd.fouls.fillna(0).sum())
            d[f"dpast_{side}"] = float(dd.challengelost.fillna(0).sum())
        out[(mid, team)] = d
    return out


def build(P: pd.DataFrame, M: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(team rows: match, team, fl_*), (player rows: match, pid, u_*) from earlier matches only."""
    ms = match_sides(P)
    th = defaultdict(lambda: deque(maxlen=N))
    team_rows = []
    tot = P.groupby(["match", "team"])[["touches", "shots", "keypass", "fouled"]].sum()
    ph = defaultdict(lambda: deque(maxlen=N))
    prow = []
    P2 = P[P.mins > 0]
    by_match = {m: g for m, g in P2.groupby("match")}
    for r in M.sort_values("ts").itertuples(index=False):
        mid = r.match
        teams = [(r.home, r.away), (r.away, r.home)]
        for team, opp in teams:
            h = list(th[team])
            def mean(k):
                v = [x[k] for x in h if k in x]
                return float(np.mean(v)) if v else np.nan
            row = {"match": mid, "team": team, "fl_n": len(h)}
            for k in ("att_L", "att_R", "conc_L", "conc_R", "dfoul_L", "dfoul_R", "dpast_L", "dpast_R"):
                row["fl_" + k] = mean(k)
            a, b = row["fl_att_L"], row["fl_att_R"]
            row["fl_bias"] = (a - b) / (a + b) if a == a and b == b and (a + b) > 0 else np.nan
            team_rows.append(row)
        g = by_match.get(mid)
        if g is not None:
            for p in g.itertuples(index=False):
                h = list(ph[p.pid])
                def share(k):
                    v = [x[k] for x in h if x.get(k) is not None]
                    return float(np.mean(v)) if v else np.nan
                prow.append({"match": mid, "pid": p.pid, "u_touch": share("touches"), "u_shots": share("shots"),
                             "u_keypass": share("keypass"), "u_fouled": share("fouled"), "u_n": len(h)})
        # update after both sides are done
        for team, opp in teams:
            d = dict(ms.get((mid, team), {}))
            o = ms.get((mid, opp), {})
            if not d:
                continue
            d["conc_L"] = o.get("att_R", np.nan)   # their right attacks our left
            d["conc_R"] = o.get("att_L", np.nan)
            th[team].append(d)
        if g is not None:
            for p in g.itertuples(index=False):
                if (mid, p.team) not in tot.index:
                    continue
                t = tot.loc[(mid, p.team)]
                ph[p.pid].append({k: (getattr(p, k) / t[k] if t[k] else None) for k in ("touches", "shots", "keypass", "fouled")})
    return pd.DataFrame(team_rows), pd.DataFrame(prow)


def player_features(F: pd.DataFrame, TR: pd.DataFrame, PR: pd.DataFrame) -> pd.DataFrame:
    own = TR.add_prefix("o_").rename(columns={"o_match": "match", "o_team": "team"})
    opp = TR.add_prefix("x_").rename(columns={"x_match": "match", "x_team": "opp"})
    F = F.merge(own, on=["match", "team"], how="left").merge(opp, on=["match", "opp"], how="left")
    F = F.merge(PR, on=["match", "pid"], how="left")
    side = np.where(F.lat <= SIDE_R, "R", np.where(F.lat >= SIDE_L, "L", "C"))
    face = np.where(side == "L", "R", np.where(side == "R", "L", "C"))
    def pick(prefix, key, sides):
        out = np.full(len(F), np.nan)
        for s in "LR":
            m = sides == s
            out[m] = F.loc[m, f"{prefix}fl_{key}_{s}"].values
        return out
    tot_att = F.o_fl_att_L + F.o_fl_att_R
    F["f_own_side_att"] = pick("o_", "att", side)
    F["f_own_side_share"] = F.f_own_side_att / tot_att
    F["f_opp_conc_facing"] = pick("x_", "conc", face)
    F["f_opp_conc_ratio"] = F.f_opp_conc_facing / ((F.x_fl_conc_L + F.x_fl_conc_R) / 2)
    F["f_opp_dpast_facing"] = pick("x_", "dpast", face)
    F["f_opp_dfoul_facing"] = pick("x_", "dfoul", face)
    F["f_opp_att_facing"] = pick("x_", "att", face)            # what comes at him (defenders)
    F["f_opp_att_ratio"] = F.f_opp_att_facing / ((F.x_fl_att_L + F.x_fl_att_R) / 2)
    F["f_target"] = F.f_own_side_share * F.f_opp_conc_ratio     # we go down his side and they leak there
    F["f_targeted"] = F.f_opp_att_ratio * (F.pos == "D")        # they come down his side
    F["f_bias_own"] = F.o_fl_bias * np.where(side == "L", 1, np.where(side == "R", -1, 0))
    F["f_bias_opp_at_me"] = F.x_fl_bias * np.where(face == "L", 1, np.where(face == "R", -1, 0))
    return F
