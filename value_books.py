#!/usr/bin/env python3
"""Value at Paddy Power, Bet365 or Sky Bet: one list, the same rules for every book.

Sky Bet added 30 Oct 2026: owned by Flutter like Paddy Power but priced by its own
traders, so it is a separate chance of a long price, read from the same Oddschecker reply.

    python value_books.py            # build reports/value_books.json and log what qualifies (publish.sh)
    python value_books.py settle     # settle logged bets that have finished (publish.sh)
    python value_books.py report     # print tonight's list and the record

30 Oct 2026, Zac: "I want lines that are value on either Paddy or 365 ... and
it has to be in line with the model". The prices come from Paddy Power's own
feed (paddypower_prices.py) and from Oddschecker (bet365_prices.py, which now
keeps Bet365's and Paddy Power's price for every line). The better of the two
is the price; a line qualifies only if:

  player lines   our model (fmodel.json) makes it 50%+ and its chance times the
                 price is 1.05 or more, and, where Betfair prices the same line,
                 Betfair's chance times the price is at least 0.98 (the sharp
                 market must not say the price is short);
  corners, cards and goals
                 Pinnacle's margin-free chance times the price is over 1.00
                 (the price beats the sharpest book), and the model agrees
                 (its chance times the price is 1.00 or more).

One line per player (two legs on one player land together). Football only:
Oddschecker's NBA and NFL pages do not list matches the way discovery reads.
Every line listed is logged to value/log.jsonl with the price first seen and
settled after the game, so the section carries its own record.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "reports" / "value_books.json"
LOG = ROOT / "value" / "log.jsonl"
OC_ALL = ROOT / "reports" / "oddschecker_all.json"
FMODEL = ROOT / "reports" / "fmodel.json"

PLAYER_MIN_P = 0.50
PLAYER_MIN_EDGE = 0.05
SHARP_FLOOR = 0.98          # Betfair's chance x price must be at least this
MAX_PRICE = 6.0
BOOK_NAME = {"B3": "Bet365", "PP": "Paddy Power", "SK": "Sky Bet"}
PIN_STATS = {"Corner kicks", "Yellow cards", "Goals"}
MODEL_ONLY_MIN_P = 0.45     # stats no sharp book prices: our number alone
MODEL_ONLY_EDGE = 0.10
MODEL_ONLY_MAX_PRICE = 4.0
MODEL_ONLY_MAX_EDGE = 0.25  # a bigger "edge" with no sharp check is our number being wrong
PIN_SANITY = 1.30           # price x Pinnacle's chance above this: a mismatched line, dropped


def _load(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def _norm(s):
    import sharp
    return sharp.norm(s or "")


def _short(s):
    import sharp
    return sharp._short(s or "")


# ------------------------------------------------------------ prices

def candidates(now: float) -> list[dict]:
    """Every priced line on upcoming football games: Oddschecker rows (Bet365 and
    Paddy), plus Paddy's own feed where Oddschecker has no row."""
    import bettable
    oc = (_load(OC_ALL).get("events") or {})
    ppix = bettable.index()
    out, seen = [], set()
    for fid, ev in oc.items():
        if not now < ev.get("kickoff", 0):
            continue
        for r in ev.get("rows") or []:
            books = dict(r.get("books") or {})
            pp = ppix.get(fid) or {}
            if r.get("player"):
                for who in (_norm(r["player"]), _short(r["player"])):
                    p = (pp.get("players") or {}).get((who, r["stat"], float(r["line"]), bool(r["over"])))
                    if p:
                        books["PP"] = max(books.get("PP", 0), p)
                        break
            if not books:
                continue
            row = dict(r, fid=fid, kickoff=ev["kickoff"], game=ev.get("name") or "",
                       home=ev.get("home") or "", away=ev.get("away") or "", books=books)
            out.append(row)
            seen.add((fid, r.get("key") or r.get("scope"), r["stat"], r["line"], r["over"]))
    # Paddy-only team lines (corners, cards, goals) where Oddschecker has none
    for fid, ev in (_load(ROOT / "reports" / "paddypower.json").get("events") or {}).items():
        if not now < ev.get("kickoff", 0):
            continue
        for l in (ev.get("team") or []) + (ev.get("goals") or []):
            if l["stat"] not in PIN_STATS or (fid, l["scope"], l["stat"], l["line"], l["over"]) in seen:
                continue
            out.append({"fid": fid, "kickoff": ev["kickoff"], "game": ev.get("name") or "",
                        "home": ev.get("ppHome") or "", "away": ev.get("ppAway") or "",
                        "stat": l["stat"], "scope": l["scope"], "line": l["line"], "over": l["over"],
                        "books": {"PP": l["price"]}})
    return out


