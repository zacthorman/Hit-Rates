#!/usr/bin/env python3
"""Per-player card history, fetched slowly across a whole day.

    caffeinate -i python cards_backfill.py          # the slow run, spread over 24 hours
    python cards_backfill.py --dry                  # how many matches it would fetch
    python cards_backfill.py --status               # progress, and any lockout

SofaScore's player box scores carry no cards, which is why the To be booked
model works from fouls. The cards are in each match's incidents
(event/{id}/incidents): who was booked, in which minute. This fetches those
for every recent match of every football side in the current reports, so a
player's own card record can replace the fouls estimate.

It is a lot of one-off requests, so it is deliberately the slowest thing in
the project:
  - spread evenly across HOURS (default 24), never closer than MIN_GAP
    seconds apart, with jitter, one at a time;
  - newest matches of the soonest fixtures first, so a run cut short still
    covers what matters this week;
  - every reply cached for good in cache/ (a finished match never changes),
    so it is resumable and nothing is ever fetched twice;
  - the FIRST refusal (403, 429, a challenge, a dead connection) stops it and
    writes a 24 hour lockout, no retries. Same rule as canary.py: repeated
    refusals are how a short block becomes a long one;
  - `touch .cards_off` stops it at the next request.

The daily update keeps running as normal alongside it; at one request a
minute or so this adds little to SofaScore's load from this machine.
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

ROOT = Path(__file__).parent
STATE = ROOT / "cache" / "cards_backfill_state.json"
OFF = ROOT / ".cards_off"
HOURS = 24
MIN_GAP = 20          # seconds, at least
PER_TEAM = 20         # recent matches per side
LOCKOUT_HOURS = 24


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1))


def todo_list() -> list[int]:
    """Match ids still to fetch, most useful first."""
    import make_index
    import sofascore_api as api
    fixtures = []
    for path in (ROOT / "reports").glob("*.html"):
        if path.name.startswith("pick-"):
            continue
        for entry, meta in make_index.read_entries(path):
            if (entry.get("fixture") or {}).get("sport", "football") != "football":
                continue
            fixtures.append((meta.get("kickoff") or 0, entry))
    now = time.time()
    fixtures.sort(key=lambda x: (x[0] < now, x[0]))   # upcoming first, soonest first
    seen, out = set(), []
    for _, entry in fixtures:
        for side in entry.get("records") or []:
            recent = sorted(side, key=lambda r: r.get("date") or "", reverse=True)[:PER_TEAM]
            for r in recent:
                mid = r.get("id")
                if not mid or mid in seen:
                    continue
                seen.add(mid)
                if api._cache_file(f"event/{mid}/incidents").exists():
                    continue
                out.append(mid)
    return out


def fetch_one(mid: int) -> str:
    """'ok', 'none' (genuinely no incidents) or raises on a refusal."""
    import sofascore_api as api
    path = f"event/{mid}/incidents"
    url = f"{api.BASE}/{path}"
    r = api._get_session().get(url, timeout=30)
    if r.status_code == 404:
        # Cache the absence too, so it is never asked again.
        api._cache_file(path).write_text(json.dumps({"incidents": [], "missing": True}))
        return "none"
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError("reply was not JSON (a challenge page?)")
    if isinstance(data, dict) and set(data) == {"error"}:
        code = (data.get("error") or {}).get("code")
        if code == 404:
            api._cache_file(path).write_text(json.dumps({"incidents": [], "missing": True}))
            return "none"
        raise RuntimeError(f"error body {code}")
    api._cache_file(path).write_text(json.dumps(data))
    return "ok"


def run(hours: float) -> int:
    st = load_state()
    if st.get("lockoutUntil", 0) > time.time():
        left = (st["lockoutUntil"] - time.time()) / 3600
        print(f"locked out for {left:.1f}h more ({st.get('lockoutWhy')}). Not fetching.")
        return 0
    todo = todo_list()
    if not todo:
        print("nothing to fetch: every recent match already has its incidents cached")
        return 0
    gap = max(MIN_GAP, hours * 3600 / len(todo))
    print(f"{len(todo)} matches to fetch, about one every {gap:.0f}s, "
          f"done in about {len(todo) * gap / 3600:.1f}h. Ctrl-C or `touch .cards_off` to stop.")
    done = 0
    for i, mid in enumerate(todo, 1):
        if OFF.exists():
            print("stopped: .cards_off")
            break
        try:
            res = fetch_one(mid)
        except Exception as exc:
            st["lockoutUntil"] = time.time() + LOCKOUT_HOURS * 3600
            st["lockoutWhy"] = f"{type(exc).__name__}: {exc}"
            save_state(st)
            print(f"refused on match {mid} ({exc}). Stopping, locked out for {LOCKOUT_HOURS}h. "
                  f"{done} fetched this run; everything fetched is kept.")
            return 1
        done += 1
        st["fetched"] = st.get("fetched", 0) + 1
        st["last"] = time.time()
        save_state(st)
        if i % 25 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)} ({res}) {time.strftime('%H:%M')}")
        time.sleep(gap * random.uniform(0.75, 1.25))
    print(f"finished: {done} matches fetched")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--hours", type=float, default=HOURS)
    args = ap.parse_args()
    if args.status:
        st = load_state()
        print(json.dumps(st, indent=1))
        print("still to fetch:", len(todo_list()))
        return 0
    if args.dry:
        n = len(todo_list())
        gap = max(MIN_GAP, args.hours * 3600 / max(n, 1))
        print(f"{n} matches to fetch; at one every {gap:.0f}s that is {n * gap / 3600:.1f}h")
        return 0
    return run(args.hours)


if __name__ == "__main__":
    raise SystemExit(main())
