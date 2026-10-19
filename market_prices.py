"""
Betfair Exchange prices for every fixture in the built reports.

    python market_prices.py              # fetch, next 7 days, all sports with reports
    python market_prices.py --show       # what was matched, and what was not

Step one of setting the site's numbers against the market. This fetches every
market Betfair carries on each fixture the reports cover (football, NFL, MLB,
darts), takes the margin off, and saves it all to market_prices.json, keyed by
our own event id. Which of those markets line up with the site's own lines
(match goals, both teams to score, corners, bookings, spreads, totals) is the
next step, worked out from what the exchange actually lists rather than from
guesses about its naming.

Matching Betfair's fixtures to ours is by team names and kick-off time.
Betfair writes "Man Utd" and "Nottm Forest"; SofaScore writes the full names.
Anything that did not match is listed by --show so the alias table can grow.
"""

from __future__ import annotations

import json
import math
import re
import time
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "market_prices.json"

EVENT_TYPES = {"football": 1, "american-football": 6423, "baseball": 7511,
               "basketball": 7522, "darts": 3503}

_DROP = {"fc", "afc", "cf", "sc", "ac", "the", "club", "de", "fk", "sk", "cd", "ud", "sv",
         "rc", "ssc", "as", "us", "if", "bk", "fsv", "tsg", "vfl", "vfb", "1", "04", "05"}
ALIASES = {
    "man utd": "manchester united", "man united": "manchester united", "man city": "manchester city",
    "nottm forest": "nottingham forest", "spurs": "tottenham hotspur", "wolves": "wolverhampton wanderers",
    "sheff utd": "sheffield united", "sheff wed": "sheffield wednesday", "qpr": "queens park rangers",
    "west brom": "west bromwich albion", "psg": "paris saint germain", "inter": "inter milan",
    "atletico madrid": "atletico madrid", "athletic bilbao": "athletic club", "betis": "real betis",
    "leverkusen": "bayer leverkusen", "gladbach": "borussia monchengladbach", "dortmund": "borussia dortmund",
    "bayern munich": "bayern munchen", "wycombe": "wycombe wanderers", "oxford utd": "oxford united",
    "cambridge utd": "cambridge united", "peterborough": "peterborough united",
}
# Words that cannot identify a club on their own: "Paris" is in both Paris FC
# and Paris Saint-Germain, "Real" in half of Spain.
_GENERIC = {"paris", "real", "inter", "united", "city", "athletic", "sporting", "dynamo", "olympique",
            "racing", "union", "red", "star", "new", "york", "los", "angeles", "san", "st", "saint",
            "west", "north", "south", "east", "atletico", "deportivo", "club", "town", "county", "rovers"}
_EXTRA = str.maketrans({"ł": "l", "ø": "o", "đ": "d", "ß": "ss", "æ": "ae", "ı": "i"})


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", (name or "").lower().translate(_EXTRA)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = " ".join(s.split())
    return ALIASES.get(s, s)


# Word-level spellings: SofaScore v Betfair.
_TOKEN = {"utd": "united", "lyonnais": "lyon", "rennais": "rennes", "brestois": "brest",
          "mgladbach": "monchengladbach", "gladbach": "monchengladbach", "mineiro": "mg",
          "louis": "louis", "coruna": "deportivo", "racing": "racing", "strasbourg": "strasbourg"}


def tokens(name: str) -> set:
    words = norm(name.replace("M'gladbach", "Monchengladbach").replace("St.", "St ")).split()
    words = [_TOKEN.get(w, w) for w in words]
    return {t for t in words if t not in _DROP and len(t) > 1} or set(words)


