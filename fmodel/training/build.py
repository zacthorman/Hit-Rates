"""Parse the cached SofaScore football data into three tables.

matches: one row per finished football match with line-ups and stats.
teams:   one row per team per match: its own stats and the opponent's (ALL).
players: one row per player per match: role, formation slot, minutes, stats.
"""
import glob, json, os, re
import numpy as np
import pandas as pd

RAW = "/home/claude/bt/raw"
OUT = "/home/claude/bt/data"

PSTATS = {  # SofaScore key -> our name. Missing key means nought.
    "totalShots": "shots", "onTargetScoringAttempt": "sot", "fouls": "fouls",
    "wasFouled": "fouled", "totalTackle": "tackles", "goals": "goals",
    "goalAssist": "assists", "expectedGoals": "xg", "expectedAssists": "xa",
    "keyPass": "keypass", "touches": "touches", "totalPass": "passes",
    "interceptionWon": "intercepts", "duelWon": "duelwon", "duelLost": "duellost",
    "totalContest": "dribbles", "wonContest": "dribblewon", "totalCross": "crosses",
    "ballRecovery": "recoveries", "totalClearance": "clearances",
    "dispossessed": "dispossessed", "aerialWon": "aerialwon", "aerialLost": "aeriallost",
    "challengeLost": "challengelost", "possessionLostCtrl": "possloss",
    "totalOffside": "offsides", "saves": "saves", "bigChanceMissed": "bcmissed",
}
TSTATS = ["Ball possession", "Expected goals", "Big chances", "Total shots", "Shots on target",
          "Corner kicks", "Fouls", "Passes", "Tackles", "Free kicks", "Yellow cards", "Red cards",
          "Touches in penalty area", "Fouled in final third", "Final third entries", "Long balls",
          "Crosses", "Dribbles", "Interceptions", "Recoveries", "Clearances", "Total tackles",
          "Duels", "Accurate passes", "Offsides", "Throw-ins", "Goal kicks", "Shots inside box"]


def num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", str(v))
    return float(m.group(1)) if m else None


def main():
    ev = {}
    for f in glob.glob(f"{RAW}/team_*_events_last_*.json"):
        try:
            for e in json.load(open(f)).get("events", []):
                ev[e["id"]] = e
        except Exception:
            pass
    M, T, P = [], [], []
    for mid, e in ev.items():
        t = e.get("tournament") or {}
        if ((t.get("category") or {}).get("sport") or {}).get("slug") != "football":
            continue
        if (e.get("status") or {}).get("type") != "finished":
            continue
        lf, sf = f"{RAW}/event_{mid}_lineups.json", f"{RAW}/event_{mid}_statistics.json"
        if not (os.path.exists(lf) and os.path.exists(sf)):
            continue
        try:
            lu, st = json.load(open(lf)), json.load(open(sf))
        except Exception:
            continue
        per = next((p for p in st.get("statistics", []) if p.get("period") == "ALL"), None)
        if not per:
            continue
        items = {}
        for g in per.get("groups", []):
            for it in g.get("statisticsItems", []):
                items.setdefault(it["name"], (num(it.get("homeValue")), num(it.get("awayValue"))))
        ut = t.get("uniqueTournament") or {}
        hs, as_ = (e.get("homeScore") or {}).get("current"), (e.get("awayScore") or {}).get("current")
        M.append({"match": mid, "ts": e["startTimestamp"], "comp": ut.get("name") or t.get("name"),
                  "comp_id": ut.get("id"), "home": e["homeTeam"]["id"], "away": e["awayTeam"]["id"],
                  "home_name": e["homeTeam"]["name"], "away_name": e["awayTeam"]["name"],
                  "hg": hs, "ag": as_})
        for side, i in (("home", 0), ("away", 1)):
            team = e[f"{side}Team"]["id"]
            opp = e["awayTeam" if side == "home" else "homeTeam"]["id"]
            row = {"match": mid, "ts": e["startTimestamp"], "team": team, "opp": opp, "home": int(side == "home"),
                   "gf": hs if side == "home" else as_, "ga": as_ if side == "home" else hs}
            for k in TSTATS:
                v = items.get(k)
                row["f_" + k] = v[i] if v else None
                row["a_" + k] = v[1 - i] if v else None
            T.append(row)
            block = lu.get(side) or {}
            form = block.get("formation") or ""
            players = block.get("players") or []
            starters = [p for p in players if not p.get("substitute")]
            # Formation slot: line index and lateral position, as luShape does.
            sizes = [int(x) for x in form.split("-") if x.isdigit()]
            outf = [p for p in starters if (p.get("position") or p["player"].get("position")) != "G"]
            slot = {}
            if sizes and sum(sizes) == len(outf):
                k = 0
                for li, s in enumerate(sizes):
                    for j in range(s):
                        slot[outf[k]["player"]["id"]] = (li, len(sizes), j / (s - 1) if s > 1 else 0.5, s)
                        k += 1
            for p in players:
                s = p.get("statistics") or {}
                mins = s.get("minutesPlayed") or 0
                pid = p["player"]["id"]
                li, nl, lat, ls = slot.get(pid, (None, None, None, None))
                r = {"match": mid, "ts": e["startTimestamp"], "team": team, "opp": opp,
                     "home": int(side == "home"), "pid": pid, "name": p["player"]["name"],
                     "pos": p.get("position") or p["player"].get("position"),
                     "starter": int(not p.get("substitute")), "mins": mins, "formation": form,
                     "line": li, "nlines": nl, "depth": (li / (nl - 1) if nl and nl > 1 else None) if li is not None else None,
                     "lat": lat, "linesize": ls, "rating": s.get("rating")}
                for k, v in PSTATS.items():
                    r[v] = s.get(k, 0) or 0
                P.append(r)
    m, t, p = pd.DataFrame(M), pd.DataFrame(T), pd.DataFrame(P)
    # Coverage, decided once and used everywhere: does this team's player data
    # carry this stat for this match? Judged against the team's own stat, so a
    # genuine 0 (no shots on target) counts as covered, not as missing.
    COVER = {"fouls": "f_Fouls", "fouled": "a_Fouls", "shots": "f_Total shots",
             "sot": "f_Shots on target", "tackles": "f_Total tackles"}
    sums = p[p.mins > 0].groupby(["match", "team"])[list(COVER)].sum()
    tt = t.set_index(["match", "team"])
    for s, col in COVER.items():
        ref = tt[col].reindex(sums.index)
        got = sums[s]
        covered = np.where(ref.isna(), got > 0,
                  np.where(ref <= 0, True, (got / ref.where(ref > 0)) > 0.5))
        cv = pd.Series(covered, index=sums.index, name="cov_" + s)
        p = p.merge(cv.reset_index(), on=["match", "team"], how="left")
        p["cov_" + s] = p["cov_" + s].fillna(False).astype(bool)
    m.to_parquet(f"{OUT}/matches.parquet"); t.to_parquet(f"{OUT}/teams.parquet"); p.to_parquet(f"{OUT}/players.parquet")
    print(len(m), "matches", len(t), "team rows", len(p), "player rows")
    print("players with minutes>0:", (p.mins > 0).sum(), " starters with slot:", p[(p.starter == 1) & p.line.notna()].shape[0], "of", (p.starter == 1).sum())


if __name__ == "__main__":
    main()
