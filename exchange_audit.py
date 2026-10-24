"""
Who has been right, the site or Betfair? A read-only audit of exchange_log.json.

    python exchange_audit.py                # print every table as Markdown
    python exchange_audit.py --cache DIR    # read SofaScore copies from DIR too

exchange_eval.py keeps the log and tunes the blend from it. This file only
reads: it changes no price, weight or betting rule, and writes nothing unless
asked to (--out). It does four things.

1. Settles every logged price it can, from every place the repo keeps a
   result, and says where each result came from:

     log        the result exchange_eval.py settle wrote into the log
     best_bets  the same bet (or another line on the same stat) in best_bets.json
     pplog      Paddy Power's player-line log, pplog/*.jsonl, where present
     cache      SofaScore's own match statistics and line-ups, read from
                cache/ or cache_backtest.tar.zst, the same numbers besttrack
                settles from

   Player lines the log settled at 0 are a known hazard: before 20 Oct the
   settler could read a line-up saved an hour before kick-off, with no
   statistics in it, and grade every player a zero (see besttrack
   _player_value). So a player loss at 0 counts only when a post-match source
   agrees. To keep that even-handed, every player line, won or lost, needs a
   post-match source to be scored; the rest are set aside. Any source
   that contradicts another is reported, and the post-match copy wins.

2. Scores four chances on the same settled bets: the site's model, the model
   with its usual lean off ("anchored"), Betfair's own chance with the margin
   off ("market"), and the blend the site prices with. Log loss, Brier and
   calibration, overall, by sport, by market and by how far apart the site and
   Betfair were. Over and under on one line are the same bet seen twice, so
   each line is scored once. Intervals are bootstrapped by fixture, because
   lines in one match win and lose together.

3. Tests the value the page shows. A back bet at price b wins (b - 1)(1 - c)
   after commission c, so it breaks even at a chance of 1 / (1 + (b - 1)(1 - c)),
   higher than 1 / b and higher still than the mid-price chance; the lay side
   of the spread is never a price you can back at. Every bet the page called
   value is backed at the back price on offer then, and the return set against
   what the site said it would make and what Betfair's own chance said.

4. Asks whether a rule for trusting the site against the exchange beats simply
   taking Betfair's chance, out of sample (fixtures held out in folds).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import tarfile
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = HERE / "exchange_log.json"
BEST = HERE / "best_bets.json"
PPLOG = HERE / "pplog"
CACHE = HERE / "cache"
TARBALL = HERE / "cache_backtest.tar.zst"

COMMISSION = 0.05
SHOWN = 0.005         # the page prints +n% value above this (make_index.py)
CHANCES = ("model", "anchored", "market", "blend")
NAMES = {"model": "Site model", "anchored": "Site, lean off", "market": "Betfair",
         "blend": "Blend (used)"}
GAP_BANDS = ((0.0, 0.03), (0.03, 0.06), (0.06, 0.10), (0.10, 0.15), (0.15, 1.01))
BOOT = 2000
SEED = 20261022
EPS = 1e-4


# ------------------------------------------------------------ small maths

def clip(p: float) -> float:
    return min(max(p, EPS), 1 - EPS)


def logit(p: float) -> float:
    p = clip(p)
    return math.log(p / (1 - p))


def sig(z: float) -> float:
    return 1 / (1 + math.exp(-z))


def logloss(p: float, won: bool) -> float:
    p = clip(p)
    return -math.log(p if won else 1 - p)


def brier(p: float, won: bool) -> float:
    return (p - (1.0 if won else 0.0)) ** 2


def back_return(back: float, won: bool, c: float = COMMISSION) -> float:
    """Profit on one unit backed at `back`, commission on the winnings."""
    return (back - 1) * (1 - c) if won else -1.0


def break_even(back: float, c: float = COMMISSION) -> float:
    """The chance a back bet needs to break even after commission."""
    return 1 / (1 + (back - 1) * (1 - c))


def ev(p: float, back: float, c: float = COMMISSION) -> float:
    """Expected profit per unit at `back` if the true chance is p."""
    return p * (back - 1) * (1 - c) - (1 - p)


def blend(market: float, model: float, w: float) -> float:
    """w on the market, 1 - w on the model, on the log-odds scale (weekend._exchange)."""
    return sig(w * logit(market) + (1 - w) * logit(model))


def cluster_boot(rows: list, stat, key=lambda r: r["event_id"], n: int = BOOT, seed: int = SEED):
    """Percentile 95% interval of stat(rows), resampling whole fixtures."""
    groups = defaultdict(list)
    for r in rows:
        groups[key(r)].append(r)
    gs = list(groups.values())
    if len(gs) < 2:
        return None, None
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        sample = [r for _ in gs for r in gs[rng.randrange(len(gs))]]
        v = stat(sample)
        if v is not None:
            vals.append(v)
    vals.sort()
    if not vals:
        return None, None
    return vals[int(0.025 * len(vals))], vals[min(len(vals) - 1, int(0.975 * len(vals)))]


def logistic_fit(xs: list[float], ys: list[bool], iters: int = 50):
    """Intercept and slope of P(win) = sig(a + b x), by Newton's method."""
    a, b = 0.0, 1.0
    for _ in range(iters):
        ga = gb = haa = hab = hbb = 0.0
        for x, y in zip(xs, ys):
            p = sig(a + b * x)
            d = (1.0 if y else 0.0) - p
            w = p * (1 - p)
            ga += d
            gb += d * x
            haa += w
            hab += w * x
            hbb += w * x * x
        det = haa * hbb - hab * hab
        if abs(det) < 1e-12:
            break
        da = (hbb * ga - hab * gb) / det
        db = (haa * gb - hab * ga) / det
        a += da
        b += db
        if abs(da) + abs(db) < 1e-9:
            break
    return a, b


