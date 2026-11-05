#!/usr/bin/env python3
"""NBA.com's official box scores, so NBA lines settle on the league's numbers.

    python -B nba_official.py fetch [--days 3]      # cache the official box scores of recent games
    python -B nba_official.py recheck [--days 7]    # show logged NBA lines SofaScore settled wrongly
    python -B nba_official.py recheck --apply       # ...and correct them in the pp log

Why this exists (5 Nov 2026). Every NBA line in the logs settles off
SofaScore's box score (besttrack._player_value). On 4 Nov SofaScore gave
Cleveland's one steal by Harden to Tyrese Proctor instead: Harden 1+ steals
settled as a loss in the pp log, Paddy Power paid it as a win. The team
total still added up (5 both ways), so nothing inside SofaScore's own data
could catch it. Bookmakers settle on the league's official box score, so
that is what this reads.

Where the data comes from: cdn.nba.com, the static JSON NBA.com's own game
pages load (not stats.nba.com, which blocks machines that ask too fast).

  staticData/scheduleLeagueV2.json   the season's schedule: game ids, tip-off
                                     times and teams. Refreshed every
                                     SCHEDULE_MAX_AGE_HOURS.
  liveData/boxscore/boxscore_<id>    one game's box score. Cached for good
                                     once the game is final and at least
                                     FINAL_SETTLE_HOURS old, so late stat
                                     corrections are picked up first.

Being polite: one request at a time, MIN_GAP seconds plus up to JITTER
apart, a timeout on each, and the first answer that is not a clean 200 with
JSON stops every further request in this run. No retries. Everything is
cached under cache/nba_official/ (cache/ is gitignored).

How it is used. besttrack._player_value asks official_value() for every NBA
line it settles; when NBA.com has the game it wins, and the SofaScore number
it replaced is kept on the leg as sofascore_value. recheck does the same for
lines already settled, so the record is corrected backwards too. Never
fatal: if NBA.com cannot be reached, SofaScore's number stands.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import time
import unicodedata
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIR = ROOT / "cache" / "nba_official"
SCHEDULE_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
BOX_URL = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Referer": "https://www.nba.com/",
    "Accept": "application/json",
}
MIN_GAP = 2.0
JITTER = 2.0
TIMEOUT = 20
SCHEDULE_MAX_AGE_HOURS = 12
FINAL_SETTLE_HOURS = 6       # a final box is cached for good only this long after tip-off
MATCH_WINDOW_HOURS = 6       # SofaScore and NBA.com tip-off times must agree to within this

# pp log stat name -> NBA.com box-score fields that add up to it
STATS = {
    "Points": ("points",),
    "Rebounds": ("reboundsTotal",),
    "Assists": ("assists",),
    "Steals": ("steals",),
    "Blocks": ("blocks",),
    "Three pointers made": ("threePointersMade",),
    "Points and rebounds": ("points", "reboundsTotal"),
    "Points and assists": ("points", "assists"),
    "Rebounds and assists": ("reboundsTotal", "assists"),
    "Points rebounds and assists": ("points", "reboundsTotal", "assists"),
}

_state = {"stopped": None, "last": 0.0}
_memo: dict = {}   # parsed schedule and player tables for this run (settle asks once per line)


class Refused(Exception):
    """NBA.com did not give a clean answer: no more requests this run."""


# ------------------------------------------------------------ names

def norm(name: str) -> str:
    """Accents, punctuation and suffixes off: 'Nikola Jokić' and 'Nikola Jokic'
    match, so do 'Jabari Smith Jr.' and 'Jabari Smith'."""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if c.isascii())
    s = re.sub(r"[^a-z ]", " ", s.lower())
    parts = [p for p in s.split() if p not in ("jr", "sr", "ii", "iii", "iv")]
    return " ".join(parts)


def team_matches(sofa_name: str, team: dict) -> bool:
    """SofaScore 'Los Angeles Clippers' against NBA.com city 'LA', name
    'Clippers': the nickname is the reliable part."""
    nick = norm(team.get("teamName") or "")
    return bool(nick) and nick in norm(sofa_name)


# ------------------------------------------------------------ fetching

def _get(url: str) -> dict:
    if _state["stopped"]:
        raise Refused(_state["stopped"])
    wait = _state["last"] + MIN_GAP + random.random() * JITTER - time.time()
    if wait > 0:
        time.sleep(wait)
    _state["last"] = time.time()
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                raise Refused(f"HTTP {resp.status}")
            return json.loads(resp.read().decode("utf-8"))
    except Refused as exc:
        _state["stopped"] = str(exc)
        raise
    except Exception as exc:  # 403, 404, timeout, bad JSON: stop asking this run
        _state["stopped"] = f"{type(exc).__name__}: {exc}"
        raise Refused(_state["stopped"]) from exc


def _read(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    tmp.replace(path)


def schedule(fetch: bool = True) -> list[dict]:
    """Every game in the season: {gameId, tip (epoch), home, away} with home
    and away the NBA.com team dicts."""
    if "schedule" in _memo:
        return _memo["schedule"]
    games = _schedule(fetch)
    if games:
        _memo["schedule"] = games
    return games


def _schedule(fetch: bool) -> list[dict]:
    path = DIR / "schedule.json"
    data = _read(path)
    fresh = data is not None and time.time() - path.stat().st_mtime < SCHEDULE_MAX_AGE_HOURS * 3600
    if not fresh and fetch:
        try:
            data = _get(SCHEDULE_URL)
            _write(path, data)
        except Refused:
            pass            # an old copy still finds games it already lists
    return parse_schedule(data or {})


def parse_schedule(data: dict) -> list[dict]:
    out = []
    for day in ((data.get("leagueSchedule") or {}).get("gameDates") or []):
        for g in day.get("games") or []:
            ts = g.get("gameDateTimeUTC") or g.get("gameDateUTC")
            try:
                tip = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
            except (AttributeError, ValueError):
                continue
            out.append({"gameId": g.get("gameId"), "tip": tip,
                        "home": g.get("homeTeam") or {}, "away": g.get("awayTeam") or {}})
    return out


def find_game(games: list[dict], home: str, away: str, kickoff: float) -> str | None:
    for g in games:
        if abs(g["tip"] - kickoff) > MATCH_WINDOW_HOURS * 3600:
            continue
        if team_matches(home, g["home"]) and team_matches(away, g["away"]):
            return g["gameId"]
        if team_matches(home, g["away"]) and team_matches(away, g["home"]):
            return g["gameId"]      # SofaScore and NBA.com disagree on home and away
    return None


def box(game_id: str, kickoff: float, fetch: bool = True) -> dict | None:
    """The game's box score, from cache when it is final and settled."""
    path = DIR / f"box_{game_id}.json"
    data = _read(path)
    settled = time.time() - kickoff > FINAL_SETTLE_HOURS * 3600
    if data is not None and (is_final(data) and settled or not fetch):
        return data
    if not fetch:
        return data
    try:
        new = _get(BOX_URL.format(gid=game_id))
    except Refused:
        return data
    _write(path, new)
    return new


