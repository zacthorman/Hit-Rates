#!/usr/bin/env python3
"""
Score the 21 October work on results already in the repo. Makes no requests.

    python3 -B proof/settle_oct21.py

Prints the tables behind PROOF-2026-10-22.md items 1 and 2:

  1. every written scoreline call ("The case" in tonight.html, every committed
     version since 21 Oct), what the settled legs say about the real score,
     and the bookmaker baseline from market_prices.json
  2. lead_log.json settled the way tonight.results_block settles it (against
     best_bets.json, plus exchange_log.json for legs only it carries), with a
     calibration table and the sample needed to tell the stated chances apart
     from a 5 or 10 point overstatement

Results come from what besttrack.py and the exchange log had settled when the
21 Oct commit was made. Final scores are not stored anywhere in the repo, so a
score is only known as far as the settled goal legs pin it down.
"""
from __future__ import annotations

import html
import json
import math
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SINCE = datetime(2026, 10, 21, tzinfo=timezone.utc).timestamp()
KEY = ("event_id", "team", "player", "stat", "period", "line", "over")
Z_A, Z_B = 1.96, 0.8416   # two-sided 5%, 80% power


def key(l: dict) -> tuple:
    return tuple(l.get(k) for k in KEY)


def settled_legs() -> dict:
    """Every settled leg in best_bets.json, then exchange_log.json for any key it alone has."""
    out = {}
    for b in json.loads((ROOT / "best_bets.json").read_text()):
        for l in b.get("legs") or []:
            if l.get("result") in ("win", "lose", "void"):
                out[key(l)] = l
    for l in json.loads((ROOT / "exchange_log.json").read_text()).values():
        if l.get("result") in ("win", "lose", "void"):
            out.setdefault(key(l), l)
    return out


def when(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%d %b %H:%M")


# ------------------------------------------------------------ 1. score calls

def written_calls() -> list[dict]:
    """'Call: A 2-1 B · home 56% · draw 20% · away 24%' from every committed tonight.html since 21 Oct."""
    revs = subprocess.run(["git", "-C", str(ROOT), "log", "--format=%H %ct", "--since=2026-10-20", "--", "tonight.html"],
                          capture_output=True, text=True, check=True).stdout.split("\n")
    calls = {}
    for line in filter(None, revs):
        rev, ct = line.split()
        page = subprocess.run(["git", "-C", str(ROOT), "show", f"{rev}:tonight.html"],
                              capture_output=True, text=True, check=True).stdout
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))
        for m in re.finditer(r"Call: (.+?) (\d+)-(\d+) (.+?) · home (\d+)% · draw (\d+)% · away (\d+)%", text):
            home, hg, ag, away, ph, pd, pa = m.groups()
            calls[(home, away)] = {"home": home, "away": away, "hg": int(hg), "ag": int(ag),
                                   "p": [int(ph) / 100, int(pd) / 100, int(pa) / 100], "rev": rev[:7]}
    return list(calls.values())


def score_box(fixture: str, legs: list[dict]) -> list[tuple[int, int]]:
    """Every score 0-0 to 9-9 consistent with the settled goal legs on this fixture."""
    home, away = fixture.split(" v ", 1)
    ok = []
    for i in range(10):
        for j in range(10):
            good = True
            for l in legs:
                if l["stat"] == "Both teams to score":
                    v = 1 if i and j else 0
                elif l["stat"] == "Match goals" or not l.get("team"):
                    v = i + j
                else:
                    v = i if l["team"] == home else j if l["team"] == away else None
                if v is None:
                    continue
                if ((v > (l.get("line") if l.get("line") is not None else 0.5)) == l["over"]) != (l["result"] == "win"):
                    good = False
                    break
            if good:
                ok.append((i, j))
    return ok


