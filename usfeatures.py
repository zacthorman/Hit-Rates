"""NBA and NFL player features, shared by the backtest and the live scorer.

    build(raw_dir, sport)            -> matches, teams, players tables from SofaScore JSON
    add_upcoming(M, T, P, games, ...) -> the same tables with upcoming games appended
    features(M, T, P, sport)         -> one row per player per game, strictly pre-game

One module so the live chances use exactly the features the model was
trained on (the football model keeps the same rule: fmodel_live.py mirrors
fmodel/training/features.py and sim_test.py checks they agree).
"""
import datetime
import glob
import json
import math
import os
import re
from collections import defaultdict, deque

import numpy as np
import pandas as pd

# ---- tables


SPORT = {
    "nba": dict(tid=132, slug="basketball", season_month=9),
    "nfl": dict(tid=9464, slug="american-football", season_month=8),
}

NBA_P = {"secondsPlayed": "secs", "points": "points", "rebounds": "rebounds", "assists": "assists",
         "threePointsMade": "threes", "threePointAttempts": "tpa", "steals": "steals", "blocks": "blocks",
         "turnovers": "turnovers", "fieldGoalAttempts": "fga", "fieldGoalsMade": "fgm",
         "freeThrowAttempts": "fta", "offensiveRebounds": "oreb", "defensiveRebounds": "dreb",
         "personalFouls": "pf", "usage": "usage", "plusMinus": "pm"}
NFL_P = {"passingYards": "pass_yds", "passingAttempts": "pass_att", "passingCompletions": "pass_cmp",
         "passingTouchdowns": "pass_td", "passingInterceptions": "pass_int",
         "rushingYards": "rush_yds", "rushingAttempts": "rush_att", "rushingTouchdowns": "rush_td",
         "receivingYards": "rec_yds", "receivingReceptions": "rec", "receivingTargets": "targets",
         "receivingTouchdowns": "rec_td", "defensiveCombineTackles": "tackles",
         "defensiveAssistTackles": "ast_tackles", "defensiveSacks": "sacks",
         "passingAirYards": "air_yds", "receivingRedZoneTargets": "rz_targets",
         "rushingRedZoneAttempts": "rz_rush"}


def num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", str(v))
    return float(m.group(1)) if m else None


def team_box(stats_json):
    """{'home': {name: value}, 'away': {...}} for the whole game (period ALL)."""
    out = {"home": {}, "away": {}}
    for per in (stats_json or {}).get("statistics", []):
        if per.get("period") != "ALL":
            continue
        for g in per.get("groups", []):
            for it in g.get("statisticsItems", []):
                n = it.get("name")
                out["home"][n] = num(it.get("homeValue", it.get("home")))
                out["away"][n] = num(it.get("awayValue", it.get("away")))
    return out


def build(RAW, sport):
    cfg = SPORT[sport]
    pmap = NBA_P if sport == "nba" else NFL_P
    ev = {}
    for f in glob.glob(f"{RAW}/team_*_events_last_*.json"):
        try:
            for e in json.load(open(f)).get("events", []):
                ev[e["id"]] = e
        except Exception:
            pass
    M, T, P = [], [], []
    for mid, e in ev.items():
        if ((e.get("tournament") or {}).get("uniqueTournament") or {}).get("id") != cfg["tid"]:
            continue
        if (e.get("status") or {}).get("type") != "finished":
            continue
        lf, sf = f"{RAW}/event_{mid}_lineups.json", f"{RAW}/event_{mid}_statistics.json"
        if not (os.path.exists(lf) and os.path.exists(sf)):
            continue
        try:
            L, S = json.load(open(lf)), json.load(open(sf))
        except Exception:
            continue
        ts = e["startTimestamp"]
        d = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
        season = d.year if d.month >= cfg["season_month"] else d.year - 1
        h, a = e["homeTeam"]["id"], e["awayTeam"]["id"]
        hs = (e.get("homeScore") or {}).get("current")
        as_ = (e.get("awayScore") or {}).get("current")
        rnd = ((e.get("roundInfo") or {}).get("name") or "") + " " + ((e.get("tournament") or {}).get("name") or "")
        playoff = "playoff" in rnd.lower() or "play-in" in rnd.lower()
        M.append(dict(match=mid, ts=ts, season=season, home=h, away=a, hs=hs, as_=as_,
                      home_name=e["homeTeam"]["name"], away_name=e["awayTeam"]["name"], playoff=playoff))
        box = team_box(S)
        for side, team, opp, pf, pa in (("home", h, a, hs, as_), ("away", a, h, as_, hs)):
            other = "away" if side == "home" else "home"
            row = dict(match=mid, ts=ts, season=season, team=team, opp=opp, home=int(side == "home"),
                       pts_for=pf, pts_against=pa)
            for k, v in box[side].items():
                row["f_" + k] = v
            for k, v in box[other].items():
                row["a_" + k] = v
            T.append(row)
            for p in (L.get(side) or {}).get("players", []) or []:
                st = p.get("statistics") or {}
                pl = p.get("player") or {}
                r = dict(match=mid, ts=ts, season=season, pid=pl.get("id"), name=pl.get("name"),
                         team=team, opp=opp, home=int(side == "home"),
                         pos=p.get("position") or pl.get("position") or "?",
                         starter=int(not p.get("substitute", False)), has_stats=int(bool(
                             {k for k in st if k != "statisticsType"})))
                for k, name in pmap.items():
                    v = st.get(k)
                    r[name] = float(v) if isinstance(v, (int, float)) else 0.0
                if sport == "nba":
                    r["mins"] = r.pop("secs") / 60
                P.append(r)
    M, T, P = pd.DataFrame(M), pd.DataFrame(T), pd.DataFrame(P)
    return M, T, P

