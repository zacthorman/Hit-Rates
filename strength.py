"""
Team strength: one Elo rating per club, built from results already in the cache.

    python strength.py                 # build, print the top 40, write strength.json
    python strength.py --team Arsenal  # one club's rating and recent path
    python strength.py --tune          # grid-search K and home advantage on log loss

Why this exists. The opponent-adjusted projection fits attack and defence
ratings off shared opponents inside one league. That is the right tool for a
league round and no tool at all for a Champions League night: LASK and
Liverpool share no opposition, the fit has nothing to calibrate against, and
every pick on the fixture fell back to the raw record. A raw record knows
nothing about who it was set against, so 26 from 38 against Austrian
Bundesliga defences and 26 from 38 against the Premier League looked the same.

Elo carries strength across competitions through the games that cross them:
European ties, the Leagues Cup, domestic cups between divisions, promotion and
relegation. The cache holds about eighteen thousand finished matches, which is
plenty.

Two rules keep it honest:

  * ONE PASS, IN DATE ORDER. Every rating is the rating as it stood before that
    match. rating_at(team, ts) answers "how strong was this side on that day"
    using only earlier results, so the backtest can use it without reading the
    future. A burn-in that runs the history twice would converge faster and
    leak every later result into every early rating.
  * A NEW SIDE STARTS AT ITS COMPETITION'S CURRENT AVERAGE, not at a global
    1500. Otherwise the first match a Kazakh club plays in the cache treats it
    as the equal of whoever it meets. Leagues that never meet anyone else end
    up on their own scale, which is harmless: their clubs never meet anyone
    else either.

Ratings only move on results. Nothing about corners or cards goes in, so the
rating is an independent measure of who is better, which is what the picks
need it for.
"""

from __future__ import annotations

import argparse
import bisect
import glob
import json
import math
import probability
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
STORE = HERE / "strength.json"

BASE = 1500.0
# Tuned on log loss over the cache (python strength.py --tune). Home advantage
# in Elo points; K per match before the goal-margin multiplier.
HOME_ADV = 60.0
K_LEAGUE = 20.0
# Continental club competitions decide the cross-league scale, and there are
# few of them, so each one is allowed to move the ratings a little further.
K_CONTINENTAL = 30.0
K_CUP = 20.0
# Friendlies are rotated squads and pre-season. They link clubs that never
# otherwise meet, so they are kept, at a weight that cannot drag anyone far.
K_FRIENDLY = 5.0
# A league's own offset, moved only by matches between clubs from different
# leagues. Without it every league starts on the same scale and stays there:
# Sabah win the Azerbaijani league every week, a handful of European results
# cannot pull one club back down, and they rated above Liverpool. The offset
# lets a league's European record reprice every club in it at once.
K_LEAGUE_OFFSET = 8.0

_CONTINENTAL = ("uefa", "conmebol", "concacaf", "leagues cup", "club world cup",
                "afc champions", "caf champions")


def _kind(tournament: dict) -> str:
    name = (tournament.get("uniqueTournament") or {}).get("name") or tournament.get("name") or ""
    low = name.lower()
    if "friendl" in low or "preseason" in low:
        return "friendly"
    if any(word in low for word in _CONTINENTAL):
        return "continental"
    if "cup" in low or "pokal" in low or "copa" in low or "coupe" in low or "coppa" in low:
        return "cup"
    return "league"


def _k(kind: str, params: dict) -> float:
    return {
        "friendly": params["k_friendly"],
        "continental": params["k_continental"],
        "cup": params["k_cup"],
    }.get(kind, params["k_league"])


def _margin(goal_diff: int) -> float:
    """World Football Elo's goal-margin multiplier."""
    gd = abs(goal_diff)
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return (11 + gd) / 8


def expected_score(rating_a: float, rating_b: float, home_adv: float = 0.0) -> float:
    """Elo's expected score for A (win 1, draw 0.5) against B."""
    return 1.0 / (1.0 + 10 ** (-(rating_a + home_adv - rating_b) / 400.0))


