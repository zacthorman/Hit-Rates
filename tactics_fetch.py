#!/usr/bin/env python3
"""
The tactical data behind "How the game will go", fetched gently and kept.

    .venv/bin/python tactics_fetch.py                  # the daily run (update.py calls it)
    .venv/bin/python tactics_fetch.py --budget 50 -v   # a small test run, printing each request
    .venv/bin/python tactics_fetch.py --status         # how much is held, what is left
    .venv/bin/python tactics_fetch.py --check          # run every parser over the cached files

Per finished football match, four SofaScore endpoints the site did not keep:

  average-positions   every player's average spot: the shape the team really
                      played (line height, width, gaps between lines, a
                      full-back pushed on, a midfielder dropping in)
  shotmap             every shot with its situation (fast break, set piece,
                      open play) and xG: rest defence, counter threat
  graph               attack momentum minute by minute
  incidents           goals, cards and substitutions with their minutes: who
                      was leading or chasing, and for how long

and, only if .understat_on exists (off by default: its robots rules disallow
automated access), Understat's league pages for the six leagues it covers,
which carry PPDA (opposition passes per defensive action, the standard
pressing measure) and deep completions for every match.

Gentle by design, through sofascore_api.get_json, so the same pacing, block
detection and FlareSolverr fallback apply. A daily budget of requests
(--budget, default 1500). Matches for teams with a fixture in the reports
come first (their last 15), then everything else newest first. A 404 is
remembered in cache/tactics_missing.json and never asked again. Finished
matches never change, so nothing is refetched. Network trouble is never
fatal; a response in a shape the checks below do not know stops the run
with "SHAPE ERROR" and exit code 2, and the file is not kept.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"
MISSING = CACHE / "tactics_missing.json"
ENDPOINTS = ("average-positions", "shotmap", "graph", "incidents")
UNDERSTAT_LEAGUES = ("EPL", "La_liga", "Bundesliga", "Serie_A", "Ligue_1", "RFPL")
PRIORITY_RECENT = 15
NUM = (int, float)


class ShapeError(ValueError):
    """A response is not the shape this file knows. Raised, never skipped."""


def _need(cond, where, what):
    if not cond:
        raise ShapeError(f"{where}: {what}")


def _list_of(d, key, where):
    _need(isinstance(d, dict), where, f"expected an object, got {type(d).__name__}")
    _need(isinstance(d.get(key), list), where, f"no {key!r} list (keys {sorted(d)[:8]})")
    for i, x in enumerate(d[key]):
        _need(isinstance(x, dict), where, f"{key}[{i}] is {type(x).__name__}, not an object")
    return d[key]


def check_average_positions(d, where="average-positions") -> dict:
    out = {}
    for side in ("home", "away"):
        for i, p in enumerate(_list_of(d, side, where)):
            _need(isinstance(p.get("player"), dict), where, f"{side}[{i}] has no player")
            _need(isinstance(p.get("averageX"), NUM) and isinstance(p.get("averageY"), NUM),
                  where, f"{side}[{i}] has no numeric averageX/averageY")
        out[side] = len(d[side])
    return out


def check_shotmap(d, where="shotmap") -> dict:
    shots = _list_of(d, "shotmap", where)
    for i, x in enumerate(shots):
        _need(isinstance(x.get("isHome"), bool), where, f"shotmap[{i}] has no isHome")
        for k in ("shotType", "situation"):
            _need(isinstance(x.get(k), str), where, f"shotmap[{i}] has no {k}")
        _need(x.get("xg") is None or isinstance(x["xg"], NUM), where, f"shotmap[{i}] xg is not a number")
    return {"shots": len(shots), "home": sum(x["isHome"] for x in shots)}


def check_graph(d, where="graph") -> dict:
    pts = _list_of(d, "graphPoints", where)
    for i, x in enumerate(pts):
        _need(isinstance(x.get("minute"), NUM) and isinstance(x.get("value"), NUM),
              where, f"graphPoints[{i}] has no numeric minute/value")
    return {"points": len(pts)}


def check_incidents(d, where="incidents") -> dict:
    inc = _list_of(d, "incidents", where)
    for i, x in enumerate(inc):
        _need(isinstance(x.get("incidentType"), str), where, f"incidents[{i}] has no incidentType")
    # cards_backfill.py writes {"incidents": [], "missing": True} for a match
    # SofaScore has nothing for: a known shape, not a fault.
    return {"incidents": len(inc), "missing": bool(d.get("missing"))}


CHECKS = {"average-positions": check_average_positions, "shotmap": check_shotmap,
          "graph": check_graph, "incidents": check_incidents}


def check_understat_teams(data, where="teamsData") -> dict:
    """Understat's teamsData: {team id: {id, title, history: [one match each]}},
    each match carrying ppda {att, def}, deep and xG. Returns {title: matches}."""
    _need(isinstance(data, dict) and data, where, f"expected a non-empty object, got {type(data).__name__}")
    out = {}
    for tid, t in data.items():
        w = f"{where} team {tid}"
        _need(isinstance(t, dict) and isinstance(t.get("title"), str), w, "no title")
        _need(isinstance(t.get("history"), list), w, "no history list")
        for i, m in enumerate(t["history"]):
            _need(isinstance(m, dict), w, f"history[{i}] is not an object")
            pp = m.get("ppda")
            _need(isinstance(pp, dict) and isinstance(pp.get("att"), NUM) and isinstance(pp.get("def"), NUM),
                  w, f"history[{i}] has no ppda att/def")
            for k in ("deep", "xG", "xGA"):
                _need(k in m, w, f"history[{i}] has no {k}")
        out[t["title"]] = len(t["history"])
    return out


def parse_understat_league(html: str, where="understat") -> dict:
    """teamsData out of an Understat league page, checked. Raises ShapeError if
    the page no longer carries it (Understat has moved data behind its own
    XHR calls before), rather than skipping the league quietly."""
    m = re.search(r"teamsData\s*=\s*JSON\.parse\('([^']+)'\)", html)
    _need(m, where, "no teamsData = JSON.parse('...') in the page")
    # The literal is \xNN-escaped; backslashreplace keeps any raw non-Latin-1
    # character intact through unicode_escape instead of turning it to mojibake.
    raw = m.group(1).encode("latin-1", "backslashreplace").decode("unicode_escape")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ShapeError(f"{where}: teamsData is not JSON ({exc})") from exc
    check_understat_teams(data, where)
    return data


def cache_path(eid: int, ep: str) -> Path:
    return CACHE / f"event_{eid}_{ep}.json"


def finished_events() -> list[dict]:
    import strength
    ev = strength.load_events(CACHE)
    n = len(glob.glob(str(CACHE / "team_*_events_last_*.json")))
    if n and not ev:
        raise ShapeError(f"{CACHE}: {n} team event files and strength.load_events found no finished match")
    return ev


def upcoming_teams() -> set:
    teams = set()
    try:
        import make_index
        for path in (ROOT / "reports").glob("*.html"):
            if path.name.startswith("pick-"):
                continue
            for entry, meta in make_index.read_entries(path):
                if ((entry.get("fixture") or {}).get("sport") or "football") != "football":
                    continue
                if meta["kickoff"] < time.time() - 3 * 3600:
                    continue
                for t in entry.get("teams") or []:
                    teams.add(t.get("id"))
    except Exception:
        pass
    return teams


def queue(events: list[dict], missing: set) -> list[tuple[int, str]]:
    have_stats = {int(m.group(1)) for m in
                  (re.match(r".*event_(\d+)_statistics\.json$", p) for p in glob.glob(str(CACHE / "event_*_statistics.json")))
                  if m}
    events = [e for e in events if e["id"] in have_stats]
    teams = upcoming_teams()
    by_team: dict = {}
    for e in sorted(events, key=lambda e: -e["ts"]):
        for t in (e["home"], e["away"]):
            by_team.setdefault(t, []).append(e)
    first, seen = [], set()
    for t in teams:
        for e in by_team.get(t, [])[:PRIORITY_RECENT]:
            if e["id"] not in seen:
                first.append(e)
                seen.add(e["id"])
    rest = [e for e in sorted(events, key=lambda e: -e["ts"]) if e["id"] not in seen]
    out = []
    for e in first + rest:
        for ep in ENDPOINTS:
            if (e["id"], ep) in missing or cache_path(e["id"], ep).exists():
                continue
            out.append((e["id"], ep))
    return out


def load_missing() -> set:
    """(event id, endpoint) pairs SofaScore had nothing for. A broken file is
    raised, not read as empty: empty would refetch every 404 and then
    overwrite the record."""
    if not MISSING.exists():
        return set()
    try:
        d = json.loads(MISSING.read_text())
    except ValueError as exc:
        raise ShapeError(f"{MISSING}: not JSON ({exc})") from exc
    _need(isinstance(d, list) and all(isinstance(x, list) and len(x) == 2 and isinstance(x[0], int)
                                      and x[1] in ENDPOINTS for x in d), MISSING, "expected [[event id, endpoint], ...]")
    return {tuple(x) for x in d}


def save_missing(missing: set) -> None:
    MISSING.write_text(json.dumps(sorted(list(m) for m in missing)))


def fetch_sofascore(budget: int, verbose: bool) -> dict:
    import sofascore_api as S
    missing = load_missing()
    todo = queue(finished_events(), missing)
    got = miss = 0
    for eid, ep in todo[:budget]:
        data = S.get_json(f"event/{eid}/{ep}", max_age_hours=None, verbose=verbose)
        if data is None:
            # get_json returns None on any non-200. A block (403/429) stops the
            # run inside get_json's own logic; a plain 404 means SofaScore has
            # nothing for this match, so remember it.
            err = (S.last_transport_error() or "") if hasattr(S, "last_transport_error") else ""
            if "403" in err or "429" in err or "block" in err.lower():
                print(f"  tactics: SofaScore refused ({err}), stopping for today")
                break
            missing.add((eid, ep))
            miss += 1
        else:
            try:
                CHECKS[ep](data, f"event {eid} {ep}")
            except ShapeError:
                # get_json has already cached it; do not keep a file nothing can read.
                cache_path(eid, ep).unlink(missing_ok=True)
                save_missing(missing)
                raise
            got += 1
    save_missing(missing)
    return {"fetched": got, "none": miss, "left": max(0, len(todo) - budget)}


def fetch_understat(verbose: bool) -> int:
    """Understat league pages for the current and previous season, at most once a day each."""
    n = 0
    year = time.gmtime().tm_year
    month = time.gmtime().tm_mon
    current = year if month >= 7 else year - 1
    for league in UNDERSTAT_LEAGUES:
        for season in (current, current - 1):
            out = CACHE / f"understat_{league}_{season}.json"
            if out.exists() and (season != current or time.time() - out.stat().st_mtime < 20 * 3600):
                continue
            url = f"https://understat.com/league/{league}/{season}"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh) hit-rates/1.0"})
                html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
            except Exception as exc:
                print(f"  understat {league} {season}: {exc}")
                continue
            data = parse_understat_league(html, f"understat {league} {season}")
            out.write_text(json.dumps(data))
            n += 1
            time.sleep(5)
    return n


def status() -> None:
    missing = load_missing()
    todo = queue(finished_events(), missing)
    held = {ep: len(glob.glob(str(CACHE / f"event_*_{ep}.json"))) for ep in ENDPOINTS}
    print("held:", held, "| no data:", len(missing), "| still to fetch:", len(todo))
    print("understat files:", len(glob.glob(str(CACHE / "understat_*.json"))))


def check_cache() -> dict:
    """Run every parser over every tactics file held. Raises on the first bad one."""
    n = {}
    for ep, fn in CHECKS.items():
        files = glob.glob(str(CACHE / f"event_*_{ep}.json"))
        for path in files:
            try:
                d = json.loads(Path(path).read_text())
            except ValueError as exc:
                raise ShapeError(f"{path}: not JSON ({exc})") from exc
            fn(d, path)
        n[ep] = len(files)
    files = glob.glob(str(CACHE / "understat_*.json"))
    for path in files:
        check_understat_teams(json.loads(Path(path).read_text()), path)
    n["understat"] = len(files)
    load_missing()
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=int, default=1500)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--check", action="store_true", help="parse every cached tactics file, fetch nothing")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    try:
        return _run(args)
    except ShapeError as exc:
        # Loud on purpose: a shape nobody has seen is a parser to fix, not a
        # quiet "0 fetched". update.py keeps going (it runs this allow_fail).
        print(f"  tactics: SHAPE ERROR, stopped: {exc}")
        return 2


def _run(args) -> int:
    if args.status:
        status()
        return 0
    if args.check:
        print("  tactics: cache parses cleanly:", check_cache())
        return 0
    try:
        r = fetch_sofascore(args.budget, args.verbose)
        print(f"  tactics: {r['fetched']} fetched, {r['none']} with no data, {r['left']} left")
    except ShapeError:
        raise
    except Exception as exc:
        print(f"  tactics: not fetched ({exc})")
    # Understat is off by default: on 22 October its robots rules disallowed
    # automated access to its league pages, so it is not fetched unless Zac
    # chooses to by creating an empty file .understat_on beside this script.
    # The pressing measure the models use (opponent passes per defensive
    # action) comes from SofaScore's own statistics in teamstyle.py anyway.
    if (ROOT / ".understat_on").exists():
        try:
            print(f"  understat: {fetch_understat(args.verbose)} league page(s) refreshed")
        except ShapeError:
            raise
        except Exception as exc:
            print(f"  understat: not fetched ({exc})")
    else:
        print("  understat: off (robots rules disallow automated access; touch .understat_on to enable)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
