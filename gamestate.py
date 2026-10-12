"""
The Line-ups tab's player lines, as JSON.

    .venv/bin/python -B gamestate.py --event 15534027
    .venv/bin/python -B gamestate.py --team "Aston Villa" --hours 168

The page works these out in the browser (gsState, gsFactor, gsRows, gsSquads,
luPairs and matchupProfile in report.py's script). This does the same sums in
Python from the same report data, so something other than a browser can read
them. The page is the reference: tests/test_gamestate.py runs the page's own
JavaScript in node on saved reports and requires every row here to match it to
3 decimal places. Change the page and that test fails until this matches.

Read only. It reads the payload already embedded in reports/*.html (the XI is
put there by lineups_auto.py), prints JSON and does nothing else.

Per fixture:
    xi            confirmed, predicted or regular starters, as gsSquads decides
    card          expected possession, projected volumes and the one-line script
    markets       Fouls, Fouled, Shots, Shots on target, Tackles: every line
                  gsRows backs ("lines") and its "works_against" list, each
                  with the positional matchup where matchupProfile has one
    foul_pairs    luPairs scoring 0.6 or more, both records; null without an XI

`on_page` marks the rows the page itself displays (top 6 lines, top 5 works
against, top 5 pairs). Everything else is what the page computes but cuts.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import hitrates
import markets
import model
from rerender import PAYLOAD

ROOT = Path(__file__).parent
REPORTS = ROOT / "reports"

PAGE_ROWS, PAGE_AGAINST, PAGE_PAIRS = 6, 5, 5

# report.py: GS_MARKETS, GS_TEAM, GS_MIN_MODEL, GS_MIN_RECORD.
GS_MARKETS = {
    "Fouls": [1, 2, 3],
    "Fouled": [1, 2, 3],
    "Shots": [1, 2, 3, 4],
    "Shots on target": [1, 2],
    "Tackles": [1, 2, 3, 4],
}
GS_TEAM = {
    "Shots":           {"stat": "Total shots",     "side": "for",     "ball": +1},
    "Shots on target": {"stat": "Shots on target", "side": "for",     "ball": +1},
    "Fouls":           {"stat": "Fouls",           "side": "for",     "ball": -1},
    "Fouled":          {"stat": "Fouls",           "side": "against", "ball": +1},
    "Tackles":         {"stat": "Tackles",         "side": "for",     "ball": -1},
}
GS_MIN_MODEL = 0.6
GS_MIN_RECORD = 0.5
PROJECTED = [("shots", "Total shots"), ("on_target", "Shots on target"),
             ("goals", "Goals"), ("fouls", "Fouls"), ("tackles", "Tackles")]

# report.py: POSITION_NAME (football's four), FOULS_ON, FOULED_BY,
# MATCHUP_PAIRING for the five markets above, MATCHUP_MIN_MATCHES.
POSITION_NAME = {"G": "goalkeepers", "D": "defenders", "M": "midfielders", "F": "forwards"}
FOULS_ON = {"G": "F", "D": "F", "M": "F", "F": "D"}
FOULED_BY = {"G": "F", "D": "F", "M": "M", "F": "D"}
MATCHUP_PAIRING = {
    "Shots":           {"mode": "conceded", "stat": "Shots"},
    "Shots on target": {"mode": "conceded", "stat": "Shots on target"},
    "Tackles":         {"mode": "conceded", "stat": "Tackles"},
    "Fouls":           {"mode": "own", "stat": "Fouled", "positions": FOULS_ON},
    "Fouled":          {"mode": "own", "stat": "Fouls", "positions": FOULED_BY},
}
MATCHUP_MIN_MATCHES = 5

SPORT = "football"
MIN_MINUTES = model.min_minutes_for(SPORT)
ZERO_FILL = markets.ZERO_FILL_BY_SPORT.get(SPORT) or hitrates.PLAYER_ZERO_FILL


# --------------------------------------------------------------- JS semantics

def truthy(v) -> bool:
    """JavaScript truthiness: an empty object or list is true there."""
    if v is None or v is False:
        return False
    if isinstance(v, (int, float)):
        return v == v and v != 0
    if isinstance(v, str):
        return v != ""
    return True


def avg(xs: list):
    """gsAvg: summed left to right like reduce, not Python's compensated sum."""
    if not xs:
        return None
    total = 0
    for x in xs:
        total += x
    return total / len(xs)


