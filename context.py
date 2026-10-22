"""
The case for a fixture, in the order a tipster makes it.

    import context
    b = context.brief(entry, meta)     # everything below, for one fixture
    context.opp_allows(leg, entry)     # what the opponent concedes in a leg's stat

Why this exists. A good preview does not say "Napoli over 14.5 shots, 71%".
It says: Napoli lost both openers and need the points, Bodo allow 25 shots a
game away in this competition, so take Napoli over 14.5 shots. The chance is
the same either way; the second version tells you what would have to be true
for the bet to lose, which is what lets you check it against the team news.

Everything here is read from what is already on disk, never fetched:

  form        the last five results, dated, with the score and W/D/L
  counts      the last ten: scored in, conceded in, clean sheets, BTTS,
              over 2.5, failed to score
  xg          expected goals for and against over the last five
  table       points and games in this competition this season, and the
              position when a cached standings table has the team in it
  next        the next three fixtures after this one (cache/team_*_events_next_0)
  absences    the injury list, each name with how often he started lately
  score       the likeliest result and score, with home, draw and away
              chances, from an independent Poisson model of every club's
              attack and defence (scoremodels.py, chosen and walk-forward
              tested in CASE-SCORE.md); the older goals-projection and xG
              route only when the model has never seen one of the sides
  facts       the handful of those that are actually unusual, in plain sentences
  opp_allows  per leg: what the opposition concedes in that stat, at the
              matching venue, in this competition when there are enough games

Nothing here changes a chance or a ranking. It is the argument, not the model.
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"

FORM_N = 5        # results in the form strip
COUNT_N = 10      # games behind the counts
XG_N = 5          # games behind the xG averages
ALLOW_N = 10      # most games behind an opponent-allows figure
ALLOW_MIN = 4     # fewest same-competition games before that split is used
NEXT_N = 3        # upcoming fixtures shown
SEASON_GAP = 45   # days without a game in a competition that end a season

# Stats a side concedes, so "Bodo allow 25 shots" reads naturally. Anything
# else (cards, fouls, throw-ins) is phrased as what the opponents do.
ALLOWED_STATS = {"Goals", "Total shots", "Shots on target", "Corner kicks", "Big chances",
                 "Expected goals", "Shots inside box", "Touches in penalty area"}

# Stats that describe the match, not one side, so "what the opponent allows"
# has no meaning for them.
MATCH_STATS = {"Match goals", "Both teams to score", "Match corners", "Match cards",
               "Both teams carded"}

SHORT_COMP = {
    "UEFA Champions League": "UCL", "UEFA Europa League": "UEL",
    "UEFA Conference League": "UECL", "UEFA Europa Conference League": "UECL",
    "Premier League": "PL", "Championship": "Champ", "EFL Cup": "EFL Cup",
    "FA Cup": "FA Cup", "LaLiga": "LaLiga", "Bundesliga": "BL", "Serie A": "Serie A",
    "Ligue 1": "L1", "Eredivisie": "Ered", "Liga Portugal": "Liga PT",
}


# ------------------------------------------------------------------ helpers

def _short(comp: str | None) -> str:
    comp = comp or ""
    return SHORT_COMP.get(comp, comp if len(comp) <= 12 else comp[:11] + ".")


def _finished(r: dict) -> bool:
    return isinstance(r.get("goals_for"), (int, float)) and isinstance(r.get("goals_against"), (int, float))


def _side_index(entry: dict, name: str | None) -> int | None:
    for i, t in enumerate(entry.get("teams") or []):
        if t.get("name") == name:
            return i
    return None


def records(entry: dict, idx: int, before: float | None = None) -> list[dict]:
    """One side's finished matches, oldest first, all before kick-off."""
    try:
        recs = entry["records"][idx] or []
    except (KeyError, IndexError, TypeError):
        return []
    cut = None
    if before:
        cut = datetime.fromtimestamp(before, timezone.utc).strftime("%Y-%m-%d")
    out = [r for r in recs if _finished(r) and (cut is None or (r.get("date") or "") < cut)]
    return sorted(out, key=lambda r: r.get("date") or "")


def _stat(block: dict | None, period: str, stat: str):
    try:
        v = block[period][stat]
    except (KeyError, TypeError):
        return None
    return v if isinstance(v, (int, float)) else None


def _date(d: str) -> str:
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%d %b").lstrip("0")
    except (TypeError, ValueError):
        return d or ""


def _of(k: int, n: int) -> str:
    return f"{k} of their last {n}"


# --------------------------------------------------------------- the pieces

def form(recs: list[dict], n: int = FORM_N) -> list[dict]:
    """The last n results, newest last, in the shape the page prints."""
    return [{
        "date": _date(r.get("date")), "comp": _short(r.get("competition")),
        "venue": "H" if r.get("venue") == "home" else "A",
        "opp": r.get("opponent") or "?", "gf": int(r["goals_for"]), "ga": int(r["goals_against"]),
        "res": r.get("result") or ("W" if r["goals_for"] > r["goals_against"]
                                   else "L" if r["goals_for"] < r["goals_against"] else "D"),
    } for r in recs[-n:]]


def counts(recs: list[dict], n: int = COUNT_N) -> dict:
    last = recs[-n:]
    k = len(last)
    gf = [r["goals_for"] for r in last]
    ga = [r["goals_against"] for r in last]
    return {
        "n": k,
        "won": sum(1 for r in last if r["goals_for"] > r["goals_against"]),
        "lost": sum(1 for r in last if r["goals_for"] < r["goals_against"]),
        "scored": sum(1 for x in gf if x > 0),
        "failed": sum(1 for x in gf if x == 0),
        "conceded": sum(1 for x in ga if x > 0),
        "clean": sum(1 for x in ga if x == 0),
        "btts": sum(1 for a, b in zip(gf, ga) if a > 0 and b > 0),
        "over25": sum(1 for a, b in zip(gf, ga) if a + b >= 3),
        "under15": sum(1 for a, b in zip(gf, ga) if a + b <= 1),
        "gf": sum(gf), "ga": sum(ga),
    }


def xg(recs: list[dict], n: int = XG_N) -> dict | None:
    """Expected goals for and against, over the last n games that carry it."""
    rows = [(_stat(r.get("stats"), "ALL", "Expected goals"), _stat(r.get("against"), "ALL", "Expected goals"))
            for r in recs]
    rows = [(a, b) for a, b in rows if a is not None and b is not None][-n:]
    if len(rows) < 2:
        return None
    k = len(rows)
    return {"n": k, "for": sum(a for a, _ in rows), "against": sum(b for _, b in rows),
            "for_pg": sum(a for a, _ in rows) / k, "against_pg": sum(b for _, b in rows) / k}


def _this_season(recs: list[dict], tid) -> list[dict]:
    """This season's games in one competition: back from the latest until a long gap."""
    comp = [r for r in recs if r.get("tournament_id") == tid]
    if not comp:
        return []
    out = [comp[-1]]
    for r in reversed(comp[:-1]):
        try:
            gap = (datetime.strptime(out[0]["date"], "%Y-%m-%d")
                   - datetime.strptime(r["date"], "%Y-%m-%d")).days
        except (KeyError, ValueError):
            break
        if gap > SEASON_GAP:
            break
        out.insert(0, r)
    return out


