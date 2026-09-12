"""Three picks across every built report: one bet, one multiple, one builder.

    from weekend import picks
    picks(entries, days=7)

Each report is one league. This reads across all of them and answers the three
questions a round actually raises: what is the single best thing to back, what
does a sensible multiple look like, and what does a same-team builder look like
when it is priced honestly.

Everything here is computed from data already inside the built reports, so this
costs nothing to run and cannot fail on a 403.

Three decisions worth knowing about, because they are what stops these numbers
flattering themselves:

Venue is chosen by the fixture, not by the data. A home side is judged on its
home record when there is enough of one. The browser's own scan tries all three
splits and keeps whichever looks best, which is fine for a list you read with
your own judgement and wrong for a headline pick, because picking the best of
three inflates the rate you end up quoting. Here the split is decided before
looking at the answer.

The multiple takes at most one leg per fixture. Two legs from the same match
are correlated, and a multiple built from them is worth less than the product
of its parts says.

The builder is priced by counting matches where every leg landed, never by
multiplying the legs together. In a builder the legs are the same team, so they
are positively correlated -- a dominant performance produces the shots and the
corners together -- and the product therefore quotes a longer price than the
truth. That is the direction that costs money: it makes the builder look like
value when it is not, which is exactly why the shops push them. The joint count
needs no independence assumption at all. It costs sample, and when the sample
is not there this returns nothing rather than a number with a shrug attached.
"""

from __future__ import annotations

import itertools
import math

import model

# A leg needs this many matches behind it before it is allowed near a headline.
MIN_SAMPLE = 10

# Below this, the venue split is too thin to prefer over the whole record.
MIN_VENUE = 6

# Zac's floor. Applied to the fair price, which is what the bet is worth, not
# to `need`, which is the longer number you should hold out for.
ODDS_FLOOR = 2.0

ACCA_LEGS = 3
ACCA_TARGET = 3.0

BUILDER_LEGS = 3
# Candidate legs per team before combinations are formed. Six gives twenty
# three-leg combinations per team, which is cheap and plenty.
BUILDER_POOL = 6
# Joint hits needed before a builder is worth quoting. Below five the interval
# is wider than the price and the honest output is silence.
BUILDER_MIN_JOINT = 5


def _sample(records, venue, games=38):
    """The matches a leg is judged on, venue decided before the stats are read."""
    recent = records[-games:]
    if venue:
        same = [r for r in recent if r.get("venue") == venue]
        if len(same) >= MIN_VENUE:
            return same, venue
    return recent, None


def _values(sample, period, stat):
    out = []
    for r in sample:
        v = (r.get("stats", {}).get(period) or {}).get(stat)
        if v is not None:
            out.append(float(v))
    return out


def legs_for(entry, meta):
    """Every priceable single on one fixture, both directions."""
    out = []
    projection = entry.get("projection") or {}
    cross = bool(entry.get("fixture", {}).get("crossLeague"))

    for team_index, team in enumerate(entry.get("teams", [])):
        venue = team.get("side")
        records = entry.get("records", [])[team_index] if team_index < len(entry.get("records", [])) else []
        sample, venue_used = _sample(records, venue)
        if len(sample) < MIN_SAMPLE:
            continue

        for period, names in (entry.get("stats") or {}).items():
            lines = (entry.get("lines") or {}).get(period) or {}
            for stat in names:
                line = lines.get(stat)
                if line is None:
                    continue
                values = _values(sample, period, stat)
                if len(values) < MIN_SAMPLE:
                    continue

                expected = None
                pair = ((projection.get(period) or {}).get(stat))
                if pair and len(pair) > team_index:
                    expected = pair[team_index]

                over_hits = sum(1 for v in values if v > line)
                for over in (True, False):
                    hits = over_hits if over else len(values) - over_hits
                    if hits == 0:
                        continue
                    price = model.price(line, over, expected, values, hits, len(values))
                    if price.get("conflict") or not math.isfinite(price["fair"]):
                        continue
                    out.append({
                        "fixture": meta,
                        "team": team.get("name"),
                        "teamIndex": team_index,
                        "period": period,
                        "stat": stat,
                        "line": line,
                        "over": over,
                        "hits": hits,
                        "total": len(values),
                        "venue": venue_used,
                        "fair": price["fair"],
                        "need": price["need"],
                        "p": price["p"],
                        "source": price["source"],
                        "evidence": model.wilson_low(hits, len(values)),
                        "crossLeague": cross,
                    })
    return out