# --------------------------------------------------------------- sources

def line_key(r: dict) -> tuple:
    """One bet line, either side: (event, who, stat, period, line)."""
    return (int(r["event_id"]), r.get("player") or r.get("team"), r["stat"],
            r.get("period") or "ALL", float(r["line"]))


def stat_key(r: dict) -> tuple:
    """The quantity a line settles on: (event, who, stat, period)."""
    return line_key(r)[:4]


def grade(value: float, line: float, over: bool) -> str:
    return "win" if (value > line if over else value < line) else "lose"


def best_bets_values(path: Path = BEST) -> dict:
    """{stat_key: (value or 'void')} from settled legs in best_bets.json."""
    out = {}
    try:
        tickets = json.loads(path.read_text())
    except (OSError, ValueError):
        return out
    for t in tickets:
        for leg in t.get("legs") or []:
            if leg.get("event_id") is None or leg.get("line") is None:
                continue
            k = stat_key(leg)
            if leg.get("result") == "void":
                out.setdefault(k, "void")
            elif leg.get("result") in ("win", "lose") and leg.get("value") is not None:
                out[k] = float(leg["value"])
    return out


def pplog_values(folder: Path = PPLOG) -> dict:
    """{stat_key: value} from Paddy Power's player-line log, where it exists."""
    out = {}
    for f in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
        for line in f.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("result") in ("win", "lose") and r.get("value") is not None:
                out[(int(r["event_id"]), r["player"], r["stat"], "ALL")] = float(r["value"])
    return out


def _read_cache_files(eids: set, folder: Path = CACHE, tarball: Path = TARBALL) -> dict:
    """{(event_id, 'lineups'|'statistics'): json} from cache/ and the tarball."""
    out = {}
    if folder.is_dir():
        for eid in eids:
            for kind in ("lineups", "statistics"):
                f = folder / f"event_{eid}_{kind}.json"
                if f.exists():
                    try:
                        out[(eid, kind)] = json.loads(f.read_text())
                    except ValueError:
                        pass
    if tarball.exists():
        try:
            import zstandard
        except ImportError:
            return out
        with open(tarball, "rb") as fh, zstandard.ZstdDecompressor().stream_reader(fh) as rd:
            with tarfile.open(fileobj=rd, mode="r|") as tf:
                for m in tf:
                    parts = m.name.rsplit("/", 1)[-1].removesuffix(".json").split("_")
                    if len(parts) != 3 or parts[0] != "event" or not m.isfile():
                        continue
                    try:
                        eid = int(parts[1])
                    except ValueError:
                        continue
                    if eid in eids and parts[2] in ("lineups", "statistics") and (eid, parts[2]) not in out:
                        try:
                            out[(eid, parts[2])] = json.loads(tf.extractfile(m).read())
                        except ValueError:
                            pass
    return out


def lineups_post_match(lu: dict | None) -> bool:
    """A line-up copy taken after the match: somebody has minutes in it."""
    for side in ("home", "away"):
        for p in (lu or {}).get(side, {}).get("players", []) or []:
            if (p.get("statistics") or {}).get("minutesPlayed"):
                return True
    return False


def player_value(lu: dict, name: str):
    """A player's stat line from a post-match line-up: dict, 'dnp', or None."""
    import hitrates
    for side in ("home", "away"):
        for p in (lu or {}).get(side, {}).get("players", []) or []:
            if (p.get("player") or {}).get("name") == name:
                st = p.get("statistics") or {}
                if not st.get("minutesPlayed"):
                    return "dnp"
                return hitrates._player_stat_values(st, zero_fill=hitrates.PLAYER_ZERO_FILL) or "dnp"
    return None


def goals_from_lineups(lu: dict):
    """(home, away) goals: each side's scorers plus the other side's own goals."""
    g = {"home": 0, "away": 0}
    og = {"home": 0, "away": 0}
    for side in ("home", "away"):
        for p in (lu or {}).get(side, {}).get("players", []) or []:
            st = p.get("statistics") or {}
            g[side] += int(st.get("goals") or 0)
            og[side] += int(st.get("ownGoals") or 0)
    return g["home"] + og["away"], g["away"] + og["home"]


