"""
Walk-forward check of darts_legs.py against what is live.

    python darts_legs_backtest.py --cache DIR            # every table in DARTS-MODEL.md
    python darts_legs_backtest.py --cache DIR --tune     # refit LEG and STATS on the tuning window

DIR is an unpacked cache_backtest.tar.zst (or the live cache/). Nothing is
fetched. Every price is made from matches strictly before the one priced.

Two comparisons:
  match markets  darts_model.Ratings (the leg Elo on the Match tab) against
                 darts_legs.LegRatings, on winner, exact score, total legs
                 and handicap
  stat lines     the record price the site bets on, (hits + 0.5) / (n + 1)
                 over the last 20 matches, against darts_legs stat_chance,
                 on the cache and on the settled darts legs in best_bets.json

Tuning uses matches before TUNE_END only; every headline figure is on
matches after it.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path

import darts_legs as L
import darts_model as dm

HERE = Path(__file__).resolve().parent
TUNE_END = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()          # match markets
STAT_TUNE_END = datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp()     # stat lines (stats are thin before)
MIN_PRIOR = 10
EPS = 1e-6

LINES = {
    "Thrown 180": [0.5, 1.5, 2.5, 3.5, 4.5, 5.5],
    "Checkouts over 100": [0.5, 1.5, 2.5],
    "Highest checkout": [80.5, 90.5, 100.5, 110.5, 120.5],
    "Average 3 darts": [85.5, 88.5, 91.5, 94.5, 97.5],
}


def _ll(p, y):
    p = min(max(p, EPS), 1 - EPS)
    return -math.log(p if y else 1 - p)


def bootstrap_diff(a: list, b: list, groups: list | None = None, reps: int = 2000, seed: int = 7):
    """Mean of a - b with a 95% interval, resampling groups (matches) so
    several lines on one match are not counted as independent."""
    rnd = random.Random(seed)
    if groups is None:
        groups = list(range(len(a)))
    by = {}
    for x, y, g in zip(a, b, groups):
        by.setdefault(g, []).append(x - y)
    keys = list(by)
    sums = [(sum(v), len(v)) for v in (by[k] for k in keys)]
    tot = sum(s for s, _ in sums) / sum(n for _, n in sums)
    draws = []
    for _ in range(reps):
        s = n = 0
        for _ in keys:
            x = sums[rnd.randrange(len(keys))]
            s += x[0]
            n += x[1]
        draws.append(s / n)
    draws.sort()
    return tot, draws[int(0.025 * reps)], draws[int(0.975 * reps) - 1]


def calibration(rows, bins=(0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.0001)):
    """rows of (p, outcome) -> [(lo, hi, n, mean p, rate)]"""
    out = []
    for lo, hi in zip(bins, bins[1:]):
        sel = [(p, y) for p, y in rows if lo <= p < hi]
        if sel:
            out.append((lo, min(hi, 1.0), len(sel), sum(p for p, _ in sel) / len(sel),
                        sum(y for _, y in sel) / len(sel)))
    return out


def ece(rows):
    n = len(rows)
    return sum(c * abs(mp - r) for _, _, c, mp, r in calibration(rows)) / n if n else float("nan")


# ------------------------------------------------------------ match markets

def match_rows(ms, leg_params=None, elo_params=None, start=0, end=9e12):
    """One row per finished match in [start, end) with both players on
    MIN_PRIOR earlier matches (the rule darts_model already scores by),
    priced by both models as of that morning."""
    elo = dm.Ratings(ms, elo_params)
    new = L.LegRatings(ms, leg_params)
    rows = []
    for m, g_elo, p_elo, won in elo.preds:
        if not (start <= m["ts"] < end) or m["id"] not in new.preds:
            continue
        if not isinstance(m.get("la"), int):
            continue
        mu, var = new.preds[m["id"]]
        fmt = m["fmt"]
        d_new = L.match_distribution(mu, var, fmt, new.p["throw"])
        s_new = L.summarise(d_new, fmt)
        row = {"m": m, "won": won, "p_elo": p_elo, "p_new": s_new["win"], "fmt": fmt}
        if fmt[0] == "legs":
            d_elo = dm.score_distribution(g_elo, fmt, elo.params["throw"])
            row["score_elo"] = d_elo.get((m["sa"], m["sb"]), EPS)
            row["score_new"] = sum(p for (a, b, _, _), p in d_new.items() if (a, b) == (m["sa"], m["sb"]))
            n = fmt[1]
            line = math.floor(n * 1.5) + 0.5
            tot = m["sa"] + m["sb"]
            row["over_line"] = line
            row["over"] = tot > line
            row["over_elo"] = sum(p for (a, b), p in d_elo.items() if a + b > line)
            row["over_new"] = sum(p for t, p in s_new["totalLegs"].items() if t > line)
            row["hcp"] = (m["sa"] - m["sb"]) > 1.5
            row["hcp_elo"] = sum(p for (a, b), p in d_elo.items() if a - b > 1.5)
            row["hcp_new"] = sum(p for (a, b, _, _), p in d_new.items() if a - b > 1.5)
        rows.append(row)
    return rows


def match_loss(rows):
    w = sum(_ll(r["p_new"], r["won"]) for r in rows) / len(rows)
    legs = [r for r in rows if "score_new" in r]
    s = sum(-math.log(max(r["score_new"], EPS)) for r in legs) / max(len(legs), 1)
    return w + s


def tune_legs(ms):
    best = None
    # A first pass over new (-0.45 to -0.25), var0 (0.1 to 0.3), q (0.0002
    # to 0.001), tau2 (0 to 0.08) and throw (0.4 to 0.6) ended on the edge
    # of every range, so this is the second pass, around that corner.
    grid = itertools.product((-0.1, -0.25), (0.03, 0.06, 0.1), (0.00005, 0.0001, 0.0002),
                             (0.08, 0.15, 0.3), (0.6, 0.7), (0.6, 0.7, 0.85, 1.0))
    for new, var0, q, tau2, th, c in grid:
        prm = {"new": new, "var0": var0, "q": q, "tau2": tau2, "throw": th, "slope": c}
        rows = match_rows(ms, prm, end=TUNE_END)
        loss = match_loss(rows)
        if best is None or loss < best[0]:
            best = (loss, prm)
            print(f"  {loss:.4f} {prm}", flush=True)
    return best


# --------------------------------------------------------------- stat lines

def stat_rows(ms, leg_params=None, stat_params=None, start=0, end=9e12, min_n=10):
    """Every (match, player, stat, line) on matches with statistics, both
    prices made from what was known before the match."""
    new = L.LegRatings(ms, leg_params)
    book = L.StatBook([], stat_params)
    rows = []
    for m in ms:
        if m["status"] != "finished":
            continue
        ok = m.get("stats") and isinstance(m.get("la"), int) and m["id"] in new.preds
        if ok and start <= m["ts"] < end:
            mu, var = new.preds[m["id"]]
            dist = L.match_distribution(mu, var, m["fmt"], new.p["throw"])
            tour = book.tour_rates(m["ts"])
            for side, pid in (("a", m["a"]), ("b", m["b"])):
                hist = book.history(pid, m["ts"])
                pl = book.player(pid, m["ts"], tour)
                actual = m["stats"][side]
                for stat, lines in LINES.items():
                    y = actual.get(stat)
                    if y is None:
                        continue
                    for line in lines:
                        rec, n = L.record_chance(hist, stat, line)
                        if rec is None or n < min_n:
                            continue
                        pn = L.stat_chance(stat, line, side, dist, pl, book, m["ts"], tour)
                        rows.append({"id": m["id"], "stat": stat, "line": line, "y": y > line,
                                     "p_rec": rec, "p_new": pn, "fmt": m["fmt"], "ts": m["ts"]})
        book.add(m)
    return rows


def tune_stats(ms, leg_params=None):
    base = dict(L.STATS)
    for key, vals, stat in (("m180", (20, 40, 80, 160, 320), "Thrown 180"),
                            ("k180", (8, 12, 25, 50, 1000), "Thrown 180"),
                            ("m100", (10, 25, 50, 100), "Checkouts over 100"),
                            ("mhc", (15, 30, 60, 120, 240), "Highest checkout"),
                            ("mavg", (0.5, 1, 2, 4), "Average 3 darts"),
                            ("window", (10, 20, 40), None)):
        best = None
        for v in vals:
            prm = dict(base, **{key: v})
            rows = stat_rows(ms, leg_params, prm, end=STAT_TUNE_END)
            rows = [r for r in rows if stat is None or r["stat"] == stat]
            loss = sum(_ll(r["p_new"], r["y"]) for r in rows) / len(rows)
            if best is None or loss < best[0]:
                best = (loss, v)
        base[key] = best[1]
        print(f"  {key} -> {best[1]}  ({best[0]:.4f})", flush=True)
    return base


# ----------------------------------------------------- settled record

def settled_rows(ms, leg_params=None, stat_params=None):
    """The darts legs the site actually put up and settled, priced again by
    the new model as of kick-off. One row per distinct selection."""
    bets = json.loads((HERE / "best_bets.json").read_text())
    legs = {}
    for b in bets:
        if b.get("sport") != "darts":
            continue
        for leg in b["legs"]:
            if leg.get("result") not in ("win", "lose"):
                continue
            key = (leg["event_id"], leg["team"], leg["stat"], leg["line"], leg["over"])
            legs[key] = leg
    by_id = {m["id"]: m for m in ms}
    new = L.LegRatings(ms, leg_params)
    book = L.StatBook(ms, stat_params)
    rows = []
    for (eid, team, stat, line, over), leg in legs.items():
        m = by_id.get(eid)
        rec = 1 / leg["fair"]
        row = {"id": eid, "stat": stat, "line": line, "over": over,
               "y": leg["result"] == "win", "p_rec": rec, "p_new": None,
               "chance": leg.get("chance"), "n": leg.get("total")}
        if m and m["fmt"] and m["id"] in new.preds:
            side = "a" if m["a_name"] == team else "b" if m["b_name"] == team else None
            if side:
                mu, var = new.preds[m["id"]]
                dist = L.match_distribution(mu, var, m["fmt"], new.p["throw"])
                tour = book.tour_rates(m["ts"])
                pl = book.player(m[side], m["ts"], tour)
                p = L.stat_chance(stat, line, side, dist, pl, book, m["ts"], tour)
                if p is not None:
                    row["p_new"] = p if over else 1 - p
                    row["fmt"] = m["fmt"]
        rows.append(row)
    return rows


# ------------------------------------------------------------------ report

def cal_lines(rows, key_cur, key_new, label_cur="current", label_new="new"):
    """Side-by-side calibration: for each 10-point band of stated chance, how
    many, what was said and what landed, for both."""
    lines = [f"| stated | {label_cur} n | said | landed | {label_new} n | said | landed |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    ca = {(lo, round(hi, 1)): x for lo, hi, *x in calibration([(r[key_cur], r["y"]) for r in rows])}
    cb = {(lo, round(hi, 1)): x for lo, hi, *x in calibration([(r[key_new], r["y"]) for r in rows])}
    for k in sorted(set(ca) | set(cb)):
        x, y = ca.get(k), cb.get(k)
        fx = f"{x[0]} | {x[1]:.3f} | {x[2]:.3f}" if x else "0 | - | -"
        fy = f"{y[0]} | {y[1]:.3f} | {y[2]:.3f}" if y else "0 | - | -"
        lines.append(f"| {k[0] * 100:.0f}-{k[1] * 100:.0f}% | {fx} | {fy} |")
    return lines


def compare(rows, key_cur, key_new, title, groups_key="id"):
    """Log loss, Brier and expected calibration error for both, with the
    paired 95% interval on the log-loss difference."""
    rows = [r for r in rows if r.get(key_new) is not None and r.get(key_cur) is not None]
    y = [r["y"] for r in rows]
    lc = [_ll(r[key_cur], v) for r, v in zip(rows, y)]
    ln = [_ll(r[key_new], v) for r, v in zip(rows, y)]
    bc = sum((r[key_cur] - v) ** 2 for r, v in zip(rows, y)) / len(rows)
    bn = sum((r[key_new] - v) ** 2 for r, v in zip(rows, y)) / len(rows)
    d, lo, hi = bootstrap_diff(ln, lc, [r[groups_key] for r in rows])
    ec = ece([(r[key_cur], r["y"]) for r in rows])
    en = ece([(r[key_new], r["y"]) for r in rows])
    return {"title": title, "n": len(rows), "matches": len({r[groups_key] for r in rows}),
            "ll_cur": sum(lc) / len(lc), "ll_new": sum(ln) / len(ln), "diff": d, "lo": lo, "hi": hi,
            "brier_cur": bc, "brier_new": bn, "ece_cur": ec, "ece_new": en}


def fmt_compare(c):
    return (f"| {c['title']} | {c['n']} | {c['matches']} | {c['ll_cur']:.4f} | {c['ll_new']:.4f} | "
            f"{c['diff']:+.4f} ({c['lo']:+.4f} to {c['hi']:+.4f}) | {c['brier_cur']:.4f} | {c['brier_new']:.4f} | "
            f"{c['ece_cur']:.3f} | {c['ece_new']:.3f} |")


HEAD = ["| market | rows | matches | log loss current | log loss new | new minus current (95%) | "
        "Brier current | Brier new | ECE current | ECE new |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]


def report(ms) -> str:
    out = []
    mr = match_rows(ms, start=TUNE_END)
    win = [{"id": r["m"]["id"], "y": r["won"], "cur": r["p_elo"], "new": r["p_new"]} for r in mr]
    legs = [r for r in mr if "score_new" in r]
    out.append(f"## Match markets, {len(mr)} matches from 1 January 2026, both players on {MIN_PRIOR}+ earlier matches\n")
    out += HEAD
    out.append(fmt_compare(compare(win, "cur", "new", "match winner")))
    over = [{"id": r["m"]["id"], "y": r["over"], "cur": r["over_elo"], "new": r["over_new"]} for r in legs]
    out.append(fmt_compare(compare(over, "cur", "new", "total legs over the middle line")))
    hcp = [{"id": r["m"]["id"], "y": r["hcp"], "cur": r["hcp_elo"], "new": r["hcp_new"]} for r in legs]
    out.append(fmt_compare(compare(hcp, "cur", "new", "first-listed player -1.5 legs")))
    sc = [-math.log(max(r["score_elo"], EPS)) for r in legs]
    sn = [-math.log(max(r["score_new"], EPS)) for r in legs]
    d, lo, hi = bootstrap_diff(sn, sc, [r["m"]["id"] for r in legs])
    out.append(f"\nExact score, {len(legs)} legs-format matches: log loss current {sum(sc) / len(sc):.4f}, "
               f"new {sum(sn) / len(sn):.4f}, new minus current {d:+.4f} (95% {lo:+.4f} to {hi:+.4f}).\n")
    out.append("\nMatch winner calibration (chance for the player listed first):\n")
    out += cal_lines(win, "cur", "new", "Elo", "new")
    out.append("\nTotal legs over the middle line:\n")
    out += cal_lines(over, "cur", "new", "Elo", "new")

    sr = stat_rows(ms, start=STAT_TUNE_END)
    out.append(f"\n## Stat lines on the cache, matches from 1 July 2026 ({len({r['id'] for r in sr})} matches)\n")
    out.append("Every player with 10+ earlier matches with statistics, at the fixed ladder of lines in "
               "LINES, over side (the under is the same bet turned round).\n")
    out += HEAD
    allc = compare(sr, "p_rec", "p_new", "all four")
    out.append(fmt_compare(allc))
    for stat in LINES:
        out.append(fmt_compare(compare([r for r in sr if r["stat"] == stat], "p_rec", "p_new", stat)))
    mid = [r for r in sr if 0.25 <= r["p_rec"] <= 0.75]
    out.append(fmt_compare(compare(mid, "p_rec", "p_new", "lines the record puts at 25-75%")))
    long_ = [r for r in sr if r["fmt"] != ("legs", 6)]
    out.append(fmt_compare(compare(long_, "p_rec", "p_new", "matches not first to 6")))
    for stat in LINES:
        out.append(f"\n{stat}, calibration:\n")
        out += cal_lines([r for r in sr if r["stat"] == stat], "p_rec", "p_new", "record", "new")

    st = settled_rows(ms)
    priced = [r for r in st if r["p_new"] is not None]
    out.append("\n## The settled darts record (best_bets.json)\n")
    out.append(f"{len(st)} distinct settled darts selections; {len(priced)} on matches in the cache "
               f"that the new model can price. Hit rate {sum(r['y'] for r in st) / len(st):.3f}, "
               f"said {sum(r['p_rec'] for r in st) / len(st):.3f}.\n")
    out += HEAD
    out.append(fmt_compare(compare(priced, "p_rec", "p_new", "settled, all")))
    for stat in LINES:
        sel = [r for r in priced if r["stat"] == stat]
        if sel:
            out.append(fmt_compare(compare(sel, "p_rec", "p_new", stat)))
    out.append("\nCalibration on the settled record:\n")
    out += cal_lines(priced, "p_rec", "p_new", "record", "new")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(HERE / "cache"))
    ap.add_argument("--tune", action="store_true")
    args = ap.parse_args()
    ms = L.load_matches(Path(args.cache))
    if args.tune:
        print("leg model, tuning window to", datetime.fromtimestamp(TUNE_END).date())
        loss, prm = tune_legs(ms)
        print("best", prm)
        print("stat lines, tuning window to", datetime.fromtimestamp(STAT_TUNE_END).date())
        print("best", tune_stats(ms, prm))
        return
    print(report(ms))


if __name__ == "__main__":
    main()
