"""
Which of the page's betting flags have earned their place? A read-only review.

    python rule_review.py                          # print every table in RULE-REVIEW.md
    python rule_review.py acceptable [--pplog DIR]  # the Paddy Power verdict tiers from pplog/

Every rule on the site that calls a bet value, take, acceptable or a pick is
measured here against what has actually settled, in two ways:

  * the return: each flagged bet backed for one unit at the price shown, after
    commission where it applies, with a 95% interval;
  * the closing price, which needs no results: what the price taken was worth
    at Betfair's last chance before kick-off. A real edge shows as a positive
    number there long before results can show it.

Intervals are percentile bootstraps resampling whole fixtures, because lines
in one match win and lose together (exchange_audit.cluster_boot).

Then the rules that lose are tightened, and the tightening is checked on data
it was not chosen on: every choice is made on fixtures that kicked off before
TEST_FROM, and reported on the fixtures from TEST_FROM to the log's last write.

It reads exchange_log.json, best_bets.json and the Paddy Power record (pplog/
where present, otherwise every committed copy of pp-results.html). It writes
nothing and changes no rule; the rule changes themselves are in weekend.py,
make_index.py, tonight.py and report.py.
"""

from __future__ import annotations

import datetime as dt
import html as htmllib
import json
import math
import re
import subprocess
from collections import defaultdict
from pathlib import Path

import exchange_audit as A

HERE = Path(__file__).resolve().parent
LOG = HERE / "exchange_log.json"
BEST = HERE / "best_bets.json"
PPLOG = HERE / "pplog"
PP_PAGE = HERE / "pp-results.html"

COMMISSION = A.COMMISSION
# The rules as they stood on oct21-work (weekend.py, make_index.py).
SHOWN = 0.005            # make_index.py: "value +n%" above this
VALUE_MIN = 0.03         # weekend.VALUE_MIN: the "Value on Betfair" list
VALUE_PRICE = (1.25, 6.0)
MIN_SAMPLE = 10          # weekend.MIN_SAMPLE
PICK_COUNT_STATS = {"Receiving receptions", "Rushing attempts", "Passing attempts", "Passing completions"}
DISAGREE = 0.15          # weekend.EXCHANGE_DISAGREE
BAD_PRICE = -0.05        # weekend.BAD_PRICE
# Paddy Power (report.py verdictOf, pplog.is_value).
PP_EDGE = 0.05
PP_MIN_P = 0.50

# Choices are made on fixtures before this and checked on fixtures after it.
TEST_FROM = dt.datetime(2026, 10, 19, tzinfo=dt.UTC).timestamp()
# A candidate is adopted only if, on the training fixtures, it flags at least
# this many bets and the lower end of its closing-price interval is above 0.
ADOPT_MIN = 10


