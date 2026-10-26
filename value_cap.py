#!/usr/bin/env python3
"""
How many singles one player may take, and the backtest that chose it.

    python -B value_cap.py            # the tables, from whatever record is on this machine

The problem. The value lists and the per-fixture singles are ranked one leg
at a time, so a player the model likes turns up again and again: Cason
Wallace had eight Paddy Power value bets on one night (steals 1.5 and 2.5,
threes, points, rebounds, three combinations) and lost all eight, because
they were one bet on one bad night. A cap of MAX_PER_PLAYER legs per player
per game keeps his best one and gives the slots to someone else.

The backtest reads two records:

  - every settled single in best_bets.json (the fixture singles and the
    player lines tonight.html put up), with the chance the site gave, to
    measure how alike two legs on one player land, and how a player's second
    and third legs land against his first;
  - every settled Paddy Power value bet: pplog/ in full on the Mac, else the
    "Recent value bets" rows of each committed pp-results.html, for the
    profit at the price on offer under each cap.

Cap 1 was chosen because two legs on one player land together (a residual
correlation of about 0.6, against about 0 for team-mates), so a second leg
doubles the stake on one outcome without adding a second view, and because
a player's second-ranked leg landed below what was said where his first
landed above it. The profit table does not separate the caps: it is too
small. CARDS-MODEL.md has the tables and says how much they can carry.
"""
from __future__ import annotations

import collections
import html
import itertools
import json
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
MAX_PER_PLAYER = 1


def cap_per_player(items, k: int | None = MAX_PER_PLAYER, key=lambda x: x.get("player")) -> list:
    """`items` in their order, with no more than `k` sharing a player.

    Team legs (no player) are never capped. The order decides which of a
    player's legs survive, so rank before capping. k None means no cap."""
    if k is None:
        return list(items)
    seen = collections.Counter()
    out = []
    for it in items:
        who = key(it)
        if who is not None:
            if seen[who] >= k:
                continue
            seen[who] += 1
        out.append(it)
    return out


# ------------------------------------------------------------------ the records

def singles(path: Path = ROOT / "best_bets.json") -> list[dict]:
    """Settled single legs from the record, one per distinct bet."""
    try:
        items = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    legs = {}
    for x in items:
        if x.get("category") not in ("Fixture single", "Player line") or len(x.get("legs") or []) != 1:
            continue
        l = x["legs"][0]
        if l.get("result") not in ("win", "lose"):
            continue
        p = l.get("chance") or (1 / l["fair"] if l.get("fair") else None)
        if p is None or not 0 < p < 1:
            continue
        k = (l.get("event_id"), l.get("player") or l.get("team"), l.get("stat"), l.get("period"),
             l.get("line"), l.get("over"), l.get("alt"), l.get("threshold"))
        legs[k] = {"event": l.get("event_id"), "player": l.get("player"), "team": l.get("team"),
                   "p": float(p), "win": l["result"] == "win", "sport": l.get("sport")}
    return list(legs.values())


def _pp_rows_pplog() -> list[dict]:
    try:
        import pplog
        rows = pplog.all_rows()
    except Exception:
        return []
    out = []
    for r in rows:
        if r.get("result") in ("win", "lose") and pplog.is_value(r):
            out.append({"event": r["event_id"], "player": r["player"], "p": r["first"]["chance"],
                        "price": r["first"]["price"], "edge": r["first"]["edge"], "win": r["result"] == "win"})
    return out


