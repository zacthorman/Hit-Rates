#!/usr/bin/env python3
"""Every Paddy Power player line, our chance at it, and how it landed.

    python pplog.py snapshot    # record lines for games not yet started (publish.sh)
    python pplog.py settle      # results for anything finished (publish.sh)
    python pplog.py report      # print the scoreboard
    python pplog.py page        # write pp-results.html

Stage 1 of tuning the system: nothing about a new factor can be judged until
there is a record of what the site said, what the bookmaker offered and what
happened. This keeps that record for Paddy Power, the book Zac bets with.

What is recorded, per line (player, stat, line, over or under):
  * Paddy Power's price and our chance at first sighting, and again at the
    last sighting before kick-off. First is what the site showed; last is the
    closest to the closing price, so the move between them is closing line
    value: a price that shortened after we flagged it means the market came
    round to us, the best early sign of real value.
  * the last-5 and last-10 records behind it, and the player's injury status.
  * the result, settled from SofaScore exactly as besttrack and linelog
    settle player legs. A player who did not play voids the line, as Paddy
    Power voids the bet.

Our chance here is model.price_player on the player's last ten appearances,
the Python mirror of the page's pricePlayer, times the same opponent
adjustment the page uses. Unders are one minus the over. It is the number the
Players tab shows, not a new model.

One JSON-lines file a month in pplog/, gitignored with cache/ and linelog/.
Records are appended, updated only before kick-off, then settled; never
rewritten after.
"""
from __future__ import annotations

import argparse
import collections
import html
import json
import math
import re
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIR = ROOT / "pplog"
PAGE = ROOT / "pp-results.html"
PP = ROOT / "reports" / "paddypower.json"

# Value, for the scoreboard: what the site would have flagged.
VALUE_EDGE = 0.05
VALUE_MIN_P = 0.50
VALUE_MIN_N = 5       # games behind it; three is not a record
# Logged but never called value until the record says how far off they are.
# Football to-score came out at 23% on average across 207 lines on 20 Oct
# against Paddy Power's 17% implied, which still includes their margin.
UNCALIBRATED = {("football", "Goals"), ("football", "Card")}
BANDS = ((0, .4), (.4, .5), (.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1.01))

# Paddy Power market name -> the site's stat. Mirrors PP_STAT in report.py.
PP_STAT = {
    "Receiving Yds": "Receiving yards", "Alt Receiving Yds": "Receiving yards",
    "Rushing Yds": "Rushing yards", "Alt Rushing Yds": "Rushing yards",
    "Passing Yds": "Passing yards", "Alt Passing Yds": "Passing yards",
    "Total Receptions": "Receiving receptions", "Alt Receptions": "Receiving receptions",
    "Rushing + Receiving Yds": "Rushing and receiving yards",
    "Alt Rushing + Receiving Yds": "Rushing and receiving yards",
    "Passing + Rushing Yds": "Passing and rushing yards",
    "Alt Passing + Rushing Yds": "Passing and rushing yards",
    "Passing TDs": "Passing touchdowns", "Alt Passing TDs": "Passing touchdowns",
    "Any Time Touchdown Scorer": "Anytime touchdown",
    "Player To Score": "Goals", "Anytime Goalscorer": "Goals",
}
YES_MARKETS = {"Anytime touchdown", "Goals"}

# Football markets are one per line, every player a runner: "Player To Have
# 2 Or More Shots". Mirrors PP_PATTERNS in report.py.
PP_PATTERNS = [
    (re.compile(r"^Player To Have (\d+) Or More Shots$"), "Shots"),
    (re.compile(r"^Player To Commit (\d+) Or More Fouls$"), "Fouls"),
    (re.compile(r"^Player To Be Fouled (\d+) Or More Times$"), "Fouled"),
]
PP_YES = {"Player Shown a Card": "Card", "Player Assists": "Assists"}


# ------------------------------------------------------------------ storage

def _month_file(ts: float) -> Path:
    return DIR / f"{time.strftime('%Y-%m', time.gmtime(ts))}.jsonl"


def _files() -> list[Path]:
    return sorted(DIR.glob("*.jsonl")) if DIR.exists() else []


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _write(path: Path, rows: list[dict]) -> None:
    DIR.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def all_rows() -> list[dict]:
    return [r for f in _files() for r in _read(f)]


