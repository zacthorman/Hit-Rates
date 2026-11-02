#!/usr/bin/env python3
"""The paper trail, live: who each starter faces, what that opponent does,
what it is worth, and the player's recent games told the same way.

    import trail_live
    tr = trail_live.matchups(entry)            # both sides, paired one to one
    trail_live.adjust(p, "Tackles", k, mult)   # a chance with the matchup applied
    trail_live.history(entry, side, name, "Tackles")

Research: research/TRAIL-2026-11-02.md. In 35,000 starter-games, what the
direct opponent usually does predicted a player's count on games the fit had
not seen, for four stats (trail_fit.json):

    tackles  his opponent's dribbles per 90        the clearest (+4.6 per 1,000), every
                                                   role, most for forwards and midfielders
                                                   facing ball-carrying defenders
    shots    his opponent's interceptions per 90   defenders and midfielders only
    fouled   his opponent's tackles per 90         defenders and midfielders only, small
    fouls    his opponent's fouls won per 90       tiny

"Faces a fouler, so he will be fouled" did not predict and is never claimed.

Direct opponents are paired one to one (an optimal assignment) from each
outfield starter's average position over his last 10 cached games, the
opponent's mirrored, so the pairing is knowable before kick-off. Rates come
from the cached match line-ups (the report rows carry only the bettable stats;
dribbles and interceptions are only in the line-ups). Reads cache/ only, never
fetches. Never fatal: anything missing gives None.
"""
from __future__ import annotations

import json
import math
import unicodedata
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
FIT = ROOT / "trail_fit.json"
N_PRIOR = 10
MIN_MINUTES = 45
MIN_APPS = 3
# Our stat name -> SofaScore line-up key, for the rates and the history.
KEYS = {"Tackles": "totalTackle", "Fouls": "fouls", "Fouled": "wasFouled", "Shots": "totalShots",
        "dribbles": "totalContest", "interc": "interceptionWon", "tackles": "totalTackle",
        "fouled": "wasFouled", "fouls": "fouls", "lost": "possessionLostCtrl"}
