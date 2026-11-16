#!/usr/bin/env python3
"""Bookmaker prices for darts, via Oddschecker, for the darts page.

    python darts_books.py                  # the normal run: find today's matches, fetch, write
    python darts_books.py --markets        # list every market name on the saved match pages
    python darts_books.py --status         # what is held
    python darts_books.py --comp darts/grand-slam-of-darts   # read this competition page as well

Why this exists (14 Nov 2026 audit): the only price the darts page had was
Betfair's match odds. Paddy Power, bet365, Sky Bet and Oddschecker were scraped
for football and the US sports and held no darts at all, so not one of the 261
darts legs in the record carried a bookmaker price and darts could be checked
for calibration but never for profit. This puts the best bookmaker price per
selection beside the page's fair price, and keeps a dated log of them
(darts_books/YYYY-MM.jsonl) so a darts ROI can be worked out later.

How it works, the same way as bet365_prices.py and through the same client
(oddschecker_client.py holds the pacing, the saved cookies and the time
budget, and every request goes direct first and through FlareSolverr second):

  1. Read Oddschecker's darts page(s) and pick out the match links
     (/darts/<event>/<a>-v-<b>/winner).
  2. Match each to one of the site's darts fixtures by the two surnames,
     using the darts events in market_prices.json and the fixtures inside
     reports/darts.html. Only matches starting inside WINDOW_HOURS, never one
     that has started.
  3. Save each new match page once (market ids do not change), read the ids
     of the markets in MARKETS off it, and fetch their odds in batched calls.
  4. Write reports/darts_books.json. report.py attaches it to the darts
     fixtures at build or rerender, and the Match tab shows it.

NOT YET RUN AGAINST THE LIVE SITE. It was written on 14 Nov 2026 from a shell
with no route to Oddschecker, so the page layout it expects is the football
one bet365_prices.py reads. First run: `python darts_books.py --markets` and
check the names against MARKETS below; an unknown name is skipped, never
guessed. Never fatal: any failure leaves the page on Betfair alone.
`touch .darts_books_off` switches it off.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "reports" / "darts_books.json"
LOG_DIR = ROOT / "darts_books"
OFF = ROOT / ".darts_books_off"
PROBE = Path.home() / ".cache" / "oddschecker" / "probe"
MARKET_PRICES = ROOT / "market_prices.json"
DARTS_REPORT = ROOT / "reports" / "darts.html"

BASE = "https://www.oddschecker.com/"
COMPETITIONS = ["darts"]          # the darts front page lists the matches of whatever is on
WINDOW_HOURS = 36
FRESH_HOURS = 3                   # a match is not refetched inside this
FRESH_CLOSE = 0.75                # ...or this, in its last three hours
MAX_NEW_PAGES = 16                # a Grand Slam session is eight matches
MAX_ROWS = 12                     # selections kept per market (correct score has dozens)

# Oddschecker market name (lower case) -> (name shown on the page, kind).
# "winner" is the one the page prices an edge on; the rest are shown as the
# best price per selection. Add a name here once --markets has shown it.
MARKETS = {
    "winner": ("Match winner", "winner"),
    "match betting": ("Match winner", "winner"),
    "match winner": ("Match winner", "winner"),
    "handicap": ("Leg handicap", "handicap"),
    "match handicap": ("Leg handicap", "handicap"),
    "leg handicap": ("Leg handicap", "handicap"),
    "total legs": ("Total legs", "total"),
    "total legs over/under": ("Total legs", "total"),
    "correct score": ("Correct score", "score"),
    "total 180s": ("Match 180s", "total180"),
    "total 180s over/under": ("Match 180s", "total180"),
    "match 180s": ("Match 180s", "total180"),
    "most 180s": ("Most 180s", "most180"),
    "highest checkout": ("Highest checkout", "checkout"),
    "match highest checkout": ("Highest checkout", "checkout"),
    "player 180s": ("Player 180s", "player180"),
    "170 checkout": ("170 checkout", "special"),
    "nine dart finish": ("Nine-dart finish", "special"),
}

# Oddschecker bookmaker codes, as in oddschecker_import.py. Exchanges are
# left out: their prices are before commission.
BOOKS = {
    "B3": "bet365", "SK": "Sky Bet", "PP": "Paddy Power", "WH": "William Hill",
    "FB": "Betfair Sportsbook", "WA": "Betway", "CE": "Coral", "LD": "Ladbrokes",
    "UN": "Unibet", "VC": "BetVictor", "BY": "BoyleSports", "EE": "888sport",
    "FR": "Betfred", "SX": "Spreadex", "QN": "QuinnBet", "MR": "Midnite",
}
EXCHANGES = {"BF", "BD", "MK", "SO", "MA"}

LINK_RE = re.compile(r'href="/(darts/[a-z0-9/-]+?)/([a-z0-9-]+-v-[a-z0-9-]+)/winner"')
MAP_RE = re.compile(r'"urlMap"\s*:\s*"([a-z0-9-]+-v-[a-z0-9-]+)"')
NAME_RE = re.compile(r'"(?:marketTypeName|marketName|displayName|name)"\s*:\s*"([^"]{3,80})"')
ID_RE = re.compile(r'"(?:ocMarketId|marketId)"\s*:\s*"?(\d+)')

_EXTRA = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D",
                        "ß": "ss", "æ": "ae", "Æ": "AE", "ı": "i"})


def say(msg: str) -> None:
    print(f"  darts books: {msg}")


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").translate(_EXTRA)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", " ", s)


def surname(name: str) -> str:
    """Same rule as darts_market.surname: 'Verberk M.' and 'Mike Verberk' and
    the slug 'mike-verberk' all come out as verberk."""
    words = [w for w in fold(name.replace("-", " ")).split() if len(w) > 1]
    return words[-1] if words else ""


# ---------------------------------------------------------------- fixtures

def site_fixtures(now: float | None = None, window: float = WINDOW_HOURS) -> dict[str, dict]:
    """The site's upcoming darts fixtures: {fixture id: {home, away, kickoff}}.

    From the fixtures embedded in reports/darts.html (the page this feeds),
    plus the darts events Betfair matched in market_prices.json."""
    now = time.time() if now is None else now
    out: dict[str, dict] = {}
    try:
        text = DARTS_REPORT.read_text(encoding="utf-8")
        start = text.index("const ALL = ") + len("const ALL = ")
        payload, _ = json.JSONDecoder().raw_decode(text[start:])
        for f in payload.get("fixtures") or []:
            fx = f.get("fixture") or {}
            if fx.get("id") and fx.get("kickoff"):
                out[str(fx["id"])] = {"home": fx.get("home", ""), "away": fx.get("away", ""),
                                      "kickoff": float(fx["kickoff"])}
    except (OSError, ValueError):
        pass
    try:
        events = json.loads(MARKET_PRICES.read_text()).get("events") or {}
    except (OSError, ValueError):
        events = {}
    for fid, e in events.items():
        if not isinstance(e, dict) or e.get("sport") != "darts" or str(fid) in out:
            continue
        names = re.split(r"\s+v\s+", e.get("betfair") or "")
        if len(names) != 2:
            continue
        if e.get("swapped"):
            names.reverse()
        try:
            ko = datetime.fromisoformat((e.get("start") or "").replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        out[str(fid)] = {"home": names[0], "away": names[1], "kickoff": ko}
    return {k: v for k, v in out.items() if now < v["kickoff"] < now + window * 3600}


def match_slug(slug: str, fixtures: dict[str, dict]) -> str | None:
    """The fixture id a slug like 'luke-littler-v-beau-greaves' is, or None.
    Both surnames must agree, in either order; two fixtures agreeing is no match."""
    a, _, b = slug.partition("-v-")
    want = {surname(a), surname(b)}
    if "" in want or len(want) != 2:
        return None
    hits = [fid for fid, f in fixtures.items() if {surname(f["home"]), surname(f["away"])} == want]
    return hits[0] if len(hits) == 1 else None


# ------------------------------------------------------------------- pages

def page_file(url: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", url.lower().split("oddschecker.com")[-1]).strip("-")
    return PROBE / f"{slug}.html"


def match_links(html: str, comp: str) -> dict[str, str]:
    """{slug: match page url} from a competition page, both layouts."""
    out = {slug: f"{BASE}{path}/{slug}/winner" for path, slug in LINK_RE.findall(html)}
    for slug in MAP_RE.findall(html):
        out.setdefault(slug, f"{BASE}{comp}/{slug}/winner")
    return out


def page_markets(html: str) -> dict[str, str]:
    """Every market id -> Oddschecker market name on a saved match page."""
    out: dict[str, str] = {}
    for m in ID_RE.finditer(html):
        n = NAME_RE.search(html, m.end(), m.end() + 800)
        if n and m.group(1) not in out:
            out[m.group(1)] = n.group(1).split("#")[-1].strip()
    return out


def wanted_markets(html: str) -> dict[str, tuple[str, str]]:
    return {mid: MARKETS[name.lower()] for mid, name in page_markets(html).items() if name.lower() in MARKETS}


# ------------------------------------------------------------------- prices

def rows_for(market: dict) -> list[dict]:
    """Best bookmaker price per selection in one all-odds market reply."""
    bets = {b.get("betId"): b for b in market.get("bets", []) if isinstance(b, dict)}
    prices: dict = {}
    for o in market.get("odds", []):
        code = o.get("bookmakerCode")
        if o.get("status") != "ACTIVE" or not o.get("oddsDecimal") or code in EXCHANGES:
            continue
        try:
            prices.setdefault(o.get("betId"), {})[code] = float(o["oddsDecimal"])
        except (TypeError, ValueError):
            continue
    out = []
    for bid, books in prices.items():
        b = bets.get(bid) or {}
        name = (b.get("betName") or "").strip()
        if not name or not books:
            continue
        line = b.get("line")
        try:
            line = float(line) if line not in (None, "") else None
        except (TypeError, ValueError):
            line = None
        best_book = max(books, key=books.get)
        out.append({"selection": name, "line": line, "best": round(books[best_book], 3), "book": best_book,
                    "bookName": BOOKS.get(best_book, best_book), "n": len(books),
                    "books": {k: round(v, 3) for k, v in sorted(books.items())}})
    out.sort(key=lambda r: (r["best"], r["selection"]))
    return out[:MAX_ROWS]


def load_out() -> dict:
    try:
        return json.loads(OUT.read_text())
    except (OSError, ValueError):
        return {"events": {}}


def due(held: dict | None, kickoff: float, now: float) -> bool:
    if not held or not held.get("fetched"):
        return True
    gap = FRESH_CLOSE if kickoff - now < 3 * 3600 else FRESH_HOURS
    return now - held["fetched"] > gap * 3600


def log_rows(fid: str, fixture: dict, markets: list[dict], now: float) -> None:
    """One line per fetch per match, kept for ever: this is the price history
    a darts ROI needs. Append only."""
    LOG_DIR.mkdir(exist_ok=True)
    path = LOG_DIR / f"{datetime.fromtimestamp(now, tz=timezone.utc):%Y-%m}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"t": round(now), "id": fid, "home": fixture["home"], "away": fixture["away"],
                             "kickoff": fixture["kickoff"], "markets": markets}, ensure_ascii=False) + "\n")


def run(comps: list[str], window: float = WINDOW_HOURS, force: bool = False) -> int:
    if OFF.exists():
        say("switched off (.darts_books_off)")
        return 0
    now = time.time()
    fixtures = site_fixtures(now, window)
    if not fixtures:
        say("no darts fixture inside the window, nothing to do")
        return 0
    from oddschecker_client import BudgetExceeded, CloudflareBlocked, OddscheckerClient
    out = load_out()
    events = {k: v for k, v in (out.get("events") or {}).items() if k in fixtures}   # started matches drop out
    PROBE.mkdir(parents=True, exist_ok=True)
    fetched = 0
    try:
        with OddscheckerClient() as client:
            links: dict[str, str] = {}
            for comp in comps:
                try:
                    links.update(match_links(client.get_html(BASE + comp), comp))
                except (CloudflareBlocked, BudgetExceeded):
                    raise
                except Exception as e:  # noqa: BLE001 - one bad page does not stop the others
                    say(f"{comp}: not read ({type(e).__name__}: {e})")
            say(f"{len(links)} match link(s) on {', '.join(comps)}")
            todo = []
            for slug, url in links.items():
                fid = match_slug(slug, fixtures)
                if fid and (force or due(events.get(fid), fixtures[fid]["kickoff"], now)):
                    todo.append((fixtures[fid]["kickoff"], fid, slug, url))
            unmatched = [s for s in links if not match_slug(s, fixtures)]
            if unmatched:
                say(f"{len(unmatched)} link(s) matched no site fixture, e.g. {', '.join(unmatched[:3])}")
            saved = 0
            for _, fid, slug, url in sorted(todo):
                page = page_file(url)
                if not page.exists():
                    if saved >= MAX_NEW_PAGES:
                        continue
                    page.write_text(client.get_html(url), encoding="utf-8")
                    saved += 1
                want = wanted_markets(page.read_text(encoding="utf-8", errors="ignore"))
                if not want:
                    say(f"{slug}: no known market on its page (run --markets and extend MARKETS)")
                    continue
                got = client.get_many(list(want))
                by_name: dict[str, dict] = {}
                for m in got if isinstance(got, list) else [got]:
                    if not isinstance(m, dict):
                        continue
                    mid = str(m.get("marketId") or m.get("ocMarketId") or "")
                    label = want.get(mid) or MARKETS.get((m.get("marketTypeName") or "").lower())
                    rows = rows_for(m)
                    if label and rows and label[0] not in by_name:
                        by_name[label[0]] = {"name": label[0], "kind": label[1], "rows": rows}
                if not by_name:
                    continue
                order = ["winner", "handicap", "total", "total180", "most180", "player180", "checkout", "score", "special"]
                markets = sorted(by_name.values(), key=lambda mk: order.index(mk["kind"]) if mk["kind"] in order else 99)
                events[fid] = {"oc": slug, "fetched": round(now), "kickoff": fixtures[fid]["kickoff"], "markets": markets}
                log_rows(fid, fixtures[fid], markets, now)
                fetched += 1
    except BudgetExceeded:
        say("out of time for this run, keeping what was fetched")
    except CloudflareBlocked as e:
        say(f"blocked by Cloudflare ({e}); keeping what is held")
    except Exception as e:  # noqa: BLE001 - never fatal to the build
        say(f"stopped: {type(e).__name__}: {e}")
    if fetched or events != (out.get("events") or {}):
        OUT.parent.mkdir(exist_ok=True)
        tmp = OUT.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"updated": round(now), "events": events}, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(OUT)
    say(f"{fetched} match(es) priced this run, {len(events)} held -> {OUT.relative_to(ROOT)}")
    return 0


def list_markets() -> int:
    import collections
    names: collections.Counter = collections.Counter()
    pages = sorted(PROBE.glob("darts-*.html")) if PROBE.exists() else []
    for page in pages:
        for name in set(page_markets(page.read_text(errors="ignore")).values()):
            names[name] += 1
    if not pages:
        print("  no darts match page saved yet: run without --markets first")
        return 1
    for name, n in sorted(names.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {n:3}  {'read' if name.lower() in MARKETS else '    '}  {name}")
    return 0


def status() -> None:
    out = load_out()
    events = out.get("events") or {}
    when = time.strftime("%d %b %H:%M", time.localtime(out["updated"])) if out.get("updated") else "never"
    print(f"  darts books: {len(events)} match(es) held, last written {when}")
    for e in events.values():
        print(f"    {e.get('oc', '?'):45} {', '.join(m['name'] for m in e.get('markets', []))}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--comp", action="append", default=[], help="an extra Oddschecker path to read, e.g. darts/grand-slam-of-darts")
    ap.add_argument("--window", type=float, default=WINDOW_HOURS)
    ap.add_argument("--force", action="store_true", help="refetch even if a match was priced recently")
    ap.add_argument("--markets", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    if args.markets:
        return list_markets()
    if args.status:
        status()
        return 0
    return run(COMPETITIONS + [c.strip("/") for c in args.comp], args.window, args.force)


if __name__ == "__main__":
    sys.exit(main())
