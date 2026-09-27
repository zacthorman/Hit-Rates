"""
Cached client for SofaScore's public JSON API.

Every response is written to disk before it is parsed. That means:

  * reruns cost nothing and hit no network
  * you keep the raw data even if SofaScore changes the format later
  * you cannot accidentally hammer them into rate-limiting you

Finished matches never change, so their cache entries are permanent.
Fixture lists and live scores do change, so those pass a max_age.
"""

from __future__ import annotations

import json
import os
import random
import time
from datetime import date
from pathlib import Path
from typing import Any

# curl_cffi is imported inside _get_session rather than here.
#
# It is only needed to make a real request, and several things that use this
# module never make one: backtest.py walks thousands of cached fixtures and
# says so in its own docstring, and rerender.py rebuilds pages from data
# already on disk. A module-level import made those cache-only paths fail on
# any machine without the package installed, for a dependency they never use.

# The site itself calls www.sofascore.com/api/v1, not api.sofascore.com.
# Always use the host the browser uses.
BASE = "https://www.sofascore.com/api/v1"

CACHE_DIR = Path(__file__).parent / "cache"

# Pause between real fetches. Cache hits do not sleep, so this only ever
# applies to traffic that actually leaves the machine.
#
# Overridable from the environment so an unattended run can be politer than
# an interactive one. A person sitting at the keyboard waiting for a report
# will not tolerate four seconds a request; a 7am cron job does not care, and
# the slower it goes the less it looks like something worth blocking.
MIN_DELAY = float(os.environ.get("SOFA_DELAY_MIN", 1.0))
MAX_DELAY = float(os.environ.get("SOFA_DELAY_MAX", 2.0))

# Circuit breaker. If the site starts refusing, the worst thing to do is keep
# asking for an hour: that turns a rate limit into a reputation problem. After
# this many blocks in a row with nothing succeeding in between, everything
# stops and says so.
MAX_CONSECUTIVE_BLOCKS = int(os.environ.get("SOFA_MAX_BLOCKS", 5))
_consecutive_blocks = 0


def _reset_blocks() -> None:
    """A success clears the count.

    Without this, five refusals spread across an entire run would trip the
    breaker even though the run was working fine in between them. Only an
    unbroken streak means anything.
    """
    global _consecutive_blocks
    _consecutive_blocks = 0


class Blocked(RuntimeError):
    """Raised when the site has refused repeatedly and we are backing off.

    Deliberately fatal rather than a return value. A run that quietly carries
    on after being blocked produces reports with holes in them that look
    exactly like reports without holes.
    """

# Competition ids. Find more by opening a league page with DevTools on the
# Network tab and reading the uniqueTournament id out of any request.
TOURNAMENTS = {
    "premier_league": 17,
    "championship": 18,
    "la_liga": 8,
    "serie_a": 23,
    "bundesliga": 35,
    "ligue_1": 34,
    "champions_league": 7,
    # The competition's own name has UEFA on the front of it, and writing it
    # that way squashed to "uefachampionsleague", matched nothing, and the
    # league was skipped in silence. Same failure as the LaLiga one below,
    # found the same way: by its absence from a finished report.
    "uefa_champions_league": 7,
    "europa_league": 679,
    "uefa_europa_league": 679,
    "nfl": 9464,
    "national_football_league": 9464,
    "mls": 242,
    "major_league_soccer": 242,
    # Brazil's top flight is also called Serie A, and "serie_a" above is
    # Italy's. Anything that resolves to Brazil has to say so, which is why
    # there is no bare "serie_a" alias here: a typo that silently built the
    # wrong continent's league would be very hard to spot in a finished report.
    # Basketball. 132 is the NBA proper: the search also returns Summer
    # League, Preseason, the G League and an All Star Game, all of which are
    # basketball and none of which is the competition anyone means.
    "nba": 132,
    "national_basketball_association": 132,
    "brasileirao": 325,
    "brasileirao_serie_a": 325,
    "brazil_serie_a": 325,
    # International football. 10783, read off the tournament's own URL rather
    # than from search, which was returning 403 at the time.
    #
    # --league will technically work -- the group tables answer -- but it
    # resolves to all 54 nations across leagues A to D, which is a fetch you
    # do not want and a report nobody reads. Use --teams for the two or three
    # fixtures you actually care about.
    #
    # Read the note in weekend.py about international form before trusting
    # anything this builds: a national side plays ten matches a year, so a
    # "last 10" window is eighteen months of Nations League, qualifiers and
    # friendlies mixed together, and the opposition ranges from France to
    # San Marino.
    "uefa_nations_league": 10783,
    "nations_league": 10783,
    # Darts. A knockout with no league table, so --league only works through
    # the season-fixtures fallback in tournament_team_ids below. It is also
    # seasonal in the strictest sense: the World Championship is played across
    # Christmas and is a dead id for ten months of the year.
    "pdc_world_championship": 616,
    "world_darts_championship": 616,
    "darts": 616,
}

