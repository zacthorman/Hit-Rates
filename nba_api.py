"""
Cached client for NBA.com's public JSON, shaped like sofascore_api's answers.

    python -B nba_api.py compare [--days 3]   # side by side: NBA.com v SofaScore, stat by stat
    python -B nba_api.py lineups <sofa_event_id>   # one game's line-ups, SofaScore-shaped

The plan (5 Nov 2026): NBA from NBA.com, football from SofaScore, NFL from
ESPN, so the three can be fetched at the same time instead of everything
queueing behind one paced SofaScore connection (the NBA build alone took
15 minutes on 5 Nov). This file is step one, and runs side by side: nothing
else imports it yet. `compare` checks that every player's numbers match
SofaScore's for recent games before anything switches over.

What it answers. The NBA build asks SofaScore for each game's line-ups (the
player box score) and team statistics, two requests a game, and that is
where its time goes. event_lineups() and event_statistics() answer the
same two questions from NBA.com's box score, in SofaScore's shape and keyed
by SofaScore's event and player ids, so run.py, hitrates.py and the logs
would not have to change. SofaScore stays the source of game ids and the
schedule (one small request a team), because Paddy Power, Betfair and every
log are matched on those ids.

Like sofascore_api, every response is written to disk before it is parsed:
reruns cost nothing, the raw data is kept if the format changes, and a final
box score is permanent once it has had FINAL_SETTLE_HOURS for late stat
corrections.

The transport. cdn.nba.com is static JSON with no Cloudflare in front, so
FlareSolverr is not needed (5 Nov 2026: through FlareSolverr the schedule
came back wrapped in a page, not JSON). The default is curl_cffi with a
browser fingerprint, the same as sofascore_api's direct mode, which fetched
29 games and the schedule cleanly on 5 Nov:

  default                   curl_cffi, impersonating NBA_IMPERSONATE (chrome142)
  NBA_IMPERSONATE=0         plain urllib, with NBA.com's own Referer
  NBA_FLARESOLVERR=<url>    FlareSolverr, only if NBA.com ever starts checking

Being polite: one request at a time, MIN_GAP plus up to JITTER seconds
apart, network errors retried with backoff (no request reached NBA.com, so a
retry costs it nothing), and a 403 or 429 stops every further request this
run. No retry on a refusal.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

BASE = "https://cdn.nba.com/static/json"
SCHEDULE = "staticData/scheduleLeagueV2.json"
BOX = "liveData/boxscore/boxscore_{gid}.json"

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache" / "nba"
SOFA_CACHE = ROOT / "cache"

MIN_GAP = 2.0
JITTER = 2.0
TIMEOUT = 20
ATTEMPTS = 4
NET_BACKOFF = (2, 5, 10, 20)
SCHEDULE_MAX_AGE_HOURS = 12
FINAL_SETTLE_HOURS = 6
MATCH_WINDOW_HOURS = 6

FLARESOLVERR = os.environ.get("NBA_FLARESOLVERR", "").strip()
IMPERSONATE = os.environ.get("NBA_IMPERSONATE", "chrome142").strip()
if IMPERSONATE.lower() in ("0", "off", "no", "false"):
    IMPERSONATE = ""
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
}

_session = None
_state: dict[str, Any] = {"stopped": None, "last": 0.0}
_memo: dict = {}


class Refused(Exception):
    """NBA.com said no (403, 429) or the run has already been stopped."""


# ------------------------------------------------------------ transport

class _UrllibSession:
    """The plain default: cdn.nba.com needs nothing more."""

    def get(self, url: str, timeout: float = TIMEOUT):
        import urllib.error
        import urllib.request
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return _Response(r.status, r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return _Response(exc.code, "")


class _Response:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text

    def json(self):
        return json.loads(self.text)


def _get_session():
    """One session for the whole run, chosen once."""
    global _session
    if _session is not None:
        return _session
    if FLARESOLVERR:
        import sofascore_api
        _session = sofascore_api._FlareSession(FLARESOLVERR)
    elif IMPERSONATE:
        from curl_cffi import requests
        _session = requests.Session(impersonate=IMPERSONATE)
        _session.headers.update(HEADERS)
    else:
        _session = _UrllibSession()
    return _session


def _cache_file(path: str) -> Path:
    return CACHE_DIR / (path.strip("/").replace("/", "_").replace("?", "_").replace("&", "_"))


def get_json(path: str, max_age_hours: float | None = None, verbose: bool = False) -> Any | None:
    """Fetch BASE/path, reusing the cached copy when there is one.

    max_age_hours=None means the cache never expires. Returns None on any
    failure, so callers decide what a failure means (as sofascore_api does).
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f = _cache_file(path)
    if f.exists() and (max_age_hours is None or time.time() - f.stat().st_mtime < max_age_hours * 3600):
        try:
            return json.loads(f.read_text())
        except ValueError:
            f.unlink(missing_ok=True)
    if _state["stopped"]:
        return _cached_anyway(f)
    url = f"{BASE}/{path}"
    for attempt in range(ATTEMPTS):
        wait = _state["last"] + MIN_GAP + random.random() * JITTER - time.time()
        if wait > 0:
            time.sleep(wait)
        _state["last"] = time.time()
        try:
            r = _get_session().get(url, timeout=TIMEOUT)
        except Exception as exc:  # the network, not NBA.com: back off and try again
            if verbose:
                print(f"  nba.com: {type(exc).__name__} on {path}, retrying")
            time.sleep(NET_BACKOFF[min(attempt, len(NET_BACKOFF) - 1)])
            continue
        if r.status_code == 200:
            try:
                data = r.json()
            except ValueError:
                head = " ".join((r.text or "")[:160].split())
                _state["stopped"] = f"not JSON from {path} (starts: {head!r})"
                return _cached_anyway(f)
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, separators=(",", ":")))
            tmp.replace(f)
            return data
        if r.status_code in (403, 429):
            _state["stopped"] = f"HTTP {r.status_code} on {path}"
            print(f"  nba.com: {_state['stopped']}; no more requests this run")
            return _cached_anyway(f)
        if r.status_code == 404:
            return None        # a game id NBA.com does not have yet
        time.sleep(NET_BACKOFF[min(attempt, len(NET_BACKOFF) - 1)])
    return _cached_anyway(f)


