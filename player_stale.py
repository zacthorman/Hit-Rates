#!/usr/bin/env python3
"""Are player lines on a record mostly from before a long break worse calibrated?

    python -B player_stale.py committed [--cache DIR]   # pp-results.html, best_bets.json legs (dates from the cache)
    python -B player_stale.py replay --rows ROWS        # the football cache replay (acceptable_check.py build)

The measure is freshness.py's: a player's break is his most recent gap of
BREAK_DAYS (45) or more between games, or between his last game and the
kick-off; the fresh share is how many of the games his line is priced on
come after it. The page now calls a line on a share under STALE_SHARE "Old
record", never acceptable. This is the evidence for that.

Replay. acceptable_check.py build prices every football player line in the
cache before kick-off the way pplog.snapshot does (opponent adjustment
included) and, since 24 Oct 2026, records each line's fresh share. Seasons
run from July. The threshold is chosen on the earlier season starts and
confirmed on the later ones:

  choose   on seasons before CONFIRM_SEASON, among lines we made 50% or
           more: the share s in GRID whose stale lines (share under s, 300
           or more of them) landed furthest below what we said
  confirm  on CONFIRM_SEASON onwards, at that s: the stale lines' got - said
           has a 95% interval wholly below zero, and so has (stale minus
           fresh). Intervals resample whole matches.

The page uses freshness.STALE_SHARE, 0.5: "mostly" from before the break, as
the brief put it. The report confirms both the chosen s and 0.5 on the later
seasons, and shows each season's August and September on their own, the
cleanest test of a season start (the cache does not hold every match, so a
"break" later in a season can be matches missing from it rather than a real
absence). PLAYER-STALE.md says which held.
"""
from __future__ import annotations

import argparse
import collections
import glob
import gzip
import json
import math
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIRM_SEASON = 2025      # seasons from July 2025 confirm; earlier ones choose
GRID = (0.3, 0.5, 0.7)
MIN_STALE = 300
BOOT = 1000
SEED = 20261024
Z = 1.959964


# ------------------------------------------------------------------ intervals

def wilson(k, n, z=Z):
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def boot(groups: dict, f, n=None, seed=SEED):
    """95% interval of f(list of group sums) resampling whole groups.
    groups: {key: tuple of sums}; f takes the summed tuple."""
    n = BOOT if n is None else n
    keys = list(groups)
    if not keys:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    vals = []
    width = len(groups[keys[0]])
    for _ in range(n):
        tot = [0.0] * width
        for _k in keys:
            g = groups[keys[rng.randrange(len(keys))]]
            for i in range(width):
                tot[i] += g[i]
        v = f(tot)
        if v is not None:
            vals.append(v)
    vals.sort()
    if not vals:
        return (float("nan"), float("nan"))
    return vals[int(0.025 * (len(vals) - 1))], vals[int(math.ceil(0.975 * (len(vals) - 1)))]


def calib(rows, group="g") -> dict:
    """n, said, got (Wilson), got - said with its interval by group."""
    n = len(rows)
    if not n:
        return {"n": 0}
    k = sum(r["y"] for r in rows)
    said = sum(r["p"] for r in rows) / n
    g = collections.defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        a = g[r[group]]
        a[0] += r["y"] - r["p"]
        a[1] += 1
    return {"n": n, "groups": len(g), "said": said, "got": k / n, "got_ci": wilson(k, n), "gap": k / n - said,
            "gap_ci": boot({key: tuple(v) for key, v in g.items()}, lambda t: t[0] / t[1] if t[1] else None)}


def contrast(a_rows, b_rows, group="g") -> dict:
    """(got - said on a) minus (got - said on b), interval by group (groups resampled jointly)."""
    g = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for r in a_rows:
        x = g[r[group]]
        x[0] += r["y"] - r["p"]
        x[1] += 1
    for r in b_rows:
        x = g[r[group]]
        x[2] += r["y"] - r["p"]
        x[3] += 1

    def f(t):
        return t[0] / t[1] - t[2] / t[3] if t[1] and t[3] else None
    tot = [sum(v[i] for v in g.values()) for i in range(4)]
    return {"diff": f(tot), "ci": boot({k: tuple(v) for k, v in g.items()}, f)}


def pct(x, d=1, sign=False):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    return f"{x * 100:+.{d}f}%" if sign else f"{x * 100:.{d}f}%"


def ci(c, d=1, sign=False):
    if not c or any(isinstance(v, float) and math.isnan(v) for v in c):
        return "-"
    return f"{pct(c[0], d, sign)} to {pct(c[1], d, sign)}"


HEAD = ["| Group | Lines | Said | Got (95%) | Got - said (95%) |", "|---|---|---|---|---|"]


