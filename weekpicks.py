#!/usr/bin/env python3
"""Picks of the week, rebuilt on evidence (2 Nov 2026).

    python weekpicks.py      # print what the front page would show

The old picks (best bet at 2.0+, banker, evens double, acca, builder,
same-game parlay, value on Betfair) were chosen for being likely or for a
model edge, mostly at prices no book offered. On real prices they lost:
priced picks -11.4% (research/BACKTEST-2026-11-02.md), parlays and doubles
worse, and the bigger the model's claimed edge the worse it did. Zac: "if
anything the picks of the week should be profitable".

So the picks are now only what has evidence behind it, each shown with its
record:

  1. Beats the sharp price. A line where Paddy Power, Bet365 or Sky Bet pays
     more than Pinnacle's or Betfair's margin-free chance, and our model does
     not disagree (value_books.py). The one method the record backs: the
     Pinnacle-checked team lines returned what Pinnacle said they would.
  2. On trial. Today's bets from the frozen rules (ruletrack.py), including
     us_likely_top5 (the five NBA/NFL lines our model rates most likely each
     day at 1.60 to 2.50), each with its live record. Shown as tracking, not
     as bets to place, until a rule's live 90% range is above zero (the same
     bar as ruletrack.VALUE_SHOW). A rule whose live record has clearly
     failed (20+ games and the whole range below zero) is left off.

Darts keeps its match prices (weekend.py), which are a separate model.
Never fatal: a section that cannot be built is left out.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WINDOW_H = 48
SHARP_MIN = 0.02          # 2%+ over the sharp chance
SHARP_SHOW = 6
RULE_SHOW = 5
UNTRIED_SHOW = 3          # bets shown for a rule with no live result yet
PRICE_SHOW = 6.0          # longer prices are left off the page (still tracked)
PROVEN_GAMES = 20         # live games before a rule can count as failed or proven
SPORTS = ("football", "basketball", "american-football")


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def bet_text(r: dict) -> str:
    """A pplog row as a bookmaker would write it."""
    stat = (r.get("stat") or "").lower()
    who = r.get("player") or r.get("team") or ""
    label = r.get("label") or ""
    if label.lower().startswith(("over ", "under ")):
        return f"{who} {label.lower()} {stat}"
    if label in ("to score", "to be booked", "anytime TD"):
        return f"{who} {label}"
    return f"{who} {label} {stat}".strip()


# ------------------------------------------------------------ 1. sharp

def sharp_record() -> dict | None:
    """The settled record of every line value_books logged with a sharp price
    behind it: what it returned, and what the sharp price said it was worth."""
    path = ROOT / "value" / "log.jsonl"
    if not path.exists():
        return None
    n = w = 0
    profit = ev = 0.0
    rets: list[float] = []
    for line in path.read_text().splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        f = r.get("first") or {}
        if r.get("result") not in ("win", "lose") or not f.get("sharp"):
            continue
        n += 1
        w += r["result"] == "win"
        ret = (f["price"] - 1) if r["result"] == "win" else -1.0
        rets.append(ret)
        profit += ret
        ev += f["sharp"] * f["price"] - 1
    if not n:
        return None
    mean = profit / n
    se = (sum((x - mean) ** 2 for x in rets) / max(n - 1, 1) / n) ** 0.5
    # the gap from what the sharp price said, in standard errors: inside 2 is
    # ordinary luck at this sample size
    return {"n": n, "won": w, "roi": mean, "expected": ev / n, "se": se,
            "noise": abs(mean - ev / n) <= 2 * se}


def sharp_bets(now: float) -> dict[str, list[dict]]:
    names = {"B3": "Bet365", "PP": "Paddy Power", "SK": "Sky Bet"}
    src = {"pinnacle": "Pinnacle", "betfair": "Betfair"}
    out: dict[str, list[dict]] = {}
    for b in _load(ROOT / "reports" / "value_books.json").get("bets") or []:
        se = b.get("sharp_edge")
        if se is None or se < SHARP_MIN or not now < b["kickoff"] <= now + WINDOW_H * 3600:
            continue
        who = b.get("player") or b.get("team") or ""
        side = "over" if b["over"] else "under"
        if b.get("player") and b["over"]:
            text = f"{who} {int(b['line'] + 0.5)}+ {b['stat'].lower()}"
        else:
            text = f"{who} {side} {b['line']} {b['stat'].lower()}"
        out.setdefault("football", []).append({
            "bet": text, "game": b.get("game"), "kickoff": b["kickoff"],
            "book": names.get(b["book"], b["book"]), "price": b["price"], "chance": b.get("p"),
            "sharp": b.get("sharp"), "sharpSrc": src.get(b.get("sharp_src"), b.get("sharp_src")),
            "edge": round(se, 4),
            "note": f"{src.get(b.get('sharp_src'), 'Sharp')} makes it {b['sharp'] * 100:.0f}%: "
                    f"{se * 100:+.1f}% at this price"})
    for k in out:
        out[k] = sorted(out[k], key=lambda x: -x["edge"])[:SHARP_SHOW]
    return out


# ------------------------------------------------------------ 2. rules

def _live(rule: str, bets: list[dict]) -> dict:
    import ruletrack
    start = ruletrack.RULE_START.get(rule, ruletrack.FROZEN)
    live = [b for b in bets if (b.get("kickoff") or 0) >= start]
    s = ruletrack._score(live, ruletrack.SCORE_AT.get(rule, "first"))
    return s


def _keep(rec: dict) -> bool:
    """Hide a rule once its live run says no: the whole 90% range below zero,
    or ten games in and still not in profit."""
    games = rec.get("games") or 0
    if games >= 3 and rec.get("hi", 1) < 0:
        return False
    if games >= 10 and (rec.get("roi") or 0) <= 0:
        return False
    return True


def rule_bets(now: float) -> dict[str, list[dict]]:
    import pplog
    import ruletrack
    q = ruletrack.qualifying(pplog.all_rows())
    today = ruletrack.tonight(now, now + WINDOW_H * 3600, q)
    groups = []
    for rule, bets in today.items():
        rec = _live(rule, q.get(rule) or [])
        if not _keep(rec):
            continue
        games = rec.get("games") or 0
        proven = games >= PROVEN_GAMES and rec.get("lo", -1) > 0
        groups.append((rule, bets, rec, proven))
    # proven first, then the best live return; untried rules last
    groups.sort(key=lambda g: (not g[3], g[2].get("n") is None, -(g[2].get("roi") or 0)))
    seen: set = set()
    out: dict[str, list[dict]] = {}
    for rule, bets, rec, proven in groups:
        snap = ruletrack.SCORE_AT.get(rule, "first")
        by_sport: dict[str, list[dict]] = {}
        for r in ruletrack.shortlist(bets):
            key = (r.get("event_id"), r.get("player") or r.get("team"), r.get("stat"), r.get("line"), r.get("over"))
            if key in seen:
                continue          # each bet once, under the strongest rule that takes it
            sport = r.get("sport") or "football"
            s = r.get(snap) or r.get("first") or {}
            if (s.get("price") or 99) > PRICE_SHOW:
                continue
            if len(by_sport.get(sport, [])) >= (RULE_SHOW if rec.get("n") else UNTRIED_SHOW):
                continue
            seen.add(key)
            by_sport.setdefault(sport, []).append({
                "bet": bet_text(r), "game": r.get("fixture"), "kickoff": r.get("kickoff"),
                "book": "Bet365" if r.get("book") == "b365" else "Paddy Power",
                "price": s.get("price"), "chance": s.get("chance")})
        for sport, items in by_sport.items():
            out.setdefault(sport, []).append({
                "rule": rule, "title": ruletrack.RULES.get(rule, rule), "proven": proven,
                "record": {k: rec.get(k) for k in ("n", "games", "won", "roi", "lo", "hi")} if rec.get("n") else None,
                "bets": items})
    return out


# ------------------------------------------------------------ build

def build(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    sections: dict[str, dict] = {s: {} for s in SPORTS}
    try:
        for sport, bets in sharp_bets(now).items():
            sections.setdefault(sport, {})["sharp"] = bets
    except Exception as exc:  # noqa: BLE001
        print(f"  weekpicks: sharp section not built ({type(exc).__name__}: {exc})")
    try:
        for sport, groups in rule_bets(now).items():
            sections.setdefault(sport, {})["rules"] = groups
    except Exception as exc:  # noqa: BLE001
        print(f"  weekpicks: rules section not built ({type(exc).__name__}: {exc})")
    return {"built": now, "windowHours": WINDOW_H, "sharpMin": SHARP_MIN, "sharpRecord": sharp_record(),
            "sports": {k: v for k, v in sections.items() if v}}


def main() -> int:
    out = build()
    rec = out.get("sharpRecord")
    if rec:
        print(f"Sharp-backed record: {rec['n']} settled, {rec['won']} won, ROI {rec['roi']:+.1%} "
              f"(the sharp price said {rec['expected']:+.1%})")
    for sport, sec in out["sports"].items():
        print(f"\n== {sport}")
        for b in sec.get("sharp") or []:
            print(f"  SHARP  {b['bet']} ({b['game']}) {b['book']} {b['price']}  {b['note']}")
        for g in sec.get("rules") or []:
            r = g["record"]
            rec_s = (f"live {r['n']} bets, {r['games']} games, ROI {r['roi']:+.1%} "
                     f"[{r['lo']:+.0%}, {r['hi']:+.0%}]") if r else "no live result yet"
            print(f"  RULE   {g['title']}  ({'proven' if g['proven'] else 'on trial'}; {rec_s})")
            for b in g["bets"]:
                print(f"           {b['bet']} ({b['game']}) {b['book']} {b['price']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
