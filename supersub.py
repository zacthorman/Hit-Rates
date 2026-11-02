#!/usr/bin/env python3
"""Paddy Power's Super Sub, on every player market it covers.

    python supersub.py fit [DIR]        # measure it on cached line-ups -> supersub_fit.json
    python supersub.py audit            # settled pplog losses Super Sub won (read only)
    python supersub.py resettle --apply # regrade them in pplog/, from cached data only

2 Nov 2026: widened from anytime goalscorer to every market Paddy Power's
terms list (read off its own event page on 2 Nov): shots 1+ to 6+, shots on
target 1+ to 4+, fouls and fouled 1+ to 3+, goals 1+ to 3+, anytime assist
and to be carded, on the Premier League, Championship, League One and Two,
FA Cup (round 3 on), EFL Cup, Champions and Europa League, Community Shield,
UEFA Super Cup and the Irish Premier Division. Not LaLiga, Serie A, the
Bundesliga, Ligue 1 or MLS. In 2+ and 3+ lines the starter's own count before
he goes off carries over and the replacement (and anyone who replaces him in
turn) only needs the rest. Whether a game qualifies is read off its Paddy
Power page (paddypower_prices.super_sub) and falls back to COMPETITIONS.

The extra chance on a counting line, k or more, is

    share x s x [P(Poisson(a + b) >= k) - P(Poisson(a) >= k)]

where share is how many of his last 10 appearances were starts (Super Sub
covers starters, and we price before the line-ups), s how often he is taken
off (his own starts ending before SUB_BEFORE), a his own expected count in
the minutes he plays when taken off (his per-90 rate, backed out of the
model's chance over his expected minutes, x his average minutes in those
starts, needing 3 such starts and held to 45-84), and b the
replacement's in the rest (the per-90 rate of replacements for his position,
measured by `fit`, x the minutes left). Anytime goalscorer keeps the original
formula below, which was checked out of sample (SUPERSUB-CHECK.md).

The original note, for anytime goalscorer:

Paddy Power's Super Sub: a pre-match anytime goalscorer bet on a player who
starts and is substituted moves to the player who replaces him. The bet wins
if either scores: the starter before he goes off, or the replacement after he
comes on. Zac should check the current terms on Paddy Power's site before
relying on the list of markets below; this applies it to anytime goalscorer
only, the one goalscorer market the site prices.

Two things went wrong without it:

  * Pricing. pplog.py and the pages priced to-score on the player alone, over
    his expected minutes. That is the right chance for an ordinary bookmaker
    but too low for Paddy Power, which pays out on the replacement as well.
    Every Paddy Power to-score edge was understated, most for forwards who are
    taken off often.
  * Settling. pplog.py settled the player's own goals. A bet the replacement
    won was graded lost, so the record understated Paddy Power's to-score
    lines too.

The extra chance is (1 - his own chance) x how often he is taken off x how
often the replacement scores, given he was taken off without scoring. The
last figure is by position (G, D, M, F) and is measured by `fit` on the
backtest line-ups in cache_backtest.tar.zst, not assumed; supersub_fit.json
holds it. How often he is taken off is his own record: the share of his
starts that ended before SUB_BEFORE minutes.

Line-ups say who started and how long everyone played, but not who replaced
whom (that is in the incidents, which the backtest cache does not keep). So
`fit` pairs them by time: the first starter off is paired with the substitute
who played longest. A red card leaves a starter short with no replacement and
can be mis-paired; it is rare enough not to move the figures much, and
settling uses the real substitution incidents, not this pairing.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import math
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIT = ROOT / "supersub_fit.json"

# Paddy Power market names (as paddypower_prices.py records them) the
# concession applies to. Both are the anytime goalscorer market.
APPLIES = {"Anytime Goalscorer", "Player To Score"}

# Every market Super Sub covers, as pplog/the pages name the stat, and the
# highest "k or more" Paddy Power's terms list for it.
MAX_LINE = {"Goals": 3, "Shots": 6, "Shots on target": 4, "Fouls": 3, "Fouled": 3,
            "Assists": 1, "Card": 1}
# The fallback when a game's page did not say (SofaScore's names). The FA Cup
# only counts from round 3, which the name cannot tell; the page flag can.
COMPETITIONS = {"Premier League", "Championship", "League One", "League Two", "FA Cup",
                "EFL Cup", "UEFA Champions League", "UEFA Europa League", "Community Shield",
                "UEFA Super Cup", "Premier Division"}
P_CAP = 0.995

SUB_BEFORE = 85      # a start that ended before this many minutes was a substitution
MIN_STARTS = 5       # starts needed before his own substitution rate is used
# Used when supersub_fit.json is missing: the fit of 23 Oct 2026 on the
# backtest cache (6,765 matches), rounded. IMPORTS.md has the table.
DEFAULT_REP = {"G": 0.0, "D": 0.024, "M": 0.052, "F": 0.080}
BANDS = ("under 2%", "2-4%", "4-6%", "6%+")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return " ".join("".join(c for c in s if c.isascii() and (c.isalpha() or c == " ")).lower().split())


# ------------------------------------------------------------------ the chance

def load_fit() -> dict:
    """Position -> chance the replacement scores, given the starter was taken off without scoring."""
    try:
        j = json.loads(FIT.read_text())
        return {k: v["rep_scores"] for k, v in j["positions"].items() if "rep_scores" in v}
    except (OSError, ValueError, KeyError, TypeError):
        return dict(DEFAULT_REP)


def sub_rate(played: list[dict], min_starts: int = MIN_STARTS):
    """Share of his starts that ended in a substitution, or None on too few.

    Rows are the player records the pipeline keeps (hitrates.py): "started"
    and "minutes". Matches he came off the bench in say nothing about it."""
    starts = [g for g in played if g.get("started") and (g.get("minutes") or 0) > 0]
    if len(starts) < min_starts:
        return None
    return sum(1 for g in starts if g["minutes"] < SUB_BEFORE) / len(starts)


def chance(p_own: float, s: float, rep: float) -> float:
    """To score with Super Sub: his own chance, or taken off without scoring and the replacement scores."""
    return p_own + (1 - p_own) * s * rep


def position_of(played: list[dict]):
    """His most common position in the records (G, D, M or F)."""
    c = collections.Counter(g.get("position") for g in played if g.get("position"))
    return c.most_common(1)[0][0] if c else None


def uplift(p_own: float, played: list[dict], fit: dict | None = None):
    """(chance with Super Sub, the extra) for one player, or (p_own, 0.0)
    when his record is too thin to say how often he comes off."""
    s = sub_rate(played)
    rep = (fit if fit is not None else load_fit()).get(position_of(played) or "")
    if s is None or not rep:
        return p_own, 0.0
    p = chance(p_own, s, rep)
    return p, p - p_own


def applies(market: str | None, sport: str = "football") -> bool:
    """Anytime goalscorer by market name (the original check, kept for callers
    that only have a market). eligible() is the full rule."""
    return sport == "football" and (market or "") in APPLIES


def eligible(sport: str | None, stat: str | None, line, over=True, flag=None,
             competition: str | None = None) -> bool:
    """Does Super Sub cover this line? `flag` is the game page's own answer
    (True/False) when there is one; otherwise the competition decides."""
    if sport != "football" or not over or stat not in MAX_LINE or line is None:
        return False
    k = int(round(float(line) + 0.5))
    if k < 1 or k > MAX_LINE[stat]:
        return False
    if flag is not None:
        return bool(flag)
    return (competition or "") in COMPETITIONS


def eligible_row(r: dict) -> bool:
    """eligible() for a pplog row: its own page flag (ss_ok) or competition."""
    return eligible(r.get("sport"), r.get("stat"), r.get("line"), r.get("over", True),
                    r.get("ss_ok"), r.get("competition"))


# Replacements' per-90 rates by the position of the man they replace, and the
# average minutes a starter has played when taken off. Used when
# supersub_fit.json has no "rates" (it does from 2 Nov 2026). Cards are
# measured from incidents, which the backtest cache does not keep, so they
# come from the live cache (see fit).
DEFAULT_RATES = {
    "D": {"Shots": 1.08, "Shots on target": 0.33, "Fouls": 1.37, "Fouled": 1.07, "Goals": 0.08, "Assists": 0.09, "Card": 0.3, "_off_minutes": 64.3},
    "M": {"Shots": 2.01, "Shots on target": 0.71, "Fouls": 1.66, "Fouled": 1.5, "Goals": 0.21, "Assists": 0.16, "Card": 0.31, "_off_minutes": 66.9},
    "F": {"Shots": 2.68, "Shots on target": 1.05, "Fouls": 1.81, "Fouled": 1.59, "Goals": 0.34, "Assists": 0.16, "Card": 0.29, "_off_minutes": 67.4},
}


def load_rates() -> dict:
    try:
        j = json.loads(FIT.read_text())
        rates = j.get("rates")
        if rates:
            return rates
    except (OSError, ValueError, AttributeError):
        pass
    return {k: dict(v) for k, v in DEFAULT_RATES.items()}


def _tail(lam: float, k: int) -> float:
    """P(Poisson(lam) >= k)."""
    if k <= 0:
        return 1.0
    if lam <= 0:
        return 0.0
    term = math.exp(-lam)
    below = term
    for i in range(1, k):
        term *= lam / i
        below += term
    return max(0.0, 1.0 - below)


def _starts(played: list[dict]) -> list[dict]:
    return [g for g in played if g.get("started") and (g.get("minutes") or 0) > 0]


def rate_from_chance(p: float, k: int, minutes: float) -> float:
    """The per-90 rate at which P(Poisson(rate x minutes/90) >= k) = p.
    Bisection, 60 steps, the same on the page."""
    p = min(max(p, 0.0), 0.999)
    if p <= 0 or minutes <= 0:
        return 0.0
    lo, hi = 0.0, 40.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _tail(mid * minutes / 90, k) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


MIN_OFF = 3          # early-ending starts needed before his own minute is used
OFF_RANGE = (45, 84) # and it is held inside this: earlier exits are mostly injuries


def off_minutes(played: list[dict]):
    """His average minutes in the starts that ended in a substitution, or
    None on fewer than MIN_OFF of them."""
    off = [g["minutes"] for g in _starts(played) if g["minutes"] < SUB_BEFORE]
    if len(off) < MIN_OFF:
        return None
    return min(OFF_RANGE[1], max(OFF_RANGE[0], sum(off) / len(off)))


def start_share(played: list[dict], last: int = 10) -> float:
    """Share of his last `last` appearances that were starts. Super Sub only
    covers a starter, and the model's chance is priced before the line-ups,
    so for a rotation player the extra is only worth this share of itself."""
    apps = sorted((g for g in played if (g.get("minutes") or 0) > 0), key=lambda g: str(g.get("date") or ""))[-last:]
    if not apps:
        return 0.0
    return sum(1 for g in apps if g.get("started")) / len(apps)


def extra_for(p_own: float, stat: str, k: int, played: list[dict],
              rates: dict | None = None, fit: dict | None = None):
    """(chance with Super Sub, the extra) for 'k or more' of `stat`.
    (p_own, 0.0) when his record cannot say how often he comes off."""
    if stat == "Goals" and k == 1:
        return uplift(p_own, played, fit)
    s = sub_rate(played)
    pos = position_of(played) or ""
    rp = (rates if rates is not None else load_rates()).get(pos) or {}
    rho = rp.get(stat)
    if s is None or not s or not rho or stat not in MAX_LINE:
        return p_own, 0.0
    m_off = off_minutes(played) or rp.get("_off_minutes") or 68.0
    share = start_share(played)
    # His own per-90 rate, backed out of the model's chance over the minutes
    # he is expected to play, so the extra always agrees with the price it is
    # added to. His raw record would not: five starts without a shot read as
    # a rate of nil against a model that, from more than his record, gave
    # him 53% (Nico Gonzalez, 2 Nov 2026), and the extra came out at +32.
    exp_min = (1 - s) * 90 + s * m_off
    lam = rate_from_chance(p_own, k, exp_min)
    a = lam * m_off / 90
    b = rho * max(0.0, 90 - m_off) / 90
    extra = max(0.0, share * s * (_tail(a + b, k) - _tail(a, k)))
    p = min(P_CAP, p_own + extra)
    return p, p - p_own


# ------------------------------------------------------------------ settling

def replacement_scored(incidents: list[dict], player: str):
    """The replacement's name if `player` started, was substituted, and the
    man who came on for him scored (not an own goal). None otherwise.

    `incidents` is SofaScore's event/<id>/incidents list: substitutions carry
    playerIn and playerOut, goals carry player and incidentClass."""
    me = _norm(player)
    came_on = any(i.get("incidentType") == "substitution"
                  and _norm((i.get("playerIn") or {}).get("name", "")) == me for i in incidents)
    if came_on:
        return None           # Super Sub covers starters only
    sub = next((i for i in incidents if i.get("incidentType") == "substitution"
                and _norm((i.get("playerOut") or {}).get("name", "")) == me), None)
    if not sub:
        return None
    rep = (sub.get("playerIn") or {}).get("name", "")
    on_at = sub.get("time") or 0
    for i in incidents:
        if (i.get("incidentType") == "goal" and i.get("incidentClass") != "ownGoal"
                and _norm((i.get("player") or {}).get("name", "")) == _norm(rep)
                and (i.get("time") or 0) >= on_at):
            return rep
    return None


def chain(incidents: list[dict], player: str):
    """Everyone who replaced `player` in turn (a sub for him, then a sub for
    that sub...), as [(name, minute on)], [] if he was not taken off, or None
    if he came on as a substitute himself (Super Sub covers starters only)."""
    subs = [i for i in incidents if i.get("incidentType") == "substitution"]
    me = _norm(player)
    if any(_norm((i.get("playerIn") or {}).get("name", "")) == me for i in subs):
        return None
    out, cur, seen = [], me, {me}
    while True:
        sub = next((i for i in subs if _norm((i.get("playerOut") or {}).get("name", "")) == cur), None)
        if not sub:
            return out
        rep = (sub.get("playerIn") or {}).get("name", "")
        if not rep or _norm(rep) in seen:
            return out
        out.append((rep, sub.get("time") or 0))
        cur = _norm(rep)
        seen.add(cur)


def _box_value(lineups: dict, name: str, stat: str) -> float:
    """One player's count of `stat` in the match line-ups (0 when absent)."""
    import hitrates
    for side in ("home", "away"):
        for p in (lineups.get(side) or {}).get("players", []) or []:
            if _norm((p.get("player") or {}).get("name", "")) == _norm(name):
                vals = hitrates._player_stat_values(p.get("statistics") or {},
                                                    zero_fill=hitrates.PLAYER_ZERO_FILL)
                return float((vals or {}).get(stat, 0.0))
    return 0.0