def is_final(data: dict) -> bool:
    # gameStatus 3 is final on NBA.com
    return ((data or {}).get("game") or {}).get("gameStatus") == 3


# ------------------------------------------------------------ values

def players(data: dict) -> dict[str, dict]:
    """norm(name) -> statistics, for players who got on the floor."""
    out = {}
    g = (data or {}).get("game") or {}
    for side in ("homeTeam", "awayTeam"):
        for p in (g.get(side) or {}).get("players") or []:
            st = p.get("statistics") or {}
            if str(p.get("played", "1")) != "1" or minutes(st.get("minutes")) <= 0:
                continue
            out[norm(p.get("name") or f"{p.get('firstName', '')} {p.get('familyName', '')}")] = st
    return out


def minutes(v) -> float:
    """'PT34M12.00S' -> 34.2."""
    if isinstance(v, (int, float)):
        return float(v)
    m = re.match(r"PT(\d+)M([\d.]+)S", v or "")
    return int(m.group(1)) + float(m.group(2)) / 60 if m else 0.0


def stat_value(st: dict, stat: str):
    keys = STATS.get(stat)
    if not keys:
        return None
    try:
        return float(sum(float(st.get(k) or 0) for k in keys))
    except (TypeError, ValueError):
        return None


def _teams(event_id) -> tuple[str, str] | None:
    """Home and away names from SofaScore's cached event."""
    d = _read(ROOT / "cache" / f"event_{event_id}.json") or {}
    e = d.get("event", d)
    h, a = (e.get("homeTeam") or {}).get("name"), (e.get("awayTeam") or {}).get("name")
    if h and a:
        return h, a
    return None