def _pp_rows_history() -> list[dict]:
    """Settled value bets from the 'Recent value bets' table of every
    committed pp-results.html. Kick-off and player stand in for the event."""
    try:
        hs = subprocess.check_output(["git", "-C", str(ROOT), "log", "--all", "--format=%h", "--", "pp-results.html"],
                                     stderr=subprocess.DEVNULL).decode().split()
    except (OSError, subprocess.CalledProcessError):
        return []
    rows = {}
    for h in hs:
        try:
            t = subprocess.check_output(["git", "-C", str(ROOT), "show", f"{h}:pp-results.html"],
                                        stderr=subprocess.DEVNULL).decode()
        except subprocess.CalledProcessError:
            continue
        for title, body in re.findall(r"<h2>(.*?)</h2>(.*?)(?=<h2>|$)", t, re.S):
            if title.strip() != "Recent value bets":
                continue
            for tr in re.findall(r"<tr>(.*?)</tr>", body, re.S):
                tds = [html.unescape(re.sub(r"<[^>]+>", " ", c)).strip()
                       for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
                if len(tds) < 8 or tds[-1].split()[0] not in ("win", "lose"):
                    continue
                try:
                    rows[tuple(tds[:3])] = {
                        "event": tds[0] + "|" + tds[1].split("   ")[-1], "player": tds[1].split("   ")[0],
                        "p": float(tds[4].rstrip("%")) / 100, "price": float(tds[5]),
                        "edge": float(tds[6].rstrip("%").replace("+", "")) / 100,
                        "win": tds[-1].startswith("win")}
                except ValueError:
                    continue
    return list(rows.values())


def value_bets() -> tuple[list[dict], str]:
    rows = _pp_rows_pplog()
    if rows:
        return rows, "pplog/ (every settled value bet)"
    return _pp_rows_history(), "pp-results.html history (recent value bets only)"


# ------------------------------------------------------------------ the tests

def residual_corr(pairs) -> tuple[int, float, float]:
    """Mean standardised residual product over pairs of legs, and its
    standard error: about 0 for independent legs, 1 for the same bet."""
    v = []
    for a, b in pairs:
        sa = math.sqrt(a["p"] * (1 - a["p"]))
        sb = math.sqrt(b["p"] * (1 - b["p"]))
        v.append((a["win"] - a["p"]) * (b["win"] - b["p"]) / (sa * sb))
    if not v:
        return 0, float("nan"), float("nan")
    m = sum(v) / len(v)
    se = math.sqrt(sum((x - m) ** 2 for x in v) / len(v) / len(v))
    return len(v), m, se


def correlations(legs: list[dict]) -> dict:
    by_player = collections.defaultdict(list)
    by_event = collections.defaultdict(list)
    for l in legs:
        if l["player"]:
            by_player[(l["event"], l["player"])].append(l)
            by_event[l["event"]].append(l)
    same = [pair for v in by_player.values() for pair in itertools.combinations(v, 2)]
    mates = [(a, b) for v in by_event.values() for a, b in itertools.combinations(v, 2)
             if a["player"] != b["player"] and a["team"] == b["team"]]
    opp = [(a, b) for v in by_event.values() for a, b in itertools.combinations(v, 2) if a["team"] != b["team"]]
    return {"same player": residual_corr(same), "team-mates": residual_corr(mates),
            "opponents": residual_corr(opp)}


def ranks(legs: list[dict], score="p") -> list[dict]:
    """Each player leg's rank among that player's legs in the game, best first."""
    g = collections.defaultdict(list)
    for l in legs:
        if l["player"]:
            g[(l["event"], l["player"])].append(l)
    for v in g.values():
        v.sort(key=lambda l: -l[score])
        for i, l in enumerate(v):
            l["rank"] = i + 1
    return [l for l in legs if l["player"]]


def rank_table(legs: list[dict], score="p") -> list[tuple]:
    out = []
    for name, keep in (("1st", lambda r: r == 1), ("2nd", lambda r: r == 2), ("3rd or lower", lambda r: r >= 3)):
        s = [l for l in ranks(legs, score) if keep(l["rank"])]
        if s:
            out.append((name, len(s), sum(l["p"] for l in s) / len(s), sum(l["win"] for l in s) / len(s)))
    return out


def cap_table(bets: list[dict], caps=(1, 2, 3, None), n_boot: int = 2000, seed: int = 7) -> list[tuple]:
    """Value bets under each cap (best edge kept): bets, won, said, landed,
    profit at the price, ROI and a 95% interval for it resampling players."""
    import random
    rng = random.Random(seed)
    out = []
    for k in caps:
        g = collections.defaultdict(list)
        for b in bets:
            g[(b["event"], b["player"])].append(b)
        kept = []
        for v in g.values():
            v.sort(key=lambda b: -b["edge"])
            kept.append(v if k is None else v[:k])
        flat = [b for v in kept for b in v]
        if not flat:
            continue
        prof = lambda bs: sum((b["price"] - 1) if b["win"] else -1 for b in bs)  # noqa: E731
        boot = []
        for _ in range(n_boot):
            pick = [kept[rng.randrange(len(kept))] for _ in kept]
            bs = [b for v in pick for b in v]
            boot.append(prof(bs) / len(bs))
        boot.sort()
        out.append(("none" if k is None else str(k), len(flat), sum(b["win"] for b in flat),
                    sum(b["p"] for b in flat) / len(flat), sum(b["win"] for b in flat) / len(flat),
                    prof(flat), prof(flat) / len(flat), boot[int(0.025 * n_boot)], boot[int(0.975 * n_boot)]))
    return out


def markdown() -> str:
    legs = singles()
    L = [f"### Singles in best_bets.json: {len(legs)} settled, {sum(1 for l in legs if l['player'])} on players\n"]
    L.append("How alike two legs land, as a residual correlation (0 independent, 1 the same bet):\n")
    L.append("| Pair | Pairs | Correlation | Standard error |\n|---|---|---|---|")
    for k, (n, m, se) in correlations(legs).items():
        L.append(f"| {k} | {n} | {m:+.2f} | {se:.2f} |")
    L.append("\nA player's legs in one game, ranked by the site's chance:\n")
    L.append("| Leg | n | Said | Landed |\n|---|---|---|---|")
    for name, n, s, g in rank_table(legs):
        L.append(f"| {name} | {n} | {s:.1%} | {g:.1%} |")
    bets, src = value_bets()
    L.append(f"\n### Paddy Power value bets: {len(bets)} settled, from {src}\n")
    L.append("| Cap per player | Bets | Won | Said | Landed | Profit | ROI | ROI 95% interval |\n|---|---|---|---|---|---|---|---|")
    for cap, n, w, s, g, p, roi, lo, hi in cap_table(bets):
        L.append(f"| {cap} | {n} | {w} | {s:.1%} | {g:.1%} | {p:+.1f}u | {roi:+.1%} | {lo:+.1%} to {hi:+.1%} |")
    L.append("\nA value bet's rank among that player's value bets in the game, by edge:\n")
    L.append("| Leg | n | Said | Landed |\n|---|---|---|---|")
    for name, n, s, g in rank_table([dict(b, team=None) for b in bets], score="edge"):
        L.append(f"| {name} | {n} | {s:.1%} | {g:.1%} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    print(markdown())
    sys.exit(0)
