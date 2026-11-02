#!/usr/bin/env python3
"""Sky Bet's NBA player prices, read from its own game pages.

    python skybet_prices.py              # tonight's NBA games (the normal run)
    python skybet_prices.py --value      # Sky Bet lines against Pinnacle's fair price
    python skybet_prices.py --probe ID   # one game (Sky / Betfair event id), saved raw, printed
    python skybet_prices.py --status     # what is held, requests used today

Why (2 Nov 2026): Paddy Power's daily cap (paddypower_prices.py) was spent by
the evening, so most NBA lines carried morning prices against current
Pinnacle ones. Sky Bet is the same company's platform, its event ids are
Betfair's (Thunder @ Cavaliers was 36262178 at both), and its game pages
carry the markets and their prices in the page itself
(window.__TBD_PRELOADED_CATALOG__: SportsbookMarket and
SportsbookRunnerLiveData), with the same market types Paddy Power uses
(TO_SCORE_15+_POINTS and so on). So a page reads straight into
paddypower_prices' own parser, and Sky Bet's prices sit beside Paddy's and
Pinnacle's without spending Paddy Power's cap.

Built like paddypower_prices.py, and deliberately no more than that: plain
requests, never through FlareSolverr or anything else that gets round a
site's protection. Paced (MIN_GAP to MIN_GAP + JITTER seconds), capped per
run and per day, a game not refetched inside FRESH_HOURS (FRESH_CLOSE in the
last 3 hours), any refusal or a page that is not the game locks it out for
LOCKOUT_HOURS, and `touch .skybet_off` switches it off.

Each tab of a game page (points, rebounds, assists, threes, combos) carries
the grid it shows first: 15+/20+/25+ points, 6+/8+/10+ rebounds, 4+/6+/8+
assists, 2+/3+/4+ threes (checked on Thunder @ Cavaliers, 2 Nov: 119 lines).
Other grids (5+/10+, 30+ to 50+ points) load only when opened and are not
read. as_page() also reads the site's own card replies, which carry the same
markets in a different layout.

Writes reports/skybet.json, the same shape as reports/paddypower.json:
    {"events": {fid: {"skEvent", "name", "kickoff", "fetchedAt", "lines": [...]}}, "updated"}
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "reports" / "skybet.json"
STATE = ROOT / "cache" / "skybet_state.json"
RAW = ROOT / "cache" / "skybet"
OFF = ROOT / ".skybet_off"

SITE = "https://skybet.com/"
TABS = ("points", "rebounds", "assists", "threes", "combos")
MIN_GAP, JITTER = 8.0, 8.0
MAX_PER_RUN = 40          # requests (a game is up to len(TABS))
MAX_PER_DAY = 120
WINDOW_HOURS = 30
FRESH_HOURS, FRESH_CLOSE = 3.0, 0.75
LOCKOUT_HOURS = 24
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"),
}


class Refused(Exception):
    pass


# ------------------------------------------------------------ state

def today() -> str:
    return time.strftime("%Y-%m-%d")


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(st))


def used(st: dict) -> int:
    return st.get("count", 0) if st.get("day") == today() else 0


def bump(st: dict) -> None:
    st["count"], st["day"], st["last"] = used(st) + 1, today(), time.time()
    save_state(st)


def wait_turn(st: dict) -> None:
    gap = MIN_GAP + random.uniform(0, JITTER)
    since = time.time() - st.get("last", 0)
    if since < gap:
        time.sleep(gap - since)


def lockout(st: dict, why: str) -> None:
    """Stop for LOCKOUT_HOURS; a second refusal switches the fetcher off for good."""
    st["lockedUntil"], st["lockedWhy"] = time.time() + LOCKOUT_HOURS * 3600, why
    st["refusals"] = st.get("refusals", 0) + 1
    save_state(st)
    if st["refusals"] >= 2:
        OFF.write_text(f"Sky Bet refused twice ({why}); delete this file to try again.\n")
        print(f"  skybet: refused again ({why}); switched off (.skybet_off)")
    else:
        print(f"  skybet: refused ({why}); locked out for {LOCKOUT_HOURS}h")


# ------------------------------------------------------------ pages

def slug(name: str) -> str:
    """'Oklahoma City Thunder @ Cleveland Cavaliers' -> 'oklahoma-city-thunder-cleveland-cavaliers'."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace(" @ ", " ")).strip("-")