def row(label, s):
    if not s.get("n"):
        return None
    return (f"| {label} | {s['n']} | {pct(s['said'])} | {pct(s['got'])} ({ci(s['got_ci'])}) | "
            f"{pct(s['gap'], sign=True)} ({ci(s['gap_ci'], sign=True)}) |")


# ------------------------------------------------------------------ 1. committed records

def pp_by_market(path: Path = ROOT / "pp-results.html") -> list[dict]:
    """Every row of pp-results.html's 'Value bets by market': sport, market, n, won, said."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    m = re.search(r"<h2>Value bets by market</h2>(.*?)(?=<h2>|</main>)", text, re.S)
    out = []
    for r in re.findall(r"<tr>(.*?)</tr>", m.group(1) if m else "", re.S):
        c = [re.sub(r"<[^>]+>", "", x).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
        if len(c) < 4 or "·" not in c[0]:
            continue
        sport, market = (x.strip() for x in c[0].split("·", 1))
        n = int(c[1])
        out.append({"sport": sport, "market": market, "n": n,
                    "won": round(float(c[2].rstrip("%")) / 100 * n), "said": float(c[3].rstrip("%")) / 100})
    return out


def appearances_index(cache: Path) -> dict:
    """(sport, player name) -> sorted [(ts, minutes or None)] from the cache's line-ups."""
    sports = {}
    for f in glob.glob(str(cache / "team_*_events_last_*.json")):
        try:
            for e in json.loads(Path(f).read_text()).get("events") or []:
                slug = (((e.get("tournament") or {}).get("category") or {}).get("sport") or {}).get("slug")
                if slug in ("football", "american-football"):
                    sports[e["id"]] = (slug, e.get("startTimestamp"))
        except (OSError, ValueError, TypeError, KeyError):
            continue
    idx = collections.defaultdict(list)
    for eid, (slug, ts) in sports.items():
        try:
            lu = json.loads((cache / f"event_{eid}_lineups.json").read_text())
        except (OSError, ValueError):
            continue
        for side in ("home", "away"):
            for p in ((lu.get(side) or {}).get("players") or []):
                st = p.get("statistics") or {}
                if not st:
                    continue
                mins = st.get("minutesPlayed") if slug == "football" else None
                if slug == "football" and not mins:
                    continue
                idx[(slug, (p.get("player") or {}).get("name"))].append((ts, mins))
    for v in idx.values():
        v.sort()
    return idx


def leg_rows(cache: Path | None) -> list[dict]:
    """Settled published player legs from best_bets.json, each line once, with its fresh share.

    Football and NFL: rebuilt from the cache (his last ten appearances before
    kick-off, 45 minutes or more in football, against his break). Basketball:
    every settled leg is from the first two nights of the season, so at most
    one of his ten games was this season's: the share is set to 0.1 at most."""
    import freshness
    try:
        bets = json.loads((ROOT / "best_bets.json").read_text())
    except (OSError, ValueError):
        return []
    idx = appearances_index(cache) if cache else {}
    seen = {}
    for b in bets:
        for l in b.get("legs") or []:
            if not l.get("player") or l.get("result") not in ("win", "lose"):
                continue
            p = l.get("chance") or (1 / l["fair"] if l.get("fair") else None)
            key = (l["event_id"], l["player"], l["stat"], l["line"], bool(l["over"]))
            if not p or key in seen:
                continue
            sport = l.get("sport")
            share = None
            if sport == "basketball":
                share = 0.1 if l["kickoff"] < datetime(2026, 10, 23, tzinfo=timezone.utc).timestamp() else None
            elif (sport, l["player"]) in idx:
                apps = [a for a in idx[(sport, l["player"])] if a[0] < l["kickoff"]]
                gated = [a for a in apps if sport != "football" or (a[1] or 0) >= 45][-10:]
                if len(gated) >= 3:
                    brk = freshness.break_date([a[0] for a in apps], l["kickoff"])
                    share = freshness.window([a[0] for a in gated], brk)["share"]
            seen[key] = {"g": time.strftime("%Y-%m-%d", time.gmtime(l["kickoff"] - 6 * 3600)),
                         "sport": sport, "p": float(p), "y": int(l["result"] == "win"), "fresh": share}
    return list(seen.values())


