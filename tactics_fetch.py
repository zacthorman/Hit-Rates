#!/usr/bin/env python3
"""
The tactical data behind "How the game will go", fetched gently and kept.

    .venv/bin/python tactics_fetch.py                  # the daily run (update.py calls it)
    .venv/bin/python tactics_fetch.py --budget 50 -v   # a small test run, printing each request
    .venv/bin/python tactics_fetch.py --status         # how much is held, what is left

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
matches never change, so nothing is refetched. Never fatal.
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


def cache_path(eid: int, ep: str) -> Path:
    return CACHE / f"event_{eid}_{ep}.json"


def finished_events() -> list[dict]:
    import strength
    return strength.load_events(CACHE)


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
    try:
        return {tuple(x) for x in json.loads(MISSING.read_text())}
    except (OSError, ValueError):
        return set()


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
                m = re.search(r"teamsData\s*=\s*JSON\.parse\('([^']+)'\)", html)
                if not m:
                    if verbose:
                        print(f"  understat {league} {season}: no teamsData")
                    continue
                data = json.loads(m.group(1).encode().decode("unicode_escape"))
                out.write_text(json.dumps(data))
                n += 1
                time.sleep(5)
            except Exception as exc:
                print(f"  understat {league} {season}: {exc}")
    return n


def status() -> None:
    missing = load_missing()
    todo = queue(finished_events(), missing)
    held = {ep: len(glob.glob(str(CACHE / f"event_*_{ep}.json"))) for ep in ENDPOINTS}
    print("held:", held, "| no data:", len(missing), "| still to fetch:", len(todo))
    print("understat files:", len(glob.glob(str(CACHE / "understat_*.json"))))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=int, default=1500)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    if args.status:
        status()
        return 0
    try:
        r = fetch_sofascore(args.budget, args.verbose)
        print(f"  tactics: {r['fetched']} fetched, {r['none']} with no data, {r['left']} left")
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
        except Exception as exc:
            print(f"  understat: not fetched ({exc})")
    else:
        print("  understat: off (robots rules disallow automated access; touch .understat_on to enable)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
