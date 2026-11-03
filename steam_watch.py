#!/usr/bin/env python3
"""Pinnacle steam watcher: alert when Pinnacle moves and Paddy or Sky has not.

    python steam_watch.py              # watch until the last game in the window starts
    python steam_watch.py --once       # one poll, then stop
    python steam_watch.py --test       # send a test alert to the phone, no requests
    python steam_watch.py --status     # requests used, alerts sent today

Why (2 Nov 2026): Max Christie Over 9.5 points sat at 2.62 at Paddy Power for
hours while Pinnacle had the same line at 1.80 (a 52% fair chance, +36%),
then Paddy cut it to 2.00. pplog.py already compares every Paddy line with
Pinnacle, but only when publish.sh runs, so a gap like that is seen after it
has closed. This polls Pinnacle's player props for the games starting soon,
and the moment its fair chance for a line makes a soft book's last-seen price
3%+ value, sends an alert to the phone (ntfy) and the Mac.

It never fetches Paddy, Sky or Bet365: it reads the prices already held in
reports/paddypower.json, reports/skybet.json and reports/bet365.json, so the
alert says "last seen 2.62 at 21:15, check now", and the check is yours.

Requests (Pinnacle's guest API, the same feed and manners as pinnacle_props.py,
and reading it is against Pinnacle's terms): games come from
reports/pinnacle_props.json, so no league calls. The first time a game is
watched, one call learns its player props (cached for the night); after that
one call per game per poll reads the prices. Only games starting inside
WINDOW_MIN, at most GAMES_PER_POLL a poll, every POLL_MIN (plus jitter), under
this watcher's own MAX_PER_DAY. A refusal locks the watcher out for a day;
`touch .pinnacle_off` switches it off with the other Pinnacle feeds.

Alerts go to https://ntfy.sh/<topic>: install the ntfy app, subscribe to the
topic `--status` prints. The topic is made once and kept in
cache/steam_topic.txt (set STEAM_NTFY_TOPIC to use your own). Every alert is
also appended to reports/steam_alerts.jsonl, so ruletrack-style checks can
later say whether these won.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import secrets
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

PROPS = ROOT / "reports" / "pinnacle_props.json"
SOFT = {"Paddy": ROOT / "reports" / "paddypower.json",
        "Sky": ROOT / "reports" / "skybet.json",
        "Bet365": ROOT / "reports" / "bet365.json"}
STATE = ROOT / "cache" / "steam_watch_state.json"
TOPIC_FILE = ROOT / "cache" / "steam_topic.txt"
ALERTS = ROOT / "reports" / "steam_alerts.jsonl"

MAX_PER_DAY = 150         # this watcher's own Pinnacle requests
GAMES_PER_POLL = 6
WINDOW_MIN = 150          # watch games starting in the next 2.5 hours
POLL_MIN = 9.0            # minutes between polls, plus up to POLL_JITTER
WAIT_HOURS = 14           # started early: wait for a tip-off up to this far ahead (3 Nov), else stop
WAIT_CHUNK_MIN = 30       # while waiting, look again this often (publish.sh may add games); no requests
POLL_JITTER = 3.0
MIN_EDGE = 0.05           # soft price x Pinnacle's fair chance - 1 (3 Nov: was 3%, all noise)
CONFIRM_PER_NIGHT = 15    # live re-checks per soft book per day, inside that book's own caps
CONFIRM_GAP_MIN = 30      # a game is re-checked at one book at most this often
SKY_TABS = {"Points": "points", "Rebounds": "rebounds", "Assists": "assists",
            "Three pointers made": "threes"}
REALERT_STEP = 0.05       # alert again on the same line only if the edge grows this much
MOVE = 0.04               # a fair-chance move this big between polls is "steam"
PRICE_RANGE = (1.30, 6.0)
STALE_SOFT_HOURS = 8      # a soft price older than this is too old to chase


# ------------------------------------------------------------ pure helpers

def norm(name: str) -> str:
    import pinnacle_props
    return pinnacle_props._norm(name or "")


def soft_index(books: dict) -> dict:
    """{(fid, player, stat, line, over): [(book, price, fetchedAt)]} from the soft books' reports."""
    import pplog
    idx: dict = {}
    for book, data in books.items():
        for fid, ev in (data.get("events") or {}).items():
            at = ev.get("fetchedAt") or 0
            for l in ev.get("lines") or []:
                got = pplog.read_line(l)
                if not got or not l.get("price"):
                    continue
                stat, line, over, _label = got
                idx.setdefault((str(fid), norm(l.get("player")), stat, float(line), over), []).append(
                    (book, float(l["price"]), at))
    return idx


