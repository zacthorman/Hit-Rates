"""
Does Paddy Power's Super Sub chance stay calibrated on top of the
recalibrated to-score chance?

    python -B supersub_check.py --code DIR --cache CACHE --audit PKL [--rows ROWS.json]   # every table in SUPERSUB-CHECK.md
    python -B supersub_check.py --from-rows ROWS.json                                   # the same, from saved rows

DIR is a checkout holding both supersub.py (bookie-imports) and
scorer_audit.py with the recalibrated to-score path (rule-review, which
carries scorer-audit). PKL is scorer_audit.py's replay (`scorer_audit.py
build`, cache/scorer_audit.pkl): every starter's fmodel to-score chance, made
with only what was known before kick-off. CACHE is the unpacked
cache_backtest.tar.zst the replay was built from. Nothing is fetched and
nothing live is changed.

What is checked. For every starter from 1 July 2026 (where fmodel is out of
sample), the chance the page now logs for a Paddy Power anytime goalscorer
line is

    own + (1 - own) x s x rep          (supersub.chance)

own is fmodel's chance (scorer-audit set its tonight.html weight to 1.0 for
to score, and pplog uses fmodel where it has one), s is his share of starts
ending before 85 minutes in his record, from his own earlier starts only
(supersub.sub_rate, five starts or more), and rep is the chance a
replacement for his position scores. rep is refitted before each month on
earlier matches only; the figures shipped in supersub_fit.json are fitted on
the whole cache, the months tested here included, and are scored as well.

Settlement is Super Sub's: he scored, or he started, came off and his
replacement scored. The cache keeps line-ups but not substitution incidents,
so the replacement is found the way supersub.fit finds it (the first starter
off is paired with the substitute who played longest). As a check on that
pairing, a looser settlement counts a goal by any substitute who came on
within three minutes of his exit.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

OOS_FROM = int(datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp())
WINDOW = 38          # appearances behind a player's record (update.json "games")
EDGE = 0.05          # #13: an edge of 5% or more either way is marked avoid
SEED = 20261023
BOOT = 2000
EPS = 1e-6
PRICE_BANDS = [(1.0, 2.5), (2.5, 4.0), (4.0, 7.0), (7.0, 12.0), (12.0, 25.0), (25.0, 1e9)]
CHANCE_BANDS = [0, .05, .1, .15, .2, .3, .4, .5, 1.0001]


def month_of(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m")


def night_of(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


# ------------------------------------------------------------ line-ups

def _when(cache: Path) -> dict:
    when = {}
    for f in glob.glob(str(cache / "team_*_events_last_*.json")):
        try:
            for e in json.loads(Path(f).read_text()).get("events") or []:
                if ((e.get("homeTeam") or {}).get("sport") or {}).get("slug") in (None, "football"):
                    when[e["id"]] = e.get("startTimestamp") or 0
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return when


def side_rows(side: dict, pairs) -> list[dict]:
    """One row per player who appeared, with what settlement needs: did he
    start, minutes, scored, taken off, and whether his paired replacement or
    any substitute on within three minutes of his exit scored.

    `pairs` is supersub._pairs, so the pairing is the live fit's own."""
    ps = side.get("players") or []

    def mins(p):
        return (p.get("statistics") or {}).get("minutesPlayed") or 0

    def goals(p):
        return ((p.get("statistics") or {}).get("goals") or 0) > 0

    out = []
    paired = pairs(side)
    starters = {id(p) for p, _ in paired}
    full = max((mins(p) for p, _ in paired), default=0)
    subs = [p for p in ps if p.get("substitute") and mins(p) > 0]
    for p, rep in paired:
        st = p.get("statistics") or {}
        if "minutesPlayed" not in st:
            continue
        m = mins(p)
        off = m < 85 and rep is not None
        near = [q for q in subs if abs((full - mins(q)) - m) <= 3]
        out.append({"pid": (p.get("player") or {}).get("id"), "pos": p.get("position"), "started": True,
                    "minutes": m, "scored": goals(p), "off": off,
                    "rep_scored": bool(off and goals(rep)),
                    "near_scored": bool(m < 85 and any(goals(q) for q in near))})
    for p in ps:
        if id(p) in starters or not mins(p):
            continue
        out.append({"pid": (p.get("player") or {}).get("id"), "pos": p.get("position"), "started": False,
                    "minutes": mins(p), "scored": goals(p), "off": False,
                    "rep_scored": False, "near_scored": False})
    return out