# ------------------------------------------------------------------ loading

def load_events(cache_dir: Path = CACHE) -> list[dict]:
    """Every finished men's football match in the cache, once each, oldest first."""
    found: dict[int, dict] = {}
    patterns = ("team_*_events_last_*.json", "unique-tournament_*_events_last_*.json")
    for pattern in patterns:
        for path in glob.glob(str(cache_dir / pattern)):
            try:
                with open(path, encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, ValueError):
                continue
            for event in data.get("events") or []:
                if (event.get("status") or {}).get("type") != "finished":
                    continue
                home, away = event.get("homeTeam") or {}, event.get("awayTeam") or {}
                if ((home.get("sport") or {}).get("slug")) != "football":
                    continue
                if home.get("gender") == "F" or away.get("gender") == "F":
                    continue
                hs = (event.get("homeScore") or {})
                aws = (event.get("awayScore") or {})
                h = hs.get("normaltime", hs.get("current"))
                a = aws.get("normaltime", aws.get("current"))
                if h is None or a is None or not event.get("startTimestamp"):
                    continue
                found[event["id"]] = {
                    "id": event["id"],
                    "ts": event["startTimestamp"],
                    "home": home.get("id"), "away": away.get("id"),
                    "home_name": home.get("name"), "away_name": away.get("name"),
                    "hg": int(h), "ag": int(a),
                    "tid": ((event.get("tournament") or {}).get("uniqueTournament") or {}).get("id"),
                    "comp": ((event.get("tournament") or {}).get("uniqueTournament") or {}).get("name")
                            or (event.get("tournament") or {}).get("name"),
                    "kind": _kind(event.get("tournament") or {}),
                }
    return sorted(found.values(), key=lambda e: (e["ts"], e["id"]))


# ---------------------------------------------------------------- the model

DEFAULTS = {"home_adv": HOME_ADV, "k_league": K_LEAGUE, "k_continental": K_CONTINENTAL,
            "k_cup": K_CUP, "k_friendly": K_FRIENDLY, "k_offset": K_LEAGUE_OFFSET}