def label(stat: str, line: float, over: bool) -> str:
    return f"{'Over' if over else 'Under'} {line:g} {stat.lower()}"


def decide(rows: list[dict], prev: dict, idx: dict, alerted: dict, game: dict, now: float) -> list[dict]:
    """Alerts for one game's fresh Pinnacle rows.

    rows: pinnacle_props.props_of rows {player, stat, line, over, price, p}.
    prev: {key: p} from the last poll. alerted: {alert key: edge already sent}."""
    out, seen = [], set()
    fid = str(game.get("fid") or "")
    for r in rows:
        key = f"{game['gid']}|{norm(r['player'])}|{r['stat']}|{r['line']:g}|{int(r['over'])}"
        was = prev.get(key)
        moved = was is not None and abs(r["p"] - was) >= MOVE
        for book, price, at in idx.get((fid, norm(r["player"]), r["stat"], float(r["line"]), r["over"]), []):
            if not PRICE_RANGE[0] <= price <= PRICE_RANGE[1] or now - at > STALE_SOFT_HOURS * 3600:
                continue
            edge = price * r["p"] - 1
            akey = f"{key}|{book}"
            if edge < MIN_EDGE or edge < alerted.get(akey, -9) + REALERT_STEP or akey in seen:
                continue
            seen.add(akey)
            out.append({"t": now, "key": akey, "game": game.get("name"), "kickoff": game.get("kickoff"),
                        "player": r["player"], "stat": r["stat"], "line": r["line"], "over": r["over"],
                        "book": book, "price": price, "seen_at": at, "p": r["p"], "fair": round(1 / r["p"], 3),
                        "pin_price": r["price"], "was_p": was, "moved": moved, "edge": round(edge, 4)})
    return out


def message(a: dict) -> tuple[str, str]:
    ko = time.strftime("%H:%M", time.localtime(a["kickoff"])) if a.get("kickoff") else "?"
    move = ""
    if a.get("was_p") is not None:
        move = f" (was {1 / a['was_p']:.2f})" if a["moved"] else ""
    title = f"{a['book']} {a['price']:.2f} v fair {a['fair']:.2f}: {a['edge']:+.0%}"
    body = (f"{a['player']} {label(a['stat'], a['line'], a['over'])}\n"
            f"Pinnacle fair {a['fair']:.2f}{move}. {a['book']} last seen {a['price']:.2f} "
            f"at {time.strftime('%H:%M', time.localtime(a['seen_at']))}"
            f"{' (re-checked live)' if a.get('confirmed') else ''}. Bet it now if it is still there.\n"
            f"{a['game']}, {ko}")
    return title, body


# ------------------------------------------------------------ state, alerts

def load_json(p: Path, default):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return default


def save_state(st: dict) -> None:
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(st))


def topic() -> str:
    t = os.getenv("STEAM_NTFY_TOPIC", "").strip()
    if t:
        return t
    try:
        return TOPIC_FILE.read_text().strip()
    except OSError:
        t = "hitrates-steam-" + secrets.token_hex(5)
        TOPIC_FILE.parent.mkdir(exist_ok=True)
        TOPIC_FILE.write_text(t + "\n")
        return t


def notify(title: str, body: str) -> None:
    print(f"\n  ALERT  {title}\n         " + body.replace("\n", "\n         "))
    try:
        req = urllib.request.Request(f"https://ntfy.sh/{topic()}", data=body.encode(),
                                     headers={"Title": title, "Priority": "high", "Tags": "chart_with_upwards_trend"})
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as exc:  # noqa: BLE001
        print(f"  (phone alert failed: {type(exc).__name__})")
    if sys.platform == "darwin":
        safe = lambda s: s.replace('"', "'").replace("\n", " ")
        subprocess.run(["osascript", "-e", f'display notification "{safe(body)}" with title "{safe(title)}" sound name "Glass"'],
                       capture_output=True)