def replacement_count(r: dict, incidents: list[dict], lineups: dict | None):
    """(the replacements' combined count of r's stat, their names) or None
    when it cannot be worked out. Goals and cards from the incidents, the
    rest from the line-ups (a substitute's whole match is after he came on)."""
    reps = chain(incidents, r["player"])
    if not reps:
        return None
    names = {_norm(n) for n, _ in reps}
    stat = r["stat"]
    if stat == "Goals":
        n = sum(1 for i in incidents if i.get("incidentType") == "goal"
                and i.get("incidentClass") != "ownGoal"
                and _norm((i.get("player") or {}).get("name", "")) in names)
    elif stat == "Card":
        n = 1 if any(i.get("incidentType") == "card"
                     and _norm((i.get("player") or {}).get("name", "")) in names for i in incidents) else 0
    else:
        if not lineups:
            return None
        n = sum(_box_value(lineups, nm, stat) for nm, _ in reps)
    return float(n), [nm for nm, _ in reps]


def settle_row(r: dict, incidents_for, lineups_for=None) -> bool:
    """Turn a lost Paddy Power line into a win when Super Sub paid: his own
    count plus his replacements' clears the line. `incidents_for(event_id)`
    and `lineups_for(event_id)` return SofaScore's data or None. Returns True
    if the row changed."""
    if r.get("result") != "lose" or not eligible_row(r):
        return False
    inc = incidents_for(r["event_id"])
    if not inc:
        return False
    lu = lineups_for(r["event_id"]) if (lineups_for and r["stat"] not in ("Goals", "Card")) else None
    got = replacement_count(r, inc, lu)
    if not got:
        return False
    n, names = got
    total = float(r.get("value") or 0) + n
    if total <= r["line"]:
        return False
    r["result"] = "win"
    r["supersub"] = names[0]
    r["supersub_value"] = total
    return True