class Ratings:
    """Elo over a list of events, with the full history kept for as-of lookups.

    A club's strength is its own rating plus its league's offset. Inside one
    league the offsets cancel and this is plain Elo; between leagues the
    offsets carry the difference in standard.
    """

    def __init__(self, events: list[dict], params: dict | None = None):
        self.params = dict(DEFAULTS, **(params or {}))
        self.club: dict[int, float] = {}
        self.games: dict[int, int] = {}
        self.names: dict[int, str] = {}
        self.home_comp: dict[int, str] = {}
        self.league_of: dict[int, object] = {}
        self.offset: dict[object, float] = {}
        # team -> parallel lists of timestamps and club rating AFTER that match
        self._ts: dict[int, list[int]] = {}
        self._after: dict[int, list[float]] = {}
        self._lg_hist: dict[int, list] = {}
        self._first: dict[int, float] = {}
        # league -> parallel lists of timestamps and offset after each change
        self._off_ts: dict[object, list[int]] = {}
        self._off_val: dict[object, list[float]] = {}
        self._comp_members: dict = {}
        self.log_loss = 0.0
        self.scored = 0
        self.cross_ll = 0.0
        self.cross_n = 0
        self._run(events)

    @property
    def rating(self) -> dict[int, float]:
        """Current strength, club rating plus league offset."""
        return {t: r + self.offset.get(self.league_of.get(t), 0.0) for t, r in self.club.items()}

    def _start(self, team: int, tid) -> float:
        members = self._comp_members.get(tid) or {}
        rated = [self.club[t] for t in members if t in self.club and t != team]
        return sum(rated) / len(rated) if len(rated) >= 4 else BASE

    def _eff(self, team: int) -> float:
        return self.club[team] + self.offset.get(self.league_of.get(team), 0.0)

    def _run(self, events: list[dict]) -> None:
        p = self.params
        for e in events:
            h, a = e["home"], e["away"]
            if h is None or a is None:
                continue
            for team, name in ((h, e["home_name"]), (a, e["away_name"])):
                if team not in self.club:
                    self.club[team] = self._start(team, e["tid"])
                    self.games[team] = 0
                    if e["kind"] == "league":
                        self.league_of[team] = e["tid"]
                    self._first[team] = self._eff(team)
                self.names[team] = name
            # A league match settles which league a club belongs to from now
            # on, which is how promotion and relegation move a club across.
            if e["kind"] == "league":
                for team in (h, a):
                    before = self.league_of.get(team)
                    if before is not None and before != e["tid"]:
                        # Promotion or relegation. The club is the same club
                        # the day after, so its strength must not jump: the
                        # club rating is re-based onto the new league's scale.
                        # Without this a promoted side inherited the whole
                        # Premier League offset and rated above Real Madrid.
                        self.club[team] += (self.offset.get(before, 0.0)
                                            - self.offset.get(e["tid"], 0.0))
                    self.league_of[team] = e["tid"]
                    self.home_comp[team] = e["comp"]

            rh, ra = self._eff(h), self._eff(a)
            exp_h = expected_score(rh, ra, p["home_adv"])
            if e["hg"] > e["ag"]:
                score = 1.0
            elif e["hg"] == e["ag"]:
                score = 0.5
            else:
                score = 0.0

            if e["kind"] != "friendly" and self.games[h] >= 5 and self.games[a] >= 5:
                q = min(max(exp_h, 1e-6), 1 - 1e-6)
                loss = -(score * math.log(q) + (1 - score) * math.log(1 - q))
                self.log_loss += loss
                self.scored += 1
                lh0, la0 = self.league_of.get(h), self.league_of.get(a)
                if lh0 is not None and la0 is not None and lh0 != la0:
                    self.cross_ll += loss
                    self.cross_n += 1

            surprise = _margin(e["hg"] - e["ag"]) * (score - exp_h)
            delta = _k(e["kind"], p) * surprise
            self.club[h] += delta
            self.club[a] -= delta

            lh, la = self.league_of.get(h), self.league_of.get(a)
            if lh is not None and la is not None and lh != la and e["kind"] != "friendly":
                move = p["k_offset"] * surprise
                for lg, sign in ((lh, 1), (la, -1)):
                    self.offset[lg] = self.offset.get(lg, 0.0) + sign * move
                    self._off_ts.setdefault(lg, []).append(e["ts"])
                    self._off_val.setdefault(lg, []).append(self.offset[lg])

            for team in (h, a):
                self.games[team] += 1
                self._ts.setdefault(team, []).append(e["ts"])
                self._after.setdefault(team, []).append(self.club[team])
                self._lg_hist.setdefault(team, []).append(self.league_of.get(team))
            members = self._comp_members.setdefault(e["tid"], {})
            members[h] = members[a] = True

    def _offset_at(self, league, ts: float) -> float:
        stamps = self._off_ts.get(league)
        if not stamps:
            return 0.0
        i = bisect.bisect_left(stamps, ts)
        return self._off_val[league][i - 1] if i else 0.0

    # ------------------------------------------------------------ lookups

    def rating_at(self, team: int | None, ts: float | None = None) -> float | None:
        """The rating as it stood before kick-off at `ts`. None if unknown."""
        if team is None or team not in self._ts:
            return None
        if ts is None:
            return self._eff(team)
        stamps = self._ts[team]
        i = bisect.bisect_left(stamps, ts)
        if i == 0:
            return self._first.get(team)
        league = self._lg_hist[team][i - 1]
        return self._after[team][i - 1] + self._offset_at(league, ts)

    def games_before(self, team: int | None, ts: float | None = None) -> int:
        if team is None or team not in self._ts:
            return 0
        if ts is None:
            return len(self._ts[team])
        return bisect.bisect_left(self._ts[team], ts)

    def win_draw_loss(self, home: int, away: int, ts: float | None = None):
        """Rough 1X2 from the rating gap. The draw share follows the usual
        football shape: biggest when the sides are level, shrinking as the
        gap opens."""
        rh, ra = self.rating_at(home, ts), self.rating_at(away, ts)
        if rh is None or ra is None:
            return None
        e = expected_score(rh, ra, self.params["home_adv"])
        draw = 0.28 * math.exp(-((e - 0.5) ** 2) / 0.08)
        win = max(0.0, e - draw / 2)
        loss = max(0.0, 1 - win - draw)
        return win, draw, loss

    def ranked(self, min_games: int = 15) -> list[tuple[int, float]]:
        current = self.rating
        return sorted(((t, r) for t, r in current.items()
                       if self.games.get(t, 0) >= min_games),
                      key=lambda x: -x[1])


