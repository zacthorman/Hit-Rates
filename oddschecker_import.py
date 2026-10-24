#!/usr/bin/env python3
"""Best bookmaker prices from Oddschecker pages Zac saves by hand.

    python oddschecker_import.py               # the normal run, from publish.sh
    python oddschecker_import.py --check FILE  # print what one file reads as, write nothing
    python oddschecker_import.py --status      # what is held

No requests at all. Zac opens an Oddschecker odds-comparison page in his own
browser (a goalscorer or player-shots market for one game) and saves it into
drop/oddschecker/, either as the page (File > Save Page As, .html) or as the
table copied and pasted into a .txt file. Each run reads every file there,
takes the best price per player per line across the bookmakers, matches the
game to the site's fixture by team names, and writes reports/oddschecker.json
in the same shape as reports/bet365.json. markets_sidecar.py merges it into
reports/markets.json as "oc", and the player profiles show it as "Best" next
to the fair price.

Optional: with the folder missing or empty nothing is written and nothing on
the pages changes. Never fatal: a file it cannot read is reported and skipped.
Files are never moved or deleted; a file for a game that has started is
ignored, so old ones can be cleared out by hand whenever.

What a file must say:
  * which game: the page's own address (kept in a saved .html), or the file
    name, e.g. arsenal-v-chelsea-anytime-goalscorer.txt
  * which market: the same, from the end of the address or file name. The
    markets read are in MARKETS; anything else is skipped.

Three layouts are read, tried in this order:
  1. Oddschecker's odds table: rows carrying data-bname, cells carrying the
     bookmaker code (data-bk) and the decimal price (data-odig) or the
     fraction (data-o). The bookmaker of the best price is known.
  2. JSON shaped like Oddschecker's all-odds reply (bets and odds lists), as
     a .json file or embedded in the page. Bookmaker known.
  3. Plain text: one player per line, his name then one price per bookmaker
     (fractions, decimals or EVS). The best is the highest; which bookmaker
     it was cannot be told from copied text, so it is shown without one.

Exchange columns (Betfair Exchange and the like) are left out: their prices
are before commission and are not a bookmaker's price.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DROP = ROOT / "drop" / "oddschecker"
OUT = ROOT / "reports" / "oddschecker.json"
SUFFIXES = {".html", ".htm", ".txt", ".json"}
DAYS_AHEAD = 7         # only games kicking off within this are matched

# Oddschecker market (its address slug, and the name on the page) -> the
# market name the pages already parse, as in paddypower_prices.py and
# bet365_prices.py. "{n}" lines need a count per row ("2+" or "Over 1.5").
MARKETS = {
    "anytime-goalscorer": "Anytime Goalscorer",
    "player-shots": "Player To Have {n} Or More Shots",
    "player-shots-on-target": "Player To Have {n} Or More Shots On Target",
    "player-fouls": "Player To Commit {n} Or More Fouls",
    "player-fouls-won": "Player To Be Fouled {n} Or More Times",
    "player-to-be-fouled": "Player To Be Fouled {n} Or More Times",
    "player-tackles": "Player To Make {n} Or More Tackles",
    "player-assists": "Player To Have {n} Or More Assists",
    "to-be-shown-a-card": "Player Shown a Card",
    "player-to-be-carded": "Player Shown a Card",
    "player-cards": "Player Shown a Card",
}
# Longest first, so "player-shots-on-target" is not read as "player-shots".
SLUGS = sorted(MARKETS, key=len, reverse=True)

# Oddschecker bookmaker codes. The common ones; an unknown code is shown as
# it is. Exchanges are dropped. Check against the first real file with
# --check: Oddschecker has changed codes before.
BOOKS = {
    "B3": "bet365", "SK": "Sky Bet", "PP": "Paddy Power", "WH": "William Hill",
    "FB": "Betfair Sportsbook", "WA": "Betway", "CE": "Coral", "LD": "Ladbrokes",
    "UN": "Unibet", "VC": "BetVictor", "BY": "BoyleSports", "EE": "888sport",
    "FR": "Betfred", "SX": "Spreadex", "QN": "QuinnBet", "MR": "Midnite",
}
EXCHANGES = {"BF", "BD", "MK", "SO", "MA"}

ODDS_TOKEN = re.compile(r"^(?:\d+/\d+|\d+(?:\.\d+)?|evs|evens|ev)$", re.I)
COUNT_RE = re.compile(r"^(.*?)\s+(?:(?:over|o)\s+(\d+(?:\.\d+)?)|(\d+)\s*\+|(\d+\.5))\s*$", re.I)


def norm(s: str) -> str:
    """Same as normName() in the page: accents off, letters and spaces only."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if c.isascii() and (c.isalpha() or c == " "))
    return " ".join(s.lower().split())