def _incidents(event_id):
    import sofascore_api as api
    data = api.get_json(f"event/{event_id}/incidents", max_age_hours=None, verbose=False)
    return (data or {}).get("incidents")


# ------------------------------------------------------------------ fit

def _pairs(side: dict):
    """(starter, replacement or None, team minutes) for one side's line-up."""
    ps = side.get("players") or []
    st = [p for p in ps if not p.get("substitute")]
    if len(st) != 11:
        return []

    def mins(p):
        return (p.get("statistics") or {}).get("minutesPlayed") or 0
    full = max(mins(p) for p in st)
    off = sorted((p for p in st if 0 < mins(p) < full - 1), key=mins)
    on = sorted((p for p in ps if p.get("substitute") and mins(p) > 0), key=mins, reverse=True)
    rep = {id(a): b for a, b in zip(off, on)}
    return [(p, rep.get(id(p))) for p in st]


def match_rows(lineups: dict) -> list[dict]:
    """One row per starter: position, minutes, scored, taken off (before
    SUB_BEFORE), and whether his replacement scored."""
    out = []
    for side in ("home", "away"):
        for p, rep in _pairs(lineups.get(side) or {}):
            st = p.get("statistics") or {}
            if "minutesPlayed" not in st:
                continue
            m = st.get("minutesPlayed") or 0
            off = rep is not None and m < SUB_BEFORE
            out.append({"id": (p.get("player") or {}).get("id"), "pos": p.get("position") or "?",
                        "minutes": m, "scored": (st.get("goals") or 0) > 0, "off": off,
                        "rep_scored": off and ((rep.get("statistics") or {}).get("goals") or 0) > 0})
    return out


