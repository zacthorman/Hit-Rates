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
WINDOW_HOURS = 30      # only games kicking off within this
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
            if name.lower() in MARKETS:
                out[m.group(1)] = name
    return out


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
        out.append({"market": label, "type": market.get("marketTypeName"), "player": player,
                    "key": norm(player), "selection": "", "side": None, "line": None,
                    "price": round(float(o["oddsDecimal"]), 3)})
    return out


# ------------------------------------------------------------ run

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


def run() -> int:
    if OFF.exists():
        print("  bet365: switched off (.bet365_off)")
        return 0
    games = saved_games()
    if not games:
        print("  bet365: no saved match pages (add one with: python bet365_prices.py --add URL)")
        return 0
    from oddschecker_client import OddscheckerClient

    data = load_out()
    held = data.setdefault("events", {})
    now = time.time()
    # Drop games that have started.
    for fid in [k for k, e in held.items() if e.get("kickoff", 0) < now]:
        held.pop(fid)
    events = None  # read only if a game needs matching (about 10 seconds)
    fetched = skipped = unmatched = 0

    with OddscheckerClient() as client:
        for page in games:
            ids = list(page_markets(page.read_text(errors="ignore")))
            if not ids:
                continue
            prior = next((e for e in held.values() if e.get("page") == page.name), None)
            if prior:
                left = prior["kickoff"] - now
                if left < 0 or left > WINDOW_HOURS * 3600:
                    skipped += 1
                    continue
                fresh = FRESH_CLOSE if left < 3 * 3600 else FRESH_HOURS
                if now - prior.get("fetchedAt", 0) < fresh * 3600:
                    skipped += 1
                    continue
            try:
                markets = client.get_many(ids)
            except SystemExit as e:          # the client's daily cap
                print(f"  bet365: {e}")
                break
            except Exception as e:           # noqa: BLE001 - never fatal
                print(f"  bet365: {page.stem} not fetched ({type(e).__name__}: {e})")
                break
            if not markets:
                continue
            first = markets[0]
            try:
                kickoff = datetime.fromisoformat(first["subeventStartTime"].replace("Z", "+00:00")).timestamp()
            except (KeyError, ValueError):
                continue
            if kickoff < now:
                continue
            if events is None:
                events = load_events()
            fid = match_fixture(first.get("subeventName", ""), kickoff, events)
            if not fid:
                unmatched += 1
                print(f"  bet365: {first.get('subeventName')} not matched to a fixture")
                continue
            lines = [l for m in markets for l in lines_for(m)]
            held[fid] = {"ocEvent": first.get("subeventId"), "name": first.get("subeventName"),
                         "page": page.name, "kickoff": kickoff, "fetchedAt": time.time(), "lines": lines}
            fetched += 1

    data["updated"] = time.time()
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":")))
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
        print(f"  {e.get('name')}  ko {ko}  {len(e.get('lines', []))} lines  fetched {age:.1f}h ago  fixture {fid}")
    print(f"  saved pages: {len(saved_games())}")
    try:
        print(f"  requests today: {(PROBE.parent / 'count.json').read_text()}")
    except OSError:
        pass


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--add", nargs="+", metavar="URL")
    p.add_argument("--status", action="store_true")
    a = p.parse_args()
    if a.status:
        status()
        return 0
    if a.add:
        return add(a.add)
    return run()


if __name__ == "__main__":
    sys.exit(main())