# ------------------------------------------------------------ polling

def _confirm_room(st: dict, book: str, fid: str, tab: str = "") -> bool:
    import pinnacle_prices as PP
    c = st.setdefault("confirm", {})
    if c.get("day") != PP.today():
        c.clear()
        c["day"] = PP.today()
    if c.get(book, 0) >= CONFIRM_PER_NIGHT:
        return False
    last = c.setdefault("last", {}).get(f"{book}|{fid}|{tab}", 0)
    return time.time() - last >= CONFIRM_GAP_MIN * 60


def _confirmed(st: dict, book: str, fid: str, tab: str = "") -> None:
    c = st["confirm"]
    c[book] = c.get(book, 0) + 1
    c["last"][f"{book}|{fid}|{tab}"] = time.time()
    save_state(st)


def recheck_paddy(fid: str, st: dict):
    """Paddy's lines for one game, fetched now, inside paddypower_prices' own caps and lockout. None if not allowed."""
    import fcntl
    import paddypower_prices as PPP
    ev = (load_json(SOFT["Paddy"], {}).get("events") or {}).get(fid) or {}
    if not ev.get("ppEvent") or not _confirm_room(st, "Paddy", fid):
        return None
    with open(PPP.LOCK, "w") as lockf:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return None                       # a publish run is fetching Paddy right now
        pst = PPP.load_state()
        if PPP.blocked(pst) or PPP.count_today(pst) >= PPP.MAX_PER_DAY:
            return None
        PPP.wait_turn(pst)
        try:
            page = PPP.fetch_event(ev["ppEvent"])
        except PPP.BadId:
            PPP.bump(pst)
            return None
        except PPP.Refused as exc:
            PPP.bump(pst)
            PPP.lockout(pst, str(exc), isinstance(exc, PPP.ServerError))
            return None
        PPP.bump(pst)
    _confirmed(st, "Paddy", fid)
    return PPP.player_lines(page)


def recheck_sky(fid: str, stat: str, st: dict):
    """Sky's lines for one game's tab, fetched now, inside skybet_prices' caps, lock and 403 switch. None if not allowed."""
    import skybet_prices as SK
    ev = (load_json(SOFT["Sky"], {}).get("events") or {}).get(fid) or {}
    tab = SKY_TABS.get(stat)
    if not ev.get("skEvent") or not tab or not _confirm_room(st, "Sky", fid, tab):
        return None
    sst = SK.load_state()
    if SK.blocked(sst) or not SK.take_lock():
        return None
    try:
        SK.wait_turn(sst, "tab")
        with SK.Browser() as b:
            try:
                html = b.get(SK.page_url(ev["skEvent"], ev.get("name", ""), tab))
            except SK.Refused as exc:
                SK.bump(sst)
                SK.lockout(sst, str(exc))
                return None
        SK.bump(sst)
    finally:
        SK.drop_lock()
    if not SK.catalog(html):
        return None
    _confirmed(st, "Sky", fid, tab)
    return SK.lines_of(html)


def confirm(cands: list[dict], rows: list[dict], prev: dict, alerted: dict, g: dict, st: dict) -> list[dict]:
    """Re-fetch each soft book's price for the flagged lines; keep only alerts still 5%+ at the fresh price.
    Bet365 has no cheap single-game fetch, so its alerts are dropped rather than sent stale."""
    fid, out = str(g.get("fid") or ""), []
    for book in sorted({a["book"] for a in cands}):
        fresh = []
        if book == "Paddy":
            fresh = recheck_paddy(fid, st) or []
        elif book == "Sky":
            for stat in sorted({a["stat"] for a in cands if a["book"] == "Sky"}):
                fresh += recheck_sky(fid, stat, st) or []
        if not fresh:
            print(f"  {book}: {sum(a['book'] == book for a in cands)} flagged line(s) in {g.get('name')} not re-checked; not sent")
            continue
        idx = soft_index({book: {"events": {fid: {"fetchedAt": time.time(), "lines": fresh}}}})
        keep = [a for a in decide(rows, prev, idx, alerted, g, time.time()) if a["book"] == book]
        gone = sum(a["book"] == book for a in cands) - len(keep)
        if gone:
            print(f"  {book}: {gone} flagged line(s) in {g.get('name')} already moved; not sent")
        out += keep
    return out


