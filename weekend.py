"""Four picks across every built report: a bet, a multiple, a builder, a parlay.

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

from datetime import datetime
import json
from pathlib import Path
import itertools
import math
import collections
import os
import re

import markets
import model

try:
    import strength
except ImportError:              # never lose the picks to this
    strength = None


def _ratings():
    """The Elo table, built once per process from the cache. None if it
    cannot be built, in which case every leg is priced the old way."""
    if strength is None:
        return None
    try:
        return strength.ratings()
    except Exception as exc:
        print(f"  team strength unavailable, picks use records only: "
              f"{type(exc).__name__}: {exc}")
        return None

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
    """Every priceable single on one fixture, both directions.

    Football team legs also carry team strength (strength.py): both sides'
    Elo as of kick-off, the record against similar-strength opposition, and a
    chance that blends the record, that similar-opposition record, a
    strength-weighted expectation and the league projection. Where that chance
    exists it is the leg's price: `fair` is one over it, and the record-only
    price is kept as `fairRecord`. See USAGE.md, "Team strength in the picks".
    """
    out = []
    projection = entry.get("projection") or {}
    cross = bool(entry.get("fixture", {}).get("crossLeague"))
    fixture = entry.get("fixture") or {}
    kickoff = fixture.get("kickoff") or (meta or {}).get("kickoff")
    team_ids = [t.get("id") for t in entry.get("teams", [])]
    ratings = _ratings() if sport_of(entry) == "football" and kickoff and len(team_ids) == 2 else None

    for team_index, team in enumerate(entry.get("teams", [])):
        venue = team.get("side")
        records = entry.get("records", [])[team_index] if team_index < len(entry.get("records", [])) else []
        sample, venue_used = _sample(records, venue)
        if len(sample) < MIN_SAMPLE:
            continue

        side = None
        if ratings is not None:
            try:
                side = strength.Side(ratings, team_ids[team_index], team_ids[1 - team_index],
                                     kickoff, venue == "home", sample)
            except Exception:
                side = None
            try:
                _market_strength(side, meta, venue == "home")
            except Exception:
                pass

        # Only markets this competition's board actually carries. The feed
        # reports throw-ins for every league on earth; a book prices them in
        # England and not in MLS, and a pick you cannot place is worse than no
        # pick because it costs the slot a real one would have had.
        sellable = markets.stats_for_competition(
            sport_of(entry), (entry.get("fixture") or {}).get("competition"))

        for period, names in (entry.get("stats") or {}).items():
            lines = (entry.get("lines") or {}).get(period) or {}
            for stat in names:
                if stat not in sellable:
                    continue
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

                raw = [(r.get("stats", {}).get(period) or {}).get(stat) for r in sample]
                keep = [v is not None for v in raw]
                raw = [float(v) if v is not None else 0.0 for v in raw]

                over_hits = sum(1 for v in values if v > line)
                for over in (True, False):
                    hits = over_hits if over else len(values) - over_hits
                    if hits == 0:
                        continue
                    price = model.price(line, over, expected, values, hits, len(values),
                                        sport=sport_of(entry))
                    if price.get("conflict") or not math.isfinite(price["fair"]):
                        continue

                    chance = None
                    if side is not None:
                        def price_fn(exp, _over=over, _hits=hits, _values=values, _line=line):
                            got = model.price(_line, _over, exp, _values, _hits, len(_values),
                                              sport="football")
                            if got.get("conflict") or not math.isfinite(got.get("fair", float("nan"))):
                                return None
                            return got["p"]
                        try:
                            chance = strength.leg_chance(side, raw, keep, hits, len(values),
                                                         line, over, expected, price_fn,
                                                         slope_key=f"{period}|{stat}")
                        except Exception:
                            chance = None
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
                        "avg": round(sum(values) / len(values), 2),
                        "last": [round(v, 1) for v in values[-5:]],
                    })
                    if chance:
                        _apply_strength(out[-1], chance, side)
    return out


def _apply_strength(leg, chance, side):
    """Make the strength-aware chance the leg's price and its evidence.

    `need` is never allowed below the new fair price: it is the price to hold
    out for, and holding out for less than the fair price is not caution.
    The evidence figure is the same Wilson floor as before, read at the new
    chance on the same sample, so the selection allowance in best_single
    still pays for how many bets were searched.
    """
    p = chance["p"]
    n = leg["total"]
    leg["fairRecord"] = leg["fair"]
    leg["pStrength"] = p
    leg["fair"] = 1 / p
    leg["need"] = max(leg["need"], leg["fair"]) if math.isfinite(leg.get("need", float("nan"))) else leg["fair"]
    leg["evidence"] = model.wilson_low(p * n, n)
    ctx = side.public()
    ctx.update({k: v for k, v in chance.items() if k != "p"})
    leg["strength"] = ctx


# ----------------------------------------------------- one honest chance
#
# Picks used to rank on the Wilson floor of the raw record, team and player
# legs alike. Two things were wrong with that, both measured:
#
#   * The records overstate. The site's own settled best bets (best_bets.json,
#     13 October) said 82% on team legs that landed 73%, and 72% on player
#     legs that landed 61%.
#   * With four to six thousand legs searched the selection allowance is
#     z ~ 4.4, at which the floor mostly measures sample size. A player's
#     record is 38 games and a team's venue split about 20, so a player prop
#     won the headline almost by default.
#
# So every leg now carries one calibrated chance and the picks rank on it.
# Football team legs: the strength-aware chance (strength.leg_chance, fitted
# and checked on held-out leagues). Player legs: the record shrunk towards a
# coin flip by a number of phantom games learned from how the site's own
# settled player picks actually landed, refitted every run. Anything else:
# the old (hits + 2) / (n + 4).

PLAYER_SHRINK_DEFAULT = 8.0
PLAYER_SHRINK_MIN_LEGS = 60
_PLAYER_SHRINK: dict = {}


def player_shrink() -> float:
    """Phantom hits and misses for a player leg, fitted on settled history.

    Maximum likelihood over a small grid, on unique settled football player
    legs in best_bets.json. These are legs the site chose, so the fit already
    carries the cost of choosing the best-looking of thousands: exactly the
    correction a headline pick needs. Falls back to the default below
    PLAYER_SHRINK_MIN_LEGS, because a shrink fitted on thirty legs is noise.
    """
    if "a" in _PLAYER_SHRINK:
        return _PLAYER_SHRINK["a"]
    a_best = PLAYER_SHRINK_DEFAULT
    try:
        import json
        from pathlib import Path
        items = json.loads((Path(__file__).parent / "best_bets.json").read_text())
        unique = {}
        for item in items:
            for l in item.get("legs") or []:
                if (l.get("sport") == "football" and l.get("player")
                        and l.get("result") in ("win", "lose") and l.get("total")):
                    k = (l.get("event_id"), l.get("player"), l.get("stat"),
                         l.get("line"), l.get("over"))
                    unique[k] = (l["hits"], l["total"], l["result"] == "win")
        legs = list(unique.values())
        if len(legs) >= PLAYER_SHRINK_MIN_LEGS:
            def loss(a):
                total = 0.0
                for h, n, won in legs:
                    p = min(max((h + a) / (n + 2 * a), 1e-4), 1 - 1e-4)
                    total -= math.log(p if won else 1 - p)
                return total
            a_best = min((2, 4, 6, 8, 10, 12, 14, 17, 20, 25), key=loss)
            _PLAYER_SHRINK["legs"] = len(legs)
    except Exception:
        pass
    _PLAYER_SHRINK["a"] = float(a_best)
    return _PLAYER_SHRINK["a"]


def _learn(legs):
    """The self-correction (learner.py): refitted from every settled pick,
    applied only while it beats leaving the chances alone on the newest ones.
    The chance before it is kept as pBase, which is what besttrack records,
    so the learner never learns from its own output."""
    try:
        import learner
        m = learner.model()
    except Exception:
        return
    for leg in legs:
        if leg.get("pBase") is not None:
            continue
        fair = leg.get("fair")
        base = leg.get("pStrength") or leg.get("pShrunk") or (
            1 / fair if isinstance(fair, (int, float)) and fair > 1 else None)
        if base is None:
            continue
        leg["pBase"] = base
        if not m.get("active"):
            continue
        sport = (leg.get("fixture") or {}).get("sport", "football")
        p = learner.apply(m, base, sport, leg.get("player"), leg.get("stat"))
        if abs(p - base) < 1e-9:
            continue
        leg["pLearned"] = p
        leg["fair"] = 1 / p
        need = leg.get("need")
        leg["need"] = max(need, leg["fair"]) if isinstance(need, (int, float)) and math.isfinite(need) else leg["fair"]


def calibrate(legs):
    """Give every football player leg its shrunk chance and price it from it,
    then apply the self-correction to every leg.

    Team legs that strength has priced are left alone by the shrink.
    Idempotent: a leg already calibrated is skipped, so tonight.py and
    picks() can both call it.
    """
    _calibrate_players(legs)
    _learn(legs)
    _exchange(legs)
    return legs


# ------------------------------------------------------------ the exchange
#
# Where Betfair prices the same bet, or implies it, the chance the picks use
# is a blend of ours and the exchange's, margin removed, on the log-odds
# scale (market_prices.leg_quote says what each kind of quote is). How much
# the exchange counts depends on how real its price is, and once enough of
# these legs have settled, on what the results say: exchange_eval.py --fit
# writes exchange_weights.json, one weight per market family, and those
# replace the defaults below wherever a family has the results to back one.
#
# Value is what a bet is worth at the price you can actually take: chance
# times (back - 1) after Betfair's commission on the winnings, minus the
# chance of losing. The chance in it is the blend, never the model alone,
# so an edge has to survive the market pulling the number towards itself.
EXCHANGE_W_DEEP = 0.85       # tight and £5,000+ matched: a top market (2.5 goals, BTTS)
EXCHANGE_W_TRADED = 0.7      # tight spread and money matched
EXCHANGE_W_TIGHT = 0.5       # tight spread, little matched
EXCHANGE_W_LOOSE = 0.3       # wide spread or back price only
EXCHANGE_W_BACK = 0.35       # back-only lists, margin estimated
EXCHANGE_W_DERIVED = 0.5     # implied by the goal model off a tight market
EXCHANGE_DISAGREE = 0.15     # model this far from the exchange: flag, do not price value
COMMISSION = float(os.environ.get("BETFAIR_COMMISSION", "0.05"))
# Market-informed strength: how far tonight's Elo gap moves towards the one
# Betfair's match odds imply (strength.Side.use_market).
MARKET_STRENGTH_W = {"traded": 0.8, "tight": 0.6, "loose": 0.4}
_PRICES: dict = {}


def _prices():
    if "data" not in _PRICES:
        try:
            import market_prices
            _PRICES["data"] = market_prices.load()
            _PRICES["mod"] = market_prices
        except Exception:
            _PRICES["data"] = None
    return _PRICES.get("data"), _PRICES.get("mod")


def _fitted_weights() -> dict:
    if "weights" not in _PRICES:
        _PRICES["weights"] = {}
        try:
            import json
            from pathlib import Path
            w = json.loads((Path(__file__).parent / "exchange_weights.json").read_text())
            _PRICES["weights"] = w.get("weights") or {}
        except Exception:
            pass
    return _PRICES["weights"]


def exchange_family(leg, q) -> str:
    """The market family a quoted leg belongs to, for fitted weights and the
    evaluation: stat, player or team, and the kind of quote."""
    who = "player" if leg.get("player") else "team"
    return f"{who}|{leg.get('stat')}|{(q or {}).get('kind', 'exchange')}"


def ev_at(p: float, back: float | None, commission: float = None) -> float | None:
    """Expected profit per unit staked at a back price, commission on wins."""
    if not back or back <= 1:
        return None
    c = COMMISSION if commission is None else commission
    return p * (back - 1) * (1 - c) - (1 - p)


def _market_strength(side, meta, home: bool) -> None:
    data, mp = _prices()
    if not data or not mp or side is None:
        return
    try:
        imp = mp.implied(data, (meta or {}).get("id"))
    except Exception:
        imp = None
    if not imp or imp.get("win") is None or imp.get("draw") is None:
        return
    w, d, l = imp["win"], imp["draw"], imp["loss"]
    if not home:
        w, l = l, w
    mo_tight = imp.get("tight")
    weight = (MARKET_STRENGTH_W["traded"] if mo_tight and (imp.get("matched") or 0) >= 2000
              else MARKET_STRENGTH_W["tight"] if mo_tight else MARKET_STRENGTH_W["loose"])
    side.use_market(w, d, l, weight)


def _exchange_weight(leg, q) -> float:
    fitted = _fitted_weights().get(exchange_family(leg, q))
    if fitted is not None:
        return float(fitted)
    kind = q.get("kind")
    if kind == "back":
        return EXCHANGE_W_BACK
    if kind == "derived":
        return EXCHANGE_W_DERIVED if q.get("tight") else EXCHANGE_W_LOOSE
    return (EXCHANGE_W_DEEP if q["tight"] and q["matched"] >= 5000
            else EXCHANGE_W_TRADED if q["tight"] and q["matched"] >= 500
            else EXCHANGE_W_TIGHT if q["tight"] else EXCHANGE_W_LOOSE)


def _lp(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


# Market anchoring. Across a whole round the exchange is right on average,
# so if the model sits above the market on a family of bets every week (on 16
# October it rated nearly every team-goals under higher than Betfair did),
# that is the model's bias, not a hundred separate edges. The average gap per
# family, on the over side and the log-odds scale, is taken off the model
# before it is compared with the market; what remains is how this bet
# differs from the market more than the model usually does, which is the
# only part that can be an edge. Shrunk towards none while a family has few
# legs.
ANCHOR_PRIOR = 20


def _over_logit(p, over):
    return _lp(p) if over else -_lp(p)


def _exchange(legs):
    data, mp = _prices()
    if not data or not mp:
        return
    fresh = []
    for leg in legs:
        if leg.get("exchange") is not None:
            continue
        fid = (leg.get("fixture") or {}).get("id")
        try:
            q = mp.leg_quote(data, fid, leg)
        except Exception:
            q = None
        leg["exchange"] = q or False
        if q:
            fresh.append((leg, q, chance(leg)))

    gaps: dict = {}
    for leg, q, model_p in fresh:
        over = bool(leg.get("over", True))
        gaps.setdefault(exchange_family(leg, q), []).append(
            _over_logit(model_p, over) - _over_logit(q["p"], over))
    bias = {f: (sum(g) / len(g)) * len(g) / (len(g) + ANCHOR_PRIOR) for f, g in gaps.items()}
    # Back-only lists carry a margin that is only estimated, so their
    # average sits a little high; anchoring up to it would manufacture value.
    # There the model is only ever pulled down.
    for f in bias:
        if f.endswith("|back"):
            bias[f] = max(bias[f], 0.0)

    for leg, q, model_p in fresh:
        over = bool(leg.get("over", True))
        fam = exchange_family(leg, q)
        b = bias.get(fam, 0.0)
        adj_z = _lp(model_p) - (b if over else -b)
        model_adj = 1 / (1 + math.exp(-adj_z))
        w = _exchange_weight(leg, q)
        z = w * _lp(q["p"]) + (1 - w) * adj_z
        p = 1 / (1 + math.exp(-z))
        leg["pModel"] = model_p
        leg["pAnchored"] = model_adj
        leg["anchor"] = {"family": fam, "legs": len(gaps.get(fam, [])), "bias": round(b, 3)}
        leg["pExchange"] = p
        leg["exchangeWeight"] = round(w, 2)
        leg["fair"] = 1 / p
        need = leg.get("need")
        leg["need"] = max(need, leg["fair"]) if isinstance(need, (int, float)) and math.isfinite(need) else leg["fair"]
        # Value is only claimed where it can mean something: a market that
        # is a real price, and a model within 15 points of it once its usual
        # bias is off. On 16 October the loudest "value" on the board was
        # Fulham under 0.5 goals at +54%, the model saying 30% to a thin
        # market's 15%. A gap that size is the model being wrong, so it is
        # flagged as a disagreement instead.
        gap = model_adj - q["p"]
        if abs(gap) > EXCHANGE_DISAGREE:
            leg["disagree"] = round(gap, 4)
        elif q.get("back") and (q["tight"] or q.get("kind") == "back"):
            leg["value"] = ev_at(p, q["back"])


def _calibrate_players(legs):
    a = None
    for leg in legs:
        if not leg.get("player") or leg.get("pStrength") or leg.get("pShrunk"):
            continue
        if (leg.get("fixture") or {}).get("sport", "football") != "football":
            continue
        if a is None:
            a = player_shrink()
        p = (leg["hits"] + a) / (leg["total"] + 2 * a)
        leg["pShrunk"] = p
        leg["fairRecord"] = leg.get("fair")
        leg["fair"] = 1 / p
        need = leg.get("need")
        leg["need"] = max(need, leg["fair"]) if isinstance(need, (int, float)) and math.isfinite(need) else leg["fair"]
    return legs


def chance(leg) -> float:
    """The one probability the picks rank on (see the note above)."""
    return (leg.get("pExchange") or leg.get("pLearned") or leg.get("pStrength")
            or leg.get("pShrunk") or _shrunk(leg))


def _prob(leg):
    return chance(leg)


def _is_football(leg) -> bool:
    return (leg.get("fixture") or {}).get("sport", "football") == "football"


def rank_key(leg, z=None):
    """What a headline pick is chosen on.

    Football: the calibrated chance, to two places, then whether team strength
    stands behind it (that chance was validated on held-out leagues; the
    player shrink is a cruder fix), then sample size. Every other sport keeps
    the selection-adjusted Wilson floor on the record, unchanged, because
    nothing here was tested on them.
    """
    if _is_football(leg):
        return (round(chance(leg), 2), bool(leg.get("pStrength")), leg["total"], leg["fair"])
    return (leg.get("adjusted") if leg.get("adjusted") is not None
            else model.wilson_low(leg["hits"], leg["total"], z=z or 1.96), 0, 0, leg["fair"])


def sort_value(leg) -> float:
    """For short per-fixture lists: calibrated chance in football, the old
    evidence floor elsewhere."""
    return chance(leg) if _is_football(leg) else (leg.get("evidence") or 0)


def _adjusted(leg, z):
    """The selection-adjusted floor.

    Football: read at the leg's calibrated chance, shown on the page but no
    longer what decides the pick, since stacking a z of 4.4 on a chance
    already calibrated on selected legs only measures sample size a second
    time. Other sports: the record's floor, as before, and still the ranking.
    """
    if _is_football(leg):
        return model.wilson_low(chance(leg) * leg["total"], leg["total"], z=z)
    return model.wilson_low(leg["hits"], leg["total"], z=z)


MIN_PLAYER_SAMPLE = 10

# Mirrors model.MIN_MINUTES. Only applied where the sport reports minutes at
# all: American football sends 0 for everyone, and gating on it threw away
# every NFL record in the file.
MIN_MINUTES = 45

# What counts as having played, per sport. A number written for football is
# not a number about football, it is a number about ninety-minute games: an
# NBA rotation player who logs twenty-two minutes has played a full shift, and
# judging him against forty-five would have emptied the basketball file the
# same way the gridiron one emptied. Twelve minutes is a quarter -- enough to
# separate a rotation player from garbage time, which is all this has to do.
MIN_MINUTES_BY_SPORT = {
    "football": 45,
    "basketball": 12,
}


def _played(games, sport="football"):
    """A player's real appearances, by whichever test the sport supports."""
    floor = MIN_MINUTES_BY_SPORT.get(sport, MIN_MINUTES)
    if any((g.get("minutes") or 0) > 0 for g in games):
        return [g for g in games if (g.get("minutes") or 0) >= floor]
    return [g for g in games if g.get("stats")]