def stat_of(rec: dict, stat: str):
    v = (rec.get("stats") or {}).get(stat)
    return 0 if v is None else v


# ------------------------------------------------------------------- the page

class Fixture:
    """One fixture of one payload, the page's DATA, with its caches."""

    def __init__(self, payload: dict, index: int, matchup_index: dict):
        self.payload = payload
        self.fx = payload["fixtures"][index]
        self.matchup_index = matchup_index
        self.state = self._state()

    # luRecords
    def records(self, t: int, name: str) -> list:
        recs = [r for r in ((self.fx.get("players") or [])[t] or [])
                if r.get("player") == name and not truthy(r.get("former_club"))
                and (r.get("minutes") or 0) >= MIN_MINUTES_LU]
        recs.sort(key=lambda r: r.get("date") or "")
        return recs[-10:]

    # gsState
    def _state(self) -> dict:
        def team(t):
            all_recs = (self.fx.get("records") or [])[t] or []
            recs = [r for r in all_recs if not truthy(r.get("club"))][-10:]

            def pick(side, stat):
                return avg([v for v in (gs_val(r, side, stat) for r in recs) if v is not None])
            return {"n": len(recs), "poss": pick("for", "Ball possession"),
                    "xg": pick("for", "Expected goals"), "xga": pick("against", "Expected goals"),
                    "by_match": {r.get("id"): r for r in all_recs}}
        teams = [team(0), team(1)]
        poss = [50, 50]
        if truthy(teams[0]["poss"]) and truthy(teams[1]["poss"]):
            lg = lambda p: math.log(p / (1 - p))  # noqa: E731
            h = min(0.85, max(0.15, teams[0]["poss"] / 100))
            a = min(0.85, max(0.15, teams[1]["poss"] / 100))
            lo = 0.85 * (lg(h) - lg(a)) + 0.06
            p0 = 100 / (1 + math.exp(-lo))
            poss = [p0, 100 - p0]
        proj = (self.fx.get("projection") or {}).get("ALL") or {}
        tier_map = (self.fx.get("tiers") or {}).get("map") or {}
        tier_lab = (self.fx.get("tiers") or {}).get("labels") or {}
        tiers = [tier_lab.get(tier_map.get(js_str(t.get("id")))) or None for t in self.fx["teams"]]
        return {"teams": teams, "poss": poss, "proj": proj, "tiers": tiers}

    # gsFactor
    def factor(self, t: int, stat: str, recs: list) -> dict:
        st = self.state
        d = GS_TEAM[stat]
        games = [g for g in (st["teams"][t]["by_match"].get(r.get("match_id")) for r in recs) if truthy(g)]
        usual = avg([v for v in (gs_val(g, d["side"], d["stat"]) for g in games) if v is not None])
        usual_poss = avg([v for v in (gs_val(g, "for", "Ball possession") for g in games) if v is not None])
        proj_row = st["proj"].get(d["stat"])
        proj_team = None
        if truthy(proj_row):
            i = t if d["side"] == "for" else 1 - t
            proj_team = proj_row[i] if i < len(proj_row) else None
        mf = proj_team / usual if truthy(proj_team) and truthy(usual) else None
        pf = None
        if truthy(usual_poss) and truthy(st["teams"][0]["poss"]) and truthy(st["teams"][1]["poss"]):
            here = st["poss"][t]
            pf = here / usual_poss if d["ball"] > 0 else (100 - here) / (100 - usual_poss)
        if truthy(mf) and truthy(pf):
            f = math.sqrt(mf * pf)
        else:
            f = mf if truthy(mf) else pf if truthy(pf) else 1
        f = min(1.6, max(0.6, f))
        return {"f": f, "mf": mf, "pf": pf, "usual": usual, "projTeam": proj_team}

    # gsSquads
    def squads(self) -> dict:
        store = self.fx.get("lineups") or {}
        lu = store.get("confirmed") if truthy(store.get("confirmed")) else store.get("predicted")
        if truthy(lu):
            return {"source": "confirmed XI" if truthy(store.get("confirmed")) else "predicted XI",
                    "sides": [[p["name"] for p in (s.get("xi") or []) if p.get("pos") != "G"]
                              for s in (lu["home"], lu["away"])]}
        sides = []
        for t in (0, 1):
            recs = (self.fx.get("players") or [])[t] or []
            ids = list(dict.fromkeys(r.get("match_id") for r in recs))
            dates = {r.get("match_id"): r.get("date") for r in recs}
            last5 = set(sorted(ids, key=lambda m: dates.get(m) or "", reverse=True)[:5])
            starts: dict = {}
            for r in recs:
                if (r.get("match_id") not in last5 or truthy(r.get("former_club"))
                        or r.get("position") == "G" or (r.get("minutes") or 0) < 45):
                    continue
                starts[r.get("player")] = starts.get(r.get("player"), 0) + 1
            sides.append([name for name, n in starts.items() if n >= 3])
        return {"source": "regular starters (no line-up yet)", "sides": sides}

    # gsRows
    def rows(self, stat: str, lines: list, squads: dict):
        out, against = [], []
        for t, names in enumerate(squads["sides"]):
            for name in names:
                recs = self.records(t, name)
                if len(recs) < 5:
                    continue
                vals = [stat_of(r, stat) for r in recs]
                a = avg(vals)
                if not truthy(a):
                    continue
                g = self.factor(t, stat, recs)
                mu = a * g["f"]
                best = None
                for L in lines:
                    k = sum(1 for v in vals if v >= L)
                    rec = (k + 2) / (len(vals) + 4)
                    p = (pois_at_least(mu, L) + rec) / 2
                    if p >= GS_MIN_MODEL and rec >= GS_MIN_RECORD:
                        best = {"L": L, "k": k, "n": len(vals), "p": p, "rec": rec}
                row = {"t": t, "name": name, "avg": a, "mu": mu, "g": g, "best": best}
                if best:
                    out.append(row)
                L1 = lines[0]
                k1 = sum(1 for v in vals if v >= L1)
                if g["f"] <= 0.85 and (k1 + 2) / (len(vals) + 4) >= 0.6:
                    against.append({**row, "L": L1, "k": k1, "n": len(vals),
                                    "p": (pois_at_least(mu, L1) + (k1 + 2) / (len(vals) + 4)) / 2})
        out.sort(key=lambda x: (-x["best"]["p"], -x["best"]["L"]))
        against.sort(key=lambda x: x["g"]["f"])
        return out, against

    # matchupProfile, with the arguments gamestate.py chooses: his position on
    # his latest start, the line as an over (2+ is over 1.5), and the
    # opponent's last ten matches as the window.
    def matchup(self, t: int, name: str, stat: str, L: int):
        recs = self.records(t, name)
        pos = (recs[-1].get("position") or "") if recs else ""
        window = ((self.fx.get("records") or [])[1 - t] or [])[-10:]
        return pos, matchup_profile(self.matchup_index, self.fx, 1 - t, pos, stat, L - 0.5, window)

    # luPairs, on the XI lineupView hands it
    def pairs(self):
        store = self.fx.get("lineups") or {}
        lu = store.get("confirmed") if truthy(store.get("confirmed")) else store.get("predicted")
        if not truthy(lu):
            return None
        shapes = [lu_shape(lu["home"]), lu_shape(lu["away"])]
        out = []
        for t in (0, 1):
            mine, theirs = shapes[t], shapes[1 - t]
            for p in [q for ln in mine["lines"] for q in ln]:
                for o in lu_opponents(p, theirs):
                    pr, orr = self.records(t, p["name"]), self.records(1 - t, o["name"])
                    if len(pr) < 5 or len(orr) < 5:
                        continue
                    a, b = lu_rate(pr, "Fouled", 1), lu_rate(orr, "Fouls", 1)
                    out.append({"score": min(a["p"], b["p"]), "t": t, "p": p["name"], "o": o["name"],
                                "a": a, "b": b})
        out.sort(key=lambda x: -x["score"])
        seen, kept = set(), []
        for x in out:
            key = (x["p"], x["o"])
            if key in seen:
                continue
            seen.add(key)
            kept.append(x)
        return kept


