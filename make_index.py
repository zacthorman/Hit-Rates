"""
Build the front page: every upcoming fixture, soonest first.

    python make_index.py

Writes index.html at the project root. GitHub Pages serves that as the site's
front page, so you send your mate one URL and he picks the game himself.

This lists FIXTURES, not report files. A league round is one file holding ten
matches, and "premier-league-10-fixtures.html" tells you nothing about whether
Arsenal are playing tonight. So the payload of every report is read, each
fixture pulled out with its kick-off time, and the whole lot sorted by when
they actually start and grouped by day. Each one links straight to itself
inside its report, using the event id in the URL hash.

Kick-off times are rendered in the reader's own timezone by the browser, not
baked in here. The page ships unix timestamps and lets the device do it.

Run it after building reports, then commit and push.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import picker
import site_guard
import weekend
import pagedata

ROOT = Path(__file__).parent
REPORTS = ROOT / "reports"


_PAYLOADS: dict[Path, dict] = {}


def read_payload(path: Path) -> dict:
    """The parsed `const ALL` object out of one report, read at most once.

    These files run to twenty-odd megabytes and both the fixture list and the
    weekend picks need them, so parsing per caller would double the build time
    of the index for no reason.
    """
    if path in _PAYLOADS:
        return _PAYLOADS[path]

    data: dict = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    if text:
        payload = pagedata.search(text)
        if payload:
            try:
                data = json.loads(payload.group(1))
            except json.JSONDecodeError:
                data = {}
    _PAYLOADS[path] = data
    return data


def read_entries(path: Path) -> list[tuple[dict, dict]]:
    """Full fixture entries plus the metadata the picks need to name them."""
    out = []
    for entry in read_payload(path).get("fixtures", []):
        fixture = entry.get("fixture", {})
        if not fixture.get("home") or not fixture.get("away"):
            continue
        out.append((entry, {
            "id": fixture.get("id"),
            "home": fixture["home"],
            "away": fixture["away"],
            "competition": fixture.get("competition", "Football"),
            "kickoff": fixture.get("kickoff") or 0,
            "report": path.name,
        }))
    return out


def read_fixtures(path: Path) -> list[dict]:
    """Every fixture inside one built report.

    The whole file is read rather than the first few thousand characters: the
    inlined CSS runs to several thousand on its own, so the payload is nowhere
    near the top. That was a real bug here once, and the symptom was every
    report being listed under its filename.
    """
    data = read_payload(path)

    out = []
    for entry in data.get("fixtures", []):
        fixture = entry.get("fixture", {})
        if not fixture.get("home") or not fixture.get("away"):
            continue
        out.append(
            {
                "id": fixture.get("id"),
                "home": fixture["home"],
                "away": fixture["away"],
                "competition": fixture.get("competition", "Football"),
                "kickoff": fixture.get("kickoff") or 0,
                "report": path.name,
                # Enough to show what the report actually carries, so you know
                # before clicking whether the player tables are in there.
                "sport": weekend.sport_of(entry),
                "players": bool(entry.get("players")),
                "adjusted": bool(entry.get("projection") or entry.get("tierProjection")),
            }
        )
    return out


def research_card() -> str:
    """A card pointing at tonight's hand-researched picks, while they are live.

    Reads research_picks.json (see tonight.research_block). Nothing once the
    file's `expires` has passed, so the front page never advertises a stale
    night.
    """
    import html as _html
    try:
        data = json.loads((ROOT / "research_picks.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    import time as _time
    if _time.time() >= (data.get("expires") or 0):
        return ""
    picks = [p for g in data.get("groups") or [] for p in g.get("picks") or []]
    lines = "".join(
        f"<li>{_html.escape(p['selection'])} <small>{_html.escape(p['fixture'])}, "
        f"{p['chance'] * 100:.0f}%, fair {p['fair']:.2f}</small></li>" for p in picks[:4])
    return (f'<div class="pick" style="margin-bottom:12px">'
            f'<h2>{_html.escape(data.get("title", "Researched picks"))} &middot; tonight</h2>'
            f'<div class="sel">{len(picks)} picks checked against line-ups, team news and referees</div>'
            f'<ol>{lines}</ol>'
            f'<div class="odds"><a href="tonight.html">All {len(picks)}, with the reasons &rarr;</a></div>'
            f'</div>')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-played", action="store_true", dest="keep_played",
                        help="keep fixtures that have already kicked off")
    parser.add_argument("--prune", action="store_true",
                        help="delete report files with no upcoming fixtures left")
    args = parser.parse_args()

    if not REPORTS.exists():
        raise SystemExit("No reports/ folder yet. Build a report first.")

    # The picker pages live in the same folder and are not fixture reports.
    # Left in, they get scanned for fixtures, find none, and the build ends by
    # announcing that nine files have no upcoming games and could be pruned.
    files = [f for f in sorted(REPORTS.glob("*.html"))
             if not f.name.startswith(("pick-", "_"))]
    if not files:
        raise SystemExit("No reports found in reports/.")

    # Newest first, purely for the de-duplication below. The listing order of
    # the page is decided by kick-off time later, so this only affects which
    # copy of a repeated fixture wins.
    #
    # A one-off build of a single match ("home-v-away.html", or a "mixed-"
    # build) beats the league round for that match, however recently the
    # round was saved. The one-off is built on purpose with more in it, player
    # stats and the Line-ups tab; lineups_auto.py re-saves the round every
    # time it attaches an XI, and on mtime alone that quietly sent the front
    # page back to the round, which had no Line-ups tab.
    def _one_off(p):
        return "-v-" in p.stem or p.stem.startswith("mixed-")
    freshest = sorted(files, key=lambda p: (_one_off(p), p.stat().st_mtime), reverse=True)

    now = datetime.now(tz=timezone.utc).timestamp()

    fixtures: list[dict] = []
    seen: set[tuple] = set()
    live_reports: set[str] = set()
    stale: dict[str, int] = {}

    for path in freshest:
        for fixture in read_fixtures(path):
            if fixture["kickoff"] > now:
                live_reports.add(path.name)
            elif not args.keep_played:
                continue

            # The same match can appear in two reports: a one-off build of a
            # club's fixtures and the league round both contain it. Keep the
            # copy from the most recently built report.
            #
            # This used to keep whichever came first alphabetically, which
            # meant "10-fixtures-manchester-city.html" from last week beat
            # "premier-league-10-fixtures.html" built an hour ago. Every link
            # for those fixtures pointed at the stale file, so new features
            # appeared to be missing from a site that had them.
            key = (fixture["home"], fixture["away"], fixture["kickoff"])
            if key in seen:
                stale.setdefault(path.name, 0)
                stale[path.name] += 1
                continue
            seen.add(key)
            fixtures.append(fixture)

    fixtures.sort(key=lambda f: (f["kickoff"] or 1 << 62, f["home"]))

    competitions = sorted({f["competition"] for f in fixtures})
    generated = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")

    # A stamp that changes whenever any report changes, used to bust the
    # browser cache on the links below.
    stamp = str(int(max((p.stat().st_mtime for p in files), default=0)))

    # The three picks, read across every report rather than per league. Built
    # from data already inside those files, so this adds no network calls and
    # cannot be the thing that breaks a publish.
    entries: list[tuple[dict, dict]] = []
    entry_seen: set[tuple] = set()
    for path in freshest:
        for entry, meta in read_entries(path):
            key = (meta["home"], meta["away"], meta["kickoff"])
            if key in entry_seen:
                continue
            entry_seen.add(key)
            entries.append((entry, meta))

    try:
        chosen = weekend.picks(entries, days=7)
    except Exception as exc:                       # never lose the index to this
        print(f"  picks failed, index built without them: "
              f"{type(exc).__name__}: {exc}")
        chosen = None
    # The picks of the week, rebuilt on evidence (weekpicks.py, 2 Nov 2026):
    # sharp-backed lines and the rules on trial. weekend.py still gives the
    # darts match prices.
    try:
        import weekpicks
        chosen = dict(chosen or {}, evidence=weekpicks.build())
    except Exception as exc:                       # never lose the index to this
        print(f"  evidence picks not built: {type(exc).__name__}: {exc}")

    payload = json.dumps(
        {"fixtures": fixtures, "competitions": competitions,
         "built": generated, "stamp": stamp, "picks": chosen},
        separators=(",", ":"),
    )

    page = PAGE.replace("__PAYLOAD__", payload).replace("__RESEARCH__", research_card())
    out = ROOT / "index.html"
    site_guard.atomic_write(out, page)

    # The picker reads the same reports this index just read, so building it
    # here is what stops the two drifting: a report rebuilt without its picker
    # page is a fixture list linking to yesterday's numbers.
    try:
        picker.main([])
    except Exception as exc:
        print(f"  picker pages not rebuilt: {type(exc).__name__}: {exc}")

    print(f"Indexed {len(fixtures)} fixture(s) across {len(competitions)} "
          f"competition(s) into {out}")
    for block in (chosen or {}).get("sports", []):
        one = block.get("single")
        if not one:
            continue
        who = one.get("player") or one["team"]
        # Ladder legs read the way the coupon writes them, same as the page.
        # This line is the only sight of the pick most runs get, and printing
        # "over 4.5 receiving receptions" for a bet the card calls "5+" is how
        # you end up doubting a fix that landed.
        if one.get("alt"):
            market = f"{one['threshold']:.0f}+ {one['stat'].lower()}"
        else:
            direction = "over" if one["over"] else "under"
            market = f"{direction} {one['line']} {one['stat'].lower()}"
        book = one.get("book")
        priced = (f"{book['name']} {book['price']:.2f} (fair {one['fair']:.2f})" if book and one.get("confirmed")
                  else f"fair {one['fair']:.2f}, not yet priced at Paddy Power or Bet365")
        print(f"  {block['label']} pick of the week: {who} {market} "
              f"at {priced} ({one['hits']}/{one['total']})")
        for slot, name in (("banker", "banker"), ("double", "double"), ("acca", "acca")):
            got = block.get(slot)
            if not got:
                continue
            if slot == "banker":
                b = got.get("book") or {}
                where = f"{b.get('name')} {got['price']:.2f}" if got.get("priced") else f"fair {got['fair']:.2f}, not priced"
                print(f"    {name}: {got.get('player') or got['team']} {got['stat'].lower()} at {where}")
            else:
                where = "book prices" if got.get("priced") else "fair, not priced"
                print(f"    {name}: {len(got['legs'])} legs at {got['combined']:.2f} ({where})")
    for competition in competitions:
        count = sum(1 for f in fixtures if f["competition"] == competition)
        print(f"  {competition}: {count}")

    if stale:
        print("\nSuperseded by a more recent build:")
        for name, count in sorted(stale.items()):
            print(f"  {name}: {count} fixture(s) also in a newer report")
        print("  Those links point at the newer file. Delete the old reports")
        print("  if you no longer want them: rm reports/<name>")

    # A report whose data would not read has no upcoming fixtures as far as
    # this loop can tell, and --prune used to delete it: a page cut off part
    # way through being written took its whole league off the site without a
    # word. It is left alone and named; site_guard decides what happens to it.
    unreadable = [p for p in files if not read_payload(p)]
    if unreadable:
        print(f"\n{len(unreadable)} report(s) would not read and were not pruned:")
        for path in unreadable:
            print(f"  {path.name}")
    dead = [p for p in files if p.name not in live_reports and p not in unreadable]
    if dead:
        print(f"\n{len(dead)} report(s) have no upcoming fixtures left:")
        for path in dead:
            print(f"  {path.name}")
        if args.prune:
            for path in dead:
                path.unlink()
            print("Deleted them. They rebuild from the cache in seconds.")
        else:
            print("Add --prune to delete their files too.")


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Football hit rates</title>
<style>
:root {
  color-scheme: light;
  --surface: #fcfcfb; --page: #f9f9f7; --raised: #ffffff;
  --text: #0b0b0b; --muted: #77756f;
  --border: rgba(11,11,11,0.10); --grid: #e8e7e1;
  --link: #2a78d6; --accent: #0b0b0b; --on-accent: #ffffff;
  --today: #c2410c;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --surface: #1a1a19; --page: #0d0d0d; --raised: #232322;
    --text: #ffffff; --muted: #8f8d87;
    --border: rgba(255,255,255,0.12); --grid: #2c2c2a;
    --link: #5ba3f5; --accent: #ffffff; --on-accent: #0b0b0b;
    --today: #fb923c;
  }
}
* { box-sizing: border-box; }

/* Top bar: the site name and one tab per sport, full width. The sport is the
   first choice anyone makes on this page, so it gets the top of the screen
   and everything else hangs off it. */
.topbar { position: sticky; top: 0; z-index: 20; background: var(--page);
          border-bottom: 1px solid var(--border); }
.topbar-in { max-width: 1240px; margin: 0 auto; padding: 0 18px;
             display: flex; align-items: center; gap: 22px; min-height: 56px; }
.brand { font-size: 19px; font-weight: 700; letter-spacing: -0.01em;
         white-space: nowrap; margin: 0; }
.sports { display: flex; gap: 2px; overflow-x: auto; scrollbar-width: none;
          align-self: stretch; }
.sports::-webkit-scrollbar { display: none; }
.sports button { border: 0; background: none; padding: 0 14px; font: inherit;
                 font-weight: 600; font-size: 0.92rem; color: var(--muted);
                 cursor: pointer; white-space: nowrap;
                 border-bottom: 2px solid transparent; margin-bottom: -1px; }
.sports button:hover { color: var(--text); }
.sports button[aria-pressed="true"] { color: var(--text);
                                      border-bottom-color: var(--accent); }
.sports button .n { font-weight: 500; opacity: 0.5; margin-left: 4px; font-size: 0.8rem; }

/* Two columns on a wide screen: fixtures in the middle, picks in a rail on
   the right that scrolls on its own. Below 1100px the rail becomes a drawer
   behind a tab on the right edge, so the fixture list keeps the full width. */
.layout { max-width: 1240px; margin: 0 auto; padding: 18px 18px 60px;
          display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 28px;
          align-items: start; }
.main { min-width: 0; max-width: 780px; width: 100%; justify-self: center; }
.rail { position: sticky; top: 74px; max-height: calc(100vh - 92px);
        overflow-y: auto; scrollbar-width: thin; padding-bottom: 12px; }
.rail-head { display: flex; align-items: center; justify-content: space-between;
             margin: 0 0 10px; }
.rail-title { font-size: 0.72rem; letter-spacing: 0.07em; text-transform: uppercase;
              color: var(--muted); font-weight: 650; margin: 0; }
.quick { display: grid; gap: 6px; margin: 0 0 16px; }
.quick a { display: flex; justify-content: space-between; align-items: center;
           background: var(--raised); border: 1px solid var(--border);
           border-radius: 9px; padding: 10px 13px; color: var(--text);
           text-decoration: none; font-weight: 600; font-size: 0.88rem; }
.quick a:hover { border-color: var(--muted); }
.quick a span { color: var(--muted); font-weight: 500; font-size: 0.8rem; }
.fold { background: none; border: 0; padding: 0; font: inherit; cursor: pointer;
        display: flex; align-items: center; gap: 7px; color: var(--text);
        font-weight: 650; font-size: 0.95rem; }
.fold::before { content: ""; width: 0; height: 0;
  border-left: 5px solid currentColor; border-top: 4px solid transparent;
  border-bottom: 4px solid transparent; transition: transform 0.15s ease; }
.fold[aria-expanded="true"]::before { transform: rotate(90deg); }
.fold small { color: var(--muted); font-weight: 500; font-size: 0.8rem; }
.drawer-close { display: none; }
.side-tab { display: none; }
.scrim { display: none; }

@media (max-width: 1099px) {
  .layout { grid-template-columns: minmax(0, 1fr); }
  .rail { position: fixed; top: 0; right: 0; bottom: 0; width: min(380px, 88vw);
          max-height: none; z-index: 40; background: var(--page);
          border-left: 1px solid var(--border); padding: 18px 16px 40px;
          transform: translateX(105%); transition: transform 0.2s ease;
          box-shadow: -8px 0 24px rgba(0,0,0,0.12); }
  body.drawer-open .rail { transform: none; }
  .scrim { display: block; position: fixed; inset: 0; z-index: 30;
           background: rgba(0,0,0,0.35); opacity: 0; pointer-events: none;
           transition: opacity 0.2s ease; }
  body.drawer-open .scrim { opacity: 1; pointer-events: auto; }
  .drawer-close { display: inline-flex; border: 1px solid var(--border);
                  background: var(--raised); color: var(--text); border-radius: 7px;
                  font: inherit; font-size: 0.8rem; padding: 4px 10px; cursor: pointer; }
  /* The tab that opens it: a strip on the right edge, always in reach. */
  .side-tab { display: block; position: fixed; right: 0; top: 50%; z-index: 25;
              transform: translateY(-50%); writing-mode: vertical-rl;
              background: var(--accent); color: var(--on-accent); border: 0;
              border-radius: 8px 0 0 8px; padding: 14px 7px; font: inherit;
              font-size: 0.8rem; font-weight: 650; letter-spacing: 0.04em;
              cursor: pointer; box-shadow: -2px 2px 10px rgba(0,0,0,0.15); }
}
@media (max-width: 560px) {
  .topbar-in { gap: 12px; padding: 0 12px; }
  .brand { font-size: 17px; }
  .sports button { padding: 0 10px; font-size: 0.86rem; }
  .layout { padding: 12px 12px 60px; }
}

.picks { display: grid; gap: 10px; margin: 0 0 12px; }
.pick { background: var(--raised); border: 1px solid var(--border);
        border-radius: 10px; padding: 13px 15px; font-size: 0.9rem; }
.pick h2 { font-size: 0.68rem; letter-spacing: 0.07em; text-transform: uppercase;
           color: var(--muted); margin: 0 0 8px; font-weight: 600; }
.pick .sel { font-size: 0.97rem; font-weight: 600; line-height: 1.35; }
.pick .where { color: var(--muted); font-size: 0.8rem; margin-top: 2px; }
.pick .odds { margin-top: 8px; }
.pick .str { color: var(--muted); font-size: 0.78rem; line-height: 1.45; margin-top: 6px; }
.pick .str b { color: var(--text); font-weight: 600; }
.pick .odds b { font-size: 1.05rem; }
.pick ol { margin: 7px 0 0; padding-left: 17px; font-size: 0.85rem; line-height: 1.45; }
.pick details { margin-top: 9px; }
.pick summary { color: var(--muted); font-size: 0.78rem; cursor: pointer;
                list-style: none; }
.pick summary::-webkit-details-marker { display: none; }
/* Drawn rather than typed. The chevron characters rendered as a missing-glyph
   box on a machine without the font, and a marker that might not exist is
   worse than one made of borders, which always does. */
.pick summary::before { content: ""; display: inline-block; width: 0; height: 0;
  border-left: 4px solid currentColor; border-top: 3.5px solid transparent;
  border-bottom: 3.5px solid transparent; margin-right: 6px;
  transform-origin: 30% 50%; transition: transform 0.15s ease; }
.pick details[open] summary::before { transform: rotate(90deg); }
.pick details p { color: var(--muted); font-size: 0.78rem; line-height: 1.45;
                  margin: 6px 0 0; }
.pick .flag { color: var(--today); font-weight: 600; }
/* Pick cards, v2: the same anatomy for every card. A label and the price on
   one line, the selection, the fixture, three numbers in chips, one short
   strength line, and everything else behind the fold. */
.pk-top { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.pk-top h2 { margin: 0; }
.pk-price { font-size: 1.15rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.pk-price small { font-size: 0.68rem; font-weight: 600; color: var(--muted); letter-spacing: 0.05em;
                  text-transform: uppercase; margin-right: 5px; }
.pk-chips { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; margin-top: 10px; }
.pk-chip { background: var(--page); border: 1px solid var(--border); border-radius: 8px; padding: 6px 8px; min-width: 0; }
.pk-chip span { display: block; font-size: 0.64rem; color: var(--muted); text-transform: uppercase;
                letter-spacing: 0.06em; }
.pk-chip b { display: block; font-size: 0.95rem; font-variant-numeric: tabular-nums; white-space: nowrap;
             overflow: hidden; text-overflow: ellipsis; }
.pk-str { color: var(--muted); font-size: 0.78rem; margin-top: 8px; line-height: 1.4; }
.pk-str b { color: var(--text); font-weight: 600; }
.pick .pk-legs { list-style: none; margin: 10px 0 0; padding: 0; display: grid; gap: 0;
                 border: 0; background: none; border-radius: 0; }
.pk-leg { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 2px 10px; padding: 8px 0;
          border-top: 1px solid var(--border); }
.pk-leg:first-child { border-top: 0; padding-top: 2px; }
.pk-leg .t { font-size: 0.86rem; font-weight: 600; line-height: 1.3; }
.pk-leg .p { font-size: 0.9rem; font-weight: 700; font-variant-numeric: tabular-nums; text-align: right; }
/* Evidence picks (weekpicks.py): a short line on why the method is trusted,
   its record as a strip, then the bets. */
.pk-intro { color: var(--muted); font-size: 0.8rem; line-height: 1.45; margin: 6px 0 0; }
.pk-rec { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.pk-rec span { background: var(--page); border: 1px solid var(--border); border-radius: 999px;
               padding: 2px 9px; font-size: 0.74rem; color: var(--muted); font-variant-numeric: tabular-nums; }
.pk-rec span b { color: var(--text); font-weight: 650; }
.pk-rule { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border); }
.pk-rule:first-of-type { border-top: 0; padding-top: 0; }
.pk-rule .rt { font-size: 0.84rem; font-weight: 600; line-height: 1.35; }
.pk-tag { display: inline-block; font-size: 0.64rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
          border-radius: 999px; padding: 1px 7px; margin-left: 6px; vertical-align: 1px; }
.pk-tag.trial { background: var(--page); border: 1px solid var(--border); color: var(--muted); }
.pk-tag.proven { background: rgba(46,139,87,.14); color: #2e8b57; }
.pk-leg .bk { font-size: 0.66rem; font-weight: 600; color: var(--muted); margin-right: 4px; text-transform: uppercase; letter-spacing: .04em; }
.pk-leg .p small { font-size: 0.62rem; font-weight: 600; color: var(--muted); letter-spacing: 0.04em; }
.pk-leg .m { grid-column: 1 / -1; color: var(--muted); font-size: 0.74rem; line-height: 1.35; }
.pk-learn { color: var(--muted); font-size: 0.72rem; margin: 2px 0 10px; }
.pk-pos { color: var(--hit, #2e9d5b); font-weight: 650; }
.pk-why { margin-top: 8px; display: grid; gap: 3px; }
.pk-why div { font-size: 0.76rem; line-height: 1.4; padding-left: 16px; position: relative; }
.pk-why .y::before { content: "+"; position: absolute; left: 2px; color: var(--hit, #2e9d5b); font-weight: 700; }
.pk-why .n::before { content: "−"; position: absolute; left: 2px; color: var(--today, #c4622d); font-weight: 700; }
.pk-why .n { color: var(--muted); }
.pick ol.pk-steps { margin: 6px 0 0; padding-left: 18px; color: var(--muted); font-size: 0.76rem; line-height: 1.45; }
.pk-val { font-size: 0.8rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.pick.ev h2 { margin: 0; }
.ev-sub { color: var(--muted); font-size: 0.8rem; line-height: 1.4; margin: 4px 0 0; }
.ev-rec { font-size: 0.74rem; color: var(--muted); line-height: 1.5; margin-top: 8px; padding: 6px 9px;
  background: var(--page); border-radius: 8px; }
.ev-rec b { color: var(--text); font-weight: 650; font-variant-numeric: tabular-nums; }
.pick .ev-list { list-style: none; margin: 6px 0 0; padding: 0; border: 0; border-radius: 0;
  background: none; overflow: visible; }
li.ev-row { border-bottom: 0; }
.ev-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; column-gap: 12px; row-gap: 1px;
  padding: 9px 0; border-top: 1px solid var(--border); }
.ev-row:first-child { border-top: 0; }
.ev-row:last-child { border-bottom: 0; }
.ev-row .t { font-size: 0.88rem; font-weight: 600; line-height: 1.3; }
.ev-row .p { font-size: 0.95rem; font-weight: 700; font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
.ev-row .p small { font-size: 0.6rem; font-weight: 600; color: var(--muted); letter-spacing: 0.05em; margin-right: 5px; }
.ev-row .m { color: var(--muted); font-size: 0.74rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ev-row .e { font-size: 0.74rem; color: var(--muted); text-align: right; white-space: nowrap; }
.ev-row .e b { margin-left: 6px; font-weight: 700; font-variant-numeric: tabular-nums; }
.pick.ev .up { color: var(--hit, #2e9d5b); }
.pick.ev .down { color: var(--today, #c4622d); }
.ev-rule { margin-top: 14px; }
.ev-rh { display: flex; align-items: baseline; justify-content: space-between; gap: 10px;
  font-size: 0.86rem; font-weight: 650; }
.ev-rh > b { font-variant-numeric: tabular-nums; white-space: nowrap; }
.ev-rs { color: var(--muted); font-size: 0.72rem; margin-top: 1px; }
.ev-new { font-size: 0.62rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted);
  border: 1px solid var(--border); border-radius: 999px; padding: 1px 7px; }
.pick details.ev-fresh { margin-top: 14px; }
.ev-fresh > summary { font-weight: 600; }
.ev-fresh .ev-rule:first-of-type { margin-top: 10px; }
.pick.none { color: var(--muted); }
body {
  margin: 0; padding: 0;
  background: var(--page); color: var(--text);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 15px; line-height: 1.5;
  -webkit-text-size-adjust: 100%;
}
.sub { color: var(--muted); font-size: 14px; margin: 0 0 20px; }

/* Filters. Sticky, because on a phone the list is long and the filter is
   the thing you reach for after scrolling, not before. Sits under the top
   bar rather than behind it. */
.filters {
  position: sticky; top: 56px; z-index: 5;
  background: var(--page); padding: 10px 0 12px;
  margin: 0 0 6px; border-bottom: 1px solid var(--border);
  display: flex; gap: 7px; flex-wrap: wrap; align-items: center;
}
.chip {
  appearance: none; cursor: pointer;
  background: var(--raised); color: var(--text);
  border: 1px solid var(--border); border-radius: 999px;
  padding: 7px 13px; font: inherit; font-size: 13.5px; font-weight: 550;
  white-space: nowrap;
}
.chip:hover { border-color: var(--muted); }
.chip[aria-pressed="true"] {
  background: var(--accent); color: var(--on-accent); border-color: var(--accent);
}
.chip .n { opacity: 0.55; margin-left: 5px; font-weight: 500; }
.search {
  flex: 1 1 150px; min-width: 130px;
  background: var(--raised); color: var(--text);
  border: 1px solid var(--border); border-radius: 999px;
  padding: 7px 13px; font: inherit; font-size: 13.5px;
}
.search::placeholder { color: var(--muted); }

.day {
  margin: 22px 0 8px; font-size: 13px; font-weight: 640;
  letter-spacing: 0.05em; text-transform: uppercase; color: var(--muted);
}
.day.soon { color: var(--today); }

ul { list-style: none; margin: 0; padding: 0;
     background: var(--surface); border: 1px solid var(--border);
     border-radius: 11px; overflow: hidden; }
li { border-bottom: 1px solid var(--grid); }
li:last-child { border-bottom: 0; }
li a {
  display: flex; align-items: baseline; gap: 12px;
  padding: 13px 16px; color: inherit; text-decoration: none;
}
li a:hover { background: var(--raised); }
.time {
  flex: 0 0 46px; font-variant-numeric: tabular-nums;
  font-weight: 620; font-size: 14.5px; color: var(--text);
}
.match { flex: 1 1 auto; min-width: 0; }
.teams { font-weight: 560; color: var(--link); }
.meta { display: block; color: var(--muted); font-size: 12.5px; margin-top: 2px; }
.tag {
  display: inline-block; font-size: 11px; font-weight: 600;
  padding: 1px 6px; border-radius: 5px; margin-left: 6px;
  border: 1px solid var(--border); color: var(--muted);
}
li.played { opacity: 0.5; }

.empty { padding: 26px 16px; color: var(--muted); text-align: center; }
footer { margin-top: 26px; color: var(--muted); font-size: 12.5px; }
</style>
</head>
<body>
<header class="topbar">
  <div class="topbar-in">
    <h1 class="brand">Hit rates</h1>
    <nav class="sports" id="sports" aria-label="Sport"></nav>
  </div>
</header>

<button type="button" class="side-tab" id="side-tab"
        aria-controls="rail" aria-expanded="false">Best picks</button>
<div class="scrim" id="scrim"></div>

<div class="layout">
  <main class="main">
    <div class="filters" id="filters"></div>
    <div id="list"></div>
    <footer id="footer"></footer>
  </main>

  <aside class="rail" id="rail" aria-label="Best picks">
    <div class="rail-head">
      <p class="rail-title">Best picks</p>
      <button type="button" class="drawer-close" id="drawer-close">Close</button>
    </div>
    <div class="quick">
      <a href="tonight.html">Tonight <span>next 8 hours &rarr;</span></a>
      <a href="best-bets-summary.html">Best bets summary <span>all sports &rarr;</span></a>
      <a href="market-check.html">Market check <span>model v Betfair &rarr;</span></a>
      <a href="pp-results.html">Paddy Power results <span>what hit, what paid &rarr;</span></a>
    </div>
    <div class="rail-head">
      <button type="button" class="fold" id="picks-btn" aria-expanded="true"
              aria-controls="picks">Picks of the week <small id="picks-sport"></small></button>
    </div>
    __RESEARCH__
    <div id="picks"></div>
  </aside>
</div>

<script>
const DATA = __PAYLOAD__;

let competition = "all";
let query = "";
let sport = null;          // set on first render to whichever has most fixtures

const SPORT_LABELS = { "football": "Football", "american-football": "NFL", "basketball": "Basketball", "darts": "Darts", "baseball": "MLB" };

/* Sports present, busiest first. Two codes on one page need separating before
   anything else: the league chips, the fixture list and the picks all mean
   something different depending on which you are looking at. */
function sportsPresent() {
  const counts = {};
  DATA.fixtures.forEach(f => {
    const key = f.sport || "football";
    counts[key] = (counts[key] || 0) + 1;
  });
  return Object.entries(counts).sort((a, b) => b[1] - a[1]);
}

/* Day headings read better as "Today" and "Tomorrow" than as a date, and the
   comparison has to be on calendar days in the reader's own timezone rather
   than on a 24 hour difference: a match at 20:00 tonight and one at 12:00
   tomorrow are 16 hours apart but belong under different headings. */
function dayKey(ts) {
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function dayLabel(ts) {
  const d = new Date(ts * 1000);
  const today = new Date();
  const tomorrow = new Date();
  tomorrow.setDate(today.getDate() + 1);

  if (dayKey(ts) === dayKey(today.getTime() / 1000)) return "Today";
  if (dayKey(ts) === dayKey(tomorrow.getTime() / 1000)) return "Tomorrow";
  return d.toLocaleDateString(undefined,
    { weekday: "long", day: "numeric", month: "long" });
}

function timeLabel(ts) {
  if (!ts) return "TBC";
  return new Date(ts * 1000).toLocaleTimeString(undefined,
    { hour: "2-digit", minute: "2-digit", hour12: false });
}

function matches(f) {
  if (sport && (f.sport || "football") !== sport) return false;
  if (competition !== "all" && f.competition !== competition) return false;
  if (!query) return true;
  const hay = `${f.home} ${f.away} ${f.competition}`.toLowerCase();
  return hay.includes(query);
}

function renderSports() {
  const present = sportsPresent();
  if (!sport) sport = present.length ? present[0][0] : "football";

  const box = document.getElementById("sports");
  if (!present.length) { box.innerHTML = ""; return; }

  box.innerHTML = present.map(([key, n]) =>
    `<button type="button" data-sport="${escapeAttr(key)}"
      aria-pressed="${key === sport}">${escapeHtml(SPORT_LABELS[key] || key)}<span class="n">${n}</span></button>`
  ).join("");

  box.querySelectorAll("[data-sport]").forEach(btn => {
    btn.addEventListener("click", () => {
      sport = btn.dataset.sport;
      competition = "all";
      renderSports();
      renderPicks();
      renderFilters();
      renderList();
    });
  });
}

function renderFilters() {
  // Only the leagues that belong to the sport on screen, so the row is four
  // chips rather than ten wrapping onto two lines with the NFL buried in it.
  const mine = DATA.fixtures.filter(f => (f.sport || "football") === sport);
  const comps = [...new Set(mine.map(f => f.competition))].sort();
  const counts = { all: mine.length };
  comps.forEach(c => {
    counts[c] = mine.filter(f => f.competition === c).length;
  });
  if (competition !== "all" && !comps.includes(competition)) competition = "all";

  const chips = ["all"].concat(comps).map(c => {
    const label = c === "all" ? "All" : c;
    return `<button type="button" class="chip" data-comp="${escapeAttr(c)}"
      aria-pressed="${c === competition}">${escapeHtml(label)}<span class="n">${counts[c]}</span></button>`;
  }).join("");

  document.getElementById("filters").innerHTML = chips +
    `<input class="search" id="search" type="search" placeholder="Search team"
      value="${escapeAttr(query)}" aria-label="Search team">`;

  document.querySelectorAll("[data-comp]").forEach(btn => {
    btn.addEventListener("click", () => {
      competition = btn.dataset.comp;
      renderFilters();
      renderList();
    });
  });

  const search = document.getElementById("search");
  search.addEventListener("input", () => {
    query = search.value.trim().toLowerCase();
    renderList();
  });
  if (query) {
    search.focus();
    search.setSelectionRange(search.value.length, search.value.length);
  }
}

function renderList() {
  const shown = DATA.fixtures.filter(matches);
  const now = Date.now() / 1000;

  if (!shown.length) {
    document.getElementById("list").innerHTML =
      `<ul><li><div class="empty">Nothing to show. Build a new round with
       <code>python run.py --league "Premier League"</code>.</div></li></ul>`;
    return;
  }

  const groups = [];
  shown.forEach(f => {
    const key = f.kickoff ? dayKey(f.kickoff) : "tbc";
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.items.push(f);
    else groups.push({ key, ts: f.kickoff, items: [f] });
  });

  document.getElementById("list").innerHTML = groups.map(g => {
    const label = g.ts ? dayLabel(g.ts) : "Date to be confirmed";
    const soon = label === "Today" || label === "Tomorrow";
    const rows = g.items.map(f => {
      const played = f.kickoff && f.kickoff <= now;
      const tags = (f.players ? '<span class="tag">players</span>' : "")
                 + (f.adjusted ? '<span class="tag">adjusted</span>' : "");
      // ?v= is the build stamp. It changes every time the index is rebuilt,
      // so the browser is forced to fetch the report rather than serve a copy
      // it cached before the report was re-rendered. Without this a fixed
      // report looks unfixed for as long as the cache holds, which is the
      // most confusing possible failure.
      return `<li class="${played ? "played" : ""}">
        <a href="reports/${escapeAttr(f.report)}?v=${DATA.stamp}#e${f.id}">
          <span class="time">${timeLabel(f.kickoff)}</span>
          <span class="match">
            <span class="teams">${escapeHtml(f.home)} v ${escapeHtml(f.away)}</span>${tags}
            <span class="meta">${escapeHtml(f.competition)}${played ? " &middot; kicked off" : ""}</span>
          </span>
        </a></li>`;
    }).join("");
    return `<div class="day${soon ? " soon" : ""}">${escapeHtml(label)}</div>
            <ul>${rows}</ul>`;
  }).join("");
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
function escapeAttr(s) { return escapeHtml(s).replace(/'/g, "&#39;"); }

document.getElementById("footer").textContent =
  `Built ${DATA.built}. Each report is a snapshot: the numbers are frozen at ` +
  `the moment it was generated. Times are shown in your own timezone.`;

/* The picks, for whichever sport is on screen.

   Decided at build time, not in the browser: a pick of the week that moves
   when you nudge a slider is a search, not a pick. Kept behind a button
   because it is a sidebar to the fixture list, not the point of the page. */
const fmtOdds = v => (v === null || v === undefined || !isFinite(v))
  ? "\u2014" : v.toFixed(2);

const half = p => p === "1ST" ? " (1st half)" : p === "2ND" ? " (2nd half)" : "";

function legText(l) {
  /* Alt lines read the way a book writes them. "50+ receiving yards" and
     "over 49.5 receiving yards" are the same bet, and only one of them is
     what you would go looking for on the coupon. */
  const market = l.alt
    ? `${l.threshold}+ ${l.stat.toLowerCase()}`
    : `${l.over ? "over" : "under"} ${l.line} ${l.stat.toLowerCase()}`;
  return l.player
    ? `${escapeHtml(l.player)} ${market}${half(l.period)}`
    : `${escapeHtml(l.team)} ${market}${half(l.period)}`;
}

/* Team strength, short: the two ratings and the chance of winning. The
   similar-opposition record and what strength and the projection expect go
   behind the fold, where they are read when wanted rather than every time. */
function oppOf(l) {
  return l.fixture ? (l.team === l.fixture.home ? l.fixture.away : l.fixture.home) : "opponent";
}
function strengthLine(l) {
  const s = l.strength;
  if (!s || s.team == null) return "";
  const pct = x => `${Math.round(x * 100)}%`;
  return `<div class="pk-str"><b>${escapeHtml(l.team)} ${s.team}</b> v ${escapeHtml(oppOf(l))} ${s.opp}`
    + (s.win != null ? ` &middot; ${pct(s.win)} to win` : "") + `</div>`;
}
function strengthDetail(l) {
  const s = l.strength;
  if (!s || s.team == null) return "";
  const bits = [`${escapeHtml(l.team)} rated ${s.teamLabel}, ${escapeHtml(oppOf(l))} ${s.oppLabel}`];
  if (s.similarN >= 2) bits.push(`${s.similarHits} of ${s.similarN} against similar opposition`);
  else bits.push("nothing comparable in the record");
  const exp = [];
  if (s.eloExpected != null) exp.push(`strength expects ${s.eloExpected}`);
  if (s.projection != null) exp.push(`the projection ${s.projection}`);
  if (exp.length) bits.push(`${exp.join(" and ")} against a line of ${l.line}`);
  return bits.join("; ") + ". ";
}
function chanceText(l) {
  return l.chance != null ? `${Math.round(l.chance * 100)}%` : "&mdash;";
}
/* Whether a value figure is shown as value: above the bar weekend.VALUE_SHOW
   sets, and never while that is off (RULE-REVIEW.md). */
function valueClaimed(v) {
  const bar = DATA.picks && DATA.picks.valueShow;
  return v != null && bar != null && v > bar;
}
/* The exchange, where Betfair prices the same bet: its chance with the margin
   off, the back price you could take, and what the pick is worth at it. */
function exchangeLine(l) {
  const x = l.exchange;
  if (!x) return "";
  const pct = p => `${Math.round(p * 100)}%`;
  const v = l.value;
  if (l.disagree != null) {
    return `<div class="pk-str">Exchange ${pct(x.p)}, model ${pct(l.chanceModel)}: <b>${Math.round(Math.abs(l.disagree) * 100)} points apart</b>,
      a warning rather than an edge; the chance used leans on the exchange.</div>`;
  }
  const val = v == null ? "" : valueClaimed(v)
    ? ` &middot; <b class="pk-pos">value +${Math.round(v * 100)}%</b> at ${fmtOdds(x.back)}`
    : ` &middot; no value at ${fmtOdds(x.back)}`;
  return `<div class="pk-str">Exchange ${pct(x.p)}, model ${pct(l.chanceModel)}${val}${x.tight ? "" : " &middot; thin market"}</div>`;
}
function thirdChip(s) {
  return s.exchange && s.exchange.back ? ["Exchange", fmtOdds(s.exchange.back)] : ["Hold out", fmtOdds(s.need)];
}
function pkChips(items) {
  return `<div class="pk-chips">${items.map(([k, v]) => `<div class="pk-chip"><span>${k}</span><b>${v}</b></div>`).join("")}</div>`;
}
function pkHead(label, price, priceLabel) {
  return `<div class="pk-top"><h2>${label}</h2>${price == null ? "" : `<div class="pk-price"><small>${priceLabel || "fair"}</small>${fmtOdds(price)}</div>`}</div>`;
}
/* Book prices (23 Oct 2026): a leg Paddy Power or Bet365 offers at our fair
   price or longer shows that price and the book; otherwise our fair price. */
function bookOk(l) { return l.book && l.book.price >= l.fair && l.book.price <= l.fair * 1.3; }
const bookShort = n => n === "Paddy Power" ? "PP" : n === "Bet365" ? "B365" : n;
function legRow(l, extra) {
  const where = l.fixture ? `${escapeHtml(l.fixture.home)} v ${escapeHtml(l.fixture.away)}` : "";
  const s = l.strength;
  const str = s && s.team != null ? ` &middot; ${s.team} v ${s.opp}` : "";
  const ex = l.exchange && l.exchange.back
    ? ` &middot; exchange ${fmtOdds(l.exchange.back)}${valueClaimed(l.value) ? ` <b class="pk-pos">+${Math.round(l.value * 100)}%</b>` : ""}` : "";
  const bk = bookOk(l) ? ` &middot; fair ${fmtOdds(l.fair)}` : (l.book ? ` &middot; ${bookShort(l.book.name)} only ${fmtOdds(l.book.price)}` : " &middot; not priced at a book");
  const shown = bookOk(l) ? `<small>${bookShort(l.book.name)}</small> ${fmtOdds(l.book.price)}` : fmtOdds(l.fair);
  return `<li class="pk-leg"><span class="t">${legText(l)}</span><span class="p">${shown}</span>
    <span class="m">${where}${where ? " &middot; " : ""}${l.hits}/${l.total}${l.chance != null ? " &middot; " + chanceText(l) : ""}${str}${ex}${bk}${extra || ""}</span></li>`;
}

/* Why a pick should land: the evidence for and against, then, behind a
   fold, how its chance was built number by number (why.py writes these). */
function whyList(l, max) {
  const w = l.why;
  if (!w) return "";
  const pro = (w.for || []).slice(0, max || 4).map(t => `<div class="y">${escapeHtml(t)}</div>`);
  const con = (w.against || []).slice(0, max || 3).map(t => `<div class="n">${escapeHtml(t)}</div>`);
  return pro.length || con.length ? `<div class="pk-why">${pro.join("")}${con.join("")}</div>` : "";
}
function whySteps(l) {
  const w = l.why;
  if (!w || !w.steps || !w.steps.length) return "";
  return `<ol class="pk-steps">${w.steps.map(t => `<li>${escapeHtml(t)}</li>`).join("")}</ol>`;
}
function whyFold(summary, l, extra) {
  const steps = whySteps(l);
  if (!steps && !extra) return "";
  return `<details><summary>${summary}</summary>${steps}${extra ? `<p>${extra}</p>` : ""}</details>`;
}
function legsWhy(legs) {
  const body = legs.map(l => `<p><b>${legText(l)}</b></p>${whyList(l, 3)}${whySteps(l)}`).join("");
  return `<details><summary>why each leg</summary>${body}</details>`;
}
function valueText(v) {
  return v == null ? "&mdash;" : `${v >= 0 ? "+" : "&minus;"}${Math.abs(v * 100).toFixed(1)}%`;
}

function note(summary, body) {
  return `<details><summary>${summary}</summary><p>${body}</p></details>`;
}

function renderPicks() {
  const box = document.getElementById("picks");
  const all = DATA.picks && DATA.picks.sports;
  if (!box || !all) return;

  const p = all.find(x => x.sport === sport);
  const lab = document.getElementById("picks-sport");
  if (lab) lab.textContent = SPORT_LABELS[sport] || sport;
  const floor = DATA.picks.floor;
  const cards = [];
  const learn = DATA.picks.learned;

  if (p && p.matches && p.matches.length) {
    const rows = p.matches.slice(0, 8).map(x => `<li class="pk-leg"><span class="t">${escapeHtml(x.fav)}</span>
      <span class="p">${fmtOdds(x.fair)}</span>
      <span class="m">${escapeHtml(x.home)} v ${escapeHtml(x.away)} &middot; ${Math.round(x.p * 100)}% to win${x.legs != null ? ` &middot; ${x.legs.toFixed(1)} legs` : ""}${x.s180 != null ? ` &middot; ${x.s180.toFixed(1)} 180s` : ""}</span></li>`).join("");
    cards.push(`<div class="pick">
      ${pkHead("Match prices", null, "")}
      <div class="where">Favourite and fair price for each match; totals, handicaps and 180s on each match's Match tab.</div>
      <ul class="pk-legs">${rows}</ul>
      ${note("how good is this?",
        `One leg-level rating per player over every PDC result since 2018. Replayed over 1,723 past matches it put
         its favourite through 61% of the time and was calibrated within a point or two up to 80%. Fair is what the
         chance is worth, not what anyone offers.`)}
    </div>`);
  }

  // Picks of the week, rebuilt on evidence (weekpicks.py, 2 Nov 2026): only
  // methods with a record behind them, and the record shown with them.
  const ev = DATA.picks && DATA.picks.evidence;
  const es = ev && ev.sports ? ev.sports[sport] : null;
  const pct = x => x == null ? "&mdash;" : `${Math.round(x * 100)}%`;
  const sgn = x => `${x >= 0 ? "+" : "&minus;"}${Math.abs(x * 100).toFixed(1)}%`;
  const when = t => {
    const d = new Date(t * 1000);
    return d.toLocaleDateString("en-GB", { weekday: "short" }) + " " + d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  };
  const evRow = (b, right) => `<li class="ev-row">
    <span class="t">${escapeHtml(b.bet)}</span>
    <span class="p"><small>${escapeHtml(bookShort(b.book))}</small>${fmtOdds(b.price)}</span>
    <span class="m">${escapeHtml(b.game || "")} &middot; ${when(b.kickoff)}</span>
    <span class="e">${right || ""}</span></li>`;
  const tone = x => x > 0 ? "up" : x < 0 ? "down" : "";
  if (es && es.sharp && es.sharp.length) {
    const r = ev.sharpRecord;
    const rec = r ? `<div class="ev-rec">Record <b>${r.n}</b> settled &middot; returned
        <b class="${tone(r.roi)}">${sgn(r.roi)}</b> &middot; sharp price said <b>${sgn(r.expected)}</b>
        &middot; ${r.noise ? "within normal swing" : '<b class="down">bigger gap than luck</b>'}</div>` : "";
    cards.push(`<div class="pick ev">
      <h2>Beats the sharp price</h2>
      <p class="ev-sub">Bookies paying more than Pinnacle or Betfair's fair chance.</p>
      ${rec}
      <ul class="ev-list">${es.sharp.map(b => evRow(b,
        `<span title="${escapeAttr(b.note)}">${escapeHtml(b.sharpSrc || "Sharp")} ${pct(b.sharp)}</span><b class="up">${sgn(b.edge)}</b>`)).join("")}</ul>
      ${note("how to read this", `The green figure is the edge: what the sharp chance says this price is worth. It is
        small and only real on average, over many bets, so use level stakes and check the price is still there.
        ${r ? `One standard error on the record is ${Math.round(r.se * 100)} points, so the gap between returned and
        expected means nothing until it is well past that.` : ""}`)}
    </div>`);
  }
  if (es && es.rules && es.rules.length) {
    const block = g => {
      const r = g.record;
      const stat = r ? `<b class="${tone(r.roi)}">${sgn(r.roi)}</b>` : `<span class="ev-new">new</span>`;
      const sub = r ? `${r.games} game${r.games === 1 ? "" : "s"} live &middot; range ${sgn(r.lo)} to ${sgn(r.hi)}`
        : "No live result yet";
      return `<div class="ev-rule">
        <div class="ev-rh"><span class="n" title="${escapeAttr(g.title)}">${escapeHtml(g.name || g.title)}${g.proven ? ` <span class="pk-tag proven">Proven</span>` : ""}</span>${stat}</div>
        <div class="ev-rs">${sub}</div>
        <ul class="ev-list">${g.bets.map(b => evRow(b)).join("")}</ul></div>`;
    };
    // the three strongest live records open; the rest, and untried rules, folded
    const tried = es.rules.filter(g => g.record), top = tried.slice(0, 3);
    const more = tried.slice(3).concat(es.rules.filter(g => !g.record));
    cards.push(`<div class="pick ev">
      <h2>Rules on trial</h2>
      <p class="ev-sub">Fixed rules and today's bets from each, judged on live results only.</p>
      ${top.map(block).join("")}
      ${more.length ? `<details class="ev-fresh"><summary>${more.length} more rule${more.length === 1 ? "" : "s"}${top.length ? "" : " (none tested live yet)"}</summary>${more.map(block).join("")}</details>` : ""}
      ${note("how rules get here", `Each rule was found on past prices, then frozen, and is judged only on games
        after that. It is marked Proven once 20+ live games put its whole 90% range above zero; until then this is
        tracking, not advice. Rules that are clearly failing are left off. Full records are on the
        <a href="tonight.html">Tonight</a> page.`)}
    </div>`);
  }

  // Strong record, model backs it (weekpicks.py, 3 Nov 2026): a record of 9+
  // in his last 10 that our model also rates at or above the price.
  if (es && es.record && es.record.length) {
    const rr = ev.recordRecord || {};
    const rule = ev.recordRule || {};
    const tally = (label, t) => t && t.n
      ? `${label} <b>${t.n}</b> settled &middot; won <b>${pct(t.won / t.n)}</b> (price said ${pct(t.implied)})
          &middot; returned <b class="${tone(t.roi)}">${sgn(t.roi)}</b>`
      : `${label}: no settled bets yet`;
    cards.push(`<div class="pick ev">
      <h2>Strong record, model backs it</h2>
      <p class="ev-sub">Cleared in ${rule.minK10 || 9}+ of his last 10, at ${fmtOdds(rule.priceLo || 1.25)} to
        ${fmtOdds(rule.priceHi || 2.5)}, and our model rates it at or above the price.</p>
      <div class="ev-rec">${tally("Live", rr.live)}<br>${tally("Before 3 Nov", rr.history)}</div>
      <ul class="ev-list">${es.record.map(b => evRow(b,
        `<span>${escapeHtml(b.form)} &middot; ours ${pct(b.chance)}</span><b class="${tone(b.edge)}">${sgn(b.edge)}</b>`)).join("")}</ul>
      ${note("how to read this", `The "Before 3 Nov" record is the data this filter was chosen on, so it flatters
        it: judge it on the live record. Left off: players listed out or doubtful, players who came off the bench in
        their last game, and NBA games projected ${rule.marginMax || 12}+ points apart. NFL is receiving lines only.
        One line per player; level stakes.`)}
    </div>`);
  }

  box.innerHTML = cards.length
    ? `<div class="picks">${cards.join("")}</div>`
    : `<div class="picks"><div class="pick none">Nothing for
       ${escapeHtml(SPORT_LABELS[sport] || sport)} in the next ${(ev && ev.windowHours) || 48} hours beats a sharp
       price, comes from a rule on trial or has a strong record the model backs. Picks appear once the books price the games (Paddy Power about a day
       before kick-off).</div></div>`;
}

/* The picks rail. Open or folded is remembered per browser, which is a
   convenience only: storage can be missing or throw, and the page works the
   same without it. */
const FOLD_KEY = "hitrates.picksOpen";
function setFold(open) {
  document.getElementById("picks").hidden = !open;
  document.getElementById("picks-btn").setAttribute("aria-expanded", String(open));
}
try { setFold(localStorage.getItem(FOLD_KEY) !== "0"); } catch (e) { setFold(true); }
document.getElementById("picks-btn").addEventListener("click", e => {
  const open = e.currentTarget.getAttribute("aria-expanded") !== "true";
  setFold(open);
  try { localStorage.setItem(FOLD_KEY, open ? "1" : "0"); } catch (err) {}
});

/* Narrow screens: the rail is a drawer behind the tab on the right edge. */
function drawer(open) {
  document.body.classList.toggle("drawer-open", open);
  document.getElementById("side-tab").setAttribute("aria-expanded", String(open));
}
document.getElementById("side-tab").addEventListener("click", () => drawer(true));
document.getElementById("drawer-close").addEventListener("click", () => drawer(false));
document.getElementById("scrim").addEventListener("click", () => drawer(false));
document.addEventListener("keydown", e => { if (e.key === "Escape") drawer(false); });

renderSports();
renderPicks();
renderFilters();
renderList();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
