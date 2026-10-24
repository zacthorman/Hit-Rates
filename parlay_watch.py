"""
Split against one-side parlays, on tickets put up from 24 October 2026 on.

    python parlay_watch.py          # print the watch from best_bets.json
    (besttrack.py settle runs it after every settle and writes parlay_watch.json)

PARLAY-CHECK.md (#16) found that parlays with legs on both teams ("split":
two joint counts multiplied) looked optimistic: 9 of 56 in the walk-forward
and 10 of 42 published against about 30% said, where parlays on one team
were close to their price. That subgroup was picked after the data had been
seen, so it is a hypothesis, not a finding. This watch tests it on tickets
nobody had seen when it was framed: only parlays first recorded on or after
START count.

Fixed now, before any of them settle:

  * Tickets. Distinct published parlays ("Pick: parlay" in best_bets.json),
    first recorded on or after START, settled win or lose. A ticket with a
    void leg is left out and counted, because its stated price includes the
    void leg (besttrack settles it on the rest).
  * Said. One over the ticket's fair price, exactly as published.
  * The alternative. The product of the legs' own record rates
    (hits / total), the price PARLAY-CHECK.md's exploratory fit pointed to.
  * The decision. Looked at once split tickets reach DECIDE_AT (300, from
    the size of the effect PARLAY-CHECK.md saw). The hypothesis holds if the
    95% interval on split landed / said lies wholly below 1 AND pricing split
    tickets off the multiplied legs lowers their log loss with a 95%
    interval wholly below zero. Anything else, and parlay pricing stays as it
    is. Until then the watch reports and decides nothing.

Parlay pricing is not touched by any of this.
"""

from __future__ import annotations

import json
import math
import os
import random
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
STORE = HERE / "best_bets.json"
OUT_NAME = "parlay_watch.json"
# Where update() writes by default. besttrack.settle passes the file beside
# the store it settles, so a test that redirects besttrack.STORE redirects
# this too; HITRATES_PARLAY_WATCH_JSON moves the default for anything else.
OUT = Path(os.environ.get("HITRATES_PARLAY_WATCH_JSON") or HERE / OUT_NAME)
START = int(datetime(2026, 10, 24, tzinfo=timezone.utc).timestamp())
DECIDE_AT = 300
SEED = 20261024
BOOT = 2000
EPS = 1e-6