def _key(r: dict) -> str:
    return f"{r['event_id']}|{r['player']}|{r['stat']}|{r['line']}|{int(r['over'])}"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return " ".join("".join(c for c in s if c.isascii() and (c.isalpha() or c == " ")).lower().split())


# ------------------------------------------------------------------ reading a line

def read_line(l: dict):
    """(stat, line, over, label) for one Paddy Power selection, or None."""
    market = l.get("market") or ""
    for rx, st in PP_PATTERNS:
        m = rx.match(market)
        if m:
            return st, int(m.group(1)) - 0.5, True, f"{m.group(1)}+"
    if market in PP_YES:
        st = PP_YES[market]
        return st, 0.5, True, "to be booked" if st == "Card" else "1+"
    stat = PP_STAT.get(market)
    if not stat:
        return None
    if stat in YES_MARKETS:
        return stat, 0.5, True, "to score" if stat == "Goals" else "anytime TD"
    side = l.get("side")
    if side in ("OVER", "UNDER") and l.get("line") is not None:
        return stat, float(l["line"]), side == "OVER", f"{'Over' if side == 'OVER' else 'Under'} {l['line']}"
    m = re.match(r"\s*(\d+(?:\.\d+)?)\+", l.get("selection") or "")
    if m:
        n = float(m.group(1))
        return stat, n - 0.5, True, f"{m.group(1)}+"
    return None


def _adjustment(entry: dict, t: int, stat: str) -> float:
    """The page's playerAdjustment: projected team stat over its usual."""
    import model
    team_stat = {**model.FOOTBALL_STAT_TO_TEAM, **model.GRIDIRON_STAT_TO_TEAM}.get(stat)
    if not team_stat:
        return 1.0
    proj = ((entry.get("projection") or {}).get("ALL") or {}).get(team_stat)
    if not proj or len(proj) <= t or proj[t] is None:
        return 1.0
    vals = [((r.get("stats") or {}).get("ALL") or {}).get(team_stat)
            for r in (entry.get("records") or [[], []])[t]]
    vals = [v for v in vals if v is not None]
    if len(vals) < 3:
        return 1.0
    mean = sum(vals) / len(vals)
    if mean <= 0:
        return 1.0
    return min(2.5, max(0.2, proj[t] / mean))


