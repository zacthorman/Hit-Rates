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


def _missing(block: dict) -> list:
    """[name, reason code, "missing" or "doubtful", description]. Older code
    reads only the first two."""
    return [[(m.get("player") or {}).get("name"), m.get("reason"), m.get("type"), m.get("description")]
            for m in block.get("missingPlayers", []) or []]


def fetch(event_id: int, max_age_hours: float = 1.0) -> dict | None:
    data = api.get_json(f"event/{event_id}/lineups", max_age_hours=max_age_hours, verbose=False)
    if not data:
        return None
    if not (data.get("home") or {}).get("players"):
        # No line-up yet. SofaScore still lists who is missing (the NBA does
        # this all day before tip-off), which is team news worth keeping.
        if not any((data.get(s) or {}).get("missingPlayers") for s in ("home", "away")):
            return None
        out = {"confirmed": False, "newsOnly": True}
        for side in ("home", "away"):
            out[side] = {"formation": "", "xi": [], "bench": [],
                         "missing": _missing(data.get(side) or {})}
        return out
    out = {"confirmed": bool(data.get("confirmed"))}
    import role
    for side in ("home", "away"):
        block = data.get(side) or {}
        starters = [p for p in block.get("players", []) if not p.get("substitute")]
        # Role from the formation and his slot (role.py, 8 Nov 2026); none
        # when the formation and the eleven do not add up.
        roles = role.roles(block.get("formation"), starters)
        out[side] = {
            "formation": block.get("formation") or "",
            "xi": [{"name": (p.get("player") or {}).get("name"), "pos": p.get("position"),
                    "shirt": p.get("shirtNumber") or p.get("jerseyNumber"),
                    **({"role": roles[(p.get("player") or {}).get("id")]}
                       if (p.get("player") or {}).get("id") in roles else {})}
                   for p in starters],
            "bench": [(p.get("player") or {}).get("name")
                      for p in block.get("players", []) if p.get("substitute")],
            "missing": _missing(block),
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
    if lu.get("newsOnly"):
        # kept apart, so the Line-ups tab never draws an empty XI
        store["news"] = lu
        return True
    if lu["confirmed"]:
        store["confirmed"] = lu
    else:
        store["predicted"] = lu
    _tag_roles(entry)
    return True


def _tag_roles(entry: dict) -> None:
    """Each football appearance row gets the role family he started in, from
    that match's cached line-up (role.py), so the page can show a line's
    record at today's role. Rows already tagged, subs and other sports are
    left alone; no request is made."""
    if ((entry.get("fixture") or {}).get("sport") or "football") != "football":
        return
    try:
        import role
        for side in entry.get("players") or []:
            for r in side:
                if "role" in r or not r.get("match_id") or r.get("started") is False:
                    continue
                got = role.match_roles(r["match_id"]).get(r.get("player_id"))
                if got:
                    r["role"] = role.FAMILY[got]
    except Exception:  # noqa: BLE001 - the line-up matters more than the tags
        pass