def cache_values(log: dict, files: dict) -> dict:
    """{stat_key: value or 'dnp'} recomputed from post-match cache copies."""
    import besttrack
    import hitrates
    out = {}
    for r in log.values():
        eid = int(r["event_id"])
        lu = files.get((eid, "lineups"))
        if not lineups_post_match(lu):
            continue
        k = stat_key(r)
        if r.get("player"):
            v = player_value(lu, r["player"])
            if v == "dnp":
                out[k] = "dnp"
            elif isinstance(v, dict):
                out[k] = float(v.get(r["stat"], 0.0))
            continue
        if r.get("sport") != "football":
            continue
        stats = hitrates.extract_match_stats(files.get((eid, "statistics")))
        hg, ag = goals_from_lineups(lu)
        home = (r.get("fixture") or "").split(" v ")[0]
        ev_ = {"homeTeam": {"name": home}, "homeScore": {"current": hg}, "awayScore": {"current": ag}}
        if r["stat"] != "Goals" and not stats:
            continue
        try:
            v = besttrack._team_value(dict(r), ev_, stats or {})
        except Exception:
            v = None
        if v is not None:
            out[k] = float(v)
    return out


def resolve(log: dict, sources: dict) -> dict:
    """Settle every record from every source. Returns {key: info} where info
    has result, value, the sources that agree, any conflict, and whether the
    record is usable for scoring ("ok")."""
    out = {}
    for key, r in log.items():
        k = stat_key(r)
        line, over = float(r["line"]), bool(r["over"])
        seen = {}
        if r.get("result") == "void":
            seen["log"] = "void"
        elif r.get("result") in ("win", "lose") and r.get("value") is not None:
            seen["log"] = float(r["value"])
        for name, vals in sources.items():
            if k in vals:
                v = vals[k]
                seen[name] = "void" if v in ("void", "dnp") else v
        graded = {s: ("void" if v == "void" else grade(v, line, over)) for s, v in seen.items()}
        post = [s for s in ("cache", "best_bets", "pplog") if s in seen]
        info = {"sources": sorted(seen), "conflict": None, "result": None, "value": None,
                "ok": False, "why": ""}
        distinct = {graded[s] for s in seen}
        if len(distinct) > 1:
            info["conflict"] = {s: (seen[s], graded[s]) for s in seen}
        if not seen:
            info["why"] = "open" if r.get("result") is None else "no source"
        else:
            # Post-match copies first (cache, then best_bets, then pplog);
            # the log only where nothing else saw the bet.
            pick = post[0] if post else "log"
            info["result"], info["value"] = graded[pick], seen[pick]
            info["picked"] = pick
            if info["result"] == "void":
                info["why"] = "void"
            elif pick == "log" and r.get("player"):
                # A player line only the log saw. Its zeros may be the
                # pre-match line-up hazard, and keeping its wins while
                # dropping its zeros would tilt every player market towards
                # winning, so neither is scored. Which fixtures have a
                # post-match copy has nothing to do with how the bet landed.
                info["why"] = ("unverified player zero" if seen["log"] == 0.0
                               else "unverified player line")
            else:
                info["ok"] = True
                info["why"] = "verified" if post else "log only"
        out[key] = info
    return out


def load_sources(log: dict, cache: Path = CACHE, tarball: Path = TARBALL) -> dict:
    eids = {int(r["event_id"]) for r in log.values()}
    files = _read_cache_files(eids, cache, tarball)
    return {"cache": cache_values(log, files), "best_bets": best_bets_values(), "pplog": pplog_values()}


# -------------------------------------------------------------- the rows

def rows_for(log: dict, res: dict, snap: str = "first", one_side: bool = True) -> list[dict]:
    """Settled, usable records as flat rows; one side per line by default
    (over kept where both were logged)."""
    rows = []
    for key, r in log.items():
        info = res[key]
        if not info["ok"]:
            continue
        s = r.get(snap) or {}
        if s.get("market") is None:
            continue
        rows.append({"key": key, "line_key": line_key(r), "event_id": int(r["event_id"]),
                     "sport": r.get("sport"), "family": r.get("family"), "kind": r.get("kind"),
                     "mtype": r.get("mtype"), "stat": r.get("stat"), "player": bool(r.get("player")),
                     "over": bool(r["over"]), "won": info["result"] == "win", "kickoff": r.get("kickoff"),
                     "competition": r.get("competition"),
                     **{c: s.get(c) for c in CHANCES}, "back": s.get("back"), "lay": s.get("lay"),
                     "tight": s.get("tight"), "w": s.get("w"), "value": s.get("value"),
                     "disagree": s.get("disagree"), "matched": s.get("matched"),
                     "last_market": (r.get("last") or {}).get("market"), "seen": r.get("seen", 1),
                     "source": info.get("picked")})
    if one_side:
        by = {}
        for x in sorted(rows, key=lambda x: not x["over"]):
            by.setdefault(x["line_key"], x)
        rows = list(by.values())
    return rows