def fit(folder: Path) -> dict:
    when = {}
    for f in glob.glob(str(folder / "team_*_events_last_*.json")):
        try:
            for e in json.loads(Path(f).read_text()).get("events") or []:
                when[e["id"]] = e.get("startTimestamp") or 0
        except (OSError, ValueError, KeyError, TypeError):
            continue
    games = []
    for f in glob.glob(str(folder / "event_*_lineups.json")):
        try:
            eid = int(Path(f).name.split("_")[1])
            rows = match_rows(json.loads(Path(f).read_text()))
        except (OSError, ValueError, IndexError):
            continue
        if rows:
            games.append((when.get(eid, 0), eid, rows))
    games.sort(key=lambda g: (g[0], g[1]))
    pos = collections.defaultdict(collections.Counter)
    for _, _, rows in games:
        for r in rows:
            c = pos[r["pos"]]
            c["starts"] += 1
            c["scored"] += r["scored"]
            c["off"] += r["off"]
            if r["off"] and not r["scored"]:
                c["off_no_goal"] += 1
                c["rep_scored"] += r["rep_scored"]
    table = {}
    for k, c in sorted(pos.items()):
        if k not in ("G", "D", "M", "F"):
            continue
        table[k] = {"starts": c["starts"], "scored": round(c["scored"] / c["starts"], 4),
                    "taken_off": round(c["off"] / c["starts"], 4),
                    "rep_scores": round(c["rep_scored"] / c["off_no_goal"], 4) if c["off_no_goal"] else 0.0,
                    "extra_wins": round(c["rep_scored"] / c["starts"], 4)}
    check = validate(games, {k: v["rep_scores"] for k, v in table.items()})
    return {"matches": len(games), "sub_before": SUB_BEFORE, "positions": table, "check": check,
            "rates": fit_rates(folder)}


