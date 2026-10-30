#!/usr/bin/env python3
"""ppcheck_us.py's question, asked of the live models on the Mac. No requests.

    python3 -B proof/ppcheck_live.py [since YYYY-MM-DD]

ppcheck_us.py needs the training box (/home/claude/usbt: parquet tables and the
train-only oos_* LightGBM models), which is not on this Mac, and LightGBM is not
installed. pplog/ already records, for every Paddy Power line, the chance the
live US model (usmodel_live.py) gave before kick-off (first.model_chance), the
site's own chance (site_chance), the page's final chance (chance) and Paddy's
price. Those were written before the game, by a model fitted before it, so
scoring them is a forward test. Paddy's chance is 1 / first price, margin left
in, exactly as ppcheck_us.py does it.
"""
import json, math, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SINCE = datetime.strptime(sys.argv[1] if len(sys.argv) > 1 else "2026-10-21", "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
SITES = {"basketball": "NBA", "american-football": "NFL"}


def ll(p, y):
    p = min(1 - 1e-4, max(1e-4, p))
    return -math.log(p if y else 1 - p)


rows = []
for f in sorted((ROOT / "pplog").glob("2026-1*.jsonl")):
    if f.name.startswith("team"):
        continue
    for line in open(f):
        r = json.loads(line)
        if r.get("sport") not in SITES or r.get("result") not in ("win", "lose") or r["kickoff"] < SINCE:
            continue
        fi = r.get("first") or {}
        if not fi.get("price") or fi.get("model_chance") is None or fi.get("t", 1e12) >= r["kickoff"]:
            continue
        rows.append(r)

for sport, name in SITES.items():
    R = [r for r in rows if r["sport"] == sport]
    games = {r["event_id"] for r in R}
    print(f"\n### {name}: {len(R):,} settled Paddy lines with a model chance, {len(games)} games, kick-off {datetime.fromtimestamp(min((r['kickoff'] for r in R), default=0), timezone.utc):%d %b} to {datetime.fromtimestamp(max((r['kickoff'] for r in R), default=0), timezone.utc):%d %b}\n")
    if not R:
        continue
    y = [1 if r["result"] == "win" else 0 for r in R]
    cand = {
        "Paddy (1 / first price)": [1 / r["first"]["price"] for r in R],
        "US model (model_chance)": [r["first"]["model_chance"] for r in R],
        "Site record (site_chance)": [r["first"].get("site_chance") for r in R],
        "Page chance (chance)": [r["first"].get("chance") for r in R],
    }
    print("| Chance | Lines | Said | Landed | Log loss | Brier |")
    print("|---|---|---|---|---|---|")
    for k, ps in cand.items():
        pr = [(p, t) for p, t in zip(ps, y) if p is not None]
        print(f"| {k} | {len(pr):,} | {sum(p for p, _ in pr) / len(pr):.1%} | {sum(t for _, t in pr) / len(pr):.1%} | "
              f"{sum(ll(p, t) for p, t in pr) / len(pr):.4f} | {sum((p - t) ** 2 for p, t in pr) / len(pr):.4f} |")
    # per-game paired difference, model minus Paddy
    g = defaultdict(list)
    for r, t in zip(R, y):
        g[r["event_id"]].append(ll(r["first"]["model_chance"], t) - ll(1 / r["first"]["price"], t))
    gm = [sum(v) / len(v) for v in g.values()]
    n = len(gm); m = sum(gm) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in gm) / (n - 1)) if n > 1 else float("nan")
    se = sd / math.sqrt(n) if n > 1 else float("nan")
    print(f"\nModel minus Paddy, log loss per line averaged within each game: {m:+.4f} (per-game sd {sd:.4f}, SE {se:.4f}, z {m / se:+.2f}, {n} games).")
    for gap in (0.02, 0.01):
        print(f"Games needed to detect a {gap} gap at that sd (80% power, two-sided 5%): {math.ceil(((1.96 + 0.8416) * sd / gap) ** 2)}.")
    # calibration of the model
    print("\n| Model chance | Lines | Said | Landed |")
    print("|---|---|---|---|")
    for lo, hi in ((0, .2), (.2, .4), (.4, .5), (.5, .6), (.6, .7), (.7, .8), (.8, 1.01)):
        b = [(r["first"]["model_chance"], t) for r, t in zip(R, y) if lo <= r["first"]["model_chance"] < hi]
        if b:
            print(f"| {lo:.0%} to {min(hi, 1):.0%} | {len(b):,} | {sum(p for p, _ in b) / len(b):.1%} | {sum(t for _, t in b) / len(b):.1%} |")
    # value flags, as ppcheck_us.py defines them, at the first-seen price
    for k in ("model_chance", "chance"):
        v = [(r["first"]["price"], t) for r, t in zip(R, y)
             if r["first"].get(k) is not None and r["first"][k] >= 0.5 and r["first"][k] * r["first"]["price"] - 1 >= 0.05]
        pl = sum((pr - 1) * t - (1 - t) for pr, t in v)
        print(f"\nValue by {k} (chance 50%+, 5%+ edge at first price): {len(v)} bets, won "
              f"{(sum(t for _, t in v) / len(v) if v else 0):.0%}, P/L {pl:+.1f} units, ROI {pl / max(1, len(v)):+.1%}.")