def gap(x: dict) -> float:
    """How far the site sat from Betfair: the anchored chance where there is
    one (what the page compares), else the raw model."""
    m = x["anchored"] if x["anchored"] is not None else x["model"]
    return m - x["market"]


# ---------------------------------------------------------------- scoring

def score(rows: list[dict], names=CHANCES) -> dict:
    out = {"n": len(rows), "fixtures": len({r["event_id"] for r in rows})}
    if not rows:
        return out
    out["landed"] = sum(r["won"] for r in rows) / len(rows)
    for c in names:
        ps = [(r[c], r["won"]) for r in rows if r.get(c) is not None]
        if len(ps) != len(rows):
            continue
        out[c] = {"logloss": sum(logloss(p, w) for p, w in ps) / len(ps),
                  "brier": sum(brier(p, w) for p, w in ps) / len(ps),
                  "said": sum(p for p, _ in ps) / len(ps)}
    return out


def paired(rows: list[dict], a: str, b: str, metric=logloss):
    """Mean of metric(a) - metric(b) per bet, with a fixture-bootstrap 95%
    interval. Negative means a scored better."""
    def stat(rs):
        if not rs:
            return None
        return sum(metric(r[a], r["won"]) - metric(r[b], r["won"]) for r in rs) / len(rs)
    lo, hi = cluster_boot(rows, stat)
    return stat(rows), lo, hi


def calibration_table(rows: list[dict], c: str, edges=(0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.0001)):
    out = []
    for lo, hi in zip(edges, edges[1:]):
        sel = [r for r in rows if lo <= r[c] < hi]
        if sel:
            out.append({"band": f"{lo:.0%}-{min(hi, 1):.0%}", "n": len(sel),
                        "said": sum(r[c] for r in sel) / len(sel),
                        "landed": sum(r["won"] for r in sel) / len(sel)})
    return out


def calibration_fit(rows: list[dict], c: str):
    """Calibration slope (1 is perfect, below 1 overconfident) and
    calibration-in-the-large (landed minus said)."""
    a, b = logistic_fit([logit(r[c]) for r in rows], [r["won"] for r in rows])
    big = sum(r["won"] for r in rows) / len(rows) - sum(r[c] for r in rows) / len(rows)
    lo, hi = cluster_boot(rows, lambda rs: logistic_fit([logit(r[c]) for r in rs],
                                                        [r["won"] for r in rs], iters=25)[1]
                          if len(rs) > 5 else None, n=500)
    return {"slope": b, "intercept": a, "large": big, "slope_lo": lo, "slope_hi": hi}


def gap_band(g: float) -> str:
    for lo, hi in GAP_BANDS:
        if lo <= abs(g) < hi:
            return f"{lo * 100:.0f}-{hi * 100:.0f} pts" if hi < 1 else f"{lo * 100:.0f}+ pts"
    return "?"


def direction(rows: list[dict]) -> dict:
    """When the site disagreed, who did the result side with? Share of the
    gap the outcome realised: mean(won - market) / mean(site - market), with
    the sign of each gap folded so that 1 means the site was right on
    average and 0 means Betfair was."""
    num = sum((1 if gap(r) > 0 else -1) * ((1.0 if r["won"] else 0.0) - r["market"]) for r in rows)
    den = sum(abs(gap(r)) for r in rows)
    sided = sum(1 for r in rows if (gap(r) > 0) == r["won"])
    return {"n": len(rows), "realised": num / den if den else None,
            "site_side": sided / len(rows) if rows else None}


# ------------------------------------------------------------------ value

def value_rows(log: dict, res: dict, snap: str = "first") -> list[dict]:
    """Every settled bet the page called value (both sides count: they are
    different bets), with the price it showed."""
    out = []
    for x in rows_for(log, res, snap, one_side=False):
        if x["value"] is not None and x["back"]:
            out.append(x)
    return out


def roi_block(rows: list[dict], c: float = COMMISSION) -> dict:
    if not rows:
        return {"n": 0}
    pnl = [back_return(r["back"], r["won"], c) for r in rows]
    mean = sum(pnl) / len(pnl)
    lo, hi = cluster_boot(rows, lambda rs: sum(back_return(r["back"], r["won"], c) for r in rs) / len(rs)
                          if rs else None)
    return {"n": len(rows), "fixtures": len({r["event_id"] for r in rows}),
            "won": sum(r["won"] for r in rows), "profit": sum(pnl), "roi": mean, "lo": lo, "hi": hi,
            "site_said": sum(r["value"] for r in rows) / len(rows),
            "betfair_said": sum(ev(r["market"], r["back"], c) for r in rows) / len(rows),
            "model_said": sum(ev(r["anchored"] if r["anchored"] is not None else r["model"], r["back"], c)
                              for r in rows) / len(rows),
            "hit": sum(r["won"] for r in rows) / len(rows),
            "need": sum(break_even(r["back"], c) for r in rows) / len(rows)}