def games_soon(now: float) -> list[dict]:
    held = (load_json(PROPS, {}).get("events") or {})
    out = []
    for gid, e in held.items():
        ko = e.get("kickoff") or 0
        if e.get("sport") in ("basketball", "american-football") and 0 < ko - now < WINDOW_MIN * 60:
            out.append({"gid": str(gid), "name": e.get("name"), "kickoff": ko, "fid": e.get("fid"), "sport": e["sport"]})
    return sorted(out, key=lambda g: g["kickoff"])


def next_kickoff(now: float) -> float | None:
    """The first NBA/NFL kickoff after the watch window but inside WAIT_HOURS, or None."""
    held = (load_json(PROPS, {}).get("events") or {})
    kos = [e.get("kickoff") or 0 for e in held.values()
           if e.get("sport") in ("basketball", "american-football")]
    kos = [k for k in kos if WINDOW_MIN * 60 <= k - now <= WAIT_HOURS * 3600]
    return min(kos) if kos else None


def specials_for(game: dict, st: dict, PP) -> list:
    """[(special id, sides, player, stat)] for a game, learned once and cached."""
    import pinnacle_props
    cache = st.setdefault("specials", {})
    if game["gid"] in cache:
        return cache[game["gid"]]
    rel = PP.get(f"/matchups/{game['gid']}/related", st)
    found = []
    for m in rel if isinstance(rel, list) else []:
        if isinstance(m, dict) and m.get("type") == "special":
            got = pinnacle_props.parse_special(m, game["sport"])
            if got:
                player, stat, sides, _parent = got
                found.append([m.get("id"), {str(k): v for k, v in sides.items()}, player, stat])
    cache[game["gid"]] = found
    return found


def poll(st: dict) -> int:
    import pinnacle_prices as PP
    import pinnacle_props
    PP.MAX_PER_DAY = MAX_PER_DAY
    now = time.time()
    games = games_soon(now)[:GAMES_PER_POLL]
    if not games:
        return 0
    idx = soft_index({b: load_json(p, {}) for b, p in SOFT.items()})
    prev, alerted = st.setdefault("snap", {}), st.setdefault("alerted", {})
    if st.get("alerted_day") != PP.today():
        alerted.clear()
        st["alerted_day"] = PP.today()
    sent = 0
    for g in games:
        specs = specials_for(g, st, PP)
        save_state(st)
        if not specs:
            continue
        mk = PP.get(f"/matchups/{g['gid']}/markets/related/straight", st)
        save_state(st)
        by_m: dict = {}
        for x in mk if isinstance(mk, list) else []:
            by_m.setdefault(x.get("matchupId"), []).append(x)
        rows = []
        for sid, sides, player, stat in specs:
            sides = {int(k) if str(k).lstrip("-").isdigit() else k: v for k, v in sides.items()}
            rows += [r for x in by_m.get(sid, []) for r in pinnacle_props.props_of(x, sides, player, stat)]
        cands = decide(rows, prev, idx, alerted, g, now)
        for a in confirm(cands, rows, prev, alerted, g, st) if cands else []:
            a["confirmed"] = True
            notify(*message(a))
            alerted[a["key"]] = a["edge"]
            ALERTS.parent.mkdir(exist_ok=True)
            with ALERTS.open("a") as f:
                f.write(json.dumps(a) + "\n")
            sent += 1
        for r in rows:
            prev[f"{g['gid']}|{norm(r['player'])}|{r['stat']}|{r['line']:g}|{int(r['over'])}"] = r["p"]
        save_state(st)
    return sent


def blocked(st: dict) -> str:
    import pinnacle_prices as PP
    if PP.OFF.exists():
        return "switched off (.pinnacle_off)"
    if st.get("lockedUntil", 0) > time.time():
        return f"locked out ({st.get('lockedWhy')})"
    other = load_json(ROOT / "cache" / "pinnacle_props_state.json", {})
    if other.get("lockedUntil", 0) > time.time():
        return f"pinnacle_props is locked out ({other.get('lockedWhy')})"
    return ""


