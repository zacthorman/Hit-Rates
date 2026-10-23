#!/usr/bin/env python3
"""Does the team-line take tier hold? Checked against what was really settled, and out of sample.

    python -B teamline_check.py record                      # best_bets.json: the published team legs
    python -B teamline_check.py cache --cache DIR           # walk forward on the cache (slow; needs lightgbm)
    python -B teamline_check.py cache --load walk.pkl       # the same from a saved walk
    python -B teamline_check.py cache --load walk.pkl --dump walk.pkl   # (with --cache) save the walk
    python teamlog.py scoreboard                            # the real record, on the Mac (teamlog.py)

Background. A team line can be called Take only in a market that passed
teamline_backtest.py, from that market's threshold to the 30% cap
(teamlines.verdict, and verdictOf in report.py). The backtest priced every
line against a proxy book, the linear game state fit with a 9% overround,
because no bookmaker team prices were kept for finished matches. So the take
tier rests on a stand-in. This asks two questions of it.

1. The record. Is there real settled evidence at real prices? Read from
   best_bets.json (the published team legs: the site's chance and the result,
   and Betfair's price where one was logged), and from pplog/team-*.jsonl
   when it is on this machine (`teamlog.py scoreboard`, the Paddy Power team
   lines with the team model's chance, the verdict, the price and the result).

2. The cache. On the walk forward teamline_backtest.py runs (the team model
   refitted every month on earlier matches only), do the lines in the take
   band land above their stated chance, market by market? The take band is
   the page's: our chance 50% or more, edge against the proxy book from the
   market's threshold (5% where the market failed, to show what it would have
   done) to 30%. Two numbers decide whether a take is real:
     got - said     how far the take's results fell short of the chance shown
                    on it. Lines picked for disagreeing with a price gather the
                    model's errors, so this is expected to be negative.
     return         per line staked at the proxy book's price. Positive means
                    the takes beat the stand-in book despite that shortfall.
   Every interval is 95% and resamples whole matches (BOOT draws), because
   the lines of one match are not independent.

Which months are held out. The thresholds were chosen on January to May
2026; June 2026 to the end of the cache was used only to confirm them. That
later period is out of sample for the model (refitted monthly on the past)
and for the threshold, but it did decide which markets passed, so it is not
untouched for the pass/fail choice. Nothing in the cache is newer than that;
the Paddy Power team log is the only fresh data.

The rule for tightening, fixed before the numbers were looked at: a passed
market's take tier is cut back only if, on the June-onwards takes,
  (a) the 95% interval of the return against the proxy book lies wholly
      below zero, or
  (b) the 95% interval of got / said lies wholly below 1 / (1 + threshold),
      so that a take at the threshold edge loses even at the proxy's prices.
Otherwise the result is reported and the gate is left alone.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BEST_BETS = ROOT / "best_bets.json"
BOOT = 2000
SEED = 20261023
Z = 1.959964


# ------------------------------------------------------------------ intervals (pure Python, for the Mac too)

def wilson(k: int, n: int, z: float = Z) -> tuple[float, float]:
    """95% Wilson interval for k successes in n."""
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def cluster_boot(groups: dict, stat, n: int = BOOT, seed: int = SEED, q: float = 0.025):
    """(low, high) of stat(rows) resampling whole groups. groups: {key: [rows]}.

    stat takes the flat list of resampled rows and returns a number or None."""
    keys = list(groups)
    if not keys:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        rows = []
        for _k in range(len(keys)):
            rows.extend(groups[keys[rng.randrange(len(keys))]])
        v = stat(rows)
        if v is not None:
            vals.append(v)
    if not vals:
        return (float("nan"), float("nan"))
    vals.sort()
    lo = vals[int(math.floor(q * (len(vals) - 1)))]
    hi = vals[int(math.ceil((1 - q) * (len(vals) - 1)))]
    return (lo, hi)


def summarise(rows: list[dict], group_key, said_key="p", won_key="won", price_key="price") -> dict:
    """n, groups, said, got (Wilson), got - said, got / said and return, with 95% intervals.

    rows: {p, won (0/1), price or None, ...}. Return is per line staked at
    price, over rows that have a price."""
    n = len(rows)
    if not n:
        return {"n": 0}
    groups = collections.defaultdict(list)
    for r in rows:
        groups[group_key(r)].append(r)
    k = sum(r[won_key] for r in rows)
    said = sum(r[said_key] for r in rows) / n

    def gap(rs):
        return sum(r[won_key] for r in rs) / len(rs) - sum(r[said_key] for r in rs) / len(rs) if rs else None

    def ratio(rs):
        s = sum(r[said_key] for r in rs)
        return sum(r[won_key] for r in rs) / s if s else None

    out = {"n": n, "groups": len(groups), "won": k, "said": said, "got": k / n, "got_ci": wilson(k, n),
           "gap": k / n - said, "gap_ci": cluster_boot(groups, gap),
           "ratio": (k / n) / said if said else None, "ratio_ci": cluster_boot(groups, ratio)}
    priced = [r for r in rows if r.get(price_key)]
    if priced:
        pg = collections.defaultdict(list)
        for r in priced:
            pg[group_key(r)].append(r)

        def ret(rs):
            return sum(r[won_key] * r[price_key] - 1 for r in rs) / len(rs) if rs else None
        out.update({"priced": len(priced), "ret": ret(priced), "ret_ci": cluster_boot(pg, ret),
                    "edge": sum(r[said_key] * r[price_key] - 1 for r in priced) / len(priced)})
    return out


def fmt_pct(x, d=1, sign=False):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    return f"{x * 100:+.{d}f}%" if sign else f"{x * 100:.{d}f}%"


def fmt_ci(ci, d=1, sign=False):
    if not ci or any(isinstance(v, float) and math.isnan(v) for v in ci):
        return "-"
    return f"{fmt_pct(ci[0], d, sign)} to {fmt_pct(ci[1], d, sign)}"


def tighten(s: dict, threshold: float) -> list[str]:
    """The pre-set rule: reasons to cut a passed market's take tier, [] if none."""
    why = []
    if s.get("ret_ci") and s["ret_ci"][1] < 0:
        why.append("the 95% interval of the return lies wholly below zero")
    if s.get("ratio_ci") and s["ratio_ci"][1] < 1 / (1 + threshold):
        why.append(f"got / said lies wholly below {1 / (1 + threshold):.3f}, so a take at the "
                   f"{fmt_pct(threshold)} threshold loses even at the proxy book's price")
    return why


