"""
Assists 1+ and the other low-count football player lines, walked forward on the cache.

    python -B assists_watch.py --rows ROWS.json.gz     # every table in ASSISTS-WATCH.md

ROWS is acceptable_check.py's replay (`acceptable_check.py fmodel` then
`build`): every football player line on Paddy Power's menu, for every player
who played, priced before kick-off the way pplog prices it, at every chance
(not only 50% and over), and settled from the match's own statistics.

ACCEPTABLE-CHECK.md (#17) found assists 1+ at 50% or more landing 22% and
20% against 53% said, on 264 and 59 lines: too few for its 500-line rule.
This reads the whole of that line, and the other low-count lines the page
prices (to score, shots on target 2+), with 95% intervals by price band and
position, on the months before 1 September 2026 and from it.

The rule for assists 1+, fixed by the brief before this was run: it becomes a
long shot in report.py verdictOf (RUNS_HIGH) if, for starters at 50% or more
(the only lines the verdict could call acceptable), landed minus said has a
95% interval wholly below zero on the earlier months and again on the later
months. Cards are on the page too, but the cache holds no player card
counts to settle them, so they are not scored.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path

CONFIRM_FROM = int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp())
REPORT_TIDS = {17, 18, 8, 23, 35, 34, 242, 325, 7, 679, 10783}   # acceptable_check.REPORT_TIDS
LINES = {("Assists", 0.5): "Assists 1+", ("Goals", 0.5): "To score", ("Shots on target", 1.5): "Shots on target 2+"}
FAIR_BANDS = ((1.0, 1.5), (1.5, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, 10.0), (10.0, 1e9))
POSITIONS = {"F": "forwards", "M": "midfielders", "D": "defenders", "G": "goalkeepers"}
SEED = 20261024
BOOT = 1000
PERIODS = (("earlier", lambda r: r["ts"] < CONFIRM_FROM), ("later", lambda r: r["ts"] >= CONFIRM_FROM))


def load(path: Path) -> list[dict]:
    """The report competitions' lines on the stats here, priced above 0 and
    below 1 (a chance of 0 has no fair price; there are a handful)."""
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        rows = json.load(fh)
    return [r for r in rows if r.get("tid") in REPORT_TIDS and (r["stat"], r["line"]) in LINES
            and 0 < r["p"] < 1]


def match_boot(rows: list[dict], reps: int = BOOT, seed: int = SEED):
    """95% intervals for landed minus said and the return at fair,
    resampling whole matches. Works on per-match sums, so it is the same
    resample exchange_audit.cluster_boot draws, without rebuilding lists."""
    by: dict = {}
    for r in rows:
        x = by.setdefault(r["event_id"], [0, 0.0, 0.0, 0])
        x[0] += r["won"]
        x[1] += r["p"]
        x[2] += (1 / r["p"] - 1) if r["won"] else -1.0
        x[3] += 1
    ms = list(by.values())
    if len(ms) < 2:
        return (None, None), (None, None)
    rnd = random.Random(seed)
    gaps, rois = [], []
    for _ in range(reps):
        w = s_ = rt = n = 0.0
        for _ in ms:
            x = ms[rnd.randrange(len(ms))]
            w += x[0]
            s_ += x[1]
            rt += x[2]
            n += x[3]
        gaps.append((w - s_) / n)
        rois.append(rt / n)
    gaps.sort()
    rois.sort()
    lo, hi = int(0.025 * reps), min(reps - 1, int(0.975 * reps))
    return (gaps[lo], gaps[hi]), (rois[lo], rois[hi])


def band(p: float) -> str:
    f = 1 / p
    for lo, hi in FAIR_BANDS:
        if lo <= f < hi:
            return f"{lo:g} to {hi:g}" if hi < 1e8 else f"{lo:g}+"
    return "?"


def block(rows: list[dict]) -> dict:
    """Landed against said, and the return at our fair price, with 95%
    intervals resampling whole matches (lines in one match land together)."""
    n = len(rows)
    if not n:
        return {"n": 0}
    said = sum(r["p"] for r in rows) / n
    landed = sum(r["won"] for r in rows) / n
    roi = sum((1 / r["p"] - 1) if r["won"] else -1.0 for r in rows) / n
    (lo, hi), (rlo, rhi) = match_boot(rows)
    return {"n": n, "matches": len({r["event_id"] for r in rows}), "said": said, "landed": landed,
            "gap": landed - said, "lo": lo, "hi": hi, "roi": roi, "roi_lo": rlo, "roi_hi": rhi}


def rule(rows: list[dict]) -> dict:
    """The brief's rule for assists 1+, starters at 50% or more."""
    sel = [r for r in rows if r["stat"] == "Assists" and r["started"] and r["p"] >= 0.5]
    got = {name: block([r for r in sel if f(r)]) for name, f in PERIODS}
    holds = all(b.get("n") and b["hi"] is not None and b["hi"] < 0 for b in got.values())
    return {"blocks": got, "holds": holds}


def _logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def platt(rows: list[dict], iters: int = 50):
    """logit(landed) = a + b logit(said), by Newton steps from (0, 1)."""
    a, b = 0.0, 1.0
    xs = [_logit(r["p"]) for r in rows]
    ys = [1.0 if r["won"] else 0.0 for r in rows]
    for _ in range(iters):
        ga = gb = haa = hab = hbb = 0.0
        for x, y in zip(xs, ys):
            q = 1 / (1 + math.exp(-(a + b * x)))
            ga += q - y
            gb += (q - y) * x
            v = q * (1 - q)
            haa += v
            hab += v * x
            hbb += v * x * x
        det = haa * hbb - hab * hab
        da, db = (hbb * ga - hab * gb) / det, (haa * gb - hab * ga) / det
        a, b = a - da, b - db
        if abs(da) < 1e-9 and abs(db) < 1e-9:
            break
    return a, b