def committed_report(cache: Path | None) -> list[str]:
    import freshness
    out = ["### Paddy Power value bets (pp-results.html, committed 22 Oct)", "",
           "Basketball's settled value bets are all from the first two nights of the season, so every record "
           "behind them was nine or ten games of last season. Football's are from mid-season, on fresh records.", "",
           "| Sport | Bets | Said | Got (95%) | Got - said |", "|---|---|---|---|---|"]
    by = collections.defaultdict(lambda: [0, 0, 0.0])
    for m in pp_by_market():
        a = by[m["sport"]]
        a[0] += m["n"]
        a[1] += m["won"]
        a[2] += m["said"] * m["n"]
    for sport, (n, k, s) in sorted(by.items(), key=lambda kv: -kv[1][0]):
        lo, hi = wilson(k, n)
        out.append(f"| {sport} | {n} | {pct(s / n, 0)} | {pct(k / n, 0)} ({pct(lo, 0)} to {pct(hi, 0)}) | "
                   f"{pct(k / n - s / n, 0, sign=True)} |")
    legs = leg_rows(cache)
    known = [r for r in legs if r["fresh"] is not None]
    out += ["", "### Published player legs (best_bets.json)", "",
            f"{len(legs)} settled distinct player legs; the fresh share is known for {len(known)} (football and NFL "
            "rebuilt from the cache, which ends on 19 October; basketball from its dates). Intervals resample nights.",
            "", *HEAD]
    for sport in sorted({r["sport"] for r in known}):
        for label, sel in (("mostly stale (share under 0.5)", [r for r in known if r["sport"] == sport
                                                               and freshness.is_stale(r["fresh"])]),
                           ("fresh (0.5 or more)", [r for r in known if r["sport"] == sport
                                                    and not freshness.is_stale(r["fresh"])])):
            x = row(f"{sport}, {label}", calib(sel))
            if x:
                out.append(x)
    st = [r for r in known if freshness.is_stale(r["fresh"])]
    fr = [r for r in known if not freshness.is_stale(r["fresh"])]
    x = row("all sports, mostly stale", calib(st))
    y = row("all sports, fresh", calib(fr))
    out += [v for v in (x, y) if v]
    if st and fr:
        c = contrast(st, fr)
        out.append(f"\nStale minus fresh, got - said: {pct(c['diff'], sign=True)} (95% {ci(c['ci'], sign=True)}).")
    return out


# ------------------------------------------------------------------ 2. the football replay

def season(ts) -> int:
    d = datetime.fromtimestamp(ts, tz=timezone.utc)
    return d.year if d.month >= 7 else d.year - 1