def page_url(event_id, name: str, tab: str) -> str:
    return f"{SITE}basketball/nba/{slug(name)}/e-{event_id}?tab={tab}"


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise Refused(f"HTTP {exc.code}")
    except Exception as exc:  # noqa: BLE001
        raise Refused(type(exc).__name__)


def catalog(html: str) -> dict:
    """The page's preloaded catalogue (markets, runners, prices), or {}."""
    key = "window.__TBD_PRELOADED_CATALOG__ ="
    a = html.find(key)
    if a < 0:
        return {}
    a += len(key)
    while a < len(html) and html[a] in " \n\r\t":
        a += 1
    try:
        return json.JSONDecoder().raw_decode(html, a)[0].get("data") or {}
    except ValueError:
        return {}


def _mid(urn_or_id) -> str:
    """'ppb:sbkMarket:930.394327825' or '930.394327825' -> '930.394327825'."""
    return str(urn_or_id or "").rsplit(":", 1)[-1]


def as_page(data) -> dict:
    """Sky Bet's markets in the shape paddypower_prices' parsers read.

    Reads either the page's preloaded catalogue (SportsbookMarket with its
    runners' names, SportsbookRunnerLiveData with their prices) or the
    site's own card replies (the same markets, with names on GridRunner
    entries and prices under liveData), wherever they sit in the JSON."""
    markets, names, prices = {}, {}, {}

    def walk(o):
        if isinstance(o, list):
            for v in o:
                walk(v)
            return
        if not isinstance(o, dict):
            return
        t = o.get("__typename")
        if o.get("marketType") and (o.get("marketId") or o.get("urn")):
            mid = _mid(o.get("marketId") or o.get("urn"))
            m = markets.setdefault(mid, {"marketId": mid, "marketType": o["marketType"], "marketName": o.get("name", "")})
            for r in o.get("runners") or []:
                if isinstance(r, dict) and r.get("selectionId") and r.get("name"):
                    names[(mid, r["selectionId"])] = r["name"]
                    m.setdefault("_hcap", {})[r["selectionId"]] = r.get("handicap") or 0
        if t == "SportsbookRunnerLiveData" or ("selectionId" in o and ("odds" in o or "trueOdds" in o)):
            mid = _mid(o.get("marketURN") or o.get("market") or (o.get("runnerURN") or "").split("/")[0])
            odds = o.get("trueOdds") or o.get("odds") or {}
            if mid and odds.get("decimal"):
                prices[(mid, o["selectionId"])] = (odds["decimal"], o.get("runnerStatus") or o.get("status") or "ACTIVE")
        dn, run = o.get("displayName"), o.get("runner")
        if isinstance(dn, dict) and isinstance(run, dict) and run.get("selectionId") and dn.get("name"):
            names[(_mid(run.get("marketURN")), run["selectionId"])] = dn["name"]
        for v in o.values():
            walk(v)

    walk(data)
    for (mid, sid), (price, status) in prices.items():
        m, who = markets.get(mid), names.get((mid, sid))
        if not m or not who:
            continue
        m.setdefault("runners", []).append({
            "selectionId": sid, "runnerName": who, "handicap": (m.get("_hcap") or {}).get(sid, 0),
            "runnerStatus": status,
            "winRunnerOdds": {"trueOdds": {"decimalOdds": {"decimalOdds": price}}}})
    for m in markets.values():
        m.pop("_hcap", None)
        m.setdefault("runners", [])
    return {"attachments": {"markets": markets}}


def lines_of(html: str) -> list[dict]:
    import paddypower_prices as pp
    return pp.player_lines(as_page(catalog(html)))


def event_name(data: dict) -> str:
    ev = data.get("SportsEvent") or []
    return (ev[0] if ev else {}).get("name", "")


# ------------------------------------------------------------ run