MIN_MINUTES_LU = 45   # luRecords' own floor, written into the page as 45


def js_str(v) -> str:
    """String(v) for the ids the page uses as keys."""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def gs_val(rec: dict, side: str, stat: str):
    block = (rec.get("stats") or {}).get("ALL") if side == "for" else (rec.get("against") or {}).get("ALL")
    return (block or {}).get(stat)


def pois_at_least(mu: float, k: int) -> float:
    term, cdf = math.exp(-mu), 0
    for i in range(k):
        cdf += term
        term *= mu / (i + 1)
    return max(0, 1 - cdf)


def lu_rate(recs: list, stat: str, line: int) -> dict:
    v = [stat_of(r, stat) for r in recs]
    k = sum(1 for x in v if x >= line)
    return {"k": k, "n": len(v), "p": k / len(v) if v else None, "avg": avg(v)}


def lu_shape(side: dict) -> dict:
    xi = side.get("xi") or []
    out = [{"name": p["name"], "pos": p.get("pos")} for p in xi if p.get("pos") != "G"]
    sizes = []
    for part in str(side.get("formation") or "").split("-"):
        try:
            n = float(part) if part.strip() else 0
        except ValueError:
            continue
        if n > 0:
            sizes.append(int(n))
    if sum(sizes) != len(out):
        sizes = [n for n in (sum(1 for p in out if p["pos"] == c) for c in "DMF") if n]
    lines, i = [], 0
    for s in sizes:
        lines.append(out[i:i + s])
        i += s
    for li, ln in enumerate(lines):
        for j, p in enumerate(ln):
            p["depth"] = li / (len(lines) - 1) if len(lines) > 1 else 0.5
            p["lat"] = j / (len(ln) - 1) if len(ln) > 1 else 0.5
            p["line"] = li
    return {"lines": lines}