# Manual role changes, for when a teammate arrives or returns and a player's
# record describes a bigger share of the offence than he will get. Same idea as
# nfl_starters.json for quarterbacks: you know before the data does, and there
# are no games with the new man yet to measure the effect from.
#
#   nfl_roles.json
#   {"Xavier Hutchinson": {"factor": 0.8, "until": "2026-11-08",
#                          "because": "Marvin Harrison Jr. debuts 18 Oct"}}
#
# Every volume stat in the receiving family is scaled by factor before the
# hits are counted, so a 3-catch game at 0.8 counts as 2.4. Rates and longs
# are left alone. Entries past their until date are ignored, by which point
# there are games with the new man in the record. The factor is a judgement,
# not a fit: say why in "because" and delete the line once it stops applying.
ROLES_FILE = Path(__file__).parent / "nfl_roles.json"
ROLE_SKIP = re.compile(r"(average|per |long|dropped)", re.I)


def _roles(today=None) -> dict:
    try:
        raw = json.loads(ROLES_FILE.read_text())
    except Exception:
        return {}
    today = today or datetime.now().strftime("%Y-%m-%d")
    return {name: r for name, r in raw.items()
            if isinstance(r, dict) and r.get("factor") and str(r.get("until", "9999")) >= today}


def _role_scaled(stat: str) -> bool:
    return stat.startswith(("Receiving", "Rushing and receiving")) and not ROLE_SKIP.search(stat)