def market_1x2(event_id) -> list[float] | None:
    ev = json.loads((ROOT / "market_prices.json").read_text()).get("events", {}).get(str(event_id)) or {}
    for m in ev.get("markets") or []:
        if m.get("type") == "MATCH_ODDS":
            ps = [r.get("p") for r in m["runners"]]
            names = [r["name"] for r in m["runners"]]
            if None in ps or len(ps) != 3:
                return None
            d = names.index("The Draw") if "The Draw" in names else names.index("Draw")
            h, a = [k for k in range(3) if k != d]
            return [ps[h], ps[d], ps[a]]
    return None


def item1(settled: dict) -> None:
    by_fixture = defaultdict(list)
    ids = {}
    for l in settled.values():
        if (l.get("kickoff") or 0) >= SINCE and l.get("sport") == "football" and l["result"] in ("win", "lose") \
                and l["stat"] in ("Goals", "Match goals", "Both teams to score") and l.get("period", "ALL") == "ALL" \
                and not l.get("player"):
            by_fixture[l["fixture"]].append(l)
            ids[l["fixture"]] = l["event_id"]
    calls = written_calls()
    print("## 1. Written score calls since 21 Oct\n")
    print("| Fixture | Call | H / D / A said | Bookmaker H / D / A | Scores the settled legs allow | Outcome known | Exact | Outcome |")
    print("|---|---|---|---|---|---|---|---|")
    for c in calls:
        fx = f"{c['home']} v {c['away']}"
        box = score_box(fx, by_fixture.get(fx, [])) if fx in by_fixture else []
        outs = {"H" if i > j else "D" if i == j else "A" for i, j in box}
        mk = market_1x2(ids.get(fx)) if fx in ids else None
        allowed = "none settled" if not box else (f"{len(box)} (home {min(i for i, _ in box)}+, away {min(j for _, j in box)}+)")
        exact = "unknown" if len(box) != 1 else ("yes" if box[0] == (c["hg"], c["ag"]) else "no")
        outcome = ("unknown" if len(outs) != 1 else
                   ("yes" if outs == {"H" if c["hg"] > c["ag"] else "D" if c["hg"] == c["ag"] else "A"} else "no"))
        print(f"| {fx} | {c['hg']}-{c['ag']} | {' / '.join(f'{p:.0%}' for p in c['p'])} | "
              f"{' / '.join(f'{p:.0%}' for p in mk) if mk else 'n/a'} | {allowed} | {'yes' if len(outs) == 1 else 'no'} | {exact} | {outcome} |")
    print()
    print("Other football fixtures since 21 Oct with settled goal legs (no written call on any committed page):\n")
    print("| Fixture | Kick-off | Scores allowed | Outcome |")
    print("|---|---|---|---|")
    called = {f"{c['home']} v {c['away']}" for c in calls}
    for fx, legs in sorted(by_fixture.items(), key=lambda kv: kv[1][0]["kickoff"]):
        if fx in called:
            continue
        box = score_box(fx, legs)
        outs = sorted({"H" if i > j else "D" if i == j else "A" for i, j in box})
        print(f"| {fx} | {when(legs[0]['kickoff'])} | {len(box)} | {'/'.join(outs)} |")
    print()
    # Assumed rates, not measured here: the likeliest scoreline lands about
    # 11% of the time and the bookmaker's favourite about 50%. The paired
    # spreads are typical per-match log loss differences on 1X2: 0.12 between
    # two sound forecasters, 0.25 between a model and the base rate.
    print("Sample needed (two-sided 5%, 80% power):\n")
    print("| Claim | Assumed | Fixtures |")
    print("|---|---|---|")
    print(f"| Exact score beats the bookmaker's likeliest score by 3 points | 11% v 14% | {n_needed(0.11, 0.14)} |")
    print(f"| Outcome accuracy beats the bookmaker's favourite by 5 points | 50% v 55% | {n_needed(0.50, 0.55)} |")
    print(f"| Log loss 0.01 better than the bookmaker | paired sd 0.12 | {math.ceil(((Z_A + Z_B) * 0.12 / 0.01) ** 2)} |")
    print(f"| Log loss 0.06 better than the base rate | paired sd 0.25 | {math.ceil(((Z_A + Z_B) * 0.25 / 0.06) ** 2)} |")
    print()