def decimal(tok) -> float | None:
    """A price as decimal odds: 6/5, 2.2, EVS. None if it is not one."""
    t = str(tok).strip().lower()
    if t in ("evs", "evens", "ev"):
        return 2.0
    try:
        if "/" in t:
            a, b = t.split("/", 1)
            v = 1 + float(a) / float(b)
        else:
            v = float(t)
    except (ValueError, ZeroDivisionError):
        return None
    return round(v, 3) if 1.0 < v < 1001 else None


# ------------------------------------------------------------------ which game, which market

def where_from(text: str, path: Path) -> str:
    """The page address if the saved page carries one, else the file name."""
    for rx in (r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"',
               r'<meta[^>]+property="og:url"[^>]+content="([^"]+)"',
               r"saved from url=\(\d+\)(\S+)"):
        m = re.search(rx, text[:200000], re.I)
        if m and "oddschecker" in m.group(1):
            return m.group(1)
    return path.stem


def market_and_game(where: str):
    """(market slug, (home, away)) from an address or a file name, or None."""
    s = where.lower().split("?")[0].rstrip("/")
    s = s.split("oddschecker.com")[-1]
    s = re.sub(r"[^a-z0-9/]+", "-", s)
    parts = [p for p in s.split("/") if p]
    if len(parts) >= 2 and parts[-1] in MARKETS and "-v-" in parts[-2]:
        slug, game = parts[-1], parts[-2]
    else:
        flat = "-".join(parts)
        slug = next((m for m in SLUGS if flat.endswith("-" + m)), None)
        if not slug:
            return None
        game = flat[: -len(slug) - 1]
    if "-v-" not in game:
        return None
    home, away = game.split("-v-", 1)
    return slug, (home.replace("-", " "), away.replace("-", " "))


# ------------------------------------------------------------------ reading prices