def lu_opponents(p: dict, opp: dict) -> list:
    L = opp["lines"]
    if not L:
        return []
    if p["line"] == 0:
        pool = [q for i, ln in enumerate(L) if i > 0 and ln[0]["depth"] > 0.5 for q in ln]
        if not pool:
            pool = L[-1]
    elif p["depth"] > 0.5:
        pool = L[0]
    else:
        want = 1 - p["depth"]
        pool = L[0]
        for ln in L:
            if abs(ln[0]["depth"] - want) < abs(pool[0]["depth"] - want):
                pool = ln
    if not pool:
        return []
    target = 1 - p["lat"]
    best = min(abs(q["lat"] - target) for q in pool)
    return [q for q in pool if abs(q["lat"] - target) <= best + 0.1][:2]


# matchupIndex: built once per payload, over every fixture in it.
def matchup_index(payload: dict) -> dict:
    conceded: dict = {}
    own: dict = {}
    covered = {"conceded": {}, "own": {}}
    seen = set()
    for fx in payload.get("fixtures") or []:
        if not isinstance(fx.get("players"), list):
            continue
        for ti, records in enumerate(fx["players"]):
            teams = fx.get("teams") or []
            team = teams[ti] if ti < len(teams) else None
            if not team or team.get("id") is None:
                continue
            all_recs = fx.get("records") or []
            by_match = {m.get("id"): m for m in ((all_recs[ti] if ti < len(all_recs) else None) or [])}
            for r in records or []:
                if truthy(r.get("former_club")) or truthy(r.get("club")):
                    continue
                m = by_match.get(r.get("match_id"))
                if not m or m.get("opponent_id") is None:
                    continue
                who = r.get("player_id") if r.get("player_id") is not None else r.get("player")
                key = f"{js_str(r.get('match_id'))}|{js_str(who)}"
                if key in seen:
                    continue
                seen.add(key)
                pos = r.get("position") or "?"
                own.setdefault(team["id"], {}).setdefault(pos, []).append(r)
                conceded.setdefault(m["opponent_id"], {}).setdefault(pos, []).append(r)
                covered["own"].setdefault(team["id"], set()).add(r.get("match_id"))
                covered["conceded"].setdefault(m["opponent_id"], set()).add(r.get("match_id"))
    return {"conceded": conceded, "own": own, "covered": covered}