# ------------------------------------------------------------ chances

def _fmodel_player(fm: dict, fid: str, name: str):
    """(SofaScore name, lines) for an Oddschecker player name, or None if unsure."""
    ev = (fm.get("events") or {}).get(fid) or {}
    players = ev.get("players") or {}
    n, sh = _norm(name), _short(name)
    exact = [k for k in players if _norm(k) == n]
    if len(exact) == 1:
        return exact[0], players[exact[0]]
    short = [k for k in players if _short(k) == sh]
    if len(short) == 1:
        return short[0], players[short[0]]
    return None


def model_player(fm, r):
    got = _fmodel_player(fm, r["fid"], r["player"])
    if not got:
        return None, None
    name, pl = got
    k = r["line"] + 0.5
    p = ((pl.get("lines") or {}).get(r["stat"]) or {}).get(str(int(k)))
    if not isinstance(p, (int, float)):
        return name, None
    return name, (p if r["over"] else 1 - p)


def betfair_player(ix, r, name):
    import sharp
    if not r["over"]:
        return None
    ev = ix.get(r["fid"]) or {}
    for who in (_norm(name), _short(name), _norm(r["player"])):
        v = ev.get((who, r["stat"], float(r["line"]), True))
        if v:
            return v["p"]
    return None


def team_side_name(r):
    return "Match" if r["scope"] == "match" else (r["home"] if r["scope"] == "home" else r["away"])


def pinnacle_team(r):
    import bettable
    leg = {"team": None if r["scope"] == "match" else team_side_name(r)}
    return bettable.pinnacle_chance(leg, {"id": r["fid"]}, r["stat"], r["line"], r["over"],
                                    "match" if r["scope"] == "match" else "side")


def model_team(rows_by_key, r):
    """The team log's chance for the same line (sharp.model_p: the team model, or
    a Poisson on the expected count), matched by side name, not by order."""
    import sharp
    side = team_side_name(r)
    for row in rows_by_key.get((r["fid"], r["stat"], r["line"], r["over"]), []):
        if r["scope"] == "match" and row.get("scope") == "match":
            return sharp.model_p(row)
        if r["scope"] != "match" and row.get("scope") != "match":
            a, b = set(_norm(side).split()), set(_norm(row.get("team")).split())
            if a & b:
                return sharp.model_p(row)
    return None


# ------------------------------------------------------------ the list

def build(now: float | None = None) -> list[dict]:
    import sharp
    import teamlog
    now = time.time() if now is None else now
    fm = _load(FMODEL)
    try:
        bfix = sharp.index()
    except Exception:  # noqa: BLE001
        bfix = {}
    tl = {}
    for p in teamlog._files():
        for row in teamlog._read(p):
            if row.get("result") is None and row.get("kickoff", 0) > now:
                tl.setdefault((str(row["event_id"]), row["stat"], float(row["line"]), bool(row["over"])), []).append(row)
    bets = []
    for r in candidates(now):
        book = max(r["books"], key=r["books"].get)
        price = r["books"][book]
        if not 1.2 <= price <= MAX_PRICE:
            continue
        other = {k: v for k, v in r["books"].items() if k != book}
        item = {"fid": r["fid"], "kickoff": r["kickoff"], "game": r["game"], "stat": r["stat"],
                "line": r["line"], "over": r["over"], "book": book, "price": price, "other": other}
        if r.get("player"):
            name, p = model_player(fm, r)
            if p is None or p < PLAYER_MIN_P or p * price < 1 + PLAYER_MIN_EDGE:
                continue
            bf = betfair_player(bfix, r, name)
            if bf is not None and bf * price < SHARP_FLOOR:
                continue
            item.update(player=name, oc_player=r["player"], p=round(p, 4), sharp=bf, sharp_src="betfair" if bf else None)
        elif r["stat"] not in PIN_STATS:
            # Offsides, shots, fouls, throw-ins and the rest (30 Oct 2026): no
            # sharp book prices them, so it is our number alone, with a wider
            # margin, and shown apart as unproven until the record says otherwise.
            mp = model_team(tl, r)
            if mp is None or mp < MODEL_ONLY_MIN_P or mp * price < 1 + MODEL_ONLY_EDGE or price > MODEL_ONLY_MAX_PRICE:
                continue
            if mp * price > 1 + MODEL_ONLY_MAX_EDGE:
                continue      # the whole market against our number by this much: trust the market
            item.update(team=team_side_name(r), scope=r["scope"], p=round(mp, 4), sharp=None,
                        sharp_src="model only")
        else:
            pin = pinnacle_team(r)
            if not pin or pin * price <= 1.0:
                continue
            if pin * price > PIN_SANITY:
                continue      # 30%+ over Pinnacle is a mismatched line or side, not value
            mp = model_team(tl, r)
            if mp is None or mp * price < 1.0:
                continue
            item.update(team=team_side_name(r), scope=r["scope"], p=round(mp, 4), sharp=round(pin, 4),
                        sharp_src="pinnacle")
        item["edge"] = round(item["p"] * price - 1, 4)
        item["sharp_edge"] = round(item["sharp"] * price - 1, 4) if item.get("sharp") else None
        bets.append(item)
    # one line per player: the biggest edge
    best = {}
    for b in bets:
        k = (b["fid"], b.get("player") or f"{b.get('team')}|{b['stat']}|{b['over']}")
        if k not in best or b["edge"] > best[k]["edge"]:
            best[k] = b
    return sorted(best.values(), key=lambda b: (-(b.get("sharp_edge") or 0), -b["edge"]))


