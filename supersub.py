#!/usr/bin/env python3
"""Paddy Power's Super Sub, for goalscorer bets.

    python supersub.py fit [DIR]   # measure it on cached line-ups -> supersub_fit.json
    python supersub.py audit       # settled pplog lines it changes (read only)

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
    return sport == "football" and (market or "") in APPLIES


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


def settle_row(r: dict, incidents_for) -> bool:
    """Turn a lost Paddy Power to-score line into a win when Super Sub paid.
    `incidents_for(event_id)` returns the incidents list or None. Returns True
    if the row changed."""
    if r.get("result") != "lose" or r.get("stat") != "Goals" or not applies(r.get("market"), r.get("sport")):
        return False
    inc = incidents_for(r["event_id"])
    if not inc:
        return False
    rep = replacement_scored(inc, r["player"])
    if not rep:
        return False
    r["result"] = "win"
    r["supersub"] = rep
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
    return {"matches": len(games), "sub_before": SUB_BEFORE, "positions": table, "check": check}


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

def audit() -> None:
    """Settled Paddy Power to-score lines graded lost that Super Sub won.
    Reads pplog/ and the cached incidents; changes nothing."""
    import pplog
    rows = [r for r in pplog.all_rows() if r.get("stat") == "Goals" and applies(r.get("market"), r.get("sport"))]
    done = [r for r in rows if r.get("result") in ("win", "lose")]
    flipped, checked = [], 0
    for r in done:
        if r["result"] != "lose" or r.get("supersub"):
            continue
        inc = _incidents(r["event_id"])
        if inc is None:
            continue
        checked += 1
        rep = replacement_scored(inc, r["player"])
        if rep:
            flipped.append((r, rep))
    already = sum(1 for r in done if r.get("supersub"))
    won = sum(1 for r in done if r["result"] == "win")
    print(f"{len(done)} settled Paddy Power to-score lines, {won} graded won "
          f"({already} of them by Super Sub already)")
    print(f"{checked} losses checked against the incidents; {len(flipped)} were Super Sub wins graded lost")
    for r, rep in flipped[:40]:
        print(f"  {r['fixture']}: {r['player']} off, {rep} scored  (price {r['first']['price']})")
    if done:
        print(f"hit rate {won / len(done):.1%} as graded, {(won + len(flipped)) / len(done):.1%} with Super Sub")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["fit", "audit"])
    ap.add_argument("folder", nargs="?", default=str(ROOT / "cache"))
    a = ap.parse_args()
    if a.cmd == "audit":
        audit()
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
    print("out of sample, starters who did not score:")
    for b, v in res["check"].items():
        print(f"  predicted {b:9} n={v['n']:<6} said {v['said']:.2%}  paid {v['paid']:.2%}")
    print(f"wrote {FIT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