_LOADED: Ratings | None = None


def ratings(cache_dir: Path = CACHE) -> Ratings:
    """Built once per process. Reading ~1,200 files takes a few seconds."""
    global _LOADED
    if _LOADED is None:
        _LOADED = Ratings(load_events(cache_dir))
    return _LOADED


def label(rating: float | None) -> str:
    """A word for a rating, for people who do not think in Elo points."""
    if rating is None:
        return "unrated"
    if rating >= 1850:
        return "elite"
    if rating >= 1720:
        return "strong"
    if rating >= 1600:
        return "good"
    if rating >= 1480:
        return "average"
    return "weak"


def write_store(r: Ratings, path: Path = STORE) -> None:
    rows = {}
    for rank, (team, value) in enumerate(r.ranked(min_games=1), start=1):
        rows[str(team)] = {"name": r.names.get(team), "elo": round(value, 1),
                           "games": r.games.get(team, 0), "rank": rank,
                           "league": r.home_comp.get(team)}
    path.write_text(json.dumps({"teams": rows, "params": r.params,
                                "logLoss": r.log_loss / max(1, r.scored),
                                "scored": r.scored}, indent=1))


def _tune(events) -> None:
    base = Ratings(events, {"home_adv": 0, "k_league": 0, "k_continental": 0,
                            "k_cup": 0, "k_friendly": 0})
    print(f"no-skill baseline (home advantage only off): {base.log_loss / base.scored:.4f}")
    best = None
    for k_off in (0, 3, 6, 10, 15):
        for kc in (20, 30):
            r = Ratings(events, {"k_offset": k_off, "k_continental": kc})
            ll = r.log_loss / r.scored
            # The cross-league games are the ones the offset exists for, and a
            # few hundred of them barely register in a total of twelve
            # thousand, so they are scored on their own as well.
            print(f"  K offset {k_off:>4}  Kcont {kc:>3}  log loss {ll:.4f}  "
                  f"cross-league {r.cross_ll / max(1, r.cross_n):.4f} over {r.cross_n}")
            if best is None or r.cross_ll / max(1, r.cross_n) < best[0]:
                best = (r.cross_ll / max(1, r.cross_n), k_off, kc)
    print("best:", best)


# ------------------------------------------------------------ for the picks
#
# How a team leg's chance is worked out once strength is known. Fitted by
# logistic regression on 48,549 replayed legs from five leagues since August
# 2025 (calib/strength_eval/stack.py, V2=1), every input computed as of
# kick-off. Held out one league at a time it beat both the live record figure
# and the league projection in all five: Premier League log loss 0.6501
# against 0.6695 for the record and 0.6605 for the projection. Its stated
# chances land within a point or two of what happened from 20% to 80%. On
# Champions League legs it never saw: 0.6654 against 0.6818 for the record.
#
# Inputs, all on the log-odds scale, in this order:
#   record      the shrunk hit rate, (hits + 2) / (n + 4)
#   similar     the hit rate in matches against similar-strength opposition,
#               shrunk towards the record by SIMILAR_PRIOR phantom matches
#   elo         the count model's chance with the strength expectation: the
#               side's average, moved by the stat's slope (strength_slopes.json)
#               for the difference between tonight's gap and its usual one
#   projection  the count model's chance with the league projection
#
# The first version weighted the side's own matches by how similar the
# opposition was and averaged them. It could not extrapolate: LASK have never
# been 230 points worse than anyone, so at Liverpool their "expectation" was
# whichever single match came nearest, a 40-shot night against Celtic, and it
# said 33 shots. The slope moves the whole average instead, the right way.
#
# The record's weight comes out NEGATIVE once the others are in. That is not
# a bug: the projection and the Elo expectation are built from the same
# matches, and the regression is saying a raw record that runs ahead of them
# is mostly luck. It is the same overconfidence the LESSONS table shows.
STACK_WITH_PROJECTION = (-0.302, -0.520, 0.252, 0.820, 0.764)
# No league projection: cross-league ties (Champions League, cups,
# internationals), or a side the league fit could not rate. Elo carries it.
STACK_WITHOUT_PROJECTION = (-0.241, -0.509, 0.315, 1.312)

