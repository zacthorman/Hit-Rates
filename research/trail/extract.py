"""Compact per-match records from the SofaScore cache, read only.

    python research/trail/extract.py cache /tmp/trail/matches.jsonl.gz

One line per match with line-ups: every player who played (id, name,
position, starter or not, a subset of his statistics, his average position
that game), the formations, goals, cards and substitutions from the
incidents, every shot from the shot map (minute, situation, xG, type, body
part, where from), the momentum graph and the team statistics. Kick-off,
competition and team names come from the cached team event lists.
"""
import glob
import gzip
import json
import os
import sys
import time

C = sys.argv[1]
OUT = sys.argv[2]


def load(p):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


ev = {}
for f in glob.glob(os.path.join(C, "team_*_events_last_*.json")) + glob.glob(os.path.join(C, "team_*_events_next_*.json")):
    for e in (load(f) or {}).get("events") or []:
        ev[e["id"]] = e
for f in glob.glob(os.path.join(C, "event_*.json")):
    if os.path.basename(f).count("_") == 1:
        d = load(f) or {}
        e = d.get("event") or d
        if e.get("id"):
            ev.setdefault(e["id"], e)

PK = ["fouls", "wasFouled", "totalTackle", "wonTackle", "totalShots", "onTargetScoringAttempt", "goals",
      "goalAssist", "keyPass", "duelWon", "duelLost", "totalContest", "wonContest", "dispossessed",
      "possessionLostCtrl", "touches", "interceptionWon", "totalClearance", "aerialWon", "aerialLost",
      "challengeLost", "totalCross", "expectedGoals", "rating", "minutesPlayed", "totalPass", "accuratePass",
      "ballRecovery", "fouledInFinalThird"]
n, t0 = 0, time.time()
with gzip.open(OUT, "wt") as out:
    for f in sorted(glob.glob(os.path.join(C, "event_*_lineups.json"))):
        eid = int(os.path.basename(f).split("_")[1])
        lu = load(f)
        if not lu or not lu.get("home") or not lu.get("away"):
            continue
        e = ev.get(eid) or {}
        rec = {"id": eid, "ts": e.get("startTimestamp"), "tour": (e.get("tournament") or {}).get("name"),
               "ut": ((e.get("tournament") or {}).get("uniqueTournament") or {}).get("id"),
               "home": (e.get("homeTeam") or {}).get("name"), "away": (e.get("awayTeam") or {}).get("name"),
               "hid": (e.get("homeTeam") or {}).get("id"), "aid": (e.get("awayTeam") or {}).get("id"),
               "hs": (e.get("homeScore") or {}).get("current"), "as": (e.get("awayScore") or {}).get("current")}
        ap = load(f.replace("_lineups", "_average-positions")) or {}
        pos = {}
        for side in ("home", "away"):
            for p in ap.get(side) or []:
                pid = (p.get("player") or {}).get("id")
                if pid:
                    pos[pid] = (round(p.get("averageX") or 0, 1), round(p.get("averageY") or 0, 1), p.get("pointsCount"))
        for side in ("home", "away"):
            blk = lu[side]
            rec[side[0] + "f"] = blk.get("formation")
            ps = []
            for p in blk.get("players") or []:
                pl = p.get("player") or {}
                st = p.get("statistics") or {}
                if not st.get("minutesPlayed"):
                    continue
                ps.append({"i": pl.get("id"), "n": pl.get("name"), "p": p.get("position") or pl.get("position"),
                           "s": bool(p.get("substitute")), "st": {k: st[k] for k in PK if k in st},
                           "xy": pos.get(pl.get("id"))})
            rec[side[0] + "p"] = ps
        inc = (load(f.replace("_lineups", "_incidents")) or {}).get("incidents")
        if inc is not None:
            rec["inc"] = [[i.get("incidentType")[0], i.get("time"), i.get("addedTime"), i.get("isHome"),
                           (i.get("player") or i.get("playerOut") or {}).get("id"), (i.get("playerIn") or {}).get("id"),
                           i.get("incidentClass")] for i in inc if i.get("incidentType") in ("goal", "card", "substitution")]
        sm = (load(f.replace("_lineups", "_shotmap")) or {}).get("shotmap")
        if sm is not None:
            rec["shots"] = [[s.get("time"), s.get("isHome"), (s.get("player") or {}).get("id"), s.get("situation"),
                             round(s.get("xg") or 0, 3), s.get("shotType"), s.get("bodyPart"),
                             (s.get("playerCoordinates") or {}).get("x"), (s.get("playerCoordinates") or {}).get("y")]
                            for s in sm]
        gr = load(f.replace("_lineups", "_graph"))
        if gr:
            rec["mom"] = [g.get("value") for g in gr.get("graphPoints") or []]
        stt = load(f.replace("_lineups", "_statistics"))
        if stt:
            ts = {}
            for per in stt.get("statistics") or []:
                if per.get("period") != "ALL":
                    continue
                for g in per.get("groups") or []:
                    for it in g.get("statisticsItems") or []:
                        ts[it["name"]] = [it.get("homeValue"), it.get("awayValue")]
            rec["ts_"] = ts
        out.write(json.dumps(rec, separators=(",", ":")) + "\n")
        n += 1
        if n % 1000 == 0:
            print(n, round(time.time() - t0), flush=True)
print("done", n, round(time.time() - t0), flush=True)