# ---- features


CFG = {
    "nba": dict(
        targets=["points", "rebounds", "assists", "threes", "steals", "blocks", "turnovers",
                 "pra", "pr", "pa", "ra"],
        volume=["mins", "fga", "tpa", "fta", "usage", "oreb", "dreb", "pf", "pm"],
        team=["pts_for", "pts_against", "f_Rebounds", "a_Rebounds", "f_Assists", "a_Assists",
              "f_3 pointers", "a_3 pointers", "f_Turnovers", "a_Turnovers", "f_Steals", "f_Blocks",
              "f_Field goals", "a_Field goals", "f_Free throws", "a_Free throws"],
        pos=lambda p: (p or "?")[0] if (p or "?")[0] in "GFC" else "?",
        mate_stats=["points", "assists", "rebounds", "fga"], regular=("mins", 15.0),
        regular_key="mins", home_adv=60, elo_k=20, scale=12.0,
    ),
    "nfl": dict(
        targets=["pass_yds", "pass_cmp", "pass_att", "pass_td", "rush_yds", "rush_att", "rec_yds",
                 "rec", "rush_rec_yds", "pass_rush_yds", "tackles", "td"],
        volume=["targets", "rush_att", "pass_att", "air_yds", "rz_targets", "rz_rush", "ast_tackles"],
        team=["pts_for", "pts_against", "f_Total yards", "a_Total yards", "f_Net yards passing",
              "a_Net yards passing", "f_Rushing attempts", "a_Rushing attempts", "f_Rushing yards",
              "a_Rushing yards", "f_Time of Possession", "f_First downs", "a_First downs"],
        pos=lambda p: {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE"}.get(
            p, "DL" if p in ("DE", "DT", "DL", "NT") else "LB" if p in ("LB", "OLB", "ILB", "MLB")
            else "DB" if p in ("CB", "SAF", "DB", "S", "FS", "SS") else "X"),
        regular_key="targets", home_adv=48, elo_k=20, scale=8.0,
        mate_stats=["targets", "rec_yds", "rush_att"], regular=("targets", 2.0),
    ),
}


def mean(v):
    v = [x for x in v if x is not None and not (isinstance(x, float) and math.isnan(x))]
    return float(np.mean(v)) if v else np.nan