def _cached_anyway(f: Path):
    try:
        return json.loads(f.read_text()) if f.exists() else None
    except ValueError:
        return None


def stopped() -> str | None:
    return _state["stopped"]


# ------------------------------------------------------------ names and games

def norm(name: str) -> str:
    """'Nikola Jokić' = 'Nikola Jokic', 'Jabari Smith Jr.' = 'Jabari Smith'."""
    s = unicodedata.normalize("NFKD", name or "")
    s = re.sub(r"[^a-z ]", " ", "".join(c for c in s if c.isascii()).lower())
    return " ".join(p for p in s.split() if p not in ("jr", "sr", "ii", "iii", "iv"))


def short(name: str) -> str:
    """First initial and surname: 'Ron Holland' and 'Ronald Holland II' both 'r holland'."""
    parts = norm(name).split()
    return f"{parts[0][0]} {parts[-1]}" if len(parts) >= 2 else norm(name)


def _lookup(table: dict, name: str):
    """By full name, else by initial and surname when only one player fits."""
    hit = table.get(norm(name))
    if hit is not None:
        return hit
    want = short(name)
    found = [v for k, v in table.items() if short(k) == want]
    return found[0] if len(found) == 1 else None


def _team_matches(sofa_name: str, team: dict) -> bool:
    nick = norm(team.get("teamName") or "")
    return bool(nick) and nick in norm(sofa_name)


def schedule() -> list[dict]:
    if "schedule" not in _memo:
        data = get_json(SCHEDULE, max_age_hours=SCHEDULE_MAX_AGE_HOURS) or {}
        games = []
        for day in ((data.get("leagueSchedule") or {}).get("gameDates") or []):
            for g in day.get("games") or []:
                try:
                    tip = datetime.fromisoformat(g["gameDateTimeUTC"].replace("Z", "+00:00")).timestamp()
                except (KeyError, AttributeError, ValueError):
                    continue
                games.append({"gameId": g.get("gameId"), "tip": tip,
                              "home": g.get("homeTeam") or {}, "away": g.get("awayTeam") or {}})
        _memo["schedule"] = games
    return _memo["schedule"]


def _sofa_event(event_id) -> dict:
    try:
        d = json.loads((SOFA_CACHE / f"event_{event_id}.json").read_text())
    except (OSError, ValueError):
        return {}
    return d.get("event", d)


def game_id_for(event_id) -> tuple[str | None, bool]:
    """NBA.com's game id for a SofaScore event, and whether NBA.com has the
    teams the other way round."""
    e = _sofa_event(event_id)
    home, away, ko = (e.get("homeTeam") or {}).get("name"), (e.get("awayTeam") or {}).get("name"), e.get("startTimestamp")
    if not (home and away and ko):
        return None, False
    for g in schedule():
        if abs(g["tip"] - ko) > MATCH_WINDOW_HOURS * 3600:
            continue
        if _team_matches(home, g["home"]) and _team_matches(away, g["away"]):
            return g["gameId"], False
        if _team_matches(home, g["away"]) and _team_matches(away, g["home"]):
            return g["gameId"], True
    return None, False