def sim(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    # a shared prefix counts too: "Bournemouth" v "AFC Bournemouth", "Wolverhampton" v "Wolves"
    for x in ta - tb:
        if any(y.startswith(x[:5]) or x.startswith(y[:5]) for y in tb - ta if len(x) >= 4 and len(y) >= 4):
            inter += 0.8
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    # A short name wholly inside the long one is the same club: "Brighton" in
    # "Brighton Hove Albion". Two names sharing one word are not: "Manchester
    # United" and "Manchester City" score 0.5, under the bar.
    if short <= long_ and (len(short) >= 2 or not short <= _GENERIC):
        return 1.0
    return inter / max(len(ta), len(tb))


def our_fixtures(days: int = 7) -> dict:
    import make_index
    import weekend
    now = time.time()
    out = {}
    for path in sorted((HERE / "reports").glob("*.html")):
        if path.name.startswith("pick-"):
            continue
        for entry, meta in make_index.read_entries(path):
            k = meta.get("kickoff") or 0
            if not (now - 3 * 3600 < k < now + days * 86400):
                continue
            sport = weekend.sport_of(entry)
            out[meta["id"]] = {"id": meta["id"], "home": meta["home"], "away": meta["away"],
                               "kickoff": k, "sport": sport, "competition": meta.get("competition")}
    return out


def _split_event(name: str):
    for sep in (" v ", " vs ", " @ ", " - "):
        if sep in name:
            a, b = name.split(sep, 1)
            # Betfair writes US games "Away @ Home"
            return (b, a) if sep == " @ " else (a, b)
    return None


def match(fixtures: dict, bf_events: list, sport: str):
    pairs, used = {}, set()
    for f in [x for x in fixtures.values() if x["sport"] == sport]:
        best = None
        for e in bf_events:
            if e["id"] in used:
                continue
            sides = _split_event(e.get("name", ""))
            if not sides:
                continue
            try:
                start = time.mktime(time.strptime(e.get("openDate", "")[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
            except ValueError:
                start = None
            if start and abs(start - f["kickoff"]) > 4 * 3600:
                continue
            s = min(sim(f["home"], sides[0]), sim(f["away"], sides[1]))
            s_swap = min(sim(f["home"], sides[1]), sim(f["away"], sides[0]))
            score, swapped = (s, False) if s >= s_swap else (s_swap, True)
            if score >= 0.6 and (best is None or score > best[0]):
                best = (score, e, swapped)
        if best:
            used.add(best[1]["id"])
            pairs[f["id"]] = (best[1], best[2], round(best[0], 2))
    return pairs


def _devig(runners, mtype: str | None = None):
    """Margin off, line by line. A multi-line market (NFL totals and spreads,
    Asian handicaps) is one market with a pair of runners per line, and taking
    the margin off across all of them at once priced every line at nothing.

    Where a line's mid prices are incomplete (one side has no lay, or the
    spread is wide) but every runner has a back price, the backs are
    normalised instead and the runner marked `est`: a usable estimate, never
    treated as a tight market. Not for lists where many runners can win
    (anytime scorer and the like): those cannot be normalised at all."""
    # Totals pair Over and Under on the same number; handicaps pair one side
    # at -h with the other at +h. Grouping on |h| alone put both of a
    # handicap's +-0.5 lines in one group of four and halved every chance.
    groups = {}
    first = next((r["name"] for r in runners), None)
    for r in runners:
        h = r.get("handicap") or 0.0
        if r["name"].lower().startswith(("over", "under")) or h == 0:
            k = h
        else:
            k = h if r["name"] == first else -h
        groups.setdefault(k, []).append(r)
    over = None
    multi = mtype in _MULTI_WINNER
    for rows in groups.values():
        priced = [r for r in rows if r.get("price")]
        tot = sum(1 / r["price"] for r in priced)
        complete = len(priced) == len(rows) and tot > 0
        for r in rows:
            r["p"] = round((1 / r["price"]) / tot, 4) if complete and r.get("price") else None
            r.pop("est", None)
        if not complete and not multi and 2 <= len(rows) <= 4 and all(r.get("back") for r in rows):
            tb = sum(1 / r["back"] for r in rows)
            # Back prices alone over-round by the spread; past 25% they say
            # nothing worth using.
            if 1.0 <= tb < 1.25:
                for r in rows:
                    r["p"] = round((1 / r["back"]) / tb, 4)
                    r["est"] = True
        if complete and (over is None or abs(tot - 1) < abs(over - 1)):
            over = round(tot, 4)
    return over


_MULTI_WINNER = {"TO_SCORE", "TO_SCORE_2_OR_MORE", "TO_SCORE_HATTRICK", "SHOWN_A_CARD",
                 "SHOTS_ON_TARGET_P1", "SHOTS_ON_TARGET_P2", "TO_SCORE_A_TOUCHDOWN",
                 "FIRST_GOAL_SCORER", "1ST_TOUCHDOWN_SCORER", "CORRECT_SCORE", "CORRECT_SCORE2",
                 "HALF_TIME_SCORE"}


def fetch(days: int = 7) -> dict:
    import betfair_api as bf
    bf.login()
    fixtures = our_fixtures(days)
    sports = sorted({f["sport"] for f in fixtures.values()})
    out = {"fetched": time.time(), "events": {}, "unmatched": []}
    for sport in sports:
        et = EVENT_TYPES.get(sport)
        if not et:
            continue
        events = bf.events(et, hours=days * 24)
        pairs = match(fixtures, events, sport)
        print(f"{sport}: {len(events)} on the exchange, {len(pairs)} of "
              f"{sum(1 for f in fixtures.values() if f['sport'] == sport)} of ours matched")
        for fid, f in fixtures.items():
            if f["sport"] == sport and fid not in pairs:
                out["unmatched"].append(f"{sport}: {f['home']} v {f['away']}")
        for fid, (e, swapped, score) in pairs.items():
            cat = bf.markets(e["id"])
            books = {b["marketId"]: b for b in bf.prices([m["marketId"] for m in cat])}
            markets = []
            for m in cat:
                book = books.get(m["marketId"]) or {}
                by_sel = {(r["selectionId"], r.get("handicap", 0.0)): r for r in book.get("runners", [])}
                runners = []
                for r in m.get("runners", []):
                    rb = by_sel.get((r["selectionId"], r.get("handicap", 0.0))) or \
                         next((x for x in book.get("runners", []) if x["selectionId"] == r["selectionId"]), {})
                    ex = rb.get("ex") or {}
                    back = (ex.get("availableToBack") or [{}])[0].get("price")
                    lay = (ex.get("availableToLay") or [{}])[0].get("price")
                    price = (back + lay) / 2 if back and lay and lay / back < 1.3 else None
                    runners.append({"name": r["runnerName"], "handicap": r.get("handicap", 0.0),
                                    "back": back, "lay": lay, "price": price})
                over = _devig(runners, (m.get("description") or {}).get("marketType"))
                markets.append({"type": (m.get("description") or {}).get("marketType"),
                                "name": m.get("marketName"), "runners": runners, "overround": over,
                                "matched": book.get("totalMatched")})
            # bfEvent: Betfair's own event id. Paddy Power shares the platform,
            # and paddypower_prices.py tries it as Paddy Power's event id,
            # checking the team names on what comes back before trusting it.
            out["events"][str(fid)] = {"betfair": e.get("name"), "bfEvent": e.get("id"),
                                       "start": e.get("openDate"),
                                       "swapped": swapped, "score": score, "sport": sport, "markets": markets}
    OUT.write_text(json.dumps(out, indent=0))
    return out


# ------------------------------------------------------------- linking
#
# Three kinds of quote, because the exchange prices things three ways, and
# each deserves a different amount of trust (weekend._exchange weighs them):
#
#   "exchange"  a two-way or band market with both a back and a lay close
#               together: the margin comes off cleanly and the chance is as
#               good as the market's.
#   "back"      a list where only back offers stand (anytime scorer, shown a
#               card, shots on target 1+ / 2+). Many players can win, so the
#               list cannot be normalised; the back price still carries the
#               layer's margin, which is taken off as an estimate
#               (BACK_MARGIN, refitted by exchange_eval.py once results
#               exist). The back price itself is real: it is what you get.
#   "derived"   a bet the exchange does not list but implies. Team goals and
#               goal lines it does not carry come from a Poisson goal model
#               fitted to Betfair's own match odds and goal lines, which is
#               how a trader would price them.

# Margin left in back-only lists, as a share of the implied chance. Starting
# points from typical sportsbook margins on these markets; exchange_eval.py
# --fit replaces them with what the results say.
BACK_MARGIN = {"TO_SCORE": 0.10, "TO_SCORE_2_OR_MORE": 0.15, "SHOWN_A_CARD": 0.12,
               "SHOTS_ON_TARGET_P1": 0.06, "SHOTS_ON_TARGET_P2": 0.10,
               "TO_SCORE_A_TOUCHDOWN": 0.10}
_FITTED_MARGIN: dict = {}


def back_margin(mtype: str) -> float:
    if "loaded" not in _FITTED_MARGIN:
        _FITTED_MARGIN["loaded"] = True
        try:
            w = json.loads((HERE / "exchange_weights.json").read_text())
            _FITTED_MARGIN.update(w.get("backMargin") or {})
        except (OSError, ValueError):
            pass
    return float(_FITTED_MARGIN.get(mtype, BACK_MARGIN.get(mtype, 0.10)))


def _player_key(name: str) -> str:
    w = [t for t in norm(name).split() if len(t) > 1]
    return (w[0][0] + " " + w[-1]) if len(w) >= 2 else (w[-1] if w else "")


def _surname(name: str) -> str:
    w = [t for t in norm(name).split() if len(t) > 1]
    return w[-1] if w else ""


def _find_player(m, player: str):
    """The runner for one of our players: initial and surname first ("L
    Martinez"), then a surname that only one runner in the list carries,
    which is how "Anastasios Douvikas" finds Betfair's "Tasos Douvikas"."""
    key = _player_key(player)
    r = next((x for x in m["runners"] if _player_key(x["name"]) == key), None)
    if r:
        return r
    sur = _surname(player)
    hits = [x for x in m["runners"] if _surname(x["name"]) == sur]
    return hits[0] if sur and len(hits) == 1 else None


def _ou(m, over: bool, line=None):
    want = "over" if over else "under"
    for r in m["runners"]:
        if r["name"].lower().startswith(want) and (line is None or abs((r.get("handicap") or 0) - line) < 1e-6):
            return r
    return None


def _yes(m, yes: bool):
    for r in m["runners"]:
        if r["name"].lower() == ("yes" if yes else "no"):
            return r
    return None


def _quote(r, m, kind="exchange"):
    if not r or r.get("p") is None:
        return None
    back, lay = r.get("back"), r.get("lay")
    tight = bool(back and lay and lay / back < 1.10) and not r.get("est")
    return {"p": r["p"], "back": back, "lay": lay, "matched": m.get("matched") or 0,
            "tight": tight, "market": m.get("name"), "kind": kind, "type": m.get("type")}


def _back_only(r, m, over: bool):
    """A back-only list runner (anytime scorer and the like)."""
    if not r or not r.get("back"):
        return None
    back, lay = r["back"], r.get("lay")
    if lay and lay / back < 1.3:
        p, kind, margin = 2 / (back + lay), "exchange", 0.0
    else:
        margin = back_margin(m.get("type"))
        p, kind = (1 / back) / (1 + margin), "back"
    p = min(max(p, 0.001), 0.999)
    q = {"p": round(p if over else 1 - p, 4), "back": back if over else None,
         "lay": lay if over else None, "matched": m.get("matched") or 0,
         "tight": bool(lay and lay / back < 1.10), "market": m.get("name"),
         "kind": kind, "type": m.get("type"), "margin": margin}
    return q


def _band(m, line, over: bool):
    """Banded markets ("9 or less", "10 - 12", "13 or more") answer the
    over/under at their edges: under 9.5 is "9 or less", over 12.5 is "13 or
    more". Priced from the whole band set with the margin off."""
    rows = []
    for r in m["runners"]:
        n = r["name"].lower()
        mm = re.match(r"(\d+)\s*or\s*(less|more)", n) or re.match(r"(\d+)\s*(?:and|or)\s*(under|over)", n)
        if mm:
            k = int(mm.group(1))
            edge = k + 0.5 if mm.group(2) in ("less", "under") else k - 0.5
            rows.append((edge, mm.group(2) in ("less", "under"), r))
    for edge, is_under, r in rows:
        if abs(edge - line) > 1e-6 or r.get("p") is None:
            continue
        p = r["p"] if is_under else 1 - r["p"]
        p = p if not over else 1 - p
        own = (not over) == is_under
        back = r.get("back") if own else None
        lay = r.get("lay") if own else None
        return {"p": round(p, 4), "back": back, "lay": lay, "matched": m.get("matched") or 0,
                "tight": bool(back and lay and lay / back < 1.10) and not r.get("est"),
                "market": m.get("name"), "kind": "exchange", "type": m.get("type")}
    return None


# --------------------------------------------------------- the goal model

def _pois(lam: float, kmax: int = 10) -> list:
    out, p = [], math.exp(-lam)
    for k in range(kmax + 1):
        out.append(p)
        p *= lam / (k + 1)
    return out


def _probs(lh: float, la: float):
    ph, pa = _pois(lh), _pois(la)
    home = draw = away = 0.0
    tot = [0.0] * 21
    for i, x in enumerate(ph):
        for j, y in enumerate(pa):
            v = x * y
            tot[i + j] += v
            if i > j:
                home += v
            elif i == j:
                draw += v
            else:
                away += v
    return home, draw, away, tot


def _lg(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


_GOALS: dict = {}


def goal_model(data: dict | None, fixture_id):
    """Expected goals for each side, read off the exchange's own match odds
    and goal lines: two Poisson means fitted so the model reproduces
    Betfair's home, away and over/under chances as closely as it can.
    Returns None without match odds and at least one goal line."""
    if not data:
        return None
    key = str(fixture_id)
    if key in _GOALS:
        return _GOALS[key]
    _GOALS[key] = None
    ev = (data.get("events") or {}).get(key)
    if not ev or ev.get("sport") != "football":
        return None
    mo = match_odds(data, fixture_id)
    if not mo or mo.get("draw") is None:
        return None
    lines = []
    for m in ev["markets"]:
        t = m.get("type") or ""
        mm = re.fullmatch(r"OVER_UNDER_(\d)5", t)
        if mm:
            r = _ou(m, True)
            if r and r.get("p") is not None:
                lines.append((int(mm.group(1)) + 0.5, r["p"], m.get("matched") or 0))
    if not lines:
        return None
    targets = [(_lg(mo["home"]), None, 2.0), (_lg(mo["away"]), None, 2.0)]

    def err(lh, la):
        h, d, a, tot = _probs(lh, la)
        e = 2.0 * (_lg(h) - _lg(mo["home"])) ** 2 + 2.0 * (_lg(a) - _lg(mo["away"])) ** 2
        for line, p, _ in lines:
            over = sum(tot[int(line) + 1:])
            e += (_lg(over) - _lg(p)) ** 2
        return e

    best = None
    step = 0.2
    grid = [0.2 + step * i for i in range(20)]
    for lh in grid:
        for la in grid:
            v = err(lh, la)
            if best is None or v < best[0]:
                best = (v, lh, la)
    for step in (0.05, 0.01):
        _, ch, ca = best
        for i in range(-4, 5):
            for j in range(-4, 5):
                lh, la = ch + i * step, ca + j * step
                if lh <= 0.05 or la <= 0.05:
                    continue
                v = err(lh, la)
                if v < best[0]:
                    best = (v, lh, la)
    v, lh, la = best
    ou = next((m for m in ev["markets"] if m.get("type") == "OVER_UNDER_25"), {})
    mom = next((m for m in ev["markets"] if m.get("type") == "MATCH_ODDS"), {})
    tight_rows = [r for r in (mom.get("runners") or []) + (ou.get("runners") or [])
                  if r.get("back") and r.get("lay")]
    tight = bool(tight_rows) and all(r["lay"] / r["back"] < 1.10 for r in tight_rows)
    out = {"home": round(lh, 3), "away": round(la, 3), "fitError": round(v / (2 + len(lines)), 4),
           "matched": mo.get("matched") or 0, "tight": tight,
           "win": mo["home"], "draw": mo["draw"], "loss": mo["away"]}
    _GOALS[key] = out
    return out


def _derived_goals(g, side, line, over, label):
    if not g or g["fitError"] > 0.05:
        return None
    lam = g["home"] if side == 0 else g["away"] if side == 1 else g["home"] + g["away"]
    ps = _pois(lam, 20)
    p_over = 1 - sum(ps[: int(line) + 1])
    p = p_over if over else 1 - p_over
    return {"p": round(min(max(p, 0.001), 0.999), 4), "back": None, "lay": None,
            "matched": g["matched"], "tight": g["tight"], "market": label,
            "kind": "derived", "type": "POISSON", "lambda": round(lam, 2)}


def leg_quote(data: dict | None, fixture_id, leg: dict):
    """The exchange's chance (margin off) and back price for one of the site's
    legs, or None if the exchange has no market that is, or implies, the same
    bet."""
    if not data:
        return None
    ev = (data.get("events") or {}).get(str(fixture_id))
    if not ev:
        return None
    stat, line, over = leg.get("stat"), leg.get("line"), bool(leg.get("over", True))
    period = leg.get("period") or "ALL"
    side = leg.get("teamIndex")
    bf_side = (1 - side) if ev.get("swapped") and side in (0, 1) else side
    by_type = {}
    for m in ev["markets"]:
        by_type.setdefault(m["type"], []).append(m)

    def one(t):
        return (by_type.get(t) or [None])[0]

    if not isinstance(line, (int, float)):
        return None

    if leg.get("player"):
        if period != "ALL":
            return None
        t = {("Shots on target", 0.5): "SHOTS_ON_TARGET_P1",
             ("Shots on target", 1.5): "SHOTS_ON_TARGET_P2",
             ("Goals", 0.5): "TO_SCORE", ("Goals", 1.5): "TO_SCORE_2_OR_MORE",
             ("Yellow cards", 0.5): "SHOWN_A_CARD",
             ("Anytime touchdown", 0.5): "TO_SCORE_A_TOUCHDOWN"}.get((stat, line))
        m = one(t) if t else None
        if not m:
            return None
        return _back_only(_find_player(m, leg["player"]), m, over)

    tag = f"{int(line * 10):02d}"
    if period == "1ST" and stat == "Match goals":
        m = one(f"FIRST_HALF_GOALS_{tag}")
        return _quote(_ou(m, over), m) if m else None
    if period != "ALL":
        return None
    if stat == "Match goals":
        m = one(f"OVER_UNDER_{tag}")
        q = _quote(_ou(m, over), m) if m else None
        if not q and one("ALT_TOTAL_GOALS"):
            alt = one("ALT_TOTAL_GOALS")
            q = _quote(_ou(alt, over, line), alt)
        return q or _derived_goals(goal_model(data, fixture_id), None, line, over, "Goal model")
    if stat == "Both teams to score" and line == 0.5:
        m = one("BOTH_TEAMS_TO_SCORE")
        return _quote(_yes(m, over), m) if m else None
    if stat == "Match corners":
        m = one(f"OVER_UNDER_{tag}_CORNR")
        q = _quote(_ou(m, over), m) if m else None
        if not q and one("CORNER_ODDS"):
            q = _band(one("CORNER_ODDS"), line, over)
        return q
    if stat == "Match cards":
        m = one(f"OVER_UNDER_{tag}_CARDS")
        return _quote(_ou(m, over), m) if m else None
    if stat == "Goals" and side in (0, 1):
        m = one(f"TEAM_{'AB'[bf_side]}_OVER_UNDER_{tag}")
        q = _quote(_ou(m, over), m) if m else None
        return q or _derived_goals(goal_model(data, fixture_id), side, line, over, "Goal model")
    return None


def implied(data: dict | None, fixture_id) -> dict | None:
    """What the market expects of a fixture, in our orientation: football
    expected goals and 1X2; NFL and MLB the points or runs total and the
    handicap where the exchange sits near even money. For explanations and
    for strength.py."""
    if not data:
        return None
    ev = (data.get("events") or {}).get(str(fixture_id))
    if not ev:
        return None
    if ev.get("sport") == "football":
        g = goal_model(data, fixture_id)
        if g:
            return dict(g, sport="football")
        mo = match_odds(data, fixture_id)
        return dict(mo, sport="football", win=mo["home"], loss=mo["away"]) if mo else None
    out = {"sport": ev.get("sport")}
    mo = match_odds(data, fixture_id)
    if mo:
        out.update(win=mo["home"], loss=mo["away"], matched=mo.get("matched"))
    tot = next((m for m in ev["markets"] if m.get("type") == "COMBINED_TOTAL"), None)
    if tot:
        best = None
        for r in tot["runners"]:
            if r["name"].lower().startswith("over") and r.get("p") is not None:
                if best is None or abs(r["p"] - 0.5) < abs(best["p"] - 0.5):
                    best = r
        if best:
            out["total"] = best["handicap"]
    hc = next((m for m in ev["markets"] if m.get("type") == "HANDICAP"), None)
    if hc and mo:
        sides = _split_event(ev.get("betfair", "")) or ("", "")
        our_home = sides[1] if ev.get("swapped") else sides[0]
        best = None
        for r in hc["runners"]:
            if r.get("p") is not None and sim(r["name"], our_home) >= 0.6:
                if best is None or abs(r["p"] - 0.5) < abs(best["p"] - 0.5):
                    best = r
        if best and abs(best["p"] - 0.5) < 0.12:
            out["homeSpread"] = best["handicap"]
    if "total" in out and "homeSpread" in out:
        out["homePoints"] = round((out["total"] - out["homeSpread"]) / 2, 1)
        out["awayPoints"] = round((out["total"] + out["homeSpread"]) / 2, 1)
    return out


def match_odds(data: dict | None, fixture_id):
    """[home, draw, away] or [home, away] chances, margin off, our orientation."""
    if not data:
        return None
    ev = (data.get("events") or {}).get(str(fixture_id))
    if not ev:
        return None
    m = next((x for x in ev["markets"] if x["type"] == "MATCH_ODDS"), None)
    if not m or any(r.get("p") is None for r in m["runners"]):
        return None
    names = [r["name"] for r in m["runners"]]
    draw = next((r["p"] for r in m["runners"] if r["name"].lower() in ("the draw", "draw")), None)
    teams = [r for r in m["runners"] if r["name"].lower() not in ("the draw", "draw")]
    if len(teams) != 2:
        return None
    # Runners come in Betfair's own order, which is not the event name's: on
    # "Chargers @ Chiefs" the Chargers are listed first. So the home runner is
    # found by name, against whichever side of the event name is our home.
    sides = _split_event(ev.get("betfair", "")) or ("", "")
    our_home = sides[1] if ev.get("swapped") else sides[0]
    h = max(teams, key=lambda r: sim(r["name"], our_home))
    a = teams[1] if h is teams[0] else teams[0]
    return {"home": h["p"], "draw": draw, "away": a["p"], "matched": m.get("matched") or 0}


def load(max_hours: float = 12) -> dict | None:
    try:
        data = json.loads(OUT.read_text())
    except (OSError, ValueError):
        return None
    if time.time() - data.get("fetched", 0) >= max_hours * 3600:
        return None
    # Priced again on load, so a file saved by an older version of the margin
    # maths is read with the current one.
    for ev in (data.get("events") or {}).values():
        for m in ev.get("markets") or []:
            m["overround"] = _devig(m.get("runners") or [], m.get("type"))
    return data


def main():
    import argparse
    import collections
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()
    data = load(24 * 7) if args.show else fetch(args.days)
    if not data:
        print("nothing cached")
        return
    types = collections.Counter()
    for ev in data["events"].values():
        for m in ev["markets"]:
            types[(ev["sport"], m["type"])] += 1
    print(f"\n{len(data['events'])} fixtures priced, written to {OUT.name}")
    for (sport, t), n in sorted(types.items()):
        print(f"  {sport:<18} {t:<34} {n}")
    if data["unmatched"]:
        print(f"\nnot matched ({len(data['unmatched'])}):")
        for u in data["unmatched"][:40]:
            print("  ", u)


if __name__ == "__main__":
    main()
