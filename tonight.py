"""
One small page of what is on soon, built from the reports already on disk.

    python tonight.py                    the next 6 hours
    python tonight.py --hours 12         a longer window
    python tonight.py --all              everything still to come

Why this exists, and why it is deliberately not another report.

A built report is one to twenty megabytes: the whole dataset is inlined so the
page can rebuild any view without a server. That is the right trade for a
laptop and a browser and completely the wrong one for a phone on 4G at a bus
stop -- and it also means nothing but a real browser can read it. A fetcher
truncates it to the first fixture and sees no numbers at all, which is exactly
what happened the evening this was written: the reports had been published
hours before kickoff and were still unusable, because the only thing that
could read them was a machine that was asleep.

So this renders the answers rather than the data. It runs the same engine --
weekend.legs_for, best_acca, builders_for, parlay -- over the payloads already
sitting in reports/, and writes a static page of maybe forty kilobytes with no
JavaScript in it. That page is legible on a phone, legible to a fetcher, and
needs nothing running anywhere once it is published.

It is a view, not a source. Every number here came out of a report, so it is
exactly as fresh as the last build and no fresher, and the header says when
that was.
"""

import argparse
import html
import time
from pathlib import Path

import make_index
import parlay
import weekend

ROOT = Path(__file__).resolve().parent

# How many single legs to print per fixture. Enough to choose from, few enough
# that the page stays a page. The scan behind it has already ranked them.
SINGLES_PER_FIXTURE = 6

# Below this, a leg is not worth a slot.
#
# Ranking singles purely on evidence fills the list with 1.11 shots: "1+
# tackles, 28 from 31" is a near-certainty and therefore always wins an
# evidence sort, and it is also not a bet -- four of them multiply to less
# than evens and the margin eats the lot. parlay.py already draws this line
# for the same reason, so the same number is used here rather than a second
# opinion about it.
MIN_PRICE = parlay.MIN_LEG_PRICE

# The multi is offered at several shapes rather than one, because "a treble"
# and "something paying about eight" are different questions and the honest
# answer to the second is sometimes four legs rather than three.
ACCA_SHAPES = ((3, 3.0), (3, 6.0), (4, 10.0))


def fmt_leg(leg) -> str:
    """A leg written the way a coupon writes it."""
    who = leg.get("player") or leg.get("team") or "?"
    stat = (leg.get("stat") or "").lower()
    if leg.get("alt"):
        market = f"{leg['threshold']:.0f}+ {stat}"
    else:
        market = f"{'over' if leg.get('over') else 'under'} {leg.get('line')} {stat}"
    period = leg.get("period")
    when = "" if period in (None, "ALL") else f" ({'first half' if period == '1ST' else 'second half'})"
    return f"{who} {market}{when}"


def legs_of(entry, meta) -> list:
    """Every priceable leg on one fixture, each one only once.

    The three sources overlap: an alt line and a single can describe the same
    bet from different directions, and printing "Zaire-Emery 1+ tackles"
    twice in a six-row table is how a short list stops looking trustworthy.
    """
    out, seen = [], set()
    for leg in (weekend.legs_for(entry, meta)
                + parlay.single_legs_for(entry, meta)
                + parlay.alt_legs_for(entry, meta)):
        key = (leg.get("player"), leg.get("team"), leg.get("stat"),
               leg.get("period"), leg.get("line"), leg.get("over"))
        if key in seen:
            continue
        seen.add(key)
        out.append(leg)
    return out


def odds(x) -> str:
    return f"{x:.2f}" if isinstance(x, (int, float)) and x == x and x != float("inf") else "&mdash;"


def leg_row(leg) -> str:
    hits, total = leg.get("hits"), leg.get("total")
    record = f"{hits}/{total}" if total else "&mdash;"
    # The venue split is printed because it repeatedly changes the answer, and
    # a rate quoted without it has quietly averaged two different teams.
    where = {"home": " at home", "away": " away"}.get(leg.get("venue"), "")
    return (
        f"<tr><td>{html.escape(fmt_leg(leg))}{where}</td>"
        f"<td class='n'>{record}</td>"
        f"<td class='n'>{odds(leg.get('fair'))}</td>"
        f"<td class='n'>{odds(leg.get('need'))}</td></tr>"
    )


