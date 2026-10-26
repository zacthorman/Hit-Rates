"""
Is learner.py leaving the published legs' under-statement on the table?

    python -B leg_calib.py                      # best_bets.json only
    python -B leg_calib.py --cache-legs F.json  # also the cache walk-forward legs in F.json
    python -B leg_calib.py --cache-legs F.json --dump ACCA_DIR CACHE   # build F.json first (see LEG-WATCH.md)

acca-correlation (#11) found published legs land about 5% more often than
stated (football team legs 1.05, 1.02 to 1.10). Correcting that is
learner.py's job, and learner.py is currently switched off: its own check
(fit on the older four fifths, score the newest fifth) did not beat leaving
the chances alone.

This replays the correction night by night. For every night from CUT on,
each method is fitted on the legs settled before that night and scores that
night's legs, so nothing is scored on data it was fitted on. Methods:

  identity        the chances as published (chance_base, or one over fair)
  learner, live   learner.fit with learner.check's gate applied, exactly as
                  learner.model() runs it: on only when the gate says so
  learner, on     learner.fit always applied
  shift           one log-odds shift per sport and leg kind, slope fixed at 1,
                  the same 100-leg prior and 10-day half-life as learner.py
  shift + slope   a and b per sport and leg kind, no market terms

The rule, fixed before the run: a method replaces learner.py's fit only if,
on the nights from CUT, it lowers log loss against "learner, live" with a
95% interval (whole nights resampled) wholly below zero, and does not raise
log loss in any sport and kind with 100 or more scored legs.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import learner

HERE = Path(__file__).resolve().parent
CUT = "2026-10-09"       # the first night scored; about the first 40% of the record is fit-only
SEED = 20261024
BOOT = 2000
EPS = 1e-4
MIN_GROUP = 100


def night_of(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def _start(night: str) -> float:
    return datetime.strptime(night, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()


def _ll(p, y):
    p = min(max(p, EPS), 1 - EPS)
    return -math.log(p if y else 1 - p)


# ------------------------------------------------------------ simple fits

def fit_shift(legs: list[dict], now: float, slope: bool = False,
              prior: float = learner.PRIOR_LEGS, half_life: float = learner.HALF_LIFE_DAYS) -> dict:
    """Per group: logit(true) = a + b logit(said), b fixed at 1 unless
    slope. Same prior (as phantom legs) and recency weights as learner.fit."""
    out = {}
    by: dict = {}
    for r in legs:
        by.setdefault(r["group"], []).append(r)
    for g, rows in by.items():
        if len(rows) < learner.MIN_LEGS_GROUP:
            continue
        a, b = 0.0, 1.0
        xs = [learner._logit(r["said"]) for r in rows]
        ys = [1.0 if r["won"] else 0.0 for r in rows]
        ws = [0.5 ** (max(0.0, (now - r["ts"]) / 86400) / half_life) for r in rows]
        pp = prior * 0.25
        for _ in range(40):
            ga, gb = pp * a, pp * (b - 1)
            haa, hab, hbb = pp, 0.0, pp
            for x, y, w in zip(xs, ys, ws):
                p = learner._sig(a + b * x)
                ga += w * (p - y)
                gb += w * (p - y) * x
                v = w * p * (1 - p)
                haa += v
                hab += v * x
                hbb += v * x * x
            if slope:
                det = haa * hbb - hab * hab
                da = (hbb * ga - hab * gb) / det
                db = (haa * gb - hab * ga) / det
            else:
                da, db = ga / haa, 0.0
            a -= da
            b -= db
            if abs(da) < 1e-8 and abs(db) < 1e-8:
                break
        out[g] = (a, b)
    return out


def apply_shift(m: dict, r: dict) -> float:
    a, b = m.get(r["group"], (0.0, 1.0))
    return learner._sig(a + b * learner._logit(r["said"]))


# ------------------------------------------------------------ the replay

METHODS = ("identity", "learner, live", "learner, on", "shift", "shift + slope")


def replay(legs: list[dict], cut: str = CUT, refit: str = "night", window_days: float | None = None,
           cap: int | None = None) -> list[dict]:
    """Every leg settled on a night from `cut`, with each method's chance
    from a fit on the legs before that night (or before that month, with
    refit="month"). window_days and cap limit the training set to the most
    recent legs, for the cache, where learner.fit in pure Python would
    otherwise take hours; with a 10-day half-life, legs over 90 days old
    carry under 0.2% of the weight anyway."""
    legs = sorted(legs, key=lambda r: r["ts"])
    for r in legs:
        r.setdefault("night", night_of(r["ts"]))
    key = (lambda n: n[:7]) if refit == "month" else (lambda n: n)
    periods = sorted({key(r["night"]) for r in legs if r["night"] >= cut})
    rnd = random.Random(SEED)
    out = []
    for period in periods:
        t0 = _start(period if refit == "night" else period + "-01")
        train = [r for r in legs if r["ts"] < t0 and (window_days is None or r["ts"] >= t0 - window_days * 86400)]
        if cap and len(train) > cap:
            train = sorted(rnd.sample(train, cap), key=lambda r: r["ts"])
        today = [r for r in legs if key(r["night"]) == period and r["night"] >= cut]
        if len(train) < 100 or not today:
            continue
        m = learner.fit(train, now=t0)
        gate = learner.check(train)
        m["active"] = True
        sh = fit_shift(train, t0)
        ss = fit_shift(train, t0, slope=True)
        for r in today:
            on = learner.apply(m, r["said"], *learner._split(r))
            out.append(dict(r, **{"identity": r["said"], "learner, on": on,
                                  "learner, live": on if gate.get("ok") else r["said"],
                                  "shift": apply_shift(sh, r), "shift + slope": apply_shift(ss, r),
                                  "gate": bool(gate.get("ok"))}))
    return out


def boot_diff(rows, a, b, seed=SEED, reps=BOOT):
    by: dict = {}
    for r in rows:
        x = by.setdefault(r["night"], [0.0, 0])
        x[0] += _ll(r[a], r["won"]) - _ll(r[b], r["won"])
        x[1] += 1
    nights = list(by.values())
    point = sum(x for x, _ in nights) / max(sum(n for _, n in nights), 1)
    if len(nights) < 2:
        return point, float("nan"), float("nan")
    rnd = random.Random(seed)
    draws = []
    for _ in range(reps):
        s = n = 0
        for _ in nights:
            x = nights[rnd.randrange(len(nights))]
            s += x[0]
            n += x[1]
        draws.append(s / n)
    draws.sort()
    return point, draws[int(0.025 * reps)], draws[int(0.975 * reps) - 1]


def boot_ratio(rows, key, seed=SEED, reps=BOOT):
    by: dict = {}
    for r in rows:
        x = by.setdefault(r["night"], [0.0, 0.0])
        x[0] += r["won"]
        x[1] += r[key]
    nights = list(by.values())
    point = sum(a for a, _ in nights) / max(sum(b for _, b in nights), EPS)
    if len(nights) < 2:
        return point, float("nan"), float("nan")
    rnd = random.Random(seed)
    draws = []
    for _ in range(reps):
        a = b = 0.0
        for _ in nights:
            x = nights[rnd.randrange(len(nights))]
            a += x[0]
            b += x[1]
        draws.append(a / b)
    draws.sort()
    return point, draws[int(0.025 * reps)], draws[int(0.975 * reps) - 1]


def verdicts(rows) -> dict:
    """The fixed rule, per method."""
    out = {}
    groups = sorted({r["group"] for r in rows})
    for m in METHODS:
        if m == "learner, live":
            continue
        d = boot_diff(rows, m, "learner, live")
        worse = []
        for g in groups:
            sel = [r for r in rows if r["group"] == g]
            if len(sel) >= MIN_GROUP and sum(_ll(r[m], r["won"]) - _ll(r["learner, live"], r["won"]) for r in sel) > 0:
                worse.append(g)
        out[m] = {"diff": d, "worse_in": worse, "holds": d[2] < 0 and not worse}
    return out


# ------------------------------------------------------------ report

def _ci(t, d=2, signed=False):
    f = (lambda v: f"{v:+.{d}f}") if signed else (lambda v: f"{v:.{d}f}")
    return f"{f(t[0])} ({f(t[1])} to {f(t[2])})"


def tables(rows, title: str) -> list[str]:
    out = [f"\n### {title}\n",
           f"{len(rows):,} legs over {len({r['night'] for r in rows})} nights, {min(r['night'] for r in rows)} to "
           f"{max(r['night'] for r in rows)}. The live gate (learner.check on the legs before each night) was on for "
           f"{sum(1 for r in rows if r.get('gate'))} of them.\n",
           "| sport and kind | legs | nights | said | landed | landed / said (95% by night) | "
           + " | ".join(f"log loss {m}" for m in METHODS) + " |",
           "|---|---:|---:|---:|---:|---:|" + "---:|" * len(METHODS)]
    groups = sorted({r["group"] for r in rows}, key=lambda g: -sum(1 for r in rows if r["group"] == g))
    for g in ["all"] + groups:
        sel = rows if g == "all" else [r for r in rows if r["group"] == g]
        n = len(sel)
        out.append(f"| {g} | {n:,} | {len({r['night'] for r in sel})} | {sum(r['said'] for r in sel) / n:.3f} | "
                   f"{sum(r['won'] for r in sel) / n:.3f} | {_ci(boot_ratio(sel, 'said'))} | "
                   + " | ".join(f"{sum(_ll(r[m], r['won']) for r in sel) / n:.4f}" for m in METHODS) + " |")
    out.append("\nAgainst \"learner, live\", log loss difference with a 95% interval resampling whole nights "
               "(negative is better):\n")
    out.append("| sport and kind | legs | " + " | ".join(m for m in METHODS if m != "learner, live") + " |")
    out.append("|---|---:|" + "---:|" * (len(METHODS) - 1))
    for g in ["all"] + groups:
        sel = rows if g == "all" else [r for r in rows if r["group"] == g]
        if g != "all" and len(sel) < 30:
            continue
        out.append(f"| {g} | {len(sel):,} | " + " | ".join(_ci(boot_diff(sel, m, 'learner, live'), 4, True)
                                                        for m in METHODS if m != "learner, live") + " |")
    out.append("\nCorrected chance against landed, per method:\n")
    out.append("| sport and kind | " + " | ".join(METHODS) + " | landed |")
    out.append("|---|" + "---:|" * (len(METHODS) + 1))
    for g in ["all"] + groups:
        sel = rows if g == "all" else [r for r in rows if r["group"] == g]
        if g != "all" and len(sel) < 30:
            continue
        out.append(f"| {g} | " + " | ".join(f"{sum(r[m] for r in sel) / len(sel):.3f}" for m in METHODS)
                   + f" | {sum(r['won'] for r in sel) / len(sel):.3f} |")
    v = verdicts(rows)
    out.append("\nThe fixed rule (beats \"learner, live\" overall with the interval below zero, and is not worse "
               f"in any sport and kind with {MIN_GROUP}+ legs):\n")
    for m, x in v.items():
        out.append(f"- {m}: {'holds' if x['holds'] else 'does not hold'} "
                   f"(overall {_ci(x['diff'], 4, True)}"
                   + (f"; worse in {', '.join(x['worse_in'])}" if x["worse_in"] else "") + ")")
    return out


def dump_cache_legs(acca_dir: Path, cache: Path, out: Path) -> int:
    """Write the cache walk-forward legs with acca_corr.py from the
    acca-correlation branch (#11): team legs and football player legs, each
    priced from games before kick-off, kept at fair prices of 1.25 to 3.0
    as there. Needs pandas and that checkout; writes only `out`."""
    import sys
    sys.path.insert(0, str(Path(acca_dir).resolve()))
    import acca_corr as A
    matches = A.load_matches(Path(cache))
    team, _ = A.team_legs(matches)
    player = A.player_legs(matches, Path(cache))
    keep = [r for r in team + player if A.LEG_RANGE[0] <= 1 / r["p"] <= A.LEG_RANGE[1]]
    out.write_text(json.dumps([{k: r[k] for k in ("night", "ts", "sport", "kind", "stat", "p", "y")} for r in keep]))
    return len(keep)


def cache_legs(path: Path) -> list[dict]:
    """Walk-forward legs from the cache (acca_corr.py's team_legs and
    player_legs, written out as JSON), in learner's shape."""
    rows = json.loads(path.read_text())
    out = []
    for r in rows:
        out.append({"said": r["p"], "won": bool(r["y"]), "ts": r["ts"], "night": r["night"],
                    "group": learner.group_of(r["sport"], r["kind"] == "player"),
                    "family": learner.family(r.get("stat"))})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-legs")
    ap.add_argument("--cache-cut", default="2026-04-01")
    ap.add_argument("--dump", nargs=2, metavar=("ACCA_DIR", "CACHE"),
                    help="write the cache walk-forward legs to --cache-legs first")
    args = ap.parse_args(argv)
    if args.dump:
        n = dump_cache_legs(Path(args.dump[0]), Path(args.dump[1]), Path(args.cache_legs))
        print(f"{n} cache legs -> {args.cache_legs}")
    t = time.time()
    legs = learner.settled_legs()
    rows = replay(legs)
    out = [f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by `leg_calib.py`. Intervals resample "
           f"whole nights, {BOOT} draws, seed {SEED}."]
    out += tables(rows, f"Published legs (best_bets.json), nights from {CUT}")
    if args.cache_legs:
        cl = cache_legs(Path(args.cache_legs))
        crow = replay(cl, args.cache_cut, refit="month", window_days=90, cap=8000)
        out += tables(crow, f"Cache walk-forward legs, nights from {args.cache_cut}")
    print("\n".join(out))
    print(f"\n({time.time() - t:.0f}s)")


if __name__ == "__main__":
    main()