def _standing(tid, team_id) -> dict | None:
    """Position from the newest cached standings table that has this team in it."""
    if tid is None or team_id is None:
        return None
    files = sorted(CACHE.glob(f"unique-tournament_{tid}_season_*_standings_total.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for table in data.get("standings") or []:
            rows = table.get("rows") or []
            for row in rows:
                if (row.get("team") or {}).get("id") == team_id:
                    return {"pos": row.get("position"), "of": len(rows), "points": row.get("points"),
                            "played": row.get("matches"), "age_days": (time.time() - path.stat().st_mtime) / 86400}
    return None


def table(recs: list[dict], tid, team_id) -> dict | None:
    """Points from this competition this season, and the table position if known."""
    season = _this_season(recs, tid)
    pts = sum(3 if r["goals_for"] > r["goals_against"] else 1 if r["goals_for"] == r["goals_against"] else 0
              for r in season)
    out = {"played": len(season), "points": pts, "pos": None, "of": None}
    st = _standing(tid, team_id)
    # A fresh standings table wins: the records cannot tell a qualifying round
    # from the league phase, so a side that came through qualifying would
    # otherwise carry those games into its points. A stale table is only
    # trusted for the position, and only when it agrees on games played.
    if st and st.get("age_days", 99) <= 2 and isinstance(st.get("played"), int) \
            and isinstance(st.get("points"), int) and st["played"] <= len(season):
        out.update(played=st["played"], points=st["points"], pos=st["pos"], of=st["of"])
    elif st and st.get("played") == len(season):
        out.update(pos=st["pos"], of=st["of"])
    return out if season else None


def next_fixtures(team_id, after: float, n: int = NEXT_N) -> list[dict]:
    """The next n fixtures after this kick-off, from the 07:00 run's cache."""
    path = CACHE / f"team_{team_id}_events_next_0.json"
    try:
        events = json.loads(path.read_text(encoding="utf-8")).get("events") or []
    except (OSError, ValueError):
        return []
    out = []
    for ev in sorted(events, key=lambda e: e.get("startTimestamp") or 0):
        ts = ev.get("startTimestamp") or 0
        if ts <= after + 3600:
            continue
        home = ev.get("homeTeam") or {}
        away = ev.get("awayTeam") or {}
        at_home = home.get("id") == team_id
        comp = ((ev.get("tournament") or {}).get("uniqueTournament") or {}).get("name") \
            or (ev.get("tournament") or {}).get("name")
        out.append({"ts": ts, "date": time.strftime("%d %b", time.localtime(ts)).lstrip("0"),
                    "days": (ts - after) / 86400, "venue": "H" if at_home else "A",
                    "opp": (away if at_home else home).get("name") or "?", "comp": _short(comp)})
        if len(out) >= n:
            break
    return out


def absences(entry: dict, idx: int, side: str, recs: list[dict]) -> list[dict]:
    """The injury list, each name with how many of the last ten he started."""
    inj = (entry.get("injuries") or {}).get(side) or []
    if not inj:
        return []
    last_ids = {r.get("id") for r in recs[-COUNT_N:]}
    try:
        apps = entry["players"][idx] or []
    except (KeyError, IndexError, TypeError):
        apps = []
    starts: dict[str, int] = {}
    for a in apps:
        if a.get("match_id") in last_ids and a.get("started"):
            starts[a.get("player")] = starts.get(a.get("player"), 0) + 1
    out = []
    for row in inj:
        name = row[0] if isinstance(row, (list, tuple)) and row else str(row)
        status = row[2] if isinstance(row, (list, tuple)) and len(row) > 2 else "Out"
        pos = row[1] if isinstance(row, (list, tuple)) and len(row) > 1 else ""
        out.append({"name": name, "status": status, "starts": starts.get(name, 0),
                    "of": len(last_ids), "pos": pos})
    out.sort(key=lambda a: -a["starts"])
    return out


def _elo_1x2(entry: dict):
    """Home win, draw, away win from strength.py, or None if either side is unrated."""
    teams = entry.get("teams") or []
    home = next((t for t in teams if t.get("side") == "home"), None)
    away = next((t for t in teams if t.get("side") == "away"), None)
    if not home or not away:
        return None
    try:
        import strength
        return strength.ratings().win_draw_loss(home.get("id"), away.get("id"),
                                                (entry.get("fixture") or {}).get("kickoff"))
    except Exception:
        return None


def _split_to(total: float, edge: float) -> tuple[float, float]:
    """Home and away goal means with this total whose Poisson P(H) - P(A) is `edge`."""
    def diff(share):
        lh, la = total * share, total * (1 - share)
        ph = pa = 0.0
        for i in range(10):
            pi = _poisson(i, lh)
            for j in range(10):
                p = pi * _poisson(j, la)
                if i > j:
                    ph += p
                elif i < j:
                    pa += p
        return ph - pa
    lo, hi = 0.05, 0.95
    for _ in range(40):
        mid = (lo + hi) / 2
        if diff(mid) < edge:
            lo = mid
        else:
            hi = mid
    share = (lo + hi) / 2
    return total * share, total * (1 - share)


def _poisson(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


# The scoreline model. Walk-forward over 3,595 cached matches (CASE-SCORE.md),
# the route below this (the report's goals projection, or recent xG with the
# Elo re-split) scored 0.2153 ranked probability score and 1.0364 log loss on
# the home, draw and away chances; this model scored 0.2101 and 1.0134, and
# was better in all four test windows. Dixon-Coles and a bivariate Poisson
# did no better: the low-score correction moved the fourth decimal and the
# shared component fitted to nothing. The half-life and ridge are the best
# pooled validation setting from those windows' training data. Fitted once
# per process on every competitive result in the cache, so it needs no
# match statistics and covers cup ties and European nights.
SCORE_KIND = "poisson"
SCORE_HALF_LIFE = 1460.0
SCORE_RIDGE = 2.0
_SCORE_MODEL: dict = {}


def score_matches(cache: Path = CACHE) -> list[dict]:
    """Every competitive result in the cache, as the scoreline model reads them."""
    import strength
    return [{"home": e["home"], "away": e["away"], "hg": e["hg"], "ag": e["ag"], "ts": e["ts"]}
            for e in strength.load_events(cache)
            if e["kind"] != "friendly" and e["home"] is not None and e["away"] is not None]


def _score_model():
    if "m" not in _SCORE_MODEL:
        try:
            import scoremodels
            _SCORE_MODEL["m"] = scoremodels.TeamGoals(SCORE_KIND, SCORE_HALF_LIFE, SCORE_RIDGE).fit(
                score_matches(), time.time())
        except Exception:
            _SCORE_MODEL["m"] = None
    return _SCORE_MODEL["m"]


def _model_score(entry: dict) -> dict | None:
    teams = entry.get("teams") or []
    home = next((t for t in teams if t.get("side") == "home"), None)
    away = next((t for t in teams if t.get("side") == "away"), None)
    if not home or not away:
        return None
    m = _score_model()
    if m is None or not (m.knows(home.get("id")) and m.knows(away.get("id"))):
        return None
    import scoremodels
    grid = m.grid(home["id"], away["id"])
    lh, la = m.expected_goals(home["id"], away["id"])
    ph, pd, pa = scoremodels.outcome_probs(grid)
    bi, bj, pb = scoremodels.pick_score(grid)
    return {"home": bi, "away": bj, "lh": lh, "la": la, "p": pb, "ph": ph, "pd": pd, "pa": pa,
            "source": "team attack and defence ratings (backtested)"}


def score(entry: dict, hrecs: list[dict], arecs: list[dict]) -> dict | None:
    """The single most likely scoreline, and where the goal means came from."""
    modelled = _model_score(entry)
    if modelled:
        return modelled
    return legacy_score(entry, hrecs, arecs)


def legacy_score(entry: dict, hrecs: list[dict], arecs: list[dict]) -> dict | None:
    """The route before CASE-SCORE.md, kept for sides the model has not seen."""
    proj = ((entry.get("projection") or {}).get("ALL") or {}).get("Goals")
    source = "goals projection"
    if isinstance(proj, list) and len(proj) == 2 and all(isinstance(x, (int, float)) for x in proj):
        lh, la = float(proj[0]), float(proj[1])
    else:
        hx, ax = xg(hrecs, COUNT_N), xg(arecs, COUNT_N)
        if not hx or not ax:
            return None
        # Each side's recent xG for, averaged with what the other side has
        # been allowing. No home edge and no strength adjustment: this is a
        # rough read for cross-league ties, and it says so on the page.
        lh = (hx["for_pg"] + ax["against_pg"]) / 2
        la = (ax["for_pg"] + hx["against_pg"]) / 2
        source = "recent xG (rough, untested)"
        # Recent xG knows nothing about who it was made against, which across
        # leagues is most of the story. Elo does (strength.py, calibrated over
        # thousands of results), so when it rates both sides the goals are
        # re-split between them until home-win minus away-win matches Elo's,
        # keeping the xG total. Elo then decides the result; xG only the goals.
        elo = _elo_1x2(entry)
        if elo:
            lh, la = _split_to(lh + la, elo[0] - elo[2])
            source = "Elo for the result, recent xG for the goals (untested)"
    # The single likeliest scoreline from two Poisson counts is nearly always
    # 1-1 or 1-0, which says nothing. So: the likeliest result first, then the
    # likeliest score within that result, the way a preview calls a game.
    grid = {(i, j): _poisson(i, lh) * _poisson(j, la) for i in range(9) for j in range(9)}
    ph = sum(p for (i, j), p in grid.items() if i > j)
    pd = sum(p for (i, j), p in grid.items() if i == j)
    pa = sum(p for (i, j), p in grid.items() if i < j)
    want = max((ph, "H"), (pd, "D"), (pa, "A"))[1]
    keep = {"H": lambda i, j: i > j, "D": lambda i, j: i == j, "A": lambda i, j: i < j}[want]
    (bi, bj), pb = max(((k, p) for k, p in grid.items() if keep(*k)), key=lambda kp: kp[1])
    return {"home": bi, "away": bj, "lh": lh, "la": la, "p": pb, "ph": ph, "pd": pd, "pa": pa,
            "source": source}


# ---------------------------------------------------------- per-leg context

def opp_allows(leg: dict, entry: dict) -> dict | None:
    """What the opposition concedes in this leg's stat, where it matters.

    The opponent's games at the opposite venue to this one (so a home leg is
    read against the opponent's away games), in this competition when there
    are at least ALLOW_MIN of them, otherwise in every competition. Team legs
    only: a player's line depends on his minutes as much as on the opponent.
    """
    if leg.get("player") or not leg.get("team"):
        return None
    stat, period = leg.get("stat"), leg.get("period") or "ALL"
    if not stat or stat in MATCH_STATS:
        return None
    me = _side_index(entry, leg["team"])
    if me is None:
        return None
    opp = 1 - me
    my_side = (entry.get("teams") or [{}, {}])[me].get("side")
    want = "away" if my_side == "home" else "home"
    kick = (entry.get("fixture") or {}).get("kickoff")
    tid = (entry.get("fixture") or {}).get("tournamentId")
    recs = [r for r in records(entry, opp, kick) if r.get("venue") == want]

    def value(r):
        if stat == "Goals" and period == "ALL":
            return r.get("goals_against")
        return _stat(r.get("against"), period, stat)

    same = [r for r in recs if r.get("tournament_id") == tid and value(r) is not None][-ALLOW_N:]
    scope = "in this competition"
    rows = same
    if len(same) < ALLOW_MIN:
        rows = [r for r in recs if value(r) is not None][-ALLOW_N:]
        scope = "in all competitions"
    if len(rows) < ALLOW_MIN:
        return None
    vals = [value(r) for r in rows]
    line = leg.get("line")
    over = leg.get("over", True)
    if leg.get("alt") and isinstance(leg.get("threshold"), (int, float)):
        line = leg["threshold"] - 0.5
    hits = None
    if isinstance(line, (int, float)):
        hits = sum(1 for v in vals if (v > line if over else v < line))
    team_name = (entry.get("teams") or [{}, {}])[opp].get("name") or "The opposition"
    avg = sum(vals) / len(vals)
    where = "away" if want == "away" else "at home"
    period_txt = "" if period == "ALL" else (" in the first half" if period == "1ST" else " in the second half")
    stat_txt = stat.lower()
    if stat in ALLOWED_STATS:
        text = (f"{team_name} allow {avg:.1f} {stat_txt}{period_txt} a game {where} {scope} "
                f"(last {len(vals)})")
    else:
        # "Allow" reads wrong for cards, fouls and throw-ins, which the side
        # concedes nothing of; say what their opponents do instead.
        text = (f"{team_name}'s opponents average {avg:.1f} {stat_txt}{period_txt} when "
                f"{team_name} are {where} {scope} (last {len(vals)})")
    rank = league_rank(team_name, stat, period) if stat in ALLOWED_STATS else None
    if rank and (rank["pos"] <= 5 or rank["pos"] > rank["of"] - 5):
        word = "most" if rank["pos"] <= 5 else "fewest"
        p = rank["pos"] if word == "most" else rank["of"] - rank["pos"] + 1
        text += f", the {p}{_ordinal(p)} {word} in {rank['league']}"
    if hits is not None:
        side = "over" if over else "under"
        text += f": {hits} of {len(vals)} went {side} {line:g}"
    return {"team": team_name, "avg": avg, "n": len(vals), "hits": hits, "line": line,
            "scope": scope, "where": where, "text": text}


# ---------------------------------------------------------------- the facts

def _facts_for(name: str, c: dict, x: dict | None, tb: dict | None, nxt: list, abs_: list,
               comp: str) -> list[tuple[float, str]]:
    """The unusual things about one side, each with a weight for ranking."""
    out: list[tuple[float, str]] = []
    n = c["n"]
    if n >= 5:
        f = lambda k: k / n
        if f(c["won"]) >= 0.7:
            out.append((f(c["won"]), f"{name} have won {_of(c['won'], n)}."))
        if f(c["lost"]) >= 0.5:
            out.append((f(c["lost"]), f"{name} have lost {_of(c['lost'], n)}."))
        if f(c["conceded"]) >= 0.8:
            out.append((f(c["conceded"]), f"{name} have conceded in {_of(c['conceded'], n)} "
                                           f"({c['clean']} clean sheet{'s' if c['clean'] != 1 else ''})."))
        if f(c["clean"]) >= 0.5:
            out.append((f(c["clean"]), f"{name} have kept {c['clean']} clean sheets in their last {n}."))
        if f(c["failed"]) >= 0.4:
            out.append((f(c["failed"]), f"{name} have failed to score in {_of(c['failed'], n)}."))
        if f(c["scored"]) >= 0.9:
            out.append((f(c["scored"]) - 0.05, f"{name} have scored in {_of(c['scored'], n)}."))
        if f(c["btts"]) >= 0.7:
            out.append((f(c["btts"]), f"Both teams scored in {_of(c['btts'], n)} {name} games."))
        if f(c["btts"]) <= 0.2:
            out.append((1 - f(c["btts"]) - 0.1, f"Both teams scored in only {_of(c['btts'], n)} {name} games."))
        if f(c["over25"]) >= 0.7:
            out.append((f(c["over25"]) - 0.05, f"{c['over25']} of {name}'s last {n} had three goals or more."))
        if f(c["under15"]) >= 0.5:
            out.append((f(c["under15"]), f"{c['under15']} of {name}'s last {n} had one goal or fewer."))
    if x and x["n"] >= 3:
        if x["against_pg"] >= 1.8:
            out.append((0.75, f"{name} have conceded {x['against']:.1f} xG in their last {x['n']}."))
        if x["for_pg"] >= 2.2:
            out.append((0.72, f"{name} have created {x['for']:.1f} xG in their last {x['n']}."))
        if x["for_pg"] <= 0.9:
            out.append((0.7, f"{name} have created only {x['for']:.1f} xG in their last {x['n']}."))
    if tb and tb["played"] >= 2:
        ppg = tb["points"] / tb["played"]
        pos = f", {tb['pos']}{_ordinal(tb['pos'])} of {tb['of']}" if tb.get("pos") else ""
        if ppg <= 1.0:
            out.append((0.8, f"{name} have {tb['points']} point{'s' if tb['points'] != 1 else ''} "
                             f"from {tb['played']} {comp} games{pos}: this one matters to them."))
        elif ppg >= 2.5:
            out.append((0.6, f"{name} have {tb['points']} points from {tb['played']} {comp} games{pos}."))
    if nxt and nxt[0]["days"] <= 4:
        g = nxt[0]
        out.append((0.65, f"{name} play again in {g['days']:.0f} days ({g['comp']}, "
                          f"{'home' if g['venue'] == 'H' else 'away'} to {g['opp']}): rotation is possible."))
    regulars = [a for a in abs_ if a["of"] and a["starts"] >= max(3, a["of"] * 0.5)]
    if regulars:
        names = ", ".join(f"{a['name']} ({a['starts']} starts in {a['of']})" for a in regulars[:3])
        out.append((0.85, f"{name} are without {names}."))
    return out


def _ordinal(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    return "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _last_result(name: str, recs: list[dict]) -> str | None:
    if not recs:
        return None
    r = recs[-1]
    gf, ga = int(r["goals_for"]), int(r["goals_against"])
    word = "win" if gf > ga else "defeat" if gf < ga else "draw"
    where = "at home to" if r.get("venue") == "home" else "away to"
    hi, lo = max(gf, ga), min(gf, ga)
    return f"{name} come off a {hi}-{lo} {word} {where} {r.get('opponent')} ({_short(r.get('competition'))}, {_date(r.get('date'))})."


def brief(entry: dict, meta: dict) -> dict:
    """Everything the page needs to argue one fixture."""
    fx = entry.get("fixture") or {}
    kick = fx.get("kickoff") or meta.get("kickoff")
    tid = fx.get("tournamentId")
    comp = _short(fx.get("competition") or meta.get("competition"))
    teams = entry.get("teams") or []
    sides = []
    for idx, t in enumerate(teams[:2]):
        recs = records(entry, idx, kick)
        side = t.get("side") or ("home" if idx == 0 else "away")
        c = counts(recs)
        x = xg(recs)
        tb = table(recs, tid, t.get("id"))
        nxt = next_fixtures(t.get("id"), kick or 0)
        ab = absences(entry, idx, side, recs)
        sides.append({
            "name": t.get("name"), "side": side, "recs": recs, "form": form(recs), "counts": c,
            "xg": x, "table": tb, "next": nxt, "absences": ab,
            "facts": _facts_for(t.get("name"), c, x, tb, nxt, ab, comp) + streaks(t.get("name"), recs),
            "last": _last_result(t.get("name"), recs),
        })
    home = next((s for s in sides if s["side"] == "home"), sides[0] if sides else None)
    away = next((s for s in sides if s["side"] == "away"), sides[-1] if sides else None)
    sc = score(entry, home["recs"], away["recs"]) if home and away else None
    facts = sorted((f for s in sides for f in s["facts"]), key=lambda f: -f[0])
    ref = entry.get("referee") or {}
    if isinstance(ref.get("yellowsPerGame"), (int, float)) and ref.get("games", 0) >= 20:
        ypg = ref["yellowsPerGame"]
        if ypg >= 4.8 or ypg <= 3.2:
            facts.append((0.55, f"Referee {ref.get('name')} averages {ypg:.1f} yellows a game "
                                f"over {ref['games']} games."))
    return {"home": home, "away": away, "score": sc,
            "facts": [t for _, t in facts[:6]],
            "story": [s["last"] for s in (home, away) if s and s.get("last")]}


FAMILY_WORDS = {
    "goals": ("scored", "conceded", "clean sheet", "xG", "goals", "Both teams", "failed to score",
              "won", "lost", "without", "matters"),
    "shots": ("xG", "created", "conceded", "without", "matters", "won", "lost"),
    "cards": ("Referee", "yellows", "matters", "without"),
    "other": ("without", "matters", "rotation", "won", "lost"),
}


def _family(stat: str | None) -> str:
    s = (stat or "").lower()
    if "card" in s or "foul" in s:
        return "cards"
    if "goal" in s or "score" in s:
        return "goals"
    if "shot" in s or "corner" in s or "xg" in s:
        return "shots"
    return "other"


def case(lead_leg: dict | None, b: dict, allows: dict | None, why_for: list[str] | None = None) -> str:
    """One short paragraph: the context, the key number, the bet."""
    if not lead_leg:
        return "Nothing for us here: no leg cleared the bar on the evidence."
    team = lead_leg.get("team")
    bits = []
    words = FAMILY_WORDS[_family(lead_leg.get("stat"))]
    relevant = [f for f in b.get("facts") or [] if any(w in f for w in words)]
    side_facts = [f for f in relevant if team and team in f]
    other = [f for f in relevant if f not in side_facts]
    if b.get("story"):
        bits.append(b["story"][0] if not team or team not in b["story"][-1] else b["story"][-1])
    if allows:
        bits.append(allows["text"] + ".")
    for f in (side_facts + other)[:2]:
        if f not in bits:
            bits.append(f)
    if not allows and why_for:
        bits.append(why_for[0].rstrip(".") + ".")
    return " ".join(bits)


# =============================================================== game state
#
# How the game should go, and what that does to every bet on it. A leg can
# look poor on its record and still be a good bet tonight (a full-back who
# rarely tackles, against a side that will have the ball and run at him), and
# the reverse, so this is not a note on the page: it re-prices every leg it
# can reach, the lead is picked on that price, and the page lists the bets it
# leans towards and away from.
#
# The weights are not guessed. gs_backtest.py replays 7,000+ cached matches
# in date order with only pre-match information and fits, per stat, how much
# each of these moves the count (gs_fit.json, written with GS_BACKTEST.md):
#
#   own      the side's (or player's) average over the last 10
#   allow    what tonight's opponent allows in that stat over its last 10
#   home     home or away
#   ball     tonight's predicted share of the ball against the share this
#            side usually has (gamestate.py's formula), raised to a fitted power
#
# The backtest's verdict, in short: the opponent is worth far more than the
# possession, and possession only measurably helps some stats (player shots,
# shots on target and tackles; team corners, tackles, clearances, saves). For
# the rest its term is switched off. Counts are priced as negative binomial
# with the fitted spread, since team shots are lumpier than Poisson allows.

GS_LEAN = 0.08        # model must beat (or trail) the record by this much
GS_MIN_CHANCE = 0.6   # leans are only listed at this chance or better

# leg stat name -> gs_fit.json team stat
TEAM_FIT = {"Total shots": "Total shots", "Shots on target": "Shots on target",
            "Corner kicks": "Corner kicks", "Big chances": "Big chances", "Fouls": "Fouls",
            "Tackles": "Total tackles", "Total tackles": "Total tackles", "Yellow cards": "Yellow cards",
            "Clearances": "Clearances", "Goalkeeper saves": "Goalkeeper saves"}
TEAM_SIGN = {"Total shots": +1, "Shots on target": +1, "Corner kicks": +1, "Big chances": +1,
             "Fouls": -1, "Total tackles": -1, "Yellow cards": -1, "Clearances": -1, "Goalkeeper saves": -1}
# leg stat (lower case) -> gs_fit.json player stat
PLAYER_FIT = {"shots": "Shots", "total shots": "Shots", "shots on target": "Shots on target",
              "fouls": "Fouls", "fouled": "Fouled", "was fouled": "Fouled", "tackles": "Tackles",
              "total tackles": "Tackles"}
# player stat -> (team stat, opponent block it reads, own-team block it is scaled by), sign
PLAYER_TEAM = {"Shots": ("Total shots", "against", "stats", +1),
               "Shots on target": ("Shots on target", "against", "stats", +1),
               "Fouls": ("Fouls", "against", "stats", -1),
               "Fouled": ("Fouls", "stats", "against", +1),
               "Tackles": ("Total tackles", "against", "stats", -1)}

_FIT: dict = {}
_PAYLOADS: dict = {}
_INDEX_CACHE: dict = {}


def gs_fit() -> dict:
    if not _FIT:
        try:
            _FIT.update(json.loads((ROOT / "gs_fit.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            _FIT["missing"] = True
    return _FIT


def _nb_at_least(k: int, mu: float, alpha: float) -> float:
    if k <= 0:
        return 1.0
    if alpha < 1e-6:
        cdf, term = 0.0, math.exp(-mu)
        for i in range(k):
            cdf += term
            term *= mu / (i + 1)
        return max(0.0, 1 - cdf)
    r = 1 / alpha
    p = r / (r + mu)
    cdf, term = 0.0, p ** r
    for i in range(k):
        cdf += term
        term *= (i + r) / (i + 1) * (1 - p)
    return max(0.0, 1 - cdf)


def _model(scope: str, stat: str, own: float, allow: float, f: float, home: bool | None = None):
    """Fitted mean, the mean without the game state, and the spread, or None."""
    r = (gs_fit().get(scope) or {}).get(stat)
    if not r or own <= 0 or allow <= 0:
        return None
    c = r["coef"]
    x = [1.0, math.log(max(own, 0.05)), math.log(max(allow, 0.05))]
    if scope == "team":
        x.append(1.0 if home else 0.0)
    eta = sum(a * b for a, b in zip(c[:len(x)], x))
    ball = c[len(x)] * math.log(f) if r.get("use") else 0.0
    return {"mu": math.exp(eta + ball), "plain": math.exp(eta), "alpha": r.get("alpha", 0.0),
            "use": bool(r.get("use"))}


def _mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return sum(xs) / len(xs) if xs else None


def _payload(report: str):
    if report not in _PAYLOADS:
        try:
            import gamestate
            _PAYLOADS.clear()
            _PAYLOADS[report] = gamestate.payload_of(ROOT / "reports" / report)
        except Exception:
            _PAYLOADS[report] = None
    return _PAYLOADS.get(report)


def _fixture(report: str, event_id):
    payload = _payload(report)
    if not payload:
        return None
    import gamestate
    for i, fx in enumerate(payload.get("fixtures") or []):
        if (fx.get("fixture") or {}).get("id") == event_id:
            key = id(payload)
            if key not in _INDEX_CACHE:
                _INDEX_CACHE.clear()
                _INDEX_CACHE[key] = gamestate.matchup_index(payload)
            return gamestate.Fixture(payload, i, _INDEX_CACHE[key])
    return None


def _ball(here, usual, sign):
    if not here or not usual:
        return 1.0
    f = here / usual if sign > 0 else (100 - here) / max(1e-6, 100 - usual)
    return min(1.6, max(0.6, f))


def _team_inputs(entry: dict, t: int, key: str):
    """Own average and what the opponent allows, last 10 each, for a team stat."""
    kick = (entry.get("fixture") or {}).get("kickoff")
    mine = records(entry, t, kick)[-10:]
    theirs = records(entry, 1 - t, kick)[-10:]
    alt = "Tackles" if key == "Total tackles" else key
    own = _mean([_stat(r.get("stats"), "ALL", key) or _stat(r.get("stats"), "ALL", alt) for r in mine])
    allow = _mean([_stat(r.get("against"), "ALL", key) or _stat(r.get("against"), "ALL", alt) for r in theirs])
    return own, allow, len(mine), len(theirs)


def _player_recent(entry: dict, t: int, name: str) -> list[dict]:
    try:
        apps = [a for a in (entry["players"][t] or []) if a.get("player") == name
                and (a.get("minutes") or 0) >= 60]
    except (KeyError, IndexError, TypeError):
        return []
    return sorted(apps, key=lambda a: a.get("date") or "")[-10:]


def _player_inputs(entry: dict, t: int, name: str, stat: str):
    apps = _player_recent(entry, t, name)
    if len(apps) < 5:
        return None
    own = _mean([(a.get("stats") or {}).get(stat) or 0 for a in apps])
    team_stat, opp_block, own_block, sign = PLAYER_TEAM[stat]
    kick = (entry.get("fixture") or {}).get("kickoff")
    mine = records(entry, t, kick)[-10:]
    theirs = records(entry, 1 - t, kick)[-10:]
    alt = "Tackles" if team_stat == "Total tackles" else team_stat
    allow = _mean([_stat(r.get(opp_block), "ALL", team_stat) or _stat(r.get(opp_block), "ALL", alt) for r in theirs])
    usual = _mean([_stat(r.get(own_block), "ALL", team_stat) or _stat(r.get(own_block), "ALL", alt) for r in mine])
    oppf = (allow / usual) if allow and usual else 1.0
    return {"own": own, "oppf": max(0.2, min(5.0, oppf)), "apps": apps, "sign": sign}


def game_state(meta: dict) -> dict | None:
    """The game state for a fixture: possession, the script, and the bets it moves."""
    try:
        import gamestate as G
        F = _fixture(meta.get("report"), meta.get("id"))
    except Exception:
        return None
    if F is None or ((F.fx.get("fixture") or {}).get("sport") or "football") != "football":
        return None
    entry = F.fx
    st = F.state
    names = [t["name"] for t in entry["teams"]]
    has_ball = G.truthy(st["teams"][0]["poss"]) and G.truthy(st["teams"][1]["poss"])
    poss = st["poss"] if has_ball else None
    usual = [st["teams"][t]["poss"] for t in (0, 1)]
    dom = 0 if st["poss"][0] >= st["poss"][1] else 1
    if not has_ball:
        script = "No possession record for one side, so only the matchup is used."
    elif abs(st["poss"][0] - 50) < 6:
        script = "Even on the ball, so the matchup matters more than the possession tonight."
    else:
        script = (f"{names[dom]} should have the ball ({st['poss'][dom]:.0f}%). Backtested, that lifts their "
                  f"shots, shots on target and corners and the other side's tackles, clearances and saves; "
                  f"fouls and cards barely move with possession.")
    squads = F.squads()
    rows = []
    if not gs_fit().get("missing"):
        for t, plist in enumerate(squads["sides"]):
            for name in plist:
                for stat in PLAYER_TEAM:
                    inp = _player_inputs(entry, t, name, stat)
                    if not inp or inp["own"] <= 0:
                        continue
                    f = _ball(poss[t] if poss else None, usual[t], inp["sign"])
                    m = _model("player", stat, inp["own"], inp["oppf"], f)
                    if not m:
                        continue
                    vals = [(a.get("stats") or {}).get(stat) or 0 for a in inp["apps"]]
                    for L in (1, 2, 3, 4):
                        k = sum(1 for v in vals if v >= L)
                        rec = (k + 2) / (len(vals) + 4)
                        p = _nb_at_least(L, m["mu"], m["alpha"])
                        rows.append({"player": name, "team": names[t], "stat": stat, "line": L, "k": k,
                                     "n": len(vals), "rec": rec, "chance": p,
                                     "plain": _nb_at_least(L, m["plain"], m["alpha"]),
                                     "ball": f if m["use"] else 1.0, "oppf": inp["oppf"],
                                     "avg": inp["own"], "mu": m["mu"]})
    best, worst = {}, {}
    for r in rows:
        key = (r["player"], r["stat"])
        if r["chance"] >= GS_MIN_CHANCE and r["chance"] - r["rec"] >= GS_LEAN:
            if key not in best or r["line"] > best[key]["line"]:
                best[key] = r
        if r["rec"] >= 0.6 and r["rec"] - r["chance"] >= GS_LEAN:
            if key not in worst or r["line"] < worst[key]["line"]:
                worst[key] = r
    leans = sorted(best.values(), key=lambda r: (-(r["chance"] - r["rec"]), -r["chance"]))[:5]
    against = sorted(worst.values(), key=lambda r: r["chance"] - r["rec"])[:4]
    return {"teams": names, "poss": poss, "usual": usual,
            "xg": [st["teams"][t]["xg"] for t in (0, 1)], "xga": [st["teams"][t]["xga"] for t in (0, 1)],
            "script": script, "xi": squads["source"], "leans": leans, "against": against,
            "entry": entry, "lookup": {(r["player"], r["stat"], r["line"]): r for r in rows},
            "fitted": not gs_fit().get("missing")}


def gs_adjust(leg: dict, entry: dict, gs: dict | None) -> dict | None:
    """The backtested model's chance for one leg, blended with the leg's own.

    Returns chance (what the page now ranks on: the leg's own chance and the
    model's, averaged), model (the model with the game state), plain (the
    model without it), and the two factors, or None when the model cannot
    reach the leg (half-time lines, match totals, markets it was not fitted on).
    """
    if not gs or not gs.get("fitted") or (leg.get("period") or "ALL") != "ALL":
        return None
    try:
        import weekend
        base = weekend.chance(leg) if (leg.get("pStrength") or leg.get("pShrunk") or leg.get("pExchange")) else None
    except Exception:
        base = None
    if base is None:
        h, n = leg.get("hits"), leg.get("total")
        base = (h + 2) / (n + 4) if isinstance(h, int) and n else None
    if base is None:
        return None
    over = leg.get("over", True)
    if leg.get("alt") and isinstance(leg.get("threshold"), (int, float)):
        k = int(round(leg["threshold"]))
    elif isinstance(leg.get("line"), (int, float)):
        k = int(math.floor(leg["line"])) + 1
    else:
        return None
    t = _side_index(entry, leg.get("team"))
    if t is None:
        return None
    poss = gs.get("poss")
    if leg.get("player"):
        stat = PLAYER_FIT.get((leg.get("stat") or "").lower())
        if not stat:
            return None
        inp = _player_inputs(entry, t, leg["player"], stat)
        if not inp or inp["own"] <= 0:
            return None
        f = _ball(poss[t] if poss else None, gs["usual"][t], inp["sign"])
        m = _model("player", stat, inp["own"], inp["oppf"], f)
        oppf = inp["oppf"]
    else:
        stat = TEAM_FIT.get(leg.get("stat") or "")
        if not stat:
            return None
        own, allow, n1, n2 = _team_inputs(entry, t, stat)
        if not own or not allow or n1 < 5 or n2 < 5:
            return None
        f = _ball(poss[t] if poss else None, gs["usual"][t], TEAM_SIGN[stat])
        home = (entry.get("teams") or [{}, {}])[t].get("side") == "home"
        m = _model("team", stat, own, allow, f, home)
        oppf = allow / own
    if not m:
        return None
    p = _nb_at_least(k, m["mu"], m["alpha"])
    q = _nb_at_least(k, m["plain"], m["alpha"])
    if not over:
        p, q = 1 - p, 1 - q
    return {"chance": (base + p) / 2, "base": base, "model": p, "plain": q,
            "factor": f if m["use"] else 1.0, "oppf": oppf, "mu": m["mu"]}


# ============================================================ minutes context

def minutes_note(entry: dict, leg: dict) -> str | None:
    """What his minutes say about a player leg: how often he plays, and where the misses came."""
    name = leg.get("player")
    if not name:
        return None
    t = _side_index(entry, leg.get("team"))
    if t is None:
        return None
    try:
        apps = [a for a in (entry["players"][t] or []) if a.get("player") == name]
    except (KeyError, IndexError, TypeError):
        return None
    apps = sorted(apps, key=lambda a: a.get("date") or "")[-10:]
    if len(apps) < 4:
        return None
    stat = leg.get("stat") or ""
    keys = {"shots": ("Shots", "Total shots"), "shots on target": ("Shots on target",),
            "fouls": ("Fouls",), "fouled": ("Fouled", "Was fouled"), "tackles": ("Tackles", "Total tackles")}
    want = keys.get(stat.lower(), (stat,))
    need = leg.get("threshold") if leg.get("alt") else (leg.get("line") or 0) + 0.5
    if not isinstance(need, (int, float)):
        return None

    def val(a):
        s = a.get("stats") or {}
        for k in want:
            if s.get(k) is not None:
                return s[k]
        return 0
    mins = [int(a.get("minutes") or 0) for a in apps]
    full = [a for a in apps if (a.get("minutes") or 0) >= 60]
    hit_full = sum(1 for a in full if val(a) >= need)
    misses = [a for a in apps if val(a) < need]
    short_misses = [a for a in misses if (a.get("minutes") or 0) < 60]
    share = sum(min(m, 90) for m in mins) / (90 * len(mins))
    bits = [f"plays {share * 100:.0f}% of the minutes (last {len(apps)})"]
    if full:
        bits.append(f"{hit_full} of {len(full)} when he plays 60+")
    if misses and len(short_misses) == len(misses):
        bits.append("every miss came in a game he played under an hour")
    elif short_misses:
        bits.append(f"{len(short_misses)} of {len(misses)} misses came in under an hour")
    return ", ".join(bits)


# =================================================================== streaks

STREAK_MIN = 8


def streaks(name: str, recs: list[dict]) -> list[tuple[float, str]]:
    """Current runs of eight or more, newest game backwards."""
    tests = [
        ("under 3.5 goals", lambda r: r["goals_for"] + r["goals_against"] <= 3),
        ("over 1.5 goals", lambda r: r["goals_for"] + r["goals_against"] >= 2),
        ("over 2.5 goals", lambda r: r["goals_for"] + r["goals_against"] >= 3),
        ("under 2.5 goals", lambda r: r["goals_for"] + r["goals_against"] <= 2),
        ("both teams scoring", lambda r: r["goals_for"] > 0 and r["goals_against"] > 0),
        ("scoring", lambda r: r["goals_for"] > 0),
        ("conceding", lambda r: r["goals_against"] > 0),
        ("unbeaten", lambda r: r["goals_for"] >= r["goals_against"]),
    ]
    out = []
    for label, ok in tests:
        run = 0
        for r in reversed(recs):
            if not ok(r):
                break
            run += 1
        if run >= STREAK_MIN:
            out.append((0.8 + min(run, 25) / 250, f"{name}: {label} in {run} straight games."))
    return out


# ============================================================== league rank
#
# "Lille rank among the highest for shots conceded in Ligue 1": where the
# opponent's number sits against every side in its own league, from every
# team record in every report built (one report holds both sides of every
# fixture in a round, so a league is usually fully covered).

_LEAGUE: dict = {}


def set_entries(entries: list) -> None:
    """Hand over every fixture entry the page read, to rank teams within leagues."""
    _LEAGUE.clear()
    _POOL.clear()
    teams: dict = {}
    for entry, _meta in entries:
        for idx, t in enumerate(entry.get("teams") or []):
            tid = t.get("id")
            if tid is None or tid in teams:
                continue
            try:
                recs = entry["records"][idx] or []
            except (KeyError, IndexError, TypeError):
                continue
            teams[tid] = (t.get("name"), recs)
    _LEAGUE["teams"] = teams


def _home_league(recs: list[dict]):
    from collections import Counter
    c = Counter((r.get("tournament_id"), r.get("competition")) for r in recs[-15:]
                if r.get("competition") and "UEFA" not in r["competition"] and "Cup" not in r["competition"]
                and "Pokal" not in r["competition"] and "Coppa" not in r["competition"])
    return c.most_common(1)[0][0] if c else (None, None)


def league_rank(team_name: str, stat: str, period: str = "ALL") -> dict | None:
    """Rank of a side's average conceded `stat` in its league this season (1 = most)."""
    teams = _LEAGUE.get("teams") or {}
    me = next((tid for tid, (n, _) in teams.items() if n == team_name), None)
    if me is None:
        return None
    lid, lname = _home_league(teams[me][1])
    if lid is None:
        return None
    table = []
    for tid, (n, recs) in teams.items():
        season = _this_season([r for r in recs if _finished(r)], lid)
        vals = [(r.get("goals_against") if stat == "Goals" and period == "ALL"
                 else _stat(r.get("against"), period, stat)) for r in season]
        vals = [v for v in vals if v is not None]
        if len(vals) >= 3:
            table.append((sum(vals) / len(vals), tid))
    if len(table) < 10 or me not in [t for _, t in table]:
        return None
    table.sort(reverse=True)
    pos = [t for _, t in table].index(me) + 1
    return {"pos": pos, "of": len(table), "league": lname}


# ===================================================== how the game will go
#
# The last section of each fixture: what is most likely to happen and why, in
# lines a coach would say ("they play a double pivot against three attacking
# midfielders, so the pivot has more ground to cover"), each tied to the
# numbers behind it. Everything is read from what is on disk: the line-up and
# formation in the report, each side's last 10 games, every other side on
# the site for the rankings, and the backtested player model (fmodel.json).
#
# A style word is only used when the side sits in the top or bottom quarter of
# every team the site holds, so "high press" means it, not "a bit above
# average".

STYLE_N = 10
_FMODEL: dict = {}


def _fmodel():
    if not _FMODEL:
        try:
            _FMODEL.update(json.loads((ROOT / "reports" / "fmodel.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            _FMODEL["events"] = {}
    return _FMODEL.get("events") or {}


def fm_chance(event_id, player: str, stat: str, k: int):
    ev = _fmodel().get(str(event_id)) or {}
    pl = (ev.get("players") or {}).get(player)
    if not pl:
        return None
    v = ((pl.get("lines") or {}).get(stat) or {}).get(str(k))
    return v if isinstance(v, (int, float)) else None


def style_of(recs: list[dict]) -> dict | None:
    """A side's style over its last 10: the numbers behind the style words."""
    recs = recs[-STYLE_N:]
    if len(recs) < 5:
        return None

    def own(k):
        return _mean([_stat(r.get("stats"), "ALL", k) for r in recs])

    def opp(k):
        return _mean([_stat(r.get("against"), "ALL", k) for r in recs])
    passes, opp_passes = own("Passes"), opp("Passes")
    tackles = own("Total tackles") or own("Tackles")
    inter, fouls = own("Interceptions"), own("Fouls")
    long_b, crosses = own("Long balls"), own("Crosses")
    fte, fte_a = own("Final third entries"), opp("Final third entries")
    out = {
        "possession": own("Ball possession"),
        # passes the opponent makes per defensive action: low means a hard press
        "ppda": (opp_passes / (tackles + (inter or 0) + (fouls or 0)))
        if opp_passes and tackles else None,
        "direct": (long_b / passes) if long_b and passes else None,
        "long_balls": long_b,
        "crosses": crosses,
        "territory": (fte / (fte + fte_a)) if fte and fte_a else None,
        "box": own("Touches in penalty area"),
        "box_allowed": opp("Touches in penalty area"),
        "corners": own("Corner kicks"),
        "fouls": fouls,
        "dribbles": own("Dribbles"),
        "xg": own("Expected goals"), "xga": opp("Expected goals"),
        "shots": own("Total shots"), "shots_allowed": opp("Total shots"),
        "crosses_allowed": opp("Crosses"),
    }
    return out


_POOL: dict = {}


def _style_pool():
    """Every side on the site, styled, to rank against."""
    if not _POOL:
        for tid, (name, recs) in (_LEAGUE.get("teams") or {}).items():
            s = style_of([r for r in recs if _finished(r)])
            if s:
                _POOL[tid] = s
    return _POOL


def _pct(key, value):
    vals = sorted(v[key] for v in _style_pool().values() if isinstance(v.get(key), (int, float)))
    if not vals or not isinstance(value, (int, float)) or len(vals) < 20:
        return None
    return sum(1 for v in vals if v < value) / len(vals)


def style_words(s: dict) -> list[str]:
    words = []
    def hi(key):
        p = _pct(key, s.get(key))
        return p is not None and p >= 0.75
    def lo(key):
        p = _pct(key, s.get(key))
        return p is not None and p <= 0.25
    if lo("ppda"):
        words.append(f"press hard ({s['ppda']:.1f} opposition passes per defensive action)")
    elif hi("ppda"):
        words.append(f"sit off and let the opponent play ({s['ppda']:.1f} passes per defensive action)")
    if hi("possession"):
        words.append(f"keep the ball ({s['possession']:.0f}%)")
    elif lo("possession"):
        words.append(f"play without the ball ({s['possession']:.0f}%)")
    if hi("direct"):
        words.append(f"go long ({s['long_balls']:.0f} long balls a game)")
    elif lo("direct"):
        words.append(f"build short (only {s['long_balls']:.0f} long balls a game)")
    if hi("crosses"):
        words.append(f"attack wide and cross ({s['crosses']:.1f} crosses a game)")
    if hi("territory"):
        words.append(f"camp in the final third ({s['territory'] * 100:.0f}% of final-third entries)")
    if hi("box"):
        words.append(f"get bodies in the box ({s['box']:.0f} touches a game)")
    if hi("box_allowed"):
        words.append(f"let opponents into their box ({s['box_allowed']:.0f} touches allowed)")
    if hi("dribbles"):
        words.append(f"run with the ball ({s['dribbles']:.0f} dribbles a game)")
    if hi("fouls"):
        words.append(f"foul a lot ({s['fouls']:.0f} a game)")
    return words


def shape(entry: dict, side: str) -> dict | None:
    """Formation and who plays where, from the confirmed or predicted line-up."""
    store = entry.get("lineups") or {}
    lu = store.get("confirmed") if store.get("confirmed") else store.get("predicted")
    if not lu or not lu.get(side):
        return None
    blk = lu[side]
    form = blk.get("formation") or ""
    xi = [p for p in (blk.get("xi") or []) if p.get("pos") != "G"]
    sizes = [int(x) for x in form.split("-") if x.isdigit()]
    lines = []
    if sizes and sum(sizes) == len(xi):
        k = 0
        for s in sizes:
            lines.append([p["name"] for p in xi[k:k + s]])
            k += s
    out = {"formation": form, "lines": lines, "confirmed": bool(lu.get("confirmed")),
           "back": sizes[0] if sizes else None}
    # The holding midfield: the second line in a 4-2-3-1, 4-2-2-2, 3-4-2-1
    # (its central two), 4-1-4-1, 4-3-3 and 3-5-2 (its middle man or men).
    piv = []
    if len(lines) >= 3:
        mid = lines[1]
        if len(mid) == 2:
            piv = mid
        elif len(mid) == 1:
            piv = mid
        elif len(mid) == 4 and out["back"] == 3:
            piv = mid[1:3]
        elif len(mid) == 3:
            piv = [mid[1]]
        elif len(mid) == 5:
            piv = mid[1:4]
    out["pivot"] = piv
    out["attack_mids"] = lines[2] if len(lines) >= 4 else []
    out["front"] = lines[-1] if lines else []
    out["central"] = (len(piv) + (len(lines[2]) if len(lines) >= 4 and len(lines[2]) in (1, 2, 3) else 0)
                      if lines else None)
    return out


def _fmt_p(p):
    return f"{p * 100:.0f}%" if isinstance(p, (int, float)) else "?"


def story(entry: dict, meta: dict, gs: dict | None, b: dict | None) -> dict:
    """What should happen in the game, and the lines of reasoning behind it."""
    teams = entry.get("teams") or []
    kick = (entry.get("fixture") or {}).get("kickoff")
    sides = []
    for t, tm in enumerate(teams[:2]):
        recs = records(entry, t, kick)
        s = style_of(recs)
        sides.append({"name": tm.get("name"), "side": tm.get("side"), "style": s,
                      "words": style_words(s) if s else [], "shape": shape(entry, tm.get("side"))})
    lines: list[tuple[float, str, str]] = []   # (weight, reasoning, "so" line)
    ev = meta.get("id")
    if len(sides) == 2 and all(x["style"] for x in sides):
        for t in (0, 1):
            me, op = sides[t], sides[1 - t]
            ms, os_ = me["style"], op["style"]
            mshape, oshape = me["shape"] or {}, op["shape"] or {}
            # 1. Pivot against attacking midfielders: who covers ground
            piv = mshape.get("pivot") or []
            ams = oshape.get("attack_mids") or []
            if len(piv) == 2 and len(ams) >= 3:
                pc = [(n, fm_chance(ev, n, "Tackles", 2), fm_chance(ev, n, "Fouls", 1)) for n in piv]
                nums = "; ".join(f"{n}: 2+ tackles {_fmt_p(a)}, 1+ foul {_fmt_p(f)}" for n, a, f in pc)
                lines.append((0.9, f"{me['name']} play a double pivot ({' and '.join(piv)}) against "
                                   f"{op['name']}'s {len(ams)} attacking midfielders ({', '.join(ams)}).",
                              f"so the pivot is outnumbered between the lines and has more ground to cover: "
                              f"expect tackles and fouls from them ({nums})."))
            elif len(piv) == 1 and len(ams) >= 2:
                n = piv[0]
                lines.append((0.85, f"{me['name']} have a single holding midfielder ({n}) facing "
                                    f"{len(ams)} {op['name']} players between the lines.",
                              f"so {n} is the one exposed: 2+ tackles {_fmt_p(fm_chance(ev, n, 'Tackles', 2))}, "
                              f"1+ foul {_fmt_p(fm_chance(ev, n, 'Fouls', 1))}."))
            # 2. Press against a short build-up
            pp, od = _pct("ppda", ms.get("ppda")), _pct("direct", os_.get("direct"))
            if pp is not None and pp <= 0.25 and od is not None and od <= 0.4:
                defs = (oshape.get("lines") or [[]])[0]
                lines.append((0.85, f"{me['name']} press hard ({ms['ppda']:.1f} passes allowed per defensive action) "
                                    f"and {op['name']} like to build short ({os_['long_balls']:.0f} long balls a game).",
                              f"so {op['name']}'s back line ({', '.join(defs[:4]) or 'their defenders'}) will be "
                              f"under pressure on the ball: more turnovers high up and more shots for {me['name']} "
                              f"({ms['shots']:.1f} a game usually)."))
            # 3. Crossing team against a side that lets crosses in
            cr, ca = _pct("crosses", ms.get("crosses")), _pct("crosses_allowed", os_.get("crosses_allowed"))
            if cr is not None and cr >= 0.7 and ca is not None and ca >= 0.6:
                lines.append((0.75, f"{me['name']} attack wide ({ms['crosses']:.1f} crosses a game) and "
                                    f"{op['name']} let opponents cross ({os_['crosses_allowed']:.1f} a game).",
                              f"so expect {me['name']} corners ({ms['corners']:.1f} a game usually) and "
                              f"headers for their front line ({', '.join((mshape.get('front') or [])[:2]) or 'the striker'})."))
            # 4. Box presence against a leaky box
            bx, ba = _pct("box", ms.get("box")), _pct("box_allowed", os_.get("box_allowed"))
            if bx is not None and bx >= 0.65 and ba is not None and ba >= 0.65:
                front = (mshape.get("front") or [])[:2]
                nums = "; ".join(f"{n}: 2+ shots {_fmt_p(fm_chance(ev, n, 'Shots', 2))}" for n in front)
                lines.append((0.8, f"{me['name']} get into the box ({ms['box']:.0f} touches a game) and "
                                   f"{op['name']} let teams in ({os_['box_allowed']:.0f} allowed).",
                              f"so the shots should come from close range for {me['name']}'s forwards ({nums})."))
            # 5. Dribblers against a side that fouls
            dr, fo = _pct("dribbles", ms.get("dribbles")), _pct("fouls", os_.get("fouls"))
            if dr is not None and dr >= 0.7 and fo is not None and fo >= 0.6:
                lines.append((0.7, f"{me['name']} run with the ball ({ms['dribbles']:.0f} dribbles a game) and "
                                   f"{op['name']} foul ({os_['fouls']:.0f} a game).",
                              f"so expect {me['name']}'s ball-carriers to be fouled and {op['name']} to pick up cards."))
            # 6. Sitting deep against a side that keeps the ball
            po = _pct("possession", ms.get("possession"))
            if po is not None and po >= 0.75 and _pct("ppda", os_.get("ppda")) is not None \
                    and _pct("ppda", os_.get("ppda")) >= 0.7:
                lines.append((0.7, f"{me['name']} keep the ball ({ms['possession']:.0f}%) and {op['name']} sit off "
                                   f"({os_['ppda']:.1f} passes per defensive action).",
                              f"so {me['name']} will have long spells of possession in front of a set block: "
                              f"more corners and blocked shots than clear chances, and tackles and clearances "
                              f"for {op['name']}'s back line."))
    # 7. The script from strength and possession
    sc = (b or {}).get("score")
    if sc and len(sides) == 2:
        fav = 0 if sc["ph"] >= sc["pa"] else 1
        pf = sc["ph"] if fav == 0 else sc["pa"]
        if pf >= 0.5:
            dog = sides[1 - fav]["name"]
            lines.append((0.8, f"{sides[fav]['name']} are favourites ({pf * 100:.0f}% to win).",
                          f"so the likeliest script is {sides[fav]['name']} ahead and {dog} chasing: "
                          f"{dog} open up late, which adds shots at both ends and fouls from {dog}."))
    if gs and gs.get("poss"):
        d = 0 if gs["poss"][0] >= gs["poss"][1] else 1
        if abs(gs["poss"][0] - 50) >= 6:
            lines.append((0.75, f"{gs['teams'][d]} should have {gs['poss'][d]:.0f}% of the ball.",
                          f"so {gs['teams'][1 - d]}'s defenders and midfielders do the tackling and clearing, "
                          f"and {gs['teams'][d]}'s wide players win the corners."))
    # 8. Missing creators
    for side in ((b or {}).get("home"), (b or {}).get("away")):
        if not side:
            continue
        key = [a for a in side.get("absences") or [] if a["of"] and a["starts"] >= a["of"] * 0.6]
        other = (b or {}).get("away") if side is (b or {}).get("home") else (b or {}).get("home")
        for group, verdict in (
                ([a for a in key if a.get("pos") in ("F", "M")],
                 lambda n: f"so {n}'s attack is weaker than its last 10 say: shade their shots and goals down."),
                ([a for a in key if a.get("pos") in ("D", "G")],
                 lambda n: f"so {n}'s defence is weaker than its last 10 say: shade "
                           f"{(other or {}).get('name') or 'the opponent'}'s shots and goals up.")):
            if not group:
                continue
            names = ", ".join(f"{a['name']} ({a['starts']} starts in {a['of']})" for a in group[:3])
            many = len(group) > 1
            lines.append((0.7, f"{side['name']} are without {names}, "
                               f"{'regular starters' if many else 'a regular starter'}.",
                          verdict(side["name"])))
    lines.sort(key=lambda x: -x[0])
    return {"sides": sides, "lines": [(r, s) for _, r, s in lines[:8]]}


# ================================================= the team model (tactics)
#
# teammodel/ holds, per team stat, whichever of two models won on validation
# in teammodel_train.py: LightGBM on every teamstyle.py feature (style,
# pressing, directness, box, shape, the clashes, Elo) or the linear model.
# Scored here with fmodel_trees.Tree, so the Mac needs no LightGBM; a test
# held it to LightGBM's own predictions to 1e-14. teamstyle.State replays
# the cache once per run to put every side's features at "now".

_TM: dict = {}
TEAM_LEG_STAT = {"Total shots": "Total shots", "Shots on target": "Shots on target",
                 "Corner kicks": "Corner kicks", "Fouls": "Fouls", "Tackles": "Total tackles",
                 "Total tackles": "Total tackles", "Yellow cards": "Yellow cards", "Clearances": "Clearances",
                 "Big chances": "Big chances", "Offsides": "Offsides", "Goalkeeper saves": "Goalkeeper saves"}


def _team_model():
    if _TM:
        return _TM
    try:
        import gzip
        import teamstyle
        from fmodel.fmodel_trees import Tree
        meta = json.loads((ROOT / "teammodel" / "meta.json").read_text())
        models = {}
        for s, e in meta["stats"].items():
            m = {"use": e["use"], "linear": e["linear"], "alpha_linear": e.get("alpha_linear", 0.05)}
            if e["use"] == "gbm":
                with gzip.open(ROOT / "teammodel" / f"{s.lower().replace(' ', '_')}.json.gz", "rt") as fh:
                    d = json.load(fh)
                m.update(trees=[Tree(t["tree_structure"]) for t in d["tree_info"]],
                         features=e["features"], alpha=e.get("alpha_gbm", 0.05))
            models[s] = m
        _TM.update(models=models, state=teamstyle.State.from_cache(CACHE, keep_rows=False))
    except Exception as exc:
        _TM["error"] = str(exc)
    return _TM


def team_model_mu(stat: str, team_id, opp_id, home: bool, f_own: str, f_opp: str):
    """Expected count and spread for one side's stat tonight, or None."""
    tm = _team_model()
    m = (tm.get("models") or {}).get(stat)
    if not m or "state" not in tm:
        return None
    x = tm["state"].features_for(team_id, opp_id, home, f_own or "", f_opp or "")
    own, conc = x.get("own_" + stat), x.get("opp_conc_" + stat)
    if own is None or conc is None or math.isnan(own) or math.isnan(conc):
        return None
    if m["use"] == "gbm":
        import numpy as np
        row = np.array([[float(x.get(f, float("nan"))) for f in m["features"]]])
        mu = float(math.exp(sum(t.predict(row)[0] for t in m["trees"])))
        return {"mu": mu, "alpha": m["alpha"], "kind": "tactics model", "x": x}
    c = m["linear"]
    ball = x.get("x_ball")
    ball = 1.0 if ball is None or math.isnan(ball) else min(2.0, max(0.5, ball))
    eta = c[0] + c[1] * math.log(max(own, .05)) + c[2] * math.log(max(conc, .05)) + c[3] * float(home) + c[4] * math.log(ball)
    return {"mu": math.exp(eta), "alpha": m["alpha_linear"], "kind": "linear model", "x": x}


_gs_adjust_simple = gs_adjust


def gs_adjust(leg: dict, entry: dict, gs: dict | None) -> dict | None:  # noqa: F811
    """Backtested chance for a leg: team model for team legs, fmodel for player legs.

    Falls back to the simpler fit above where neither reaches the leg.
    """
    if (leg.get("period") or "ALL") != "ALL":
        return None
    over = leg.get("over", True)
    if leg.get("alt") and isinstance(leg.get("threshold"), (int, float)):
        k = int(round(leg["threshold"]))
    elif isinstance(leg.get("line"), (int, float)):
        k = int(math.floor(leg["line"])) + 1
    else:
        return None
    try:
        import weekend
        base = weekend.chance(leg) if (leg.get("pStrength") or leg.get("pShrunk") or leg.get("pExchange")) else None
    except Exception:
        base = None
    if base is None:
        h, n = leg.get("hits"), leg.get("total")
        base = (h + 2) / (n + 4) if isinstance(h, int) and n else None
    t = _side_index(entry, leg.get("team"))
    if base is None or t is None:
        return _gs_adjust_simple(leg, entry, gs)
    teams = entry.get("teams") or [{}, {}]
    if leg.get("player"):
        stat = PLAYER_FIT.get((leg.get("stat") or "").lower())
        ev = (entry.get("fixture") or {}).get("id")
        p = fm_chance(ev, leg["player"], stat, k) if stat else None
        if p is None or not over:
            return _gs_adjust_simple(leg, entry, gs)
        simple = _gs_adjust_simple(leg, entry, gs) or {}
        # the leg's own chance already carries fmodel where the site blends it
        chance = base if leg.get("chance_model") is not None else (base + p) / 2
        return {"chance": chance, "base": base, "model": p, "plain": simple.get("plain", p),
                "factor": simple.get("factor", 1.0), "oppf": simple.get("oppf", 1.0), "kind": "player model"}
    stat = TEAM_LEG_STAT.get(leg.get("stat") or "")
    if not stat:
        return None
    side = teams[t].get("side")
    sh_me, sh_op = shape(entry, side) or {}, shape(entry, "away" if side == "home" else "home") or {}
    r = team_model_mu(stat, teams[t].get("id"), teams[1 - t].get("id"), side == "home",
                      sh_me.get("formation"), sh_op.get("formation"))
    if not r:
        return _gs_adjust_simple(leg, entry, gs)
    p = _nb_at_least(k, r["mu"], r["alpha"])
    if not over:
        p = 1 - p
    x = r["x"]
    oppf = (x.get("opp_conc_" + stat) or 0) / max(1e-6, x.get("own_" + stat) or 1e-6)
    ball = x.get("x_ball")
    return {"chance": (base + p) / 2, "base": base, "model": p, "plain": p, "mu": r["mu"],
            "factor": 1.0 if ball is None or math.isnan(ball) else ball, "oppf": oppf, "kind": r["kind"]}


# ===================================================================== NBA
#
# usmodel_live.py writes, per NBA game, each side's game state (usgame.py:
# pace, ratings, expected points, margin, blowout rate, rest) and its team
# numbers priced by the model nba_team_train.py chose (reports/usmodel.json).
# Team legs are re-priced from those; the story reads the state. NBA player
# legs already carry usmodel through the site's own blend.

_US: dict = {}
NBA_ALTITUDE = {"Denver Nuggets", "Utah Jazz"}


def _usmodel():
    if not _US:
        try:
            _US.update(json.loads((ROOT / "reports" / "usmodel.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            _US["events"] = {}
    return _US.get("events") or {}


def nba_event(entry: dict) -> dict | None:
    ev = _usmodel().get(str((entry.get("fixture") or {}).get("id")))
    return ev if ev and ev.get("teams") else None


def nba_adjust(leg: dict, entry: dict) -> dict | None:
    if leg.get("player") or (leg.get("period") or "ALL") != "ALL":
        return None
    ev = nba_event(entry)
    tm = ((ev or {}).get("teams") or {}).get(leg.get("team")) or {}
    st = tm.get(leg.get("stat"))
    if not st:
        return None
    if leg.get("alt") and isinstance(leg.get("threshold"), (int, float)):
        k = int(round(leg["threshold"]))
    elif isinstance(leg.get("line"), (int, float)):
        k = int(math.floor(leg["line"])) + 1
    else:
        return None
    p = (st.get("lines") or {}).get(str(k))
    if p is None:
        return None
    if not leg.get("over", True):
        p = 1 - p
    try:
        import weekend
        base = weekend.chance(leg) if (leg.get("pStrength") or leg.get("pShrunk") or leg.get("pExchange")) else None
    except Exception:
        base = None
    if base is None:
        h, n = leg.get("hits"), leg.get("total")
        base = (h + 2) / (n + 4) if isinstance(h, int) and n else p
    return {"chance": (base + p) / 2, "base": base, "model": p, "plain": p, "mu": st.get("mu"),
            "factor": 1.0, "oppf": 1.0, "kind": "NBA team model"}


_gs_adjust_football = gs_adjust


def gs_adjust(leg: dict, entry: dict, gs: dict | None) -> dict | None:  # noqa: F811
    if ((entry.get("fixture") or {}).get("sport") or "football") == "basketball":
        return nba_adjust(leg, entry)
    return _gs_adjust_football(leg, entry, gs)


def _nba_recent(entry: dict, t: int, name: str, n: int = 10):
    try:
        apps = [a for a in (entry["players"][t] or []) if a.get("player") == name]
    except (KeyError, IndexError, TypeError):
        return None
    apps = sorted(apps, key=lambda a: a.get("date") or "")[-n:]
    if not apps:
        return None
    pts = [((a.get("stats") or {}).get("Points") or 0) for a in apps]
    mins = [((a.get("stats") or {}).get("Seconds played") or 0) / 60 for a in apps]
    return {"pts": sum(pts) / len(pts), "mins": sum(mins) / len(mins), "n": len(apps)}


def nba_story(entry: dict, meta: dict) -> dict:
    """How an NBA game should go: pace, score, blowout risk, legs, who is out and who gains."""
    ev = nba_event(entry)
    teams = entry.get("teams") or []
    if not ev or len(teams) < 2:
        return {"lines": [], "score": None}
    names = [t.get("name") for t in teams]
    st = [ev["state"].get(n) or {} for n in names]
    tm = [ev["teams"].get(n) or {} for n in names]
    lines: list[tuple[float, str, str]] = []
    pts = [((tm[i].get("Points") or {}).get("mu")) for i in (0, 1)]
    score = None
    if all(isinstance(p, (int, float)) for p in pts):
        score = {"home": pts[0], "away": pts[1], "total": pts[0] + pts[1]}
    g = lambda i, k: st[i].get(k)  # noqa: E731
    # pace
    pm, po = g(0, "g_pace_me"), g(1, "g_pace_me")
    if isinstance(pm, (int, float)) and isinstance(po, (int, float)) and abs(pm - po) >= 2.5:
        fast, slow = (0, 1) if pm > po else (1, 0)
        ep = g(0, "g_exp_pace")
        lines.append((0.9, f"{names[fast]} play fast ({max(pm, po):.1f} possessions a game) and {names[slow]} slow "
                           f"({min(pm, po):.1f}); tonight should run at about {ep:.1f}.",
                      f"so {names[fast]}'s counting numbers come down a touch from their usual and "
                      f"{names[slow]}'s go up; totals sit between the two."))
    # expected score and margin
    if score:
        fav = 0 if pts[0] >= pts[1] else 1
        margin = abs(pts[0] - pts[1])
        lines.append((0.85, f"The team model has it {names[0]} {pts[0]:.0f}, {names[1]} {pts[1]:.0f} "
                            f"(total {score['total']:.0f}), from each side's last 10 and what the other concedes.",
                      f"so {names[fav]} by about {margin:.0f}."))
        br = g(fav, "g_blowout_rate_me")
        if margin >= 8:
            lines.append((0.85, f"{names[fav]} should win by {margin:.0f} or more"
                                + (f", and {br * 100:.0f}% of their last 10 ended 15+ apart" if isinstance(br, (int, float)) else "") + ".",
                          f"so blowout risk is real: {names[fav]}'s starters can sit the fourth quarter. Shade their "
                          f"overs down and their bench's up; {names[1 - fav]}'s starters may chase it with heavy minutes."))
    # schedule and altitude
    for i in (0, 1):
        if (g(i, "g_games_4d") or 0) >= 2:
            lines.append((0.8, f"{names[i]} are on their third game in four nights.",
                          f"so tired legs: shade {names[i]}'s overs down (minutes get managed) and their opponents' up."))
    rd = g(0, "g_rest_diff")
    if isinstance(rd, (int, float)) and abs(rd) >= 2 and abs(rd) < 30:
        fresh = 0 if rd > 0 else 1
        lines.append((0.6, f"{names[fresh]} have had {abs(rd):.0f} more days' rest.",
                      f"so {names[fresh]} start the fresher side."))
    if teams[0].get("name") in NBA_ALTITUDE:
        lines.append((0.6, f"{names[0]} play at altitude.",
                      f"so visitors fade late: {names[1]}'s fourth-quarter numbers tend to drop."))
    # who is out, and who gains
    us_players = ev.get("players") or {}
    for i, side in enumerate(("home", "away")):
        out = [r for r in ((entry.get("injuries") or {}).get(side) or [])
               if isinstance(r, (list, tuple)) and len(r) > 2 and str(r[2]).lower().startswith("out")]
        key = []
        for r in out:
            rec = _nba_recent(entry, i, r[0])
            if rec and rec["mins"] >= 20:
                key.append((r[0], rec))
        if not key:
            continue
        gains = []
        for pname, pl in us_players.items():
            mu = (pl.get("mu") or {}).get("Points")
            rec = _nba_recent(entry, i, pname)
            if mu is None or not rec or rec["n"] < 3:
                continue
            gains.append((mu - rec["pts"], pname, mu, rec["pts"]))
        gains.sort(reverse=True)
        who = "; ".join(f"{n} {mu:.1f} expected against {usual:.1f} usual" for d, n, mu, usual in gains[:2] if d > 0.5)
        names_out = ", ".join(f"{n} ({r['pts']:.1f} pts, {r['mins']:.0f} min)" for n, r in key[:3])
        lines.append((0.95, f"{names[i]} are without {names_out}.",
                      (f"so their shots and minutes go elsewhere: {who}." if who
                       else f"so their shots and minutes go elsewhere: look at {names[i]}'s other starters' overs.")))
    lines.sort(key=lambda x: -x[0])
    return {"lines": [(r, s) for _, r, s in lines[:7]], "score": score, "state": st, "names": names}
