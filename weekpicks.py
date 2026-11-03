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
  3. Strong record, model backs it (added 3 Nov 2026). Zac: the picks do not
     have to beat Pinnacle or Betfair, a strong record the model recommends is
     enough. An over Paddy offers no under on (an alternative line), cleared
     in 9+ of his last 10, at 1.25 to 2.50, where our chance times the price
     is at least 1. On settled NBA alt overs, 20 Oct to 2 Nov: 99 bets, 54
     games, 74% landed against 70% implied, +6.5%; the same record without
     the model agreeing lost 5.0% (270 bets). Chosen on that data, so it is
     in sample: the live record counts from RECORD_START. Left off after the
     2 Nov night (drift legs 1 of 7, mostly lost minutes): players listed out
     or doubtful, players who came off the bench in their last game, and NBA
     games projected 12+ points apart. One line per player. NFL: receiving
     lines only.

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
RULE_SHOW = 3
UNTRIED_SHOW = 3          # bets shown for a rule with no live result yet
PRICE_SHOW = 6.0          # longer prices are left off the page (still tracked)
PROVEN_GAMES = 20         # live games before a rule can count as failed or proven
RECORD_MIN_K10 = 9        # strong record: cleared in 9+ of his last 10
RECORD_PRICE = (1.25, 2.50)
RECORD_SHOW = 6
RECORD_MARGIN_MAX = 12.0  # NBA projected margin: bigger games cut minutes on both sides
RECORD_START = 1793719800  # 3 Nov 2026 15:30 UTC: the live record counts from here
RECORD_OUT = ("out", "doubtful")
SPORTS = ("football", "basketball", "american-football")

# Plain names for the page; the full rule text goes in the tooltip.
SHORT = {
    "nba_under_main": "NBA unders, main line",
    "nba_under_model": "NBA unders, model agrees",
    "nfl_receiving_model": "NFL receiving overs, model agrees",
    "beats_betfair": "Paddy beats Betfair's price",
    "learned_value": "Learned value over Paddy",
    "nba_alt_perfect": "NBA alt overs, 10 from 10",
    "nba_under_blowout": "NBA unders, blowout underdog",
    "nba_alt_drift_miss": "NBA alt overs, drifted after a miss",
    "nba_alt_short_perfect": "NBA short alt overs, 10 from 10",
    "nba_main_day_drift": "NBA main line, drifted on the day",
    "nba_under_reversion": "NBA unders, line above baseline",
    "nba_under_reversion_strong": "NBA unders, line well above form",
    "props_beat_pinnacle": "Paddy beats Pinnacle on props",
    "fb_ss_fouls_model": "Football fouls overs, Super Sub",
    "fb_ss_shots_model": "Football shots overs, Super Sub",
    "us_likely_top5": "Five most likely a day",
}


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
        if rule.startswith("control_"):
            continue          # controls are built to lose: tracked, never shown
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
                "rule": rule, "name": SHORT.get(rule, ruletrack.RULES.get(rule, rule)),
                "title": ruletrack.RULES.get(rule, rule), "proven": proven,
                "record": {k: rec.get(k) for k in ("n", "games", "won", "roi", "lo", "hi")} if rec.get("n") else None,
                "bets": items})
    return out


# ------------------------------------------------------------ 3. strong record

def _player_rows(rows: list[dict]) -> list[dict]:
    """Player lines from the pp log. pplog.all_rows() also reads
    pinnacle-YYYY-MM.jsonl, whose rows have no event_id or snapshots."""
    return [r for r in rows if r.get("event_id") is not None and r.get("player") and r.get("first")]


def _norm(s: str) -> str:
    import pplog
    return pplog._norm(s)


def _mains(rows: list[dict]) -> set:
    """Lines Paddy prices both ways (main lines). The rest are alternatives."""
    sides: dict[tuple, set] = {}
    for r in rows:
        k = (r["event_id"], _norm(r["player"]), r["stat"], r["line"])
        sides.setdefault(k, set()).add(bool(r["over"]))
    return {k for k, v in sides.items() if len(v) == 2}


def _starts(rows: list[dict]) -> dict[tuple, list[tuple]]:
    """Each player's settled games, oldest first: (kickoff, started)."""
    seen: dict[tuple, dict] = {}
    for r in rows:
        if r.get("result") in ("win", "lose") and r.get("started") is not None:
            seen.setdefault((r.get("sport"), _norm(r["player"])), {})[r["kickoff"]] = bool(r["started"])
    return {k: sorted(v.items()) for k, v in seen.items()}


def _started_last(starts: dict, r: dict):
    """Whether he started his last settled game before this one (None if unknown)."""
    prev = None
    for ko, started in starts.get((r.get("sport"), _norm(r["player"])), []):
        if ko >= r["kickoff"] - 6 * 3600:
            break
        prev = started
    return prev