def matchup_profile(idx: dict, fx: dict, opp_index: int, player_pos: str, stat: str,
                    line: float, window: list):
    pairing = MATCHUP_PAIRING.get(stat)
    teams = fx.get("teams") or []
    opp = teams[opp_index] if opp_index < len(teams) else None
    if not pairing or not opp or opp.get("id") is None:
        return None
    pos = pairing["positions"].get(player_pos) if pairing["mode"] == "own" else player_pos
    if not pos or pos not in POSITION_NAME:
        return None
    source = idx[pairing["mode"]]
    pool = source.get(opp["id"], {}).get(pos, [])
    window_ids = {m.get("id") for m in window}
    with_data = idx["covered"][pairing["mode"]].get(opp["id"], set())
    covered = sum(1 for i in window_ids if i in with_data)
    in_window = [g for g in pool if g.get("match_id") in window_ids]
    gated = any((g.get("minutes") or 0) > 0 for g in in_window)
    n = hits = 0
    total = minutes = 0
    matches = set()
    for g in in_window:
        if gated:
            if (g.get("minutes") or 0) < MIN_MINUTES:
                continue
        elif not (g.get("stats") or {}):
            continue
        v = (g.get("stats") or {}).get(pairing["stat"])
        if v is None and pairing["stat"] in ZERO_FILL:
            v = 0
        if v is None:
            continue
        n += 1
        total += v
        minutes += g.get("minutes") or 0
        if v > line:
            hits += 1
        matches.add(g.get("match_id"))
    rate = ((total / minutes) * 90 if minutes > 0 else total / n) if n else None
    return {"against": POSITION_NAME[pos], "mode": pairing["mode"], "stat": pairing["stat"],
            "n": n, "hits": hits, "matches": len(matches),
            "share": hits / n if n else None, "rate": rate,
            "unit": "per 90" if minutes > 0 else "per game",
            "covered": covered, "window": len(window),
            "thin": len(matches) < MATCHUP_MIN_MATCHES}


# ------------------------------------------------------------------ the output

_INDEXES: dict = {}


