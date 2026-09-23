"""What SofaScore knows about a competition, in about ten requests.

    SOFA_DELAY_MIN=4 SOFA_DELAY_MAX=8 .venv/bin/python check_sport.py NBA

The generalised version of check_nfl.py, which existed because NFL support
could not be written from memory. Neither can basketball, or anything else:
markets.py lists every bettable stat by its exact SofaScore name, and a single
character wrong -- "Rebounds" where the feed says "Total rebounds" -- silently
drops the row rather than failing loudly.

So this guesses nothing. It answers the questions that have to be settled
before a sport can be added at all, and it answers them from the feed:

    1. Is the competition there, what is its uniqueTournament id, and what
       sport slug does the feed give it? That slug is what run.py writes into
       every fixture and what markets.py keys off, so it has to be read, not
       assumed.
    2. Which seasons exist, and what is last season's id?
    3. Does the standings endpoint give a usable team list, and in how many
       blocks? Conferences and divisions arrive as separate tables, which is
       what broke the NFL team list until tournament_table started taking the
       longest one instead of the first.
    4. What does a finished game's team statistics block actually contain --
       the real stat names, and crucially which PERIODS. American football
       returns ALL and nothing else, so no first-quarter market is possible;
       a sport that returns quarters can carry them.
    5. What does the lineups block contain per player?

Nothing here builds a report and nothing is written outside cache/. Everything
goes through sofascore_api, so the pacing, the cache and the five-strikes
circuit breaker all apply. Run it with the delays raised.
"""

from __future__ import annotations

import json
import sys

import sofascore_api as api


def main() -> None:
    query = " ".join(sys.argv[1:]).strip() or "NBA"
    print(f"looking for {query!r}, pacing {api.MIN_DELAY} to {api.MAX_DELAY}s\n")

    found = api.get_json(f"search/all?q={query.replace(' ', '%20')}", max_age_hours=168)
    candidates = []
    for hit in (found or {}).get("results", []):
        entity = hit.get("entity", {})
        category = entity.get("category") or {}
        sport = category.get("sport") or {}
        if hit.get("type") == "uniqueTournament":
            candidates.append((entity.get("id"), entity.get("name"),
                               sport.get("slug"), entity.get("userCount")))
    print(f"uniqueTournament hits for {query!r}:")
    for cid, name, slug, users in candidates:
        print(f"   id={cid!s:<8} {name!r:34} sport-slug={slug!r:16} users={users}")
    if not candidates:
        print("   none. Try the full name, or a club in it.")
        sys.exit(1)

    candidates.sort(key=lambda c: -(c[3] or 0))
    tid, tname, slug, _ = candidates[0]
    print(f"\nusing uniqueTournament {tid} ({tname!r}), sport slug {slug!r}")
    print("   ^ that slug is the key markets.BY_SPORT needs an entry for\n")

    seasons = api.get_json(f"unique-tournament/{tid}/seasons", max_age_hours=168)
    rows = (seasons or {}).get("seasons", [])[:4]
    print("seasons, newest first:")
    for s in rows:
        print(f"   id={s.get('id')!s:<8} {s.get('name')!r}  year={s.get('year')!r}")
    if not rows:
        sys.exit("no seasons, so nothing can be built")
    last_season = rows[1]["id"] if len(rows) > 1 else rows[0]["id"]

    standings = api.get_json(
        f"unique-tournament/{tid}/season/{last_season}/standings/total",
        max_age_hours=168)
    blocks = (standings or {}).get("standings", [])
    print(f"\nstandings blocks last season: {len(blocks)}")
    teams = []
    for b in blocks:
        brows = b.get("rows", [])
        print(f"   {str(b.get('name'))!r:30} type={b.get('type')!r:10} {len(brows)} rows")
        for r in brows:
            t = r.get("team") or {}
            if t.get("id"):
                teams.append((t["id"], t.get("name")))
    unique = {t[0]: t[1] for t in teams}
    print(f"   {len(teams)} rows, {len(unique)} distinct teams")
    if len(blocks) > 1:
        print("   several blocks: tournament_table takes the longest, and")
        print("   tournament_team_ids de-duplicates, so both are already handled.")

    if not unique:
        # A knockout has no table. Darts, tennis and every cup are brackets,
        # and standings come back empty -- which is not a failure, it is the
        # shape of the competition. The interesting half of this probe is the
        # stat keys, so fall back to the season's own fixtures and carry on
        # rather than exiting before the part that matters.
        #
        # It does mean run.py's --league path will not work for that sport,
        # because that path starts from the team list. --teams with ids, or
        # --search by name, is the way in instead.
        print("\n   no standings table: this is a knockout, so --league will not")
        print("   work for it. Reading the season's fixtures instead.")
        rounds = api.get_json(
            f"unique-tournament/{tid}/season/{last_season}/events/last/0",
            max_age_hours=24) or {}
        for event in (rounds.get("events") or []):
            for side in ("homeTeam", "awayTeam"):
                t = event.get(side) or {}
                if t.get("id"):
                    unique[t["id"]] = t.get("name")
        print(f"   {len(unique)} competitor(s) found in recent fixtures")

    if not unique:
        sys.exit("no competitors found by either route")

    team_id, team_name = next(iter(unique.items()))
    print(f"\nreading {team_name} (id {team_id})")
    events = (api.get_json(f"team/{team_id}/events/last/0", max_age_hours=6) or {}).get("events", [])
    finished = [e for e in events if (e.get("status") or {}).get("type") == "finished"]
    print(f"   {len(finished)} finished game(s) on page 0")
    if not finished:
        sys.exit("no finished games to inspect")

    event = finished[-1]
    eid = event["id"]
    home = (event.get("homeTeam") or {}).get("name")
    away = (event.get("awayTeam") or {}).get("name")
    comp = (event.get("tournament") or {}).get("name")
    print(f"   sampling event {eid}: {home} v {away}  [{comp}]")

    stats = api.get_json(f"event/{eid}/statistics")
    periods = [p.get("period") for p in (stats or {}).get("statistics", [])]
    print(f"\nTEAM STATISTICS  periods: {periods}")
    if periods and periods != ["ALL"]:
        print("   more than ALL, so period-scoped markets are possible here")
    for block in (stats or {}).get("statistics", []):
        if block.get("period") != "ALL":
            continue
        for group in block.get("groups", []):
            print(f"   group {group.get('groupName')!r}")
            for item in group.get("statisticsItems", []):
                name = item.get("name")
                print(f"      {name!r:34} home={item.get('home')!r:>10} away={item.get('away')!r:>10}")

    lineups = api.get_json(f"event/{eid}/lineups")
    if not lineups:
        print("\nPLAYER STATISTICS: no lineups endpoint for this sport")
        return
    players = (lineups.get("home") or {}).get("players") or []
    print(f"\nPLAYER STATISTICS  {len(players)} home players")
    seen = {}
    for p in players:
        for k, v in (p.get("statistics") or {}).items():
            seen.setdefault(k, v)
    for k in sorted(seen):
        print(f"   {k!r:36} e.g. {seen[k]!r}")
    if players:
        first = players[0]
        who = (first.get("player") or {}).get("name")
        print(f"\none whole record, {who}:")
        print(json.dumps(first, indent=2)[:900])


if __name__ == "__main__":
    main()