def key(b) -> str:
    return f"{b['fid']}|{b.get('player') or b.get('team')}|{b['stat']}|{b['line']}|{int(b['over'])}"


def log(bets: list[dict], now: float) -> int:
    LOG.parent.mkdir(exist_ok=True)
    rows = [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()] if LOG.exists() else []
    have = {r["key"]: r for r in rows}
    new = 0
    for b in bets:
        k = key(b)
        snap = {"t": round(now), "book": b["book"], "price": b["price"], "p": b["p"], "sharp": b.get("sharp")}
        if k in have:
            if have[k].get("result") is None and b["kickoff"] > now:
                have[k]["last"] = snap
            continue
        row = dict(b, key=k, first=snap, last=snap, result=None, value=None, logged_at=round(now))
        rows.append(row); have[k] = row; new += 1
    LOG.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return new


def run() -> int:
    now = time.time()
    bets = build(now)
    OUT.write_text(json.dumps({"generated": now, "bets": bets}, separators=(",", ":")))
    new = log(bets, now)
    print(f"  value books: {len(bets)} line(s) qualify, {new} new logged")
    return 0


# ------------------------------------------------------------ settle and record

def settle() -> int:
    import besttrack
    import hitrates
    import sofascore_api as api
    if not LOG.exists():
        return 0
    rows = [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]
    now, done, cache = time.time(), 0, {}
    for r in rows:
        if r.get("result") is not None or r["kickoff"] > now - 3 * 3600:
            continue
        eid = int(r["fid"])
        if eid not in cache:
            ev = (api.get_json(f"event/{eid}", max_age_hours=1, verbose=False) or {})
            ev = ev.get("event", ev)
            fin = (ev.get("status") or {}).get("type") == "finished"
            cache[eid] = (ev, hitrates.extract_match_stats(api.event_statistics(eid)) if fin and not r.get("player") else None)
        ev, stats = cache[eid]
        st = (ev.get("status") or {}).get("type")
        if st in ("canceled", "postponed"):
            r["result"] = "void"; done += 1
            continue
        if st != "finished":
            continue
        if r.get("player"):
            v = besttrack._player_value({"event_id": eid, "player": r["player"], "kickoff": r["kickoff"],
                                         "stat": r["stat"]}, "football")
            if v == "dnp":
                r["result"] = "void"; done += 1
                continue
        else:
            if stats is None:
                stats = hitrates.extract_match_stats(api.event_statistics(eid))
                cache[eid] = (ev, stats)
            home, away = (ev.get("homeTeam") or {}).get("name"), (ev.get("awayTeam") or {}).get("name")
            leg = lambda team: {"team": team, "period": "ALL", "stat": r["stat"]}  # noqa: E731
            if r.get("scope") == "match":
                a, b = besttrack._team_value(leg(home), ev, stats), besttrack._team_value(leg(away), ev, stats)
                v = None if a is None or b is None else a + b
            else:
                side = home if set(_norm(r["team"]).split()) & set(_norm(home).split()) else away
                v = besttrack._team_value(leg(side), ev, stats)
        if v is None:
            continue
        r["value"] = v
        r["result"] = "win" if (v > r["line"] if r["over"] else v < r["line"]) else "lose"
        done += 1
    LOG.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"  value books: settled {done} line(s)")
    return done


