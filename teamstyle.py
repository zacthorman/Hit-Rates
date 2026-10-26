"""
Team style, tactics and shape features for the team-stats model, from cache/.

    import teamstyle
    S = teamstyle.State.from_cache()                 # replay every cached match once
    rows = S.rows                                    # one pre-kick-off row per team per match (training)
    x = S.features_for(team, opp, home, f_own, f_opp)  # the same row for an upcoming match (live)

One module for training, the weekly retrain and the page, so the three can
never compute a feature differently (the usfeatures.py pattern). Everything
a row holds was known before kick-off: each side's last 10 matches with
statistics, a simple Elo over every match in the cache, and the formations
(tonight's from the line-up, which is known an hour before kick-off).

Features, per side and for the opponent (prefix opp_ / ok_):
  own_<stat>, conc_<stat>   last-10 average of the stat for and against
  k_ppda      opponent passes per defensive action (tackles + interceptions + fouls)
  k_direct    long balls per pass        k_territory  share of final-third entries
  k_cross / k_cross_allowed, k_box / k_box_allowed (touches in the box),
  k_poss, k_dribbles, k_fouls, k_xg / k_xga, k_bigch / k_bigch_allowed
  s_back, s_pivot, s_attmid, s_front, s_back3, s_central_mid  tonight's shape
  x_*         the clashes: predicted possession and the ball ratio, press
              against build-up, crosses against crosses allowed, box against
              box allowed, dribblers against foul rate, pivot against
              attacking midfielders
"""
from __future__ import annotations

import glob
import json
import math
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"

STATS = ["Total shots", "Shots on target", "Corner kicks", "Fouls", "Total tackles", "Yellow cards",
         "Clearances", "Big chances", "Offsides", "Goalkeeper saves"]
RAW = ["Ball possession", "Expected goals", "Big chances", "Total shots", "Shots on target",
       "Corner kicks", "Fouls", "Passes", "Tackles", "Free kicks", "Yellow cards", "Red cards",
       "Touches in penalty area", "Fouled in final third", "Final third entries", "Long balls",
       "Crosses", "Dribbles", "Interceptions", "Recoveries", "Clearances", "Total tackles",
       "Duels", "Accurate passes", "Offsides", "Throw-ins", "Goal kicks", "Shots inside box",
       "Goalkeeper saves"]
NAN = float("nan")


def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", str(v))
    return float(m.group(1)) if m else None


def _mean(xs, need=1):
    xs = [x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    return sum(xs) / len(xs) if len(xs) >= need else NAN


def shape(formation: str) -> dict:
    sizes = [int(x) for x in str(formation or "").split("-") if x.isdigit()]
    n = len(sizes)
    if not sizes:
        return {k: NAN for k in ("back", "nlines", "pivot", "attmid", "front", "back3", "central_mid")}
    pivot = sizes[1] if n >= 4 else (sizes[1] if n == 3 else NAN)
    if n == 3 and sizes[1] == 3:
        pivot = 1
    if n == 3 and sizes[1] == 5:
        pivot = 1
    if n >= 4 and sizes[0] == 3 and sizes[1] == 4:
        pivot = 2
    attmid = sizes[2] if n >= 4 else NAN
    central = (0 if math.isnan(pivot) else pivot) + (attmid if not math.isnan(attmid) and attmid <= 3 else 0)
    return {"back": sizes[0], "nlines": n, "pivot": pivot, "attmid": attmid, "front": sizes[-1],
            "back3": float(sizes[0] == 3), "central_mid": central}


class ShapeError(ValueError):
    """A cached file is not the shape this parser knows. Raised, never skipped:
    a silently empty parse trains the weekly model on nothing and looks fine."""


def _read(path) -> object:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as exc:
        raise ShapeError(f"{path}: not JSON ({exc})") from exc


def _error_body(d) -> bool:
    """SofaScore's {"error": {...}} body, cached before sofascore_api learned to
    drop it: the match has no such data, which is not a shape fault."""
    return isinstance(d, dict) and set(d) == {"error"}


def _check_event(e, path):
    if not isinstance(e, dict):
        raise ShapeError(f"{path}: event is {type(e).__name__}, not an object")
    for k in ("id", "startTimestamp", "homeTeam", "awayTeam", "status"):
        if k not in e:
            raise ShapeError(f"{path}: event {e.get('id')} has no {k!r}")
    for k in ("homeTeam", "awayTeam"):
        if not isinstance(e[k], dict) or "id" not in e[k]:
            raise ShapeError(f"{path}: event {e['id']} {k} has no id")


def parse_statistics(d, path="statistics") -> dict | None:
    """{stat name: (home, away)} for the whole match, None for an error body."""
    if _error_body(d):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("statistics"), list):
        raise ShapeError(f"{path}: expected {{'statistics': [...]}}, got {_describe(d)}")
    per = next((p for p in d["statistics"] if isinstance(p, dict) and p.get("period") == "ALL"), None)
    if per is None:
        if not d["statistics"]:
            return None  # an empty list: the match has no statistics
        raise ShapeError(f"{path}: no 'ALL' period among {[p.get('period') for p in d['statistics'] if isinstance(p, dict)]}")
    if not isinstance(per.get("groups"), list):
        raise ShapeError(f"{path}: period ALL has no 'groups' list")
    items = {}
    for g in per["groups"]:
        its = g.get("statisticsItems") if isinstance(g, dict) else None
        if not isinstance(its, list):
            raise ShapeError(f"{path}: a group has no 'statisticsItems' list")
        for it in its:
            if not isinstance(it, dict) or "name" not in it or not ({"homeValue", "awayValue"} & set(it)):
                raise ShapeError(f"{path}: statistics item {_describe(it)} has no name or values")
            items.setdefault(it["name"], (_num(it.get("homeValue")), _num(it.get("awayValue"))))
    return items