# ------------------------------------------------------------------ 1. the published record

def record_rows(path: Path = BEST_BETS) -> list[dict]:
    """Settled football team legs from best_bets.json, one per distinct line.

    A leg appears in every ticket that used it; it is counted once, with the
    chance first published for it."""
    import teamlines
    try:
        bets = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return []
    seen = {}
    for b in bets:
        for l in b.get("legs") or []:
            if l.get("player") or l.get("sport") != "football" or l.get("result") not in ("win", "lose"):
                continue
            p = l.get("chance") or (1 / l["fair"] if l.get("fair") else None)
            if not p:
                continue
            key = (l["event_id"], l.get("team"), l["stat"], l["line"], bool(l["over"]))
            if key in seen:
                continue
            scope = "match" if (l.get("stat") or "").startswith("Match ") else "side"
            seen[key] = {"event_id": l["event_id"], "night": (l["kickoff"] - 6 * 3600) // 86400,
                         "stat": l["stat"], "market": teamlines.market_key(l["stat"], scope),
                         "over": bool(l["over"]), "p": float(p), "won": int(l["result"] == "win"),
                         "price": l.get("exchange_back"), "kickoff": l["kickoff"]}
    return list(seen.values())


def record_report(rows: list[dict]) -> tuple[list[str], dict]:
    import teamlines
    passed = {k for k in (teamlines.gate().get("markets") or {}) if teamlines.market_gate(k)}
    gated = set(teamlines.LABEL)
    out = ["| Market | Passed | Lines | Nights | Said | Got (95%) | Got - said (95%, by night) | With a Betfair price |",
           "|---|---|---|---|---|---|---|---|"]
    res = {}
    by = collections.defaultdict(list)
    for r in rows:
        if r["stat"] in gated:
            by[r["market"]].append(r)
    for key in sorted(by, key=lambda k: -len(by[k])):
        s = summarise(by[key], lambda r: r["night"])
        res[key] = s
        out.append(f"| {teamlines.market_name(key)} | {'yes' if key in passed else 'no'} | {s['n']} | {s['groups']} | "
                   f"{fmt_pct(s['said'])} | {fmt_pct(s['got'])} ({fmt_ci(s['got_ci'])}) | "
                   f"{fmt_pct(s['gap'], sign=True)} ({fmt_ci(s['gap_ci'], sign=True)}) | {s.get('priced', 0)} |")
    return out, res


