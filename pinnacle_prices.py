#!/usr/bin/env python3
"""Pinnacle's football prices, as fair chances, for checking the soft books.

    python pinnacle_prices.py              # the normal run (publish.sh can call it)
    python pinnacle_prices.py --probe      # one league, prints what came back
    python pinnacle_prices.py --leagues    # Pinnacle's soccer league names and ids
    python pinnacle_prices.py --status     # what is held, requests used today

Pinnacle is the sharpest book there is, and the one price that settles whether
a Paddy Power or Bet365 line is long. Betfair is thin on corners and cards,
which is exactly where Paddy Power's soft lines were on 23 Oct 2026.

Reads the guest API Pinnacle's own site uses (guest.api.arcadia.pinnacle.com),
logged out, with the site's public key kept in cache/pinnacle_key.json (out
of the repo). That is an undocumented feed and reading it is against
Pinnacle's terms, so it is built like paddypower_prices.py: per league, not per
game (about 2 requests a league), paced, capped, and any refusal locks it out
for a day. `touch .pinnacle_off` switches it off.

Writes reports/pinnacle.json keyed by the site's fixture id (matched the same
way bet365_prices.py matches Oddschecker's games):
    {"name", "kickoff", "pinId", "fetchedAt",
     "lines": [{"stat", "scope", "line", "over", "price", "p"}]}
stat is the site's name (Result, Goals, Corner kicks, Yellow cards); scope is
home | away | match; for Result, line is None and over is "home"|"draw"|"away".
p is the margin-free chance (the two or three prices of one market normalised).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "reports" / "pinnacle.json"
STATE = ROOT / "cache" / "pinnacle_state.json"
KEYFILE = ROOT / "cache" / "pinnacle_key.json"
OFF = ROOT / ".pinnacle_off"

BASE = "https://guest.api.arcadia.pinnacle.com/0.1"
SOCCER = 29
MIN_GAP, JITTER = 4.0, 4.0     # seconds between requests
MAX_PER_DAY = 150
MAX_RELATED = 30               # corners/bookings lookups per run
WINDOW_HOURS = 72
LOCKOUT_HOURS = 24
FRESH_HOURS = 1.5              # a league is not refetched inside this
SIDE_HOURS = 6                 # a game's corners/bookings lookup is reused inside this

# The site's competitions -> Pinnacle league name. Premier League (1980) and
# La Liga (2196) confirmed from the site on 23 Oct 2026; the rest are matched
# by name from /sports/29/leagues, so check --leagues if one goes missing.
LEAGUES = [
    "England - Premier League", "England - Championship", "Spain - La Liga",
    "Italy - Serie A", "Germany - Bundesliga", "France - Ligue 1",
    "USA - Major League Soccer", "Brazil - Serie A",
    "UEFA - Champions League", "UEFA - Europa League", "UEFA - Conference League",
    "England - EFL Cup",
]
KNOWN_IDS = {"England - Premier League": 1980, "Spain - La Liga": 2196}


class Refused(Exception):
    """Pinnacle said no (or the connection failed): lock out for a day."""
    pass


class Capped(Exception):
    """Our own daily request cap. Not a refusal: stop this run, no lockout.
    (Until 28 Oct 2026 this raised Refused, so reaching the cap at 17:00 locked
    the feed out until 17:00 the next day and that day's runs fetched nothing.)"""
    pass


# ------------------------------------------------------------ plumbing

def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(st))


def today() -> str:
    return time.strftime("%Y-%m-%d")


def headers() -> dict:
    try:
        k = json.loads(KEYFILE.read_text())
    except (OSError, ValueError):
        raise SystemExit(f"no key: put the site's x-api-key in {KEYFILE}")
    h = {"Accept": "application/json", "Origin": "https://www.pinnacle.com",
         "Referer": "https://www.pinnacle.com/",
         "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
         "X-API-Key": k["x-api-key"]}
    if k.get("x-device-uuid"):
        h["X-Device-UUID"] = k["x-device-uuid"]
    return h


def get(path: str, st: dict):
    """One paced, counted GET. Any refusal locks the feed out for a day."""
    used = st.setdefault("count", {}).get(today(), 0)
    if used >= MAX_PER_DAY:
        raise Capped(f"daily cap of {MAX_PER_DAY} reached")
    wait = st.get("last", 0) + MIN_GAP + random.uniform(0, JITTER) - time.time()
    if wait > 0:
        time.sleep(wait)
    st["count"] = {today(): used + 1}
    st["last"] = time.time()
    try:
        r = requests.get(BASE + path, headers=HDR, timeout=20)
    except requests.RequestException as e:
        raise Refused(f"{type(e).__name__} on {path}")
    if r.status_code != 200:
        raise Refused(f"HTTP {r.status_code} on {path}")
    try:
        return r.json()
    except ValueError:
        raise Refused(f"non-JSON reply on {path}")


def lockout(st: dict, why: str) -> None:
    st["lockedUntil"] = time.time() + LOCKOUT_HOURS * 3600
    st["lockedWhy"] = why
    save_state(st)
    print(f"  pinnacle: refused ({why}); locked out for {LOCKOUT_HOURS}h")


