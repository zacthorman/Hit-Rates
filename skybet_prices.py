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

Pages load through FlareSolverr (the same container update.py keeps healthy
for SofaScore and Oddschecker), as one browser session per run, so cookies
and the site's own scripts carry across pages the way one visitor's tab
would. The run opens the NBA hub first, lands on a game's points tab, then
clicks through the other tabs in a random order, with browsing-speed gaps
(TAB_GAP between tabs, GAME_GAP between games, now and then a longer
BREAK). SKYBET_FLARESOLVERR=0 goes back to plain requests; if FlareSolverr
cannot be reached the run falls back to plain requests and says so.

Limits, so the IP is never pushed into a ban: MAX_PER_RUN, MAX_PER_HOUR
(rolling, shared by runs and --probe) and MAX_PER_DAY, one run at a time
(cache/skybet.lock), a game not refetched inside FRESH_HOURS (FRESH_CLOSE in
the last 3 hours). A 403 or 429 switches it off (.skybet_off) until that
file is deleted by hand; any other refusal, or a page that is not the game,
locks it out for LOCKOUT_HOURS, and a second one switches it off.
`touch .skybet_off` switches it off too.

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
import os
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
HUB = SITE + "basketball/nba"
TABS = ("points", "rebounds", "assists", "threes", "combos")
MIN_GAP, JITTER = 12.0, 8.0     # floor between any two requests, kept across runs
TAB_GAP = (6.0, 18.0)           # reading one tab before clicking the next
GAME_GAP = (25.0, 75.0)         # going back to the list and picking another game
BREAK, BREAK_CHANCE = (90.0, 240.0), 0.12   # now and then, a longer look away
_flare = os.getenv("SKYBET_FLARESOLVERR", os.getenv("FLARESOLVERR_URL", "http://localhost:8191/v1")).strip()
FLARE_URL = "" if _flare.lower() in ("0", "false", "no", "off") else _flare
CHALLENGE_MARKERS = ("Just a moment", "challenge-platform", "cf-chl", "Attention Required",
                     "Access Denied", "px-captcha")
# IP-ban guard (2 Nov 2026). Sky Bet answered a plain request with 403 seconds
# after serving the page, so the caps stay well under what one person browsing
# would do, and a hard refusal (403/429) stops everything until Zac says so.
MAX_PER_RUN = 26          # the NBA hub + 5 games of len(TABS) tabs
MAX_PER_HOUR = 30         # rolling 60 minutes, across every run and --probe
MAX_PER_DAY = 100         # 15 games x 5 tabs + a hub per run fits
HARD_REFUSALS = ("HTTP 403", "HTTP 429")
HARD_CEILING = 80        # --max can lift the run and hour caps this far, never the day cap
LOCK = ROOT / "cache" / "skybet.lock"
LOCK_STALE = 45 * 60      # a lock older than this is a crashed run
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


def hour_used(st: dict) -> int:
    return sum(1 for t in st.get("times", []) if t > time.time() - 3600)


def left(st: dict) -> int:
    """Requests still allowed now: the tighter of the hourly and daily caps."""
    return max(0, min(MAX_PER_HOUR - hour_used(st), MAX_PER_DAY - used(st)))


def set_max(n: int) -> int:
    """One-off: lift the run and hour caps to n (at most HARD_CEILING) for this process."""
    global MAX_PER_RUN, MAX_PER_HOUR
    n = max(1, min(int(n), HARD_CEILING))
    MAX_PER_RUN = MAX_PER_HOUR = n
    return n


def bump(st: dict) -> None:
    now = time.time()
    st["count"], st["day"], st["last"] = used(st) + 1, today(), now
    st["times"] = [t for t in st.get("times", []) if t > now - 3600] + [now]
    save_state(st)


def blocked(st: dict) -> str:
    """Why no request may be made right now, or ''."""
    if OFF.exists():
        return "switched off (.skybet_off)"
    if st.get("lockedUntil", 0) > time.time():
        return f"locked out ({st.get('lockedWhy')})"
    if left(st) <= 0:
        return f"cap reached ({hour_used(st)}/{MAX_PER_HOUR} this hour, {used(st)}/{MAX_PER_DAY} today)"
    return ""


def take_lock() -> bool:
    """One run at a time, so two runs (publish.sh and a manual one) never double the rate."""
    LOCK.parent.mkdir(exist_ok=True)
    try:
        if time.time() - LOCK.stat().st_mtime > LOCK_STALE:
            LOCK.unlink()
    except OSError:
        pass
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    return True


def drop_lock() -> None:
    try:
        LOCK.unlink()
    except OSError:
        pass


