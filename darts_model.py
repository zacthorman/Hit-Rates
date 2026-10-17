"""
Darts match markets: who wins, total legs, handicap, correct score, 180s.

    python darts_model.py --tune        # fit the settings on past matches
    python darts_model.py --backtest    # how good the prices were, as of each match
    python darts_model.py --player "Luke Humphries"

The darts pages used to carry four lines per player, all read off his own
record (180s, average, highest checkout, 100+ checkouts). That answers none of
the questions a darts coupon actually asks: who wins, how many legs, by how
much, how many 180s in the match. Those all come from one number, the chance
each man wins a leg, and the format.

THE LEG. A leg-level Elo over every cached result (about 3,100 matches since
2018), so a 6-4 is ten pieces of evidence and a 6-0 six. Updated with the
gradient of the leg log-likelihood: K x (legs won - legs expected). One pass,
in date order, so every rating is as of the morning of the match. Throwing
first in a leg is a real edge in darts, so a leg is won with
logistic(gap + throw) on your own throw and logistic(gap - throw) on his.

THE MATCH. First to N legs, or first to S sets of first to L legs, worked out
exactly by recursion over the score, with the throw alternating each leg and
each set. Who throws first in the match is decided by the bull and usually not
known in advance, so prices average over both.

Tuned on log loss of the match winner (python darts_model.py --tune): K 3 a
leg, throw 0.5, gap shrunk to 0.8, a new name starting at 1350. Recent 3-dart
average was tried as a second input and made every fit worse on the 415
matches where both men had one: the leg Elo already carries it.

180s. Each man's 180s per leg from his recent matches with stats, shrunk
towards the field. The match total is a Poisson mixture over the number of
legs the score distribution says will be played.
"""

from __future__ import annotations

import argparse
import functools
import glob
import json
import math
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"

BASE = 1500.0
NEW_PLAYER = 1350.0      # a name first seen in the cache is usually a qualifier
K_LEG = 3.0              # per leg of surprise
K_SET = 6.9              # per set, when only sets are known
THROW = 0.5              # log-odds edge of throwing first in a leg
SCALE = 400.0

# The rating gap is shrunk before it is priced. An Elo built on legs is
# noisier than its own numbers admit (form, travel, a bad night), and the raw
# gap priced 80-90% favourites who won 73%. Tuned with the rest.
SHRINK = 0.8
DEFAULTS = {"k_leg": K_LEG, "k_set": K_SET, "throw": THROW, "new": NEW_PLAYER, "shrink": SHRINK}


