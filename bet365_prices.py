#!/usr/bin/env python3
"""Bet365's player prices for upcoming games, via Oddschecker, for the pages.

    python bet365_prices.py                    # the normal run, from publish.sh
    python bet365_prices.py --add URL [URL..]  # save a match page so its markets are known
    python bet365_prices.py --status           # games held, requests used today

Mirrors paddypower_prices.py. Writes reports/bet365.json in the same shape
(per Betfair-matched fixture id, a list of player lines), which
markets_sidecar.py merges into reports/markets.json as "b365" for the pages.

How a game gets in:
  1. `--add` with the Oddschecker match URL saves the page (about 2 requests)
     to ~/.cache/oddschecker/probe/. Market ids never change for a game, so
     this is once per game.
  2. Each run reads the saved pages, picks out the player markets (shots,
     shots on target, fouls, fouled, tackles, assists, cards), and fetches
     their odds in one batched call per game (oddschecker_client.py, which
     holds the pacing, the saved cookies and the daily cap).
  3. Only Bet365 (Oddschecker code B3) is kept, and each game is matched to
     the site's fixture by kick-off time and team names in market_prices.json.

Gentle by design: only games kicking off within WINDOW_HOURS, never once
started, and not refetched within FRESH_HOURS (FRESH_CLOSE in the last three
hours, when prices move). `touch .bet365_off` switches it off. Never fatal:
any failure leaves the pages on Betfair and Paddy Power.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "reports" / "bet365.json"
OFF = ROOT / ".bet365_off"
PROBE = Path.home() / ".cache" / "oddschecker" / "probe"
MARKET_PRICES = ROOT / "market_prices.json"

BOOK = "B3"            # Oddschecker's code for Bet365
WINDOW_HOURS = 72      # only games kicking off within this (30 Oct 2026: was 30; weekend lines from Thursday)
FRESH_FAR = 12         # games more than a day away: refetched at most every 12 hours
BUDGET_FETCH_MIN = 120 # seconds kept for fetching prices after discovery
FRESH_HOURS = 4        # do not refetch a game within this
FRESH_CLOSE = 0.75     # ...or this, in the last three hours before kick-off
MATCH_MINUTES = 60     # kick-off must agree with the fixture to within this

# Oddschecker market name -> (name the pages already parse, has a line).
# The page names follow paddypower_prices.py so report.py reads both alike.
MARKETS = {
    "player shots": "Player To Have {n} Or More Shots",
    "player shots on target": "Player To Have {n} Or More Shots On Target",
    "player fouls": "Player To Commit {n} Or More Fouls",
    "player fouls won": "Player To Be Fouled {n} Or More Times",
    "player tackles": "Player To Make {n} Or More Tackles",
    "player assists": "Player To Have {n} Or More Assists",
    "to be shown a card": "Player Shown a Card",
}

# Team markets (23 Oct 2026): Oddschecker name -> (the site's stat, scope).
# Every one is an "Over"/"Under" bet with a line, home and away in
# Oddschecker's order (ppHome below lines them up with the fixture, as for
# Paddy Power). Cards are booked as "Yellow cards", as Paddy Power's are.
# Team shots and shots on target are asked for too, though on the 23 Oct
# sample (Arsenal v Everton) Oddschecker listed other books there and no
# Bet365 price; they are kept whenever one appears.
TEAM_MARKETS = {
    "total home corners": ("Corner kicks", "home"),
    "total away corners": ("Corner kicks", "away"),
    "total corners": ("Corner kicks", "match"),
    "total home team cards": ("Yellow cards", "home"),
    "total away team cards": ("Yellow cards", "away"),
    "total cards": ("Yellow cards", "match"),
    "total home goals": ("Goals", "home"),
    "total away goals": ("Goals", "away"),
    "total goals over/under": ("Goals", "match"),
    "total home shots": ("Total shots", "home"),
    "total away shots": ("Total shots", "away"),
    "match total shots": ("Total shots", "match"),
    "total home shots on target": ("Shots on target", "home"),
    "total away shots on target": ("Shots on target", "away"),
    "match shots on target": ("Shots on target", "match"),
}

# Every other team stat Bet365 prices (30 Oct 2026): offsides, fouls, throw-ins,
# goal kicks, tackles, saves, free kicks, shots. Read off the Oddschecker name
# by keyword, so a market appears as soon as Oddschecker lists it, without a
# name being added here by hand. Halves, "most", races, handicaps, player and
# booking-points markets are left out: the model has no number for them.
TEAM_WORDS = [  # checked in order: "shots on target" before "shots"
    ("shots on target", "Shots on target"), ("shots", "Total shots"), ("corners", "Corner kicks"),
    ("offsides", "Offsides"), ("fouls", "Fouls"), ("throw", "Throw-ins"), ("goal kicks", "Goal kicks"),
    ("tackles", "Tackles"), ("saves", "Total saves"), ("free kicks", "Free kicks"), ("cards", "Yellow cards"),
]
TEAM_SKIP = ("half", "1st", "2nd", "player", "most", "race", "first", "last", "handicap", "booking",
             "points", "each", "both", "odd", "even", "minute", "inside", "outside", "headed", "woodwork")


def team_market(name: str):
    """(stat, scope) for an Oddschecker team over/under market name, or None."""
    n = (name or "").lower().strip()
    if n in TEAM_MARKETS:
        return TEAM_MARKETS[n]
    if any(w in n for w in TEAM_SKIP):
        return None
    stat = next((st for w, st in TEAM_WORDS if w in n), None)
    if not stat:
        return None
    scope = "home" if "home" in n else "away" if "away" in n else "match"
    return stat, scope


# Every bookmaker's price, not only Bet365's (30 Oct 2026): the same all-odds
# reply carries them all, so reports/oddschecker_all.json keeps Bet365, Paddy
# Power and the best price per line for the value section (value_books.py).
ALL_OUT = ROOT / "reports" / "oddschecker_all.json"
PLAYER_STAT = {"player shots": "Shots", "player shots on target": "Shots on target",
               "player fouls": "Fouls", "player fouls won": "Fouled", "player tackles": "Tackles",
               "player assists": "Assists", "to be shown a card": "Card"}
KEEP_BOOKS = ("B3", "PP", "SK")   # Bet365, Paddy Power, Sky Bet (Sky added 30 Oct 2026)

# Discovery (30 Oct 2026): each competition's Oddschecker page lists its
# matches, either as links (/path/home-v-away/winner) or in the page's own data
# ("urlMap"). New matches kicking off inside the window get their match page
# saved once (its market ids never change), nearest first, at most
# MAX_NEW_PAGES a run. No more `--add` by hand. Paths checked by hand on
# 30 Oct 2026; the Conference League, NBA and NFL pages do not list matches
# this way.
BASE = "https://www.oddschecker.com/"
COMPETITIONS = [
    "football/english/premier-league", "football/english/championship", "football/english/efl-cup",
    "football/spain/la-liga-primera", "football/italy/serie-a", "football/germany/bundesliga",
    "football/france/ligue-1", "football/champions-league", "football/europa-league",
    "football/world/usa/mls", "football/world/brazil/serie-a",
]
MAX_NEW_PAGES = 12
DISCOVER_SHARE = 0.45      # of the time budget, at most, spent finding games
DISCOVER_SECONDS = 120     # and never more than this
SLUG_RE = re.compile(r'"urlMap"\s*:\s*"([a-z0-9-]+-v-[a-z0-9-]+)"')

NAME_RE = re.compile(r'"(?:marketTypeName|marketName|displayName|name)"\s*:\s*"([^"]{3,80})"')
ID_RE = re.compile(r'"(?:ocMarketId|marketId)"\s*:\s*"?(\d+)')


def norm(s: str) -> str:
    """Same as normName() in the page: accents off, letters and spaces only."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if c.isascii() and (c.isalpha() or c == " "))
    return " ".join(s.lower().split())