def parse_lineups(d, path="lineups") -> list[str] | None:
    """[home formation, away formation] ('' when not given), None for an error body."""
    if _error_body(d):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("home"), dict) or not isinstance(d.get("away"), dict):
        raise ShapeError(f"{path}: expected {{'home': {{...}}, 'away': {{...}}}}, got {_describe(d)}")
    out = []
    for side in ("home", "away"):
        f = d[side].get("formation")
        if f is not None and not isinstance(f, str):
            raise ShapeError(f"{path}: {side} formation is {type(f).__name__}")
        out.append(f or "")
    return out


def _describe(d) -> str:
    return f"keys {sorted(d)[:8]}" if isinstance(d, dict) else type(d).__name__


def load(cache: Path = CACHE) -> list[dict]:
    """Every finished football match with statistics and line-ups, oldest first.

    A match without its statistics or line-up file is skipped (not fetched
    yet); a file in a shape not met before raises ShapeError naming it."""
    ev = {}
    files = glob.glob(str(cache / "team_*_events_last_*.json"))
    for f in files:
        d = _read(f)
        if _error_body(d):
            continue
        if not isinstance(d, dict) or not isinstance(d.get("events"), list):
            raise ShapeError(f"{f}: expected {{'events': [...]}}, got {_describe(d)}")
        for e in d["events"]:
            _check_event(e, f)
            ev[e["id"]] = e
    if files and not ev:
        raise ShapeError(f"{cache}: {len(files)} team event files and not one event in them")
    out = []
    for mid, e in ev.items():
        t = e.get("tournament") or {}
        if ((t.get("category") or {}).get("sport") or {}).get("slug") != "football":
            continue
        if (e.get("status") or {}).get("type") != "finished":
            continue
        lf, sf = cache / f"event_{mid}_lineups.json", cache / f"event_{mid}_statistics.json"
        if not (lf.exists() and sf.exists()):
            continue
        form, items = parse_lineups(_read(lf), lf), parse_statistics(_read(sf), sf)
        if form is None or items is None:
            continue
        hs, as_ = (e.get("homeScore") or {}).get("current"), (e.get("awayScore") or {}).get("current")
        out.append({"match": mid, "ts": e["startTimestamp"], "home": e["homeTeam"]["id"], "away": e["awayTeam"]["id"],
                    "hg": hs, "ag": as_, "items": items, "form": form})
    out.sort(key=lambda m: (m["ts"], m["match"]))
    return out


