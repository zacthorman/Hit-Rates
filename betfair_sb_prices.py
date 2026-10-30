#!/usr/bin/env python3
"""Betfair Sportsbook as a fallback for Paddy Power's prices.

    python betfair_sb_prices.py            # runs only while Paddy Power is paused
    python betfair_sb_prices.py --force    # run even if Paddy Power is fine (by hand)
    python betfair_sb_prices.py --check 36206188   # one game: Betfair vs Paddy's held prices
    python betfair_sb_prices.py --status

Paddy Power and Betfair Sportsbook are one Flutter platform: same market ids
(924.x / 927.x), same selection ids, and the same prices. Betfair has no
event-page feed like Paddy's (its site is GraphQL cards), but it does have a
plain prices call, getMarketPrices, that takes a list of market ids and
returns every runner's price. So while Paddy is paused this re-prices the
games Paddy already read (reports/paddypower.json keeps each line's market
and selection id), in a few batched POSTs, and stamps them "via": "betfair"
and "pricesAt". Selections Betfair shows as suspended or closed are dropped.
A game Paddy never read cannot be covered: there is nothing to re-price.

Gentle like Paddy: logged out, no cookies, at most MARKETS_PER_CALL ids per
request, 15 to 30 s apart, capped per day, any refusal locks out
(cache/betfair_sb_state.json), `touch .betfair_sb_off` stops it. Shares
Paddy's run lock, so the two never run at once. Never fatal.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import random
import time
import urllib.error
import urllib.request

import paddypower_prices as pp

ROOT = pp.ROOT
URL = ("https://smp.betfair.com/www/sports/fixedodds/readonly/v1/getMarketPrices"
       "?priceHistory=0&_ak=K61C39rIC0WKzoQ7")
HEADERS = {
    "Accept": "application/json", "Content-Type": "application/json",
    "Accept-Language": "en-GB,en;q=0.9",
    "Origin": "https://www.betfair.com", "Referer": "https://www.betfair.com/",
    "User-Agent": pp.HEADERS["User-Agent"],
}
STATE = ROOT / "cache" / "betfair_sb_state.json"
OFF = ROOT / ".betfair_sb_off"
CHECK_LOG = ROOT / "cache" / "betfair_sb_check.jsonl"
MARKETS_PER_CALL = 40
MAX_CALLS_PER_RUN = 12
MAX_CALLS_PER_DAY = 80
MIN_GAP, JITTER = 15, 15
LOCKOUT_HOURS, SERVER_ERROR_HOURS = 24, 2
FRESH_MIN = 45        # do not re-price a game inside this many minutes


class Refused(Exception):
    pass


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


def blocked(st: dict) -> str | None:
    if OFF.exists():
        return "switched off (.betfair_sb_off)"
    if st.get("lockoutUntil", 0) > now():
        return f"locked out {(st['lockoutUntil'] - now()) / 3600:.1f}h more ({st.get('lockoutWhy')})"
    return None


def count_today(st: dict) -> int:
    return st.get("count", 0) if st.get("day") == pp.today() else 0


def bump(st: dict) -> None:
    if st.get("day") != pp.today():
        st["day"], st["count"] = pp.today(), 0
    st["count"] = st.get("count", 0) + 1
    st["lastRequest"] = now()
    save_state(st)


def lockout(st: dict, why: str, hours: float) -> None:
    st["lockoutUntil"], st["lockoutWhy"] = now() + hours * 3600, why
    save_state(st)
    print(f"  betfair sb: paused for {hours:g}h ({why})")


def wait_turn(st: dict) -> None:
    gap = MIN_GAP + random.uniform(0, JITTER)
    since = now() - st.get("lastRequest", 0)
    if since < gap:
        time.sleep(gap - since)


def fetch_prices(market_ids: list[str]) -> dict:
    """{marketId: {"open": bool, "runners": {selectionId: price or None}}}"""
    body = json.dumps({"marketIds": market_ids}).encode()
    req = urllib.request.Request(URL, data=body, headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise Refused(f"HTTP {exc.code}")
    except urllib.error.URLError as exc:
        raise Refused(f"URLError {exc.reason}")
    except Exception as exc:  # noqa: BLE001
        raise Refused(type(exc).__name__)
    try:
        data = json.loads(raw)
    except ValueError:
        raise Refused("reply was not JSON (a challenge page?)")
    if not isinstance(data, list):
        raise Refused("unexpected reply shape")
    out = {}
    for m in data:
        runners = {}
        for r in m.get("runnerDetails") or []:
            try:
                p = r["winRunnerOdds"]["trueOdds"]["decimalOdds"]["decimalOdds"]
            except (KeyError, TypeError):
                p = None
            runners[r.get("selectionId")] = p if r.get("runnerStatus") == "ACTIVE" else None
        out[str(m.get("marketId"))] = {"open": m.get("marketStatus") == "OPEN", "runners": runners}
    return out


def _rows(ev: dict):
    for k in ("lines", "team", "goals"):
        for row in ev.get(k) or []:
            yield k, row


def market_ids(ev: dict) -> list[str]:
    return sorted({str(r["mid"]) for _, r in _rows(ev) if r.get("mid")})


def apply(ev: dict, prices: dict) -> tuple[int, int, int]:
    """Re-price an event in place. Returns (updated, dropped, untouched)."""
    upd = drop = same = 0
    for k in ("lines", "team", "goals"):
        keep = []
        for row in ev.get(k) or []:
            m = prices.get(str(row.get("mid")))
            if m is None or not row.get("mid"):
                keep.append(row)
                same += 1
                continue
            p = m["runners"].get(row.get("sid")) if m["open"] else None
            if p is None:
                drop += 1
                continue
            if abs(p - row["price"]) > 1e-9:
                row["price"] = round(p, 3)
                upd += 1
            keep.append(row)
        if k in ev:
            ev[k] = keep
    return upd, drop, same


def due(events: dict) -> list[tuple]:
    out = []
    for fid, ev in events.items():
        ko = ev.get("kickoff", 0)
        if ko <= now():
            continue
        last = max(ev.get("fetchedAt", 0), ev.get("pricesAt", 0))
        if now() - last < FRESH_MIN * 60:
            continue
        if not market_ids(ev):
            continue
        out.append((ko, fid))
    return [fid for _, fid in sorted(out)]


def run(force: bool = False) -> int:
    why_pp = pp.blocked(pp.load_state())
    if not why_pp and not force:
        print("  betfair sb: Paddy Power is fetching, not needed")
        return 0
    with open(pp.LOCK, "w") as lockf:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("  betfair sb: a Paddy Power run is going, skipping")
            return 0
        st = load_state()
        why = blocked(st)
        if why:
            print(f"  betfair sb: not fetching, {why}")
            return 0
        print(f"  betfair sb: standing in for Paddy Power ({why_pp or 'forced'})")
        data = pp.load_out()
        events = data.get("events") or {}
        todo = due(events)
        if not todo:
            print("  betfair sb: nothing to re-price")
            return 0
        # Fill each call with whole games, soonest first.
        batches, cur, cur_f = [], [], []
        for fid in todo:
            ids = market_ids(events[fid])
            if cur and len(cur) + len(ids) > MARKETS_PER_CALL:
                batches.append((cur, cur_f))
                cur, cur_f = [], []
            cur += ids
            cur_f.append(fid)
        if cur:
            batches.append((cur, cur_f))
        calls = games = upd = drop = 0
        for ids, fids in batches:
            if calls >= MAX_CALLS_PER_RUN or count_today(st) >= MAX_CALLS_PER_DAY:
                break
            wait_turn(st)
            prices = {}
            try:
                for i in range(0, len(ids), MARKETS_PER_CALL):
                    prices.update(fetch_prices(ids[i:i + MARKETS_PER_CALL]))
            except Refused as exc:
                bump(st)
                server = str(exc) in ("HTTP 500", "HTTP 502", "HTTP 504") or str(exc).startswith("URLError")
                lockout(st, str(exc), SERVER_ERROR_HOURS if server else LOCKOUT_HOURS)
                break
            bump(st)
            calls += 1
            for fid in fids:
                u, d, _ = apply(events[fid], prices)
                events[fid]["via"], events[fid]["pricesAt"] = "betfair", now()
                games += 1
                upd += u
                drop += d
        if games:
            data["updated"] = now()
            pp.OUT.write_text(json.dumps(data, separators=(",", ":")))
        print(f"  betfair sb: {games} game(s) re-priced in {calls} call(s), {upd} prices moved, "
              f"{drop} suspended dropped, {count_today(st)}/{MAX_CALLS_PER_DAY} calls today")
    return 0


def check(event_id: str) -> int:
    """Price one held Paddy game on Betfair and compare. Writes nothing to the prices."""
    ev = next((e for e in (pp.load_out().get("events") or {}).values()
               if str(e.get("ppEvent")) == str(event_id)), None) or {}
    if not market_ids(ev):
        # Held before ids were kept: read a saved Paddy reply instead
        # (python paddypower_prices.py --event ID --save).
        saved = ROOT / "cache" / f"pp_event_{event_id}.json"
        if saved.exists():
            page = json.loads(saved.read_text())
            ev = {"name": ev.get("name") or event_id, "fetchedAt": saved.stat().st_mtime,
                  "lines": pp.player_lines(page), "team": pp.team_lines(page), "goals": pp.goal_lines(page)}
    ids = market_ids(ev)
    if not ids:
        print("no market ids for that game yet. Run first:\n"
              f"  .venv/bin/python paddypower_prices.py --event {event_id} --save")
        return 1
    st = load_state()
    why = blocked(st)
    if why:
        print("not fetching:", why)
        return 0
    prices = {}
    try:
        for i in range(0, len(ids), MARKETS_PER_CALL):
            wait_turn(st)
            prices.update(fetch_prices(ids[i:i + MARKETS_PER_CALL]))
            bump(st)
    except Refused as exc:
        bump(st)
        print("failed:", exc, "(no lockout for a by-hand check)")
        return 1
    both = differ = gone = 0
    diffs = []
    for _, row in _rows(ev):
        m = prices.get(str(row.get("mid")))
        if not m:
            continue
        p = m["runners"].get(row.get("sid")) if m["open"] else None
        if p is None:
            gone += 1
            continue
        both += 1
        if abs(p - row["price"]) > 0.005:
            differ += 1
            diffs.append((row.get("player") or row.get("stat"), row.get("market"), row.get("line"), row["price"], p))
    age = (now() - ev.get("fetchedAt", 0)) / 3600
    print(f"{ev.get('name')}: {len(ids)} markets asked, {len(prices)} answered; "
          f"{both} selections matched, {differ} priced differently, {gone} suspended "
          f"(Paddy's copy is {age:.1f}h old)")
    for d in diffs[:25]:
        print(f"  {str(d[0]):22} {str(d[1])[:30]:30} {d[2] or '':>5}  PP {d[3]}  BF {round(d[4], 3)}")
    CHECK_LOG.parent.mkdir(exist_ok=True)
    with open(CHECK_LOG, "a") as f:
        f.write(json.dumps({"at": now(), "event": event_id, "name": ev.get("name"), "paddyAgeH": round(age, 2),
                            "markets": len(ids), "matched": both, "differ": differ, "gone": gone}) + "\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--check")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.status:
        st = load_state()
        held = (pp.load_out().get("events") or {}).values()
        print("Paddy Power:", pp.blocked(pp.load_state()) or "fetching normally")
        print("Betfair SB:", blocked(st) or "ready", f"({count_today(st)}/{MAX_CALLS_PER_DAY} calls today)")
        print("games with ids to re-price:", sum(1 for e in held if market_ids(e)),
              "| re-priced via Betfair:", sum(1 for e in held if e.get("via") == "betfair"))
        return 0
    if a.check:
        return check(a.check)
    return run(a.force)


if __name__ == "__main__":
    raise SystemExit(main())