RATE_STATS = ("Shots", "Shots on target", "Fouls", "Fouled", "Goals", "Assists")


def fit_rates(folder: Path) -> dict:
    """Per position of the starter taken off: his replacement's per-90 rate
    for each stat over the minutes the replacement played, and the starter's
    average minutes when taken off. Cards from incidents where the folder has
    them (the backtest cache does not; cache/ does). Same pairing as fit()."""
    import hitrates
    acc = collections.defaultdict(lambda: collections.defaultdict(float))
    for f in glob.glob(str(folder / "event_*_lineups.json")):
        try:
            lu = json.loads(Path(f).read_text())
        except (OSError, ValueError):
            continue
        inc_path = Path(f.replace("_lineups.json", "_incidents.json"))
        booked = None
        if inc_path.exists():
            try:
                booked = {_norm((i.get("player") or {}).get("name", ""))
                          for i in (json.loads(inc_path.read_text()).get("incidents") or [])
                          if i.get("incidentType") == "card"}
            except (OSError, ValueError, AttributeError):
                booked = None
        for side in ("home", "away"):
            for p, rep in _pairs(lu.get(side) or {}):
                st = p.get("statistics") or {}
                m = st.get("minutesPlayed") or 0
                if rep is None or not m or m >= SUB_BEFORE:
                    continue
                rs = rep.get("statistics") or {}
                rm = rs.get("minutesPlayed") or 0
                if not rm:
                    continue
                a = acc[p.get("position") or "?"]
                a["n"] += 1
                a["off_minutes"] += m
                a["rep_minutes"] += rm
                vals = hitrates._player_stat_values(rs, zero_fill=hitrates.PLAYER_ZERO_FILL) or {}
                for k in RATE_STATS:
                    a[k] += float(vals.get(k, 0.0))
                if booked is not None:
                    a["card_minutes"] += rm
                    a["Card"] += 1 if _norm((rep.get("player") or {}).get("name", "")) in booked else 0
    out = {}
    for pos, a in sorted(acc.items()):
        if pos not in ("D", "M", "F") or a["n"] < 50:
            continue
        row = {k: round(a[k] / a["rep_minutes"] * 90, 4) for k in RATE_STATS}
        row["Card"] = round(a["Card"] / a["card_minutes"] * 90, 4) if a["card_minutes"] else DEFAULT_RATES[pos]["Card"]
        row["_off_minutes"] = round(a["off_minutes"] / a["n"], 1)
        row["_pairs"] = int(a["n"])
        row["_card_pairs_minutes"] = round(a["card_minutes"])
        out[pos] = row
    return out


