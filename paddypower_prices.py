#!/usr/bin/env python3
"""Paddy Power's prices for upcoming games, read gently from its page feed.

    python paddypower_prices.py                 # the normal run, from publish.sh
    python paddypower_prices.py --event 36160515  # one game by Paddy Power id, print its lines
    python paddypower_prices.py --status        # caps, lockout and what is held

One GET per game to the feed the Paddy Power event page itself uses
(smspp/event-page), logged out, no cookies, no account. It returns every market
on the game with names, lines and prices. Written to reports/paddypower.json
for the pages, merged into reports/markets.json by markets_sidecar.py.

THIS IS PADDY POWER'S PRIVATE FEED, NOT A PUBLIC API, and it runs from Zac's
home connection, the one he bets from. Everything below exists to keep the
footprint smaller than one person browsing the site, and to stop at the first
sign Paddy Power minds:

  - Off switch: an empty file `.paddypower_off` in this folder stops it dead.
  - Lockout: any refusal (403, 429, 5xx, a timeout, a non-JSON reply) writes a
    lockout and nothing is requested for LOCKOUT_HOURS. No retries, ever.
  - Caps: at most MAX_PER_RUN games a run and MAX_PER_DAY a day.
  - Spacing: MIN_GAP to MIN_GAP + JITTER seconds between requests, randomised,
    and never sooner than MIN_GAP after the last request of any earlier run.
  - Only what is useful: games kicking off within WINDOW_HOURS, never once
    started, and a game is not fetched again within FRESH_HOURS (FRESH_CLOSE
    in the last three hours before kick-off, when prices actually move).
  - One run at a time: a lock file, so publish.sh and the line-ups job can
    never overlap and double the rate.
  - Ids are checked: Paddy Power's event id is tried as Betfair's (same
    company, same platform). The team names on the reply must match the
    fixture; a mismatch or a 400 stops the run and records that the mapping
    does not hold, so it does not keep asking for the wrong things.

Never fatal: any failure leaves the site on its estimates.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import random
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "reports" / "paddypower.json"
STATE = ROOT / "cache" / "paddypower_state.json"
LOCK = ROOT / "cache" / "paddypower.lock"
OFF = ROOT / ".paddypower_off"

MIN_GAP = 15          # seconds between requests, at least
JITTER = 15           # plus up to this much, randomised
MAX_PER_RUN = 15      # games per run
MAX_PER_DAY = 60      # games per day, across all runs
WINDOW_HOURS = 30     # only games kicking off within this
FRESH_HOURS = 4       # do not refetch a game inside this
FRESH_CLOSE = 1       # ...or this, in the last 3 hours before kick-off
LOCKOUT_HOURS = 24    # after any refusal
KEEP_AFTER_KO = 6     # hours a game's prices are kept after kick-off

BASE = "https://apisms.paddypower.com/smspp/event-page/v5"
PARAMS = {
    "_ak": "vsd0Rm5ph2sS2uaK", "betexRegion": "GBR", "capiJurisdiction": "intl",
    "countryCode": "GB", "currencyCode": "GBP", "exchangeLocale": "en_GB",
    "includeBettingOpportunities": "false", "includePrices": "true",
    "includeSeoCards": "true", "includeSeoFooter": "true", "language": "en",
    "loggedIn": "false", "priceHistory": "1", "regionCode": "UK", "tab": "bet-builder",
}
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Origin": "https://www.paddypower.com",
    "Referer": "https://www.paddypower.com/",
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
}


class Refused(Exception):
    """Paddy Power said no, or something like it. Stop and lock out."""


class BadId(Exception):
    """A 400: the id was not one Paddy Power knows. Stop, but no lockout."""


# ------------------------------------------------------------------ state

def now() -> float:
    return time.time()


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1))


def today() -> str:
    # UTC, so the daily cap is one day whatever clock reads it.
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def lockout(st: dict, why: str) -> None:
    st["lockoutUntil"] = now() + LOCKOUT_HOURS * 3600
    st["lockoutWhy"] = why
    save_state(st)
    print(f"  paddypower: locked out for {LOCKOUT_HOURS}h ({why})")


def blocked(st: dict) -> str | None:
    if OFF.exists():
        return "switched off (.paddypower_off)"
    if st.get("lockoutUntil", 0) > now():
        left = (st["lockoutUntil"] - now()) / 3600
        return f"locked out {left:.1f}h more ({st.get('lockoutWhy')})"
    if st.get("idMapping") is False:
        return "Betfair ids do not work as Paddy Power ids; needs another way to find games"
    return None


def count_today(st: dict) -> int:
    return st.get("count", 0) if st.get("day") == today() else 0


def bump(st: dict) -> None:
    if st.get("day") != today():
        st["day"], st["count"] = today(), 0
    st["count"] = st.get("count", 0) + 1
    st["lastRequest"] = now()
    save_state(st)


def wait_turn(st: dict) -> None:
    gap = MIN_GAP + random.uniform(0, JITTER)
    since = now() - st.get("lastRequest", 0)
    if since < gap:
        time.sleep(gap - since)


# ------------------------------------------------------------------ fetch

def fetch_event(event_id) -> dict:
    url = BASE + "?" + urllib.parse.urlencode(dict(PARAMS, eventId=str(event_id)))
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 404):
            raise BadId(f"HTTP {exc.code}")
        raise Refused(f"HTTP {exc.code}")
    except Exception as exc:
        raise Refused(f"{type(exc).__name__}")
    try:
        data = json.loads(body)
    except ValueError:
        raise Refused("reply was not JSON (a challenge page?)")
    if "attachments" not in data:
        raise Refused("reply had no markets")
    return data


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return " ".join("".join(c for c in s if c.isascii() and (c.isalpha() or c == " ")).lower().split())


def player_lines(page: dict) -> list[dict]:
    """Every open selection in a player market."""
    out = []
    markets = ((page.get("attachments") or {}).get("markets") or {})
    for m in markets.values():
        mtype = m.get("marketType", "")
        name = m.get("marketName", "")
        player, sep, market = name.partition(" - ")
        # NFL: PLAYER_X_* (one market per player, "Name - Market").
        # Football: one market per line with every player as a runner,
        # e.g. PLAYER_TO_HAVE_2_OR_MORE_SHOTS. First-half and each-half
        # versions are skipped: there are no player numbers by half.
        halves = ("FIRST_HALF" in mtype or "1ST_HALF" in mtype or "EACH_HALF" in mtype)
        is_player = (mtype.startswith("PLAYER_X")
                     or (mtype.startswith("PLAYER_TO_") and not halves)
                     or mtype in ("ANY_TIME_TOUCHDOWN_SCORER", "ANYTIME_GOALSCORER", "TO_SCORE",
                                  "TO_BE_BOOKED", "ANYTIME_ASSIST"))
        if not is_player:
            continue
        for r in m.get("runners", []):
            if r.get("runnerStatus") != "ACTIVE":
                continue
            try:
                price = r["winRunnerOdds"]["trueOdds"]["decimalOdds"]["decimalOdds"]
            except (KeyError, TypeError):
                continue
            sel = r.get("runnerName", "")
            who = player if sep else sel
            out.append({"market": market if sep else name, "type": mtype,
                        "player": who, "key": _norm(who),
                        "selection": sel.replace(who, "").strip() if sep else "",
                        "side": (r.get("result") or {}).get("type"),
                        "line": r.get("handicap") or None, "price": round(price, 3)})
    return out


# ------------------------------------------------------------------ run

def candidates(st: dict) -> list[tuple]:
    """Fixtures worth asking about, soonest first."""
    try:
        mp = json.loads((ROOT / "market_prices.json").read_text())
    except (OSError, ValueError):
        return []
    held = (load_out().get("events") or {})
    out = []
    for fid, ev in (mp.get("events") or {}).items():
        bf_id = ev.get("bfEvent")
        if not bf_id:
            continue
        try:
            ko = datetime.fromisoformat(ev["start"].replace("Z", "+00:00")).timestamp()
        except (KeyError, ValueError):
            continue
        to_ko = ko - now()
        if to_ko <= 0 or to_ko > WINDOW_HOURS * 3600:
            continue
        last = (held.get(fid) or {}).get("fetchedAt", 0)
        fresh = (FRESH_CLOSE if to_ko < 3 * 3600 else FRESH_HOURS) * 3600
        if now() - last < fresh:
            continue
        out.append((ko, fid, bf_id, ev.get("betfair", "")))
    out.sort()
    return out


def load_out() -> dict:
    try:
        return json.loads(OUT.read_text())
    except (OSError, ValueError):
        return {"events": {}}


def names_match(page: dict, betfair_name: str) -> bool:
    import market_prices as mpx
    ev = next(iter(((page.get("attachments") or {}).get("events") or {}).values()), {})
    pp = ev.get("name", "")
    a = mpx._split_event(pp) or (pp, "")
    b = mpx._split_event(betfair_name) or (betfair_name, "")
    straight = min(mpx.sim(a[0], b[0]), mpx.sim(a[1], b[1]))
    crossed = min(mpx.sim(a[0], b[1]), mpx.sim(a[1], b[0]))
    return max(straight, crossed) >= 0.6


def run() -> int:
    LOCK.parent.mkdir(exist_ok=True)
    with open(LOCK, "w") as lockf:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("  paddypower: another run is going, skipping")
            return 0
        st = load_state()
        why = blocked(st)
        if why:
            print(f"  paddypower: not fetching, {why}")
            return 0
        todo = candidates(st)
        room = min(MAX_PER_RUN, MAX_PER_DAY - count_today(st))
        if room <= 0:
            print(f"  paddypower: daily cap of {MAX_PER_DAY} reached")
            return 0
        data = load_out()
        events = data.setdefault("events", {})
        got = 0
        for ko, fid, pp_id, bf_name in todo[:room]:
            wait_turn(st)
            try:
                page = fetch_event(pp_id)
            except BadId as exc:
                bump(st)
                if not st.get("idMapping"):
                    st["idMapping"] = False
                    save_state(st)
                    print(f"  paddypower: Betfair id {pp_id} unknown to Paddy Power ({exc}); stopping")
                else:
                    print(f"  paddypower: {bf_name} not on Paddy Power ({exc}); stopping this run")
                break
            except Refused as exc:
                bump(st)
                lockout(st, str(exc))
                break
            bump(st)
            if not names_match(page, bf_name):
                if not st.get("idMapping"):
                    st["idMapping"] = False
                    save_state(st)
                print(f"  paddypower: id {pp_id} is a different game on Paddy Power; stopping")
                break
            if st.get("idMapping") is not True:
                st["idMapping"] = True
                save_state(st)
            lines = player_lines(page)
            events[fid] = {"ppEvent": pp_id, "name": bf_name, "kickoff": ko,
                           "fetchedAt": now(), "lines": lines}
            got += 1
        # Drop games long finished.
        for fid in [f for f, e in events.items() if e.get("kickoff", 0) + KEEP_AFTER_KO * 3600 < now()]:
            del events[fid]
        data["updated"] = now()
        OUT.parent.mkdir(exist_ok=True)
        OUT.write_text(json.dumps(data, separators=(",", ":")))
        print(f"  paddypower: {got} game(s) fetched, {len(events)} held, "
              f"{count_today(load_state())}/{MAX_PER_DAY} today")
    return 0


def status() -> None:
    st = load_state()
    print("blocked:", blocked(st) or "no")
    print("today:", count_today(st), "of", MAX_PER_DAY)
    print("id mapping:", {True: "works", False: "does not work", None: "untested"}[st.get("idMapping")])
    for fid, e in (load_out().get("events") or {}).items():
        age = (now() - e.get("fetchedAt", 0)) / 3600
        print(f"  {e.get('name')}: {len(e.get('lines', []))} prices, {age:.1f}h old")
    print("would fetch next:", [c[3] for c in candidates(st)][:MAX_PER_RUN])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", help="one Paddy Power event id, printed only")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    if args.status:
        status()
        return 0
    if args.event:
        st = load_state()
        why = blocked(st)
        if why and "ids do not work" not in why:
            print("not fetching:", why)
            return 0
        wait_turn(st)
        try:
            page = fetch_event(args.event)
        except (Refused, BadId) as exc:
            bump(st)
            if isinstance(exc, Refused):
                lockout(st, str(exc))
            print("failed:", exc)
            return 1
        bump(st)
        lines = player_lines(page)
        ev = next(iter(page["attachments"].get("events", {}).values()), {})
        print(f"ok: {ev.get('name', '?')}  {len(page['attachments'].get('markets', {}))} markets, "
              f"{len(lines)} player prices")
        for l in sorted(lines, key=lambda x: (x["player"], x["market"], x["line"] or 0))[:40]:
            print(f"  {l['player']:24} {l['market']:28} {l['selection'] or l['side'] or '':16} "
                  f"{l['line'] or '':>6}  {l['price']}")
        return 0
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