def candidates() -> list[tuple]:
    """(kickoff, fid, event id, 'Away @ Home') for NBA games inside the window, soonest first."""
    try:
        mp = json.loads((ROOT / "market_prices.json").read_text())
    except (OSError, ValueError):
        return []
    held = (load_out().get("events") or {})
    now, out = time.time(), []
    for fid, ev in (mp.get("events") or {}).items():
        name, eid = ev.get("betfair") or "", ev.get("bfEvent")
        if " @ " not in name or not eid:
            continue
        try:
            ko = datetime.fromisoformat(ev["start"].replace("Z", "+00:00")).timestamp()
        except (KeyError, ValueError):
            continue
        if not 0 < ko - now < WINDOW_HOURS * 3600:
            continue
        fresh = (FRESH_CLOSE if ko - now < 3 * 3600 else FRESH_HOURS) * 3600
        if now - (held.get(fid) or {}).get("fetchedAt", 0) < fresh:
            continue
        out.append((ko, fid, eid, name))
    return sorted(out)


def load_out() -> dict:
    try:
        return json.loads(OUT.read_text())
    except (OSError, ValueError):
        return {"events": {}}


def run() -> int:
    if OFF.exists():
        print("  skybet: switched off (.skybet_off)")
        return 0
    st = load_state()
    if st.get("lockedUntil", 0) > time.time():
        print(f"  skybet: locked out ({st.get('lockedWhy')})")
        return 0
    out = load_out()
    held = out.setdefault("events", {})
    for k in [k for k, e in held.items() if (e.get("kickoff") or 0) < time.time() - 6 * 3600]:
        held.pop(k)
    budget = min(MAX_PER_RUN, MAX_PER_DAY - used(st))
    games = 0
    for ko, fid, eid, name in candidates():
        if budget < len(TABS):
            break
        lines, ok = [], True
        for tab in TABS:
            wait_turn(st)
            try:
                html = fetch(page_url(eid, name, tab))
            except Refused as exc:
                bump(st)
                lockout(st, str(exc))
                ok = False
                break
            bump(st)
            budget -= 1
            data = catalog(html)
            if not data:
                lockout(st, "a page with no game data (a challenge page?)")
                ok = False
                break
            if event_name(data) and event_name(data).split(" @ ")[-1] != name.split(" @ ")[-1]:
                print(f"  skybet: {eid} is {event_name(data)!r}, not {name!r}; skipped")
                break
            lines += lines_of(html)
        if not ok:
            break
        seen, keep = set(), []
        for l in lines:
            k = (l["key"], l["market"], l["side"], l["line"])
            if k not in seen:
                seen.add(k)
                keep.append(l)
        held[fid] = {"skEvent": eid, "name": name, "kickoff": ko, "fetchedAt": time.time(), "lines": keep}
        games += 1
    out["updated"] = time.time()
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(f"  skybet: {games} game(s) fetched, {len(held)} held, {used(st)}/{MAX_PER_DAY} requests today")
    return 0


# ------------------------------------------------------------ value against Pinnacle

def value(min_edge: float = 0.03) -> int:
    """Sky Bet lines over Pinnacle's margin-free chance at the same line."""
    import pinnacle_props
    import pplog
    rows = []
    for fid, e in (load_out().get("events") or {}).items():
        if (e.get("kickoff") or 0) < time.time():
            continue
        for l in e.get("lines", []):
            got = pplog.read_line(l)
            if not got:
                continue
            stat, line, over, label = got
            label = f"{line + 0.5:g}+" if l.get("type", "")[:1].isdigit() or "+" in l.get("type", "") else label
            sh = pinnacle_props.sharp_for("basketball", l["player"], stat, line, over, e["kickoff"], fid)
            if not sh or not sh.get("same"):
                continue
            edge = l["price"] * sh["p"] - 1
            if edge >= min_edge:
                rows.append((edge, e["name"], l["player"], stat, label, l["price"], 1 / sh["p"]))
    rows.sort(reverse=True)
    if not rows:
        print("No Sky Bet line is 3%+ over Pinnacle's fair price at the same line.")
    for edge, game, who, stat, label, price, fair in rows[:30]:
        print(f"  {edge:+6.1%}  {who:24} {label:10} {stat.lower():24} Sky {price:<6} fair {fair:.2f}  ({game})")
    return 0


