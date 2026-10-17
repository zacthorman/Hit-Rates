"""
Betfair Exchange prices for darts, set against the model.

    python darts_market.py          # fetch match odds for the next 48 hours
    python darts_market.py --show   # what is cached, and how it lines up

The darts model rates players on results alone (darts_model.py). It knows
nothing of reputation, practice form, stage nerves or any match outside the
cache, and over 1,723 replayed matches its favourite won 61%. The exchange
knows all of that. So the price the page quotes for the winner is a blend,
leaning on the market, and every other darts market (legs, handicap, scores,
180s) is recomputed from the leg chance that reproduces the blended winner
price, so the whole page agrees with itself.

Where the two disagree by more than the model has earned (FLAG points), the
page says so plainly. On 16 October the model had Niko Springer 60% and the
market had Scott Williams about 55%: a 15-point gap is a warning, not an edge.

Needs .betfair.env (see betfair_api.py). Betfair is reached from the Mac, not
from anywhere else, so this runs in the darts build (darts.sh) or by hand.
Prices land in darts_prices.json; the report build reads that file, so a
rerender picks them up with no requests. Each fetch is also appended to
darts_market_log.json with the model's chance at the time, so the blend
weight can be fitted from results once there are enough (fit_weight below).
"""

from __future__ import annotations

import json
import math
import re
import time
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRICES = HERE / "darts_prices.json"
LOG = HERE / "darts_market_log.json"

DARTS = 3503            # Betfair event type id for darts
MARKET_WEIGHT = 0.75    # share of the market in the blend, on the log-odds scale
FLAG = 0.12             # model and market further apart than this get flagged
FRESH_HOURS = 12


# Letters NFKD does not break down, so "Białecki" folds to bialecki and
# matches Betfair's spelling rather than losing the l.
_EXTRA = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D",
                        "ß": "ss", "æ": "ae", "Æ": "AE", "ı": "i"})


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").translate(_EXTRA)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", " ", s)


def surname(name: str) -> str:
    """SofaScore writes some players as 'Verberk M.' and Betfair as 'Mike
    Verberk', so the comparison is on the surname alone."""
    # Drop initials, then take the last word: "Verberk M." -> verberk,
    # "Mike Verberk" -> verberk, "Sebastian Białecki" -> bialecki.
    words = [w for w in _fold(name).split() if len(w) > 1]
    return words[-1] if words else ""


def fetch(hours: int = 48) -> dict:
    import betfair_api as bf
    bf.login()
    out = {"fetched": time.time(), "matches": []}
    for e in bf.events(DARTS, hours=hours):
        cat = [m for m in bf.markets(e["id"])
               if (m.get("description") or {}).get("marketType") == "MATCH_ODDS"]
        if not cat:
            continue
        book = bf.prices([cat[0]["marketId"]])
        if not book:
            continue
        best = bf.best(book[0])
        runners = []
        for r in cat[0].get("runners", []):
            back, lay, _ = best.get(r["selectionId"], (None, None, None))
            # Mid of back and lay where both exist; the back price alone
            # overstates the chance on thin markets.
            if back and lay and lay / back < 1.3:
                price = (back + lay) / 2
            else:
                price = back or lay
            runners.append({"name": r["runnerName"], "price": price})
        if len(runners) != 2 or not all(r["price"] for r in runners):
            continue
        raw = [1 / r["price"] for r in runners]
        tot = sum(raw)
        for r, q in zip(runners, raw):
            r["p"] = round(q / tot, 4)
        out["matches"].append({"event": e["name"], "start": e.get("openDate"), "runners": runners,
                               "overround": round(tot, 4)})
    PRICES.write_text(json.dumps(out, indent=1))
    return out


def load() -> dict | None:
    try:
        data = json.loads(PRICES.read_text())
    except (OSError, ValueError):
        return None
    if time.time() - data.get("fetched", 0) > FRESH_HOURS * 3600:
        return None
    return data


def market_chance(prices: dict | None, home: str, away: str) -> float | None:
    """The exchange's chance for `home`, margin removed, or None."""
    if not prices:
        return None
    h, a = surname(home), surname(away)
    for m in prices.get("matches", []):
        names = [surname(r["name"]) for r in m["runners"]]
        if names == [h, a]:
            return m["runners"][0]["p"]
        if names == [a, h]:
            return m["runners"][1]["p"]
    return None


def _logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def blend(model_p: float, market_p: float, w: float | None = None) -> float:
    w = MARKET_WEIGHT if w is None else w
    z = w * _logit(market_p) + (1 - w) * _logit(model_p)
    return 1 / (1 + math.exp(-z))


def log_snapshot(rows: list[dict]) -> None:
    """Append (event, model, market) so the weight can be fitted later."""
    try:
        old = json.loads(LOG.read_text()) if LOG.exists() else []
    except ValueError:
        old = []
    seen = {(r["id"], r["fetched"]) for r in old}
    old += [r for r in rows if (r["id"], r["fetched"]) not in seen]
    LOG.write_text(json.dumps(old, indent=0))


def fit_weight(min_settled: int = 100) -> float | None:
    """The market weight that would have scored best, once enough logged
    matches have finished. None until then (MARKET_WEIGHT is used)."""
    try:
        rows = json.loads(LOG.read_text())
        import darts_model
        results = {m["id"]: m for m in darts_model.load_matches() if m["status"] == "finished"}
    except Exception:
        return None
    last = {}
    for r in rows:
        last[r["id"]] = r            # the snapshot nearest kick-off
    data = []
    for eid, r in last.items():
        m = results.get(eid)
        if m and isinstance(m["sa"], int) and isinstance(m["sb"], int):
            data.append((r["model"], r["market"], m["sa"] > m["sb"]))
    if len(data) < min_settled:
        return None
    best = None
    for w in [i / 20 for i in range(21)]:
        ll = 0.0
        for mp, kp, won in data:
            p = min(max(blend(mp, kp, w), 1e-4), 1 - 1e-4)
            ll -= math.log(p if won else 1 - p)
        if best is None or ll < best[0]:
            best = (ll, w)
    return best[1]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--hours", type=int, default=48)
    args = ap.parse_args()
    if args.show:
        data = load()
        if not data:
            print("no fresh prices cached; run without --show")
            return
        print(f"fetched {time.strftime('%d %b %H:%M', time.localtime(data['fetched']))}, "
              f"{len(data['matches'])} matches")
        for m in data["matches"]:
            a, b = m["runners"]
            print(f"  {m['event']:<45} {a['name']} {a['p']:.0%} v {b['name']} {b['p']:.0%}")
        print("fitted market weight:", fit_weight() or f"not enough settled yet, using {MARKET_WEIGHT}")
        return
    data = fetch(args.hours)
    print(f"{len(data['matches'])} darts match(es) priced on the exchange -> {PRICES.name}")


if __name__ == "__main__":
    main()