def day(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%d %b")


def wilson(k: int, n: int, z: float = 1.96):
    """95% Wilson interval for k successes in n."""
    if n == 0:
        return None, None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


# ------------------------------------------------------------- the bets

def bet_rows(log: dict, res: dict) -> list[dict]:
    """Every logged bet with a back price at first sighting, both sides (an
    over and an under are different bets), whether or not it settled.

    `won` is None unless exchange_audit verified the result. `close` is
    Betfair's chance at the last sighting, kept only where that sighting was
    a second one and came before the log's last write, so it is the last
    price before kick-off rather than a price days out."""
    last_write = max((r.get("last") or {}).get("t", 0) for r in log.values())
    out = []
    for key, r in log.items():
        f = r.get("first") or {}
        if not f.get("back") or f.get("market") is None or f.get("model") is None:
            continue
        info = res[key]
        site = f["anchored"] if f.get("anchored") is not None else f["model"]
        last = r.get("last") or {}
        closes = (r.get("seen", 1) >= 2 and r["kickoff"] <= last_write and last.get("market") is not None
                  and last.get("t", 0) > f.get("t", 0))
        out.append({
            "key": key, "event_id": int(r["event_id"]), "kickoff": r["kickoff"],
            "family": r.get("family"), "kind": r.get("kind"), "stat": r.get("stat"),
            "player": bool(r.get("player")), "over": bool(r["over"]),
            "hits": r.get("hits"), "total": r.get("total"),
            "back": f["back"], "tight": f.get("tight"), "w": f.get("w"),
            "model": f["model"], "site": site, "market": f["market"], "blend": f.get("blend"),
            "value": f.get("value"), "disagree": f.get("disagree"),
            # What the blend said the bet was worth, whether or not the page
            # printed it (it does not where the disagreement flag is up).
            "blend_value": A.ev(f["blend"], f["back"]) if f.get("blend") is not None else None,
            "close": last["market"] if closes else None,
            "won": (info["result"] == "win") if info["ok"] else None,
        })
    return out


def clv(r: dict) -> float:
    return A.ev(r["close"], r["back"])


def ret(r: dict) -> float:
    return A.back_return(r["back"], r["won"])


def mean_or_none(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def measure(rows: list[dict], claim=lambda r: r["blend_value"]) -> dict:
    """Return and closing value of a set of flagged bets."""
    c = [r for r in rows if r["close"] is not None]
    s = [r for r in rows if r["won"] is not None]
    out = {"n": len(rows), "fixtures": len({r["event_id"] for r in rows}),
           "said": mean_or_none(claim(r) for r in rows if claim(r) is not None),
           "betfair_said": mean_or_none(A.ev(r["market"], r["back"]) for r in rows),
           "clv_n": len(c), "clv": None, "clv_lo": None, "clv_hi": None,
           "settled": len(s), "won": sum(1 for r in s if r["won"]),
           "profit": sum(ret(r) for r in s), "roi": None, "roi_lo": None, "roi_hi": None}
    if c:
        out["clv"] = mean_or_none(clv(r) for r in c)
        out["clv_lo"], out["clv_hi"] = A.cluster_boot(c, lambda rs: mean_or_none(clv(r) for r in rs))
    if s:
        out["roi"] = out["profit"] / len(s)
        out["roi_lo"], out["roi_hi"] = A.cluster_boot(s, lambda rs: mean_or_none(ret(r) for r in rs))
    return out


# --------------------------------------------------- the rules, as they were

def page_value(r: dict) -> bool:
    """make_index.py exchangeLine: "value +n%" beside a pick."""
    return r["value"] is not None and r["value"] > SHOWN


def value_list(r: dict) -> bool:
    """weekend.best_value, every filter the log can see. Not applied: the
    last-five check and one bet per fixture, which only shorten the list."""
    return (r["value"] is not None and r["value"] >= VALUE_MIN and r["disagree"] is None
            and (r["total"] or 0) >= MIN_SAMPLE and r["stat"] not in PICK_COUNT_STATS
            and VALUE_PRICE[0] <= r["back"] <= VALUE_PRICE[1])


def blocked_by_disagree(r: dict) -> bool:
    """Bets the 15-point disagreement flag stopped from being called value:
    the blend priced them above the bar, the flag held them back."""
    return r["disagree"] is not None and (r["blend_value"] or 0) > SHOWN


def bad_price(r: dict) -> bool:
    """weekend._headline_ok: out of the headline picks below -5%."""
    return r["value"] is not None and r["value"] < BAD_PRICE


def kept_by_bad_price(r: dict) -> bool:
    """The bets with a value figure that the bad-price guard lets through."""
    return r["value"] is not None and r["value"] >= BAD_PRICE


RULES = (
    ("Page: \"value +n%\" (blend over 0.5% at the back price)", page_value),
    ("Value on Betfair list (3%+, filters)", value_list),
    ("Held back by the 15-point disagreement flag", blocked_by_disagree),
    ("Every bet with a value figure", lambda r: r["value"] is not None),
    ("Bad-price guard: value below -5% (kept out of headline picks)", bad_price),
    ("Let through by the bad-price guard (-5% or better)", kept_by_bad_price),
)


# --------------------------------------------------- tightening, held out

def split(rows: list[dict]):
    train = [r for r in rows if r["kickoff"] < TEST_FROM]
    test = [r for r in rows if r["kickoff"] >= TEST_FROM]
    return train, test


def fit_pooled_weight(rows: list[dict]) -> float:
    """The weight on Betfair that minimises log loss over settled lines,
    one side per line, on these rows only."""
    by = {}
    for r in sorted((r for r in rows if r["won"] is not None), key=lambda r: not r["over"]):
        by.setdefault(r["key"].rsplit("|", 1)[0], r)
    lines = [{"market": r["market"], "anchored": r["site"], "model": r["model"],
              "won": r["won"] if r["over"] else not r["won"]} for r in by.values()]
    # The over side's chances: flip an under that stood in for its line.
    for x, r in zip(lines, by.values()):
        if not r["over"]:
            x["market"], x["anchored"], x["model"] = 1 - r["market"], 1 - r["site"], 1 - r["model"]
    return A.fit_weight(lines) if lines else 1.0


def candidates(train: list[dict]) -> list[tuple[str, object]]:
    """Ways to tighten the value flag. Each returns the value it claims for a
    bet, or None where it claims nothing. None of them looks at results on
    the test fixtures; the one fitted number (the weight) is fitted on train."""
    w = fit_pooled_weight(train)

    def thr(t):
        return lambda r: r["value"] if r["value"] is not None and r["value"] > t else None

    def reweighted(r):
        if r["value"] is None:          # only where the page priced value at all
            return None
        v = A.ev(A.blend(r["market"], r["site"], w), r["back"])
        return v if v > SHOWN else None

    return [
        ("As now: over 0.5%", thr(SHOWN)),
        ("Bar raised to 3%", thr(0.03)),
        ("Bar raised to 6%", thr(0.06)),
        ("Bar raised to 10%", thr(0.10)),
        (f"Blend {w:.2f} on Betfair (fitted on train), over 0.5%", reweighted),
        ("Betfair's chance alone (claims nothing)", lambda r: None),
    ]


def held_out(rows: list[dict]) -> dict:
    train, test = split(rows)
    out = []
    for name, claim in candidates(train):
        a = measure([r for r in train if claim(r) is not None], claim)
        b = measure([r for r in test if claim(r) is not None], claim)
        out.append({"rule": name, "train": a, "test": b})
    adoptable = [x for x in out if x["train"]["clv_n"] >= ADOPT_MIN
                 and x["train"]["clv_lo"] is not None and x["train"]["clv_lo"] > 0]
    choice = max(adoptable, key=lambda x: x["train"]["clv"])["rule"] if adoptable \
        else "Betfair's chance alone (claims nothing)"
    return {"rows": out, "choice": choice,
            "train": (len(train), len({r["event_id"] for r in train})),
            "test": (len(test), len({r["event_id"] for r in test}))}


def claim_vs_close(rows: list[dict]) -> dict:
    """Does a bigger claimed value go with a better closing value? Slope of
    closing value on the value claimed, over every bet with both."""
    c = [r for r in rows if r["close"] is not None and r["value"] is not None]
    if len(c) < 3:
        return {"n": len(c)}

    def slope(rs):
        if len(rs) < 3:
            return None
        mx = sum(r["value"] for r in rs) / len(rs)
        my = sum(clv(r) for r in rs) / len(rs)
        sxx = sum((r["value"] - mx) ** 2 for r in rs)
        return sum((r["value"] - mx) * (clv(r) - my) for r in rs) / sxx if sxx else None
    lo, hi = A.cluster_boot(c, slope)
    return {"n": len(c), "slope": slope(c), "lo": lo, "hi": hi}


# --------------------------------------------------- Paddy Power: take

def pp_rows(folder: Path = PPLOG) -> list[dict]:
    rows = []
    for f in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
        for line in f.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows


# Football player lines where our chance runs high (ACCEPTABLE-CHECK.md):
# acceptable there is a long shot. report.py RUNS_HIGH.
RUNS_HIGH_STATS = {"Fouls", "Fouled", "Tackles"}


def runs_high(stat, line, sport="football", over=True) -> bool:
    return sport == "football" and over is not False and stat in RUNS_HIGH_STATS and (line or 0) >= 1.5


def pp_verdict(p: float, price: float, n: int = 5, heuristic: bool = False, stat: str | None = None,
               line: float | None = None, sport: str = "football", over: bool = True,
               fresh: float | None = None) -> str | None:
    """report.py verdictOf for a player line, in Python, for the tests and
    for scoring pplog: nothing is called take; a price that beats our chance
    by 5% or more is avoid, like one 5% worse; the card estimate and the
    lines where our chance runs high are long shots, never acceptable; and a
    record mostly from before the player's last long break (fresh, the share
    of his window since it, under freshness.STALE_SHARE) is "stale", the
    page's "Old record", never acceptable either."""
    if not (price > 1) or not (p > 0):
        return None
    e = p * price - 1
    if e < -PP_EDGE:
        return "avoid"
    if p < PP_MIN_P:
        return "long"
    if e >= PP_EDGE:
        return "avoid"
    if heuristic or runs_high(stat, line, sport, over):
        return "long"
    import freshness
    if freshness.is_stale(fresh):
        return "stale"
    return "ok"


def pp_verdict_before(p: float, price: float, n: int = 5, heuristic: bool = False,
                      unadjusted: bool = False) -> str | None:
    """report.py verdictOf as it stood on oct21-work, without the stale-data
    and basketball guards (which need the page's data)."""
    if not (price > 1) or not (p > 0):
        return None
    e = p * price - 1
    if e < -PP_EDGE:
        return "avoid"
    if heuristic:
        return "ok" if p >= 0.5 and e >= PP_EDGE else "long"
    if p < PP_MIN_P:
        return "long"
    if e >= PP_EDGE and n >= 5 and not unadjusted:
        return "take"
    return "ok"


def pp_from_log(rows: list[dict]) -> list[dict]:
    """Every verdict, before and after this review, on the Paddy Power record
    itself, on the fixtures before TEST_FROM and from it."""
    done = [r for r in rows if r.get("result") in ("win", "lose") and (r.get("first") or {}).get("price")]
    for r in done:
        f = r["first"]
        r["_ret"] = (f["price"] - 1) if r["result"] == "win" else -1.0
        r["_before"] = pp_verdict_before(f["chance"], f["price"], r.get("n10") or 0)
        r["_after"] = pp_verdict(f["chance"], f["price"], r.get("n10") or 0)
    out = []
    for period, sel in (("train", [r for r in done if r["kickoff"] < TEST_FROM]),
                        ("test", [r for r in done if r["kickoff"] >= TEST_FROM])):
        for when in ("_before", "_after"):
            for verdict in ("take", "ok"):
                bets = [r for r in sel if r[when] == verdict]
                lo, hi = A.cluster_boot(bets, lambda rs: mean_or_none(x["_ret"] for x in rs)) \
                    if bets else (None, None)
                out.append({"period": period, "when": when.strip("_"), "verdict": verdict, "n": len(bets),
                            "won": sum(1 for r in bets if r["result"] == "win"),
                            "said": mean_or_none(r["first"]["chance"] for r in bets),
                            "roi": mean_or_none(r["_ret"] for r in bets), "lo": lo, "hi": hi})
    return out


# --------------------------------------------------- Paddy Power: acceptable

PRICE_BANDS = ((1.0, 1.5), (1.5, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, 1e9))
VERDICT_NAMES = {"ok": "acceptable", "long": "long shot", "avoid": "avoid"}


def price_band(price: float) -> str:
    for lo, hi in PRICE_BANDS:
        if lo <= price < hi:
            return f"{lo:.2f}-{hi:.2f}" if hi < 1e8 else f"{lo:.2f}+"
    return "?"


def acceptable_rows(rows: list[dict]) -> list[dict]:
    """Every settled pplog line with the verdict the page gives it now, at
    the price and chance first seen."""
    out = []
    for r in rows:
        f = r.get("first") or {}
        if r.get("result") not in ("win", "lose") or not f.get("price") or f.get("chance") is None:
            continue
        v = pp_verdict(f["chance"], f["price"], r.get("n10") or 0, heuristic=r.get("stat") == "Card",
                       stat=r.get("stat"), line=r.get("line"), sport=r.get("sport") or "football",
                       over=r.get("over", True))
        if v is None:
            continue
        last = (r.get("last") or {}).get("price")
        out.append({"event_id": r["event_id"], "kickoff": r["kickoff"], "sport": r.get("sport") or "football",
                    "stat": r.get("stat"), "side": "over" if r.get("over", True) else "under",
                    "verdict": v, "p": f["chance"], "price": f["price"], "won": r["result"] == "win",
                    "ret": (f["price"] - 1) if r["result"] == "win" else -1.0,
                    "shortened": (last < f["price"]) if last and f.get("t") != (r.get("last") or {}).get("t") else None,
                    "source": f.get("source") or "site"})
    return out


def acceptable_block(rows: list[dict]) -> dict:
    """Landed against said and the return at the price first seen, with 95%
    intervals resampling whole fixtures."""
    if not rows:
        return {"n": 0}
    n = len(rows)
    out = {"n": n, "won": sum(r["won"] for r in rows), "said": sum(r["p"] for r in rows) / n,
           "profit": sum(r["ret"] for r in rows)}
    out["landed"] = out["won"] / n
    out["gap"] = out["landed"] - out["said"]
    out["roi"] = out["profit"] / n
    out["gap_lo"], out["gap_hi"] = A.cluster_boot(rows, lambda rs: (sum(r["won"] for r in rs) - sum(r["p"] for r in rs))
                                                  / len(rs) if rs else None, n=1000)
    out["roi_lo"], out["roi_hi"] = A.cluster_boot(rows, lambda rs: sum(r["ret"] for r in rs) / len(rs) if rs else None,
                                                  n=1000)
    seen = [r["shortened"] for r in rows if r["shortened"] is not None]
    out["shortened"] = sum(seen) / len(seen) if seen else None
    return out


def acceptable_scoreboard(rows: list[dict]) -> str:
    """The verdict tiers on the Paddy Power record: by verdict, then by sport,
    stat and price band within each, and the earlier and later halves of the
    record by kick-off."""
    A_rows = acceptable_rows(rows)
    if not A_rows:
        return "No settled Paddy Power lines in pplog/."
    head = ["Bets", "Won", "Said", "Landed", "Landed minus said", "95%", "Profit", "ROI", "95%",
            "Price shortened"]

    def cells(b):
        if not b.get("n"):
            return [0] + ["-"] * 9
        return [b["n"], b["won"], pct(b["said"], False), pct(b["landed"], False), pct(b["gap"]),
                iv(b["gap_lo"], b["gap_hi"]), f"{b['profit']:+.1f}u", pct(b["roi"]), iv(b["roi_lo"], b["roi_hi"]),
                pct(b["shortened"], False) if b["shortened"] is not None else "-"]

    ko = sorted(r["kickoff"] for r in A_rows)
    mid = ko[len(ko) // 2]
    out = [f"{len(A_rows):,} settled Paddy Power lines, verdicts as the page gives them now, at the price first seen. "
           f"Earlier half: kick-off before {day(mid)}; later half: from it.\n"]
    rows_out = []
    for v in ("ok", "long", "avoid"):
        for label, sel in (("all", lambda r: True), ("earlier", lambda r: r["kickoff"] < mid),
                           ("later", lambda r: r["kickoff"] >= mid)):
            rows_out.append([VERDICT_NAMES[v], label] + cells(acceptable_block(
                [r for r in A_rows if r["verdict"] == v and sel(r)])))
    out.append(table(["Verdict", "Half"] + head, rows_out))
    for title, key in (("sport", lambda r: r["sport"]), ("stat", lambda r: f"{r['sport']} · {r['stat']} {r['side']}"),
                       ("price band", lambda r: price_band(r["price"])), ("chance from", lambda r: r["source"])):
        groups = defaultdict(list)
        for r in A_rows:
            if r["verdict"] == "ok":
                groups[key(r)].append(r)
        out.append(f"\nAcceptable by {title}:\n")
        out.append(table([title.capitalize()] + head,
                         [[k] + cells(acceptable_block(g)) for k, g in sorted(groups.items(), key=lambda kv: -len(kv[1]))]))
    return "\n".join(out)


def _text(s: str) -> str:
    t = re.sub(r"<[^>]+>", " | ", s)
    return re.sub(r"(\s*\|\s*)+", " | ", htmllib.unescape(t))


def parse_pp_page(s: str) -> dict:
    """The scoreboard numbers pplog.page() prints: value bets, every line,
    value bets by market, and the calibration bands."""
    t = _text(s[s.find("<body"):] if "<body" in s else s)
    out = {}
    m = re.search(r"Updated (\w{3} \d+ \w{3} \d\d:\d\d)", t)
    out["updated"] = m.group(1) if m else None
    m = re.search(r"(\d+) logged · (\d+) settled · (\d+) open · (\d+) void", t)
    if m:
        out["logged"], out["settled"], out["open"], out["void"] = (int(g) for g in m.groups())
    for name, label in (("value", "Value bets"), ("strong", r"Strong lines \(ours 70%\+\)"), ("all", "Every line")):
        m = re.search(label + r" \| ([+-][\d.]+)u \| (\d+) bets · (\d+) won · hit (\d+)%\s*\(said (\d+)%\) · ROI \| ([+-]?\d+)%", t)
        if m:
            out[name] = {"profit": float(m.group(1)), "n": int(m.group(2)), "won": int(m.group(3)),
                         "hit": int(m.group(4)) / 100, "said": int(m.group(5)) / 100, "roi": int(m.group(6)) / 100}
    i, j = t.find("Value bets by market"), t.find("Is the model honest")
    out["by_market"] = []
    if i >= 0 and j > i:
        for m in re.finditer(r"\| ([\w-]+) · ([^|]+?) (over|under) \| (\d+) \| (\d+)% \| (\d+)% \| ([+-][\d.]+)u \| ([+-]?\d+)%",
                             t[i:j]):
            out["by_market"].append({"sport": m.group(1), "stat": m.group(2), "side": m.group(3),
                                     "n": int(m.group(4)), "hit": int(m.group(5)) / 100,
                                     "said": int(m.group(6)) / 100, "profit": float(m.group(7))})
    k = t.find("Recent value bets")
    out["bands"] = []
    if j >= 0:
        for m in re.finditer(r"\| (\d+)-(\d+)% \| (\d+) \| (\d+)%", t[j:k if k > j else None]):
            out["bands"].append({"band": f"{m.group(1)}-{m.group(2)}%", "lo": int(m.group(1)) / 100,
                                 "hi": int(m.group(2)) / 100, "n": int(m.group(3)), "hit": int(m.group(4)) / 100})
    return out


def pp_pages_from_git(path: str = "pp-results.html") -> list[dict]:
    """Every committed copy of the Paddy Power page, oldest first."""
    try:
        shas = subprocess.run(["git", "log", "--format=%H", "--", path], cwd=HERE, capture_output=True,
                              text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        shas = []
    pages = []
    for sha in reversed(shas):
        try:
            s = subprocess.run(["git", "show", f"{sha}:{path}"], cwd=HERE, capture_output=True,
                               text=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            continue
        p = parse_pp_page(s)
        p["commit"] = sha[:7]
        pages.append(p)
    # A copy whose results a later copy revised (the 21 Oct 00:41 copy graded
    # players 0 from a pre-match line-up; 522 of its voids and many of its
    # losses were re-settled) cannot be differenced against: drop it.
    pages = [p for i, p in enumerate(pages)
             if not any((q.get("void") or 0) < (p.get("void") or 0) for q in pages[i + 1:])]
    if not pages and PP_PAGE.exists():
        p = parse_pp_page(PP_PAGE.read_text())
        p["commit"] = "working tree"
        pages.append(p)
    return pages


def pp_slice(a: dict | None, b: dict) -> dict:
    """The value bets settled between two copies of the page (cumulative
    totals differenced), with a Wilson interval on the hit rate and the ROI
    that interval implies at the slice's own average winning price."""
    a = a or {"n": 0, "won": 0, "profit": 0.0, "said": 0.0}
    n, k = b["n"] - a["n"], b["won"] - a["won"]
    prof = b["profit"] - a["profit"]
    said = (b["said"] * b["n"] - a["said"] * a["n"]) / n if n else None
    lost = n - k
    win_pay = (prof + lost) / k if k else None        # average (price - 1) on the wins
    lo, hi = wilson(k, n)
    out = {"n": n, "won": k, "profit": prof, "roi": prof / n if n else None, "said": said,
           "hit_lo": lo, "hit_hi": hi}
    if win_pay is not None and lo is not None:
        out["roi_lo"] = lo * (win_pay + 1) - 1
        out["roi_hi"] = hi * (win_pay + 1) - 1
    return out


def pp_band_slices(pages: list[dict]) -> list[dict]:
    """The calibration bands of each copy, cumulative totals differenced, so
    each row is only the lines settled since the copy before."""
    out, prev = [], {}
    for p in pages:
        for b in p["bands"]:
            a = prev.get(b["band"], {"n": 0, "hit": 0.0})
            n = b["n"] - a["n"]
            k = round(b["n"] * b["hit"]) - round(a["n"] * a["hit"])
            if n > 0:
                lo, hi = wilson(k, n)
                out.append({"commit": p["commit"], "updated": p["updated"], "band": b["band"],
                            "mid": (b["lo"] + min(b["hi"], 1)) / 2, "n": n, "hit": k / n, "lo": lo, "hi": hi})
        prev = {b["band"]: b for b in p["bands"]}
    return out


def pp_by_sport(page: dict) -> list[dict]:
    by = defaultdict(lambda: {"n": 0, "won": 0, "profit": 0.0, "said": 0.0})
    for m in page["by_market"]:
        x = by[m["sport"]]
        x["n"] += m["n"]
        x["won"] += round(m["n"] * m["hit"])
        x["profit"] += m["profit"]
        x["said"] += m["said"] * m["n"]
    out = []
    for sport, x in sorted(by.items(), key=lambda kv: -kv[1]["n"]):
        lo, hi = wilson(x["won"], x["n"])
        out.append({"sport": sport, "n": x["n"], "won": x["won"], "said": x["said"] / x["n"],
                    "profit": x["profit"], "roi": x["profit"] / x["n"], "lo": lo, "hi": hi})
    return out


def pp_worst_case(page: dict) -> dict:
    """If every football loss among the value bets had really been a win
    (the pre-match line-up hazard that graded players 0), what then?"""
    fb = [m for m in page["by_market"] if m["sport"] == "football"]
    n_fb = sum(m["n"] for m in fb)
    won_fb = sum(round(m["n"] * m["hit"]) for m in fb)
    v = page["value"]
    k = v["won"] + (n_fb - won_fb)
    lo, hi = wilson(k, v["n"])
    return {"football": n_fb, "football_won": won_fb, "won": k, "n": v["n"], "hit": k / v["n"],
            "lo": lo, "hi": hi, "said": v["said"]}


# --------------------------------------------------- headline picks

def picks(path: Path = BEST) -> list[dict]:
    """best_bets.json tickets by category: how often each landed against the
    chance its fair price said. No bookmaker price is recorded with them, so
    the return shown is at the page's own fair price: break-even if the
    chance was right, and the best a bettor could do at any price shorter."""
    tickets = json.loads(path.read_text())
    by = defaultdict(list)
    for t in tickets:
        if t.get("result") not in ("win", "lose") or not t.get("fair") or not t.get("legs"):
            continue
        by[t["category"]].append({"event_id": t["legs"][0]["event_id"], "said": 1 / t["fair"],
                                  "fair": t["fair"], "won": t["result"] == "win",
                                  "snapshot": t.get("snapshot_at")})
    out = []
    for cat, rows in sorted(by.items(), key=lambda kv: -len(kv[1])):
        def gap(rs):
            return (sum(r["won"] for r in rs) - sum(r["said"] for r in rs)) / len(rs) if rs else None
        lo, hi = A.cluster_boot(rows, gap)
        out.append({"category": cat, "n": len(rows), "said": mean_or_none(r["said"] for r in rows),
                    "landed": mean_or_none(r["won"] for r in rows), "gap": gap(rows), "lo": lo, "hi": hi,
                    "at_fair": mean_or_none((r["fair"] - 1) if r["won"] else -1.0 for r in rows)})
    return out


# ------------------------------------------------------------ printing

def pct(x, sign=True, nd=1):
    if x is None:
        return "-"
    return f"{x * 100:+.{nd}f}%" if sign else f"{x * 100:.{nd}f}%"


def iv(lo, hi, sign=True, nd=1):
    return "-" if lo is None else f"{pct(lo, sign, nd)} to {pct(hi, sign, nd)}"


def table(head: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] + ["---:"] * (len(head) - 1)) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def measure_cells(m: dict) -> list:
    return [m["n"], pct(m["said"]), pct(m["betfair_said"]),
            m["clv_n"], pct(m["clv"]), iv(m["clv_lo"], m["clv_hi"]),
            f"{m['won']}/{m['settled']}", pct(m["roi"]), iv(m["roi_lo"], m["roi_hi"])]


MEASURE_HEAD = ["Bets", "Site said", "Betfair said", "Seen at close", "Worth at close", "95%",
                "Won", "ROI", "95%"]


def main(argv=None) -> None:
    import argparse
    a = argparse.ArgumentParser(description="The page's betting rules against what settled.")
    a.add_argument("cmd", nargs="?", choices=("all", "acceptable"), default="all")
    a.add_argument("--pplog", default=str(PPLOG), help="folder of pplog *.jsonl files (default pplog/)")
    args = a.parse_args(argv)
    if args.cmd == "acceptable":
        rows = pp_rows(Path(args.pplog))
        print(acceptable_scoreboard(rows) if rows else f"No pplog files in {args.pplog}.")
        return
    log = json.loads(LOG.read_text())
    res = A.resolve(log, A.load_sources(log))
    rows = bet_rows(log, res)

    print("## 1. Betfair value rules, everything logged (16 to 21 October)\n")
    print(table(["Rule"] + MEASURE_HEAD, [[name] + measure_cells(measure([r for r in rows if pred(r)]))
                                          for name, pred in RULES]))
    s = claim_vs_close(rows)
    print(f"\nClosing value against value claimed: slope {s.get('slope', 0):+.2f} "
          f"(95% {s.get('lo', 0):+.2f} to {s.get('hi', 0):+.2f}) over {s['n']} bets.\n")

    print("## 2. Tightening the value flag, chosen before 19 October, checked after\n")
    h = held_out(rows)
    print(f"Train: {h['train'][0]} bets, {h['train'][1]} fixtures. Test: {h['test'][0]} bets, "
          f"{h['test'][1]} fixtures.\n")
    print(table(["Rule", "Period"] + MEASURE_HEAD,
                [[x["rule"], p] + measure_cells(x[p]) for x in h["rows"] for p in ("train", "test")]))
    print(f"\nChosen on train: {h['choice']}\n")
    before = next(x for x in h["rows"] if x["rule"].startswith("As now"))["test"]
    after = next(x for x in h["rows"] if x["rule"] == h["choice"])["test"]
    print("Before and after, test fixtures only (19 to 21 October):\n")
    print(table(["Value flag", "Bets called value", "Worth at close", "95%", "Won", "Profit"],
                [[label, m["n"], pct(m["clv"]), iv(m["clv_lo"], m["clv_hi"]), f"{m['won']}/{m['settled']}",
                  f"{m['profit']:+.2f}u"] for label, m in (("Before", before), ("After", after))]) + "\n")

    print("## 3. Paddy Power: take (ours 50%+, beats the price by 5%+, five games+)\n")
    log_rows = pp_rows(Path(args.pplog))
    if log_rows:
        print(acceptable_scoreboard(log_rows) + "\n")
        print(table(["Period", "Verdicts", "Verdict", "Bets", "Won", "Said", "ROI", "95%"],
                    [[x["period"], x["when"], x["verdict"], x["n"], x["won"], pct(x["said"], False),
                      pct(x["roi"]), iv(x["lo"], x["hi"])] for x in pp_from_log(log_rows)]) + "\n")
    pages = [p for p in pp_pages_from_git() if p.get("value")]
    prev = None
    sl = []
    for p in pages:
        x = pp_slice(prev, p["value"])
        sl.append([f"{p['commit']} ({p['updated']})", x["n"], x["won"], pct(x["said"], False),
                   f"{pct(x['won'] / x['n'] if x['n'] else None, False)} ({iv(x['hit_lo'], x['hit_hi'], False)})",
                   f"{x['profit']:+.1f}u", pct(x["roi"]), iv(x.get("roi_lo"), x.get("roi_hi"))])
        prev = p["value"]
    print(table(["Settled by", "New bets", "Won", "Said", "Hit (95%)", "Profit", "ROI", "ROI 95% (approx.)"], sl))
    if len(pages) >= 2:
        x = pp_slice(pages[0]["value"], pages[-1]["value"])
        print(f"\nBefore and after, the {x['n']} bets settled after the first copy: before, {x['n']} called take, "
              f"{x['won']} won, {x['profit']:+.1f}u; after, none called take or acceptable (all {x['n']} are avoid), "
              f"so nothing staked on the verdict's say-so.")
    if pages:
        last = pages[-1]
        print("\nBy sport, everything settled by the last copy:\n")
        print(table(["Sport", "Bets", "Won", "Said", "Hit 95%", "Profit", "ROI"],
                    [[x["sport"], x["n"], x["won"], pct(x["said"], False), iv(x["lo"], x["hi"], False),
                      f"{x['profit']:+.1f}u", pct(x["roi"])] for x in pp_by_sport(last)]))
        w = pp_worst_case(last)
        print(f"\nWorst case, every football loss a win: {w['won']}/{w['n']} = {pct(w['hit'], False)} "
              f"(95% {iv(w['lo'], w['hi'], False)}), said {pct(w['said'], False)}.")
        print("\nCalibration of ours on every Paddy Power line, by the copy it first settled in:\n")
        print(table(["Settled by", "Ours said", "Lines", "Hit", "95%"],
                    [[f"{b['commit']} ({b['updated']})", b["band"], b["n"], pct(b["hit"], False, 0),
                      iv(b["lo"], b["hi"], sign=False, nd=0)] for b in pp_band_slices(pages)
                     if b["mid"] >= 0.5]))

    print("\n## 4. Headline picks (best_bets.json)\n")
    print(table(["Category", "Settled", "Said", "Landed", "Landed minus said", "95%", "Return at fair price"],
                [[x["category"], x["n"], pct(x["said"], False), pct(x["landed"], False), pct(x["gap"]),
                  iv(x["lo"], x["hi"]), pct(x["at_fair"])] for x in picks()]))


if __name__ == "__main__":
    main()