# ------------------------------------------------------------------ 2. the cache

def take_rows(df, key: str, threshold: float, overround: float, held_out: bool):
    """The take band in one market against the proxy book, as plain rows."""
    import pandas as pd
    import teamline_backtest as B
    import teamlines
    cut = pd.Timestamp(B.SELECT_END).timestamp()
    d = df[df.market == key]
    d = d[d.ts >= cut] if held_out else d[d.ts < cut]
    if not len(d):
        return []
    c = B.offered(d, key, overround)
    c = c[(c.p >= teamlines.MIN_P) & (c.edge >= threshold) & (c.edge <= teamlines.SUSPECT)]
    return [{"match": m, "p": float(p), "won": int(w), "price": float(pr), "edge": float(e)}
            for m, p, w, pr, e in zip(c.match, c.p, c.win, c.price, c.edge)]


def likely_rows(df, key: str, held_out: bool):
    """Every line on an offered side that the model called 50% or more: no book involved."""
    import pandas as pd
    import teamline_backtest as B
    import teamlines
    cut = pd.Timestamp(B.SELECT_END).timestamp()
    d = df[df.market == key]
    d = d[d.ts >= cut] if held_out else d[d.ts < cut]
    under = teamlines.MARKETS[tuple(key.split("|"))]
    rows = [{"match": m, "p": float(p), "won": int(y)} for m, p, y in zip(d.match, d.model, d.y) if p >= 0.5]
    if under:
        rows += [{"match": m, "p": float(1 - p), "won": int(1 - y)} for m, p, y in zip(d.match, d.model, d.y)
                 if 1 - p >= 0.5]
    return rows