def box_score(game_id: str, tip: float | None = None) -> dict | None:
    """NBA.com's box score. Kept for good once final and settled."""
    path = BOX.format(gid=game_id)
    data = get_json(path, max_age_hours=None)
    final = ((data or {}).get("game") or {}).get("gameStatus") == 3
    settled = tip is not None and time.time() - tip > FINAL_SETTLE_HOURS * 3600
    if data is None or not (final and settled):
        fresh = get_json(path, max_age_hours=0)
        data = fresh or data
    return data


# ------------------------------------------------------------ SofaScore-shaped answers

def _minutes(v) -> float:
    m = re.match(r"PT(\d+)M([\d.]+)S", v or "")
    return int(m.group(1)) + float(m.group(2)) / 60 if m else 0.0


def player_statistics(st: dict, team: dict | None = None) -> dict:
    """One NBA.com player line in SofaScore's basketball keys.

    SofaScore also sends three derived numbers, computed here the standard
    way. usage feeds the NBA player model (usfeatures.py), so it has to be
    there; on 650 lines from 2 to 4 Nov these came within 0.3 points of
    SofaScore's usage and matched its eFG% and TS% exactly. SofaScore's own
    "rating" has no public formula and nothing downstream needs it."""
    g = lambda k: int(st.get(k) or 0)  # noqa: E731
    fgm, fga = g("fieldGoalsMade"), g("fieldGoalsAttempted")
    fta, tov, pts, tpm = g("freeThrowsAttempted"), g("turnovers"), g("points"), g("threePointersMade")
    mins = _minutes(st.get("minutes"))
    extra: dict[str, float] = {}
    if fga:
        extra["effectiveFieldGoalPercentage"] = round(100 * (fgm + 0.5 * tpm) / fga, 2)
    if fga + 0.44 * fta:
        extra["trueShootingPercentage"] = round(100 * pts / (2 * (fga + 0.44 * fta)), 2)
    t = team or {}
    t_poss = float(t.get("fieldGoalsAttempted") or 0) + 0.44 * float(t.get("freeThrowsAttempted") or 0) \
        + float(t.get("turnoversTotal", t.get("turnovers")) or 0)
    t_min = _minutes(t.get("minutes"))
    if mins > 0 and t_poss and t_min:
        extra["usage"] = 100 * (fga + 0.44 * fta + tov) * (t_min / 5) / (mins * t_poss)
    return {**extra,
        "secondsPlayed": round(_minutes(st.get("minutes")) * 60),
        "points": g("points"),
        "twoPointsMade": g("twoPointersMade"), "twoPointAttempts": g("twoPointersAttempted"),
        "threePointsMade": g("threePointersMade"), "threePointAttempts": g("threePointersAttempted"),
        "freeThrowsMade": g("freeThrowsMade"), "freeThrowAttempts": g("freeThrowsAttempted"),
        "fieldGoalsMade": fgm, "fieldGoalAttempts": fga,
        "rebounds": g("reboundsTotal"), "defensiveRebounds": g("reboundsDefensive"),
        "offensiveRebounds": g("reboundsOffensive"),
        "assists": g("assists"), "steals": g("steals"), "blocks": g("blocks"),
        "turnovers": g("turnovers"), "personalFouls": g("foulsPersonal"),
        "plusMinus": int(float(st.get("plusMinusPoints") or 0)),
        **({"fieldGoalPct": round(100 * fgm / fga)} if fga else {}),   # whole numbers, as SofaScore
        "statisticsType": {"sportSlug": "basketball", "statisticsType": "player"},
        "source": "nba.com",
    }


def _sofa_players(event_id) -> dict[str, dict]:
    """norm(name) -> SofaScore's player dict, so the NBA.com rows carry
    SofaScore's ids and names: from its line-ups for the game when it has
    them, else from both teams' squads (cache/team_<id>_players.json), which
    the build fetches anyway."""
    out: dict[str, dict] = {}
    try:
        d = json.loads((SOFA_CACHE / f"event_{event_id}_lineups.json").read_text())
    except (OSError, ValueError):
        d = None
    if d:
        for side in ("home", "away"):
            for p in (d.get(side) or {}).get("players") or []:
                pl = p.get("player") or {}
                out[norm(pl.get("name") or "")] = {"player": pl, "teamId": p.get("teamId"), "side": side}
        return out
    e = _sofa_event(event_id)
    for side in ("home", "away"):
        tid = (e.get(f"{side}Team") or {}).get("id")
        try:
            sq = json.loads((SOFA_CACHE / f"team_{tid}_players.json").read_text())
        except (OSError, ValueError):
            continue
        for p in sq.get("players") or []:
            pl = p.get("player") or {}
            if pl.get("name"):
                out.setdefault(norm(pl["name"]), {"player": pl, "teamId": tid, "side": side})
    return out