def night_of(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def shape(legs: list[dict]) -> str:
    return "split" if len({l.get("team") for l in legs}) > 1 else "one side"


def tickets(items: list[dict], start: int = START) -> tuple[list[dict], dict]:
    """Settled parlays from `start`, one row per distinct ticket, and the
    counts of what was left out."""
    seen: dict = {}
    left = {"void leg": 0, "open": 0, "before start": 0}
    for b in items:
        if b.get("category") != "Pick: parlay":
            continue
        key = tuple(sorted((l.get("event_id"), l.get("player"), l.get("stat"), l.get("threshold"), l.get("line"))
                           for l in b.get("legs") or []))
        if key in seen:
            continue
        if (b.get("snapshot_at") or 0) < start:
            left["before start"] += 1
            seen[key] = None
            continue
        res = [l.get("result") for l in b.get("legs") or []]
        if any(r == "void" for r in res):
            left["void leg"] += 1
            seen[key] = None
            continue
        if b.get("result") not in ("win", "lose") or any(r not in ("win", "lose") for r in res):
            left["open"] += 1         # not kept: it may settle on a later run
            continue
        fair = b.get("fair")
        if not isinstance(fair, (int, float)) or fair <= 1:
            continue
        mult = 1.0
        for l in b["legs"]:
            h, n = l.get("hits"), l.get("total")
            mult *= (h / n) if isinstance(h, (int, float)) and n else float("nan")
        kick = min(l.get("kickoff") or 0 for l in b["legs"])
        seen[key] = {"night": night_of(kick), "sport": b.get("sport"), "shape": shape(b["legs"]),
                     "said": 1 / fair, "multiplied": mult, "won": int(b["result"] == "win")}
    return [r for r in seen.values() if r], left


def wilson(k: int, n: int, z: float = 1.96):
    if not n:
        return float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def _boot(rows, stat, seed=SEED, reps=BOOT):
    by: dict = {}
    for r in rows:
        by.setdefault(r["night"], []).append(r)
    nights = list(by.values())
    point = stat(nights)
    if len(nights) < 2:
        return point, None, None
    rnd = random.Random(seed)
    draws = sorted(stat([nights[rnd.randrange(len(nights))] for _ in nights]) for _ in range(reps))
    return point, draws[int(0.025 * reps)], draws[int(0.975 * reps) - 1]


def _ll(p, y):
    p = min(max(p, EPS), 1 - EPS)
    return -math.log(p if y else 1 - p)


def block(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"tickets": 0}
    k = sum(r["won"] for r in rows)
    lo, hi = wilson(k, n)
    ratio = _boot(rows, lambda ns: (sum(r["won"] for g in ns for r in g)
                                    / max(sum(r["said"] for g in ns for r in g), EPS)))
    ok = [r for r in rows if r["multiplied"] == r["multiplied"]]
    diff = _boot(ok, lambda ns: (sum(_ll(r["multiplied"], r["won"]) - _ll(r["said"], r["won"])
                                     for g in ns for r in g) / max(sum(len(g) for g in ns), 1))) if ok else None
    return {"tickets": n, "nights": len({r["night"] for r in rows}), "landed": k, "rate": k / n,
            "rate_95": [lo, hi], "said": sum(r["said"] for r in rows) / n,
            "multiplied": sum(r["multiplied"] for r in ok) / len(ok) if ok else None,
            "landed_over_said": ratio[0], "landed_over_said_95": [ratio[1], ratio[2]],
            "log_loss_said": sum(_ll(r["said"], r["won"]) for r in rows) / n,
            "multiplied_minus_said": diff[0] if diff else None,
            "multiplied_minus_said_95": [diff[1], diff[2]] if diff else [None, None]}


def decide(split: dict) -> str:
    n = split.get("tickets", 0)
    if n < DECIDE_AT:
        return f"waiting: {n} of {DECIDE_AT} settled split tickets"
    hi = (split.get("landed_over_said_95") or [None, None])[1]
    dhi = (split.get("multiplied_minus_said_95") or [None, None])[1]
    if hi is not None and hi < 1 and dhi is not None and dhi < 0:
        return "holds: split tickets land below said and the multiplied legs price them better"
    return "does not hold: leave parlay pricing as it is"


def summary(items: list[dict], start: int = START) -> dict:
    rows, left = tickets(items, start)
    split = block([r for r in rows if r["shape"] == "split"])
    one = block([r for r in rows if r["shape"] == "one side"])
    return {"start": night_of(start), "decide_at": DECIDE_AT, "split": split, "one side": one,
            "all": block(rows), "left out": left, "decision": decide(split)}


def update(items: list[dict] | None = None, path: Path | None = None) -> dict:
    """Rewrite the watch from the settled record. Called by besttrack.settle,
    which passes the file beside its own store."""
    path = Path(path) if path is not None else OUT
    items = items if items is not None else json.loads(STORE.read_text())
    s = summary(items)
    s["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    path.write_text(json.dumps(s, indent=1) + "\n")
    return s


def text(s: dict) -> str:
    def pct(x):
        return "-" if x is None else f"{x:.1%}"

    def iv(xs, d=2):
        return "-" if not xs or xs[0] is None else f"{xs[0]:.{d}f} to {xs[1]:.{d}f}"
    out = [f"Parlay watch, tickets from {s['start']}: {s['decision']}"]
    for k in ("split", "one side"):
        b = s[k]
        if not b.get("tickets"):
            out.append(f"  {k:<9} no settled tickets yet")
            continue
        out.append(f"  {k:<9} {b['landed']}/{b['tickets']} landed {pct(b['rate'])} "
                   f"(95% {pct(b['rate_95'][0])} to {pct(b['rate_95'][1])}), said {pct(b['said'])}, "
                   f"landed/said {b['landed_over_said']:.2f} ({iv(b['landed_over_said_95'])}), "
                   f"multiplied legs minus said, log loss "
                   + ("-" if b["multiplied_minus_said"] is None else f"{b['multiplied_minus_said']:+.4f}")
                   + f" ({iv(b['multiplied_minus_said_95'], 4)})")
    lo = s["left out"]
    out.append(f"  left out: {lo['void leg']} with a void leg, {lo['open']} open, "
               f"{lo['before start']} recorded before {s['start']}")
    return "\n".join(out)


if __name__ == "__main__":
    print(text(summary(json.loads(STORE.read_text()))))