def cache_report(df) -> tuple[list[str], dict]:
    import teamline_backtest as B
    import teamlines
    g = teamlines.gate()
    lines, res = [], {}
    markets = [k for k in (g.get("markets") or {})]
    by_m = lambda r: r["match"]  # noqa: E731

    lines += ["### The take band, market by market", "",
              "Against the proxy book at a 9% overround. Passed markets at their gate threshold; failed markets "
              "at 5%, to show what a take there would have done. Said is the model's chance on the takes; got is "
              "how often they landed. 95% intervals resample whole matches.", "",
              "| Market | Gate | Months | Takes | Matches | Said | Got (95%) | Got - said (95%) | Got / said (95%) "
              "| Claimed edge | Return (95%) |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for key in markets:
        m = teamlines.market_gate(key, g)
        t = m["threshold"] if m else 0.05
        for held in (False, True):
            rows = take_rows(df, key, t, B.OVERROUND, held)
            s = summarise(rows, by_m)
            res[(key, held)] = s
            if not s["n"]:
                lines.append(f"| {teamlines.market_name(key)} | {'take from ' + fmt_pct(t) if m else 'failed'} | "
                             f"{'Jun on' if held else 'Jan to May'} | 0 | - | - | - | - | - | - | - |")
                continue
            lines.append(
                f"| {teamlines.market_name(key)} | {'take from ' + fmt_pct(t) if m else 'failed (5% shown)'} | "
                f"{'Jun on' if held else 'Jan to May'} | {s['n']} | {s['groups']} | {fmt_pct(s['said'])} | "
                f"{fmt_pct(s['got'])} ({fmt_ci(s['got_ci'])}) | {fmt_pct(s['gap'], sign=True)} "
                f"({fmt_ci(s['gap_ci'], sign=True)}) | {s['ratio']:.3f} ({s['ratio_ci'][0]:.3f} to "
                f"{s['ratio_ci'][1]:.3f}) | {fmt_pct(s['edge'], sign=True)} | {fmt_pct(s['ret'], sign=True)} "
                f"({fmt_ci(s['ret_ci'], sign=True)}) |")

    lines += ["", "### Inside the take band, by claimed edge (passed markets, June on)", "",
              "| Market | Claimed edge | Takes | Said | Got | Got - said (95%) | Return (95%) |",
              "|---|---|---|---|---|---|---|"]
    for key in markets:
        m = teamlines.market_gate(key, g)
        if not m:
            continue
        rows = take_rows(df, key, m["threshold"], B.OVERROUND, True)
        for lo, hi in ((m["threshold"], 0.10), (0.10, 0.20), (0.20, 0.3001)):
            sub = [r for r in rows if lo <= r["edge"] < hi]
            s = summarise(sub, by_m)
            res[(key, "band", lo)] = s
            if not s["n"]:
                continue
            lines.append(f"| {teamlines.market_name(key)} | {fmt_pct(lo, 0)} to {fmt_pct(min(hi, 0.30), 0)} | {s['n']} | "
                         f"{fmt_pct(s['said'])} | {fmt_pct(s['got'])} | {fmt_pct(s['gap'], sign=True)} "
                         f"({fmt_ci(s['gap_ci'], sign=True)}) | {fmt_pct(s['ret'], sign=True)} ({fmt_ci(s['ret_ci'], sign=True)}) |")

    lines += ["", "### Other proxy books (passed markets, June on)", "",
              "A sharper book (5%) or a softer one (12%) picks different takes from the same chances.", "",
              "| Market | Overround | Takes | Said | Got | Got - said (95%) | Return (95%) |",
              "|---|---|---|---|---|---|---|"]
    for key in markets:
        m = teamlines.market_gate(key, g)
        if not m:
            continue
        for ovr in (0.05, 0.09, 0.12):
            s = summarise(take_rows(df, key, m["threshold"], ovr, True), by_m)
            res[(key, "ovr", ovr)] = s
            if s["n"]:
                lines.append(f"| {teamlines.market_name(key)} | {fmt_pct(ovr, 0)} | {s['n']} | {fmt_pct(s['said'])} | "
                             f"{fmt_pct(s['got'])} | {fmt_pct(s['gap'], sign=True)} ({fmt_ci(s['gap_ci'], sign=True)}) | "
                             f"{fmt_pct(s['ret'], sign=True)} ({fmt_ci(s['ret_ci'], sign=True)}) |")

    lines += ["", "### Every line the model called 50% or more (no book), June on", "",
              "The same months without picking against a price: how the model's chance runs on the likely side "
              "of a line in general.", "",
              "| Market | Lines | Said | Got (95%) | Got - said (95%) |", "|---|---|---|---|---|"]
    for key in markets:
        s = summarise(likely_rows(df, key, True), by_m)
        res[(key, "likely")] = s
        if s["n"]:
            lines.append(f"| {teamlines.market_name(key)} | {s['n']} | {fmt_pct(s['said'])} | {fmt_pct(s['got'])} "
                         f"({fmt_ci(s['got_ci'])}) | {fmt_pct(s['gap'], sign=True)} ({fmt_ci(s['gap_ci'], sign=True)}) |")

    lines += ["", "### The rule for tightening, applied", ""]
    for key in markets:
        m = teamlines.market_gate(key, g)
        if not m:
            continue
        why = tighten(res[(key, True)], m["threshold"])
        res[(key, "tighten")] = why
        lines.append(f"- **{teamlines.market_name(key)}**: " + ("tighten: " + "; ".join(why) if why
                     else "no reason to tighten under the rule (neither interval lies wholly on the wrong side)."))
    return lines, res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("part", choices=["record", "cache"])
    ap.add_argument("--cache", help="folder of SofaScore cache files (cache/ unpacked from cache_backtest.tar.zst)")
    ap.add_argument("--load", help="a walk saved with --dump")
    ap.add_argument("--dump", help="save the walk here (with --cache)")
    a = ap.parse_args(argv)
    if a.part == "record":
        rows = record_rows()
        out, _ = record_report(rows)
        print(f"{len(rows)} settled football team lines in best_bets.json, "
              f"{sum(1 for r in rows if r['price'])} with a Betfair price\n")
        print("\n".join(out))
        return 0
    import pickle
    if a.load:
        with open(a.load, "rb") as fh:
            df = pickle.load(fh)[0]
    elif a.cache:
        import teamline_backtest as B
        R = B.build(Path(a.cache))
        df, xdf, uses, alphas = B.walk(R, exchange=B.exchange_lines())
        if a.dump:
            with open(a.dump, "wb") as fh:
                pickle.dump((df, xdf, uses, alphas, len(R)), fh)
    else:
        print("cache needs --cache DIR or --load FILE")
        return 1
    out, _ = cache_report(df)
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