def event_lineups(event_id) -> dict | None:
    """sofascore_api's event/<id>/lineups, built from NBA.com's box score."""
    gid, flipped = game_id_for(event_id)
    if not gid:
        return None
    data = box_score(gid, _sofa_event(event_id).get("startTimestamp"))
    game = (data or {}).get("game") or {}
    if not game:
        return None
    sofa = _sofa_players(event_id)
    sides = {"home": "awayTeam" if flipped else "homeTeam", "away": "homeTeam" if flipped else "awayTeam"}
    out: dict[str, Any] = {"confirmed": True, "source": "nba.com", "nbaGameId": gid}
    for side, key in sides.items():
        players = []
        for p in (game.get(key) or {}).get("players") or []:
            name = p.get("name") or f"{p.get('firstName', '')} {p.get('familyName', '')}".strip()
            known = _lookup(sofa, name) or {}
            played = str(p.get("played", "1")) == "1"
            players.append({
                "player": known.get("player") or {"name": name, "id": None, "nbaPersonId": p.get("personId")},
                "teamId": known.get("teamId") or (_sofa_event(event_id).get(f"{side}Team") or {}).get("id"),
                "jerseyNumber": p.get("jerseyNum"),
                "position": p.get("position"),
                "substitute": str(p.get("starter", "0")) != "1",
                "statistics": player_statistics(p.get("statistics") or {},
                                                (game.get(key) or {}).get("statistics")) if played else {},
            })
        out[side] = {"players": players}
    return out


def event_statistics(event_id) -> dict | None:
    """sofascore_api's event/<id>/statistics, built from NBA.com's team
    totals, with SofaScore's display names: hitrates.py reads items by name
    ("Rebounds", "Free throws"), so the names must match SofaScore's."""
    gid, flipped = game_id_for(event_id)
    if not gid:
        return None
    game = ((box_score(gid, _sofa_event(event_id).get("startTimestamp")) or {}).get("game")) or {}
    if not game:
        return None
    h, a = ("awayTeam", "homeTeam") if flipped else ("homeTeam", "awayTeam")
    hs, as_ = (game.get(h) or {}).get("statistics") or {}, (game.get(a) or {}).get("statistics") or {}

    def num(d, k):
        try:
            return int(float(d.get(k) or 0))
        except (TypeError, ValueError):
            return 0

    def made(key, name, m, att):
        hm, ha, am, aa = num(hs, m), num(hs, att), num(as_, m), num(as_, att)
        txt = lambda x, y: f"{x}/{y} ({round(100 * x / y) if y else 0}%)"  # noqa: E731
        return {"key": key, "name": name, "home": txt(hm, ha), "away": txt(am, aa),
                "homeValue": hm, "awayValue": am, "homeTotal": ha, "awayTotal": aa,
                "compareCode": 1, "statisticsType": "positive", "valueType": "team"}

    def plain(key, name, n, kind="positive"):
        hv, av = num(hs, n), num(as_, n)
        return {"key": key, "name": name, "home": str(hv), "away": str(av), "homeValue": hv, "awayValue": av,
                "compareCode": 1 if hv >= av else 2, "statisticsType": kind, "valueType": "event"}

    scoring = [made("freeThrowsScored", "Free throws", "freeThrowsMade", "freeThrowsAttempted"),
               made("twoPointersScored", "2 pointers", "twoPointersMade", "twoPointersAttempted"),
               made("threePointersScored", "3 pointers", "threePointersMade", "threePointersAttempted"),
               made("fieldGoalsScored", "Field goals", "fieldGoalsMade", "fieldGoalsAttempted")]
    # reboundsPersonal, not reboundsTotal: NBA.com's total adds "team
    # rebounds" no player is credited with, SofaScore's is its players' sum.
    other = [plain("rebounds", "Rebounds", "reboundsPersonal" if "reboundsPersonal" in hs else "reboundsTotal"),
             plain("defensiveRebounds", "Defensive rebounds", "reboundsDefensive"),
             plain("offensiveRebounds", "Offensive rebounds", "reboundsOffensive"),
             plain("assists", "Assists", "assists"),
             plain("turnovers", "Turnovers", "turnovers", "negative"),
             plain("steals", "Steals", "steals"),
             plain("blocks", "Blocks", "blocks"),
             plain("totalFouls", "Fouls", "foulsPersonal", "negative")]
    lead = []
    if "biggestLead" in hs or "biggestLead" in as_:
        lead.append(plain("biggestLead", "Biggest lead", "biggestLead"))
    if "biggestScoringRun" in hs or "biggestScoringRun" in as_:
        lead.append(plain("maxPointsInARow", "Max points in a row", "biggestScoringRun"))
    if "timeLeading" in hs or "timeLeading" in as_:
        hl, al = round(_minutes(hs.get("timeLeading")) * 60), round(_minutes(as_.get("timeLeading")) * 60)
        mmss = lambda x: f"{x // 60}:{x % 60:02d}"  # noqa: E731
        lead.append({"key": "timeSpentInLead", "name": "Time spent in lead", "home": mmss(hl), "away": mmss(al),
                     "homeValue": hl, "awayValue": al, "compareCode": 1 if hl >= al else 2,
                     "statisticsType": "positive", "valueType": "time"})
    groups = [{"groupName": "Scoring", "statisticsItems": scoring},
              {"groupName": "Other", "statisticsItems": other}]
    if lead:
        groups.append({"groupName": "Lead", "statisticsItems": lead})
    return {"statistics": [{"period": "ALL", "groups": groups}], "source": "nba.com"}