def record_edge(r: dict, snap: str, mains: set, starts: dict):
    """The model edge (chance x price - 1) if the line qualifies, else None."""
    if r.get("sport") not in SPORTS or not r.get("over"):
        return None
    # NFL: receiving lines only. On the history the filter took 13 receiving
    # overs (+1.9%) and 12 others (-44%), so only receiving stays (3 Nov 2026).
    if r["sport"] == "american-football" and not (r.get("stat") or "").startswith("Receiving"):
        return None
    if (r["event_id"], _norm(r["player"]), r["stat"], r["line"]) in mains:
        return None
    if (r.get("k10") or 0) < RECORD_MIN_K10:
        return None
    s = r.get(snap) or {}
    price, chance = s.get("price"), s.get("chance")
    if not price or chance is None or not RECORD_PRICE[0] <= price <= RECORD_PRICE[1]:
        return None
    edge = chance * price - 1
    if edge < 0:
        return None
    if (r.get("injury") or "").strip().lower().startswith(RECORD_OUT):
        return None
    # Bench: NFL line-ups mark nearly every skill player a substitute, so the
    # flag only means something in basketball and football.
    if r["sport"] in ("basketball", "football") and _started_last(starts, r) is False:
        return None
    pm = r.get("proj_margin")
    if r["sport"] == "basketball" and pm is not None and abs(pm) >= RECORD_MARGIN_MAX:
        return None
    return edge


def _best_per_player(rows: list[tuple]) -> list[tuple]:
    """One line per player per game, the one the model likes most."""
    best: dict[tuple, tuple] = {}
    for edge, r in rows:
        k = (r["event_id"], _norm(r["player"]))
        if k not in best or edge > best[k][0]:
            best[k] = (edge, r)
    return sorted(best.values(), key=lambda x: -x[0])


def record_bets(now: float, rows: list[dict]) -> dict[str, list[dict]]:
    mains, starts = _mains(rows), _starts(rows)
    found = []
    for r in rows:
        if r.get("result") is not None or not now < r["kickoff"] <= now + WINDOW_H * 3600:
            continue
        edge = record_edge(r, "last", mains, starts)
        if edge is not None:
            found.append((edge, r))
    out: dict[str, list[dict]] = {}
    for edge, r in _best_per_player(found):
        sport = r.get("sport") or "football"
        if len(out.get(sport, [])) >= RECORD_SHOW:
            continue
        s = r.get("last") or r.get("first") or {}
        out.setdefault(sport, []).append({
            "bet": bet_text(r), "game": r.get("fixture"), "kickoff": r.get("kickoff"),
            "book": "Bet365" if r.get("book") == "b365" else "Paddy Power",
            "price": s.get("price"), "chance": s.get("chance"), "edge": round(edge, 4),
            "form": f"{r.get('k10')}/{r.get('n10') or 10} last 10"})
    return out


def _tally(items: list[tuple]) -> dict:
    n = len(items)
    if not n:
        return {"n": 0}
    won = sum(r["result"] == "win" for _, r in items)
    profit = sum((r["first"]["price"] - 1) if r["result"] == "win" else -1.0 for _, r in items)
    return {"n": n, "won": won, "games": len({r["event_id"] for _, r in items}), "roi": profit / n,
            "implied": sum(1 / r["first"]["price"] for _, r in items) / n}


def record_record(rows: list[dict]) -> dict:
    """Settled record of the section at the first price logged: live (from
    RECORD_START) and the history it was chosen on, kept apart."""
    mains, starts = _mains(rows), _starts(rows)
    found = []
    for r in rows:
        if r.get("result") not in ("win", "lose"):
            continue
        edge = record_edge(r, "first", mains, starts)
        if edge is not None:
            found.append((edge, r))
    best = _best_per_player(found)
    return {"live": _tally([x for x in best if x[1]["kickoff"] >= RECORD_START]),
            "history": _tally([x for x in best if x[1]["kickoff"] < RECORD_START])}


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
    record = None
    try:
        import pplog
        rows = _player_rows(pplog.all_rows())
        for sport, bets in record_bets(now, rows).items():
            sections.setdefault(sport, {})["record"] = bets
        record = record_record(rows)
    except Exception as exc:  # noqa: BLE001
        print(f"  weekpicks: strong record section not built ({type(exc).__name__}: {exc})")
    return {"built": now, "windowHours": WINDOW_H, "sharpMin": SHARP_MIN, "sharpRecord": sharp_record(),
            "recordRule": {"minK10": RECORD_MIN_K10, "priceLo": RECORD_PRICE[0], "priceHi": RECORD_PRICE[1],
                           "marginMax": RECORD_MARGIN_MAX, "start": RECORD_START},
            "recordRecord": record,
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
        for b in sec.get("record") or []:
            print(f"  RECORD {b['bet']} ({b['game']}) {b['book']} {b['price']}  {b['form']}, "
                  f"ours {b['chance'] * 100:.0f}%, edge {b['edge']:+.1%}")
    rr = out.get("recordRecord") or {}
    for label, key in (("live", "live"), ("history (in sample)", "history")):
        t = rr.get(key) or {}
        if t.get("n"):
            print(f"Strong record {label}: {t['n']} bets, {t['games']} games, {t['won']} won, "
                  f"ROI {t['roi']:+.1%} (implied {t['implied']:.0%})")
        else:
            print(f"Strong record {label}: no settled bets yet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
