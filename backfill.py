#!/usr/bin/env python3
"""Fill the cache with whole seasons of NBA and NFL box scores, for the backtest.

    SOFA_DELAY_MIN=2 SOFA_DELAY_MAX=4 python3 backfill.py        # everything below
    python3 backfill.py --dry                                    # just count what is missing

What it fetches, per finished game: the team box score (event/{id}/statistics)
and the player box scores (event/{id}/lineups). Nothing else. The games are
the ones already listed in the cached team schedules, so no listing requests.

  NBA 2025-26 (regular season and playoffs)   about 800 games missing
  NFL 2023-24 and 2024-25                     about 380 games missing

Resumable: anything already cached is skipped without a request, so stopping
it (Ctrl-C) and starting again carries on where it was. It stops by itself if
SofaScore starts refusing (sofascore_api's circuit breaker). Polite by
default: 2 to 4 seconds between requests, set by SOFA_DELAY_MIN/MAX.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import time

os.environ.setdefault("SOFA_DELAY_MIN", "2")
os.environ.setdefault("SOFA_DELAY_MAX", "4")
import sofascore_api as api  # noqa: E402

WANT = {  # tournament id -> seasons (first year) wanted
    132: ("NBA", {2025}),
    9464: ("NFL", {2023, 2024}),
}


def season_of(ts: int, nba: bool) -> int:
    d = datetime.datetime.utcfromtimestamp(ts)
    return d.year if d.month >= (9 if nba else 8) else d.year - 1


def games(tid: int) -> dict[int, dict]:
    """Finished games in the wanted seasons, from the cached team schedules."""
    name, seasons = WANT[tid]
    real = api.get_json
    api.get_json = lambda path, *a, **k: (__import__("json").loads(api._cache_file(path).read_text())
                                         if api._cache_file(path).exists() else None)
    try:
        out = {}
        for t in api.tournament_team_ids(tid):
            for k in range(12):
                d = api.get_json(f"team/{t}/events/last/{k}")
                if not d:
                    break
                for e in d.get("events", []):
                    if ((e.get("tournament") or {}).get("uniqueTournament") or {}).get("id") != tid:
                        continue
                    if (e.get("status") or {}).get("type") != "finished":
                        continue
                    if season_of(e["startTimestamp"], tid == 132) in seasons:
                        out[e["id"]] = e
        return out
    finally:
        api.get_json = real


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    todo = []
    for tid in WANT:
        evs = games(tid)
        miss = [(e["startTimestamp"], tid, i) for i, e in evs.items()
                if not api._cache_file(f"event/{i}/statistics").exists()
                or not api._cache_file(f"event/{i}/lineups").exists()]
        print(f"{WANT[tid][0]}: {len(evs)} games, {len(miss)} missing something")
        todo += miss
    todo.sort()
    if a.dry or not todo:
        return 0
    print(f"fetching {len(todo)} games, about {len(todo) * 2 * 3.5 / 3600:.1f} hours. Ctrl-C is safe.")
    start = time.time()
    for n, (_, tid, i) in enumerate(todo, 1):
        api.event_statistics(i)
        api.event_lineups(i)
        if api.last_transport_error():
            print(f"\nstopping: {api.last_transport_error()}. Run again later to carry on.")
            return 1
        if n % 10 == 0 or n == len(todo):
            left = (time.time() - start) / n * (len(todo) - n) / 60
            print(f"  {n}/{len(todo)} games, about {left:.0f} min left", end="\r", flush=True)
    print(f"\ndone: {len(todo)} games in {(time.time() - start) / 60:.0f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