def human_gap(kind: str) -> float:
    """Seconds a person might take before the next page: 'tab' or 'game'."""
    lo, hi = TAB_GAP if kind == "tab" else GAME_GAP
    gap = random.triangular(lo, hi, lo + (hi - lo) * 0.35)   # mostly quick, sometimes slow
    if random.random() < BREAK_CHANCE:
        gap += random.uniform(*BREAK)
    return gap


def wait_turn(st: dict, kind: str = "tab") -> None:
    """Sleep for a browsing-speed gap, never less than the cross-run floor."""
    floor = MIN_GAP + random.uniform(0, JITTER)
    since = time.time() - st.get("last", 0)
    wait = max(floor - since, human_gap(kind) if st.get("last") else 0)
    if wait > 0:
        time.sleep(wait)


def tab_order() -> list[str]:
    """Points first (the tab a game page opens on), the rest in a random order."""
    rest = [t for t in TABS if t != "points"]
    random.shuffle(rest)
    return (["points"] if "points" in TABS else []) + rest


def lockout(st: dict, why: str) -> None:
    """Stop for LOCKOUT_HOURS. A 403 or 429, or a second refusal of any kind,
    switches the fetcher off until .skybet_off is deleted by hand: pushing on
    after a site has said no is what turns a block into an IP ban."""
    st["lockedUntil"], st["lockedWhy"] = time.time() + LOCKOUT_HOURS * 3600, why
    st["refusals"] = st.get("refusals", 0) + 1
    save_state(st)
    if any(why.startswith(h) for h in HARD_REFUSALS):
        OFF.write_text(f"Sky Bet refused ({why}) at {time.strftime('%d %b %H:%M')}; "
                       "wait a day or more, then delete this file to try again.\n")
        print(f"  skybet: refused ({why}); switched off (.skybet_off) until you delete it")
    elif st["refusals"] >= 2:
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