def probe(eid: str) -> int:
    try:
        mp = json.loads((ROOT / "market_prices.json").read_text()).get("events") or {}
    except (OSError, ValueError):
        mp = {}
    name = next((e.get("betfair") for e in mp.values() if str(e.get("bfEvent")) == str(eid)), None)
    if not name:
        print(f"no game with event id {eid} in market_prices.json")
        return 1
    st = load_state()
    if OFF.exists() or st.get("lockedUntil", 0) > time.time():
        print("  skybet: switched off or locked out; no request made")
        return 1
    RAW.mkdir(parents=True, exist_ok=True)
    url = page_url(eid, name, "points")
    print("GET", url)
    try:
        html = fetch(url)
    except Refused as exc:
        print("refused:", exc)
        return 1
    bump(st)
    (RAW / f"{eid}-points.html").write_text(html)
    data = catalog(html)
    print(f"  {len(html)} bytes, catalogue keys: {sorted(data)[:20]}")
    page = as_page(data)
    for m in page["attachments"]["markets"].values():
        print(f"  {m['marketType']:40} {m['marketName'][:40]:40} {len(m['runners'])} runners")
    ls = lines_of(html)
    print(f"  {len(ls)} player lines read, e.g. {ls[:3]}")
    return 0


def from_saved() -> int:
    """Read pages saved in cache/skybet into reports/skybet.json: no requests.

    Takes the game pages --probe saves (ID-points.html), pages you save from
    your own browser, and the site's card replies copied from the browser's
    network tab (any .json or .txt; the game is read from inside it)."""
    try:
        mp = json.loads((ROOT / "market_prices.json").read_text()).get("events") or {}
    except (OSError, ValueError):
        mp = {}
    out = load_out()
    held = out.setdefault("events", {})
    for f in sorted(list(RAW.glob("*.html")) + list(RAW.glob("*.json")) + list(RAW.glob("*.txt"))):
        text = f.read_text()
        m = re.search(r"ppb:event:(\d+)", text)
        eid = f.stem.split("-")[0] if f.stem.split("-")[0].isdigit() else (m.group(1) if m else "")
        fid, ev = next(((k, e) for k, e in mp.items() if str(e.get("bfEvent")) == eid), (None, None))
        if not fid:
            continue
        try:
            ko = datetime.fromisoformat(ev["start"].replace("Z", "+00:00")).timestamp()
        except (KeyError, ValueError):
            continue
        prev = held.get(fid) or {}
        lines = {(l["key"], l["market"], l["side"], l["line"]): l for l in prev.get("lines", [])}
        if f.suffix == ".html":
            got = lines_of(text)
        else:
            import paddypower_prices as pp
            try:
                got = pp.player_lines(as_page(json.loads(text)))
            except ValueError:
                got = []
        for l in got:
            lines[(l["key"], l["market"], l["side"], l["line"])] = l
        held[fid] = {"skEvent": eid, "name": ev.get("betfair"), "kickoff": ko,
                     "fetchedAt": f.stat().st_mtime, "lines": list(lines.values())}
        print(f"  {ev.get('betfair')}: {len(lines)} lines from {f.name}")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    return 0


def status() -> None:
    st = load_state()
    for fid, e in sorted((load_out().get("events") or {}).items(), key=lambda kv: kv[1].get("kickoff", 0)):
        print(f"  {e['name']:<44} {time.strftime('%a %H:%M', time.localtime(e['kickoff']))}  {len(e['lines'])} lines")
    print(f"  requests today: {used(st)}/{MAX_PER_DAY}",
          f"locked: {st.get('lockedWhy')}" if st.get("lockedUntil", 0) > time.time() else "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--value", action="store_true")
    ap.add_argument("--probe", metavar="EVENT_ID")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--saved", action="store_true", help="read pages already saved by --probe; no requests")
    a = ap.parse_args()
    if a.status:
        status()
        return 0
    if a.saved:
        return from_saved()
    if a.probe:
        return probe(a.probe)
    if a.value:
        return value()
    return run()


if __name__ == "__main__":
    sys.exit(main())
