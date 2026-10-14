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
import os
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--team", help="show one club (any part of the name)")
    parser.add_argument("--tune", action="store_true")
    parser.add_argument("--top", type=int, default=40)
    args = parser.parse_args()

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