# Team ids that do not need the search endpoint.
#
# search/all started answering 403 to everything while the match and
# statistics endpoints carried on working normally, which meant --names died
# on the lookup for fixtures the tool could otherwise build perfectly well.
# The ids themselves are not secret: they are in the URL of every team page on
# the site, so anything read off there once never needs asking for again.
#
# National sides are the ones worth keeping, because their names are stable
# and there is no league table to enumerate them from. Same idea as
# nfl_teams.py, which exists because search used to answer NFL queries with
# soccer clubs.
KNOWN_TEAM_IDS = {
    "england": 4713, "spain": 4698, "france": 4481, "italy": 4707,
    "belgium": 4717, "germany": 4711, "netherlands": 4705, "portugal": 4704,
    "croatia": 4715, "czechia": 4714, "scotland": 4695, "switzerland": 4699,
}


def known_team_id(name: str) -> int | None:
    """A team id from the built-in table, or None. Never touches the network."""
    return KNOWN_TEAM_IDS.get("".join(
        c for c in (name or "").lower() if c.isalnum()))


def tournament_id_for(name: str) -> int | None:
    """Competition name to id, forgiving about how it is written.

    "LaLiga", "La Liga", "la-liga" and "LA LIGA" all mean the same competition
    and all now resolve. Before this, "LaLiga" normalised to "laliga", the
    table held "la_liga", and the whole league was skipped. It failed inside a
    fourteen hour scheduled run whose output was being captured rather than
    streamed, so the only trace was the word "Failed" with no reason attached.
    """
    if not name:
        return None

    # Accents are stripped as well as punctuation. Python counts an accented
    # letter as alphanumeric, so "Brasileirao" and "Brasileirao" written with
    # the tilde squash to different strings and only one of them would match.
    # That is the same class of bug as the LaLiga one above, and it would fail
    # the same silent way.
    import unicodedata
    folded = unicodedata.normalize("NFKD", name.lower())
    squashed = "".join(c for c in folded if c.isalnum() and not unicodedata.combining(c))
    for key, tournament_id in TOURNAMENTS.items():
        if "".join(c for c in key if c.isalnum()) == squashed:
            return tournament_id
    return None


_session = None

# Which browser to look like on the wire.
#
# This was the bare alias "chrome", which curl_cffi maps to a default that
# ages: the installed 0.16.0 ships targets up to chrome146, and the default
# is years behind them. An old TLS and HTTP/2 fingerprint is precisely what a
# bot filter is looking for, and it is why every request started coming back
# 403 while the same URL served 200 to the real Chrome on the same machine.
#
# Overridable, because this will go stale again. When it does, raise it to
# the newest target the installed curl_cffi lists rather than assuming a ban:
#   python -c "from curl_cffi.requests.impersonate import BrowserTypeLiteral; \
#              import typing; print(typing.get_args(BrowserTypeLiteral))"
IMPERSONATE = os.environ.get("SOFA_IMPERSONATE", "chrome142")

# FlareSolverr route. Opt-in: set SOFA_FLARESOLVERR=1 (or a full URL) and
# every request goes through a real Chrome in the FlareSolverr container
# instead of curl_cffi. Slower per request, but it gets past Cloudflare
# challenges that a fingerprint alone no longer does. Everything downstream
# (cache, backoff, circuit breaker) is unchanged because this answers the
# same .get() / .status_code / .json() calls a curl_cffi session does.
FLARESOLVERR = os.environ.get("SOFA_FLARESOLVERR", "")
if FLARESOLVERR in ("1", "true", "yes"):
    FLARESOLVERR = "http://localhost:8191/v1"


class _FlareResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text

    def json(self):
        # Raises json.JSONDecodeError on non-JSON, which get_json already handles.
        return json.loads(self.text)