def _score_chance(played: list[dict], adj: float, mins: int) -> float | None:
    """Football to-score, as the page's scoreCase: 60% xG and 40% goals per
    90 over expected minutes, half last ten and half every match on file,
    Poisson for at least one. A goals record alone is far too noisy: four in
    five read as 52% for a 5.50 shot."""
    def lam(games):
        g = [x for x in games if (x.get("minutes") or 0) >= mins]
        if len(g) < 3:
            return None
        m = sum(x["minutes"] for x in g)
        if m <= 0:
            return None
        goals = sum((x.get("stats") or {}).get("Goals", 0) or 0 for x in g) / m * 90
        has_xg = any("xG" in (x.get("stats") or {}) for x in g)
        xg = sum((x.get("stats") or {}).get("xG", 0) or 0 for x in g) / m * 90 if has_xg else None
        rate = 0.6 * xg + 0.4 * goals if xg is not None else goals
        ms = sorted(x["minutes"] for x in g)
        return rate * min(90, ms[len(ms) // 2]) / 90 * adj
    a, b = lam(played[-10:]), lam(played)
    if a is None or b is None:
        return None
    return 1 - math.exp(-(a + b) / 2)


def _card_chance(played: list[dict], entry: dict, t: int, mins: int) -> float | None:
    """The page's To be booked: fouls per 90 times the side's cards per foul,
    over expected minutes, times the side's projected fouls against its
    usual; half last ten, half every match. Heuristic: logged, not value."""
    recs = [r for r in (entry.get("records") or [[], []])[t]]
    F = sum(((r.get("stats") or {}).get("ALL") or {}).get("Fouls", 0) or 0 for r in recs)
    Y = sum(((r.get("stats") or {}).get("ALL") or {}).get("Yellow cards", 0) or 0 for r in recs)
    per_foul = Y / F if F >= 30 else 0.13
    adj = _adjustment(entry, t, "Fouls")

    def lam(games):
        g = [x for x in games if (x.get("minutes") or 0) >= mins]
        if len(g) < 3:
            return None
        m = sum(x["minutes"] for x in g)
        if m <= 0:
            return None
        f90 = sum((x.get("stats") or {}).get("Fouls", 0) or 0 for x in g) / m * 90
        ms = sorted(x["minutes"] for x in g)
        return f90 * min(90, ms[len(ms) // 2]) / 90 * per_foul * adj
    a, b = lam(played[-10:]), lam(played)
    if a is None or b is None:
        return None
    return 1 - math.exp(-(a + b) / 2)


def _injury(entry: dict, t: int, name: str):
    side = (entry.get("injuries") or {}).get("home" if t == 0 else "away") or []
    for r in side:
        if _norm(r[0]) == _norm(name):
            return r[2]
    return None


def _match_player(pp_key: str, squads: list[dict]):
    """(team index, our name) for a Paddy Power player name."""
    for t, by in enumerate(squads):
        for name in by:
            if _norm(name) == pp_key:
                return t, name
    # Surname plus first initial, only if it picks out exactly one player.
    parts = pp_key.split()
    if len(parts) >= 2:
        hits = [(t, n) for t, by in enumerate(squads) for n in by
                if _norm(n).split()[-1:] == parts[-1:] and _norm(n)[:1] == pp_key[:1]]
        if len(hits) == 1:
            return hits[0]
    return None


# ------------------------------------------------------------------ snapshot

def _fmodel() -> dict:
    """reports/fmodel.json (fmodel_live.py): event id -> {normalised name: player}."""
    try:
        j = json.loads((ROOT / "reports" / "fmodel.json").read_text())
    except (OSError, ValueError, NameError):
        try:
            j = json.loads((Path(__file__).parent / "reports" / "fmodel.json").read_text())
        except (OSError, ValueError):
            return {}
    out = {}
    for eid, ev in (j.get("events") or {}).items():
        out[eid] = {"confirmed": bool(ev.get("confirmed")),
                    "players": {_norm(n): pl for n, pl in (ev.get("players") or {}).items()}}
    return out


def _fmodel_p(fm: dict, fid: str, name: str, stat: str, line: float):
    """The backtested model's chance of over `line`, or None."""
    ev = fm.get(fid)
    pl = ev and ev["players"].get(_norm(name))
    k = line + 0.5
    if not pl or abs(k - round(k)) > 1e-9:
        return None
    return ((pl.get("lines") or {}).get(stat) or {}).get(str(int(round(k))))


def snapshot(args=None) -> int:
    import markets
    import model
    import playerlines
    try:
        pp = json.loads(PP.read_text())
    except (OSError, ValueError):
        print("pp log: no Paddy Power prices held")
        return 0
    now = time.time()
    fixtures = {str(m["id"]): (e, m) for e, m in playerlines.upcoming(48)}
    existing = {}
    for path in _files():
        for r in _read(path):
            existing[_key(r)] = (path, r)
    new_rows, touched = [], set()
    fm = _fmodel()
    for fid, ev in (pp.get("events") or {}).items():
        if fid not in fixtures:
            continue
        entry, meta = fixtures[fid]
        if meta["kickoff"] <= now:
            continue
        sport = (entry.get("fixture") or {}).get("sport") or "football"
        fill = markets.ZERO_FILL_BY_SPORT.get(sport) or frozenset()
        mins = model.min_minutes_for(sport)
        squads = []
        for t in (0, 1):
            by = collections.defaultdict(list)
            for r in (entry.get("players") or [[], []])[t]:
                by[r["player"]].append(r)
            for name in by:
                by[name].sort(key=lambda r: r.get("date") or "")
            squads.append(by)
        for l in ev.get("lines", []):
            read = read_line(l)
            if not read:
                continue
            stat, line, over, label = read
            who = _match_player(l.get("key") or _norm(l.get("player", "")), squads)
            if not who:
                continue
            t, name = who
            apps = model.appearances(squads[t][name], "Fouls" if stat == "Card" else stat, fill, mins)
            recent = apps[-10:]
            if len(recent) < 3:
                continue
            adj = _adjustment(entry, t, stat)
            if sport == "football" and stat == "Goals":
                p_over = _score_chance(squads[t][name], adj, mins)
                if p_over is None:
                    continue
            elif stat == "Card":
                p_over = _card_chance(squads[t][name], entry, t, mins)
                if p_over is None:
                    continue
            else:
                p_over = model.price_player(recent, line, True, adj, None, sport)["p"]
            site_over = p_over
            m_over = _fmodel_p(fm, fid, name, stat, line) if sport == "football" else None
            if m_over is not None:
                p_over = m_over
            p = p_over if over else 1 - p_over
            vals = [a["value"] for a in recent]
            hit = (lambda v: v > line) if over else (lambda v: v <= line)
            k10 = sum(1 for v in vals if hit(v))
            k5 = sum(1 for v in vals[-5:] if hit(v))
            if stat == "Card":
                # No card record in the box scores (cards_backfill.py will
                # bring one); the fouls behind the estimate are not it.
                k10 = k5 = None
            row = {
                "event_id": int(fid), "pp_event": ev.get("ppEvent"),
                "fixture": f"{meta['home']} v {meta['away']}", "competition": meta.get("competition"),
                "kickoff": meta["kickoff"], "sport": sport,
                "team": (entry.get("teams") or [{}, {}])[t].get("name"), "player": name,
                "pp_player": l.get("player"), "stat": stat, "line": line, "over": over,
                "label": label, "market": l.get("market"),
            }
            key = _key(row)
            snap = {"t": round(now), "price": l["price"], "chance": round(p, 4),
                    "edge": round(p * l["price"] - 1, 4)}
            if m_over is not None:
                # The model's chance is the one logged; the old one is kept
                # beside it so the two can be compared on results.
                snap["source"] = "fmodel"
                snap["site_chance"] = round(site_over if over else 1 - site_over, 4)
                snap["confirmed_xi"] = fm[fid]["confirmed"]
            # "Over 2.5" and "3+" are one bet: keep the better price.
            if key in touched:
                prev = next((x for x in new_rows if _key(x) == key), None) \
                    or (existing[key][1] if key in existing else None)
                cur = (prev or {}).get("last") or {}
                if prev is not None and l["price"] > cur.get("price", 0):
                    prev["last"] = snap
                    if prev in new_rows:
                        prev["first"] = snap
                continue
            touched.add(key)
            if key in existing:
                path, old = existing[key]
                if old.get("result") is None and old["kickoff"] > now:
                    old["last"] = snap
            else:
                row.update({"logged_at": round(now), "first": snap, "last": snap,
                            "k5": k5, "n5": min(5, len(vals)), "k10": k10, "n10": len(vals),
                            "adj": round(adj, 3), "injury": _injury(entry, t, name),
                            "result": None, "value": None})
                new_rows.append(row)
    # Rewrite the files that had rows updated, then append the new ones.
    changed = collections.defaultdict(list)
    for key, (path, r) in existing.items():
        changed[path].append(r)
    for path in {p for k, (p, r) in existing.items() if k in touched}:
        _write(path, _read_merge(path, changed[path]))
    if new_rows:
        by_file = collections.defaultdict(list)
        for r in new_rows:
            by_file[_month_file(r["kickoff"])].append(r)
        for path, rows in by_file.items():
            _write(path, (_read(path) if path.exists() else []) + rows)
    print(f"pp log: {len(new_rows)} new line(s), {len(touched) - len(new_rows)} re-priced")
    return len(new_rows)


def _read_merge(path: Path, updated: list[dict]) -> list[dict]:
    by = {_key(r): r for r in updated}
    return [by.get(_key(r), r) for r in _read(path)]


# ------------------------------------------------------------------ settle

def settle(args=None) -> int:
    import besttrack
    import sofascore_api as api
    now = time.time()
    done = 0
    status_of = {}
    for path in _files():
        rows = _read(path)
        changed = False
        for r in rows:
            if r["result"] is not None or r["kickoff"] > now - 3 * 3600:
                continue
            eid = r["event_id"]
            if eid not in status_of:
                ev = api.get_json(f"event/{eid}", max_age_hours=1, verbose=False) or {}
                status_of[eid] = ((ev.get("event", ev).get("status") or {}).get("type"))
            st = status_of[eid]
            if st in ("canceled", "postponed"):
                r["result"] = "void"
                changed = True
                continue
            if st != "finished":
                continue
            v = _card_value(r) if r["stat"] == "Card" else besttrack._player_value(r, r["sport"])
            if v is None:
                continue
            if v == "dnp":
                r["result"] = "void"
            else:
                r["value"] = v
                won = v > r["line"] if r["over"] else v < r["line"]
                r["result"] = "win" if won else "lose"
            done += 1
            changed = True
        if changed:
            _write(path, rows)
    print(f"pp log: settled {done} line(s)")
    return done


def _card_value(r: dict):
    """1 if booked, 0 if played and not, 'dnp' if he did not play.
    Cards are not in the box score, so the match's incidents decide it."""
    import besttrack
    import sofascore_api as api
    played = besttrack._player_value(dict(r, stat="Minutes"), r["sport"])
    if played == "dnp" or played is None:
        return played
    data = api.get_json(f"event/{r['event_id']}/incidents", max_age_hours=6, verbose=False)
    if not data:
        return None
    for inc in data.get("incidents") or []:
        if inc.get("incidentType") == "card" and _norm((inc.get("player") or {}).get("name", "")) == _norm(r["player"]):
            return 1.0
    return 0.0


# ------------------------------------------------------------------ scoring

def is_value(r: dict, snap: str = "first") -> bool:
    s = r.get(snap) or {}
    return (s.get("chance", 0) >= VALUE_MIN_P and s.get("edge", -1) >= VALUE_EDGE
            and (r.get("n10") or 0) >= VALUE_MIN_N
            and ((r.get("sport"), r.get("stat")) not in UNCALIBRATED
                 or (s.get("source") == "fmodel" and r.get("stat") != "Card")))


def _profit(r: dict, snap: str = "first") -> float:
    return (r[snap]["price"] - 1) if r["result"] == "win" else -1.0


def _clv(r: dict):
    """How far the price moved our way between first and last sighting.
    Positive: Paddy Power shortened it, the market came round to us."""
    a, b = r["first"]["price"], r["last"]["price"]
    return a / b - 1 if b else None


def summary() -> dict:
    rows = all_rows()
    done = [r for r in rows if r["result"] in ("win", "lose")]
    val = [r for r in done if is_value(r)]
    strong = [r for r in done if r["first"]["chance"] >= 0.7]

    def block(sel):
        n = len(sel)
        won = sum(1 for r in sel if r["result"] == "win")
        prof = sum(_profit(r) for r in sel)
        said = sum(r["first"]["chance"] for r in sel) / n if n else 0
        return {"n": n, "won": won, "hit": won / n if n else 0, "said": said,
                "profit": prof, "roi": prof / n if n else 0}

    def group(sel, keyf):
        g = collections.defaultdict(list)
        for r in sel:
            g[keyf(r)].append(r)
        return {k: block(v) for k, v in sorted(g.items(), key=lambda x: -len(x[1]))}

    def band(r):
        for lo, hi in BANDS:
            if lo <= r["first"]["chance"] < hi:
                return f"{int(lo*100)}-{min(int(hi*100), 100)}%"

    open_val = [r for r in rows if r["result"] is None and is_value(r, "last")]
    moved = [c for r in rows if is_value(r) and r["first"]["t"] != r["last"]["t"]
             for c in [_clv(r)] if c is not None]
    return {
        "logged": len(rows), "settled": len(done),
        "open": sum(1 for r in rows if r["result"] is None),
        "void": sum(1 for r in rows if r["result"] == "void"),
        "all": block(done), "value": block(val), "strong": block(strong),
        "value_by_market": group(val, lambda r: f"{r['sport']} · {r['stat']} {'over' if r['over'] else 'under'}"),
        "all_by_market": group(done, lambda r: f"{r['sport']} · {r['stat']}"),
        "by_band": group(done, band),
        "clv": {"n": len(moved), "avg": sum(moved) / len(moved) if moved else 0,
                "beat": sum(1 for c in moved if c > 0), "lost": sum(1 for c in moved if c < 0)},
        "recent_value": sorted(val, key=lambda r: -r["kickoff"])[:40],
        "open_value": sorted(open_val, key=lambda r: (r["kickoff"], -r["last"]["edge"]))[:40],
    }


def report(args=None) -> None:
    s = summary()
    print(f"{s['logged']} Paddy Power lines logged, {s['settled']} settled, "
          f"{s['open']} open, {s['void']} void\n")
    for name, b in (("Every line", s["all"]), ("Value bets (edge 5%+, ours 50%+)", s["value"]),
                    ("Strong lines (ours 70%+)", s["strong"])):
        print(f"{name:36} {b['n']:>5} bets  hit {b['hit']:.0%} (said {b['said']:.0%})  "
              f"profit {b['profit']:+.1f}u  ROI {b['roi']:+.1%}")
    c = s["clv"]
    print(f"\nPrice moves on value bets: {c['beat']} shortened, {c['lost']} drifted, "
          f"average {c['avg']:+.1%}")
    print("\nValue bets by market")
    for k, b in s["value_by_market"].items():
        print(f"   {k:44} n={b['n']:<4} hit {b['hit']:.0%} said {b['said']:.0%}  ROI {b['roi']:+.1%}")
    print("\nCalibration (every line)")
    for k, b in s["by_band"].items():
        print(f"   said {k:8} n={b['n']:<5} landed {b['hit']:.0%}")


# ------------------------------------------------------------------ page

def _pct(x, sign=False):
    return f"{x:+.0%}" if sign else f"{x:.0%}"


def _cls(x):
    return "pos" if x > 0.0001 else "neg" if x < -0.0001 else ""


def page(args=None) -> Path:
    s = summary()
    e = html.escape

    def card(title, b, note):
        return f"""<div class="card"><h3>{e(title)}</h3>
          <div class="big {_cls(b['profit'])}">{b['profit']:+.1f}u</div>
          <div class="sub">{b['n']} bets &middot; {b['won']} won &middot; hit {_pct(b['hit'])}
            (said {_pct(b['said'])}) &middot; ROI <b class="{_cls(b['roi'])}">{_pct(b['roi'], True)}</b></div>
          <p>{note}</p></div>"""

    def table(rows, cols):
        head = "".join(f"<th>{c}</th>" for c in cols)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"

    def bet_row(r, snap):
        s_ = r[snap]
        res = r["result"] or "open"
        val = "" if r.get("value") is None else f"{r['value']:g}"
        when = time.strftime("%a %d %b %H:%M", time.localtime(r["kickoff"]))
        inj = f' <span class="tag">{e(r["injury"])}</span>' if r.get("injury") else ""
        rec = ("&ndash;" if r.get("k5") is None
               else f"{r['k5']}/{r['n5']} &middot; {r['k10']}/{r['n10']}")
        return (f"<tr><td>{when}</td><td><b>{e(r['player'])}</b>{inj}<br><small>{e(r['fixture'])}</small></td>"
                f"<td>{e(r['stat'])} {e(r['label'])}</td><td>{rec}</td>"
                f"<td>{_pct(s_['chance'])}</td><td>{s_['price']:.2f}</td>"
                f"<td class='{_cls(s_['edge'])}'>{_pct(s_['edge'], True)}</td>"
                f"<td class='res {res}'>{res}{(' (' + val + ')') if val else ''}</td></tr>")

    mk = [f"<tr><td>{e(k)}</td><td>{b['n']}</td><td>{_pct(b['hit'])}</td><td>{_pct(b['said'])}</td>"
          f"<td class='{_cls(b['profit'])}'>{b['profit']:+.1f}u</td><td class='{_cls(b['roi'])}'>{_pct(b['roi'], True)}</td></tr>"
          for k, b in s["value_by_market"].items()]
    bands = [f"<tr><td>{e(k)}</td><td>{b['n']}</td><td>{_pct(b['hit'])}</td></tr>" for k, b in s["by_band"].items()]
    c = s["clv"]
    body = f"""
<h1>Paddy Power results</h1>
<p class="lede">Every Paddy Power player line the site has seen, our chance at the time, and how it landed.
Value bets are lines where ours was 50%+ and beat Paddy Power's price by 5%+, at the price first seen, 1 unit each.
{s['logged']} logged &middot; {s['settled']} settled &middot; {s['open']} open &middot; {s['void']} void (did not play).
Updated {time.strftime('%a %d %b %H:%M')}.</p>
<div class="cards">
{card('Value bets', s['value'], 'The number that matters: would backing what the site flagged have made money?')}
{card('Strong lines (ours 70%+)', s['strong'], 'Hit rate on the lines the site rates most likely, value or not.')}
{card('Every line', s['all'], 'Backing everything Paddy Power offers at their price. Should lose about their margin.')}
<div class="card"><h3>Price moves</h3><div class="big {_cls(c['avg'])}">{_pct(c['avg'], True)}</div>
<div class="sub">{c['beat']} shortened &middot; {c['lost']} drifted, of {c['n']} value bets seen twice</div>
<p>When Paddy Power shortens a price after we flagged it, the market agreed with us. Beating the closing price over time is the best early sign of real value.</p></div>
</div>
<h2>Open value bets</h2>
{table([bet_row(r, 'last') for r in s['open_value']], ['Kick-off', 'Player', 'Line', 'Last 5 · 10', 'Ours', 'Paddy Power', 'Edge', ''])
  if s['open_value'] else '<p class="muted">None right now.</p>'}
<h2>Value bets by market</h2>
{table(mk, ['Market', 'Bets', 'Hit', 'Said', 'Profit', 'ROI']) if mk else '<p class="muted">Nothing settled yet.</p>'}
<h2>Is the model honest? Every line</h2>
{table(bands, ['Ours said', 'Lines', 'Actually hit']) if bands else '<p class="muted">Nothing settled yet.</p>'}
<h2>Recent value bets</h2>
{table([bet_row(r, 'first') for r in s['recent_value']], ['Kick-off', 'Player', 'Line', 'Last 5 · 10', 'Ours', 'Paddy Power', 'Edge', 'Result'])
  if s['recent_value'] else '<p class="muted">Nothing settled yet.</p>'}
"""
    PAGE.write_text(f"""<!doctype html><html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Paddy Power results</title>
<style>
:root {{ --bg:#f9f9f7; --card:#fff; --tx:#0b0b0b; --mu:#6b6a66; --bd:rgba(0,0,0,.1); --pos:#0a8f3c; --neg:#c43a3a; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#0d0d0d; --card:#1a1a19; --tx:#fff; --mu:#a5a49d; --bd:rgba(255,255,255,.1); --pos:#3ccf73; --neg:#ff6b6b; }} }}
body {{ margin:0; background:var(--bg); color:var(--tx); font:15px/1.45 -apple-system,system-ui,sans-serif; }}
main {{ max-width:1100px; margin:0 auto; padding:24px 16px 60px; }}
a {{ color:inherit; }} h1 {{ font-size:28px; margin:8px 0; }} h2 {{ font-size:18px; margin:28px 0 10px; }}
.lede, .muted, small {{ color:var(--mu); }}
.cards {{ display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); }}
.card {{ background:var(--card); border:1px solid var(--bd); border-radius:12px; padding:14px; }}
.card h3 {{ margin:0 0 6px; font-size:13px; text-transform:uppercase; letter-spacing:.06em; color:var(--mu); }}
.card p {{ font-size:13px; color:var(--mu); margin:8px 0 0; }}
.big {{ font-size:30px; font-weight:750; }} .sub {{ font-size:13px; }}
.pos {{ color:var(--pos); }} .neg {{ color:var(--neg); }}
table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--bd); border-radius:12px; overflow:hidden; font-size:13.5px; }}
th {{ text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--mu); padding:9px 10px; border-bottom:1px solid var(--bd); }}
td {{ padding:8px 10px; border-bottom:1px solid var(--bd); vertical-align:top; }}
.res.win {{ color:var(--pos); font-weight:700; }} .res.lose {{ color:var(--neg); font-weight:700; }} .res.open {{ color:var(--mu); }}
.tag {{ font-size:11px; border:1px solid var(--neg); color:var(--neg); border-radius:999px; padding:0 6px; }}
@media (max-width:700px) {{ table {{ display:block; overflow-x:auto; }} }}
</style></head><body><main><p><a href="index.html">&larr; All fixtures</a></p>{body}</main></body></html>""",
                    encoding="utf-8")
    return PAGE


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["snapshot", "settle", "report", "page"])
    args = ap.parse_args()
    {"snapshot": snapshot, "settle": settle, "report": report,
     "page": lambda a=None: print("wrote", page())}[args.cmd]()


if __name__ == "__main__":
    main()