def clv_block(rows: list[dict], c: float = COMMISSION) -> dict:
    """Value against the closing price: the back price taken, worth what at
    Betfair's last chance before kick-off? Needs no results."""
    sel = [r for r in rows if r.get("seen", 1) >= 2 and r.get("last_market")]
    if not sel:
        return {"n": 0}
    vals = [ev(r["last_market"], r["back"], c) for r in sel]
    moved = [logit(r["last_market"]) - logit(r["market"]) for r in sel]
    lo, hi = cluster_boot(sel, lambda rs: sum(ev(r["last_market"], r["back"], c) for r in rs) / len(rs)
                          if rs else None)
    return {"n": len(sel), "clv": sum(vals) / len(vals), "lo": lo, "hi": hi,
            "shortened": sum(1 for m in moved if m > 0.01) / len(sel),
            "drifted": sum(1 for m in moved if m < -0.01) / len(sel)}


def spread_check(log: dict, snap: str = "first") -> dict:
    """Is Betfair's chance where the spread says it should be? For two-way
    quotes with both prices. The lay price is the longer one, so the chance
    sits between 1/lay and 1/back before the margin comes off, and close to
    that band after it."""
    inside = near = total = 0
    widths = []
    for r in log.values():
        s = r.get(snap) or {}
        if r.get("kind") != "exchange" or not s.get("back") or not s.get("lay") or s.get("market") is None:
            continue
        if r["over"] is False and r.get("mtype") in ("CORNER_ODDS",):
            continue
        lo, hi = 1 / s["lay"], 1 / s["back"]
        total += 1
        widths.append(hi - lo)
        if lo - 1e-9 <= s["market"] <= hi + 1e-9:
            inside += 1
        elif lo - 0.02 <= s["market"] <= hi + 0.02:
            near += 1
    widths.sort()
    return {"n": total, "inside": inside, "near": near,
            "median_width": widths[len(widths) // 2] if widths else None}


# ------------------------------------------------------------------- rules

def fit_weight(rows: list[dict], site: str = "anchored", grid: int = 40) -> float:
    """The market weight w that minimises log loss of blend(market, site, w)."""
    def loss(w):
        return sum(logloss(blend(r["market"], r[site] if r[site] is not None else r["model"], w), r["won"])
                   for r in rows)
    return min((i / grid for i in range(grid + 1)), key=loss)


def cv_rules(rows: list[dict], folds: int = 5, seed: int = SEED) -> dict:
    """Out-of-sample log loss of candidate trust rules, folds by fixture."""
    events = sorted({r["event_id"] for r in rows})
    rng = random.Random(seed)
    rng.shuffle(events)
    fold_of = {e: i % folds for i, e in enumerate(events)}
    rules = {
        "Betfair only": lambda train: (lambda r: r["market"]),
        "Site model only": lambda train: (lambda r: r["model"]),
        "Site, lean off": lambda train: (lambda r: r["anchored"] if r["anchored"] is not None else r["model"]),
        "Blend as used": lambda train: (lambda r: r["blend"]),
        "Fixed 50/50": lambda train: (lambda r: blend(r["market"], _site(r), 0.5)),
        "One fitted weight": lambda train: (lambda w: lambda r: blend(r["market"], _site(r), w))(fit_weight(train)),
        "Weight by gap band": _by(lambda r: gap_band(gap(r))),
        "Weight by market": _by(lambda r: r["family"]),
    }
    out = {}
    for name, make in rules.items():
        per = []
        for k in range(folds):
            train = [r for r in rows if fold_of[r["event_id"]] != k]
            test = [r for r in rows if fold_of[r["event_id"]] == k]
            f = make(train)
            per.extend({"event_id": r["event_id"], "ll": logloss(f(r), r["won"]),
                        "ref": logloss(r["market"], r["won"])} for r in test)
        mean = sum(p["ll"] for p in per) / len(per)
        lo, hi = cluster_boot(per, lambda ps: sum(p["ll"] - p["ref"] for p in ps) / len(ps) if ps else None)
        out[name] = {"logloss": mean, "vs_betfair": mean - sum(p["ref"] for p in per) / len(per),
                     "lo": lo, "hi": hi, "n": len(per)}
    return out


def _site(r):
    return r["anchored"] if r["anchored"] is not None else r["model"]


def _by(group):
    def make(train):
        overall = fit_weight(train)
        groups = defaultdict(list)
        for r in train:
            groups[group(r)].append(r)
        # Shrink each group's weight to the pooled one, 30 pseudo-bets.
        ws = {g: (len(rs) * fit_weight(rs) + 30 * overall) / (len(rs) + 30) for g, rs in groups.items()}
        return lambda r: blend(r["market"], _site(r), ws.get(group(r), overall))
    return make


def fitted_back_margin(rows: list[dict]) -> float | None:
    """The margin in back-only prices that best fits the results: chance =
    (1 / back) / (1 + m)."""
    sel = [r for r in rows if r["back"] and r["kind"] == "back" and r["over"]]
    if not sel:
        return None
    return min((i / 100 for i in range(-20, 101)),
               key=lambda m: sum(logloss((1 / r["back"]) / (1 + m), r["won"]) for r in sel))


# ---------------------------------------------------------------- output

def pct(x, signed=False, d=1):
    if x is None:
        return "-"
    return f"{x * 100:+.{d}f}%" if signed else f"{x * 100:.{d}f}%"


def num(x, d=4, signed=False):
    if x is None:
        return "-"
    return f"{x:+.{d}f}" if signed else f"{x:.{d}f}"


def table(head: list[str], body: list[list]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" if i == 0 else "---:" for i in range(len(head))) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in body]
    return "\n".join(out)


def interval(lo, hi, f=pct, **kw):
    return "-" if lo is None else f"{f(lo, **kw)} to {f(hi, **kw)}"


def score_table(groups: list[tuple[str, list[dict]]], names=CHANCES) -> str:
    body = []
    for label, rows in groups:
        s = score(rows, names)
        if not s.get("n"):
            continue
        best = min((c for c in names if c in s), key=lambda c: s[c]["logloss"], default=None)
        d, lo, hi = paired(rows, "model", "market") if "model" in s and "market" in s else (None, None, None)
        body.append([label, s["n"], s["fixtures"], pct(s["landed"])]
                    + [num(s[c]["logloss"]) if c in s else "-" for c in names]
                    + [num(s[c]["brier"]) if c in s else "-" for c in ("model", "market", "blend")]
                    + [f"{num(d, signed=True)} ({interval(lo, hi, num, signed=True)})", NAMES.get(best, "-")])
    head = (["Group", "Lines", "Fixtures", "Landed"] + [f"LL {NAMES[c]}" for c in names]
            + ["Brier model", "Brier Betfair", "Brier blend", "Model minus Betfair LL (95%)", "Best"])
    return table(head, body)


def report(cache: Path = CACHE, tarball: Path = TARBALL) -> str:
    log = json.loads(LOG.read_text())
    sources = load_sources(log, cache, tarball)
    res = resolve(log, sources)
    parts = []
    add = parts.append

    # 1. matching
    why = Counter(i["why"] for i in res.values())
    add("### 1a. What happened to every logged price\n")
    add(table(["Status", "Records"], [[k, v] for k, v in why.most_common()] + [["Total", len(res)]]))
    src = Counter()
    for k, i in res.items():
        if i["ok"]:
            src[(log[k].get("player") is not None, tuple(s for s in i["sources"]))] += 1
    add("\n### 1b. Where the scored results came from\n")
    add(table(["Market side", "Sources that saw the result", "Records"],
              [["player" if p else "team", " + ".join(s), n] for (p, s), n in sorted(src.items(), key=lambda kv: -kv[1])]))
    conf = [(k, i) for k, i in res.items() if i["conflict"]]
    add("\n### 1c. Conflicts between sources\n")
    add(table(["Record", "What each source said (value, result)"],
              [[k.replace("|", " / "), "; ".join(f"{s}: {v} {g}" for s, (v, g) in i["conflict"].items())]
               for k, i in conf]) if conf else "None.")
    zero = [k for k, i in res.items() if i["why"] == "unverified player zero"]
    zfam = Counter(log[k]["family"] for k in zero)
    add("\n### 1d. Player zeros nothing else could confirm (set aside)\n")
    add(table(["Market", "Records"], [[f.replace("|", " / "), n] for f, n in zfam.most_common()]) if zero else "None.")

    rows = rows_for(log, res)
    rows_last = rows_for(log, res, "last")
    raw_rows = []   # the log exactly as settled, for comparison
    for k, r in log.items():
        if r.get("result") in ("win", "lose") and (r.get("first") or {}).get("market") is not None:
            raw_rows.append(k)

    # 2. scoring
    add("\n### 2a. Overall, one side per line, chance at first sighting\n")
    add(score_table([("All verified lines", rows),
                     ("Same, chance at last sighting", rows_last),
                     ("Both sides of every line (double counts)", rows_for(log, res, one_side=False))]))
    add("\n### 2b. By sport\n")
    add(score_table([(s, [r for r in rows if r["sport"] == s]) for s in sorted({r["sport"] for r in rows})]))
    add("\n### 2c. By market\n")
    fams = Counter(r["family"] for r in rows)
    add(score_table([(f.replace("|", " / "), [r for r in rows if r["family"] == f]) for f, _ in fams.most_common()]))
    add("\n### 2d. By how far apart the site and Betfair were (site lean off, at first sighting)\n")
    bands = [gap_band(lo + 1e-9) for lo, _ in GAP_BANDS]
    add(score_table([(b, [r for r in rows if gap_band(gap(r)) == b]) for b in bands]))
    add("\n### 2e. When they disagreed, which way did the result go?\n")
    body = []
    for b in bands:
        sel = [r for r in rows if gap_band(gap(r)) == b]
        if not sel:
            continue
        dd = direction(sel)
        lo, hi = cluster_boot(sel, lambda rs: direction(rs)["realised"] if rs else None)
        body.append([b, dd["n"], pct(sum(abs(gap(r)) for r in sel) / len(sel)),
                     num(dd["realised"], 2), interval(lo, hi, num, d=2), pct(dd["site_side"], d=0)])
    dd = direction(rows)
    lo, hi = cluster_boot(rows, lambda rs: direction(rs)["realised"] if rs else None)
    body.append(["All", dd["n"], pct(sum(abs(gap(r)) for r in rows) / len(rows)), num(dd["realised"], 2),
                 interval(lo, hi, num, d=2), pct(dd["site_side"], d=0)])
    add(table(["Gap", "Lines", "Average gap", "Share of gap realised", "95%", "Landed on site's side"], body))
    add("\nShare of gap realised: 1 means results moved the full distance from Betfair's chance to the "
        "site's, 0 means they stayed at Betfair's, below 0 means they moved the other way.")

    add("\n### 2f. Calibration\n")
    body = []
    for c in CHANCES:
        f = calibration_fit(rows, c)
        body.append([NAMES[c], num(f["slope"], 2), interval(f["slope_lo"], f["slope_hi"], num, d=2),
                     pct(f["large"], signed=True)])
    add(table(["Chance", "Calibration slope", "95%", "Landed minus said"], body))
    add("\nSlope 1 is perfect; below 1 the chances are too spread out (overconfident), above 1 too timid.\n")
    for c in ("model", "market", "blend"):
        add(f"\n{NAMES[c]}, by band:\n")
        add(table(["Said", "Lines", "Average said", "Landed"],
                  [[b["band"], b["n"], pct(b["said"]), pct(b["landed"])] for b in calibration_table(rows, c)]))

    # 3. value
    vr = value_rows(log, res)
    add("\n### 3a. Bets the page called value, backed at the price shown, 5% commission\n")
    body = []
    for label, sel in (("Every bet with a value figure", vr),
                       ("Value below 0 (not shown as value)", [r for r in vr if r["value"] <= SHOWN]),
                       ("Shown as value on the page (over 0.5%)", [r for r in vr if r["value"] > SHOWN]),
                       ("Value list bar (3%+)", [r for r in vr if r["value"] >= 0.03]),
                       ("Value 6%+", [r for r in vr if r["value"] >= 0.06]),
                       ("Shown, two-way exchange markets", [r for r in vr if r["kind"] == "exchange" and r["value"] > SHOWN]),
                       ("Shown, back-only player lists", [r for r in vr if r["kind"] == "back" and r["value"] > SHOWN])):
        b = roi_block(sel)
        if not b["n"]:
            body.append([label, 0] + ["-"] * 8)
            continue
        body.append([label, b["n"], b["fixtures"], f"{b['won']} ({pct(b['hit'], d=0)})", pct(b["need"], d=0),
                     pct(b["site_said"], signed=True), pct(b["betfair_said"], signed=True),
                     f"{b['profit']:+.2f}u", pct(b["roi"], signed=True), interval(b["lo"], b["hi"], signed=True)])
    add(table(["Bets", "n", "Fixtures", "Won", "Needed to break even", "Site said", "Betfair said",
               "Profit", "ROI", "ROI 95%"], body))
    add("\n### 3b. The same bets against Betfair's closing chance (no results needed)\n")
    body = []
    for label, sel in (("Shown as value (over 0.5%)", [r for r in vr if r["value"] > SHOWN]),
                       ("Value list bar (3%+)", [r for r in vr if r["value"] >= 0.03]),
                       ("Not shown as value", [r for r in vr if r["value"] <= SHOWN]),
                       ("Every bet with a value figure", vr)):
        c_ = clv_block(sel)
        if c_["n"]:
            body.append([label, c_["n"], pct(c_["clv"], signed=True), interval(c_["lo"], c_["hi"], signed=True),
                         pct(c_["shortened"], d=0), pct(c_["drifted"], d=0)])
    add(table(["Bets", "Seen twice", "Worth at close", "95%", "Shortened", "Drifted"], body))
    add("\n### 3c. Value by market\n")
    body = []
    for f in sorted({r["family"] for r in vr}):
        b = roi_block([r for r in vr if r["family"] == f and r["value"] > SHOWN])
        if b["n"]:
            body.append([f.replace("|", " / "), b["n"], b["won"], pct(b["site_said"], signed=True),
                         pct(b["roi"], signed=True), interval(b["lo"], b["hi"], signed=True)])
    add(table(["Market", "Value bets", "Won", "Site said", "ROI", "95%"], body))

    add("\n### 3d. Is Betfair's chance where its spread says? (two-way markets, first sighting)\n")
    sc = spread_check(log)
    add(table(["Quotes with back and lay", "Chance inside [1/lay, 1/back]", "Within 2 pts more", "Median spread width"],
              [[sc["n"], sc["inside"], sc["near"], pct(sc["median_width"])]]))
    add("\n### 3e. Reading Betfair's chance different ways (two-way markets with both prices)\n")
    two = [r for r in rows if r["kind"] == "exchange" and r["back"] and r["lay"]]
    if two:
        alt = [dict(r, p_back=1 / r["back"], p_lay=min(1 / r["lay"], 1 - EPS), p_mid=2 / (r["back"] + r["lay"]),
                    p_be=break_even(r["back"])) for r in two]
        names_ = {"p_back": "1 / back", "p_lay": "1 / lay", "p_mid": "1 / mid price", "p_be": "Back break-even after commission",
                  "market": "Margin off, as logged"}
        body = []
        for c in names_:
            s = score(alt, (c,))
            body.append([names_[c], s["n"], pct(s[c]["said"]), pct(s["landed"]), num(s[c]["logloss"]), num(s[c]["brier"])])
        add(table(["Betfair's chance read as", "Lines", "Said", "Landed", "Log loss", "Brier"], body))
    backs = [r for r in rows if r["kind"] == "back" and r["back"]]
    if backs:
        add("\n### 3f. Back-only lists: what margin the results say is in the price\n")
        fm = fitted_back_margin(backs)
        lo, hi = cluster_boot(backs, fitted_back_margin, n=300)
        raw = [r for r in rows_for(log, {k: dict(i, ok=log[k].get("result") in ("win", "lose"), result=log[k].get("result"))
                                         for k, i in res.items()}) if r["kind"] == "back" and r["back"]]
        add(table(["Results used", "Lines", "Fitted margin", "95%"],
                  [["Verified only", len(backs), pct(fm), interval(lo, hi)],
                   ["The log as settled (includes unverified zeros)", len(raw), pct(fitted_back_margin(raw)), "-"]]))

    # 4. rules
    add("\n### 4. Trust rules, out of sample (5 folds by fixture)\n")
    cv = cv_rules(rows)
    add(table(["Rule", "Lines", "Log loss", "Minus Betfair", "95%"],
              [[k, v["n"], num(v["logloss"]), num(v["vs_betfair"], signed=True),
                interval(v["lo"], v["hi"], num, signed=True)] for k, v in cv.items()]))
    w_all = fit_weight(rows)
    lo, hi = cluster_boot(rows, lambda rs: fit_weight(rs, grid=20) if len(rs) > 10 else None, n=300)
    add(f"\nWeight on Betfair that fits all verified lines best: {w_all:.2f} (95% {lo:.2f} to {hi:.2f}).")
    body = []
    for b in bands:
        sel = [r for r in rows if gap_band(gap(r)) == b]
        if len(sel) >= 10:
            l2, h2 = cluster_boot(sel, lambda rs: fit_weight(rs, grid=20) if len(rs) > 5 else None, n=300)
            body.append([b, len(sel), num(fit_weight(sel), 2), interval(l2, h2, num, d=2)])
    add("\n" + table(["Gap", "Lines", "Best weight on Betfair", "95%"], body))
    body = []
    for f, _ in fams.most_common():
        sel = [r for r in rows if r["family"] == f]
        if len(sel) >= 10:
            l2, h2 = cluster_boot(sel, lambda rs: fit_weight(rs, grid=20) if len(rs) > 5 else None, n=300)
            used = sum(r["w"] for r in sel if r["w"] is not None) / max(1, sum(1 for r in sel if r["w"] is not None))
            body.append([f.replace("|", " / "), len(sel), num(used, 2), num(fit_weight(sel), 2), interval(l2, h2, num, d=2)])
    add("\n" + table(["Market", "Lines", "Weight the site used", "Best weight on Betfair", "95%"], body))
    return "\n".join(parts) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cache", type=Path, default=CACHE, help="folder of SofaScore copies (default cache/)")
    ap.add_argument("--tarball", type=Path, default=TARBALL)
    ap.add_argument("--out", type=Path, help="write the tables here as well as printing them")
    a = ap.parse_args()
    md = report(a.cache, a.tarball)
    print(md)
    if a.out:
        a.out.write_text(md)


if __name__ == "__main__":
    main()