# ------------------------------------------------------------ side by side

COMPARE_KEYS = ("secondsPlayed", "points", "rebounds", "assists", "steals", "blocks",
                "threePointsMade", "turnovers")


def compare(days: float = 3) -> dict:
    """Every SofaScore NBA game finished in the last `days` with a cached
    line-up, checked player by player against NBA.com."""
    since = time.time() - days * 86400
    games = diffs = players = unmatched = missing = 0
    out = []
    t0 = time.time()
    for f in sorted(SOFA_CACHE.glob("event_*_lineups.json")):
        eid = f.name.split("_")[1]
        e = _sofa_event(eid)
        if (((e.get("tournament") or {}).get("uniqueTournament") or {}).get("name")) != "NBA":
            continue
        if (e.get("status") or {}).get("type") != "finished" or (e.get("startTimestamp") or 0) < since:
            continue
        nba = event_lineups(eid)
        if not nba:
            missing += 1
            continue
        games += 1
        sofa = json.loads(f.read_text())
        mine = {norm((p["player"] or {}).get("name") or ""): p for s in ("home", "away") for p in nba[s]["players"]}
        for side in ("home", "away"):
            for p in (sofa.get(side) or {}).get("players") or []:
                st = p.get("statistics") or {}
                if not st.get("secondsPlayed"):
                    continue
                players += 1
                name = (p.get("player") or {}).get("name") or ""
                q = _lookup(mine, name)
                if not q:
                    unmatched += 1
                    out.append((e.get("slug", eid), name, "not found on NBA.com", None, None))
                    continue
                for k in COMPARE_KEYS:
                    a, b = st.get(k) or 0, (q.get("statistics") or {}).get(k) or 0
                    if k == "secondsPlayed":
                        if abs(a - b) > 90:      # minutes are rounded differently; a minute and a half is the same
                            diffs += 1
                            out.append((e.get("slug", eid), name, k, a, b))
                    elif a != b:
                        diffs += 1
                        out.append((e.get("slug", eid), name, k, a, b))
    return {"games": games, "players": players, "differences": diffs, "unmatched": unmatched,
            "no_nba_game": missing, "rows": out, "seconds": round(time.time() - t0, 1), "stopped": stopped()}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["compare", "lineups"])
    ap.add_argument("event", nargs="?")
    ap.add_argument("--days", type=float, default=3)
    a = ap.parse_args(argv)
    if a.cmd == "lineups":
        print(json.dumps(event_lineups(a.event), indent=1)[:4000])
        return 0
    r = compare(a.days)
    for slug, name, k, sofa, nba in r["rows"][:60]:
        print(f"  {slug[:38]:38} {name:26} {k:16} SofaScore {sofa}  NBA.com {nba}")
    print(f"\n  {r['games']} game(s), {r['players']} player lines: {r['differences']} stat(s) differ, "
          f"{r['unmatched']} player(s) not matched, {r['no_nba_game']} game(s) not found on NBA.com, "
          f"{r['seconds']}s" + (f"; stopped: {r['stopped']}" if r["stopped"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
