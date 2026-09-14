"""Resolve NFL team names to SofaScore ids, and print the command to run.

    .venv/bin/python nfl_teams.py "Green Bay Packers" "Minnesota Vikings"

run.py --names goes through search_teams, which answers with soccer clubs and
found nothing for either of these. Rather than widen that and risk changing
how every football name resolves on a Saturday morning, this does the search
itself and filters on sport, which is the one thing the football path has no
reason to check.
"""

from __future__ import annotations

import sys

import sofascore_api as api

SPORT = "american football"


def find(name: str) -> list[tuple[int, str]]:
    data = api.get_json(f"search/all?q={name}&page=0", max_age_hours=24,
                        verbose=False) or {}
    out = []
    for hit in data.get("results", []):
        if hit.get("type") != "team":
            continue
        entity = hit.get("entity", {})
        sport = ((entity.get("sport") or {}).get("name")
                 or ((entity.get("category") or {}).get("sport") or {}).get("name")
                 or "")
        if sport.lower() != SPORT:
            continue
        out.append((entity.get("id"), entity.get("name")))
    return out


def main() -> None:
    names = sys.argv[1:]
    if not names:
        raise SystemExit(__doc__)

    ids = []
    for name in names:
        hits = find(name)
        if not hits:
            print(f"  {name!r}: nothing in American football")
            continue
        for tid, full in hits[:3]:
            print(f"  {name!r} -> id={tid} {full!r}")
        ids.append(str(hits[0][0]))

    if len(ids) != len(names):
        raise SystemExit("\nnot every name resolved, so no command printed")

    print("\nNow run:\n")
    print(f'  SOFA_DELAY_MIN=4 SOFA_DELAY_MAX=8 .venv/bin/python run.py \\\n'
          f'    --teams {",".join(ids)} --games 20 --players --h2h --no-open')


if __name__ == "__main__":
    main()
