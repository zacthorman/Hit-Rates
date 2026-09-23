"""Write the derived gridiron markets into a report already on disk.

A stop-gap, and deliberately a small one. The derived stats -- Anytime
Touchdown, Passing and Rushing Yards, Rushing and Receiving Yards -- are
computed in hitrates when a report is built, so a report built before they
existed does not carry them. Rebuilding is the proper fix and needs the
network. This needs nothing: every lineup the report was built from is still
in the cache, so the same function can be run over it again and the values
patched back in.

    python3 enrich_derived.py reports/kansas-city-chiefs-v-denver-broncos.html

Rewrites the file in place, then re-render with rerender.py or rebuild the
index. Running it twice is harmless.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import hitrates

CACHE = Path(__file__).parent / "cache"


def _lineup_stats(match_id):
    path = CACHE / f"event_{match_id}_lineups.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    out = {}
    for side in ("home", "away"):
        for player in (data.get(side) or {}).get("players", []) or []:
            pid = (player.get("player") or {}).get("id")
            if pid is not None:
                out[pid] = player.get("statistics") or {}
    return out


def enrich(path: Path) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"const ALL = (\{.*?\});\n", text, re.S)
    if not match:
        raise SystemExit(f"{path.name}: no payload found")
    payload = json.loads(match.group(1))

    cached: dict[int, dict] = {}
    touched = added = 0
    for entry in payload.get("fixtures", []):
        for side in entry.get("players") or []:
            for record in side:
                mid = record.get("match_id")
                if mid is None:
                    continue
                if mid not in cached:
                    cached[mid] = _lineup_stats(mid)
                raw = cached[mid].get(record.get("player_id"))
                if not raw:
                    continue
                derived = hitrates._gridiron_derived(raw)
                if derived:
                    record["stats"].update(derived)
                    touched += 1
                    added += len(derived)

    # The picker list and the suggested lines are settled at build time too,
    # so a patched payload with no entry in either carries stats the page
    # cannot offer. Rebuild both from what the records now hold.
    if touched:
        for entry in payload.get("fixtures", []):
            squads = entry.get("players") or []
            names = hitrates.player_stat_names(*squads, sport="american-football")
            entry["playerStats"] = names
            entry["playerLines"] = hitrates.suggest_player_lines(squads, names)

    if touched:
        path.write_text(
            text[:match.start(1)] + json.dumps(payload) + text[match.end(1):],
            encoding="utf-8",
        )
    return touched, added


if __name__ == "__main__":
    targets = [Path(a) for a in sys.argv[1:]] or sorted(Path("reports").glob("*.html"))
    for target in targets:
        touched, added = enrich(target)
        print(f"{target.name}: {touched} records, {added} values")