def features(M, T, P, sport, only=None):
    """One row per player per game, from earlier games only.

    only: match ids to build rows for (the live scorer's upcoming games).
    Every game still feeds the histories, so those rows come out exactly as
    they would in a full build; the other rows, which the live scorer threw
    away, are simply not built. None builds them all, as training needs.
    """
    c = CFG[sport]
    M = M.sort_values("ts")
    if "upcoming" not in P:
        P = P.assign(upcoming=0)
    if sport == "nfl":
        P["td"] = P.rush_td + P.rec_td
        P["mins"] = 60.0          # NFL box scores carry no minutes
        # Everyone in the line-up played (SofaScore lists about 35 a side,
        # not the 46+ actives): one with no statistics is a game of zeros.
        # Keeping only those with statistics chose rows by the result: a
        # receiver with no catch, a guaranteed under, was never a row, and
        # his blank game never reached his form. Fixed 22 Oct 2026.
        played = pd.Series(True, index=P.index)
    else:
        played = (P.mins > 0) | (P.upcoming == 1)
    # Who was there is the active list (known before kick-off), not who
    # recorded a stat: an NFL receiver who caught nothing has no stats, and a
    # backup quarterback only has them if the starter went off, which is
    # in-game news. NBA line-ups list only players who got minutes.
    listed = {m: set(g.pid) for m, g in P.groupby("match")}
    roster = {m: list(zip(g.pid, g.team, g.pos.map(c["pos"]))) for m, g in P.groupby("match")}
    P = P[played].copy()
    P["pgrp"] = P.pos.map(c["pos"])
    stats = list(dict.fromkeys(c["targets"] + c["volume"]))
    for s in stats:
        if s not in P:
            P[s] = 0.0

    # --- Elo, one pass in date order (margin-weighted, like football's)
    elo = defaultdict(lambda: 1500.0)
    elo_season = {}
    pre_elo = {}
    for r in M.itertuples():
        # a new season pulls each side a third of the way back to the
        # average: rosters change over the summer
        for t in (r.home, r.away):
            if elo_season.get(t, r.season) != r.season:
                elo[t] = 1500.0 + (elo[t] - 1500.0) * 2 / 3
            elo_season[t] = r.season
        h, a = elo[r.home], elo[r.away]
        pre_elo[r.match] = (h, a)
        if r.hs is None or r.as_ is None or pd.isna(r.hs) or pd.isna(r.as_):
            continue
        exp = 1 / (1 + 10 ** ((a - h - c["home_adv"]) / 400))
        res = 1.0 if r.hs > r.as_ else 0.5 if r.hs == r.as_ else 0.0
        k = c["elo_k"] * (1 + abs(r.hs - r.as_) / c["scale"]) ** 0.5
        elo[r.home] += k * (res - exp)
        elo[r.away] -= k * (res - exp)

    # --- team rolling style and positional concession, before each game
    ts_of = dict(zip(M.match, M.ts))
    playoff_of = dict(zip(M.match, M.playoff.fillna(False))) if "playoff" in M else {}
    Mrow = {r["match"]: r for r in M.to_dict("records")}
    Tg = {m: g for m, g in T.groupby("match")}
    Pg = {m: g for m, g in P.groupby("match")}
    team_hist = defaultdict(lambda: deque(maxlen=10))
    conc = defaultdict(lambda: defaultdict(lambda: deque(maxlen=10)))  # team -> pos -> per-game dicts
    team_feat, conc_feat = {}, {}
    pending = []
    cur = None
    for mid in M.match:
        if ts_of[mid] != cur:                       # same tip-off never sees itself
            for fn in pending:
                fn()
            pending, cur = [], ts_of[mid]
        g = Tg.get(mid)
        if g is None:
            # an upcoming game: no box score yet, but both sides still need
            # their pre-game team features
            mr = Mrow.get(mid)
            if mr is None:
                continue
            g = pd.DataFrame([{"team": mr["home"], "opp": mr["away"]}, {"team": mr["away"], "opp": mr["home"]}])
            upcoming_game = True
        else:
            upcoming_game = False
        for r in g.to_dict("records"):
            h = team_hist[r["team"]]
            team_feat[(mid, r["team"])] = {**{"t_" + k: mean([x.get(k) for x in h]) for k in c["team"]},
                                           "t_n": len(h)}
            cf = {}
            for pos, dq in conc[r["team"]].items():
                for s in c["targets"]:
                    cf[f"{pos}|{s}"] = mean([x.get(s) for x in dq])
            conc_feat[(mid, r["team"])] = cf
        if upcoming_game:
            continue
        recs = g.to_dict("records")
        pm = Pg.get(mid)

        def upd(recs=recs, pm=pm):
            for r in recs:
                team_hist[r["team"]].append(r)
                if pm is None:
                    continue
                opp_players = pm[pm.team == r["opp"]]
                for pos, sub in opp_players.groupby("pgrp"):
                    # the leading man at the position, which is what props are on
                    conc[r["team"]][pos].append({s: float(sub[s].max()) for s in c["targets"]})
        pending.append(upd)

    # --- player histories and rows
    P = P.sort_values(["ts", "match"])
    hist = defaultdict(list)
    h2h = defaultdict(list)
    rows = []
    for ts, block in P.groupby("ts", sort=True):
        updates = []
        for mid, pm in block.groupby("match", sort=False):
            if only is not None and mid not in only:
                # Not a row anyone will read. Touch the same history keys the
                # full build touches (a defaultdict lookup adds the key, and
                # the order of hist decides the order regulars are found in),
                # then fall through to the updates below.
                for q_pid, _, _ in roster.get(mid, list(zip(pm.pid, pm.team, pm.pgrp))):
                    hist[q_pid]
                for pid in pm.pid:
                    hist[pid]
            else:
                _rows_for(mid, pm, ts, hist, h2h, rows, pre_elo, listed, roster, c, sport,
                          stats, playoff_of, team_feat, conc_feat)
            for r in pm.itertuples(index=False):
                if r.upcoming:
                    continue
                d = {s: float(getattr(r, s)) for s in stats}
                d.update({"ts": r.ts, "team": r.team, "starter": r.starter, "mins": r.mins})
                updates.append((r.pid, r.opp, d))
        for pid, opp, d in updates:
            hist[pid].append(d)
            h2h[(pid, opp)].append(d)
    return pd.DataFrame(rows)