# ------------------------------------------------------------ 2. lead log

def n_needed(p0: float, p1: float) -> int:
    """One-sample binomial: legs needed to tell a true rate p1 from the stated p0."""
    return math.ceil(((Z_A * math.sqrt(p0 * (1 - p0)) + Z_B * math.sqrt(p1 * (1 - p1))) / (p0 - p1)) ** 2)


def binom_tail_le(k: int, n: int, p: float) -> float:
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def item2(settled: dict) -> None:
    log = json.loads((ROOT / "lead_log.json").read_text())
    rows = sorted(log.values(), key=lambda r: r["kickoff"])
    print("## 2. lead_log.json\n")
    print("| Kick-off (UTC) | Competition | Lead | Said | Result |")
    print("|---|---|---|---|---|")
    done = []
    for r in rows:
        l = settled.get(key(r))
        res = l["result"] if l else "not settled"
        print(f"| {when(r['kickoff'])} | {r['competition']} | {r['selection']} | {r['chance'] * 100:.0f}% | {res} |")
        if l and l["result"] in ("win", "lose"):
            done.append((r["chance"], 1 if l["result"] == "win" else 0, r))
    n = len(done)
    won = sum(y for _, y, _ in done)
    said = sum(p for p, _, _ in done)
    brier = sum((p - y) ** 2 for p, y, _ in done) / n
    ll = -sum(math.log(p if y else 1 - p) for p, y, _ in done) / n
    base = said / n
    print(f"\nSettled {n}: won {won}, said {said:.2f} ({base:.1%} a leg), landed {won / n:.1%}. "
          f"Brier {brier:.4f}, log loss {ll:.4f}.")
    # every lead at one flat chance, the hit rate of everything settled in best_bets since 21 Oct
    pool = [l for l in settled.values() if (l.get("kickoff") or 0) >= SINCE and l["result"] in ("win", "lose")]
    flat = sum(l["result"] == "win" for l in pool) / len(pool)
    print(f"Flat baseline: every lead at {flat:.1%}, the hit rate of all {len(pool)} legs settled since 21 Oct. "
          f"Brier {sum((flat - y) ** 2 for _, y, _ in done) / n:.4f}, "
          f"log loss {-sum(math.log(flat if y else 1 - flat) for _, y, _ in done) / n:.4f}.")
    print(f"P(at most {won} of {n} | stated chances) by the mean chance: "
          f"{binom_tail_le(won, n, base):.2f}; P(at least {won}): {1 - binom_tail_le(won - 1, n, base):.2f}.\n")
    print("| Stated chance | Leads | Said (mean) | Landed | Hit rate |")
    print("|---|---|---|---|---|")
    for lo, hi in ((0.65, 0.70), (0.70, 0.75), (0.75, 0.80), (0.80, 0.85), (0.85, 1.0)):
        b = [(p, y) for p, y, _ in done if lo <= p < hi]
        if b:
            print(f"| {lo:.0%} to {hi:.0%} | {len(b)} | {sum(p for p, _ in b) / len(b):.1%} | "
                  f"{sum(y for _, y in b)} | {sum(y for _, y in b) / len(b):.0%} |")
        else:
            print(f"| {lo:.0%} to {hi:.0%} | 0 | | | |")
    zero = [r for r in rows if not r["chance"]]
    print(f"\nLeads written with chance 0 (cannot be calibrated): {len(zero)}, all "
          f"{sorted({r['competition'] for r in zero})}.")
    print(f"Sample needed at the mean stated chance {base:.0%}: "
          f"{n_needed(base, base - 0.10)} settled leads to detect a 10 point overstatement, "
          f"{n_needed(base, base - 0.05)} for 5 points (two-sided 5%, 80% power).\n")


if __name__ == "__main__":
    s = settled_legs()
    item1(s)
    item2(s)
