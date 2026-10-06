"""Line-ups for the report's Line-ups tab: predicted first, confirmed later.

SofaScore serves one endpoint for both. Days out it is a predicted XI
(confirmed: false); about an hour before kick-off it flips to the real one
(confirmed: true). attach() keeps the first predicted XI it ever saw next to
the confirmed one, so the page can show both and you can see who dropped out.

Formation plus the order SofaScore lists players in (goalkeeper, then each
line from right to left) is enough to place everyone on a pitch and pair each
player with the man directly opposite him.
"""
from __future__ import annotations

import sofascore_api as api


def fetch(event_id: int, max_age_hours: float = 1.0) -> dict | None:
    data = api.get_json(f"event/{event_id}/lineups", max_age_hours=max_age_hours, verbose=False)
    if not data or not (data.get("home") or {}).get("players"):
        return None
    out = {"confirmed": bool(data.get("confirmed"))}
    for side in ("home", "away"):
        block = data.get(side) or {}
        out[side] = {
            "formation": block.get("formation") or "",
            "xi": [{"name": (p.get("player") or {}).get("name"), "pos": p.get("position"),
                    "shirt": p.get("shirtNumber") or p.get("jerseyNumber")}
                   for p in block.get("players", []) if not p.get("substitute")],
            "bench": [(p.get("player") or {}).get("name")
                      for p in block.get("players", []) if p.get("substitute")],
            "missing": [((m.get("player") or {}).get("name"), m.get("reason"))
                        for m in block.get("missingPlayers", []) or []],
        }
    return out


def attach(entry: dict, max_age_hours: float = 1.0) -> bool:
    """Add or refresh entry["lineups"] = {"predicted": ..., "confirmed": ...}."""
    try:
        lu = fetch(entry["fixture"]["id"], max_age_hours)
    except Exception:
        return False
    if not lu:
        return False
    store = entry.setdefault("lineups", {})
    if lu["confirmed"]:
        store["confirmed"] = lu
    else:
        store["predicted"] = lu
    return True