def replay_rows(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        rows = json.load(fh)
    out = []
    for r in rows:
        if r.get("fresh") is None:
            continue
        out.append({"g": r["event_id"], "ts": r["ts"], "season": season(r["ts"]), "p": r["p"], "y": int(r["won"]),
                    "fresh": r["fresh"], "stat": r["stat"], "line": r["line"], "started": r.get("started"),
                    "month": datetime.fromtimestamp(r["ts"], tz=timezone.utc).month, "rest": r.get("rest")})
    return out


def choose(rows: list[dict]) -> tuple[float | None, list]:
    tried = []
    for s in GRID:
        st = [r for r in rows if r["fresh"] < s]
        c = calib(st) if len(st) >= MIN_STALE else {"n": len(st)}
        tried.append((s, c))
    ok = [(s, c) for s, c in tried if c.get("n", 0) >= MIN_STALE]
    if not ok:
        return None, tried
    return min(ok, key=lambda sc: sc[1]["gap"])[0], tried


def replay_report(path: Path) -> list[str]:
    rows = [r for r in replay_rows(path) if r["p"] >= 0.5]
    if not rows:
        return [f"No replay rows with a fresh share in {path}. Run acceptable_check.py build first."]
    early = [r for r in rows if r["season"] < CONFIRM_SEASON]
    late = [r for r in rows if r["season"] >= CONFIRM_SEASON]
    seasons = sorted({r["season"] for r in rows})
    out = [f"{len(rows)} football player lines we made 50% or more, seasons "
           f"{', '.join(f'{s}-{(s + 1) % 100:02d}' for s in seasons)}: {len(early)} choose (before "
           f"{CONFIRM_SEASON}-{(CONFIRM_SEASON + 1) % 100:02d}), {len(late)} confirm. Intervals resample matches.", ""]
    s, tried = choose(early)
    out += ["### Choosing the share, earlier seasons", "", "| Share under | Stale lines | Said | Got | Got - said (95%) |",
            "|---|---|---|---|---|"]
    for t, c in tried:
        out.append(f"| {t} | {c.get('n', 0)} | {pct(c.get('said'))} | {pct(c.get('got'))} | "
                   f"{pct(c.get('gap'), sign=True)} ({ci(c.get('gap_ci'), sign=True)}) |" if c.get("said") is not None
                   else f"| {t} | {c.get('n', 0)} | - | - | too few |")
    out.append("")
    out.append(f"Chosen: {s}." if s is not None else "No share had enough stale lines to choose from.")
    res = {"chosen": s}
    for label, sel in (("earlier seasons", early), ("later seasons (confirm)", late)):
        if s is None:
            break
        st = [r for r in sel if r["fresh"] < s]
        fr = [r for r in sel if r["fresh"] >= s]
        out += ["", f"### {label.capitalize()}, at share under {s}", "", *HEAD]
        for name, x in (("mostly stale", st), ("fresh", fr),
                        ("mostly stale, August and September", [r for r in st if r["month"] in (8, 9)]),
                        ("fresh, August and September", [r for r in fr if r["month"] in (8, 9)]),
                        ("mostly stale, rest of the season", [r for r in st if r["month"] not in (8, 9)]),
                        ("all stale: share 0", [r for r in st if r["fresh"] == 0])):
            v = row(name, calib(x))
            if v:
                out.append(v)
        c = contrast(st, fr)
        out.append(f"\nStale minus fresh, got - said: {pct(c['diff'], sign=True)} (95% {ci(c['ci'], sign=True)}).")
        res[label] = {"stale": calib(st), "contrast": c}
    page = __import__("freshness").STALE_SHARE
    if s is not None and page != s:
        st = [r for r in late if r["fresh"] < page]
        fr = [r for r in late if r["fresh"] >= page]
        c = contrast(st, fr)
        out += ["", f"### Later seasons, at the page's share under {page}", "", *HEAD,
                row("mostly stale", calib(st)), row("fresh", calib(fr)),
                f"\nStale minus fresh, got - said: {pct(c['diff'], sign=True)} (95% {ci(c['ci'], sign=True)})."]
        res["page"] = {"stale": calib(st), "contrast": c}
    out += ["", f"### Starters and substitutes separately, at share under {page}", "",
            "Before the line-up is known the page cannot tell them apart; afterwards it can.", "",
            "| Who | Seasons | Stale lines | Got - said (95%) | Fresh lines | Got - said | Stale minus fresh (95%) |",
            "|---|---|---|---|---|---|---|"]
    for who, flag in (("starters", True), ("substitutes", False)):
        for label, sel in (("earlier", early), ("later", late)):
            ss = [r for r in sel if bool(r["started"]) == flag]
            st = [r for r in ss if r["fresh"] < page]
            fr = [r for r in ss if r["fresh"] >= page]
            if not st or not fr:
                continue
            a_, b_, c_ = calib(st), calib(fr), contrast(st, fr)
            out.append(f"| {who} | {label} | {a_['n']} | {pct(a_['gap'], sign=True)} ({ci(a_['gap_ci'], sign=True)}) | "
                       f"{b_['n']} | {pct(b_['gap'], sign=True)} | {pct(c_['diff'], sign=True)} ({ci(c_['ci'], sign=True)}) |")
            res[(who, label)] = {"stale": a_, "fresh": b_, "contrast": c_}
    out += ["", f"### Each season's August and September, at share under {page}", "",
            "| Season | Stale lines | Got - said | Fresh lines | Got - said | Stale minus fresh (95%) |",
            "|---|---|---|---|---|---|"]
    for sea in seasons:
        sel = [r for r in rows if r["season"] == sea and r["month"] in (8, 9)]
        st = [r for r in sel if r["fresh"] < page]
        fr = [r for r in sel if r["fresh"] >= page]
        if len(st) < 30 or len(fr) < 30:
            continue
        a, b, c = calib(st), calib(fr), contrast(st, fr)
        out.append(f"| {sea}-{(sea + 1) % 100:02d} | {a['n']} | {pct(a['gap'], sign=True)} | {b['n']} | "
                   f"{pct(b['gap'], sign=True)} | {pct(c['diff'], sign=True)} ({ci(c['ci'], sign=True)}) |")
    if s is not None:
        conf = res["later seasons (confirm)"]
        held = conf["stale"].get("gap_ci", (0, 0))[1] < 0 and conf["contrast"]["ci"][1] < 0
        res["held"] = held
        out += ["", f"**Confirmed on the later seasons:** {'yes' if held else 'no'} "
                f"(stale got - said wholly below zero: {'yes' if conf['stale']['gap_ci'][1] < 0 else 'no'}; "
                f"stale minus fresh wholly below zero: {'yes' if conf['contrast']['ci'][1] < 0 else 'no'})."]
    by_share = collections.defaultdict(list)
    for r in late:
        by_share[min(10, int(round(r["fresh"] * 10)))].append(r)
    out += ["", "### Later seasons, by fresh share", "", *HEAD]
    for k in sorted(by_share):
        v = row(f"{k} of 10 since the break", calib(by_share[k]))
        if v:
            out.append(v)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("part", choices=["committed", "replay"])
    ap.add_argument("--cache", help="SofaScore cache folder (cache/ unpacked from cache_backtest.tar.zst)")
    ap.add_argument("--rows", default=str(ROOT / "cache" / "acceptable_rows.json.gz"))
    a = ap.parse_args(argv)
    lines = committed_report(Path(a.cache) if a.cache else None) if a.part == "committed" else replay_report(Path(a.rows))
    print("\n".join(l for l in lines if l is not None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