def watch(once: bool = False) -> int:
    import pinnacle_prices as PP
    st = load_json(STATE, {})
    print(f"  steam watch: alerts to ntfy.sh/{topic()} (subscribe in the ntfy app); "
          f"{GAMES_PER_POLL} games every {POLL_MIN:g}-{POLL_MIN + POLL_JITTER:g} min")
    transient = 0
    started = time.time()
    while True:
        why = blocked(st)
        if why:
            print(f"  steam watch: {why}; stopping")
            return 0
        try:
            sent = poll(st)
            transient = 0
        except PP.Capped as e:
            print(f"  steam watch: {e}; stopping")
            return 0
        except PP.Transient as e:
            transient += 1
            print(f"  steam watch: {e}" + ("; second in a row, stopping" if transient >= 2 else "; trying next poll"))
            if transient >= 2:
                return 0
            sent = 0
        except PP.Refused as e:
            st["lockedUntil"], st["lockedWhy"] = time.time() + PP.LOCKOUT_HOURS * 3600, str(e)
            save_state(st)
            print(f"  steam watch: refused ({e}); locked out for {PP.LOCKOUT_HOURS}h")
            return 0
        left = games_soon(time.time())
        used = st.get("count", {}).get(PP.today(), 0)
        print(f"  {time.strftime('%H:%M')}  {sent} alert(s), {len(left)} game(s) in the window, "
              f"{used}/{MAX_PER_DAY} requests today")
        if once:
            return 0
        if not left:
            nxt = next_kickoff(time.time())
            if not nxt:
                # Tonight's games reach reports/pinnacle_props.json only when publish.sh runs, so
                # an early start waits for that (re-reading the file, no requests) up to WAIT_HOURS.
                if time.time() - started > WAIT_HOURS * 3600:
                    print(f"  steam watch: no NBA/NFL game known after {WAIT_HOURS}h; stopping")
                    return 0
                print(f"  waiting: no NBA/NFL games known yet (pinnacle_props.json updated "
                      f"{time.strftime('%d %b %H:%M', time.localtime(load_json(PROPS, {}).get('updated', 0)))}); "
                      f"looking again in {WAIT_CHUNK_MIN} min, no requests")
                time.sleep(WAIT_CHUNK_MIN * 60)
                continue
            wake = nxt - WINDOW_MIN * 60
            print(f"  waiting: first tip-off {time.strftime('%H:%M', time.localtime(nxt))}, "
                  f"watching from about {time.strftime('%H:%M', time.localtime(wake))} (no requests until then)")
            time.sleep(min(max(wake - time.time(), 60), WAIT_CHUNK_MIN * 60))
            continue
        time.sleep((POLL_MIN + random.uniform(0, POLL_JITTER)) * 60)


def status() -> None:
    import pinnacle_prices as PP
    st = load_json(STATE, {})
    print(f"  ntfy topic: {topic()}  (ntfy app > + > subscribe to this name)")
    print(f"  requests today: {st.get('count', {}).get(PP.today(), 0)}/{MAX_PER_DAY}",
          blocked(st) or "")
    today = time.strftime("%Y-%m-%d")
    n = 0
    try:
        for line in ALERTS.read_text().splitlines():
            a = json.loads(line)
            if time.strftime("%Y-%m-%d", time.localtime(a["t"])) == today:
                n += 1
                print("   ", message(a)[0], "|", a["player"], label(a["stat"], a["line"], a["over"]))
    except OSError:
        pass
    print(f"  alerts today: {n}")


def main() -> int:
    global GAMES_PER_POLL, POLL_MIN
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--test", action="store_true", help="send a test alert, no requests")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--games", type=int, metavar="N", help=f"games per check (default {GAMES_PER_POLL})")
    ap.add_argument("--every", type=float, metavar="MIN", help=f"minutes between checks (default {POLL_MIN:g})")
    a = ap.parse_args()
    if a.games:
        GAMES_PER_POLL = max(1, a.games)
    if a.every:
        POLL_MIN = max(5.0, a.every)
    if a.status:
        status()
        return 0
    if a.test:
        notify("Steam watch test", f"If this reached your phone, alerts work. Topic: {topic()}")
        return 0
    return watch(a.once)


if __name__ == "__main__":
    sys.exit(main())