def player_legs_for(entry, meta):
    """Every priceable player prop on one fixture, both directions.

    No venue split here, unlike the team legs. A player's record is already
    the thinnest sample on the page, and halving it to honour home and away
    buys a little relevance for a lot of noise.

    The lines come from the report, which sets one line per stat across both
    squads rather than per player. That is fine for ranking and wrong for
    staking: twenty-one and a half receiving yards is a different proposition
    for a first-choice receiver than for a rookie, so the price to beat is the
    book's line, not this one.
    """
    out = []
    lines = entry.get("playerLines") or {}
    teams = entry.get("teams") or []
    sport = sport_of(entry)
    cross = bool(entry.get("fixture", {}).get("crossLeague"))

    # NFL: nobody on the injury report as out, and no passing or receiving
    # leg for a side whose quarterback has changed, since every one of those
    # records was built with the other man throwing. See nfl_injuries.py.
    # Every sport now: team_news.py fills entry["injuries"] from the
    # confirmed line-up, ESPN (NBA, NFL) and SofaScore's missing players.
    out_re = re.compile(r"^(out|doubtful|injured reserve|ir\b|suspen|pup|physically unable|"
                        r"non-football|reserve|inactive|not in squad|bench)", re.I)
    injuries = entry.get("injuries") or {}
    qb_change = entry.get("qbChange") or {}
    roles = _roles() if sport == "american-football" else {}

    for team_index, records in enumerate(entry.get("players") or []):
        if team_index >= len(teams):
            continue
        team = teams[team_index]
        side = "home" if team_index == 0 else "away"
        unavailable = {p[0] for p in injuries.get(side) or [] if out_re.match(p[2] or "")}
        new_qb = side in qb_change

        by_player: dict[str, list] = {}
        for record in records:
            name = record.get("player")
            if name:
                by_player.setdefault(name, []).append(record)

        for name, games in by_player.items():
            if name in unavailable:
                continue
            played = _played(games, sport)
            if len(played) < MIN_PLAYER_SAMPLE:
                continue
            position = played[0].get("position")

            for stat, line in lines.items():
                if new_qb and stat.startswith(("Passing", "Receiving", "Rushing and receiving")):
                    continue
                values = [g["stats"][stat] for g in played
                          if (g.get("stats") or {}).get(stat) is not None]
                if len(values) < MIN_PLAYER_SAMPLE:
                    continue
                role = roles.get(name) if _role_scaled(stat) else None
                if role:
                    values = [v * float(role["factor"]) for v in values]

                over_hits = sum(1 for v in values if v > line)
                for over in (True, False):
                    hits = over_hits if over else len(values) - over_hits
                    if hits == 0:
                        continue
                    price = model.price(line, over, None, values, hits, len(values),
                                        sport=sport_of(entry))
                    if not math.isfinite(price["fair"]):
                        continue
                    out.append({
                        "fixture": meta, "team": team.get("name"),
                        "teamIndex": team_index, "player": name,
                        "position": position, "period": "ALL", "stat": stat,
                        "line": line, "over": over, "hits": hits,
                        "total": len(values), "venue": None,
                        "fair": price["fair"], "need": price["need"],
                        "p": price["p"], "source": price["source"],
                        "evidence": model.wilson_low(hits, len(values)),
                        "crossLeague": cross,
                        "roleFactor": float(role["factor"]) if role else None,
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
    out = {
        "team": leg["team"], "period": leg["period"], "stat": leg["stat"],
        "line": leg["line"], "over": leg["over"], "hits": leg["hits"],
        "total": leg["total"], "fair": leg["fair"], "venue": leg["venue"],
        "player": leg.get("player"), "position": leg.get("position"),
    }
    out["chance"] = round(chance(leg), 4)
    if leg.get("pBase") is not None:
        out["chanceBase"] = round(leg["pBase"], 4)
    if leg.get("exchange"):
        q = leg["exchange"]
        out["exchange"] = {"p": q["p"], "back": q.get("back"), "lay": q.get("lay"),
                           "tight": q.get("tight"), "matched": round(q.get("matched") or 0)}
        out["chanceModel"] = round(leg.get("pModel") or 0, 4)
        if leg.get("value") is not None:
            out["value"] = round(leg["value"], 4)
        if leg.get("disagree") is not None:
            out["disagree"] = leg["disagree"]
    if leg.get("exchange"):
        q = leg["exchange"]
        out["exchange"].update({"kind": q.get("kind"), "market": q.get("market"),
                                "weight": leg.get("exchangeWeight")})
        if leg.get("pAnchored") is not None:
            out["chanceAnchored"] = round(leg["pAnchored"], 4)
            out["anchor"] = leg.get("anchor")
        if q.get("lambda") is not None:
            out["exchange"]["lambda"] = q["lambda"]
    for k in ("avg", "last"):
        if leg.get(k) is not None:
            out[k] = leg[k]
    if leg.get("fairRecord") is not None:
        out["fairRecord"] = leg.get("fairRecord")
    if leg.get("pStrength"):
        out["strength"] = leg.get("strength")
    # A ladder leg carries the rung it was read at, so the page can print
    # "100+ rushing and receiving yards" rather than "over 99.5" -- the same
    # bet, and only one of them is what you would look for on a coupon.
    if leg.get("alt"):
        out["alt"] = True
        out["threshold"] = leg["threshold"]
    try:
        import why
        out["why"] = why.reasons(leg)
    except Exception:
        pass
    return out


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
    """Distinct questions asked, which is what the evidence bar is scaled to.

    The player has to be in the key. Without it every receiver on a roster
    counts as one question about receiving yards, the adjustment comes out far
    too soft, and the headline pick is whichever squad member got the kindest
    fifteen games.
    """
    return len({(l["fixture"]["id"], l["teamIndex"], l.get("player"), l["stat"])
                for l in legs})



# ------------------------------------------------------------ bookmaker check
#
# The pick used to be quoted at our own fair price, whether or not anyone
# offered the bet. Each leg now carries the best price Paddy Power or Bet365
# actually has for it (same player or side, stat, line and direction), read
# from reports/paddypower.json and reports/bet365.json with pplog's reader,
# and the headline single is taken from legs a book offers at or above our
# fair price whenever there are any. Paddy Power prices about 30 hours out,
# so early in the week the pick falls back to the unpriced best, marked so.

def _book_index() -> dict:
    import pplog
    out = {}
    root = Path(__file__).parent / "reports"
    for fname, book in (("paddypower.json", "Paddy Power"), ("bet365.json", "Bet365")):
        try:
            data = json.loads((root / fname).read_text())
        except (OSError, ValueError):
            continue
        for fid, ev in (data.get("events") or {}).items():
            for l in ev.get("lines", []):
                got = pplog.read_line(l)
                if not got:
                    continue
                stat, line, over, _ = got
                k = (str(fid), "p", l.get("key") or pplog._norm(l.get("player", "")), stat, float(line), bool(over))
                if k not in out or l["price"] > out[k][1]:
                    out[k] = (book, l["price"])
            for l in ev.get("team", []) or []:
                k = (str(fid), "t", (l["scope"], ev.get("ppHome") or ""), l["stat"], float(l["line"]), bool(l["over"]))
                if k not in out or l["price"] > out[k][1]:
                    out[k] = (book, l["price"])
    return out


def _pp_swapped(pp_home: str, fx: dict) -> int:
    """1 when Paddy Power's home side is our away side (ppTeamOrder's word
    overlap: "Ararat-Armenia" against "FC Ararat-Armenia" shares no first word)."""
    import pplog
    stop = {"the", "club", "real", "sporting", "city", "united", "fc", "afc", "cf"}
    words = lambda t: {w for w in pplog._norm(t.replace("-", " ")).split() if len(w) >= 3 and w not in stop}
    h = words(pp_home)
    return int(len(h & words(fx.get("away", ""))) > len(h & words(fx.get("home", ""))))


def attach_books(legs) -> int:
    """Set leg["book"] = {"name", "price"} where a book offers the leg."""
    import pplog
    idx = _book_index()
    if not idx:
        return 0
    team_keys = collections.defaultdict(list)
    for k in idx:
        if k[1] == "t":
            team_keys[k[0]].append(k)
    n = 0
    for leg in legs:
        fx = leg.get("fixture") or {}
        fid = str(fx.get("id"))
        line = leg.get("line")
        if line is None or leg.get("period", "ALL") != "ALL":
            continue
        if leg.get("player"):
            k = (fid, "p", pplog._norm(leg["player"]), leg["stat"], float(line), bool(leg["over"]))
            hit = idx.get(k)
        else:
            hit = None
            for k in team_keys.get(fid, []):
                (scope, pp_home) = k[2]
                if scope == "match" or k[3] != leg["stat"] or k[4] != float(line) or k[5] != bool(leg["over"]):
                    continue
                side = (0 if scope == "home" else 1) ^ _pp_swapped(pp_home, fx)
                if side == leg.get("teamIndex"):
                    hit = idx[k]
                    break
        if hit:
            leg["book"] = {"name": hit[0], "price": hit[1]}
            n += 1
    return n


def us_model(legs) -> int:
    """NBA and NFL player legs: the backtested model's chance (usmodel.json),
    blended with this leg's own exactly as the page's withModel() does, so the
    pick of the week and the Value tab agree."""
    try:
        um = json.loads((Path(__file__).parent / "reports" / "usmodel.json").read_text())
    except (OSError, ValueError):
        return 0
    import pplog
    lg = lambda q: math.log(min(1 - 1e-4, max(1e-4, q)) / (1 - min(1 - 1e-4, max(1e-4, q))))
    sg = lambda z: 1 / (1 + math.exp(-z))
    n = 0
    for leg in legs:
        if not leg.get("player") or leg.get("line") is None:
            continue
        # NBA and NFL stat names never overlap, so the stat says which sport
        bl = next((b[leg["stat"]] for b in (um.get("blend") or {}).values() if leg["stat"] in b), None)
        ev = (um.get("events") or {}).get(str((leg.get("fixture") or {}).get("id")))
        if not bl or not ev:
            continue
        pl = next((v for k, v in ev["players"].items() if pplog._norm(k) == pplog._norm(leg["player"])), None)
        k = leg["line"] + 0.5
        p_new = ((pl or {}).get("lines", {}).get(leg["stat"]) or {}).get(str(int(k))) if float(k).is_integer() else None
        if p_new is None:
            continue
        site_over = leg["p"] if leg["over"] else 1 - leg["p"]
        sf = sg(bl["site_cal"][0] + bl["site_cal"][1] * lg(site_over))
        p_over = sg(bl["blend"][0] + bl["blend"][1] * lg(p_new) + bl["blend"][2] * lg(sf))
        p = p_over if leg["over"] else 1 - p_over
        leg["p"], leg["fair"] = p, 1 / p
        leg["need"] = max(leg.get("need") or 0, leg["fair"])
        leg["source"] = "usmodel"
        n += 1
    return n

def best_single(legs):
    """The best-evidenced bet that still pays the floor or longer.

    Ranked on the Wilson lower bound rather than the raw rate, so twelve from
    fifteen does not outrank twenty-six from thirty-eight. Note this will tend
    to settle near the floor: asking for 2.00 caps the probability at a half,
    and among bets that pay at least evens the best-supported ones are the
    ones closest to being a coin flip. That is the honest shape of the
    question, not a fault in the sort.
    """
    # A bet a book actually offers, at evens or longer and no shorter than
    # our fair price, whenever there is one; otherwise the unpriced best.
    # ...and no more than 30% over it: a bigger gap is far more often our
    # number being wrong (a role change, a new team-mate) than the book's.
    # Cross-league legs are left out: this path has no opponent
    # adjustment for them, and a Viking forward's Norwegian shots record at
    # Villa Park is the AEK problem of 20 Oct 2026 over again.
    confirmed = [l for l in legs if _headline_ok(l) and l.get("book")
                 and not l.get("crossLeague")
                 # the record has to agree: at least half its games landed
                 and l.get("total") and l["hits"] / l["total"] >= 0.5
                 # as on the Value tab: football to-score and cards are not
                 # called value until the results say how far off they run
                 and not (l.get("player") and l["stat"] in ("Goals", "Card", "Yellow cards"))
                 and max(ODDS_FLOOR, l["fair"]) <= l["book"]["price"] <= l["fair"] * 1.3]
    eligible = confirmed or [l for l in legs if l["fair"] >= ODDS_FLOOR and _headline_ok(l)]
    if not eligible:
        return None

    z = selection_z(group_count(legs))
    for leg in eligible:
        leg["adjusted"] = _adjusted(leg, z)

    winner = max(eligible, key=rank_key)
    out = _single_public(winner)
    out["book"] = winner.get("book")
    out["confirmed"] = bool(confirmed)
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
    take(sorted([l for l in pool if l["fair"] >= per_leg],
                key=lambda l: (-sort_value(l), -l["total"])))
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


# ------------------------------------------------------------ evens double
#
# Asked for often enough to deserve its own slot: "a solid evens bet". The
# best single at 2.00 is by construction a coin flip (see best_single), so the
# steadier way to reach evens is two strong legs at about 1.40 each. Chosen to
# maximise the chance both land, not the price.

# Counts (catches, carries, attempts) settle on one snap too few far more
# often than the yards they feed; lines of 0.5 are near-certain and priced to
# nothing. Neither belongs in a headline pick.
PICK_COUNT_STATS = {"Receiving receptions", "Rushing attempts",
                    "Passing attempts", "Passing completions"}
DOUBLE_TARGET = 2.0
DOUBLE_MAX = 2.6
BANKER_RANGE = (1.30, 1.75)
# Headline picks want a real record behind them, not a lucky ten games.
HEADLINE_SAMPLE = 15


def _shrunk(leg, a=2.0):
    return (leg["hits"] + a) / (leg["total"] + 2 * a)


# A leg the exchange prices clearly shorter than its fair chance is a bet
# you can only place at a bad price: out of the headline picks.
BAD_PRICE = -0.05


def _headline_ok(leg, sample=MIN_SAMPLE):
    if leg["total"] < sample or leg.get("stat") in PICK_COUNT_STATS:
        return False
    if leg.get("value") is not None and leg["value"] < BAD_PRICE:
        return False
    if not leg.get("player") and leg.get("line") == 0.5 and leg.get("over"):
        return False
    return 1.05 < leg["fair"] < 100


def _dedupe(legs):
    """"X receiving yards" and "X rushing and receiving yards" at one line are
    the same bet for a receiver; keep whichever has the better record."""
    best = {}
    for l in legs:
        stat = l["stat"].replace("Rushing and receiving yards", "Receiving yards") \
            if l.get("position") in ("WR", "TE") else l["stat"]
        key = (l["fixture"]["id"], l.get("player") or l.get("team"), stat,
               l.get("period"), l.get("line"), l.get("over"))
        if key not in best or (_prob(l), -len(l["stat"])) > (_prob(best[key]), -len(best[key]["stat"])):
            best[key] = l
    return list(best.values())


def best_double(legs, target=DOUBLE_TARGET):
    pool = _dedupe([l for l in legs if _headline_ok(l, HEADLINE_SAMPLE) and 1.25 <= l["fair"] <= 1.8])
    pool.sort(key=lambda l: -_prob(l))
    # The best few in each 0.05 price band rather than the 80 most likely
    # overall. Once a leg's price is one over its chance, the 80 most likely
    # are all priced 1.25 to 1.30 and no two of them reach evens, which is how
    # the double went missing the first time this ran.
    banded: dict[int, list] = {}
    for l in pool:
        band = banded.setdefault(int(l["fair"] / 0.05), [])
        if len(band) < 15:
            band.append(l)
    pool = [l for band in banded.values() for l in band]
    fixtures = {l["fixture"]["id"] for l in pool}
    best = None
    for a, b in itertools.combinations(pool, 2):
        if a.get("player") and a.get("player") == b.get("player"):
            continue
        if len(fixtures) > 1 and a["fixture"]["id"] == b["fixture"]["id"]:
            continue
        if a["fixture"]["id"] == b["fixture"]["id"] and a["teamIndex"] == b["teamIndex"]:
            continue
        combined = a["fair"] * b["fair"]
        if not (target * 0.95 <= combined <= DOUBLE_MAX):
            continue
        joint = _prob(a) * _prob(b)
        if best is None or joint > best[0]:
            best = (joint, combined, a, b)
    if not best:
        return None
    joint, combined, a, b = best
    return {"legs": [_single_public(a), _single_public(b)],
            "combined": combined, "joint": joint,
            "sameGame": a["fixture"]["id"] == b["fixture"]["id"]}


def best_banker(legs):
    """The single most likely to land that still pays something."""
    lo, hi = BANKER_RANGE
    pool = _dedupe([l for l in legs if _headline_ok(l, HEADLINE_SAMPLE) and lo <= l["fair"] <= hi])
    if not pool:
        return None
    z = selection_z(group_count(legs))
    for l in pool:
        l["adjusted"] = _adjusted(l, z)
    w = max(pool, key=rank_key)
    out = _single_public(w)
    out["adjusted"] = w["adjusted"]
    return out


# ------------------------------------------------------------ value bets
#
# The one list on the site picked on price rather than on chance: legs where
# the blended chance, at the back price Betfair offers right now, after
# commission, is worth more than the stake. Small edges only count past
# VALUE_MIN, because the blend's own error is a few points either way.
VALUE_MIN = 0.03
VALUE_PRICE = (1.25, 6.0)
VALUE_COUNT = 5


def best_value(legs):
    quoted = [l for l in legs if l.get("exchange")]
    pool = [l for l in quoted
            if l.get("value") is not None and l["value"] >= VALUE_MIN
            and l.get("disagree") is None and l["total"] >= MIN_SAMPLE
            and l.get("stat") not in PICK_COUNT_STATS
            and VALUE_PRICE[0] <= (l["exchange"].get("back") or 0) <= VALUE_PRICE[1]]
    # Not against its own last five: one landing in five is either a role
    # that has changed or a run the market has already seen.
    pool = [l for l in pool if not (l.get("last") and len(l["last"]) >= 4
            and sum(1 for v in l["last"] if (v > l["line"]) == bool(l.get("over", True))) <= 1)]
    pool.sort(key=lambda l: -l["value"])
    chosen, used = [], set()
    for l in pool:
        k = (l["fixture"]["id"], l.get("player") or l.get("team"))
        fk = l["fixture"]["id"]
        if k in used or fk in used:
            continue
        used.update({k, fk})
        chosen.append(l)
        if len(chosen) >= VALUE_COUNT:
            break
    return {"legs": [_single_public(l) for l in chosen], "quoted": len(quoted),
            "positive": sum(1 for l in quoted if (l.get("value") or 0) > 0),
            "commission": COMMISSION, "min": VALUE_MIN}


def best_builder(entries):
    candidates = []
    for entry, meta in entries:
        candidates.extend(builders_for(entry, meta))
    if not candidates:
        return None
    return max(candidates, key=lambda b: (b["evidence"], b["fair"]))


# Stat names that only American football has. Used to work out the sport of a
# report built before run.py started recording it, which is every report on
# disk today. The two vocabularies share nothing, so one hit is conclusive.
_GRIDIRON = {"Touchdowns", "Net yards passing", "Rushing yards", "Total yards",
             "First downs", "Interceptions thrown"}

# Basketball's giveaways. Deliberately not "Points", "Field goals" or
# "Turnovers": gridiron has all three under the same names meaning different
# things, and a fingerprint that fires on both sports is worse than none.
# Rebounds and 3 pointers belong to nobody else.
_BASKETBALL = {"Rebounds", "3 pointers", "Defensive rebounds",
               "Offensive rebounds", "Steals", "Blocks"}

# Darts. One match is two players and no team, and the feed reports the pair
# of them as teams, which is why nothing below needs a special case: a darts
# "team" is a man. The fingerprint is only a fallback -- the tournament's own
# category names the sport, and these fixtures arrive with it attached -- but
# a report built before that field existed still has to land somewhere.
_DARTS = {"Thrown 180", "Average 3 darts", "Highest checkout",
          "Checkouts over 100", "Thrown over 140", "Checkouts accuracy"}

# Baseball. Rows no other sport has: the Batting/Pitching block's own words.
_BASEBALL = {"Left on base", "Innings pitched", "Base on balls", "At bats",
             "Earned runs", "RBI"}

SPORT_LABELS = {
    "football": "Football",
    "american-football": "NFL",
    "basketball": "Basketball",
    "darts": "Darts",
    "baseball": "MLB",
}


def sport_of(entry) -> str:
    """Which sport a fixture belongs to, from the payload or its stat names."""
    named = (entry.get("fixture") or {}).get("sport")
    if named:
        return named
    for names in (entry.get("stats") or {}).values():
        present = set(names)
        if _DARTS & present:
            return "darts"
        if _BASEBALL & present:
            return "baseball"
        if _BASKETBALL & present:
            return "basketball"
        if _GRIDIRON & present:
            return "american-football"
    return "football"


def picks(entries, days=7, now=None):
    """The three picks, over every fixture kicking off inside the window."""
    import time

    # Imported here rather than at the top: parlay imports this module for the
    # appearance filter and the selection z, and a pair of module-level imports
    # would be a cycle.
    import parlay

    now = now if now is not None else time.time()
    horizon = now + days * 86400

    upcoming = [(e, m) for e, m in entries if now < (m.get("kickoff") or 0) <= horizon]
    if not upcoming:
        return None

    # One set of picks per sport, never one across both.
    #
    # A single pool would let an NFL leg take the best-bet slot off the
    # football and would build accumulators that mix the two codes. It is also
    # not a fair contest: the NFL sample is a season old and the football is
    # days old, and the selection-adjusted bound has no way to know that, so it
    # weighs them as if they were the same kind of evidence.
    by_sport: dict[str, list] = {}
    for entry, meta in upcoming:
        by_sport.setdefault(sport_of(entry), []).append((entry, meta))

    out = {"days": days, "floor": ODDS_FLOOR, "sports": [],
           "playerShrink": player_shrink(),
           "playerShrinkLegs": _PLAYER_SHRINK.get("legs")}
    try:
        import learner
        m = learner.model()
        learner.save(m)     # the card below reports this fit; record it beside the page
        chk = m.get("check") or {}
        out["learned"] = {"legs": m.get("legs"), "active": bool(m.get("active")), "updated": m.get("updated"),
                          "said": chk.get("said"), "landed": chk.get("landed"), "test": chk.get("test")}
    except Exception:
        pass
    for sport, group in by_sport.items():
        legs = []
        for entry, meta in group:
            legs.extend(legs_for(entry, meta))

            # Player legs come off the ladder, both ends of it, and no longer
            # from the report's suggested line.
            #
            # That line is one number per stat shared across both squads --
            # fine for ranking a page of players against each other, useless
            # as a headline. It offered "Gibbs over 35.5 rushing and receiving
            # yards" because 35.5 is roughly the median of everyone who
            # recorded any, while Gibbs' own median is 102. A book prices that
            # at about 1.02. The ladder asks the question the other way round
            # -- fix the rate, read off the line -- so the number quoted is
            # always one the player himself makes interesting.
            legs.extend(parlay.single_legs_for(entry, meta))
            legs.extend(parlay.alt_legs_for(entry, meta))
        calibrate(legs)
        try:
            us_model(legs)
            attach_books(legs)
        except Exception as exc:  # never lose the picks to this
            print(f"  book prices not attached: {type(exc).__name__}: {exc}")
        matches = None
        if sport == "darts":
            # The match markets from darts_model.py, one row per match, soonest
            # first: who wins at what price, and how long it should run.
            matches = []
            for entry, meta in sorted(group, key=lambda x: x[1].get("kickoff") or 0):
                dm = entry.get("dartsModel")
                if not dm:
                    continue
                t = entry.get("teams") or [{}, {}]
                fav = 0 if dm["winA"] >= 0.5 else 1
                pw = dm["winA"] if fav == 0 else 1 - dm["winA"]
                matches.append({"fixture": meta, "home": t[0].get("name"), "away": t[1].get("name"),
                                "fav": t[fav].get("name"), "p": round(pw, 4), "fair": round(1 / pw, 2),
                                "legs": dm.get("expLegs"), "s180": dm.get("exp180"),
                                "kickoff": meta.get("kickoff"), "report": meta.get("report")})
        out["sports"].append({
            "matches": matches,
            "sport": sport,
            "label": SPORT_LABELS.get(sport, sport.replace("-", " ").title()),
            "fixtures": len(group),
            "legs": len(legs),
            "single": best_single(legs),
            "value": best_value(legs),
            "double": best_double(legs),
            "banker": best_banker(legs),
            "acca": best_acca(legs),
            "builder": best_builder(group),
            "parlay": parlay.best_parlay(group),
        })

    out["sports"].sort(key=lambda s: -s["fixtures"])
    return out
