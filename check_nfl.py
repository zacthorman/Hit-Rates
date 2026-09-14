"""What SofaScore knows about the NFL, in about ten requests.

    SOFA_DELAY_MIN=4 SOFA_DELAY_MAX=8 .venv/bin/python check_nfl.py

Nothing here is a build. It answers the four questions that have to be settled
before NFL support can be written at all, and it answers them cheaply:

    1. Is there an NFL competition, and what is its uniqueTournament id?
    2. Which seasons exist, and what is last season's id?
    3. What does a finished game's team statistics block actually contain --
       the real stat names, not what I would guess them to be.
    4. What does the lineups block contain per player?

Three and four are the ones that matter. markets.py lists the soccer stats
worth pricing by their exact SofaScore names, and the equivalent NFL list
cannot be written from memory: guess "Passing yards" when the feed says
"Passing Yards" or "passingYards" and every row is silently dropped, which is
the same class of failure as the LaLiga one in tournament_id_for.

Everything goes through sofascore_api, so the pacing, the cache and the
five-strikes circuit breaker all apply. Run it with the delays raised.
"""

from __future__ import annotations

import json
import sys

import sofascore_api as api


def show(label, data, limit=900):
    text = json.dumps(data, indent=2)[:limit] if data else repr(data)
    print(f"\n--- {label} ---\n{text}")


def main() -> None:
    print(f"pacing: {api.MIN_DELAY} to {api.MAX_DELAY}s between fetches\n")

    # 1. Find it. The search endpoint is the honest way in: hardcoding an id
    #    read off a forum is how you end up building a season of reports for
    #    the wrong competition.
    found = api.get_json("search/all?q=NFL", max_age_hours=168)
    candidates = []
    for hit in (found or {}).get("results", []):
        entity = hit.get("entity", {})
        sport = (entity.get("category", {}) or {}).get("sport", {}) or {}
        if hit.get("type") == "uniqueTournament":
            candidates.append((entity.get("id"), entity.get("name"),
                               sport.get("name"), entity.get("userCount")))
    print("uniqueTournament hits for 'NFL':")
    for c in candidates:
        print(f"   id={c[0]:<8} {c[1]!r:34} sport={c[2]!r:20} users={c[3]}")
    if not candidates:
        print("   none. Try q=National Football League, or the sport listing.")
        sys.exit(1)

    tid = candidates[0][0]
    print(f"\nusing uniqueTournament {tid}\n")

    # 2. Seasons.
    seasons = api.get_json(f"unique-tournament/{tid}/seasons", max_age_hours=168)
    rows = (seasons or {}).get("seasons", [])[:4]
    print("seasons, newest first:")
    for s in rows:
        print(f"   id={s.get('id'):<8} {s.get('name')!r}  year={s.get('year')!r}")
    if len(rows) < 2:
        print("   need at least two to read last season")
        sys.exit(1)
    last_season = rows[1]["id"]

    # 3. Do standings give a team list? tournament_team_ids depends on this,
    #    and a conference/division split may mean several blocks rather than
    #    the single table soccer returns.
    standings = api.get_json(
        f"unique-tournament/{tid}/season/{last_season}/standings/total",
        max_age_hours=168)
    blocks = (standings or {}).get("standings", [])
    print(f"\nstandings blocks last season: {len(blocks)}")
    teams = []
    for b in blocks:
        rows_ = b.get("rows", [])
        print(f"   {b.get('name')!r:28} type={b.get('type')!r:10} {len(rows_)} rows")
        for r in rows_:
            t = r.get("team", {})
            if t.get("id"):
                teams.append((t["id"], t.get("name")))
    note = ""
    if len(blocks) > 1:
        note = ("   <-- several blocks. tournament_table() breaks after the "
                "first one, so it would see a single division and the tier map "
                "would call every other team bottom.")
    print(f"   {len(teams)} teams total")
    if note:
        print(note)
    if not teams:
        sys.exit("no teams, so tournament_team_ids would return nothing")

    # 4. One team's finished games, then the two blocks that decide everything.
    team_id, team_name = teams[0]
    print(f"\nreading {team_name} (id {team_id})")
    events = (api.get_json(f"team/{team_id}/events/last/0", max_age_hours=6) or {}).get("events", [])
    finished = [e for e in events if e.get("status", {}).get("type") == "finished"]
    print(f"   {len(finished)} finished game(s) on page 0")
    if not finished:
        sys.exit("no finished games to inspect")

    event = finished[-1]
    eid = event["id"]
    print(f"   sampling event {eid}: "
          f"{event.get('homeTeam', {}).get('name')} v {event.get('awayTeam', {}).get('name')}"
          f"  [{event.get('tournament', {}).get('name')}]")

    stats = api.get_json(f"event/{eid}/statistics")
    periods = [p.get("period") for p in (stats or {}).get("statistics", [])]
    print(f"\nTEAM STATISTICS  periods: {periods}")
    for block in (stats or {}).get("statistics", []):
        if block.get("period") != "ALL":
            continue
        for group in block.get("groups", []):
            print(f"   group {group.get('groupName')!r}")
            for item in group.get("statisticsItems", []):
                print(f"      {item.get('name')!r:34} home={item.get('home')!r:>10} "
                      f"away={item.get('away')!r:>10}")

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
        show("one player, whole record", players[0], 700)


if __name__ == "__main__":
    main()