# Width of "similar opposition", in Elo points of rating gap. Matches whose
# gap (this side minus that opponent, on the day) sits near tonight's gap get
# the weight. 125 was best of 75, 125 and 200 in the replay; 75 starved the
# sample and 200 barely differed from no weighting.
SIMILAR_SIGMA = 125.0
# Phantom matches the similar-opposition rate is shrunk towards the whole
# record with, against the summed weight of the similar ones, so a sample
# that is mostly dissimilar does not speak loudly.
SIMILAR_PRIOR = 4.0

SLOPES_FILE = HERE / "strength_slopes.json"
_SLOPES: dict = {}


def slopes() -> dict:
    """Log change in each stat per 100 Elo of advantage, by "PERIOD|Stat".
    Shots about +0.11, corners +0.13, yellow cards -0.05, saves -0.12."""
    if not _SLOPES:
        try:
            _SLOPES.update(json.loads(SLOPES_FILE.read_text()))
        except (OSError, ValueError):
            _SLOPES["_missing"] = 0.0
    return _SLOPES


def fit_slopes(report_dir: Path = HERE / "reports", r: "Ratings | None" = None) -> dict:
    """Fit the per-stat slopes from every football record in the built reports.

    Within each team, the log of a stat (plus a half, so zeros count) against
    the rating gap on the day, home advantage included. Centring within team
    keeps a good side's high averages from posing as a strength effect.
    """
    import collections
    import make_index
    r = r or ratings()
    seen, data = set(), collections.defaultdict(list)
    for path in sorted(report_dir.glob("*.html")):
        if path.name.startswith("pick-"):
            continue
        for entry, _meta in make_index.read_entries(path):
            if (entry.get("fixture") or {}).get("sport", "football") != "football":
                continue
            for ti, recs in enumerate(entry.get("records") or []):
                tid = entry["teams"][ti]["id"]
                for rec in recs:
                    if (tid, rec.get("id")) in seen:
                        continue
                    seen.add((tid, rec.get("id")))
                    ts = _date_ts(rec.get("date"))
                    o = r.rating_at(rec.get("opponent_id"), ts) if ts else None
                    m = r.rating_at(tid, ts) if ts else None
                    if o is None or m is None:
                        continue
                    x = (m - o + (HOME_ADV if rec.get("venue") == "home" else -HOME_ADV)) / 100
                    for period, block in (rec.get("stats") or {}).items():
                        for name, v in block.items():
                            if isinstance(v, (int, float)) and v >= 0:
                                data[(period, name)].append((tid, x, float(v)))
    out = {}
    for (period, name), rows in data.items():
        if len(rows) < 2000:
            continue
        by_team = collections.defaultdict(list)
        for t, x, v in rows:
            by_team[t].append((x, v))
        sxy = sxx = 0.0
        for lst in by_team.values():
            if len(lst) < 8:
                continue
            mx = sum(x for x, _ in lst) / len(lst)
            mv = sum(v for _, v in lst) / len(lst)
            for x, v in lst:
                sxy += (x - mx) * math.log((v + 0.5) / (mv + 0.5))
                sxx += (x - mx) ** 2
        if sxx > 0:
            out[f"{period}|{name}"] = round(sxy / sxx, 4)
    return out