def _leg_landed(record, period, stat, line, over):
    v = (record.get("stats", {}).get(period) or {}).get(stat)
    if v is None:
        return None
    return (float(v) > line) if over else (float(v) < line)


def joint_rate(sample, legs):
    """Matches where every leg landed, out of those carrying all the stats.

    The whole point of the builder. A match only counts in the denominator if
    every leg could be settled on it, so a stat missing from one fixture does
    not quietly become a loss.
    """
    hits = total = 0
    for r in sample:
        outcomes = [_leg_landed(r, l["period"], l["stat"], l["line"], l["over"]) for l in legs]
        if any(o is None for o in outcomes):
            continue
        total += 1
        if all(outcomes):
            hits += 1
    return hits, total


def builders_for(entry, meta):
    """Same-team builders on one fixture, priced off the joint count."""
    out = []
    cross = bool(entry.get("fixture", {}).get("crossLeague"))

    for team_index, team in enumerate(entry.get("teams", [])):
        records = entry.get("records", [])
        if team_index >= len(records):
            continue
        sample, venue_used = _sample(records[team_index], team.get("side"))
        if len(sample) < MIN_SAMPLE:
            continue

        # One leg per stat. Over 14.5 shots and over 6.5 first-half shots are
        # very nearly the same bet twice, and a builder made of those looks
        # like three opinions when it is one.
        best_by_stat = {}
        for leg in legs_for(entry, meta):
            if leg["teamIndex"] != team_index:
                continue
            current = best_by_stat.get(leg["stat"])
            if current is None or leg["evidence"] > current["evidence"]:
                best_by_stat[leg["stat"]] = leg

        pool = sorted(best_by_stat.values(), key=lambda l: -l["evidence"])[:BUILDER_POOL]
        if len(pool) < BUILDER_LEGS:
            continue

        for combo in itertools.combinations(pool, BUILDER_LEGS):
            hits, total = joint_rate(sample, combo)
            if total < MIN_SAMPLE or hits < BUILDER_MIN_JOINT:
                continue
            fair = total / hits
            if fair < ODDS_FLOOR:
                continue

            # What multiplying the legs would have told you. Carried so the
            # page can show the gap rather than assert it.
            naive = 1.0
            for leg in combo:
                naive *= leg["fair"]

            low = model.wilson_low(hits, total)
            out.append({
                "fixture": meta,
                "team": team.get("name"),
                "venue": venue_used,
                "legs": [_leg_public(l) for l in combo],
                "hits": hits,
                "total": total,
                "fair": fair,
                "need": (1 / low) if low > 0 else None,
                "naive": naive,
                "evidence": low,
                "crossLeague": cross,
            })
    return out


def _leg_public(leg):
    return {
        "team": leg["team"], "period": leg["period"], "stat": leg["stat"],
        "line": leg["line"], "over": leg["over"], "hits": leg["hits"],
        "total": leg["total"], "fair": leg["fair"], "venue": leg["venue"],
    }


def _single_public(leg):
    out = _leg_public(leg)
    out.update({
        "fixture": leg["fixture"], "need": leg["need"], "source": leg["source"],
        "evidence": leg["evidence"], "crossLeague": leg["crossLeague"],
    })
    return out