def map_check(rows: list[dict]) -> dict:
    """Evidence for the follow-up, not a change: a Platt map on assists 1+
    for starters, fitted on the earlier months, scored on the later."""
    sel = [r for r in rows if r["stat"] == "Assists" and r["started"]]
    fit = [r for r in sel if r["ts"] < CONFIRM_FROM]
    test = [r for r in sel if r["ts"] >= CONFIRM_FROM]
    a, b = platt(fit)
    mapped = [dict(r, p=1 / (1 + math.exp(-(a + b * _logit(r["p"]))))) for r in test]

    def ll(q):
        return -sum(math.log(r["p"] if r["won"] else 1 - r["p"]) for r in q) / len(q)
    return {"a": a, "b": b, "n": len(test), "said": sum(r["p"] for r in test) / len(test),
            "mapped": sum(r["p"] for r in mapped) / len(test),
            "landed": sum(r["won"] for r in test) / len(test), "ll_said": ll(test), "ll_mapped": ll(mapped),
            "mapped_block": block(mapped), "mapped_50": sum(1 for r in mapped if r["p"] >= 0.5)}


def _p(x, sign=False):
    return "-" if x is None else (f"{x * 100:+.1f}" if sign else f"{x * 100:.1f}") + "%"


def _iv(lo, hi):
    return "-" if lo is None else f"{lo * 100:+.1f} to {hi * 100:+.1f}"


HEAD = ("| {} | period | lines | matches | said | landed | landed minus said | 95% | return at fair | 95% |\n"
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")


def line(label, period, b):
    if not b.get("n"):
        return f"| {label} | {period} | 0 | | | | | | | |"
    return (f"| {label} | {period} | {b['n']:,} | {b['matches']:,} | {_p(b['said'])} | {_p(b['landed'])} | "
            f"{_p(b['gap'], True)} | {_iv(b['lo'], b['hi'])} | {_p(b['roi'], True)} | {_iv(b['roi_lo'], b['roi_hi'])} |")


def report(rows: list[dict]) -> str:
    out = [f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by `assists_watch.py`. Earlier: matches "
           f"before 1 September 2026; later: from it. Intervals resample whole matches, 1,000 draws.\n"]
    for (stat, ln), name in LINES.items():
        rs = [r for r in rows if r["stat"] == stat and r["line"] == ln]
        out.append(f"\n### {name}\n")
        out.append(HEAD.format("who and chance"))
        for who, f in (("starters, every chance", lambda r: r["started"]),
                       ("starters, ours 50%+", lambda r: r["started"] and r["p"] >= 0.5),
                       ("starters, under 50%", lambda r: r["started"] and r["p"] < 0.5),
                       ("came on, every chance", lambda r: not r["started"])):
            for period, g in PERIODS:
                out.append(line(who, period, block([r for r in rs if f(r) and g(r)])))
        out.append("\nStarters by fair price (one over our chance):\n")
        out.append(HEAD.format("fair price"))
        for lo, hi in FAIR_BANDS:
            lab = f"{lo:g} to {hi:g}" if hi < 1e8 else f"{lo:g}+"
            for period, g in PERIODS:
                sel = [r for r in rs if r["started"] and band(r["p"]) == lab and g(r)]
                if len(sel) >= 20:
                    out.append(line(lab, period, block(sel)))
        out.append("\nStarters by position:\n")
        out.append(HEAD.format("position"))
        for pos, lab in POSITIONS.items():
            for period, g in PERIODS:
                sel = [r for r in rs if r["started"] and r["pos"] == pos and g(r)]
                if len(sel) >= 20:
                    out.append(line(lab, period, block(sel)))
    rr = rule(rows)
    out.append("\n### The rule for assists 1+\n")
    out.append("Starters at 50% or more, landed minus said: the 95% interval must lie wholly below zero on the "
               "earlier months and on the later months.\n")
    out.append(HEAD.format("assists 1+, starters 50%+"))
    for period, b in rr["blocks"].items():
        out.append(line("assists 1+", period, b))
    out.append(f"\nHolds: {'yes' if rr['holds'] else 'no'}.")
    rec = [r for r in rows if r["stat"] == "Assists" and r["started"]]
    out.append(f"\nWhere the gap comes from, starters on assists 1+: their own record (hits over their last ten) "
               f"says {sum(r['k10'] / r['n10'] for r in rec) / len(rec):.1%}, model.price_player says "
               f"{sum(r['p'] for r in rec) / len(rec):.1%}, and {sum(r['won'] for r in rec) / len(rec):.1%} landed.")
    m = map_check(rows)
    out.append("\n### Evidence for a follow-up: a Platt map on assists 1+\n")
    out.append(f"Fitted on the earlier months' starters: logit(chance) = {m['a']:+.3f} {m['b']:+.3f} x logit(ours). "
               f"On the later months ({m['n']:,} starter lines): ours said {m['said']:.1%}, mapped {m['mapped']:.1%}, "
               f"landed {m['landed']:.1%}; log loss {m['ll_said']:.4f} as now, {m['ll_mapped']:.4f} mapped. "
               f"Mapped, {m['mapped_50']} later lines would be at 50% or more. Not wired in here.\n")
    out.append(HEAD.format("assists 1+, starters, mapped"))
    out.append(line("every chance", "later", m["mapped_block"]))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", required=True, help="acceptable_check.py build output")
    args = ap.parse_args(argv)
    print(report(load(Path(args.rows))))


if __name__ == "__main__":
    main()
