"""How much of a player's record is from before his last long break.

    import freshness
    brk = freshness.break_date(dates, kickoff)          # "2026-10-21", or None
    f = freshness.window(window_dates, brk)             # {"fresh": 3, "n": 10, "share": 0.3}
    freshness.is_stale(f["share"])                      # True: mostly before the break

The page's stale guard (run.py _sample_age, staleDays) is about the fixture:
days since the newest match in either team's form. It lifts once each team
has played one game of the new season, while a player's last ten can still be
nine of last season's games, at last season's minutes. This is the same
question asked of one player: of the games his line is priced on, how many
come after his most recent break of BREAK_DAYS or more (the summer, or a long
injury)?

A break is a gap of BREAK_DAYS or more between two of his games, or between
his last game and this kick-off. Games on or after the break date count as
fresh. A record whose fresh share is under STALE_SHARE is mostly stale: the
page never calls such a line acceptable, and labels it (PLAYER-STALE.md has
the evidence). National sides are left out: caps come in windows months
apart, so every record would read as stale.

Mirrored in report.py (breakDateOf, freshnessOf); tests/test_player_stale.py
runs both on the same records.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

BREAK_DAYS = 45
STALE_SHARE = 0.5


def _day(x) -> int | None:
    """A date as a day number: an ISO date or datetime string, or a Unix timestamp."""
    if x is None or x == "":
        return None
    if isinstance(x, (int, float)):
        return datetime.fromtimestamp(x, tz=timezone.utc).date().toordinal()
    try:
        return date.fromisoformat(str(x)[:10]).toordinal()
    except ValueError:
        return None


def break_date(dates, kickoff) -> str | None:
    """The first day of his current spell: the date of his first game after
    the most recent gap of BREAK_DAYS or more, or the kick-off's date when his
    last game was that long ago. None when his record has no such gap."""
    days = sorted(d for d in (_day(x) for x in dates) if d is not None)
    ko = _day(kickoff)
    if not days:
        return None
    if ko is not None and ko - days[-1] >= BREAK_DAYS:
        return date.fromordinal(ko).isoformat()
    for i in range(len(days) - 1, 0, -1):
        if days[i] - days[i - 1] >= BREAK_DAYS:
            return date.fromordinal(days[i]).isoformat()
    return None


def window(window_dates, brk: str | None) -> dict:
    """{fresh, n, share} for the games a line is priced on, against a break date."""
    days = [d for d in (_day(x) for x in window_dates) if d is not None]
    n = len(days)
    if not n:
        return {"fresh": 0, "n": 0, "share": None}
    b = _day(brk)
    fresh = n if b is None else sum(1 for d in days if d >= b)
    return {"fresh": fresh, "n": n, "share": fresh / n}


def is_stale(share) -> bool:
    return share is not None and share < STALE_SHARE


def player_breaks(rows: list[dict], kickoff) -> dict:
    """{player name: break date or None} over one side's player records (run.py's entry["players"][t])."""
    by: dict[str, list] = {}
    for r in rows or []:
        if r.get("player"):
            by.setdefault(r["player"], []).append(r.get("date"))
    return {name: break_date(ds, kickoff) for name, ds in by.items()}