def decimal(american) -> float | None:
    try:
        a = float(american)
    except (TypeError, ValueError):
        return None
    if a >= 100:
        return round(1 + a / 100, 4)
    if a <= -100:
        return round(1 + 100 / -a, 4)
    return None


# ------------------------------------------------------------ parsing

def kind_of(matchup: dict) -> str | None:
    """'Result' side for the main game; corners and bookings come as their
    own related matchups, told apart by 'units' (seen as 'Regular' on the main
    game) or by the league or participant names carrying the word."""
    blob = " ".join(str(x) for x in (matchup.get("units"), (matchup.get("league") or {}).get("name"),
                                     *[p.get("name", "") for p in matchup.get("participants", [])])).lower()
    if "corner" in blob:
        return "Corner kicks"
    if "booking" in blob or "card" in blob:
        return "Yellow cards"
    if (matchup.get("units") or "Regular") == "Regular" and matchup.get("type") == "matchup":
        return "Goals"
    return None


def lines_of(market: dict, stat: str) -> list[dict]:
    """A straight market -> rows with margin-free chances. Full time only."""
    if market.get("period") != 0 or market.get("status", "open") != "open":
        return []
    t = market.get("type")
    prices = market.get("prices") or []
    dec = [(p, decimal(p.get("price"))) for p in prices]
    dec = [(p, d) for p, d in dec if d]
    if len(dec) < 2:
        return []
    book = sum(1 / d for _, d in dec)
    out = []
    for p, d in dec:
        des = p.get("designation")
        row = {"stat": stat, "price": round(d, 3), "p": round((1 / d) / book, 4)}
        if t == "moneyline" and stat == "Goals":
            out.append(dict(row, stat="Result", scope="match", line=None, over=des))
        elif t == "total" and des in ("over", "under"):
            out.append(dict(row, scope="match", line=p.get("points"), over=des == "over"))
        elif t == "team_total" and des in ("over", "under"):
            side = market.get("side")
            if side in ("home", "away"):
                out.append(dict(row, scope=side, line=p.get("points"), over=des == "over"))
    return [r for r in out if r["line"] is None or float(r["line"]) % 1 == 0.5]


def pin_events() -> dict:
    """The site's fixtures to match against (bet365_prices.load_events)."""
    import bet365_prices
    return bet365_prices.load_events()


def match(m: dict, events: dict) -> str | None:
    import bet365_prices
    from datetime import datetime
    home = next((p["name"] for p in m.get("participants", []) if p.get("alignment") == "home"), None)
    away = next((p["name"] for p in m.get("participants", []) if p.get("alignment") == "away"), None)
    if not home or not away:
        return None
    ko = datetime.fromisoformat(m["startTime"].replace("Z", "+00:00")).timestamp()
    return bet365_prices.match_fixture(f"{home} v {away}", ko, events)


# ------------------------------------------------------------ run

def league_ids(st: dict) -> dict:
    """Name -> id, refreshed once a day from Pinnacle's soccer league list."""
    if st.get("leaguesOn") == today() and st.get("leagues"):
        return st["leagues"]
    got = get(f"/sports/{SOCCER}/leagues?all=false", st)
    names = {l.get("name"): l.get("id") for l in got if isinstance(l, dict)}
    ids = {n: names.get(n) or KNOWN_IDS.get(n) for n in LEAGUES}
    missing = [n for n, i in ids.items() if not i]
    if missing:
        print(f"  pinnacle: no league called {missing}; see --leagues")
    st["leagues"] = {n: i for n, i in ids.items() if i}
    st["leaguesOn"] = today()
    return st["leagues"]