class State:
    def __init__(self):
        self.hist = defaultdict(list)       # team -> list of {f_*, a_*}
        self.elo = defaultdict(lambda: 1500.0)
        self.rows: list[dict] = []

    @classmethod
    def from_cache(cls, cache: Path = CACHE, keep_rows: bool = True):
        S = cls()
        for m in load(cache):
            S.add(m, keep_rows)
        return S

    def _side(self, team):
        h = self.hist[team][-10:]
        d = {"n": len(h)}
        for s in STATS:
            d["own_" + s] = _mean([x.get("f_" + s) for x in h], 5)
            d["conc_" + s] = _mean([x.get("a_" + s) for x in h], 5)
        m = lambda k: _mean([x.get(k) for x in h])  # noqa: E731
        defacts = m("f_Total tackles") + m("f_Interceptions") + m("f_Fouls")
        d.update({
            "k_ppda": m("a_Passes") / defacts if defacts and not math.isnan(defacts) and defacts > 0 else NAN,
            "k_direct": m("f_Long balls") / m("f_Passes") if m("f_Passes") else NAN,
            "k_cross": m("f_Crosses"), "k_cross_allowed": m("a_Crosses"),
            "k_territory": (m("f_Final third entries") / (m("f_Final third entries") + m("a_Final third entries"))
                            if m("f_Final third entries") and m("a_Final third entries") else NAN),
            "k_box": m("f_Touches in penalty area"), "k_box_allowed": m("a_Touches in penalty area"),
            "k_poss": m("f_Ball possession"), "k_dribbles": m("f_Dribbles"), "k_fouls": m("f_Fouls"),
            "k_xg": m("f_Expected goals"), "k_xga": m("a_Expected goals"),
            "k_bigch": m("f_Big chances"), "k_bigch_allowed": m("a_Big chances")})
        return d

    def features_for(self, team, opp, home: bool, form_own: str, form_opp: str, elo_diff=None) -> dict:
        me, op = self._side(team), self._side(opp)
        x = {"home": float(bool(home)), "n": me["n"]}
        for k, v in me.items():
            if k.startswith(("own_", "conc_")):
                x[k] = v
            elif k.startswith("k_"):
                x["tk_" + k] = v
        for k, v in op.items():
            if k.startswith(("own_", "conc_")):
                x["opp_" + k] = v
            elif k.startswith("k_"):
                x["ok_" + k] = v
        for k, v in shape(form_own).items():
            x["tk_s_" + k] = v
        for k, v in shape(form_opp).items():
            x["ok_s_" + k] = v
        if elo_diff is None:
            eh, ea = self.elo[team], self.elo[opp]
            elo_diff = eh - ea
        x["elo_diff"] = elo_diff

        def lg(p):
            p = min(85, max(15, p)) / 100
            return math.log(p / (1 - p))
        a, b = x["tk_k_poss"], x["ok_k_poss"]
        if not (math.isnan(a) or math.isnan(b)) and a > 0 and b > 0:
            lo = 0.85 * (lg(a) - lg(b)) + (0.06 if home else -0.06)
            x["x_poss_pred"] = 100 / (1 + math.exp(-lo))
            x["x_ball"] = x["x_poss_pred"] / a
        else:
            x["x_poss_pred"] = x["x_ball"] = NAN
        ok = lambda v: v is not None and not math.isnan(v) and v > 0  # noqa: E731
        x["x_press_v_build"] = (1 / x["tk_k_ppda"]) * (1 - x["ok_k_direct"] * 10) if ok(x["tk_k_ppda"]) else NAN
        x["x_their_press_v_build"] = (1 / x["ok_k_ppda"]) * (1 - x["tk_k_direct"] * 10) if ok(x["ok_k_ppda"]) else NAN
        x["x_cross_v"] = x["tk_k_cross"] * x["ok_k_cross_allowed"]
        x["x_box_v"] = x["tk_k_box"] * x["ok_k_box_allowed"]
        x["x_drib_v_fouls"] = x["ok_k_dribbles"] * x["tk_k_fouls"]
        x["x_pivot_v_attmid"] = x["tk_s_pivot"] - x["ok_s_attmid"]
        x["x_central"] = x["tk_s_central_mid"] - x["ok_s_central_mid"]
        return x

    def add(self, m: dict, keep_rows: bool = True):
        items = m["items"]
        if keep_rows:
            for i, (team, opp) in enumerate(((m["home"], m["away"]), (m["away"], m["home"]))):
                x = self.features_for(team, opp, i == 0, m["form"][i], m["form"][1 - i])
                x.update({"match": m["match"], "ts": m["ts"], "team": team, "opp": opp})
                for s in STATS:
                    v = items.get(s)
                    x["y_" + s] = v[i] if v else None
                self.rows.append(x)
        for i, team in enumerate((m["home"], m["away"])):
            rec = {}
            for k in RAW:
                v = items.get(k)
                rec["f_" + k] = v[i] if v else None
                rec["a_" + k] = v[1 - i] if v else None
            self.hist[team].append(rec)
        hg, ag = m["hg"], m["ag"]
        if hg is not None and ag is not None:
            h, a = self.elo[m["home"]], self.elo[m["away"]]
            e = 1 / (1 + 10 ** ((a - h - 60) / 400))
            res = 1.0 if hg > ag else 0.5 if hg == ag else 0.0
            k = 20 * (1 + abs(hg - ag)) ** 0.5
            self.elo[m["home"]] += k * (res - e)
            self.elo[m["away"]] -= k * (res - e)