def fixture_lines(payload: dict, index: int) -> dict:
    """Everything the Line-ups tab's player lines show for one fixture."""
    key = id(payload)
    if key not in _INDEXES:
        _INDEXES.clear()
        _INDEXES[key] = matchup_index(payload)
    F = Fixture(payload, index, _INDEXES[key])
    fx, st = F.fx, F.state
    teams = [t["name"] for t in fx["teams"]]
    squads = F.squads()
    has_ball = truthy(st["teams"][0]["poss"]) and truthy(st["teams"][1]["poss"])

    dom = 0 if st["poss"][0] >= st["poss"][1] else 1
    if not has_ball:
        script = "No possession record for one side, so only the fitted ratings are used."
    elif abs(st["poss"][0] - 50) < 6:
        script = "Even on the ball. Player numbers move little from their usual."
    else:
        script = (f"{teams[dom]} expected to have the ball. Their shots and fouls won go up; "
                  f"{teams[1 - dom]}'s tackles and fouls committed go up, and the reverse for each.")

    def factor_of(x):
        g = x["g"]
        return {"avg": x["avg"], "adjusted_avg": x["mu"], "factor": g["f"], "factor_fitted": g["mf"],
                "factor_ball": g["pf"], "team_usual": g["usual"], "team_projected": g["projTeam"]}

    out_markets = {}
    for stat, lines in GS_MARKETS.items():
        rows, against = F.rows(stat, lines, squads)
        shown, works = [], []
        for j, x in enumerate(rows):
            b = x["best"]
            pos, mu = F.matchup(x["t"], x["name"], stat, b["L"])
            shown.append({"player": x["name"], "side": x["t"], "team": teams[x["t"]], "position": pos,
                          "line": b["L"], "k": b["k"], "n": b["n"], "chance": b["p"], "record": b["rec"],
                          **factor_of(x), "on_page": j < PAGE_ROWS, "matchup": mu})
        for j, x in enumerate(against):
            pos, mu = F.matchup(x["t"], x["name"], stat, x["L"])
            works.append({"player": x["name"], "side": x["t"], "team": teams[x["t"]], "position": pos,
                          "line": x["L"], "k": x["k"], "n": x["n"], "chance": x["p"],
                          **factor_of(x), "on_page": j < PAGE_AGAINST, "matchup": mu})
        out_markets[stat] = {"lines": shown, "works_against": works}

    pairs = F.pairs()
    if pairs is not None:
        pairs = [{"score": x["score"], "side": x["t"], "player": x["p"], "opponent": x["o"],
                  "player_fouled": x["a"], "opponent_fouls": x["b"], "on_page": j < PAGE_PAIRS}
                 for j, x in enumerate(p for p in pairs if p["score"] >= 0.6)]

    meta = fx["fixture"]
    kickoff = meta.get("kickoff")
    return {
        "event": meta["id"],
        "home": meta.get("home"),
        "away": meta.get("away"),
        "competition": meta.get("competition"),
        "kickoff": kickoff,
        "kickoff_utc": (datetime.fromtimestamp(kickoff, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                        if kickoff else None),
        "xi": squads["source"].split(" XI")[0].split(" (")[0],
        "xi_label": squads["source"],
        "squads": squads["sides"],
        "card": {
            "teams": [{"name": teams[t], "tier": st["tiers"][t], "n": st["teams"][t]["n"],
                       "possession": st["teams"][t]["poss"], "xg": st["teams"][t]["xg"],
                       "xga": st["teams"][t]["xga"]} for t in (0, 1)],
            "possession": st["poss"] if has_ball else None,
            "projected": {k: [st["proj"][s][0], st["proj"][s][1]]
                          for k, s in PROJECTED if st["proj"].get(s) is not None},
            "script": script,
        },
        "markets": out_markets,
        "foul_pairs": pairs,
    }


def payload_of(path: Path):
    """The dataset embedded in a built report, or None."""
    try:
        match = PAYLOAD.search(path.read_text(encoding="utf-8"))
        return json.loads(match.group(1)) if match else None
    except (OSError, json.JSONDecodeError) as exc:
        print(f"{path.name}: cannot read the payload ({exc})", file=sys.stderr)
        return None


def is_football(fx: dict) -> bool:
    return ((fx.get("fixture") or {}).get("sport") or "football") == "football"


def find(reports: Path, event: int | None, team: str | None, hours: float) -> list:
    """Matching fixtures, newest report first, each event once."""
    now = time.time()
    found, seen = [], set()
    files = sorted(reports.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        if event is not None:
            text_hint = f'"id": {event}'
            try:
                if text_hint not in path.read_text(encoding="utf-8"):
                    continue
            except OSError:
                continue
        payload = payload_of(path)
        if not payload:
            continue
        for i, fx in enumerate(payload.get("fixtures") or []):
            meta = fx.get("fixture") or {}
            if not is_football(fx) or meta.get("id") in seen:
                continue
            if event is not None and meta.get("id") != event:
                continue
            if team is not None:
                names = [t.get("name", "") for t in fx.get("teams") or []]
                if not any(team.casefold() in n.casefold() for n in names):
                    continue
                ko = meta.get("kickoff") or 0
                if not now <= ko <= now + hours * 3600:
                    continue
            seen.add(meta.get("id"))
            row = fixture_lines(payload, i)
            row["report"] = path.name
            found.append(row)
    found.sort(key=lambda r: r["kickoff"] or 0)
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="The Line-ups tab's player lines as JSON. Reads only.")
    who = ap.add_mutually_exclusive_group(required=True)
    who.add_argument("--event", type=int, help="SofaScore event id")
    who.add_argument("--team", help="any part of a team name, e.g. Villa")
    ap.add_argument("--hours", type=float, default=168,
                    help="with --team: kick-offs from now to this many hours ahead (default 168)")
    ap.add_argument("--reports", type=Path, default=REPORTS, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    fixtures = find(args.reports, args.event, args.team, args.hours)
    json.dump({"fixtures": fixtures}, sys.stdout, indent=1, ensure_ascii=False)
    sys.stdout.write("\n")
    if not fixtures:
        print("no matching football fixture in reports/", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