def _logit(p):
    return probability.logit(p, 1e-3)


def _date_ts(date: str | None) -> float | None:
    from datetime import datetime, timezone
    try:
        return datetime.strptime((date or "")[:10], "%Y-%m-%d").replace(
            tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


class Side:
    """Strength context for one team in one fixture, computed once and reused
    for every leg on that team."""

    def __init__(self, r: Ratings, team_id, opp_id, kickoff, home: bool, sample: list[dict]):
        self.team = r.rating_at(team_id, kickoff)
        self.opp = r.rating_at(opp_id, kickoff)
        hfa = r.params["home_adv"]
        self.team_games = r.games_before(team_id, kickoff)
        self.opp_games = r.games_before(opp_id, kickoff)
        self.gap = None if self.team is None or self.opp is None else self.team - self.opp
        wdl = (r.win_draw_loss(team_id, opp_id, kickoff) if home
               else r.win_draw_loss(opp_id, team_id, kickoff))
        if wdl and not home:
            wdl = (wdl[2], wdl[1], wdl[0])
        self.win_draw_loss = wdl
        self.hfa = hfa
        self.home = home
        self.elo_gap = self.gap
        self.market_gap = None
        self.market_weight = 0.0
        self.market_wdl = None
        # Each past match: our rating minus theirs at the time, and the venue.
        self._past = []
        for rec in sample:
            ts = _date_ts(rec.get("date"))
            o = r.rating_at(rec.get("opponent_id"), ts) if ts else None
            m = r.rating_at(team_id, ts) if ts else None
            self._past.append((None if o is None or m is None else m - o, rec.get("venue")))
        self._derive()

    def _derive(self) -> None:
        """Similar-opposition weights and the shift, from whatever gap is
        current (Elo alone, or Elo moved towards the market)."""
        self.weights = []
        xs = []
        for diff, venue in self._past:
            if diff is None or self.gap is None:
                self.weights.append(1e-3)
            else:
                self.weights.append(math.exp(-0.5 * ((diff - self.gap) / SIMILAR_SIGMA) ** 2))
            xs.append(None if diff is None else (diff + (self.hfa if venue == "home" else -self.hfa)) / 100)
        known = [x for x in xs if x is not None]
        # How far tonight's gap, home advantage in, sits from the side's usual.
        self.shift = (None if self.gap is None or not known
                      else (self.gap + (self.hfa if self.home else -self.hfa)) / 100 - sum(known) / len(known))

    def use_market(self, win: float, draw: float, loss: float, weight: float) -> None:
        """Move tonight's gap towards the one the exchange's match odds imply.

        The market's 1X2 is turned back into a rating gap on the same scale
        as the Elo (expected score = win + half the draw, through the same
        logistic, home advantage taken out), so the per-stat slopes fitted on
        Elo still apply. The market knows things the ratings cannot: injuries,
        rotation, a manager sacked on Tuesday. `weight` is how far to move,
        set by how much money the market has seen.
        """
        e = min(max(win + draw / 2, 0.02), 0.98)
        with_hfa = 400 * math.log10(e / (1 - e))
        self.market_gap = with_hfa - (self.hfa if self.home else -self.hfa)
        self.market_wdl = (win, draw, loss)
        if self.gap is None:
            return
        self.market_weight = weight
        self.gap = weight * self.market_gap + (1 - weight) * self.elo_gap
        self._derive()

    def usable(self) -> bool:
        return self.gap is not None and self.team_games >= 5 and self.opp_games >= 5

    def public(self) -> dict:
        out = {"team": round(self.team) if self.team is not None else None,
               "opp": round(self.opp) if self.opp is not None else None,
               "teamLabel": label(self.team), "oppLabel": label(self.opp),
               "gap": round(self.gap) if self.gap is not None else None}
        if self.win_draw_loss:
            out["win"], out["draw"], out["loss"] = (round(x, 3) for x in self.win_draw_loss)
        if self.market_gap is not None:
            out["eloGap"] = round(self.elo_gap) if self.elo_gap is not None else None
            out["marketGap"] = round(self.market_gap)
            out["marketWeight"] = round(self.market_weight, 2)
            out["marketWin"], out["marketDraw"], out["marketLoss"] = (round(x, 3) for x in self.market_wdl)
        return out


def leg_chance(side: Side, sample_values: list, keep: list[bool], hits: int, n: int,
               line: float, over: bool, expected, price_fn, slope_key: str = "") -> dict | None:
    """Strength-aware chance for one team leg, plus what it was built from.

    `sample_values` and `keep` are parallel to the sample the Side was built
    on: the value of this stat in each match, and whether that match had one.
    `price_fn(expected)` is model.price for this leg with a given expectation
    and returns its probability (or None).
    """
    if not side.usable():
        return None
    ws = [w for w, k in zip(side.weights, keep) if k]
    vals = [v for v, k in zip(sample_values, keep) if k]
    if len(ws) != n or not ws:
        return None
    sw = sum(ws)
    landed = [(v > line) == over for v in vals]
    wh = sum(w for w, h in zip(ws, landed) if h)
    shr = (hits + 2) / (n + 4)
    rate = wh / sw if sw else None
    sim = shr if rate is None else (rate * sw + SIMILAR_PRIOR * shr) / (sw + SIMILAR_PRIOR)
    b = slopes().get(slope_key, 0.0)
    ev = (sum(vals) / len(vals)) * math.exp(b * side.shift) if side.shift is not None else None
    p_rec = price_fn(None)
    p_elo = price_fn(ev) if ev is not None else None
    if p_elo is None:
        p_elo = p_rec
    if p_rec is None:
        return None
    if expected is not None:
        p_proj = price_fn(expected)
        if p_proj is None:
            return None
        x = (1.0, _logit(shr), _logit(sim), _logit(p_elo), _logit(p_proj))
        w = STACK_WITH_PROJECTION
    else:
        x = (1.0, _logit(shr), _logit(sim), _logit(p_elo))
        w = STACK_WITHOUT_PROJECTION
    z = sum(a * b for a, b in zip(w, x))
    p = 1 / (1 + math.exp(-z))
    return {"p": p, "similar": round(sim, 3), "similarHits": round(wh, 1),
            "similarN": round(sw, 1), "eloExpected": round(ev, 2) if ev is not None else None,
            "projection": round(expected, 2) if expected is not None else None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--team", help="show one club (any part of the name)")
    parser.add_argument("--tune", action="store_true")
    parser.add_argument("--top", type=int, default=40)
    parser.add_argument("--slopes", action="store_true",
                        help="refit strength_slopes.json from the built reports")
    args = parser.parse_args()

    if args.slopes:
        fitted = fit_slopes()
        SLOPES_FILE.write_text(json.dumps(fitted, indent=1, sort_keys=True))
        print(f"wrote {len(fitted)} slopes to {SLOPES_FILE.name}")
        return

    events = load_events()
    if args.tune:
        _tune(events)
        return
    r = Ratings(events)
    write_store(r)
    print(f"{len(events)} matches, {len(r.rating)} teams, "
          f"log loss {r.log_loss / max(1, r.scored):.4f} over {r.scored} scored")
    if args.team:
        needle = args.team.lower()
        for team, name in r.names.items():
            if needle in (name or "").lower():
                print(f"{name} ({team}): {r.rating[team]:.0f}, {r.games[team]} games, "
                      f"{label(r.rating[team])}, league {r.home_comp.get(team)}")
        return
    for rank, (team, value) in enumerate(r.ranked()[:args.top], start=1):
        print(f"{rank:>3} {value:7.1f}  {r.names.get(team)}  ({r.home_comp.get(team)})")


if __name__ == "__main__":
    main()