class _Table(HTMLParser):
    """Rows with data-bname and cells with data-bk, and the page as text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, list[tuple[str, float]]]] = []
        self.text: list[str] = []
        self._row = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self._skip += 1
        if tag == "tr":
            self.text.append("\n")
            self._row = (a.get("data-bname"), []) if a.get("data-bname") else None
            if self._row:
                self.rows.append(self._row)
        elif tag in ("td", "th"):
            self.text.append("\t")
        elif tag in ("br", "p", "div", "li"):
            self.text.append("\n")
        if self._row is not None and a.get("data-bk"):
            p = decimal(a.get("data-odig")) or decimal(a.get("data-o") or "")
            if p:
                self._row[1].append((a["data-bk"], p))

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag == "tr":
            self._row = None

    def handle_data(self, data):
        if not self._skip:
            self.text.append(data)


def _walk_json(node, found):
    if isinstance(node, dict):
        if isinstance(node.get("bets"), list) and isinstance(node.get("odds"), list):
            found.append(node)
        for v in node.values():
            _walk_json(v, found)
    elif isinstance(node, list):
        for v in node:
            _walk_json(v, found)


def rows_from_json(text: str) -> list[tuple[str, list]]:
    """Oddschecker all-odds shaped JSON: a .json file or embedded in a page."""
    blobs = []
    t = text.strip()
    if t[:1] in "[{":
        blobs.append(t)
    blobs += re.findall(r"<script[^>]*>\s*([\[{].*?)\s*</script>", text, re.S)
    found: list = []
    for b in blobs:
        try:
            _walk_json(json.loads(b), found)
        except ValueError:
            continue
    out = []
    for m in found:
        bets = {b.get("betId"): b for b in m["bets"] if isinstance(b, dict)}
        by: dict[str, list] = {}
        for o in m["odds"]:
            if not isinstance(o, dict) or o.get("status", "ACTIVE") != "ACTIVE":
                continue
            b = bets.get(o.get("betId")) or {}
            name = (b.get("betName") or "").strip()
            if not name or name.endswith(" Under"):
                continue
            if b.get("line") not in (None, ""):
                name = f"{name[:-5].strip() if name.endswith(' Over') else name} Over {b['line']}"
            p = decimal(o.get("oddsDecimal"))
            if p:
                by.setdefault(name, []).append((o.get("bookmakerCode") or "", p))
        out += list(by.items())
    return out


def rows_from_text(text: str) -> list[tuple[str, list]]:
    """Copied table: a name, then a price per bookmaker. Bookmakers unknown."""
    out = []
    for line in text.splitlines():
        toks = [t for t in re.split(r"[\t ]+", line.strip()) if t]
        prices = []
        while toks and ODDS_TOKEN.match(toks[-1]):
            prices.insert(0, toks.pop())
        if toks and toks[-1].lower() in ("over", "o"):
            # "Over 1.5" was eaten as a price: give the line back.
            toks.append(prices.pop(0))
        name = " ".join(toks).strip(" -:")
        vals = [p for p in (decimal(x) for x in prices) if p]
        # Two prices or more: a lone number after a name is a shirt number or
        # a count, not a row of odds.
        if name and len(vals) >= 2 and re.search(r"[A-Za-z]", name):
            out.append((name, [("", v) for v in vals]))
    return out


def read_rows(text: str) -> tuple[str, list]:
    """(layout, [(selection, [(book, price)])]) for one saved file."""
    looks_html = "<html" in text[:5000].lower() or "<tr" in text.lower()
    if looks_html:
        t = _Table()
        t.feed(text)
        if t.rows and any(r[1] for r in t.rows):
            return "table", [r for r in t.rows if r[1]]
    rows = rows_from_json(text)
    if rows:
        return "json", rows
    if looks_html:
        t = _Table()
        t.feed(text)
        text = html.unescape("".join(t.text))
    return "text", rows_from_text(text)


def best(prices: list[tuple[str, float]]):
    """(price, book or None, how many bookmakers) over bookmakers only."""
    keep = [(b, p) for b, p in prices if b.upper() not in EXCHANGES]
    if not keep:
        return None
    b, p = max(keep, key=lambda x: x[1])
    return p, (b or None), len(keep)


def lines_for(slug: str, rows: list) -> list[dict]:
    """Rows to the line shape bet365_prices.py writes, plus book and books."""
    template = MARKETS[slug]
    out = []
    for sel, prices in rows:
        b = best(prices)
        if not b:
            continue
        sel = " ".join(sel.split())
        if "{n}" in template:
            m = COUNT_RE.match(sel)
            if not m:
                continue
            player = m.group(1).strip()
            if m.group(3):
                n = int(m.group(3))
            else:
                n = int(float(m.group(2) or m.group(4)) + 0.5)
            label = template.format(n=n)
        else:
            if re.search(r"\b(no goalscorer|any other|none)\b", sel, re.I):
                continue
            player, label = sel, template
        player = re.sub(r"^\d+\s+", "", player)     # a shirt number in copied text
        if not norm(player):
            continue
        price, book, n_books = b
        out.append({"market": label, "type": slug, "player": player, "key": norm(player),
                    "selection": "", "side": None, "line": None, "price": price,
                    "book": book, "books": n_books})
    return out


# ------------------------------------------------------------------ fixtures

def match_game(home: str, away: str, events: dict, now: float | None = None):
    """The site's fixture id for a game named by its teams, or None.

    Only games not yet started and within DAYS_AHEAD; Oddschecker's order
    (home v away) is checked both ways round, as some leagues swap it."""
    import bet365_prices as b3
    now = time.time() if now is None else now
    best_fid, best_score, best_ko = None, 0.0, None
    for fid, ev in events.items():
        try:
            start = datetime.fromisoformat(ev["start"].replace("Z", "+00:00")).timestamp()
        except (KeyError, ValueError):
            continue
        if start <= now or start - now > DAYS_AHEAD * 86400:
            continue
        teams = b3.split_teams(ev.get("betfair", ""))
        if not teams:
            continue
        if ev.get("swapped"):
            teams = (teams[1], teams[0])
        score = max(min(b3.side_score(home, teams[0]), b3.side_score(away, teams[1])),
                    min(b3.side_score(home, teams[1]), b3.side_score(away, teams[0])))
        if score > best_score:
            best_fid, best_score, best_ko = fid, score, start
    return (best_fid, best_ko) if best_score >= 0.6 else (None, None)


# ------------------------------------------------------------------ run

def read_file(path: Path) -> dict:
    """Everything one file says, without matching it to a fixture."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    where = where_from(text, path)
    mg = market_and_game(where)
    if not mg:
        return {"error": f"no market or game in its address or name ({where[:80]})"}
    slug, (home, away) = mg
    layout, rows = read_rows(text)
    lines = lines_for(slug, rows)
    if not lines:
        return {"error": f"no prices read ({layout} layout, {len(rows)} rows)"}
    return {"market": slug, "home": home, "away": away, "layout": layout, "lines": lines}