STAT_FIT = {"Tackles": "tackles", "Fouled": "fouled", "Fouls": "fouls", "Shots": "shots"}
SAME_LINE = {("D", "D"), ("F", "F")}
DRIVER_WORDS = {"dribbles": "dribbles", "tackles": "tackles", "fouled": "fouls won", "interc": "interceptions"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return " ".join("".join(c for c in s if c.isascii() and (c.isalpha() or c == " ")).lower().split())


@lru_cache(maxsize=1)
def fit() -> dict:
    try:
        return json.loads(FIT.read_text()).get("stats") or {}
    except (OSError, ValueError):
        return {}


@lru_cache(maxsize=4096)
def _load(eid, kind: str):
    try:
        return json.loads((CACHE / f"event_{eid}_{kind}.json").read_text())
    except (OSError, ValueError):
        return None


def _player_in(lineups: dict | None, pid=None, name=None):
    """(side, player block) for one player in a match's line-ups."""
    if not lineups:
        return None, None
    n = _norm(name) if name else None
    for side in ("home", "away"):
        for p in (lineups.get(side) or {}).get("players") or []:
            pl = p.get("player") or {}
            if (pid and pl.get("id") == pid) or (n and _norm(pl.get("name")) == n):
                return side, p
    return None, None


def _rows(entry: dict, t: int) -> dict:
    """normalised name -> (player id, his rows newest last) for one side."""
    out = {}
    for r in (entry.get("players") or [[], []])[t]:
        k = _norm(r.get("player"))
        out.setdefault(k, (r.get("player_id"), []))[1].append(r)
    for k, (_, rs) in out.items():
        rs.sort(key=lambda r: r.get("date") or "")
    return out


def profile(pid, rows: list[dict]) -> dict:
    """His last N_PRIOR games with minutes: rates per 90 from the cached
    line-ups, and his average position where the cache has one."""
    rates_tot, mins, xs, ys, apps = {}, 0.0, [], [], 0
    for r in reversed(rows):
        if apps >= N_PRIOR:
            break
        if (r.get("minutes") or 0) < MIN_MINUTES:
            continue
        eid = r.get("match_id")
        lu = _load(eid, "lineups")
        _, p = _player_in(lu, pid=pid, name=r.get("player"))
        st = (p or {}).get("statistics") or {}
        if not st.get("minutesPlayed"):
            continue
        apps += 1
        mins += st["minutesPlayed"]
        for k, sk in KEYS.items():
            rates_tot[k] = rates_tot.get(k, 0.0) + float(st.get(sk, 0) or 0)
        if r.get("started"):
            ap = _load(eid, "average-positions") or {}
            for side in ("home", "away"):
                for q in ap.get(side) or []:
                    if (q.get("player") or {}).get("id") == pid:
                        xs.append(q.get("averageX") or 0)
                        ys.append(q.get("averageY") or 0)
    rates = {k: v / mins * 90 for k, v in rates_tot.items()} if mins >= 90 else {}
    return {"apps": apps, "rates": rates,
            "x": sum(xs) / len(xs) if xs else None, "y": sum(ys) / len(ys) if ys else None}


def _xi(entry: dict, side: str) -> list[dict]:
    store = entry.get("lineups") or {}
    lu = store.get("confirmed") if store.get("confirmed") else store.get("predicted")
    return [p for p in ((lu or {}).get(side) or {}).get("xi") or [] if p.get("pos") != "G"]


def _assign(a: list[tuple], b: list[tuple]) -> list[tuple[int, int]]:
    """One-to-one pairing minimising squared distance; b is mirrored."""
    if not a or not b:
        return []
    cost = [[(ax - (100 - bx)) ** 2 + (ay - (100 - by)) ** 2 for bx, by in b] for ax, ay in a]
    try:
        from scipy.optimize import linear_sum_assignment
        ri, ci = linear_sum_assignment(cost)
        return list(zip(ri.tolist(), ci.tolist()))
    except Exception:  # noqa: BLE001  greedy fallback
        pairs, used = [], set()
        for i in sorted(range(len(a)), key=lambda i: min(cost[i])):
            j = min((j for j in range(len(b)) if j not in used), key=lambda j: cost[i][j], default=None)
            if j is not None:
                used.add(j)
                pairs.append((i, j))
        return pairs


def multiplier(stat: str, opp_rates: dict) -> tuple[float, float | None, str | None]:
    """(multiplier on his expected count, the opponent's rate, its driver)."""
    f = fit().get(STAT_FIT.get(stat, ""))
    if not f:
        return 1.0, None, None
    rate = opp_rates.get(f["driver"])
    if rate is None:
        return 1.0, None, f["driver"]
    return math.exp(f["coef"] * (math.log(max(rate, 0.05)) - f["centre"])), rate, f["driver"]


def band(stat: str, rate: float) -> str:
    """'top 10%' ... 'bottom 10%' of direct opponents for that driver."""
    q = (fit().get(STAT_FIT.get(stat, "")) or {}).get("quantiles") or []
    if len(q) != 5 or rate is None:
        return ""
    if rate >= q[4]:
        return "top 10%"
    if rate >= q[3]:
        return "top 25%"
    if rate <= q[0]:
        return "bottom 10%"
    if rate <= q[1]:
        return "bottom 25%"
    return "around average"


def matchups(entry: dict) -> dict:
    """{"home": [...], "away": [...]}: each outfield starter with his direct
    opponent, both profiles and the multiplier for each stat."""
    teams = entry.get("teams") or []
    if len(teams) < 2:
        return {}
    sides = [(t, (teams[t] or {}).get("side") or ("home", "away")[t]) for t in (0, 1)]
    prof = {}
    for t, side in sides:
        rows = _rows(entry, t)
        lst = []
        for p in _xi(entry, side):
            pid, rs = rows.get(_norm(p.get("name")), (None, []))
            pr = profile(pid, rs) if rs else {"apps": 0, "rates": {}, "x": None, "y": None}
            lst.append({"name": p.get("name"), "pos": p.get("pos"), "pid": pid, **pr})
        prof[side] = lst
    a = [p for p in prof.get("home", []) if p["x"] is not None]
    b = [p for p in prof.get("away", []) if p["x"] is not None]
    out = {"home": [], "away": []}
    for i, j in _assign([(p["x"], p["y"]) for p in a], [(p["x"], p["y"]) for p in b]):
        for me, op, side in ((a[i], b[j], "home"), (b[j], a[i], "away")):
            if me["apps"] < MIN_APPS or op["apps"] < MIN_APPS:
                continue
            # Centre-back against centre-back, or striker against striker,
            # is not a duel: the assignment pairs everyone, so these are
            # left out (2 Nov 2026: O'Brien "faced" Dan Burn).
            if (me["pos"], op["pos"]) in SAME_LINE:
                continue
            eff = {}
            for stat in STAT_FIT:
                roles = (fit().get(STAT_FIT[stat]) or {}).get("roles")
                if roles and (me["pos"] not in roles["player"] or op["pos"] not in roles["opponent"]):
                    # Shots and fouled only held for defenders and midfielders
                    # facing a forward or midfielder (2 Nov 2026 role check).
                    eff[stat] = {"mult": 1.0, "rate": None, "driver": None, "band": ""}
                    continue
                m, rate, drv = multiplier(stat, op["rates"])
                eff[stat] = {"mult": m, "rate": rate, "driver": drv, "band": band(stat, rate)}
            out[side].append({"player": me["name"], "pos": me["pos"], "opp": op["name"], "opp_pos": op["pos"],
                              "rates": me["rates"], "opp_rates": op["rates"], "effects": eff})
    return out


def adjust(p: float, stat: str, k: int, mult: float) -> float:
    """A 'k or more' chance with his expected count scaled by the matchup."""
    if not p or mult == 1.0:
        return p
    import supersub
    lam = supersub.rate_from_chance(p, k, 90)
    return min(0.995, supersub._tail(lam * mult * 1.0, k))


def history(entry: dict, t: int, name: str, stat: str, n: int = 6) -> list[dict]:
    """His last n games with the trail: his count, who he faced (paired on
    that game's own average positions), what that man did, and his team's
    possession."""
    rows = _rows(entry, t)
    pid, rs = rows.get(_norm(name), (None, []))
    f = fit().get(STAT_FIT.get(stat, "")) or {}
    drv = f.get("driver")
    out = []
    for r in reversed(rs):
        if len(out) >= n:
            break
        if not r.get("started") or (r.get("minutes") or 0) < MIN_MINUTES:
            continue
        eid = r.get("match_id")
        lu, ap = _load(eid, "lineups"), _load(eid, "average-positions")
        side, me = _player_in(lu, pid=pid, name=name)
        if not me:
            continue
        val = (me.get("statistics") or {}).get(KEYS.get(stat, ""), 0) or 0
        row = {"date": r.get("date"), "opponent": r.get("opponent"), "value": val,
               "opp": None, "opp_did": None, "poss": None}
        if ap and side:
            other = "away" if side == "home" else "home"
            mine = [q for q in ap.get(side) or [] if (q.get("player") or {}).get("id")]
            theirs = [q for q in ap.get(other) or [] if (q.get("player") or {}).get("id")]
            starters = {(q.get("player") or {}).get("id") for q in (lu.get(other) or {}).get("players") or []
                        if not q.get("substitute") and (q.get("player") or {}).get("position") != "G"}
            own_st = {(q.get("player") or {}).get("id") for q in (lu.get(side) or {}).get("players") or []
                      if not q.get("substitute") and (q.get("player") or {}).get("position") != "G"}
            mine = [q for q in mine if q["player"]["id"] in own_st]
            theirs = [q for q in theirs if q["player"]["id"] in starters]
            pr = _assign([(q["averageX"], q["averageY"]) for q in mine], [(q["averageX"], q["averageY"]) for q in theirs])
            for i, j in pr:
                if mine[i]["player"]["id"] == (me.get("player") or {}).get("id"):
                    oq = theirs[j]["player"]
                    _, op = _player_in(lu, pid=oq.get("id"))
                    row["opp"] = ((op or {}).get("player") or {}).get("name") or oq.get("name")
                    if drv:
                        row["opp_did"] = ((op or {}).get("statistics") or {}).get(KEYS[drv], 0) or 0
        st = _load(eid, "statistics") or {}
        for per in st.get("statistics") or []:
            if per.get("period") != "ALL":
                continue
            for g in per.get("groups") or []:
                for it in g.get("statisticsItems") or []:
                    if it.get("name") == "Ball possession":
                        v = it.get("homeValue") if side == "home" else it.get("awayValue")
                        try:
                            row["poss"] = float(str(v).rstrip("%"))
                        except (TypeError, ValueError):
                            pass
        if row["opp"] is None:
            continue          # no positions cached for that game: nothing to trace
        out.append(row)
    return list(reversed(out))
