#!/usr/bin/env python3
"""NBA injury news, seen as it lands: step 1 of INJURY-NEWS-TEST.md.

    python news_watch.py             # one tick: fetch, diff, log any news
    python news_watch.py --force     # the same outside the NBA window
    python news_watch.py --dry-run   # print what it would log, write nothing
    python news_watch.py status      # what it has seen so far

The question (INJURY-NEWS-TEST.md): when an NBA player is ruled out, or
back in, does Paddy Power leave his team-mates' props at the old price long
enough to take them? Before that can be answered, the news itself has to be
caught, with the time it landed and the time we saw it. That is all this
does. It bets nothing and makes no Paddy Power request; step 2 will spend a
small reserve of those on the games this flags.

Each tick (launchd, every 3 minutes, 16:00 to 03:30 UK):

  1. Fetch ESPN's NBA injury feed, at most once every FRESH seconds. Its own
     cache file, so team_news.py's three-hour copy is never touched.
  2. Diff it against the last answer. A player's status is read as a level:
     fit (not listed, Probable), doubt (Day-To-Day, Questionable) or out
     (Out, Doubtful, Suspension). A change of level is a change.
  3. Keep the changes that can move a price tonight: his team plays within
     HORIZON hours, he averages MIN_MINUTES or more over his last 10
     appearances, and, for an "out", he played in at least one of his team's
     last LONG_OUT_GAMES games (a long absence is already priced).
  4. Append each kept change to news/events.jsonl and each dropped one, with
     the reason, to news/skipped.jsonl, so the filters can be checked.

An event's "kind" is out (to Out or Doubtful), back (from out to anything
else), downgrade or upgrade (between fit and doubt). Out and back are the
ones the test is about; the other two are kept for the record.

ESPN statuses only, not its comments: a comment such as "won't return to
Saturday's game" is about a game already played as often as the next one.
The comment is stored with the event so that can be checked later.

Safety, as for the price feeds:
  - Off switch: an empty file `.news_off` in this folder stops it.
  - One run at a time (a lock file); a second tick just exits.
  - Never fatal: any failure logs one line to news/watch.log and exits 0.
  - The first run, and any run after a missing or broken snapshot, only
    records a baseline: otherwise every listed player would be "news".
  - An answer far smaller than the last (half the players gone) is treated
    as a broken reply and ignored, not read as 40 players coming back.

news/ is kept on this machine like pplog/ (gitignored).
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import re
import sys
import time
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
NEWS = ROOT / "news"
EVENTS = NEWS / "events.jsonl"
SKIPPED = NEWS / "skipped.jsonl"
STATE = NEWS / "espn_last.json"
LOG = NEWS / "watch.log"
RAW = ROOT / "cache" / "news" / "espn_nba.json"
LOCK = ROOT / "cache" / "news" / "news_watch.lock"
OFF = ROOT / ".news_off"
REPORT = ROOT / "reports" / "nba.html"

URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
FRESH = 170            # seconds an ESPN answer is reused (a 3-minute tick refetches)
HORIZON = 14 * 3600    # only games tipping off within this
MIN_MINUTES = 15.0     # his average over his last 10 appearances
LONG_OUT_GAMES = 3     # an "out" who missed all of these is a long absence
SHRINK = 0.5           # an answer under this share of the last is broken
UK = ZoneInfo("Europe/London")
WINDOW = ((16, 0), (3, 30))   # UK local time, across midnight

FIT, DOUBT, OUT = 0, 1, 2
LEVEL_NAMES = {FIT: "fit", DOUBT: "doubt", OUT: "out"}
NOT_LISTED = "Not listed"
_OUT = re.compile(r"^(out|doubtful|suspen|inactive|injured reserve|not with team)", re.I)
_DOUBT = re.compile(r"^(day.to.day|questionable|game.time|gtd)", re.I)
_FIT = re.compile(r"^(probable|available|active)", re.I)


# ------------------------------------------------------------------ helpers

def now() -> float:
    return time.time()


def _norm(name: str) -> str:
    """team_news._norm: accents, punctuation and suffixes ignored."""
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    n = re.sub(r"[^a-z ]", "", n.lower().replace("-", " "))
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    return " ".join(n.split())


def _nickname(team: str) -> str:
    """The last word of a team name: unique in the NBA, and the same whether
    ESPN says "LA Clippers" or SofaScore "Los Angeles Clippers"."""
    words = _norm(team).split()
    return words[-1] if words else ""


def level(status: str | None) -> int:
    if not status or status == NOT_LISTED:
        return FIT
    s = status.strip()
    if _OUT.match(s):
        return OUT
    if _FIT.match(s):
        return FIT
    if _DOUBT.match(s):
        return DOUBT
    return DOUBT   # anything unfamiliar: neither fit nor out


def kind(before: int, after: int) -> str | None:
    if before == after:
        return None
    if after == OUT:
        return "out"
    if before == OUT:
        return "back"
    return "downgrade" if after > before else "upgrade"


def in_window(t: float) -> bool:
    local = datetime.fromtimestamp(t, UK)
    hm = (local.hour, local.minute)
    start, end = WINDOW
    return hm >= start or hm < end


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_espn_date(s: str | None) -> float | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def log(msg: str, t: float | None = None) -> None:
    try:
        NEWS.mkdir(exist_ok=True)
        stamp = datetime.fromtimestamp(t or now(), UK).strftime("%d %b %H:%M:%S")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{stamp}  {msg}\n")
    except OSError:
        pass
    print(f"news watch: {msg}")


# ------------------------------------------------------------------ ESPN

def fetch_espn() -> dict:
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 hit-rates"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def espn_answer(t: float, fetch=fetch_espn) -> tuple[dict | None, bool]:
    """(ESPN's answer, fresh from the network?). Reuses RAW inside FRESH."""
    if RAW.exists() and t - RAW.stat().st_mtime < FRESH:
        try:
            return json.loads(RAW.read_text(encoding="utf-8")), False
        except ValueError:
            pass
    data = fetch()
    RAW.parent.mkdir(parents=True, exist_ok=True)
    RAW.write_text(json.dumps(data), encoding="utf-8")
    return data, True


def listing(data: dict) -> dict[str, dict]:
    """{normalised name: {player, team, status, date, comment, espn_id}}."""
    out = {}
    for team in (data or {}).get("injuries") or []:
        tname = team.get("displayName") or ""
        for inj in team.get("injuries") or []:
            ath = inj.get("athlete") or {}
            name = ath.get("displayName")
            status = inj.get("status")
            if isinstance(status, dict):
                status = status.get("name") or status.get("type")
            if not name or not status:
                continue
            ath_team = (ath.get("team") or {}).get("displayName") if isinstance(ath.get("team"), dict) else None
            out[_norm(name)] = {
                "player": name, "team": ath_team or tname, "status": str(status),
                "date": inj.get("date"), "comment": inj.get("shortComment") or "",
                "espn_id": inj.get("id"),
            }
    return out


def changes(before: dict, after: dict) -> list[dict]:
    """Every player whose level moved, with what he was and is."""
    out = []
    for key in sorted(set(before) | set(after)):
        b, a = before.get(key), after.get(key)
        sb = b["status"] if b else NOT_LISTED
        sa = a["status"] if a else NOT_LISTED
        k = kind(level(sb), level(sa))
        if k is None:
            continue
        cur = a or b
        out.append({
            "key": key, "player": cur["player"], "team": cur["team"],
            "from_status": sb, "to_status": sa,
            "from_level": LEVEL_NAMES[level(sb)], "to_level": LEVEL_NAMES[level(sa)],
            "kind": k,
            # a player taken off the list carries no new date of his own
            "espn_date": a.get("date") if a else None,
            "comment": (a or {}).get("comment", ""),
            "espn_id": cur.get("espn_id"),
        })
    return out


# ------------------------------------------------------------------ fixtures

def load_fixtures(t: float, path: Path = REPORT) -> list[tuple[dict, dict]]:
    """(entry, meta) for every NBA game tipping off within HORIZON."""
    if not path.exists():
        return []
    import make_index
    return [(e, m) for e, m in make_index.read_entries(path)
            if t < (m.get("kickoff") or 0) <= t + HORIZON]


def _place(change: dict, fixtures: list) -> tuple[dict, dict, int] | None:
    """The game and side he plays for: by name in a squad first, then team."""
    for e, m in fixtures:
        for side in (0, 1):
            for r in (e.get("players") or [[], []])[side]:
                if _norm(r.get("player")) == change["key"]:
                    return e, m, side
    nick = _nickname(change["team"])
    for e, m in fixtures:
        for side, name in ((0, m["home"]), (1, m["away"])):
            if nick and _nickname(name) == nick:
                return e, m, side
    return None


def _record(entry: dict, side: int, key: str) -> dict:
    """His last 10 appearances' minutes, and whether he played lately."""
    rows = (entry.get("players") or [[], []])[side]
    mine = sorted((r for r in rows if _norm(r.get("player")) == key and (r.get("minutes") or 0) > 0),
                  key=lambda r: r.get("date") or "")
    last10 = mine[-10:]
    team_dates = sorted({r.get("date") for r in rows if r.get("date") and (r.get("minutes") or 0) > 0})
    recent = team_dates[-LONG_OUT_GAMES:]
    my_dates = {r.get("date") for r in mine}
    return {
        "apps": len(last10),
        "avg_minutes": round(sum(r["minutes"] for r in last10) / len(last10), 1) if last10 else None,
        "played_recent": sum(1 for d in recent if d in my_dates),
        "recent_team_games": len(recent),
        "last_played": mine[-1].get("date") if mine else None,
    }


def judge(change: dict, fixtures: list, t: float) -> tuple[dict | None, str | None]:
    """(event, None) to keep it, or (partial row, reason) to skip it."""
    placed = _place(change, fixtures)
    if placed is None:
        return dict(change), "his team has no game within the horizon"
    entry, meta, side = placed
    rec = _record(entry, side, change["key"])
    row = dict(change)
    row.update({
        "fixture_id": meta["id"], "fixture": f"{meta['home']} v {meta['away']}",
        "kickoff": meta["kickoff"], "side": "home" if side == 0 else "away",
        **rec,
    })
    if rec["avg_minutes"] is None:
        return row, "no appearances on record"
    if rec["avg_minutes"] < MIN_MINUTES:
        return row, f"averages {rec['avg_minutes']} minutes, under {MIN_MINUTES:g}"
    if (change["kind"] == "out" and rec["recent_team_games"] >= LONG_OUT_GAMES
            and rec["played_recent"] == 0):
        return row, f"missed all of his team's last {LONG_OUT_GAMES} games, already priced"
    return row, None


def _stamp(row: dict, t: float) -> dict:
    espn_ts = _parse_espn_date(row.get("espn_date"))
    row["seen_at"] = round(t)
    row["seen_iso"] = _iso(t)
    row["espn_ts"] = espn_ts
    row["lag_min"] = round((t - espn_ts) / 60, 1) if espn_ts else None
    row["mins_to_tip"] = round((row["kickoff"] - t) / 60) if row.get("kickoff") else None
    ident = f"{row['key']}|{row.get('fixture_id')}|{row['to_status']}|{row.get('espn_date')}"
    row["id"] = hashlib.sha1(ident.encode()).hexdigest()[:12]
    row.setdefault("paddy", None)   # step 2 fills this in
    return row


# ------------------------------------------------------------------ files

def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _append(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    NEWS.mkdir(exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def load_state() -> dict | None:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_state(players: dict, t: float) -> None:
    NEWS.mkdir(exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"fetched_at": round(t), "players": players}), encoding="utf-8")
    tmp.replace(STATE)


# ------------------------------------------------------------------ the tick

def tick(t: float | None = None, force: bool = False, dry: bool = False,
         fetch=fetch_espn, fixtures_loader=load_fixtures) -> dict:
    """One run. Returns a summary; never raises for an expected failure."""
    t = now() if t is None else t
    if OFF.exists():
        return {"ran": False, "why": ".news_off is set"}
    if not force and not in_window(t):
        return {"ran": False, "why": "outside the NBA window"}
    try:
        data, fresh = espn_answer(t, fetch)
    except Exception as exc:  # noqa: BLE001  never fatal
        log(f"ESPN not fetched ({type(exc).__name__}: {exc}); nothing changed", t)
        return {"ran": True, "error": type(exc).__name__}
    current = listing(data)
    state = load_state()
    if state is None or not isinstance(state.get("players"), dict):
        if not dry:
            save_state(current, t)
        log(f"baseline recorded: {len(current)} players listed", t)
        return {"ran": True, "baseline": True, "listed": len(current)}
    before = state["players"]
    if before and len(current) < SHRINK * len(before):
        log(f"ESPN listed {len(current)} players against {len(before)} last time; "
            "treated as a broken answer, ignored", t)
        return {"ran": True, "ignored": True, "listed": len(current)}
    moved = changes(before, current)
    kept, skipped = [], []
    if moved:
        try:
            fixtures = fixtures_loader(t)
        except Exception as exc:  # noqa: BLE001
            log(f"NBA report not read ({type(exc).__name__}); {len(moved)} change(s) "
                "held for the next tick", t)
            return {"ran": True, "error": type(exc).__name__, "held": len(moved)}
        seen = {r.get("id") for r in _read_jsonl(EVENTS)}
        for ch in moved:
            row, why = judge(ch, fixtures, t)
            row = _stamp(row, t)
            if why is None:
                if row["id"] not in seen:
                    kept.append(row)
            else:
                row["reason"] = why
                skipped.append(row)
    if dry:
        for r in kept:
            print(f"  WOULD LOG  {r['kind']:9} {r['player']} ({r['from_status']} -> {r['to_status']}) "
                  f"{r['fixture']}, tip in {r['mins_to_tip']} min, avg {r['avg_minutes']} min")
        for r in skipped:
            print(f"  would skip {r['kind']:9} {r['player']}: {r['reason']}")
        return {"ran": True, "dry": True, "events": len(kept), "skipped": len(skipped)}
    _append(EVENTS, kept)
    _append(SKIPPED, skipped)
    save_state(current, t)
    for r in kept:
        lag = f", {r['lag_min']} min after ESPN's stamp" if r.get("lag_min") is not None else ""
        log(f"NEWS {r['kind']}: {r['player']} {r['from_status']} -> {r['to_status']}, "
            f"{r['fixture']}, tip in {r['mins_to_tip']} min{lag}", t)
    if moved and not kept:
        log(f"{len(moved)} change(s), none that can move a price tonight", t)
    return {"ran": True, "fresh": fresh, "listed": len(current), "changes": len(moved),
            "events": len(kept), "skipped": len(skipped)}


def status() -> None:
    st = load_state()
    if st:
        print(f"last ESPN answer: {_iso(st['fetched_at'])}, {len(st.get('players') or {})} players listed")
    else:
        print("no ESPN answer recorded yet")
    ev = _read_jsonl(EVENTS)
    sk = _read_jsonl(SKIPPED)
    by = {}
    for r in ev:
        by[r["kind"]] = by.get(r["kind"], 0) + 1
    print(f"events: {len(ev)} " + (f"({', '.join(f'{k} {v}' for k, v in sorted(by.items()))})" if by else ""))
    reasons = {}
    for r in sk:
        reasons[r.get("reason")] = reasons.get(r.get("reason"), 0) + 1
    print(f"skipped: {len(sk)}")
    for why, n in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {n:4}  {why}")
    lags = sorted(r["lag_min"] for r in ev if r.get("lag_min") is not None)
    if lags:
        print(f"minutes from ESPN's stamp to seen: median {lags[len(lags) // 2]}")
    for r in ev[-10:]:
        print(f"  {r['seen_iso']}  {r['kind']:9} {r['player']}: {r['from_status']} -> {r['to_status']} "
              f"({r['fixture']}, tip in {r['mins_to_tip']} min)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "status"])
    ap.add_argument("--force", action="store_true", help="run outside the NBA window")
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        status()
        return 0
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lockf:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("news watch: another run is going, skipped")
            return 0
        try:
            sys.path.insert(0, str(ROOT))
            res = tick(force=a.force, dry=a.dry_run)
        except Exception as exc:  # noqa: BLE001  never fatal
            log(f"failed ({type(exc).__name__}: {exc})")
            return 0
    if not res.get("ran"):
        print(f"news watch: not run, {res.get('why')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