def record() -> dict:
    rows = [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()] if LOG.exists() else []
    by = {}
    for r in rows:
        if r.get("result") not in ("win", "lose"):
            continue
        price = r["first"]["price"]
        pr = price - 1 if r["result"] == "win" else -1.0
        kind = "player" if r.get("player") else "model only" if r.get("sharp_src") == "model only" else "team"
        for k in ("all", kind, BOOK_NAME.get(r["first"]["book"], r["first"]["book"]), f"stat:{r['stat']}"):
            g = by.setdefault(k, {"n": 0, "w": 0, "profit": 0.0, "said": 0.0})
            g["n"] += 1; g["w"] += r["result"] == "win"; g["profit"] += pr; g["said"] += r["first"]["p"]
    return by


def box(now: float, until: float) -> str:
    """The tonight-page section: tonight's list, and the record it has earned."""
    import html
    esc = html.escape
    bets = [b for b in (_load(OUT).get("bets") or []) if now < b["kickoff"] <= until]
    rec = record().get("all")
    so_far = (f"{rec['n']} settled, {rec['w']} won (the model said {rec['said']:.0f}), "
              f"{rec['profit']:+.1f} pts at level stakes" if rec else "nothing settled yet: logging started 30 Oct 2026")
    if not bets:
        return (f"<p class='none'>Nothing at Paddy Power, Bet365 or Sky Bet clears the bar in this window.</p>"
                f"<p class='sub'>Record so far: {so_far}.</p>")
    rows = []
    for b in bets[:12]:
        ko = time.strftime("%H:%M", time.localtime(b["kickoff"]))
        who = b.get("player") or b.get("team")
        stat = b["stat"].lower()
        sel = (f"{who} {int(b['line'] + 0.5)}+ {stat}" if b.get("player") and b["over"]
               else f"{who} {'over' if b['over'] else 'under'} {b['line']} {stat}")
        other = " &middot; ".join(f"{BOOK_NAME.get(k, k)} {v:.2f}" for k, v in b["other"].items())
        sharp = ("model only, no sharp price" if b.get("sharp_src") == "model only"
                 else f"Pinnacle {1 / b['sharp']:.2f}" if b.get("sharp_src") == "pinnacle"
                 else f"Betfair {1 / b['sharp']:.2f}" if b.get("sharp") else "no sharp price")
        rows.append(
            f"<tr><td>{esc(sel)}<div class='sub'>{ko} &middot; {esc(b['game'])}"
            f"{' &middot; ' + other if other else ''} &middot; {sharp}</div></td>"
            f"<td class='n'><b>{b['price']:.2f}</b><div class='sub'>{BOOK_NAME.get(b['book'], b['book'])}</div></td>"
            f"<td class='n'>{1 / b['p']:.2f}</td><td class='n'>{b['edge'] * 100:+.0f}%</td></tr>")
    return ("<table><thead><tr><th>Bet</th><th class='n'>Best price</th><th class='n'>Fair</th>"
            "<th class='n'>Edge</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
            "<p class='sub'>The best of Paddy Power, Bet365 and Sky Bet at the last publish, against our model's fair price. "
            "Player lines need the model at 50%+ and 5%+ over the price, and Betfair not saying the price is short; "
            "corners, cards and goals need the price to beat Pinnacle and the model to agree; other team stats (offsides, shots, fouls, "
            "throw-ins and so on) have no sharp price, so they need our number 10%+ over the price and are unproven. One line per player. "
            f"Check the price before betting. Record so far: {so_far}.</p>")


def report() -> None:
    now = time.time()
    for b in build(now)[:30]:
        print(f"{b['edge'] * 100:+5.1f}%  {BOOK_NAME.get(b['book'], b['book']):12} {b['price']:5.2f}  fair {1 / b['p']:5.2f}  "
              f"{b.get('player') or b.get('team')} {'over' if b['over'] else 'under'} {b['line']} {b['stat']}  "
              f"({b['game']}) sharp {b.get('sharp_src') or '-'}")
    for k, g in sorted(record().items()):
        print(f"{k}: {g['n']} bets, {g['w']} won (said {g['said']:.1f}), {g['profit']:+.1f} pts")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    {"run": run, "settle": settle, "report": report}[cmd]()