def _rows_for(mid, pm, ts, hist, h2h, rows, pre_elo, listed, roster, c, sport,
              stats, playoff_of, team_feat, conc_feat):
    """The feature rows for one game, from the histories as they stand."""
    el = pre_elo.get(mid, (1500, 1500))
    # regulars per team: top 7 by the regular key over their last 10 team games
    present = listed.get(mid, set(pm.pid)) | set(pm.pid)
    team_missing = {}
    for team in pm.team.unique():
        mates = [pid for pid, hh in hist.items() if hh and hh[-1]["team"] == team
                 and ts - hh[-1]["ts"] < 30 * 86400]
        prof_r = sorted(((mean([x[c["regular_key"]] for x in hist[q][-10:]]), q) for q in mates),
                        reverse=True)[:7]
        miss = [q for v, q in prof_r if q not in present]
        team_missing[team] = {
            "miss_n": len(miss),
            "miss_key": sum(mean([x[c["regular_key"]] for x in hist[q][-10:]]) for q in miss),
            **{f"miss_{s}": sum(mean([x[s] for x in hist[q][-10:]]) for q in miss)
               for s in c["targets"][:4]},
        }
    # The rest of the side tonight, from each player's own record
    # wherever it was made: a star arriving (Kawhi Leonard at the
    # Raptors, Oct 2026) takes shots off everyone, and missing_*
    # only knows about team-mates who are absent.
    rk, rmin = c["regular"]
    own = {}
    for q_pid, q_team, q_grp in roster.get(mid, list(zip(pm.pid, pm.team, pm.pgrp))):
        hq = hist[q_pid][-10:]
        if not hq:
            continue
        if sport == "nfl" and q_grp not in ("RB", "WR", "TE"):
            continue
        vals = {s_: mean([x[s_] for x in hq]) for s_ in c["mate_stats"]}
        if mean([x[rk] for x in hq]) >= rmin or (sport == "nfl" and mean([x["rush_att"] for x in hq]) >= 5):
            own[q_pid] = (q_team, vals)
    for r in pm.itertuples(index=False):
        hh = hist[r.pid]
        if len(hh) < 3:
            continue
        f = {"match": mid, "ts": ts, "pid": r.pid, "name": r.name, "team": r.team, "opp": r.opp,
             "season": r.season, "home": r.home, "pos": r.pgrp, "starter": r.starter,
             "playoff": float(bool(playoff_of.get(mid, False)))}
        f.update(profile(hh, stats, c["targets"], ts))
        me, op = (el[0], el[1]) if r.home else (el[1], el[0])
        f["elo_me"], f["elo_op"], f["elo_diff"] = me, op, me - op
        f.update(team_feat.get((mid, r.team), {}))
        f.update({"o" + k: v for k, v in team_feat.get((mid, r.opp), {}).items()})
        cf = conc_feat.get((mid, r.opp), {})
        for s in c["targets"]:
            f["oc_" + s] = cf.get(f"{r.pgrp}|{s}", np.nan)
        f.update(team_missing.get(r.team, {}))
        for s_ in c["mate_stats"]:
            tot = sum(v[s_] for q, (tm, v) in own.items() if tm == r.team and q != r.pid
                      and not math.isnan(v[s_]))
            f["mate_" + s_] = tot
            mine = f.get(f"{s_}_m10", np.nan)
            f["mate_share_" + s_] = (mine / (mine + tot)) if tot + (mine or 0) > 0 and not pd.isna(mine) else np.nan
        hv = h2h[(r.pid, r.opp)]
        f["h2h_n"] = len(hv)
        for s in c["targets"][:6]:
            f["h2h_" + s] = mean([x[s] for x in hv])
        for s in c["targets"]:
            f["y_" + s] = getattr(r, s)
        f["y_mins"] = r.mins
        rows.append(f)