def fetch_plain(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise Refused(f"HTTP {exc.code}")
    except Exception as exc:  # noqa: BLE001
        raise Refused(type(exc).__name__)


def _flare_call(payload: dict, timeout: float = 90) -> dict:
    req = urllib.request.Request(FLARE_URL, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


class Browser:
    """One FlareSolverr browser session for the run, or plain requests.

    Use as a context manager: the session is destroyed on the way out, so a
    crashed run does not leave a Chrome open inside the container."""

    def __init__(self, flare_url: str = None):
        self.url = FLARE_URL if flare_url is None else flare_url
        self.session = None

    def __enter__(self):
        if self.url:
            try:
                made = _flare_call({"cmd": "sessions.create"}, 60)
                if made.get("status") == "ok" and made.get("session"):
                    self.session = made["session"]
            except Exception as exc:  # noqa: BLE001
                print(f"  skybet: FlareSolverr not reachable ({type(exc).__name__}); using plain requests")
        return self

    def __exit__(self, *exc):
        if self.session:
            try:
                _flare_call({"cmd": "sessions.destroy", "session": self.session}, 20)
            except Exception:  # noqa: BLE001
                pass
            self.session = None
        return False

    @property
    def mode(self) -> str:
        return "FlareSolverr" if self.session else "plain"

    def get(self, url: str) -> str:
        if not self.session:
            return fetch_plain(url)
        try:
            got = _flare_call({"cmd": "request.get", "url": url, "session": self.session,
                               "maxTimeout": 60000})
        except Exception as exc:  # noqa: BLE001
            raise Refused(f"FlareSolverr {type(exc).__name__}")
        if got.get("status") != "ok":
            raise Refused(f"FlareSolverr: {str(got.get('message'))[:80]}")
        sol = got.get("solution") or {}
        code, body = int(sol.get("status") or 0), sol.get("response") or ""
        if code >= 400:
            raise Refused(f"HTTP {code}")
        if any(m in body[:5000] for m in CHALLENGE_MARKERS) and "__TBD_PRELOADED_CATALOG__" not in body:
            raise Refused("challenge page")
        return body


def fetch(url: str) -> str:
    """One page, outside a run (used by --probe)."""
    with Browser() as b:
        return b.get(url)


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
        # NBA only: NFL games are "Away @ Home" too (Bears @ Seahawks, 2 Nov), and a
        # basketball/nba URL for one 404s, which would lock the fetcher out.
        if ev.get("sport") != "basketball" or " @ " not in name or not eid:
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
        out.append((fid in held, ko, fid, eid, name))
    # Games never fetched come before refreshes, so a night's runs work through
    # every game before going back over the early ones (2 Nov: an hour on,
    # the first five were stale again and would have taken every run).
    return [c[1:] for c in sorted(out)]


def load_out() -> dict:
    try:
        return json.loads(OUT.read_text())
    except (OSError, ValueError):
        return {"events": {}}


def run() -> int:
    st = load_state()
    why = blocked(st)
    if why:
        print(f"  skybet: {why}; no request made")
        return 0
    if not take_lock():
        print("  skybet: another run is going (cache/skybet.lock); no request made")
        return 0
    try:
        return _run(st)
    finally:
        drop_lock()


def _run(st: dict) -> int:
    out = load_out()
    held = out.setdefault("events", {})
    for k in [k for k, e in held.items() if (e.get("kickoff") or 0) < time.time() - 6 * 3600]:
        held.pop(k)
    budget = min(MAX_PER_RUN, left(st))
    games = 0
    todo = candidates()
    with Browser() as b:
        if todo and budget > len(TABS):
            # Arrive the way a person does: the NBA list first, not straight onto a deep link.
            wait_turn(st, "game")
            try:
                b.get(HUB)
            except Refused as exc:
                bump(st)
                lockout(st, f"{exc} on the NBA hub")
                todo = []
            else:
                bump(st)
                budget -= 1
        for ko, fid, eid, name in todo:
            if budget < len(TABS):
                break
            lines, ok = [], True
            for i, tab in enumerate(tab_order()):
                wait_turn(st, "game" if i == 0 else "tab")
                try:
                    html = b.get(page_url(eid, name, tab))
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
        mode = b.mode
    out["updated"] = time.time()
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(f"  skybet: {games} game(s) fetched via {mode}, {len(held)} held, "
          f"{hour_used(st)}/{MAX_PER_HOUR} requests this hour, {used(st)}/{MAX_PER_DAY} today")
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
    why = blocked(st)
    if why:
        print(f"  skybet: {why}; no request made")
        return 1
    RAW.mkdir(parents=True, exist_ok=True)
    url = page_url(eid, name, "points")
    print("GET", url)
    try:
        html = fetch(url)
    except Refused as exc:
        bump(st)
        lockout(st, str(exc))
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


def paste() -> int:
    """Read Sky Bet data from the clipboard (Mac pbpaste), save it, then show value. No requests."""
    import subprocess
    try:
        text = subprocess.run(["pbpaste"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        print("could not read the clipboard (pbpaste)")
        return 1
    if "ppb:sbkMarket" not in text and "__TBD_PRELOADED_CATALOG__" not in text:
        print("the clipboard has no Sky Bet markets in it: copy the response first")
        return 1
    RAW.mkdir(parents=True, exist_ok=True)
    ext = ".html" if "__TBD_PRELOADED_CATALOG__" in text else ".json"
    m = re.search(r"ppb:event:(\d+)", text)
    (RAW / f"{m.group(1) if m else 'paste'}-paste-{int(time.time())}{ext}").write_text(text)
    from_saved()
    return value()


def status() -> None:
    st = load_state()
    for fid, e in sorted((load_out().get("events") or {}).items(), key=lambda kv: kv[1].get("kickoff", 0)):
        print(f"  {e['name']:<44} {time.strftime('%a %H:%M', time.localtime(e['kickoff']))}  {len(e['lines'])} lines")
    print(f"  requests: {hour_used(st)}/{MAX_PER_HOUR} this hour, {used(st)}/{MAX_PER_DAY} today",
          "SWITCHED OFF" if OFF.exists() else "",
          f"locked: {st.get('lockedWhy')}" if st.get("lockedUntil", 0) > time.time() else "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--value", action="store_true")
    ap.add_argument("--probe", metavar="EVENT_ID")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--paste", action="store_true", help="read a copied Sky Bet response from the clipboard, then --value")
    ap.add_argument("--saved", action="store_true", help="read pages already saved by --probe; no requests")
    ap.add_argument("--max", type=int, metavar="N",
                    help=f"one-off: lift this run's run and hour caps to N (ceiling {HARD_CEILING}); day cap unchanged")
    ap.add_argument("--tabs", metavar="LIST", help="comma list of tabs to read, e.g. points,threes (default all)")
    a = ap.parse_args()
    if a.status:
        status()
        return 0
    if a.paste:
        return paste()
    if a.saved:
        return from_saved()
    if a.probe:
        return probe(a.probe)
    if a.value:
        return value()
    global TABS
    if a.tabs:
        want = tuple(t.strip() for t in a.tabs.split(",") if t.strip() in TABS)
        if want:
            TABS = want
    if a.max:
        print(f"  skybet: caps lifted to {set_max(a.max)} for this run (403/429 still switches off)")
    return run()


if __name__ == "__main__":
    sys.exit(main())