class _FlareSession:
    """Looks enough like a curl_cffi session for get_json not to notice."""

    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        # One browser session for the whole run, so the Cloudflare clearance
        # cookie is reused instead of re-solved on every request.
        created = self._call({"cmd": "sessions.create"}, timeout=60)
        self.session_id = created.get("session")

    def _call(self, payload: dict, timeout: float) -> dict:
        import urllib.request
        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

    def get(self, url: str, timeout: float = 30):
        import html
        import re

        wait = max(timeout, 60)
        payload = {"cmd": "request.get", "url": url, "maxTimeout": int(wait * 1000)}
        if self.session_id:
            payload["session"] = self.session_id
        out = self._call(payload, timeout=wait + 30)

        if out.get("status") != "ok":
            # FlareSolverr could not get through. Report it as a block so the
            # circuit breaker counts it, rather than as a network fault that
            # would just be retried.
            return _FlareResponse(403, "")

        sol = out.get("solution") or {}
        body = sol.get("response") or ""
        # Chrome shows a JSON response wrapped in <pre>...</pre>.
        m = re.search(r"<pre[^>]*>(.*?)</pre>", body, re.S)
        text = html.unescape(m.group(1)) if m else body
        return _FlareResponse(int(sol.get("status") or 0), text)

def _get_session():
    """One session for the whole run, so cookies persist between requests.

    Reusing a session matters more than any individual header: once
    Cloudflare has decided you are acceptable, the clearance cookie rides
    along on everything afterwards.
    """
    global _session
    if _session is None and FLARESOLVERR:
        _session = _FlareSession(FLARESOLVERR)
    if _session is None:
        from curl_cffi import requests
        _session = requests.Session(impersonate=IMPERSONATE)
        _session.headers.update(
            {
                "Accept": "*/*",
                "Accept-Language": "en-GB,en;q=0.9",
                "Referer": "https://www.sofascore.com/",
                "Origin": "https://www.sofascore.com",
                # What a real XHR from the site sends. Their edge checks
                # these, and a request without them is obviously not a page.
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        _warm(_session)
    return _session

def _warm(session) -> None:
    """Load one ordinary page before asking the API anything.

    The docstring above has always said the clearance cookie rides along on
    everything once you are accepted. Nothing ever went and got one. The
    session was created, had headers set, and went straight at /api/v1 with
    an empty cookie jar -- which is a request that looks like nothing a
    browser has ever sent, because a browser loads the site first.

    That is what the 403s were. The endpoint had not moved: the very same URL
    returned 200 from Chrome on the same machine at the same minute. Only the
    caller looked wrong.

    One request, failures ignored: if this does not work the API call is no
    worse off than before.
    """
    try:
        session.get("https://www.sofascore.com/", timeout=20)
    except Exception:
        pass


# How many times one request is attempted, and how long to wait between
# tries when the failure is the network rather than the server.
#
# This used to be three tries over seven seconds, which is not patience, it is
# a formality. A Mac coming back from sleep, or a router re-establishing a
# connection, takes longer than that to resolve a name again -- and on the
# night of 15 September it cost four leagues: Premier League, Championship,
# La Liga and Serie A all died on DNSError inside the first thirty seconds of
# the run, while every league attempted after 20:00 built without a hitch.
# Nothing was wrong except that the job started a moment too early.
#
# Waiting longer here is free. A transport error means no request reached
# SofaScore at all, so retrying costs them nothing and is not the behaviour
# rate limiting is meant to discourage. The 403 path below is untouched and
# still stops hard at the fifth refusal.
ATTEMPTS = 6
NET_BACKOFF = (2, 5, 10, 20, 30, 30)

# Set to the exception name when a request fails before reaching the server,
# cleared the moment one gets through. Callers use it to tell "the network
# dropped" apart from "the endpoint has moved", which look identical from the
# outside and have completely different fixes.
_last_transport_error: str | None = None


def last_transport_error() -> str | None:
    """Why the most recent request failed, if it failed before being sent."""
    return _last_transport_error


def _cache_file(path: str) -> Path:
    """Human-readable cache filename, so you can browse what you've collected.

    'event/123/statistics' becomes 'event_123_statistics.json'. Hashing the
    URL would work too, but then debugging means staring at files called
    a3f9c2....json.
    """
    name = path.strip("/").replace("/", "_").replace("?", "_").replace("&", "_")
    return CACHE_DIR / f"{name}.json"


def get_json(
    path: str,
    max_age_hours: float | None = None,
    verbose: bool = True,
) -> Any | None:
    """Fetch an API path, reusing the cached copy when there is one.

    max_age_hours=None means the cache never expires, which is correct for
    anything about a finished match. Pass a number for data that moves.

    Returns None on any non-200, so callers decide what a failure means.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _cache_file(path)

    if cache_file.exists():
        fresh = max_age_hours is None or (
            time.time() - cache_file.stat().st_mtime < max_age_hours * 3600
        )
        if fresh:
            try:
                return json.loads(cache_file.read_text())
            except json.JSONDecodeError:
                # Half-written file from an interrupted run. Drop it and refetch.
                cache_file.unlink(missing_ok=True)

    url = f"{BASE}/{path.strip('/')}"

    for attempt in range(ATTEMPTS):
        try:
            response = _get_session().get(url, timeout=30)
        except Exception as exc:
            global _last_transport_error
            _last_transport_error = type(exc).__name__
            wait = NET_BACKOFF[min(attempt, len(NET_BACKOFF) - 1)]
            if verbose:
                print(f"    {type(exc).__name__} on {path}, retrying in {wait}s")
            time.sleep(wait)
            continue

        _last_transport_error = None

        if response.status_code == 200:
            try:
                data = response.json()
            except json.JSONDecodeError:
                if verbose:
                    print(f"    non-JSON response on {path}")
                return None
            cache_file.write_text(json.dumps(data))
            # Sleep only after a real network call. Cache hits return above,
            # so a fully cached run is instant.
            _reset_blocks()
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
            return data

        if response.status_code == 404:
            # Usually means "this genuinely does not exist" rather than an
            # error, so no retry and no cache. Still worth saying out loud:
            # a silent 404 is indistinguishable from an empty result, and
            # that ambiguity wastes a lot of debugging time.
            if verbose:
                print(f"    404 on {path}")
            return None

        if response.status_code in (403, 429):
            global _consecutive_blocks
            _consecutive_blocks += 1
            if _consecutive_blocks >= MAX_CONSECUTIVE_BLOCKS:
                raise Blocked(
                    f"{_consecutive_blocks} refusals in a row from SofaScore "
                    f"({response.status_code}). Stopping rather than hammering "
                    f"it. Wait a few hours and try again; if it persists, raise "
                    f"SOFA_DELAY_MIN and SOFA_DELAY_MAX and rebuild fewer "
                    f"leagues at a time. Everything already in cache/ still works."
                )
            wait = (2**attempt) * 5
            if verbose:
                print(f"    {response.status_code} on {path}, backing off {wait}s "
                      f"({_consecutive_blocks}/{MAX_CONSECUTIVE_BLOCKS} before stopping)")
            time.sleep(wait)
            continue

        if verbose:
            print(f"    unexpected {response.status_code} on {path}")
        time.sleep(2**attempt)

    return None


# --------------------------------------------------------------- endpoints


def current_season_id(tournament_id: int) -> int | None:
    """The most recent season for a competition."""
    data = get_json(f"unique-tournament/{tournament_id}/seasons", max_age_hours=168)
    seasons = (data or {}).get("seasons", [])
    return seasons[0]["id"] if seasons else None


def season_ids(tournament_id: int, count: int = 4) -> list[int]:
    """Recent season ids, newest first.

    Needed because a club's standard is judged on where it finished LAST
    season, not on this one, which in August is three games old and tells
    you nothing.
    """
    data = get_json(f"unique-tournament/{tournament_id}/seasons", max_age_hours=168)
    seasons = (data or {}).get("seasons", [])
    return [s["id"] for s in seasons[:count] if isinstance(s.get("id"), int)]


def previous_season_id(tournament_id: int) -> int | None:
    """Last completed season. The current one is index 0, so this is index 1."""
    ids = season_ids(tournament_id, count=2)
    return ids[1] if len(ids) > 1 else None


def tournament_table(
    tournament_id: int, season_id: int | None = None
) -> list[dict]:
    """The final league table: one row per club, in finishing order.

    Returns [{"id", "name", "position", "points", "played"}]. Position is
    taken from the table's own ordering rather than a field, because the
    field is missing on some competitions and the row order never is.
    """
    if season_id is None:
        season_id = current_season_id(tournament_id)
    if season_id is None:
        return []

    data = get_json(
        f"unique-tournament/{tournament_id}/season/{season_id}/standings/total",
        max_age_hours=168,
    )

    tables: list[list[dict]] = []
    for standing in (data or {}).get("standings", []):
        table: list[dict] = []
        # A competition with groups returns several standings blocks. Only
        # the overall league table is wanted, and that is the one whose type
        # is "total" with no group name.
        for i, row in enumerate(standing.get("rows", []), start=1):
            team = row.get("team", {})
            if not isinstance(team.get("id"), int):
                continue
            table.append(
                {
                    "id": team["id"],
                    "name": team.get("name", "?"),
                    "position": row.get("position") or i,
                    "points": row.get("points"),
                    "played": row.get("matches"),
                }
            )
        if table:
            tables.append(table)

    # The biggest block is the overall table.
    #
    # This used to take the first non-empty one, on the assumption that a
    # competition has a single table. The NFL puts the AFC first, so a tier
    # map built from it saw sixteen clubs and called the other half of the
    # league bottom; a pre-2024 Champions League season put Group A first and
    # it saw four. Size is the honest discriminator: a conference or a group
    # is by definition a slice of the thing we want.
    return max(tables, key=len) if tables else []


def tournament_team_ids(tournament_id: int, season_id: int | None = None) -> list[int]:
    """Every team in a competition, read off the league table.

    Used so you can say "the Premier League" instead of listing twenty ids.
    Returns an empty list if the endpoint has moved, and the caller decides
    what to do about it.
    """
    if season_id is None:
        season_id = current_season_id(tournament_id)
    if season_id is None:
        return []

    data = get_json(
        f"unique-tournament/{tournament_id}/season/{season_id}/standings/total",
        max_age_hours=24,
    )

    # A knockout has no table. Darts, cups and the Champions League since 2024
    # all 404 here, and returning nothing made --league silently useless for
    # every one of them -- it looked like the competition had no teams rather
    # than no table. The fixtures know who is in it, so read them instead.
    if not (data or {}).get("standings"):
        return _team_ids_from_fixtures(tournament_id, season_id)

    # De-duplicated, because a competition can describe itself several ways.
    #
    # A football league returns one table and this never mattered. The NFL
    # returns eleven: the AFC, the NFC, eight divisions and an overall table,
    # with every club appearing in three of them. Appending blindly reported
    # 96 teams for a 32-team league, which means fitting ratings would have
    # fetched each club's season three times over and spent an hour doing it.
    ids: list[int] = []
    seen: set[int] = set()
    for standing in (data or {}).get("standings", []):
        for row in standing.get("rows", []):
            team = row.get("team", {})
            if isinstance(team.get("id"), int) and team["id"] not in seen:
                seen.add(team["id"])
                ids.append(team["id"])
    return ids


def _team_ids_from_fixtures(tournament_id: int, season_id: int) -> list[int]:
    """Everyone who has played or is due to play in a competition with no table.

    Both directions, because a knockout early in its run has almost nothing
    finished and one late in its run has almost nothing left. Order is by first
    appearance, which for a seeded draw is roughly seeding order and is as good
    a default as anything.
    """
    ids: list[int] = []
    seen: set[int] = set()
    for direction in ("last", "next"):
        data = get_json(
            f"unique-tournament/{tournament_id}/season/{season_id}"
            f"/events/{direction}/0",
            max_age_hours=6,
        )
        for event in (data or {}).get("events", []):
            for side in ("homeTeam", "awayTeam"):
                team = event.get(side) or {}
                if isinstance(team.get("id"), int) and team["id"] not in seen:
                    seen.add(team["id"])
                    ids.append(team["id"])
    return ids


def team_next_events(team_id: int, page: int = 0) -> list[dict]:
    """A team's upcoming fixtures, soonest first."""
    data = get_json(f"team/{team_id}/events/next/{page}", max_age_hours=6)
    return (data or {}).get("events", [])


def team_near_events(team_id: int) -> dict:
    """The team's most recent match and their next one."""
    return get_json(f"team/{team_id}/near-events", max_age_hours=6) or {}


def _looks_like_team(node: dict, sport: str = "football") -> bool:
    """Does this node look like a competitor in the sport being searched for?

    The sport filter used to be the literal string "football", which is why
    nfl_teams.py exists: --search answered an NFL query with soccer clubs, so
    the ids had to be written out by hand. Darts would have hit the same wall,
    and a darts "team" is a man. None means take anything team-shaped.
    """
    return (
        isinstance(node.get("id"), int)
        and isinstance(node.get("name"), str)
        and "slug" in node
        and "sport" in node
        and (sport is None or node.get("sport", {}).get("slug") == sport)
    )


def _harvest_teams(node, found: dict, sport: str = "football") -> None:
    """Walk an arbitrary JSON tree collecting anything shaped like a team.

    The search endpoint's response shape is not documented and has changed
    before, so rather than hardcode a path this just looks for the shape.
    Slower, but it survives them rearranging things.
    """
    if isinstance(node, dict):
        if _looks_like_team(node, sport):
            found.setdefault(node["id"], node)
        for value in node.values():
            _harvest_teams(value, found, sport)
    elif isinstance(node, list):
        for item in node:
            _harvest_teams(item, found, sport)


def search_teams(query: str, sport: str = "football") -> list[dict]:
    """Find teams by name, so you don't have to know ids.

    Tries a few known search paths and uses whichever answers. Defaults to
    football so every existing caller behaves exactly as before; pass another
    sport slug, or None for all of them.
    """
    candidates = [
        f"search/teams?q={query}&page=0",
        f"search/all?q={query}&page=0",
        f"search/{query}",
    ]

    for path in candidates:
        data = get_json(path, max_age_hours=24, verbose=False)
        if not data:
            continue
        found: dict[int, dict] = {}
        _harvest_teams(data, found, sport)
        if found:
            return list(found.values())

    return []


def team_events(team_id: int, page: int = 0) -> list[dict]:
    """A team's past matches, ~30 per page. Page 0 is the most recent.

    Returned oldest-first, so the most recent are at the end of the list.
    """
    data = get_json(f"team/{team_id}/events/last/{page}", max_age_hours=6)
    return (data or {}).get("events", [])


def team_squad(team_id: int) -> list[dict]:
    """The team's current squad.

    Needed because a "last 10 matches" sample straddles the transfer window.
    Without this you get last season's departed striker sitting near the top
    of the shots table, which is worse than useless: it looks like a finding.
    """
    data = get_json(f"team/{team_id}/players", max_age_hours=24)
    players = (data or {}).get("players", [])
    return [p.get("player", p) for p in players if isinstance(p, dict)]


def squad_player_ids(team_id: int) -> set[int]:
    return {p["id"] for p in team_squad(team_id) if isinstance(p.get("id"), int)}


def event_statistics(event_id: int) -> dict | None:
    """Team-level match stats: shots, corners, offsides, throw-ins, cards."""
    return get_json(f"event/{event_id}/statistics")


def event_details(event_id: int, max_age_hours: float | None = 12) -> dict | None:
    """The full record for a single match: venue, attendance and, once one
    has been appointed, the referee - complete with SofaScore's running card
    totals for him (yellowCards, redCards, yellowRedCards, games), which is
    what makes a card rate possible without any per-referee endpoint.

    Twelve hours of cache, not permanent, and that is deliberate. This is
    called for UPCOMING fixtures, and referee appointments are typically
    published only a few days before kick-off. A permanent cache taken a week
    out would freeze "no referee yet" forever; twelve hours means the daily
    07:00 run re-asks once a day until the name appears. The cache file is
    event_{id}.json, the same entry a finished match would use, so nothing
    is fetched twice.
    """
    data = get_json(f"event/{event_id}", max_age_hours=max_age_hours)
    if not isinstance(data, dict):
        return None
    event = data.get("event")
    return event if isinstance(event, dict) else None


def h2h_events(event_id: int) -> list[dict]:
    """Dead endpoint. Kept only so its absence is documented, not repeated.

    SofaScore removed event/{id}/h2h/events. It returned 404 for all 87
    fixtures of the 1 September 2026 run, which is why the report's Head to
    head button stayed disabled for days while the flag, the config and the
    payload were all correct. Nothing calls this now: hitrates.head_to_head
    derives meetings from the two clubs' own match feeds instead, which costs
    no extra request and cannot be taken away.

    If you are tempted to wire it back in, check it returns something first.
    """
    data = get_json(f"event/{event_id}/h2h/events", max_age_hours=168)
    return (data or {}).get("events", [])


def event_lineups(event_id: int) -> dict | None:
    """Per-player stats for one match."""
    return get_json(f"event/{event_id}/lineups")


def cache_summary() -> str:
    if not CACHE_DIR.exists():
        return "cache is empty"
    files = list(CACHE_DIR.glob("*.json"))
    size = sum(f.stat().st_size for f in files) / 1_000_000
    return f"{len(files)} cached responses, {size:.1f} MB"