def validate(games: list, rep: dict) -> dict:
    """Out of sample: fitted on the first 70% of matches by date, each
    starter's Super Sub extra predicted from his own earlier starts only,
    compared on the last 30% with how often it actually paid."""
    cut = int(len(games) * 0.7)
    train = collections.defaultdict(collections.Counter)
    for _, _, rows in games[:cut]:
        for r in rows:
            if r["off"] and not r["scored"]:
                train[r["pos"]]["n"] += 1
                train[r["pos"]]["k"] += r["rep_scored"]
    rep_tr = {k: c["k"] / c["n"] for k, c in train.items() if c["n"]}
    history = collections.defaultdict(list)
    bands = collections.defaultdict(lambda: [0, 0.0, 0])
    for i, (_, _, rows) in enumerate(games):
        for r in rows:
            past = history[r["id"]]
            if i >= cut and not r["scored"] and r["pos"] in rep_tr and len(past) >= MIN_STARTS:
                s = sum(1 for m in past if m < SUB_BEFORE) / len(past)
                pred = s * rep_tr[r["pos"]]
                b = "under 2%" if pred < 0.02 else "2-4%" if pred < 0.04 else "4-6%" if pred < 0.06 else "6%+"
                bands[b][0] += 1
                bands[b][1] += pred
                bands[b][2] += r["rep_scored"]
            past.append(r["minutes"])
    return {b: {"n": bands[b][0], "said": round(bands[b][1] / bands[b][0], 4),
                "paid": round(bands[b][2] / bands[b][0], 4)} for b in BANDS if bands[b][0]}


