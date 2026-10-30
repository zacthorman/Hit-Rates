#!/usr/bin/env python3
"""NBA.com stats: minutes, starters and five-man line-ups, for two questions.

    python -B nba_stats.py fetch --season 2025-26 [--max N] [--playoffs]
    python -B nba_stats.py status --season 2025-26
    python -B nba_stats.py withwithout "Mitchell Robinson" --teammate "Karl-Anthony Towns"
    python -B nba_stats.py smallball --season 2025-26 [--who backup-bigs|bigs|all]

Why this exists. SofaScore, which the rest of the repo reads, gives a box
score per player but not who started, and nothing about who was on the floor
together. Two questions need exactly that:

  1. Small ball. Do backup big men (and others) lose minutes and output when
     the opponent plays small? An earlier rough test on 20 games a team was
     inconclusive, and two reasonable definitions of "big" gave opposite
     signs. SofaScore's positions are part of the problem: it lists
     Karl-Anthony Towns as F. NBA.com's listed position (C, C-F, F-C) is
     reliable, and its line-up tables say how many minutes each five-man
     group played, so "how small did the opponent play" can be counted rather
     than guessed.
  2. Injury boosts. When a team-mate is out, how do a player's minutes,
     points, rebounds and assists change? The player game log lists every
     player who got on the floor in every game, so "with" and "without" can
     be split exactly.

Where the data comes from (stats.nba.com, all LeagueID 00):

  leaguegamelog          one request each for teams (T) and players (P): every
                         finished game, and every player's minutes, points,
                         rebounds and assists in it. Refreshed every
                         LOG_MAX_AGE_HOURS, because it grows daily.
  playerindex            one request: each player's listed position (C, F-C,
                         G-F...) and height. Refreshed weekly.
  boxscoretraditionalv3  one request a game: who started. Finished games never
                         change, so the answer is cached for good. v2 has the
                         same data in the older resultSets shape and is read
                         too, but NBA.com stopped filling v2 for new games, so
                         v3 is what is asked for.
  leaguedashlineups      one request a game day, GroupQuantity=5 with DateFrom
                         and DateTo both that day. A team plays at most once a
                         day, so a one-day table is that team's line-ups in
                         that one game. Also cached for good once the day is
                         over.

A whole regular season is about 1,230 box scores and 165 game days, so the
first full fetch is roughly 1,400 requests. At the pace below that is about
an hour, so it is capped per run (--max, default 300) and resumed by running
it again: everything already in cache/nba_stats/ is never asked for twice.

Being polite. stats.nba.com is known to block machines that ask too fast,
and to answer a blocked machine by hanging rather than refusing. So every
request waits MIN_GAP seconds plus up to JITTER more, has a timeout, and any
answer other than a clean 200 with JSON (a 403, a 429, a 5xx, a timeout, a
dropped connection) stops the whole run at once. There is no retry loop:
retrying is how a slow-down turns into a ban. Everything fetched before the
stop is already on disk, so nothing is lost by stopping.

This is a by-hand tool. Nothing in update.py or publish.sh calls it, so it
can never stop the daily build. It writes only under cache/nba_stats/ (cache/
is gitignored).

Not yet run live. stats.nba.com does not answer from the cloud container this
was written in, so the parsers were tested on fixtures built from the
documented response shapes (tests/test_nba_stats.py), not on real answers.
The first live run has to happen on the Mac; see NBA-STATS.md.

Every range printed is a 90% bootstrap range (BOOT draws, fixed seed).
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache" / "nba_stats"

BASE = "https://stats.nba.com/stats"
LEAGUE = "00"
# The headers stats.nba.com expects from its own site. Without a browser
# User-Agent, Referer and Origin it tends to hang rather than refuse.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "Connection": "keep-alive",
}
MIN_GAP, JITTER = 1.5, 1.5        # seconds between real requests (cache hits never wait)
TIMEOUT = (10, 30)                # connect, read
DEFAULT_MAX = 300                 # real requests per run
LOG_MAX_AGE_HOURS = 6             # game logs grow daily
INDEX_MAX_AGE_HOURS = 24 * 7      # listed positions barely move

BIG_POSITIONS = {"C", "C-F", "F-C"}
BOOT = 2000
SEED = 20261028


class Stopped(RuntimeError):
    """stats.nba.com did not give a clean answer, so the run stops here.

    Raised on the first 403, 429, other non-200, timeout, dropped connection
    or non-JSON body. Never caught inside a loop: catching it to try the next
    game would be the retry loop this module refuses to have.
    """


# ------------------------------------------------------------------ parsing

def result_set(data: dict, name: str | None = None) -> list[dict]:
    """Rows of one result set as dicts, header name to value.

    stats.nba.com answers {"resultSets": [{"name", "headers", "rowSet"}]};
    a few endpoints (playerindex among them) say "resultSet" with one dict
    instead of a list. Both are read. With no name, the first set is used.
    """
    sets = data.get("resultSets")
    if sets is None:
        sets = data.get("resultSet")
    if isinstance(sets, dict):
        sets = [sets]
    for rs in sets or []:
        if name is None or rs.get("name") == name:
            headers = rs.get("headers") or []
            return [dict(zip(headers, row)) for row in rs.get("rowSet") or []]
    raise KeyError(f"no result set {name!r}")


def parse_minutes(value: Any) -> float:
    """Minutes played as a float, from any of the shapes NBA.com uses.

    "34:12" (v3), "34.000000:12" (v2 since 2023), "PT34M12.00S" (the live
    feed), a plain number (game logs, line-ups), or empty / None for a player
    who did not play.
    """
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if s.startswith("PT"):
        mins, _, rest = s[2:].partition("M")
        secs = rest.rstrip("S") or "0"
        return float(mins or 0) + float(secs) / 60
    if ":" in s:
        mins, secs = s.split(":", 1)
        return float(mins or 0) + float(secs or 0) / 60
    return float(s)


def parse_box(data: dict) -> dict:
    """One game's box score as {"game_id", "players": [...]}, from v3 or v2.

    Each player: player_id, name, team_id, starter, min, pts, reb, ast,
    comment. In v3 a starter is a player with a "position" (F, C, G); in v2
    it is START_POSITION. A player with a DNP comment comes back with 0
    minutes, which is how a game he missed is told apart from one he was not
    on the roster for.
    """
    if "boxScoreTraditional" in data:
        b = data["boxScoreTraditional"]
        players = []
        for side in ("homeTeam", "awayTeam"):
            team = b.get(side) or {}
            for p in team.get("players") or []:
                st = p.get("statistics") or {}
                players.append({
                    "player_id": int(p["personId"]),
                    "name": f'{p.get("firstName", "")} {p.get("familyName", "")}'.strip(),
                    "team_id": int(team.get("teamId") or 0),
                    "starter": bool((p.get("position") or "").strip()),
                    "min": parse_minutes(st.get("minutes")),
                    "pts": st.get("points") or 0,
                    "reb": st.get("reboundsTotal") or 0,
                    "ast": st.get("assists") or 0,
                    "comment": (p.get("comment") or "").strip(),
                })
        return {"game_id": str(b.get("gameId")), "players": players}
    rows = result_set(data, "PlayerStats")
    players = [{
        "player_id": int(r["PLAYER_ID"]),
        "name": r.get("PLAYER_NAME") or "",
        "team_id": int(r["TEAM_ID"]),
        "starter": bool((r.get("START_POSITION") or "").strip()),
        "min": parse_minutes(r.get("MIN")),
        "pts": r.get("PTS") or 0,
        "reb": r.get("REB") or 0,
        "ast": r.get("AST") or 0,
        "comment": (r.get("COMMENT") or "").strip(),
    } for r in rows]
    gid = str(rows[0]["GAME_ID"]) if rows else ""
    return {"game_id": gid, "players": players}


def parse_lineups(data: dict) -> list[dict]:
    """Five-man line-ups as {"team_id", "ids": (five player ids), "min"}.

    GROUP_ID looks like "-1626157-1628389-1628973-1629628-1630193-": the five
    player ids joined by dashes, with a dash at each end.
    """
    out = []
    for r in result_set(data, "Lineups"):
        ids = tuple(int(x) for x in str(r["GROUP_ID"]).split("-") if x.strip())
        out.append({"team_id": int(r["TEAM_ID"]), "ids": ids, "min": parse_minutes(r.get("MIN"))})
    return out


def parse_team_log(data: dict) -> list[dict]:
    """Team game log rows as {"game_id", "date", "team_id", "team", "opp_id", "opp"}.

    The log has one row per team per game; the opponent is the other row with
    the same GAME_ID. A game with only one row (it happens while a log is
    being updated) is dropped rather than guessed.
    """
    rows = result_set(data, "LeagueGameLog")
    by_game: dict[str, list[dict]] = {}
    for r in rows:
        by_game.setdefault(str(r["GAME_ID"]), []).append(r)
    out = []
    for gid, pair in by_game.items():
        if len(pair) != 2:
            continue
        for me, them in (pair, pair[::-1]):
            out.append({"game_id": gid, "date": str(me["GAME_DATE"])[:10],
                        "team_id": int(me["TEAM_ID"]), "team": me["TEAM_ABBREVIATION"],
                        "opp_id": int(them["TEAM_ID"]), "opp": them["TEAM_ABBREVIATION"]})
    out.sort(key=lambda g: (g["date"], g["game_id"], g["team_id"]))
    return out


def parse_player_log(data: dict) -> list[dict]:
    """Player game log rows: everyone who got on the floor, with his numbers."""
    return [{
        "game_id": str(r["GAME_ID"]), "date": str(r["GAME_DATE"])[:10],
        "player_id": int(r["PLAYER_ID"]), "name": r["PLAYER_NAME"],
        "team_id": int(r["TEAM_ID"]), "min": parse_minutes(r.get("MIN")),
        "pts": r.get("PTS") or 0, "reb": r.get("REB") or 0, "ast": r.get("AST") or 0,
    } for r in result_set(data, "LeagueGameLog")]


def parse_positions(data: dict) -> dict[int, dict]:
    """playerindex as {player_id: {"name", "position", "height"}}."""
    out = {}
    for r in result_set(data):
        name = f'{r.get("PLAYER_FIRST_NAME", "")} {r.get("PLAYER_LAST_NAME", "")}'.strip()
        out[int(r["PERSON_ID"])] = {"name": name, "position": (r.get("POSITION") or "").strip(),
                                    "height": r.get("HEIGHT") or ""}
    return out


def is_big(position: str) -> bool:
    return (position or "").strip().upper() in BIG_POSITIONS


# ------------------------------------------------------------------ fetching

def season_type(playoffs: bool) -> str:
    return "Playoffs" if playoffs else "Regular Season"


def _slug(stype: str) -> str:
    return "po" if stype == "Playoffs" else "rs"


class Client:
    """Cached, paced, stop-on-first-refusal access to stats.nba.com.

    session, sleep and now are injectable so the tests can run it with a fake
    session and no waiting. max_requests counts real requests only; cache
    hits are free. When the cap is reached, fetch() returns None and the
    caller winds down quietly, which is different from Stopped: hitting your
    own cap is not a refusal.
    """

    def __init__(self, cache: Path = CACHE, session: Any = None, max_requests: int = DEFAULT_MAX,
                 sleep: Callable[[float], None] = time.sleep, verbose: bool = True):
        self.cache = Path(cache)
        self._session = session
        self.max_requests = max_requests
        self.sleep = sleep
        self.verbose = verbose
        self.requests = 0
        self._last = 0.0

    def session(self):
        # requests is imported here so the analysis commands, which only read
        # the cache, run on a machine without it.
        if self._session is None:
            import requests
            self._session = requests.Session()
            self._session.headers.update(HEADERS)
        return self._session

    def path(self, key: str) -> Path:
        return self.cache / f"{key}.json"

    def cached(self, key: str, max_age_hours: float | None = None) -> Any | None:
        f = self.path(key)
        if not f.exists():
            return None
        if max_age_hours is not None and time.time() - f.stat().st_mtime > max_age_hours * 3600:
            return None
        try:
            return json.loads(f.read_text())
        except json.JSONDecodeError:
            return None          # half-written by an interrupted run: fetched again

    def save(self, key: str, data: Any) -> None:
        self.cache.mkdir(parents=True, exist_ok=True)
        tmp = self.path(key).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(self.path(key))

    def fetch(self, endpoint: str, params: dict, key: str, max_age_hours: float | None = None,
              keep: Callable[[Any], bool] = lambda d: True) -> Any | None:
        """The cached answer if there is one, else one real request.

        keep(data) decides whether an answer is final enough to cache (a box
        score with no players is not). Raises Stopped on anything but a clean
        JSON 200; returns None only when the run's cap is reached.
        """
        hit = self.cached(key, max_age_hours)
        if hit is not None:
            return hit
        if self.requests >= self.max_requests:
            return None
        wait = self._last + MIN_GAP + random.uniform(0, JITTER) - time.monotonic()
        if self.requests and wait > 0:
            self.sleep(wait)
        self.requests += 1
        url = f"{BASE}/{endpoint}"
        try:
            r = self.session().get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        except Exception as exc:          # timeout, reset, DNS: all mean stop
            raise Stopped(f"{type(exc).__name__} on {endpoint} ({key}); stopping the run") from exc
        finally:
            self._last = time.monotonic()
        if r.status_code != 200:
            raise Stopped(f"HTTP {r.status_code} on {endpoint} ({key}); stopping the run. "
                          f"Wait a few hours before trying again.")
        try:
            data = r.json()
        except ValueError as exc:
            raise Stopped(f"non-JSON answer on {endpoint} ({key}); stopping the run") from exc
        if keep(data):
            self.save(key, data)
        if self.verbose:
            print(f"    fetched {key}")
        return data


def _date_param(iso: str) -> str:
    """stats.nba.com takes dates as MM/DD/YYYY."""
    d = date.fromisoformat(iso)
    return f"{d.month:02d}/{d.day:02d}/{d.year}"


def log_params(season: str, stype: str, who: str) -> dict:
    return {"Counter": 0, "DateFrom": "", "DateTo": "", "Direction": "ASC", "LeagueID": LEAGUE,
            "PlayerOrTeam": who, "Season": season, "SeasonType": stype, "Sorter": "DATE"}


def index_params(season: str) -> dict:
    return {"Active": "", "AllStar": "", "College": "", "Country": "", "DraftPick": "",
            "DraftRound": "", "DraftYear": "", "Height": "", "Historical": 1, "LeagueID": LEAGUE,
            "Season": season, "SeasonType": "Regular Season", "TeamID": 0, "Weight": ""}


def box_params(game_id: str) -> dict:
    return {"GameID": game_id, "LeagueID": LEAGUE, "endPeriod": 0, "endRange": 0,
            "rangeType": 0, "startPeriod": 0, "startRange": 0}


def lineup_params(season: str, stype: str, day: str) -> dict:
    d = _date_param(day)
    return {"Conference": "", "DateFrom": d, "DateTo": d, "Division": "", "GameSegment": "",
            "GroupQuantity": 5, "LastNGames": 0, "LeagueID": LEAGUE, "Location": "",
            "MeasureType": "Base", "Month": 0, "OpponentTeamID": 0, "Outcome": "", "PORound": 0,
            "PaceAdjust": "N", "PerMode": "Totals", "Period": 0, "PlusMinus": "N", "Rank": "N",
            "Season": season, "SeasonSegment": "", "SeasonType": stype, "ShotClockRange": "",
            "TeamID": 0, "VsConference": "", "VsDivision": ""}


def keys(season: str, stype: str) -> dict[str, str]:
    s = f"{season}_{_slug(stype)}"
    return {"team_log": f"gamelog_T_{s}", "player_log": f"gamelog_P_{s}",
            "index": f"playerindex_{season}"}


def _has_players(data: dict) -> bool:
    try:
        return bool(parse_box(data)["players"])
    except Exception:
        return False


def fetch(client: Client, season: str, stype: str, today: date | None = None) -> dict:
    """Game logs, positions, then box scores and line-ups for every finished game.

    Oldest games first, so a capped run fills the cache in order and the
    next run carries on where it stopped. A line-up day is only fetched once
    it is over (before today, UTC, minus a day for US time zones), so a
    half-finished day is never cached as final.
    """
    today = today or datetime.now(timezone.utc).date()
    k = keys(season, stype)
    done = {"box": 0, "lineups": 0, "capped": False}
    team_log = client.fetch("leaguegamelog", log_params(season, stype, "T"), k["team_log"],
                            LOG_MAX_AGE_HOURS)
    if client.fetch("leaguegamelog", log_params(season, stype, "P"), k["player_log"],
                    LOG_MAX_AGE_HOURS) is None:
        done["capped"] = True
    if client.fetch("playerindex", index_params(season), k["index"], INDEX_MAX_AGE_HOURS) is None:
        done["capped"] = True
    if team_log is None:
        done["capped"] = True
        return done
    games = parse_team_log(team_log)
    played = {g["game_id"]: g["date"] for g in games}
    for gid in sorted(played, key=lambda x: (played[x], x)):
        key = f"box_{gid}"
        if client.cached(key) is not None:
            continue
        if client.fetch("boxscoretraditionalv3", box_params(gid), key, keep=_has_players) is None:
            done["capped"] = True
            return done
        done["box"] += 1
    last_final = (today - timedelta(days=1)).isoformat()
    for day in sorted({g["date"] for g in games}):
        if day >= last_final:
            continue
        key = f"lineups_{season}_{_slug(stype)}_{day}"
        if client.cached(key) is not None:
            continue
        if client.fetch("leaguedashlineups", lineup_params(season, stype, day), key) is None:
            done["capped"] = True
            return done
        done["lineups"] += 1
    return done


# ------------------------------------------------------------------ loading

class League:
    """Everything in the cache for one season, parsed. Reads only; never fetches."""

    def __init__(self, team_games, player_games, positions, boxes, lineups):
        self.team_games = team_games          # list of team-game dicts
        self.player_games = player_games      # list of player-game dicts
        self.positions = positions            # {player_id: {name, position, height}}
        self.boxes = boxes                    # {game_id: parsed box}
        self.lineups = lineups                # {date: [lineup dicts]}

    @classmethod
    def from_cache(cls, season: str, stype: str, cache: Path = CACHE) -> "League":
        c = Client(cache=cache, verbose=False)
        k = keys(season, stype)
        tl, pl, ix = (c.cached(k[n]) for n in ("team_log", "player_log", "index"))
        if tl is None or pl is None:
            raise SystemExit(f"No game logs for {season} {stype} in {cache}. "
                             f"Run `nba_stats.py fetch --season {season}` first (on the Mac).")
        team_games = parse_team_log(tl)
        boxes, lineups = {}, {}
        for g in {g["game_id"] for g in team_games}:
            b = c.cached(f"box_{g}")
            if b is not None:
                boxes[g] = parse_box(b)
        for d in {g["date"] for g in team_games}:
            lu = c.cached(f"lineups_{season}_{_slug(stype)}_{d}")
            if lu is not None:
                lineups[d] = parse_lineups(lu)
        return cls(team_games, parse_player_log(pl), parse_positions(ix) if ix else {},
                   boxes, lineups)


# ------------------------------------------------------------------ statistics

def bootstrap_mean_diff(a: list[float], b: list[float], boot: int = BOOT,
                        seed: int = SEED) -> tuple[float, float, float]:
    """mean(a) - mean(b) with a 90% percentile range, resampling each side."""
    if not a or not b:
        return (float("nan"),) * 3
    rng = random.Random(seed)
    est = statistics.fmean(a) - statistics.fmean(b)
    draws = sorted(statistics.fmean(rng.choices(a, k=len(a))) -
                   statistics.fmean(rng.choices(b, k=len(b))) for _ in range(boot))
    return est, draws[int(0.05 * boot)], draws[int(0.95 * boot) - 1]


def bootstrap_mean(xs: list[float], boot: int = BOOT, seed: int = SEED) -> tuple[float, float, float]:
    """mean(xs) with a 90% percentile range."""
    if not xs:
        return (float("nan"),) * 3
    rng = random.Random(seed)
    draws = sorted(statistics.fmean(rng.choices(xs, k=len(xs))) for _ in range(boot))
    return statistics.fmean(xs), draws[int(0.05 * boot)], draws[int(0.95 * boot) - 1]


def _norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    return "".join(ch for ch in s.lower() if ch.isalnum())


def find_player(league: League, name: str) -> tuple[int, str]:
    """Player id from a name: exact (accents and punctuation ignored), else a unique part."""
    names = {}
    for p in league.player_games:
        names.setdefault(p["player_id"], p["name"])
    want = _norm(name)
    exact = [(i, n) for i, n in names.items() if _norm(n) == want]
    if len(exact) == 1:
        return exact[0]
    part = [(i, n) for i, n in names.items() if want in _norm(n)]
    if len(part) == 1:
        return part[0]
    found = ", ".join(sorted(n for _, n in (exact or part))) or "nobody"
    raise SystemExit(f"{name!r} matches {found}; give more of the name")


STATS = ("min", "pts", "reb", "ast")


def with_without(league: League, player: int, teammate: int, since_joined: bool = False) -> dict:
    """His games split by whether the team-mate played, per team they shared.

    "Played" means the team-mate is in that game's player log for the same
    team, so got on the floor. A team-mate who was on the roster but did not
    play (injured, rested, a DNP) counts as without, which is the point.
    Only teams the team-mate played for this season are used. A team-mate
    who arrived by trade mid-season counts the games before he arrived as
    without; since_joined=True starts the split at his first game for the
    team instead.
    """
    by_game: dict[tuple[str, int], set[int]] = {}
    for p in league.player_games:
        if p["min"] > 0:
            by_game.setdefault((p["game_id"], p["team_id"]), set()).add(p["player_id"])
    mate_first: dict[int, str] = {}
    for p in league.player_games:
        if p["player_id"] == teammate and p["min"] > 0:
            t = p["team_id"]
            mate_first[t] = min(mate_first.get(t, p["date"]), p["date"])
    with_, without = [], []
    for p in league.player_games:
        if p["player_id"] != player or p["min"] <= 0 or p["team_id"] not in mate_first:
            continue
        if since_joined and p["date"] < mate_first[p["team_id"]]:
            continue
        (with_ if teammate in by_game.get((p["game_id"], p["team_id"]), ()) else without).append(p)
    out = {"with": len(with_), "without": len(without), "rows": {}}
    for s in STATS:
        a = [float(p[s]) for p in without]
        b = [float(p[s]) for p in with_]
        out["rows"][s] = {
            "with": statistics.fmean(b) if b else float("nan"),
            "without": statistics.fmean(a) if a else float("nan"),
            "diff": bootstrap_mean_diff(a, b),
        }
    return out


def small_share(league: League) -> dict[tuple[str, int], float]:
    """Share of each team-game's line-up minutes with one big or fewer on the floor.

    Keyed by (date, team_id). Big is listed position C, C-F or F-C on
    NBA.com. A line-up player with no listed position counts as not big, and
    is rare (two-way call-ups added after the index was fetched).
    """
    out = {}
    for day, rows in league.lineups.items():
        tot: dict[int, float] = {}
        small: dict[int, float] = {}
        for r in rows:
            bigs = sum(is_big(league.positions.get(i, {}).get("position", "")) for i in r["ids"])
            tot[r["team_id"]] = tot.get(r["team_id"], 0.0) + r["min"]
            if bigs <= 1:
                small[r["team_id"]] = small.get(r["team_id"], 0.0) + r["min"]
        for t, m in tot.items():
            if m > 0:
                out[(day, t)] = small.get(t, 0.0) / m
    return out


def _player_rows(league: League) -> list[dict]:
    """Player-games with starter flags: box scores where cached, else the log."""
    rows = []
    boxed = set(league.boxes)
    for b in league.boxes.values():
        for p in b["players"]:
            if p["min"] > 0:
                rows.append({**p, "game_id": b["game_id"]})
    for p in league.player_games:
        if p["game_id"] not in boxed and p["min"] > 0:
            rows.append({**p, "starter": None})
    return rows


def smallball(league: League, who: str = "backup-bigs", cut: float | None = None,
              min_games: int = 5, min_minutes: float = 8.0) -> dict:
    """Each player's numbers against small and big opponents, within player.

    An opponent is small in a game when its small-ball share (small_share)
    is above cut, the league median of all team-games by default, and big
    otherwise. Each player is compared only with himself, so a player who
    simply plays more against bad teams does not drive the answer.

    who: backup-bigs (listed big, started under half his box-scored games),
    bigs (any listed big), or all. Players need min_games each side and
    min_minutes a game on average.

    Per player: small minus big for minutes, points and rebounds, each with a
    90% range resampling his games. Pooled: the mean of the players'
    differences, with a 90% range resampling players, plus points and
    rebounds per 36 minutes, which says whether a change is minutes or rate.
    """
    share = small_share(league)
    if not share:
        return {"cut": None, "players": [], "pooled": {}, "team_games": 0}
    cut = statistics.median(share.values()) if cut is None else cut
    game_meta = {(g["game_id"], g["team_id"]): g for g in league.team_games}
    per: dict[int, dict] = {}
    for p in _player_rows(league):
        g = game_meta.get((p["game_id"], p["team_id"]))
        if g is None:
            continue
        s = share.get((g["date"], g["opp_id"]))
        if s is None:
            continue
        d = per.setdefault(p["player_id"], {"name": p["name"], "small": [], "big": [],
                                            "starts": 0, "boxed": 0})
        if p["starter"] is not None:
            d["boxed"] += 1
            d["starts"] += bool(p["starter"])
        d["small" if s > cut else "big"].append(p)
    players = []
    for pid, d in per.items():
        pos = league.positions.get(pid, {}).get("position", "")
        if who in ("bigs", "backup-bigs") and not is_big(pos):
            continue
        if who == "backup-bigs" and (d["boxed"] == 0 or d["starts"] / d["boxed"] >= 0.5):
            continue
        games = d["small"] + d["big"]
        if len(d["small"]) < min_games or len(d["big"]) < min_games:
            continue
        if statistics.fmean(g["min"] for g in games) < min_minutes:
            continue
        row = {"player_id": pid, "name": d["name"], "position": pos,
               "n_small": len(d["small"]), "n_big": len(d["big"])}
        for s in ("min", "pts", "reb"):
            row[s] = bootstrap_mean_diff([float(g[s]) for g in d["small"]],
                                         [float(g[s]) for g in d["big"]])
        for s in ("pts", "reb"):
            def per36(gs):
                m = sum(g["min"] for g in gs)
                return 36 * sum(g[s] for g in gs) / m if m else 0.0
            row[f"{s}36"] = per36(d["small"]) - per36(d["big"])
        players.append(row)
    players.sort(key=lambda r: r["min"][0])
    pooled = {}
    if players:
        for s in ("min", "pts", "reb"):
            pooled[s] = bootstrap_mean([r[s][0] for r in players])
        for s in ("pts36", "reb36"):
            pooled[s] = bootstrap_mean([r[s] for r in players])
    return {"cut": cut, "players": players, "pooled": pooled, "team_games": len(share)}


# ------------------------------------------------------------------ printing

def _fmt(t: tuple[float, float, float]) -> str:
    est, lo, hi = t
    return f"{est:+.1f} ({lo:+.1f} to {hi:+.1f})"


def print_withwithout(name: str, mate: str, res: dict) -> None:
    print(f"{name}, with and without {mate}: {res['with']} games with, {res['without']} without")
    print(f"{'':6}{'with':>8}{'without':>9}  without minus with (90% range)")
    for s in STATS:
        r = res["rows"][s]
        print(f"{s:6}{r['with']:8.1f}{r['without']:9.1f}  {_fmt(r['diff'])}")
    if min(res["with"], res["without"]) < 5:
        print("Fewer than five games on one side: the range says more than the estimate.")


def print_smallball(res: dict, who: str) -> None:
    if res["cut"] is None:
        print("No line-up days in the cache yet. Run fetch first (on the Mac).")
        return
    print(f"{res['team_games']} team-games with line-ups. An opponent is small when over "
          f"{res['cut']:.0%} of its line-up minutes had one big or fewer on the floor.")
    print(f"Players ({who}), small-opponent games minus big-opponent games, 90% ranges:")
    print(f"{'player':24}{'pos':5}{'n':>8}  {'minutes':24}{'points':24}{'rebounds'}")
    for r in res["players"]:
        print(f"{r['name'][:23]:24}{r['position']:5}{r['n_small']:>3}/{r['n_big']:<4}  "
              f"{_fmt(r['min']):24}{_fmt(r['pts']):24}{_fmt(r['reb'])}")
    if res["pooled"]:
        p = res["pooled"]
        print(f"\nPooled over {len(res['players'])} players (range resamples players):")
        print(f"  minutes {_fmt(p['min'])}, points {_fmt(p['pts'])}, rebounds {_fmt(p['reb'])}")
        print(f"  per 36: points {_fmt(p['pts36'])}, rebounds {_fmt(p['reb36'])}")


def print_status(season: str, stype: str, cache: Path = CACHE) -> None:
    try:
        lg = League.from_cache(season, stype, cache)
    except SystemExit as e:
        print(e)
        return
    games = {g["game_id"] for g in lg.team_games}
    days = {g["date"] for g in lg.team_games}
    print(f"{season} {stype}: {len(games)} games in the log, {len(lg.boxes)} box scores, "
          f"{len(lg.lineups)} of {len(days)} line-up days, {len(lg.positions)} listed positions")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("fetch", "status", "withwithout", "smallball"):
        sp = sub.add_parser(name)
        sp.add_argument("--season", default="2025-26")
        sp.add_argument("--playoffs", action="store_true")
        if name == "fetch":
            sp.add_argument("--max", type=int, default=DEFAULT_MAX,
                            help="real requests this run (cache hits are free)")
        if name == "withwithout":
            sp.add_argument("player")
            sp.add_argument("--teammate", required=True)
            sp.add_argument("--since-joined", action="store_true",
                            help="only games after the team-mate's first for the team")
        if name == "smallball":
            sp.add_argument("--who", choices=("backup-bigs", "bigs", "all"), default="backup-bigs")
            sp.add_argument("--cut", type=float, default=None,
                            help="small-ball share above which an opponent is small (default: median)")
            sp.add_argument("--min-games", type=int, default=5)
    a = ap.parse_args(argv)
    stype = season_type(a.playoffs)
    if a.cmd == "fetch":
        client = Client(max_requests=a.max)
        try:
            done = fetch(client, a.season, stype)
        except Stopped as e:
            print(f"STOPPED: {e}\n{client.requests} requests made; everything before the stop is cached.")
            return 2
        print(f"{client.requests} requests: {done['box']} box scores, {done['lineups']} line-up days"
              + (" (cap reached; run again to carry on)" if done["capped"] else ", up to date"))
        print_status(a.season, stype)
        return 0
    if a.cmd == "status":
        print_status(a.season, stype)
        return 0
    lg = League.from_cache(a.season, stype)
    if a.cmd == "withwithout":
        pid, pname = find_player(lg, a.player)
        mid, mname = find_player(lg, a.teammate)
        print_withwithout(pname, mname, with_without(lg, pid, mid, a.since_joined))
        return 0
    print_smallball(smallball(lg, a.who, a.cut, a.min_games), a.who)
    return 0


if __name__ == "__main__":
    sys.exit(main())