# ------------------------------------------------------------ saved pages

def page_markets(html: str) -> dict[str, str]:
    """Player market id -> Oddschecker market name, from a saved match page."""
    out: dict[str, str] = {}
    for m in ID_RE.finditer(html):
        n = NAME_RE.search(html, m.end(), m.end() + 800)
        if n and m.group(1) not in out:
            name = n.group(1).split("#")[-1].strip()
            if name.lower() in MARKETS or team_market(name):
                out[m.group(1)] = name
    return out


def page_all_markets(html: str) -> dict[str, str]:
    """Every market id -> name on a saved page, player or not (for --markets)."""
    out: dict[str, str] = {}
    for m in ID_RE.finditer(html):
        n = NAME_RE.search(html, m.end(), m.end() + 800)
        if n and m.group(1) not in out:
            out[m.group(1)] = n.group(1).split("#")[-1].strip()
    return out


def list_markets(sample: list[str] | None) -> int:
    """List the market names on the saved pages; with --sample, fetch one of
    them for one game (a single request) and print its bets, so team markets
    can be mapped the way the player ones are."""
    import collections
    names = collections.Counter()
    first: dict[str, tuple[str, str]] = {}
    # Sample from a game still to kick off: Oddschecker returns nothing for a
    # market whose game has been played, and the saved pages sort
    # alphabetically, which put Wednesday's Champions League first.
    live = {e.get("page") for e in (load_out().get("events") or {}).values()
            if e.get("kickoff", 0) > time.time()}
    pages = sorted(saved_games(), key=lambda p: p.name not in live)
    for page in pages:
        for mid, name in page_all_markets(page.read_text(errors="ignore")).items():
            names[name] += 1
            first.setdefault(name.lower(), (mid, page.stem))
    for name, n in sorted(names.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {n:3}  {name}")
    if not sample:
        return 0
    from oddschecker_client import OddscheckerClient
    ids = [first[s.lower()][0] for s in sample if s.lower() in first]
    if not ids:
        print("  none of those names are on a saved page")
        return 1
    print(f"\n  sampling {', '.join(sorted({first[s.lower()][1] for s in sample if s.lower() in first}))}")
    with OddscheckerClient() as c:
        got = c.get_many(ids)
        if not got:
            print("  Oddschecker returned nothing for those markets")
        for m in got:
            print(f"\n== {m.get('marketTypeName')} | {m.get('subeventName')}")
            bets = {b.get("betId"): b for b in m.get("bets", []) if isinstance(b, dict)}
            b3 = {o.get("betId"): o.get("oddsDecimal") for o in m.get("odds", []) if o.get("bookmakerCode") == BOOK}
            for bid, b in list(bets.items())[:40]:
                print(f"  {b.get('betName')!r:40} line={b.get('line')!r:8} b365={b3.get(bid)}")
            print("  bet keys:", sorted({k for b in bets.values() for k in b}))
    return 0


def match_slugs(html: str, path: str) -> set[str]:
    """Match slugs ('arsenal-v-everton') on a competition page, both layouts."""
    link = re.compile(r'href="/' + re.escape(path) + r'/([a-z0-9-]+-v-[a-z0-9-]+)/winner"')
    return set(link.findall(html)) | set(SLUG_RE.findall(html))


def page_file(url: str) -> Path:
    """Where a match page is saved: the same name `--add` has always used."""
    slug = re.sub(r"[^a-z0-9]+", "-", url.lower().split("oddschecker.com")[-1]).strip("-")
    return PROBE / f"{slug}.html"


def wanted(slug: str, events: dict, window: float) -> float | None:
    """Kick-off of the site fixture this slug is, if it is inside the window."""
    h, _, a = slug.partition("-v-")
    now = time.time()
    best, best_score = None, 0.0
    for ev in events.values():
        try:
            start = datetime.fromisoformat(ev["start"].replace("Z", "+00:00")).timestamp()
        except (KeyError, ValueError):
            continue
        if not now < start < now + window * 3600:
            continue
        bf = split_teams(ev.get("betfair", ""))
        if not bf:
            continue
        if ev.get("swapped"):
            bf = (bf[1], bf[0])
        score = min(side_score(h, bf[0]), side_score(a, bf[1]))
        if score > best_score:
            best, best_score = start, score
    return best if best_score >= 0.6 else None


DISCOVER_STATE = ROOT / "cache" / "oc_discover.json"
COMP_PER_RUN = 3          # competition pages read a run, oldest-read first
COMP_FRESH_HOURS = 6      # a competition page is not re-read inside this


def _dstate() -> dict:
    try:
        return json.loads(DISCOVER_STATE.read_text())
    except (OSError, ValueError):
        return {}


def discover(client, window: float, budget_end: float) -> int:
    """Save the match page of every new game the site covers inside the window.

    30 Oct 2026: reading all eleven competition pages every run took the whole
    discovery budget (15 to 35 s between requests), so no match page was ever
    saved and every run ended with 0 games. Now a few competitions a run, the
    longest-unread first and none inside COMP_FRESH_HOURS, and the games found
    are remembered (cache/oc_discover.json) so later runs save them without
    reading the competition pages again. Saving pages comes first."""
    events = load_events()
    st = _dstate()
    comp = st.setdefault("comp", {})
    found = st.setdefault("todo", {})          # url -> kick-off
    now = time.time()
    for url in [u for u, ko in found.items() if ko < now or page_file(u).exists()]:
        found.pop(url)

    def save_state():
        DISCOVER_STATE.parent.mkdir(exist_ok=True)
        DISCOVER_STATE.write_text(json.dumps(st, indent=1))

    saved = 0
    PROBE.mkdir(parents=True, exist_ok=True)

    def save_pages():
        nonlocal saved
        for ko, url in sorted((ko, u) for u, ko in found.items()):
            if saved >= MAX_NEW_PAGES or time.time() > budget_end:
                break
            try:
                html = client.get_html(url)
            except Exception as e:  # noqa: BLE001
                if type(e).__name__ == "BudgetExceeded":
                    save_state()
                    raise
                print(f"  bet365: {url} not read ({type(e).__name__})")
                found.pop(url, None)
                continue
            if page_markets(html):
                page_file(url).write_text(html)
                saved += 1
            found.pop(url, None)
            save_state()

    save_pages()                               # games already known go first
    due = sorted((comp.get(p, 0), p) for p in COMPETITIONS
                 if now - comp.get(p, 0) > COMP_FRESH_HOURS * 3600)
    read = 0
    for _, path in due[:COMP_PER_RUN]:
        if time.time() > budget_end:
            break
        try:
            html = client.get_html(BASE + path)
        except Exception as e:  # noqa: BLE001 - BudgetExceeded is handled by the caller
            if type(e).__name__ == "BudgetExceeded":
                save_state()
                raise
            print(f"  bet365: {path} not read ({type(e).__name__})")
            continue
        comp[path] = time.time()
        read += 1
        for slug in match_slugs(html, path):
            url = f"{BASE}{path}/{slug}/winner"
            if page_file(url).exists() or url in found:
                continue
            ko = wanted(slug, events, window)
            if ko:
                found[url] = ko
        save_state()
    save_pages()
    save_state()
    print(f"  bet365: discovery read {read} competition page(s), saved {saved} game page(s), "
          f"{len(found)} still to save")
    return saved


def all_rows(market: dict) -> list[dict]:
    """Every selection in a player or team market with Bet365's, Paddy Power's
    and the best price: {player|stat/scope, line, over, books: {B3, PP}, best, bestBook, n}."""
    name = (market.get("marketTypeName") or "").lower()
    pstat, team = PLAYER_STAT.get(name), team_market(name)
    if not pstat and not team:
        return []
    bets = {b.get("betId"): b for b in market.get("bets", []) if isinstance(b, dict)}
    prices: dict = {}
    for o in market.get("odds", []):
        if o.get("status") != "ACTIVE" or not o.get("oddsDecimal"):
            continue
        try:
            prices.setdefault(o.get("betId"), {})[o.get("bookmakerCode")] = float(o["oddsDecimal"])
        except (TypeError, ValueError):
            continue
    out = []
    for bid, books in prices.items():
        b = bets.get(bid) or {}
        raw = (b.get("betName") or "").strip()
        try:
            line = float(b.get("line")) if b.get("line") not in (None, "") else 0.5
        except (TypeError, ValueError):
            continue
        if line % 1 != 0.5:
            continue
        over = not raw.endswith(" Under") and raw.lower() != "under"
        best_book = max(books, key=books.get)
        row = {"line": line, "over": over, "books": {k: round(v, 3) for k, v in books.items() if k in KEEP_BOOKS},
               "best": round(books[best_book], 3), "bestBook": best_book, "n": len(books)}
        if pstat:
            player = raw[:-5].strip() if raw.endswith(" Over") else raw[:-6].strip() if raw.endswith(" Under") else raw
            if not player:
                continue
            row.update(player=player, key=norm(player), stat=pstat)
        else:
            if raw.lower() not in ("over", "under"):
                continue
            row.update(stat=team[0], scope=team[1])
        out.append(row)
    return out


def retire(page: Path) -> None:
    """Move a finished game's saved page aside so later runs spend no request on it."""
    try:
        (PROBE / "old").mkdir(parents=True, exist_ok=True)
        page.rename(PROBE / "old" / page.name)
    except OSError:
        pass


def saved_games() -> list[Path]:
    return sorted(PROBE.glob("*-v-*.html")) if PROBE.exists() else []


# ------------------------------------------------------------ fixture match

TEAM_DROP = {"fc", "cf", "afc", "sc", "ac", "the", "de", "club"}
ALIASES = {"psg": "paris st g", "paris saint germain": "paris st g", "man utd": "man united",
           "manchester united": "man united", "manchester city": "man city",
           "spurs": "tottenham", "wolverhampton": "wolves", "inter milan": "inter"}


def team_key(s: str) -> str:
    s = norm(s.replace("-", " "))
    s = ALIASES.get(s, s)
    return " ".join(w for w in s.split() if w not in TEAM_DROP)


def side_score(a: str, b: str) -> float:
    a, b = team_key(a), team_key(b)
    if not a or not b:
        return 0.0
    if a == b or a in b or b in a:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def split_teams(name: str) -> tuple[str, str] | None:
    for sep in (" v ", " vs ", " @ "):
        if sep in name:
            h, a = name.split(sep, 1)
            return (a, h) if sep == " @ " else (h, a)
    return None


def match_fixture(oc_name: str, kickoff: float, events: dict) -> str | None:
    teams = split_teams(oc_name)
    if not teams:
        return None
    best, best_score = None, 0.0
    for fid, ev in events.items():
        try:
            start = datetime.fromisoformat(ev["start"].replace("Z", "+00:00")).timestamp()
        except (KeyError, ValueError):
            continue
        if abs(start - kickoff) > MATCH_MINUTES * 60:
            continue
        bf = split_teams(ev.get("betfair", ""))
        if not bf:
            continue
        if ev.get("swapped"):
            bf = (bf[1], bf[0])
        score = min(side_score(teams[0], bf[0]), side_score(teams[1], bf[1]))
        if score > best_score:
            best, best_score = fid, score
    return best if best_score >= 0.6 else None


# ------------------------------------------------------------ lines

def lines_for(market: dict) -> list[dict]:
    template = MARKETS.get((market.get("marketTypeName") or "").lower())
    if not template:
        return []
    bets = {b.get("betId"): b for b in market.get("bets", []) if isinstance(b, dict)}
    # Every other bookmaker's price for the same selection (23 Oct 2026): the
    # market around Bet365, so b365value.py can say whether Bet365 is long or
    # short against everyone else, not only against our model.
    others: dict = {}
    for o in market.get("odds", []):
        if o.get("bookmakerCode") != BOOK and o.get("status") == "ACTIVE" and o.get("oddsDecimal"):
            try:
                others.setdefault(o.get("betId"), []).append(float(o["oddsDecimal"]))
            except (TypeError, ValueError):
                pass
    out = []
    for o in market.get("odds", []):
        if o.get("bookmakerCode") != BOOK or o.get("status") != "ACTIVE" or not o.get("oddsDecimal"):
            continue
        b = bets.get(o.get("betId")) or {}
        raw = (b.get("betName") or "").strip()
        if raw.endswith(" Under"):
            continue
        player = raw[:-5].strip() if raw.endswith(" Over") else raw
        if not player:
            continue
        if "{n}" in template:
            try:
                n = int(float(b.get("line")) + 0.5)
            except (TypeError, ValueError):
                continue
            label = template.format(n=n)
        else:
            label = template
        row = {"market": label, "type": market.get("marketTypeName"), "player": player,
               "key": norm(player), "selection": "", "side": None, "line": None,
               "price": round(float(o["oddsDecimal"]), 3)}
        oth = sorted(others.get(o.get("betId")) or [])
        if oth:
            row["mkt_n"] = len(oth)
            row["mkt_median"] = round(oth[len(oth) // 2] if len(oth) % 2 else
                                      (oth[len(oth) // 2 - 1] + oth[len(oth) // 2]) / 2, 3)
            row["mkt_best"] = round(oth[-1], 3)
        out.append(row)
    return out


def _market_around(market: dict) -> dict:
    """betId -> every other bookmaker's active price for it."""
    others: dict = {}
    for o in market.get("odds", []):
        if o.get("bookmakerCode") != BOOK and o.get("status") == "ACTIVE" and o.get("oddsDecimal"):
            try:
                others.setdefault(o.get("betId"), []).append(float(o["oddsDecimal"]))
            except (TypeError, ValueError):
                pass
    return others


def team_lines_for(market: dict) -> list[dict]:
    """Bet365's team lines in one market, in paddypower_prices.team_lines'
    shape: {stat, scope, line, over, price, market}, half lines only (whole
    lines are Asian, with a push)."""
    got = team_market(market.get("marketTypeName") or "")
    if not got:
        return []
    stat, scope = got
    bets = {b.get("betId"): b for b in market.get("bets", []) if isinstance(b, dict)}
    others = _market_around(market)
    out = []
    for o in market.get("odds", []):
        if o.get("bookmakerCode") != BOOK or o.get("status") != "ACTIVE" or not o.get("oddsDecimal"):
            continue
        b = bets.get(o.get("betId")) or {}
        side = (b.get("betName") or "").strip().lower()
        if side not in ("over", "under"):
            continue
        try:
            line = float(b.get("line"))
        except (TypeError, ValueError):
            continue
        if line % 1 != 0.5:
            continue
        row = {"stat": stat, "scope": scope, "line": line, "over": side == "over",
               "price": round(float(o["oddsDecimal"]), 3), "market": market.get("marketTypeName")}
        oth = sorted(others.get(o.get("betId")) or [])
        if oth:
            row["mkt_n"] = len(oth)
            row["mkt_median"] = round(oth[len(oth) // 2] if len(oth) % 2 else
                                      (oth[len(oth) // 2 - 1] + oth[len(oth) // 2]) / 2, 3)
        out.append(row)
    return out


# ------------------------------------------------------------ run

def work_due(window: float = WINDOW_HOURS) -> int:
    """How many things a run would do now, without a request: saved games never
    priced or gone stale, games found but not saved, and competition pages due.
    Read by lineups_auto.py to decide whether to run the odds job."""
    if OFF.exists():
        return 0
    now = time.time()
    held = {e.get("page"): e for e in (load_out().get("events") or {}).values()}
    n = 0
    for page in saved_games():
        e = held.get(page.name)
        if not e:
            n += 1
            continue
        left = e.get("kickoff", 0) - now
        if left <= 0 or left > window * 3600:
            continue
        fresh = FRESH_CLOSE if left < 3 * 3600 else FRESH_HOURS if left < 24 * 3600 else FRESH_FAR
        if now - e.get("fetchedAt", 0) >= fresh * 3600:
            n += 1
    st = _dstate()
    n += len(st.get("todo") or {})
    comp = st.get("comp") or {}
    n += sum(1 for p in COMPETITIONS if now - comp.get(p, 0) > COMP_FRESH_HOURS * 3600)
    return n


def load_out() -> dict:
    try:
        return json.loads(OUT.read_text())
    except (OSError, ValueError):
        return {"events": {}}


def load_events() -> dict:
    """Fixtures to match against, keyed by the site's fixture id.

    Betfair's matched events, plus the site's own fixture list from the
    reports (market_prices.our_fixtures), so a game Betfair could not match,
    like PSG v Barcelona on 20 Oct 2026, still gets its Bet365 prices."""
    out: dict = {}
    try:
        out.update(json.loads(MARKET_PRICES.read_text()).get("events") or {})
    except (OSError, ValueError):
        pass
    try:
        import market_prices
        for fid, f in market_prices.our_fixtures(2).items():
            start = datetime.fromtimestamp(f["kickoff"], tz=timezone.utc).isoformat()
            out.setdefault(str(fid), {"betfair": f"{f['home']} v {f['away']}", "start": start})
    except Exception as e:  # noqa: BLE001 - fall back to Betfair's list alone
        print(f"  bet365: site fixture list not read ({type(e).__name__}), using Betfair's")
    return out


def drop_ambiguous(lines: list[dict]) -> list[dict]:
    """Settle players Oddschecker names differently in different markets.

    It does not always name a player the same way in every market. Two cases,
    told apart by which name carries most of the markets:

    - An alias: "Herman Haugen" in most markets and "Herman Johan Haugen" in
      one, never both in the same market. The longer, rarer name is the same
      man, so its lines are renamed to the common one and kept.
    - Ambiguous: on 21 October Inter v Shakhtar had "Pedrinho" only in the
      shots market while "Pedrinho da Silva" and "Pedro Henrique Azevedo"
      carried everything else. Matched by name the 2.20 landed on the wrong
      player (Bet365's own page had Pedrinho da Silva at 1.33). A short name
      that is the rarer one, sits inside two or more longer names, or is
      priced in the same market as the longer name could be someone else,
      so its lines are dropped rather than guessed.
    """
    def key(l):
        return norm(l.get("player") or "")
    types: dict[str, set] = {}
    for l in lines:
        if l.get("player"):
            types.setdefault(key(l), set()).add(l.get("type") or l.get("market"))
    toks = {n: set(n.split()) for n in types if n}
    rename, drop = {}, set()
    for n in toks:
        longer = [m for m in toks if m != n and toks[n] and toks[n] < toks[m]]
        if not longer:
            continue
        if len(longer) >= 2:
            drop.add(n)
            continue
        m = longer[0]
        if types[n] & types[m]:
            drop.add(n)                   # both priced in one market: two people
        elif len(types[m]) <= len(types[n]):
            rename[m] = n                 # the long name is a rare alias
        else:
            drop.add(n)                   # the short name is the odd one out
    if drop or rename:
        print(f"  bet365: names merged {sorted(rename.items())}, dropped as ambiguous {sorted(drop)}")
    out = []
    for l in lines:
        k = key(l)
        if k in drop:
            continue
        if k in rename:
            l = dict(l, player=next(x.get("player") for x in lines if key(x) == rename[k]), key=rename[k])
        out.append(l)
    return out


def run(window: float = WINDOW_HOURS, force: bool = False) -> int:
    if OFF.exists():
        print("  bet365: switched off (.bet365_off)")
        return 0
    from oddschecker_client import BudgetExceeded, OddscheckerClient
    try:
        with OddscheckerClient() as c:
            discover(c, window, time.time() + min(DISCOVER_SECONDS, c.left() * DISCOVER_SHARE))
    except BudgetExceeded as e:
        print(f"  bet365: discovery stopped ({e})")
    except Exception as e:  # noqa: BLE001 - never fatal
        print(f"  bet365: discovery failed ({type(e).__name__}: {e})")
    games = saved_games()
    if not games:
        print("  bet365: no match pages saved yet")
        return 0
    try:
        allbooks = json.loads(ALL_OUT.read_text())
    except (OSError, ValueError):
        allbooks = {"events": {}}
    allheld = allbooks.setdefault("events", {})

    data = load_out()
    held = data.setdefault("events", {})
    now = time.time()
    # Drop games that have started.
    for fid in [k for k, e in held.items() if e.get("kickoff", 0) < now]:
        held.pop(fid)
    events = None  # read only if a game needs matching (about 10 seconds)
    fetched = skipped = unmatched = 0

    from oddschecker_client import BUDGET
    # Fetching gets a full budget of its own (30 Oct 2026: 165 s was spent before one game finished).
    with OddscheckerClient(budget=max(BUDGET_FETCH_MIN, BUDGET)) as client:
      try:
        # Never-priced games first (their opening lines), then by kick-off, soonest first.
        ko_of = {e.get("page"): e.get("kickoff", 0) for e in held.values()}
        games = sorted(games, key=lambda p: (p.name in ko_of, ko_of.get(p.name, 0)))
        for page in games:
            ids = list(page_markets(page.read_text(errors="ignore")))
            if not ids:
                continue
            prior = next((e for e in held.values() if e.get("page") == page.name), None)
            if prior:
                left = prior["kickoff"] - now
                if left < 0 or left > window * 3600:
                    skipped += 1
                    continue
                fresh = FRESH_CLOSE if left < 3 * 3600 else FRESH_HOURS if left < 24 * 3600 else FRESH_FAR
                if not force and now - prior.get("fetchedAt", 0) < fresh * 3600:
                    skipped += 1
                    continue
            try:
                markets = client.get_many(ids)
            except SystemExit as e:          # the client's daily cap
                print(f"  bet365: {e}")
                break
            except BudgetExceeded:
                raise
            except Exception as e:           # noqa: BLE001 - never fatal
                print(f"  bet365: {page.stem} not fetched ({type(e).__name__}: {e})")
                break
            if not markets:
                if time.time() - page.stat().st_mtime > 3 * 86400:
                    retire(page)            # nothing priced for days: the game is gone
                continue
            first = markets[0]
            try:
                kickoff = datetime.fromisoformat(first["subeventStartTime"].replace("Z", "+00:00")).timestamp()
            except (KeyError, ValueError):
                continue
            if kickoff < now:
                retire(page)                # played: never ask about it again
                continue
            if events is None:
                events = load_events()
            fid = match_fixture(first.get("subeventName", ""), kickoff, events)
            if not fid:
                unmatched += 1
                print(f"  bet365: {first.get('subeventName')} not matched to a fixture")
                continue
            lines = drop_ambiguous([l for m in markets for l in lines_for(m)])
            team = [t for m in markets for t in team_lines_for(m)]
            sides = split_teams(first.get("subeventName", "")) or ("", "")
            held[fid] = {"ocEvent": first.get("subeventId"), "name": first.get("subeventName"),
                         "page": page.name, "kickoff": kickoff, "fetchedAt": time.time(), "lines": lines,
                         "team": team, "ppHome": sides[0], "ppAway": sides[1]}
            allheld[fid] = {"name": first.get("subeventName"), "kickoff": kickoff, "fetchedAt": time.time(),
                            "home": sides[0], "away": sides[1],
                            "rows": [r for m in markets for r in all_rows(m)]}
            fetched += 1
      except BudgetExceeded as e:
        print(f"  bet365: stopped early ({e}); continuing without the rest")

    data["updated"] = time.time()
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":")))
    for fid in [k for k, e in allheld.items() if e.get("kickoff", 0) < now]:
        allheld.pop(fid)
    allbooks["updated"] = time.time()
    ALL_OUT.write_text(json.dumps(allbooks, separators=(",", ":")))
    print(f"  bet365: {fetched} game(s) fetched, {skipped} still fresh, {unmatched} unmatched, {len(held)} held")
    return 0


def add(urls: list[str]) -> int:
    from oddschecker_client import OddscheckerClient

    PROBE.mkdir(parents=True, exist_ok=True)
    with OddscheckerClient() as c:
        for url in urls:
            slug = re.sub(r"[^a-z0-9]+", "-", url.lower().split("oddschecker.com")[-1]).strip("-")
            sol = c._flaresolverr_get(url)
            c._adopt(sol)
            html = sol.get("response") or ""
            found = page_markets(html)
            if not found:
                print(f"  {url}: no player markets found, not saved")
                continue
            (PROBE / f"{slug}.html").write_text(html)
            print(f"  saved {slug}: {', '.join(sorted(set(found.values())))}")
    return 0


def status() -> None:
    data = load_out()
    for fid, e in sorted((data.get("events") or {}).items(), key=lambda kv: kv[1].get("kickoff", 0)):
        ko = datetime.fromtimestamp(e["kickoff"]).strftime("%a %H:%M")
        age = (time.time() - e.get("fetchedAt", 0)) / 3600
        print(f"  {e.get('name')}  ko {ko}  {len(e.get('lines', []))} lines  {len(e.get('team', []))} team  fetched {age:.1f}h ago  fixture {fid}")
    print(f"  saved pages: {len(saved_games())}")
    try:
        print(f"  requests today: {(PROBE.parent / 'count.json').read_text()}")
    except OSError:
        pass


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--add", nargs="+", metavar="URL")
    p.add_argument("--status", action="store_true")
    p.add_argument("--window", type=float, default=WINDOW_HOURS,
                   help=f"fetch games kicking off within this many hours (default {WINDOW_HOURS}); "
                        "e.g. 60 on a Friday for Sunday's games")
    p.add_argument("--force", action="store_true", help="refetch held games even if fetched recently")
    p.add_argument("--markets", nargs="*", metavar="NAME",
                   help="list every market name on the saved pages; give names to fetch one game's bets for them")
    a = p.parse_args()
    if a.markets is not None:
        return list_markets(a.markets)
    if a.status:
        status()
        return 0
    if a.add:
        return add(a.add)
    return run(a.window, a.force)


if __name__ == "__main__":
    sys.exit(main())