def selection_z(groups: int) -> float:
    """How strict the evidence bound has to be, given how hard we looked.

    A round offers something like nine thousand priceable legs. Take the
    maximum of nine thousand sample rates and the winner is partly the
    luckiest sample rather than the best bet -- the ordinary 95% Wilson bound
    answers "is this rate real", asked once, and we are asking it thousands of
    times. Unadjusted, the headline pick is reliably a small-sample fluke,
    which is the single most likely way this feature loses money.

    Bonferroni over every leg would be far too harsh, because the legs are
    nowhere near independent: over and under of one line are the same test
    twice, and the same stat across periods is largely the same test again. So
    the count used is distinct team-and-stat groups, which is the number of
    genuinely different questions being asked.

    Returns the z for a two-sided alpha of 0.05/groups, via the Beasley-
    Springer-Moro style rational approximation to the normal quantile -- good
    to about four decimal places, which is far beyond what this needs.
    """
    groups = max(1, groups)
    p = 1 - (0.05 / groups) / 2
    if p >= 1:
        return 6.0

    # Acklam's inverse normal CDF.
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > ph:
        q = math.sqrt(-2 * math.log(1 - p))
        return -((((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) /
                 ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1))
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def group_count(legs) -> int:
    return len({(l["fixture"]["id"], l["teamIndex"], l["stat"]) for l in legs})


def best_single(legs):
    """The best-evidenced bet that still pays the floor or longer.

    Ranked on the Wilson lower bound rather than the raw rate, so twelve from
    fifteen does not outrank twenty-six from thirty-eight. Note this will tend
    to settle near the floor: asking for 2.00 caps the probability at a half,
    and among bets that pay at least evens the best-supported ones are the
    ones closest to being a coin flip. That is the honest shape of the
    question, not a fault in the sort.
    """
    eligible = [l for l in legs if l["fair"] >= ODDS_FLOOR and l["total"] >= MIN_SAMPLE]
    if not eligible:
        return None

    z = selection_z(group_count(legs))
    for leg in eligible:
        leg["adjusted"] = model.wilson_low(leg["hits"], leg["total"], z=z)

    winner = max(eligible, key=lambda l: (l["adjusted"], l["fair"]))
    out = _single_public(winner)
    out["adjusted"] = winner["adjusted"]
    out["z"] = z
    out["consideredGroups"] = group_count(legs)
    return out


def best_acca(legs, wanted=ACCA_LEGS, target=ACCA_TARGET):
    """The fewest well-supported legs whose fair prices multiply past a target.

    At most one leg per fixture. The browser's slip allows one per team per
    stat, which can put both sides of the same match on one ticket; across a
    whole round there is no reason to accept that correlation when there are
    ninety other fixtures to choose from.
    """
    pool = [l for l in legs if 1.05 < l["fair"] < 100 and l["total"] >= MIN_SAMPLE]
    if len(pool) < 2:
        return None

    per_leg = target ** (1 / wanted)
    chosen, used = [], set()

    def take(candidates):
        for leg in candidates:
            if len(chosen) >= wanted:
                return
            key = leg["fixture"]["id"]
            if key in used:
                continue
            used.add(key)
            chosen.append(leg)

    # Legs that carry their share first, best-evidenced among them. Sorting on
    # price alone reaches any target in two legs by taking the two worst bets
    # on the board; sorting on evidence alone returns three near-certainties
    # multiplying to nothing anyone would place.
    take(sorted([l for l in pool if l["fair"] >= per_leg], key=lambda l: -l["evidence"]))
    take(sorted(pool, key=lambda l: -l["fair"]))

    if len(chosen) < 2:
        return None

    combined = 1.0
    for leg in chosen:
        combined *= leg["fair"]

    return {
        "legs": [_single_public(l) for l in chosen],
        "combined": combined,
        "target": target,
        "short": combined < target,
    }


def best_builder(entries):
    candidates = []
    for entry, meta in entries:
        candidates.extend(builders_for(entry, meta))
    if not candidates:
        return None
    return max(candidates, key=lambda b: (b["evidence"], b["fair"]))


def picks(entries, days=7, now=None):
    """The three picks, over every fixture kicking off inside the window."""
    import time
    now = now if now is not None else time.time()
    horizon = now + days * 86400

    upcoming = [(e, m) for e, m in entries if now < (m.get("kickoff") or 0) <= horizon]
    if not upcoming:
        return None

    legs = []
    for entry, meta in upcoming:
        legs.extend(legs_for(entry, meta))

    return {
        "days": days,
        "fixtures": len(upcoming),
        "legs": len(legs),
        "floor": ODDS_FLOOR,
        "single": best_single(legs),
        "acca": best_acca(legs),
        "builder": best_builder(upcoming),
    }