# ------------------------------------------------------------------ audit

def _cached(path: str):
    """A SofaScore answer from cache/ only: no requests."""
    import sofascore_api as api
    f = api._cache_file(path)
    try:
        return json.loads(f.read_text())
    except (OSError, ValueError):
        return None


def resettle(apply: bool = False) -> int:
    """Settled pplog losses that Super Sub won, from cached incidents and
    line-ups only. Prints them; with apply, regrades the rows in pplog/.
    Also turns back goalscorer wins credited outside Super Sub's
    competitions before 2 Nov 2026 (the old check looked at the market only)."""
    import pplog
    flipped, unflipped, checked, missing = [], [], 0, 0
    by_stat = collections.Counter()
    for path in pplog._files():
        rows = pplog._read(path)
        changed = False
        for r in rows:
            if r.get("sport") != "football":
                continue
            if r.get("supersub") and r.get("result") == "win" and not eligible_row(r):
                unflipped.append(r)
                if apply:
                    r["result"] = "lose"
                    r.pop("supersub", None)
                    r.pop("supersub_value", None)
                    changed = True
                continue
            if r.get("result") != "lose" or not eligible_row(r):
                continue
            inc = (_cached(f"event/{r['event_id']}/incidents") or {}).get("incidents")
            if not inc:
                missing += 1
                continue
            checked += 1
            before = dict(r)
            if settle_row(r, lambda _e: inc, lambda e: _cached(f"event/{e}/lineups")):
                flipped.append(r)
                by_stat[(r["stat"], r["line"] + 0.5)] += 1
                if apply:
                    changed = True
                else:
                    r.clear()
                    r.update(before)
        if changed:
            pplog._write(path, rows)
    print(f"{checked} eligible losses checked ({missing} with no cached incidents)")
    print(f"{len(flipped)} were Super Sub wins graded lost" + ("; regraded" if apply else "; run with --apply to regrade"))
    for (stat, k), n in sorted(by_stat.items()):
        print(f"  {stat} {k:.0f}+: {n}")
    if unflipped:
        print(f"{len(unflipped)} goalscorer wins credited to Super Sub outside its competitions"
              + ("; set back to lost" if apply else ""))
    return len(flipped)


def audit() -> None:
    """Read-only resettle."""
    resettle(apply=False)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["fit", "audit", "resettle"])
    ap.add_argument("folder", nargs="?", default=str(ROOT / "cache"))
    ap.add_argument("--apply", action="store_true", help="resettle: write the regraded rows")
    a = ap.parse_args()
    if a.cmd == "audit":
        audit()
        return 0
    if a.cmd == "resettle":
        resettle(apply=a.apply)
        return 0
    res = fit(Path(a.folder))
    if not res["matches"]:
        print(f"no football line-ups in {a.folder}")
        return 1
    FIT.write_text(json.dumps(res, indent=1) + "\n")
    print(f"{res['matches']} matches")
    print(f"{'pos':4} {'starts':>7} {'scored':>7} {'off':>6} {'rep scores':>11} {'extra wins':>11}")
    for k, v in res["positions"].items():
        print(f"{k:4} {v['starts']:>7} {v['scored']:>7.1%} {v['taken_off']:>6.1%} "
              f"{v['rep_scores']:>11.1%} {v['extra_wins']:>11.2%}")
    for pos, r in (res.get("rates") or {}).items():
        print(f"  replacing {pos}: " + ", ".join(f"{k} {v:.2f}" for k, v in r.items() if not k.startswith("_"))
              + f" per 90; starter off at {r['_off_minutes']:.0f} min ({r['_pairs']} pairs)")
    print("out of sample, starters who did not score:")
    for b, v in res["check"].items():
        print(f"  predicted {b:9} n={v['n']:<6} said {v['said']:.2%}  paid {v['paid']:.2%}")
    print(f"wrote {FIT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