def builder_block(builder) -> str:
    """A same-game builder, with the correlation discount shown rather than hidden."""
    if not builder:
        return "<p class='none'>No same-game builder here: no set of legs on one team both qualified and co-occurred often enough to price.</p>"
    rows = "".join(f"<li>{html.escape(fmt_leg(l))}</li>" for l in builder["legs"])
    fair = builder.get("fair")
    naive = builder.get("naive")
    need = builder.get("need")
    hits, total = builder.get("hits"), builder.get("total")

    gap = ""
    if isinstance(fair, (int, float)) and isinstance(naive, (int, float)) and naive > fair:
        gap = (f" Multiplying the legs would say <b>{naive:.2f}</b>; they actually "
               f"landed together {hits} times in {total}, so the real price is "
               f"<b>{fair:.2f}</b>. That gap is the correlation, and it is the whole "
               f"reason a builder looks better than it is.")

    return (
        f"<ul class='legs'>{rows}</ul>"
        f"<p class='price'>Landed together <b>{hits}/{total}</b> &middot; "
        f"fair <b>{fair:.2f}</b> &middot; "
        f"needs <b>{need:.2f}</b> to be a bet on the evidence.{gap}</p>"
    )


def acca_block(acca, wanted, target) -> str:
    if not acca or not acca.get("legs"):
        return ""
    rows = "".join(
        f"<li>{html.escape(fmt_leg(l))} "
        f"<span class='sub'>{l.get('hits')}/{l.get('total')} &middot; "
        f"fair {l['fair']:.2f} &middot; "
        f"{html.escape((l.get('fixture') or {}).get('home','?'))} v "
        f"{html.escape((l.get('fixture') or {}).get('away','?'))}</span></li>"
        for l in acca["legs"]
    )
    combined = acca.get("combined")
    short = acca.get("short")
    note = (f" Short of the {target:.2f} asked for &mdash; nothing on the board "
            f"multiplies that far at this many legs." if short else "")
    return (
        f"<h3>{wanted} legs, aiming at {target:.2f}</h3>"
        f"<ol class='legs'>{rows}</ol>"
        f"<p class='price'>Fair combined <b>{combined:.2f}</b>.{note}</p>"
    )


def build(hours: float | None) -> str:
    entries: list[tuple[dict, dict]] = []
    seen: set[tuple] = set()
    newest = 0.0
    for path in sorted((ROOT / "reports").glob("*.html")):
        if path.name.startswith("pick-"):
            continue
        newest = max(newest, path.stat().st_mtime)
        for entry, meta in make_index.read_entries(path):
            key = (meta["home"], meta["away"], meta["kickoff"])
            if key in seen:
                continue
            seen.add(key)
            entries.append((entry, meta))

    now = time.time()
    horizon = now + hours * 3600 if hours else float("inf")
    window = sorted(
        [(e, m) for e, m in entries if now < m["kickoff"] <= horizon],
        key=lambda pair: pair[1]["kickoff"],
    )

    built = time.strftime("%a %d %b, %H:%M %Z", time.localtime(newest))
    span = f"the next {hours:g} hours" if hours else "everything still to come"

    if not window:
        body = (f"<p class='none'>Nothing kicks off in {span}. "
                f"The reports were built {built}.</p>")
        return PAGE.format(built=built, span=span, body=body,
                           stamp=time.strftime("%a %d %b, %H:%M %Z", time.localtime(now)))

    # ---------------------------------------------------------- the multi
    legs = []
    for entry, meta in window:
        legs.extend(legs_of(entry, meta))

    multi = "".join(
        acca_block(weekend.best_acca(legs, wanted=w, target=t), w, t)
        for w, t in ACCA_SHAPES
    )

    # ------------------------------------------------------ the same games
    blocks = []
    for entry, meta in window:
        kick = time.strftime("%H:%M", time.localtime(meta["kickoff"]))
        builders = weekend.builders_for(entry, meta) or []
        best = max(builders, key=lambda b: b.get("evidence", 0)) if builders else None

        own = sorted(
            [l for l in legs_of(entry, meta)
             if isinstance(l.get("fair"), (int, float))
             and l["fair"] >= MIN_PRICE],
            key=lambda l: -(l.get("evidence") or 0),
        )[:SINGLES_PER_FIXTURE]

        singles = "".join(leg_row(l) for l in own) or "<tr><td colspan='4'>nothing qualified</td></tr>"
        blocks.append(
            f"<section><h2>{kick} &middot; {html.escape(meta['home'])} v "
            f"{html.escape(meta['away'])}</h2>"
            f"<p class='comp'>{html.escape(meta['competition'])}</p>"
            f"<h3>Same-game builder</h3>{builder_block(best)}"
            f"<h3>Best singles here</h3>"
            f"<table><thead><tr><th>Selection</th><th class='n'>Record</th>"
            f"<th class='n'>Fair</th><th class='n'>Need</th></tr></thead>"
            f"<tbody>{singles}</tbody></table></section>"
        )

    body = (f"<section><h2>Multi across the {len(window)} games</h2>{multi}</section>"
            + "".join(blocks))
    return PAGE.format(built=built, span=span, body=body,
                       stamp=time.strftime("%a %d %b, %H:%M %Z", time.localtime(now)))


PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tonight</title>
<style>
:root {{ --bg:#fcfcfb; --fg:#0b0b0b; --muted:#75736e; --line:rgba(11,11,11,.12); --accent:#d03b3b; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#141413; --fg:#fff; --muted:#908e88; --line:rgba(255,255,255,.14); }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:20px 16px 60px; background:var(--bg); color:var(--fg);
  font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  max-width:760px; margin-inline:auto; }}
h1 {{ font-size:22px; margin:0 0 4px; }}
h2 {{ font-size:18px; margin:32px 0 2px; }}
h3 {{ font-size:14px; text-transform:uppercase; letter-spacing:.06em;
  color:var(--muted); margin:20px 0 6px; font-weight:600; }}
section {{ border-top:1px solid var(--line); padding-top:4px; }}
.comp, .sub {{ color:var(--muted); font-size:13px; }}
.stamp {{ color:var(--muted); font-size:13px; margin:0 0 8px; }}
.legs {{ margin:6px 0; padding-left:20px; }}
.legs li {{ margin:3px 0; }}
.price {{ font-size:14px; margin:6px 0 0; }}
.none {{ color:var(--muted); font-size:14px; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; margin-top:4px; }}
th, td {{ text-align:left; padding:6px 4px; border-bottom:1px solid var(--line); }}
th {{ color:var(--muted); font-weight:600; font-size:12px; text-transform:uppercase;
  letter-spacing:.04em; }}
.n {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
.warn {{ border-left:3px solid var(--accent); padding:10px 14px; margin:16px 0;
  font-size:13.5px; color:var(--muted); }}
</style></head><body>
<h1>Tonight</h1>
<p class="stamp">{span} &middot; page made {stamp} &middot; numbers from reports built {built}</p>
<div class="warn">
Fair and Need are what the record implies, not what anyone is offering.
<b>Need</b> is the price the evidence supports once the sample size is paid for,
and it is the one to bet off. Neither includes the bookmaker's margin, which
runs 5&ndash;8% a market and compounds with every leg you add.
</div>
{body}
<div class="warn">
A multiple is worse than its legs. The margin compounds, the legs in one round
are correlated, and the shop sells accumulators because they are the most
profitable thing on the counter. The same-game prices above already carry that
discount; the cross-game ones do not, and are therefore optimistic.
</div>
</body></html>
"""


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hours", type=float, default=6,
                    help="how far ahead to look (default 6)")
    ap.add_argument("--all", action="store_true",
                    help="every upcoming fixture, no time limit")
    args = ap.parse_args(argv)

    page = build(None if args.all else args.hours)
    out = ROOT / "tonight.html"
    out.write_text(page, encoding="utf-8")
    print(f"Wrote {out} ({len(page)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