def files() -> list[Path]:
    if not DROP.exists():
        return []
    return sorted(p for p in DROP.iterdir() if p.is_file() and p.suffix.lower() in SUFFIXES)


def build(paths: list[Path], events: dict, now: float | None = None) -> dict:
    """reports/oddschecker.json for these files. Newest file wins a market."""
    now = time.time() if now is None else now
    held: dict = {}
    for path in sorted(paths, key=lambda p: p.stat().st_mtime):
        try:
            got = read_file(path)
        except Exception as e:  # noqa: BLE001 - one bad file never stops the rest
            print(f"  oddschecker: {path.name} not read ({type(e).__name__})")
            continue
        if "error" in got:
            print(f"  oddschecker: {path.name}: {got['error']}")
            continue
        fid, ko = match_game(got["home"], got["away"], events, now)
        if not fid:
            # Most often a game already played: kept quiet unless it is new.
            if now - path.stat().st_mtime < 2 * 86400:
                print(f"  oddschecker: {path.name}: {got['home']} v {got['away']} not matched to a game to come")
            continue
        ev = held.setdefault(fid, {"name": f"{got['home']} v {got['away']}", "kickoff": ko,
                                   "fetchedAt": 0, "files": [], "lines": []})
        ev["lines"] = [l for l in ev["lines"] if l["type"] != got["market"]] + got["lines"]
        ev["files"].append(path.name)
        ev["fetchedAt"] = max(ev["fetchedAt"], path.stat().st_mtime)
    return {"updated": now, "events": held}


def run() -> int:
    paths = files()
    if not paths:
        # Nothing dropped: leave no stale file behind for the pages.
        if OUT.exists():
            OUT.write_text(json.dumps({"updated": time.time(), "events": {}}))
        print("  oddschecker: no saved pages in drop/oddschecker/")
        return 0
    import bet365_prices
    data = build(paths, bet365_prices.load_events())
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":")))
    n = sum(len(e["lines"]) for e in data["events"].values())
    print(f"  oddschecker: {len(paths)} file(s), {len(data['events'])} game(s), {n} best prices")
    return 0


def check(path: Path) -> int:
    got = read_file(path)
    if "error" in got:
        print(got["error"])
        return 1
    print(f"{got['home']} v {got['away']} · {got['market']} · {got['layout']} layout · {len(got['lines'])} lines")
    for l in got["lines"]:
        book = BOOKS.get(l["book"] or "", l["book"] or "bookmaker unknown")
        print(f"  {l['player']:28} {l['market']:42} {l['price']:>7}  {book} (of {l['books']})")
    return 0


def status() -> None:
    try:
        data = json.loads(OUT.read_text())
    except (OSError, ValueError):
        data = {}
    for fid, e in (data.get("events") or {}).items():
        ko = datetime.fromtimestamp(e["kickoff"], tz=timezone.utc).strftime("%a %d %b %H:%M UTC")
        print(f"  {e['name']}  ko {ko}  {len(e['lines'])} prices  from {', '.join(e['files'])}  fixture {fid}")
    print(f"  files in drop/oddschecker/: {len(files())}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--check", metavar="FILE")
    p.add_argument("--status", action="store_true")
    a = p.parse_args()
    if a.check:
        return check(Path(a.check))
    if a.status:
        status()
        return 0
    return run()


if __name__ == "__main__":
    sys.exit(main())