def profile(hh, stats, targets, ts):
    out = {"n": len(hh), "days_rest": (ts - hh[-1]["ts"]) / 86400,
           "start_rate": mean([x["starter"] for x in hh[-10:]]),
           "b2b": float((ts - hh[-1]["ts"]) < 36 * 3600)}
    for s in stats:
        v = [x[s] for x in hh]
        for w in (3, 5, 10, 20):
            out[f"{s}_m{w}"] = mean(v[-w:])
        wts = np.array([0.5 ** ((len(v) - 1 - i) / 5) for i in range(len(v))])
        out[f"{s}_ew"] = float((wts * np.array(v)).sum() / wts.sum())
        out[f"{s}_sd10"] = float(np.std(v[-10:])) if len(v) >= 3 else np.nan
        out[f"{s}_med10"] = float(np.median(v[-10:]))
    for s in targets:
        if s in ("points", "pra", "pr", "pa", "rebounds", "assists"):
            mins = np.array([x["mins"] for x in hh[-10:]])
            vals = np.array([x[s] for x in hh[-10:]])
            out[f"{s}_p36"] = float(vals.sum() / mins.sum() * 36) if mins.sum() > 0 else np.nan
    return out




def _nm(name):
    import re, unicodedata
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    n = re.sub(r"[^a-z ]", "", n.lower().replace("-", " "))
    return " ".join(re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n).split())


def add_upcoming(M, T, P, games, sport, out_ids=frozenset(), squads=None, lineups=None):
    """Append upcoming games: each team's regulars (played for it in 2 of its
    last 5 games, most recent game for this team, within 30 days), minus
    out_ids (player ids ruled out). Stats are left empty; features() builds
    their rows from earlier games only, and never learns from them.

    games: iterable of dicts {match, ts, home, away, season}.
    lineups: {(match, team id): {"xi": names, "roster": names}} from a
    confirmed line-up. Then the roster decides who plays and the XI who
    starts, as the real line-up did in training."""
    c = CFG[sport]
    rows = []
    Pp = (P if sport == "nfl" else P[P.mins > 0]).sort_values("ts")   # as features(): listed is played
    for g in games:
        for team, opp, home in ((g["home"], g["away"], 1), (g["away"], g["home"], 0)):
            tg = Pp[Pp.team == team]
            last5 = list(dict.fromkeys(tg.sort_values("ts", ascending=False).match))[:5]
            if not last5:
                continue
            recent = tg[tg.match.isin(last5)]
            latest = Pp.groupby("pid").tail(1).set_index("pid")
            if squads and squads.get(team):
                # the current squad: summer moves and trades land on the right
                # side. A regular is anyone with 2 of his own last 5 games
                # played, wherever they were.
                cands = []
                for pid in squads[team]:
                    own = Pp[Pp.pid == pid].tail(5)
                    if len(own) >= 2 and g["ts"] - own.ts.iloc[-1] < 200 * 86400:
                        cands.append((pid, own))
            else:
                cands = [(pid, recent[recent.pid == pid]) for pid, n in recent.groupby("pid").size().items()
                         if n >= 2 and latest.loc[pid].team == team
                         and g["ts"] - latest.loc[pid].ts < 200 * 86400]
            lu = (lineups or {}).get((g["match"], team))
            if lu:
                xi = {_nm(n) for n in lu["xi"]}
                roster = {_nm(n) for n in lu["roster"]}
            for pid, prev in cands:
                if pid in out_ids:
                    continue
                lt = latest.loc[pid]
                starter = int(prev.starter.mean() >= 0.5)
                if lu:
                    if _nm(lt["name"]) not in roster:
                        continue
                    if sport == "nba":      # an NFL "XI" is not its starters
                        starter = int(_nm(lt["name"]) in xi)
                rows.append(dict(match=g["match"], ts=g["ts"], season=g["season"], pid=pid, name=lt["name"],
                                 team=team, opp=opp, home=home, pos=lt.pos,
                                 starter=starter, has_stats=0, upcoming=1,
                                 mins=float(prev.mins.mean()) if "mins" in prev else 60.0))
    U = pd.DataFrame(rows)
    if U.empty:
        return M, T, P.assign(upcoming=0)
    P2 = pd.concat([P.assign(upcoming=0), U], ignore_index=True)
    for col in P.columns:
        if col not in U and P[col].dtype.kind in "fi":
            P2[col] = P2[col].fillna(0.0) if col not in c["targets"] else P2[col]
    M2 = pd.concat([M, pd.DataFrame([dict(g, hs=None, as_=None) for g in games])], ignore_index=True)
    return M2, T, P2