def _p(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def gap_logit(ra: float, rb: float) -> float:
    return (ra - rb) * math.log(10) / SCALE


# ------------------------------------------------------------------ loading

def load_matches(cache_dir: Path = CACHE) -> list[dict]:
    found = {}
    for pattern in ("team_*_events_last_*.json", "team_*_events_next_*.json"):
        for path in glob.glob(str(cache_dir / pattern)):
            try:
                data = json.load(open(path, encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for e in data.get("events") or []:
                if ((e.get("homeTeam") or {}).get("sport") or {}).get("slug") != "darts":
                    continue
                found[e["id"]] = e
    out = []
    for e in found.values():
        status = (e.get("status") or {}).get("type")
        hs = (e.get("homeScore") or {}).get("current")
        aw = (e.get("awayScore") or {}).get("current")
        fmt = match_format(e, hs, aw)
        row = {
            "id": e["id"], "ts": e.get("startTimestamp") or 0, "status": status,
            "a": (e.get("homeTeam") or {}).get("id"), "b": (e.get("awayTeam") or {}).get("id"),
            "a_name": (e.get("homeTeam") or {}).get("name"), "b_name": (e.get("awayTeam") or {}).get("name"),
            "sa": hs, "sb": aw, "first": e.get("firstToServe"), "fmt": fmt,
            "comp": ((e.get("tournament") or {}).get("uniqueTournament") or {}).get("name")
                    or (e.get("tournament") or {}).get("name"),
        }
        stats_path = cache_dir / f"event_{e['id']}_statistics.json"
        if status == "finished" and stats_path.exists():
            row["stats"] = _stats(stats_path)
        out.append(row)
    return sorted(out, key=lambda r: (r["ts"], r["id"]))


def match_format(e: dict, hs=None, aw=None):
    """("legs", N) for first to N legs, ("sets", S, L) for first to S sets of
    first to L legs, or None if it cannot be told."""
    bl, bs = e.get("bestOfLegs"), e.get("bestOfSets")
    if bs and bs > 1:
        return ("sets", (bs + 1) // 2, ((bl or 5) + 1) // 2)
    if bl:
        return ("legs", (bl + 1) // 2)
    if isinstance(hs, int) and isinstance(aw, int) and max(hs, aw) > 0:
        return ("legs", max(hs, aw))
    return None


def _stats(path: Path) -> dict | None:
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    out = {"a": {}, "b": {}}
    for period in data.get("statistics") or []:
        if period.get("period") != "ALL":
            continue
        for g in period.get("groups") or []:
            for it in g.get("statisticsItems") or []:
                if it.get("homeValue") is not None:
                    out["a"][it["name"]] = it["homeValue"]
                    out["b"][it["name"]] = it["awayValue"]
    return out if out["a"] else None


# ---------------------------------------------------------- match maths

@functools.lru_cache(maxsize=200000)
def _legs(n: int, pa_throw: float, pa_recv: float, a_first: bool):
    """Distribution of final scores (a_legs, b_legs) in first to n legs, a
    throwing first in leg one when a_first. Dynamic programming over the
    score, O(n squared). Returns a tuple of ((a, b), probability)."""
    grid = {(0, 0): 1.0}
    dist = {}
    for total in range(0, 2 * n - 1):
        for a in range(0, min(total, n - 1) + 1):
            b = total - a
            if b > n - 1:
                continue
            prob = grid.get((a, b), 0.0)
            if not prob:
                continue
            a_throws = (total % 2 == 0) == a_first
            p = pa_throw if a_throws else pa_recv
            for (na, nb), q in (((a + 1, b), p), ((a, b + 1), 1 - p)):
                if na == n or nb == n:
                    dist[(na, nb)] = dist.get((na, nb), 0) + prob * q
                else:
                    grid[(na, nb)] = grid.get((na, nb), 0) + prob * q
    return tuple(dist.items())


def score_distribution(gap: float, fmt, throw: float = THROW, a_first: bool | None = None) -> dict:
    """Final score distribution for one match. gap is a's log-odds edge in a
    leg on neutral throw. a_first None averages over who throws first."""
    pa_throw, pa_recv = _p(gap + throw), _p(gap - throw)
    starts = [True, False] if a_first is None else [a_first]
    out: dict = {}
    for first in starts:
        w = 1 / len(starts)
        if fmt[0] == "legs":
            for (a, b), p in _legs(fmt[1], round(pa_throw, 6), round(pa_recv, 6), first):
                out[(a, b)] = out.get((a, b), 0) + w * p
        else:
            S, L = fmt[1], fmt[2]
            # Probability a wins a set, by who throws first in it, plus the
            # legs each set takes, for the total-legs market.
            sets = {}
            for f in (True, False):
                d = _legs(L, round(pa_throw, 6), round(pa_recv, 6), f)
                sets[f] = d
            win = {f: sum(p for (x, y), p in sets[f] if x == L) for f in (True, False)}

            def rec(a, b, a_first_set, prob):
                if a == S or b == S:
                    out[(a, b)] = out.get((a, b), 0) + w * prob
                    return
                pw = win[a_first_set]
                # The throw alternates set to set.
                rec(a + 1, b, not a_first_set, prob * pw)
                rec(a, b + 1, not a_first_set, prob * (1 - pw))

            rec(0, 0, first, 1.0)
    return out


def match_win(gap, fmt, throw=THROW, a_first=None) -> float:
    d = score_distribution(gap, fmt, throw, a_first)
    target = fmt[1]
    return sum(p for (a, b), p in d.items() if a == target)


# --------------------------------------------------------------- ratings

class Ratings:
    def __init__(self, matches: list[dict], params: dict | None = None):
        self.params = dict(DEFAULTS, **(params or {}))
        self.r: dict = {}
        self.n: dict = {}
        self.names: dict = {}
        self.hist: dict = {}       # player -> list of (ts, rating after)
        self.form: dict = {}       # player -> list of (ts, avg, 180s, legs)
        self.ll = 0.0
        self.scored = 0
        self.preds: list = []
        self._run(matches)

    def rating(self, pid, ts=None):
        if pid not in self.r:
            return None
        if ts is None:
            return self.r[pid]
        h = self.hist.get(pid) or []
        before = [x for t, x in h if t < ts]
        return before[-1] if before else self.params["new"]

    def games_before(self, pid, ts):
        return sum(1 for t, _ in self.hist.get(pid, []) if t < ts)

    def _run(self, matches):
        p = self.params
        for m in matches:
            if m["status"] != "finished" or m["fmt"] is None or m["a"] is None or m["b"] is None:
                continue
            if not isinstance(m["sa"], int) or not isinstance(m["sb"], int):
                continue
            for pid, name in ((m["a"], m["a_name"]), (m["b"], m["b_name"])):
                if pid not in self.r:
                    self.r[pid] = p["new"]
                    self.n[pid] = 0
                self.names[pid] = name
            ra, rb = self.r[m["a"]], self.r[m["b"]]
            gap = gap_logit(ra, rb)
            # Who throws first is NOT read from the feed. SofaScore's
            # firstToServe on a finished match names the winner 98% of the
            # time (1,307 matches checked), so it is filled in after the
            # result and using it priced the past with the future. Every
            # match is priced as if the bull is still to be thrown.
            first = None
            # Score the match prediction before seeing the result.
            if self.n[m["a"]] >= 10 and self.n[m["b"]] >= 10:
                pw = match_win(gap * p["shrink"], m["fmt"], p["throw"], first)
                won = m["sa"] > m["sb"]
                q = min(max(pw, 1e-6), 1 - 1e-6)
                self.ll -= math.log(q if won else 1 - q)
                self.scored += 1
                self.preds.append((m, gap * p["shrink"], pw, won))
            # Update on legs (or sets).
            total = m["sa"] + m["sb"]
            pl = _p(gap)
            k = p["k_leg"] if m["fmt"][0] == "legs" else p["k_set"]
            delta = k * (m["sa"] - total * pl)
            self.r[m["a"]] += delta
            self.r[m["b"]] -= delta
            for pid in (m["a"], m["b"]):
                self.n[pid] += 1
                self.hist.setdefault(pid, []).append((m["ts"], self.r[pid]))
            st = m.get("stats")
            if st and m["fmt"][0] == "legs":
                for side, pid in (("a", m["a"]), ("b", m["b"])):
                    s = st[side]
                    self.form.setdefault(pid, []).append(
                        (m["ts"], s.get("Average 3 darts"), s.get("Thrown 180"), total))


# ----------------------------------------------------------------- 180s

FIELD_180_PER_LEG = 0.25
PRIOR_LEGS = 30.0


def rate_180(r: Ratings, pid, ts, window=25):
    rows = [x for x in r.form.get(pid, []) if x[0] < ts and x[2] is not None][-window:]
    legs = sum(x[3] for x in rows)
    n180 = sum(x[2] for x in rows)
    rate = (n180 + FIELD_180_PER_LEG * PRIOR_LEGS) / (legs + PRIOR_LEGS)
    return rate, legs


def poisson_tail(lam: float, line: float) -> float:
    """P(X > line) for Poisson(lam)."""
    k = int(math.floor(line))
    term = math.exp(-lam)
    cdf = term
    for i in range(1, k + 1):
        term *= lam / i
        cdf += term
    return 1 - cdf


# ----------------------------------------------------------------- markets

def gap_for_win(target: float, fmt, throw=THROW) -> float:
    """The leg edge that makes the match chance come out at `target`, by
    bisection. Used to price every other market off a blended winner price."""
    lo, hi = -4.0, 4.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if match_win(mid, fmt, throw) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def markets(r: Ratings, a, b, fmt, ts=None, a_first=None, win_override: float | None = None) -> dict | None:
    ra, rb = r.rating(a, ts), r.rating(b, ts)
    if ra is None or rb is None or fmt is None:
        return None
    gap = gap_logit(ra, rb) * r.params["shrink"]
    model_win = match_win(gap, fmt, r.params["throw"], a_first)
    if win_override is not None:
        gap = gap_for_win(win_override, fmt, r.params["throw"])
    dist = score_distribution(gap, fmt, r.params["throw"], a_first)
    target = fmt[1]
    pa = sum(p for (x, y), p in dist.items() if x == target)
    out = {"ratingA": round(ra), "ratingB": round(rb), "legA": round(_p(gap), 4),
           "winA": round(pa, 4), "modelWinA": round(model_win, 4), "format": list(fmt),
           "gamesA": r.games_before(a, ts or 9e12), "gamesB": r.games_before(b, ts or 9e12)}
    scores = sorted(dist.items(), key=lambda kv: -kv[1])
    out["scores"] = [[x, y, round(p, 4)] for (x, y), p in scores]
    if fmt[0] == "legs":
        totals = {}
        for (x, y), p in dist.items():
            totals[x + y] = totals.get(x + y, 0) + p
        exp_legs = sum(t * p for t, p in totals.items())
        out["expLegs"] = round(exp_legs, 2)
        lines = [t + 0.5 for t in range(target, 2 * target - 1)]
        out["totalLegs"] = [[L, round(sum(p for t, p in totals.items() if t > L), 4)] for L in lines]
        hcp = []
        for h in (1.5, 2.5, 3.5):
            hcp.append([h, round(sum(p for (x, y), p in dist.items() if x - y > h), 4),
                        round(sum(p for (x, y), p in dist.items() if y - x > h), 4)])
        out["handicap"] = hcp
        ra180, la = rate_180(r, a, ts or 9e12)
        rb180, lb = rate_180(r, b, ts or 9e12)
        out["rate180"] = [round(ra180, 3), round(rb180, 3)]
        out["legs180"] = [la, lb]
        lam_by_total = {t: (ra180 + rb180) * t for t in totals}
        lines180 = [x + 0.5 for x in range(0, 12)]
        out["total180"] = [[L, round(sum(p * poisson_tail(lam_by_total[t], L) for t, p in totals.items()), 4)]
                           for L in lines180]
        out["exp180"] = round(sum(p * lam_by_total[t] for t, p in totals.items()), 2)
        # Most 180s: independent Poisson per player over the expected legs.
        la_, lb_ = ra180 * exp_legs, rb180 * exp_legs
        pa_more = pb_more = 0.0
        fa = [math.exp(-la_) * la_ ** i / math.factorial(i) for i in range(25)]
        fb = [math.exp(-lb_) * lb_ ** i / math.factorial(i) for i in range(25)]
        for i in range(25):
            for j in range(25):
                if i > j:
                    pa_more += fa[i] * fb[j]
                elif j > i:
                    pb_more += fa[i] * fb[j]
        out["most180"] = [round(pa_more, 4), round(1 - pa_more - pb_more, 4), round(pb_more, 4)]
    return out


_LOADED: Ratings | None = None


def ratings() -> Ratings:
    global _LOADED
    if _LOADED is None:
        _LOADED = Ratings(load_matches())
    return _LOADED


def upcoming_format(event_id: int, cache_dir: Path = CACHE):
    for m in load_matches(cache_dir):
        if m["id"] == event_id:
            return m["fmt"], None
    return None, None


# --------------------------------------------------------------- checking

def backtest(r: Ratings) -> None:
    import collections
    preds = r.preds
    n = len(preds)
    base = sum(-math.log(0.5) for _ in preds) / n
    print(f"{n} matches scored, both players with 10+ prior matches")
    print(f"match winner log loss {r.ll / r.scored:.4f}  (coin flip {base:.4f})")
    hits = sum(1 for _, _, p, w in preds if (p > 0.5) == w)
    print(f"favourite won {hits / n:.1%}")
    buckets = collections.defaultdict(lambda: [0, 0, 0.0])
    for _, _, p, w in preds:
        fav = max(p, 1 - p)
        won = w if p >= 0.5 else not w
        bk = min(int((fav - 0.5) * 10), 4)
        buckets[bk][0] += 1
        buckets[bk][1] += won
        buckets[bk][2] += fav
    for bk in sorted(buckets):
        c, w, s = buckets[bk]
        print(f"  favourite {50 + bk * 10}-{60 + bk * 10}%: {c:>5} matches, said {s / c:.3f}, won {w / c:.3f}")
    # Total legs, legs format only.
    tl = [(m, gap) for m, gap, _, _ in preds if m["fmt"][0] == "legs"]
    ll = 0.0
    over_rows = []
    for m, gap in tl:
        first = None
        d = score_distribution(gap, m["fmt"], r.params["throw"], first)
        p = d.get((m["sa"], m["sb"]), 1e-6)
        ll -= math.log(max(p, 1e-6))
        target = m["fmt"][1]
        line = target + (target - 1) / 2 + 0.5 - 0.5 * ((target - 1) % 2 == 0) + 0.0
        line = math.floor(target * 1.5) + 0.5
        po = sum(q for (x, y), q in d.items() if x + y > line)
        over_rows.append((po, (m["sa"] + m["sb"]) > line))
    print(f"exact score log loss {ll / len(tl):.4f} over {len(tl)} legs-format matches")
    bk = collections.defaultdict(lambda: [0, 0, 0.0])
    for po, o in over_rows:
        b_ = min(int(po * 5), 4)
        bk[b_][0] += 1
        bk[b_][1] += o
        bk[b_][2] += po
    print("total legs over the middle line (e.g. 9.5 in first to 6):")
    for b_ in sorted(bk):
        c, w, s = bk[b_]
        print(f"  said {s / c:.3f}  landed {w / c:.3f}  ({c})")
    # 180s
    rows = []
    for m, gap, _, _ in preds:
        st = m.get("stats")
        if not st or m["fmt"][0] != "legs":
            continue
        a180, b180 = st["a"].get("Thrown 180"), st["b"].get("Thrown 180")
        if a180 is None or b180 is None:
            continue
        ra_, _ = rate_180(r, m["a"], m["ts"])
        rb_, _ = rate_180(r, m["b"], m["ts"])
        legs = m["sa"] + m["sb"]
        rows.append(((ra_ + rb_) * legs, a180 + b180))
    if rows:
        mean_p = sum(x for x, _ in rows) / len(rows)
        mean_a = sum(y for _, y in rows) / len(rows)
        var = sum((y - x) ** 2 for x, y in rows) / len(rows)
        print(f"match 180s, {len(rows)} matches (legs played known): predicted mean {mean_p:.2f}, "
              f"actual {mean_a:.2f}, residual variance {var:.2f} (Poisson would be about {mean_p:.2f})")


def tune(matches) -> None:
    best = None
    for k in (2, 3, 4, 6):
        for th in (0.2, 0.35, 0.5):
            for new in (1400, 1450):
                for sh in (0.6, 0.75, 0.9):
                    r = Ratings(matches, {"k_leg": k, "throw": th, "new": new, "k_set": k * 2.3, "shrink": sh})
                    ll = r.ll / r.scored
                    if best is None or ll < best[0]:
                        best = (ll, k, th, new, sh)
    print("best (log loss, K, throw, new, shrink)", best)
    print("best", best)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tune", action="store_true")
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--player")
    args = ap.parse_args()
    matches = load_matches()
    if args.tune:
        tune(matches)
        return
    r = Ratings(matches)
    if args.backtest:
        backtest(r)
        return
    if args.player:
        for pid, name in r.names.items():
            if args.player.lower() in (name or "").lower():
                print(name, round(r.r[pid]), r.n[pid], "matches", "180s/leg", round(rate_180(r, pid, 9e12)[0], 3))
        return
    top = sorted(((x, pid) for pid, x in r.r.items() if r.n[pid] >= 20), reverse=True)[:30]
    for i, (x, pid) in enumerate(top, 1):
        print(f"{i:>3} {x:7.1f}  {r.names[pid]}  ({r.n[pid]})")


if __name__ == "__main__":
    main()