def load_lineups(cache: Path, supersub) -> list[tuple]:
    """(ts, event id, rows) for every football line-up with a full XI, oldest first."""
    when = _when(cache)
    games = []
    for f in glob.glob(str(cache / "event_*_lineups.json")):
        try:
            eid = int(Path(f).name.split("_")[1])
        except (IndexError, ValueError):
            continue
        if eid not in when:
            continue
        try:
            lu = json.loads(Path(f).read_text())
        except (OSError, ValueError):
            continue
        rows = []
        for side in ("home", "away"):
            rows += side_rows(lu.get(side) or {}, supersub._pairs)
        if rows:
            games.append((when[eid], eid, rows))
    games.sort(key=lambda g: (g[0], g[1]))
    return games


# ------------------------------------------------------------ the replay

def rep_fit(games, before: float) -> dict:
    """Position -> P(replacement scores | he went off without scoring), on
    matches before `before` only. supersub.fit's figure, walk-forward."""
    c = collections.defaultdict(lambda: [0, 0])
    for ts, _, rows in games:
        if ts >= before:
            break
        for r in rows:
            if r["started"] and r["off"] and not r["scored"]:
                c[r["pos"]][0] += 1
                c[r["pos"]][1] += r["rep_scored"]
    return {k: (v[1] / v[0] if v[0] else 0.0) for k, v in c.items() if k in ("G", "D", "M", "F")}


def replay(games, own: dict, supersub, shipped: dict) -> list[dict]:
    """One row per starter from OOS_FROM with an fmodel chance.

    s and position come from his appearances before the match, as
    pplog.snapshot passes squads[t][name] to supersub.uplift."""
    hist = collections.defaultdict(list)
    fits = {}
    out = []
    for ts, eid, rows in games:
        if ts >= OOS_FROM:
            m = month_of(ts)
            if m not in fits:
                start = datetime.strptime(m + "-01", "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
                fits[m] = rep_fit(games, start)
            for r in rows:
                if not r["started"]:
                    continue
                p_own = own.get((eid, r["pid"]))
                if p_own is None:
                    continue
                played = hist[r["pid"]][-WINDOW:]
                s = supersub.sub_rate(played)
                starts = [g for g in played if g["started"] and g["minutes"] > 0]
                pos = supersub.position_of(played)
                rep_wf = fits[m].get(pos or "")
                rep_sh = shipped.get(pos or "")
                p_wf = supersub.chance(p_own, s, rep_wf) if s is not None and rep_wf else p_own
                p_sh = supersub.chance(p_own, s, rep_sh) if s is not None and rep_sh else p_own
                out.append({"night": night_of(ts), "month": m, "game": eid, "pid": r["pid"],
                            "pos": pos or r["pos"] or "?", "own": p_own, "s": s,
                            "rep_wf": rep_wf, "ss": p_wf, "ss_shipped": p_sh,
                            "scored": int(r["scored"]),
                            "won": int(r["scored"] or r["rep_scored"]),
                            "won_near": int(r["scored"] or r["near_scored"]),
                            "off": int(r["off"]), "starts": len(starts),
                            "offs": sum(1 for g in starts if g["minutes"] < 85)})
        for r in rows:
            hist[r["pid"]].append({"started": r["started"], "minutes": r["minutes"], "position": r["pos"]})
    return out


def load_own(pkl: Path) -> dict:
    """(match, pid) -> fmodel's to-score chance, starters only, from the replay."""
    import pandas as pd
    D = pd.read_pickle(pkl)
    D = D[(D.starter == 1) & D.fm_goals_1.notna() & (D.ts >= OOS_FROM)]
    return {(int(m), int(p)): float(x) for m, p, x in zip(D.match, D.pid, D.fm_goals_1)}


# ------------------------------------------------------------ measures

def log_loss(ps, ys) -> float:
    t = 0.0
    for p, y in zip(ps, ys):
        p = min(max(p, EPS), 1 - EPS)
        t -= math.log(p if y else 1 - p)
    return t / max(len(ys), 1)


def wilson(k, n, z=1.96):
    if not n:
        return float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def _boot(rows, stat, seed=SEED, reps=BOOT):
    """stat(list of per-night aggregates) with a 95% interval, resampling nights."""
    by = collections.defaultdict(list)
    for r in rows:
        by[r["night"]].append(r)
    nights = list(by.values())
    point = stat(nights)
    if len(nights) < 2:
        return point, float("nan"), float("nan")
    rnd = random.Random(seed)
    draws = sorted(stat([nights[rnd.randrange(len(nights))] for _ in nights]) for _ in range(reps))
    return point, draws[int(0.025 * reps)], draws[int(0.975 * reps) - 1]


def ratio(rows, y="won", p="ss"):
    """landed / said, by night."""
    def f(nights):
        a = sum(r[y] for n in nights for r in n)
        b = sum(r[p] for n in nights for r in n)
        return a / b if b else float("nan")
    return _boot(rows, f)


def ll_diff(rows, a, b, y="won"):
    """log loss of a minus log loss of b, per row, by night."""
    def f(nights):
        s = n_ = 0
        for n in nights:
            for r in n:
                s += log_loss([r[a]], [r[y]]) - log_loss([r[b]], [r[y]])
                n_ += 1
        return s / n_ if n_ else float("nan")
    return _boot(rows, f)


def _f(x, d=3):
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{d}f}"