def run(probe: bool = False) -> int:
    if OFF.exists():
        print("  pinnacle: switched off (.pinnacle_off)")
        return 0
    st = load_state()
    if st.get("lockedWhy", "").startswith("daily cap"):
        # left behind by the old behaviour, where our own cap locked us out
        st.pop("lockedUntil", None)
        st.pop("lockedWhy", None)
    if st.get("lockedUntil", 0) > time.time():
        print(f"  pinnacle: locked out ({st.get('lockedWhy')})")
        return 0
    try:
        out = json.loads(OUT.read_text())
    except (OSError, ValueError):
        out = {"events": {}}
    held = out.setdefault("events", {})
    now = time.time()
    for fid in [k for k, e in held.items() if e.get("kickoff", 0) < now]:
        held.pop(fid)
    events = pin_events()
    got = related = 0
    try:
        ids = league_ids(st)
        if probe:
            ids = {k: v for k, v in ids.items() if v == 1980}
        fresh = st.setdefault("leagueAt", {})
        for name, lid in ids.items():
            if not probe and now - fresh.get(name, 0) < FRESH_HOURS * 3600:
                continue
            ms = get(f"/leagues/{lid}/matchups", st)
            mk = get(f"/leagues/{lid}/markets/straight", st)
            by_m: dict = {}
            for m in mk if isinstance(mk, list) else []:
                by_m.setdefault(m.get("matchupId"), []).append(m)
            fresh[name] = time.time()
            mains = [m for m in ms if m.get("type") == "matchup" and not m.get("parentId")]
            # Corners and bookings come back in the same league call, as
            # their own matchups (units "Corners" / "Bookings") hanging off the
            # game by parentId, with their markets in the same straight list
            # (probe, 23 Oct 2026). So no per-game call is needed.
            kids: dict = {}
            for c in ms:
                if c.get("parentId") and c.get("type") == "matchup":
                    stat = kind_of(c)
                    if stat in ("Corner kicks", "Yellow cards"):
                        kids.setdefault(c["parentId"], []).append((stat, c["id"]))
            if probe:
                print(f"\n== {name}: {len(ms)} matchups, {len(mk)} markets")
                print("  units seen:", sorted({str(m.get('units')) for m in ms}))
                print("  market types:", sorted({str(x.get('type')) for x in mk}))
                tt = next((x for x in mk if x.get("type") == "team_total"), None)
                print("  a team_total market:", json.dumps(tt)[:400] if tt else None)
            for m in mains:
                from datetime import datetime
                ko = datetime.fromisoformat(m["startTime"].replace("Z", "+00:00")).timestamp()
                if not now < ko < now + WINDOW_HOURS * 3600:
                    continue
                fid = match(m, events)
                if not fid:
                    continue
                rows = [r for x in by_m.get(m["id"], []) for r in lines_of(x, "Goals")]
                before = held.get(fid) or {}
                held[fid] = {"name": f"{m['participants'][0]['name']} v {m['participants'][1]['name']}",
                             "kickoff": ko, "pinId": m["id"], "league": name,
                             "fetchedAt": time.time(), "lines": rows}
                for stat, cid in kids.get(m["id"], []):
                    held[fid]["lines"] += [x for mm in by_m.get(cid, []) for x in lines_of(mm, stat)]
                got += 1
                # Fallback only: a game whose side markets were not in the
                # league list gets one related call (capped). The answer is
                # kept for SIDE_HOURS, empty or not, so the same game is not
                # looked up on every run: those repeat lookups were what used
                # the whole day's cap by late afternoon (27 Oct 2026).
                if not kids.get(m["id"]) and time.time() - before.get("sideAt", 0) < SIDE_HOURS * 3600:
                    held[fid]["lines"] += [x for x in before.get("lines", []) if x["stat"] in ("Corner kicks", "Yellow cards")]
                    held[fid]["sideAt"] = before["sideAt"]
                elif (not kids.get(m["id"]) and related < MAX_RELATED and not probe):
                    held[fid]["sideAt"] = time.time()
                    rel = get(f"/matchups/{m['id']}/related", st)
                    related += 1
                    if probe:
                        print(f"\n  related for {held[fid]['name']}:",
                              [(r.get("id"), r.get("units"), r.get("type")) for r in rel][:10])
                    for r in rel if isinstance(rel, list) else []:
                        stat = kind_of(r)
                        if stat in ("Corner kicks", "Yellow cards") and r.get("id") != m["id"]:
                            rm = get(f"/matchups/{r['id']}/markets/straight", st)
                            held[fid]["lines"] += [x for mm in rm for x in lines_of(mm, stat)]
                            if probe:
                                print(f"  {stat}: {len(rm)} markets ->",
                                      [x for mm in rm for x in lines_of(mm, stat)][:4])
    except Capped as e:
        print(f"  pinnacle: stopped early ({e}); resumes tomorrow, no lockout")
    except Refused as e:
        lockout(st, str(e))
    save_state(st)
    out["updated"] = time.time()
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(f"  pinnacle: {got} game(s) priced, {related} with side markets looked up, "
          f"{len(held)} held, {st.get('count', {}).get(today(), 0)}/{MAX_PER_DAY} today")
    return 0


def leagues() -> int:
    st = load_state()
    got = get(f"/sports/{SOCCER}/leagues?all=false", st)
    save_state(st)
    for l in sorted(got, key=lambda l: l.get("name", "")):
        print(f"  {l.get('id'):>6}  {l.get('name')}")
    return 0


def status() -> None:
    st = load_state()
    try:
        held = json.loads(OUT.read_text()).get("events", {})
    except (OSError, ValueError):
        held = {}
    for fid, e in sorted(held.items(), key=lambda kv: kv[1].get("kickoff", 0)):
        kinds = sorted({l["stat"] for l in e["lines"]})
        print(f"  {e['name']:<40} {time.strftime('%a %H:%M', time.localtime(e['kickoff']))}  "
              f"{len(e['lines'])} lines {kinds}")
    print(f"  requests today: {st.get('count', {}).get(today(), 0)}/{MAX_PER_DAY}",
          f"locked: {st.get('lockedWhy')}" if st.get("lockedUntil", 0) > time.time() else "")


HDR: dict = {}


def main() -> int:
    global HDR
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--probe", action="store_true")
    p.add_argument("--leagues", action="store_true")
    p.add_argument("--status", action="store_true")
    a = p.parse_args()
    if a.status:
        status()
        return 0
    HDR = headers()
    if a.leagues:
        return leagues()
    return run(probe=a.probe)


if __name__ == "__main__":
    sys.exit(main())