def official_value(leg: dict, fetch: bool = True):
    """The official NBA.com value for a basketball leg, or None if NBA.com
    does not have the game final, the player, or the stat."""
    if leg.get("stat") not in STATS:
        return None
    teams = _teams(leg.get("event_id"))
    if not teams and " v " in (leg.get("fixture") or ""):
        teams = tuple(leg["fixture"].split(" v ", 1))
    if not teams:
        return None
    gid = find_game(schedule(fetch), teams[0], teams[1], float(leg["kickoff"]))
    if not gid:
        return None
    key = ("box", gid)
    if key not in _memo:
        data = box(gid, float(leg["kickoff"]), fetch)
        _memo[key] = players(data) if data and is_final(data) else None
    table = _memo[key]
    if table is None:
        return None
    st = table.get(norm(leg.get("player") or ""))
    return stat_value(st, leg["stat"]) if st else None


# ------------------------------------------------------------ commands

def _recent_rows(days: float) -> list[tuple]:
    import pplog
    out = []
    since = time.time() - days * 86400
    for path in pplog._files():
        for i, r in enumerate(pplog._read(path)):
            if r.get("sport") == "basketball" and r.get("result") in ("win", "lose") and r["kickoff"] >= since:
                out.append((path, i, r))
    return out


def fetch_cmd(days: float) -> int:
    games = schedule(True)
    seen = set()
    for _, _, r in _recent_rows(days):
        teams = _teams(r["event_id"])
        if not teams:
            continue
        gid = find_game(games, teams[0], teams[1], float(r["kickoff"]))
        if gid and gid not in seen:
            seen.add(gid)
            box(gid, float(r["kickoff"]), True)
    print(f"  nba.com: {len(seen)} game(s) checked"
          + (f", stopped ({_state['stopped']})" if _state["stopped"] else ""))
    return 0


def recheck(days: float, apply: bool) -> int:
    import pplog
    rows = _recent_rows(days)
    changes: dict[Path, list[tuple[int, dict]]] = {}
    checked = 0
    for path, i, r in rows:
        v = official_value(r, fetch=True)
        if v is None:
            continue
        checked += 1
        if r.get("value") is not None and abs(float(r["value"]) - v) < 1e-9:
            continue
        won = v > r["line"] if r["over"] else v < r["line"]
        res = "win" if won else "lose"
        print(f"  {r['player']:24} {r['stat']:28} {r['line']:>5} {'over' if r['over'] else 'under'}: "
              f"SofaScore {r.get('value')}, NBA.com {v:g}  {r['result']} -> {res}  ({r['fixture']})")
        new = dict(r, value=v, result=res, sofascore_value=r.get("value"), official_source="nba.com")
        changes.setdefault(path, []).append((i, new))
    n_changed = sum(len(v) for v in changes.values())
    print(f"  nba.com recheck: {checked} line(s) checked, {n_changed} value(s) differ"
          + (f"; stopped early ({_state['stopped']})" if _state["stopped"] else ""))
    if apply and changes:
        for path, lst in changes.items():
            data = pplog._read(path)
            for i, new in lst:
                # only touch the row if it is still the one we read
                if pplog._key(data[i]) == pplog._key(new):
                    data[i] = new
            pplog._write(path, data)
        print(f"  pp log corrected: {n_changed} line(s)")
    elif changes:
        print("  (dry run: add --apply to correct the pp log)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["fetch", "recheck"])
    ap.add_argument("--days", type=float, default=3)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        return fetch_cmd(a.days)
    return recheck(a.days, a.apply)


if __name__ == "__main__":
    raise SystemExit(main())