def _ci(t, d=2, signed=False):
    fmt = (lambda v: f"{v:+.{d}f}") if signed else (lambda v: f"{v:.{d}f}")
    return f"{fmt(t[0])} ({fmt(t[1])} to {fmt(t[2])})"


SUMMARY_HEAD = ["| set | starters | nights | landed (Super Sub) | 95% Wilson | said, Super Sub | landed / said (95% by night) "
                "| log loss, Super Sub | log loss, own chance only | Super Sub minus own (95% by night) |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]


def summary_row(label, rows, y="won", p="ss"):
    n = len(rows)
    if not n:
        return f"| {label} | 0 | | | | | | | | |"
    k = sum(r[y] for r in rows)
    lo, hi = wilson(k, n)
    return (f"| {label} | {n:,} | {len({r['night'] for r in rows})} | {k / n:.1%} | {lo:.1%} to {hi:.1%} | "
            f"{sum(r[p] for r in rows) / n:.1%} | {_ci(ratio(rows, y, p))} | "
            f"{log_loss([r[p] for r in rows], [r[y] for r in rows]):.4f} | "
            f"{log_loss([r['own'] for r in rows], [r[y] for r in rows]):.4f} | "
            f"{_ci(ll_diff(rows, p, 'own', y), 4, True)} |")


def band_of(x, bands):
    for lo, hi in bands:
        if lo <= x < hi:
            return lo, hi
    return None


def price_label(lo, hi):
    return f"{lo:g} to {hi:g}" if hi < 1e8 else f"{lo:g}+"


def calibration(rows, p="ss", y="won"):
    out = ["| chance | starters | said | landed | 95% Wilson |", "|---|---:|---:|---:|---:|"]
    for lo, hi in zip(CHANCE_BANDS, CHANCE_BANDS[1:]):
        sel = [r for r in rows if lo <= r[p] < hi]
        if not sel:
            continue
        k = sum(r[y] for r in sel)
        a, b = wilson(k, len(sel))
        out.append(f"| {lo:.0%} to {min(hi, 1):.0%} | {len(sel):,} | {sum(r[p] for r in sel) / len(sel):.1%} | "
                   f"{k / len(sel):.1%} | {a:.1%} to {b:.1%} |")
    return out


def extra_rows(rows):
    """The uplift on its own: starters who did not score, where Super Sub
    applied, predicted s x rep against whether the replacement scored."""
    out = []
    for r in rows:
        if r["scored"] or r["s"] is None or not r["rep_wf"]:
            continue
        out.append(dict(r, said_extra=r["s"] * r["rep_wf"], paid=r["won"], paid_near=r["won_near"]))
    return out


def verdict(p: float, price: float) -> str:
    """report.py verdictOf for a Paddy Power player line (#13): avoid when
    the price is 5% or more worse than our chance; long under 50%, whatever
    the edge; avoid when it is 5% or more better; acceptable otherwise."""
    e = p * price - 1
    if e < -EDGE:
        return "avoid"
    if p < 0.5:
        return "long"
    if e >= EDGE:
        return "avoid"
    return "ok"


def verdict_changes(rows, margins=(0.0, 0.05, 0.10, 0.15, 0.20, 0.30)):
    """How Super Sub moves the verdict, line by line.

    There is no record of Paddy Power goalscorer prices to replay (pplog/
    is not in the repository and pp-results.html holds one settled
    to-score line), so the price is a scenario: Paddy Power's price set off
    the starter's own chance with a margin m, price = 1 / (own x (1 + m)).
    Each line is given the verdict on its own chance and on its Super Sub
    chance at that price. Returns [(m, n, Counter of (before, after))]."""
    out = []
    for m in margins:
        c = collections.Counter()
        x = [r for r in rows if r["own"] > 0]
        for r in x:
            price = 1 / (r["own"] * (1 + m))
            c[(verdict(r["own"], price), verdict(r["ss"], price))] += 1
        out.append((m, len(x), c))
    return out


# ------------------------------------------------------------ report

FIX_FROM = "2026-09"     # fixes fitted on July and August, scored on September and October


def pos_off_rate(rows, before: str) -> dict:
    """Position -> share of starts ending before 85 minutes, from the
    records behind rows earlier than `before` (pre-match figures only)."""
    c = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        if r["month"] < before and r["starts"]:
            c[r["pos"]][0] += r["starts"]
            c[r["pos"]][1] += r["offs"]
    return {k: v[1] / v[0] for k, v in c.items() if v[0]}


def fixed(r, k=0.0, c=1.0, prior=None):
    """The Super Sub chance with s shrunk towards his position's rate by k
    pseudo-starts and the uplift scaled by c. k = 0, c = 1 is supersub.chance."""
    if r["s"] is None or not r["rep_wf"]:
        return r["own"]
    s = r["s"]
    if k and prior and r["pos"] in prior:
        s = (r["offs"] + k * prior[r["pos"]]) / (r["starts"] + k)
    return min(1 - EPS, r["own"] + (1 - r["own"]) * s * r["rep_wf"] * c)


def fix_check(rows):
    """Fit k and c on months before FIX_FROM, score them on FIX_FROM on."""
    train = [r for r in rows if r["month"] < FIX_FROM and r["s"] is not None and r["rep_wf"]]
    test = [r for r in rows if r["month"] >= FIX_FROM and r["s"] is not None and r["rep_wf"]]
    prior = pos_off_rate(rows, FIX_FROM)
    ys = [r["won"] for r in train]
    best = min(((k, c) for k in (0, 2, 5, 10, 20, 40) for c in (0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5)),
               key=lambda kc: log_loss([fixed(r, kc[0], kc[1], prior) for r in train], ys))
    k, c = best
    for r in test:
        r["ss_fix"] = fixed(r, k, c, prior)
    return k, c, prior, train, test


def report(rows) -> str:
    out = []
    w = out.append
    covered = [r for r in rows if r["s"] is not None and r["rep_wf"]]
    w(f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by `supersub_check.py`. Intervals "
      f"resample whole nights, {BOOT} draws, seed {SEED}.\n")
    w(f"{len(rows):,} starters with an fmodel to-score chance, {len({r['game'] for r in rows}):,} matches, "
      f"{len({r['night'] for r in rows})} nights, {min(r['night'] for r in rows)} to {max(r['night'] for r in rows)}. "
      f"{len(covered):,} of them had five or more earlier starts and an outfield position, so Super Sub adds to their "
      f"chance; the rest are priced on their own chance, as supersub.uplift does.\n")

    w("### 1. The chance against Super Sub settlement\n")
    out.extend(SUMMARY_HEAD)
    w(summary_row("every starter", rows))
    w(summary_row("where Super Sub adds", covered))
    w(summary_row("where Super Sub adds, shipped supersub_fit.json", covered, p="ss_shipped"))
    w(summary_row("where Super Sub adds, looser settlement", covered, y="won_near"))
    w("\nFor reference, the own chance against the player's own goals on the same rows: "
      f"said {sum(r['own'] for r in covered) / len(covered):.1%}, scored "
      f"{sum(r['scored'] for r in covered) / len(covered):.1%}, landed / said "
      f"{_ci(ratio(covered, 'scored', 'own'))}.\n")

    w("### 2. By position\n")
    out.extend(SUMMARY_HEAD)
    for pos in ("F", "M", "D", "G"):
        sel = [r for r in rows if r["pos"] == pos]
        if sel:
            w(summary_row({"F": "forwards", "M": "midfielders", "D": "defenders", "G": "goalkeepers"}[pos], sel))

    w("\n### 3. By fair price (one over the Super Sub chance)\n")
    out.extend(SUMMARY_HEAD)
    for lo, hi in PRICE_BANDS:
        sel = [r for r in covered if band_of(1 / max(r["ss"], EPS), [(lo, hi)])]
        if sel:
            w(summary_row(price_label(lo, hi), sel))
    w("\nForwards and midfielders by price:\n")
    out.extend(SUMMARY_HEAD)
    for pos in ("F", "M"):
        for lo, hi in PRICE_BANDS:
            sel = [r for r in covered if r["pos"] == pos and band_of(1 / max(r["ss"], EPS), [(lo, hi)])]
            if len(sel) >= 50:
                w(summary_row(f"{pos}, {price_label(lo, hi)}", sel))

    w("\n### 4. Calibration of the Super Sub chance\n")
    out.extend(calibration(covered))

    w("\n### 5. The uplift on its own\n")
    w("Starters who did not score, where Super Sub applied: the predicted s x rep (the chance the bet is "
      "won by his replacement) against how often it was.\n")
    ex = extra_rows(rows)
    w("| set | starters | said | paid | landed / said (95% by night) | paid, looser settlement |")
    w("|---|---:|---:|---:|---:|---:|")

    def ex_row(label, sel):
        if not sel:
            return
        n = len(sel)
        w(f"| {label} | {n:,} | {sum(r['said_extra'] for r in sel) / n:.2%} | {sum(r['paid'] for r in sel) / n:.2%} | "
          f"{_ci(ratio(sel, 'paid', 'said_extra'))} | {sum(r['paid_near'] for r in sel) / n:.2%} |")
    ex_row("all", ex)
    for pos in ("F", "M", "D"):
        ex_row({"F": "forwards", "M": "midfielders", "D": "defenders"}[pos], [r for r in ex if r["pos"] == pos])
    for lo, hi in ((0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)):
        ex_row(f"taken off {lo:.0%} to {min(hi, 1):.0%} of starts", [r for r in ex if lo <= r["s"] < hi])
    w("\nAnd how often he went off when he did not score, against the record's s:\n")
    w("| set | starters | s said | went off |")
    w("|---|---:|---:|---:|")
    for pos in ("F", "M", "D"):
        sel = [r for r in ex if r["pos"] == pos]
        if sel:
            w(f"| {pos} | {len(sel):,} | {sum(r['s'] for r in sel) / len(sel):.1%} | "
              f"{sum(r['off'] for r in sel) / len(sel):.1%} |")

    w("\n### 6. A fix to the uplift, fitted on July and August, scored on September and October\n")
    k, c, prior, train, test = fix_check(rows)
    w(f"s shrunk towards the position's own rate ({', '.join(f'{p} {v:.1%}' for p, v in sorted(prior.items()) if p in 'DMF')}) "
      f"by k pseudo-starts, and the uplift multiplied by c. Fitted on {len(train):,} starters: k = {k:g}, c = {c:g}.\n")
    w("| set | starters | landed | said, as shipped | said, fixed | landed / said, shipped | landed / said, fixed "
      "| log loss shipped | log loss fixed | fixed minus shipped (95% by night) |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for label, sel in (("all", test), *(((p_, [r for r in test if r["pos"] == p_]) for p_ in ("F", "M", "D")))):
        if not sel:
            continue
        n = len(sel)
        w(f"| {label} | {n:,} | {sum(r['won'] for r in sel) / n:.1%} | {sum(r['ss'] for r in sel) / n:.1%} | "
          f"{sum(r['ss_fix'] for r in sel) / n:.1%} | {_ci(ratio(sel))} | {_ci(ratio(sel, p='ss_fix'))} | "
          f"{log_loss([r['ss'] for r in sel], [r['won'] for r in sel]):.5f} | "
          f"{log_loss([r['ss_fix'] for r in sel], [r['won'] for r in sel]):.5f} | "
          f"{_ci(ll_diff(sel, 'ss_fix', 'ss'), 5, True)} |")
    ex = extra_rows(test)
    if ex:
        n = len(ex)
        said_fix = sum((fixed(r, k, c, prior) - r["own"]) / (1 - r["own"]) for r in ex) / n
        w(f"\nThe uplift alone on the same months, starters who did not score: said {sum(r['said_extra'] for r in ex) / n:.2%} "
          f"as shipped, {said_fix:.2%} fixed, paid {sum(r['paid'] for r in ex) / n:.2%}.\n")

    w("\n### 7. How Super Sub moves the Paddy Power verdict\n")
    w("report.py verdictOf (#13) on each line, before and after the uplift. No Paddy Power goalscorer prices "
      "are held to replay, so the price is a scenario: Paddy Power priced off the starter's own chance with margin m. "
      "verdictOf calls anything under 50% a long shot before it looks at a +5% edge, so only lines at 50% or more "
      "can become avoid that way.\n")
    w("| margin m | starters | long to acceptable | long to avoid (edge 5%+) | acceptable to avoid (edge 5%+) "
      "| avoid (price 5% worse) to long | avoid (price 5% worse) to acceptable | unchanged |")
    w("|---:|---:|---:|---:|---:|---:|---:|---:|")
    for m, n, c in verdict_changes(covered):
        w(f"| {m:.0%} | {n:,} | {c[('long', 'ok')]:,} | {c[('long', 'avoid')]:,} | {c[('ok', 'avoid')]:,} | "
          f"{c[('avoid', 'long')]:,} | {c[('avoid', 'ok')]:,} | "
          f"{sum(v for (a_, b_), v in c.items() if a_ == b_):,} |")
    ss50 = [r for r in covered if r["ss"] >= 0.5]
    w(f"\n{len(ss50)} starters had a Super Sub chance of 50% or more, {sum(r['own'] >= 0.5 for r in covered)} an own "
      f"chance of 50% or more; they landed {sum(r['won'] for r in ss50) / max(len(ss50), 1):.1%} against "
      f"{sum(r['ss'] for r in ss50) / max(len(ss50), 1):.1%} said.")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", help="checkout with supersub.py and scorer_audit.py")
    ap.add_argument("--cache")
    ap.add_argument("--audit", help="scorer_audit.py build output (scorer_audit.pkl)")
    ap.add_argument("--rows", help="also write the per-starter rows here, as JSON")
    ap.add_argument("--from-rows", help="report from rows a previous run wrote with --rows")
    args = ap.parse_args(argv)
    if args.from_rows:
        print(report(json.loads(Path(args.from_rows).read_text())))
        return
    if not (args.code and args.cache and args.audit):
        ap.error("--code, --cache and --audit are needed unless --from-rows is given")
    sys.path.insert(0, str(Path(args.code).resolve()))
    import supersub
    games = load_lineups(Path(args.cache), supersub)
    own = load_own(Path(args.audit))
    shipped = supersub.load_fit()
    rows = replay(games, own, supersub, shipped)
    if args.rows:
        Path(args.rows).write_text(json.dumps(rows))
    print(report(rows))


if __name__ == "__main__":
    main()
