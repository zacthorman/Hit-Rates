"""A clean front end for picking a bet, generated from reports already built.

    python3 picker.py            # every report
    python3 picker.py nfl        # one of them

The detailed report answers "what does this whole fixture look like". This
answers the only question you have standing at the coupon: what does this man
do, at what line, and what is it worth. Fixture, then player, then market,
then the ladder -- and nothing else on screen.

It is a separate page on purpose. The report is four thousand lines of working
code with a scan, a slip, matchups and head to heads in it, and rewriting that
to look nicer is a good way to break something that works. This reads the same
payload, keeps only what a picker needs, and leaves the report alone. Every
page links to its report for the full detail.

Payload: one file per league, self-contained, so it opens from disk as well as
from the published site. A shared page fetching JSON would be tidier and would
not open locally, which is how these get checked.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import markets

ROOT = Path(__file__).parent
REPORTS = ROOT / "reports"

# Players with less than this many appearances are dropped. A three-game
# record is not a ladder, it is a rumour, and leaving them in makes the
# player list twice as long for no gain.
MIN_APPS = 6

# Who to show first. Alphabetical put a cornerback at the top of a squad list
# and "defensive assist tackles" at the top of his markets, which is nobody's
# first question about an NFL game. Positions the feed actually reports, best
# first; anything unlisted sorts after, by appearances.
POSITION_ORDER = {
    "american-football": ["QB", "RB", "FB", "WR", "TE", "K"],
    "football": ["F", "M", "D", "G"],
    "basketball": ["G", "F", "C"],
}


def slim(payload: dict) -> list[dict]:
    """Just enough of a report to pick a bet from."""
    out = []
    for entry in payload.get("fixtures", []):
        fx = entry["fixture"]
        sport = fx.get("sport") or "football"
        bettable = markets.player_stats_for(sport)
        team_markets = markets.stats_for(sport)

        players = []
        for team_index, side in enumerate(entry.get("players") or []):
            grouped: dict[str, dict] = {}
            for record in side:
                name = record.get("player")
                if not name:
                    continue
                slot = grouped.setdefault(name, {
                    "n": name, "p": record.get("position") or "",
                    "t": team_index, "s": {},
                })
                # Each appearance carries its venue, so the page can split
                # home from away. That split has changed the answer more than
                # once -- a leg worth 1.43 across twenty games and 1.80 away
                # from home is the difference between a bet and a mistake --
                # and it costs about a third more payload to carry it.
                where = "h" if record.get("venue") == "home" else "a"
                for stat, value in (record.get("stats") or {}).items():
                    if stat not in bettable or value is None:
                        continue
                    slot["s"].setdefault(stat, []).append([round(float(value), 1), where])
            order = POSITION_ORDER.get(sport, [])
            for slot in grouped.values():
                apps = max((len(v) for v in slot["s"].values()), default=0)
                if apps < MIN_APPS:
                    continue
                pos = (slot["p"] or "").upper()
                slot["r"] = order.index(pos) if pos in order else len(order)
                slot["a"] = apps
                players.append(slot)
            players.sort(key=lambda x: (x["t"], x.get("r", 99), -x.get("a", 0), x["n"]))

        teams = []
        for team_index, records in enumerate(entry.get("records") or []):
            stats: dict[str, list] = {}
            for record in records:
                where = "h" if record.get("venue") == "home" else "a"
                for stat, value in ((record.get("stats") or {}).get("ALL") or {}).items():
                    if stat in team_markets and value is not None:
                        stats.setdefault(stat, []).append([round(float(value), 1), where])
            teams.append({"n": entry["teams"][team_index]["name"],
                          "side": entry["teams"][team_index].get("side"), "s": stats})

        out.append({
            "id": fx["id"], "h": fx["home"], "a": fx["away"],
            "k": fx.get("kickoff"), "c": fx.get("competition"),
            "sp": sport, "teams": teams, "pl": players,
        })
    return out


CSS = """
:root {
  --bg:#fbfbfa; --card:#fff; --fg:#1a1a18; --muted:#78776f; --line:#e7e6e1;
  --accent:#b4541f; --accent-soft:#fdf2ec; --good:#2f6f4f;
  --radius:10px;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme=light]) {
    --bg:#131312; --card:#1c1c1a; --fg:#eceae4; --muted:#95938a; --line:#2c2c29;
    --accent:#e08a55; --accent-soft:#2a1d15; --good:#6fbb8f;
  }
}
:root[data-theme=dark] {
  --bg:#131312; --card:#1c1c1a; --fg:#eceae4; --muted:#95938a; --line:#2c2c29;
  --accent:#e08a55; --accent-soft:#2a1d15; --good:#6fbb8f;
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Inter,system-ui,sans-serif;
  -webkit-font-smoothing:antialiased; }
.wrap { max-width:760px; margin:0 auto; padding:0 20px 80px; }
header { display:flex; align-items:baseline; gap:12px; padding:28px 0 20px; }
h1 { font-size:17px; font-weight:600; margin:0; letter-spacing:-0.01em; }
.sub { color:var(--muted); font-size:13px; }
.ghost { margin-left:auto; background:none; border:1px solid var(--line);
  color:var(--muted); border-radius:99px; padding:5px 12px; font-size:12px;
  cursor:pointer; font-family:inherit; }
.ghost:hover { color:var(--fg); border-color:var(--muted); }

.rows { border-top:1px solid var(--line); }
.row { display:flex; gap:14px; align-items:center; width:100%; text-align:left;
  padding:13px 4px; border:0; border-bottom:1px solid var(--line);
  background:none; color:inherit; font:inherit; cursor:pointer; }
.row:hover { background:var(--card); }
.row .when { color:var(--muted); font-size:12px; width:96px; flex:none;
  font-variant-numeric:tabular-nums; }
.row .tie { font-weight:500; }
.row .comp { margin-left:auto; color:var(--muted); font-size:11px;
  border:1px solid var(--line); border-radius:99px; padding:2px 9px; flex:none; }

.back { background:none; border:0; color:var(--muted); font:inherit;
  font-size:13px; cursor:pointer; padding:20px 0 6px; }
.back:hover { color:var(--fg); }
h2 { font-size:20px; margin:0 0 2px; letter-spacing:-0.015em; }
.meta { color:var(--muted); font-size:13px; margin-bottom:22px; }

.seg { display:inline-flex; background:var(--card); border:1px solid var(--line);
  border-radius:99px; padding:3px; margin-bottom:18px; }
.seg button { border:0; background:none; color:var(--muted); font:inherit;
  font-size:13px; padding:5px 15px; border-radius:99px; cursor:pointer; }
.seg button[aria-pressed=true] { background:var(--accent); color:#fff; }

.picks { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:22px; }
@media (max-width:560px) { .picks { grid-template-columns:1fr; } }
label { display:block; font-size:11px; color:var(--muted); margin-bottom:5px;
  text-transform:uppercase; letter-spacing:.06em; }
select { width:100%; appearance:none; background:var(--card); color:var(--fg);
  border:1px solid var(--line); border-radius:var(--radius); padding:10px 34px 10px 12px;
  font:inherit; font-size:14px; cursor:pointer;
  background-image:linear-gradient(45deg,transparent 50%,currentColor 50%),
    linear-gradient(135deg,currentColor 50%,transparent 50%);
  background-position:calc(100% - 17px) 50%, calc(100% - 12px) 50%;
  background-size:5px 5px,5px 5px; background-repeat:no-repeat; }
select:focus { outline:none; border-color:var(--accent); }

.summary { background:var(--card); border:1px solid var(--line);
  border-radius:var(--radius); padding:16px 18px; margin-bottom:6px; }
.summary .big { font-size:19px; font-weight:600; letter-spacing:-0.01em; }
.summary .seq { color:var(--muted); font-size:12px; margin-top:8px;
  font-variant-numeric:tabular-nums; word-spacing:2px; }
.chips { display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; }
.chip { font-size:12px; color:var(--muted); border:1px solid var(--line);
  border-radius:99px; padding:3px 10px; }
.chip b { color:var(--fg); font-weight:600; }

table { width:100%; border-collapse:collapse; margin-top:14px;
  font-variant-numeric:tabular-nums; }
th { text-align:right; font-size:11px; font-weight:500; color:var(--muted);
  text-transform:uppercase; letter-spacing:.06em; padding:0 0 8px;
  border-bottom:1px solid var(--line); }
th:first-child, td:first-child { text-align:left; }
td { padding:9px 0; border-bottom:1px solid var(--line); text-align:right;
  font-size:14px; }
tr.here td { background:var(--accent-soft); }
tr.here td:first-child { box-shadow:inset 2px 0 0 var(--accent); padding-left:9px; }
td.line { font-weight:600; }
td.dim { color:var(--muted); }
.note { color:var(--muted); font-size:12px; line-height:1.6; margin:18px 0 0; }
.empty { color:var(--muted); padding:28px 0; }
a.full { color:var(--accent); font-size:13px; text-decoration:none; }
a.full:hover { text-decoration:underline; }
"""

JS = r"""
const D = __DATA__;
const LEAGUE = __LEAGUE__;
const REPORT = __REPORT__;

const $ = s => document.querySelector(s);
const odds = v => (!isFinite(v) || v <= 0) ? "—" : v >= 100 ? "99+" : v.toFixed(2);
const isYards = s => /yards/i.test(s);

function wilsonLow(k, n, z = 1.96) {
  if (!n) return 0;
  const p = k / n, d = 1 + z * z / n;
  const c = p + z * z / (2 * n);
  const m = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n));
  return Math.max(0, (c - m) / d);
}

/* The rungs a book posts: fives up to fifty, tens above, whole numbers for
   anything countable. Same shape as the report and the parlay engine. */
function rungs(stat, values) {
  const top = Math.max(...values);
  if (!(top > 0)) return [];
  const out = [];
  if (isYards(stat)) {
    for (let t = 5; t < 50; t += 5) out.push(t);
    for (let t = 50; t <= top + 10; t += 10) out.push(t);
  } else {
    for (let t = 1; t <= Math.floor(top); t++) out.push(t);
  }
  return out.filter(t => t <= top);
}

function ladder(stat, values) {
  const n = values.length;
  const all = rungs(stat, values).map(t => {
    const k = values.filter(v => v >= t).length;
    return { t, k, n, rate: k / n };
  }).filter(r => r.k > 0 && r.rate < 1 && r.rate >= 0.15);
  // One row per distinct record, at the highest line that achieves it.
  return all.filter((r, i) => i === all.length - 1 || all[i + 1].k !== r.k);
}

let view = { fixture: null, mode: "players", team: 0, who: "", stat: "", venue: "all" };

/* Markets in the order this player actually does them, not alphabetically.
   A receiver's receiving yards should be the first thing offered; his
   defensive tackles, if the feed bothered to record one, should be last. */
function statsByVolume(bag) {
  return Object.keys(bag).sort((a, b) => {
    const live = k => bag[k].filter(v => v[0] > 0).length;
    return live(b) - live(a) || a.localeCompare(b);
  });
}

// Appearances matching the venue filter, values only.
function pick(rows) {
  const want = view.venue;
  return (rows || []).filter(r => want === "all" || r[1] === want[0]).map(r => r[0]);
}

function fmtWhen(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toLocaleString(undefined,
    { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function renderList() {
  const rows = [...D].sort((a, b) => (a.k || 0) - (b.k || 0)).map((f, i) => `
    <button class="row" data-fx="${i}">
      <span class="when">${fmtWhen(f.k)}</span>
      <span class="tie">${f.h} v ${f.a}</span>
      <span class="comp">${f.c || ""}</span>
    </button>`).join("");
  $("#main").innerHTML = `<div class="rows">${rows || '<p class="empty">No fixtures.</p>'}</div>`;
  document.querySelectorAll("[data-fx]").forEach(b =>
    b.addEventListener("click", () => {
      // venue has to be reset here too. Leaving it out set view.venue to
      // undefined on every fixture opened from the list, and pick() then read
      // want[0] off nothing at all.
      view = { fixture: +b.dataset.fx, mode: "players", team: 0, who: "",
               stat: "", venue: "all" };
      history.replaceState(null, "", "#e" + D[view.fixture].id);
      renderFixture();
    }));
}

function optionsFor(f) {
  if (view.mode === "team") {
    const t = f.teams[view.team] || { s: {} };
    return { names: [t.n], stats: statsByVolume(t.s), values: s => pick(t.s[s]) };
  }
  const squad = f.pl.filter(p => p.t === view.team);   // already in squad order
  const byName = Object.fromEntries(squad.map(p => [p.n, p]));
  const names = squad.map(p => p.n);
  const who = byName[view.who] ? view.who : names[0];
  const stats = who ? statsByVolume(byName[who].s) : [];
  return { names, stats, values: s => (byName[who] ? pick(byName[who].s[s]) : []), who, byName };
}

function renderFixture() {
  const f = D[view.fixture];
  const opt = optionsFor(f);
  if (view.mode === "players") view.who = opt.who || "";
  if (!opt.stats.includes(view.stat)) view.stat = opt.stats[0] || "";
  const values = opt.values(view.stat);

  const teamBtns = f.teams.map((t, i) =>
    `<button data-team="${i}" aria-pressed="${i === view.team}">${t.n}</button>`).join("");

  const rows = values.length ? ladder(view.stat, values) : [];
  const body = rows.map(r => `
    <tr>
      <td class="line">${r.t}+</td>
      <td class="dim">${r.k}/${r.n}</td>
      <td>${Math.round(r.rate * 100)}%</td>
      <td><b>${odds(1 / r.rate)}</b></td>
      <td class="dim">${odds(1 / (1 - r.rate))}</td>
      <td class="dim">${odds(1 / wilsonLow(r.k, r.n))}</td>
    </tr>`).join("");

  const sorted = [...values].sort((a, b) => a - b);
  const n = sorted.length;
  const median = !n ? 0 : n % 2 ? sorted[(n - 1) / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2;
  const mean = n ? values.reduce((a, b) => a + b, 0) / n : 0;

  $("#main").innerHTML = `
    <button class="back" id="back">&larr; All fixtures</button>
    <h2>${f.h} v ${f.a}</h2>
    <div class="meta">${fmtWhen(f.k)} &middot; ${f.c || ""} &middot;
      <a class="full" href="${REPORT}#e${f.id}">full report</a></div>

    <div class="seg" id="mode">
      <button data-mode="players" aria-pressed="${view.mode === "players"}">Players</button>
      <button data-mode="team" aria-pressed="${view.mode === "team"}">Team</button>
    </div>
    <div class="seg" id="teams" style="margin-left:8px">${teamBtns}</div>
    <div class="seg" id="venue" style="margin-left:8px">
      ${[["all", "All games"], ["home", "Home"], ["away", "Away"]].map(([v, t]) =>
        `<button data-venue="${v}" aria-pressed="${view.venue === v}">${t}</button>`).join("")}
    </div>

    <div class="picks">
      ${view.mode === "players" ? `<div><label>Player</label>
        <select id="who">${opt.names.map(x =>
          `<option${x === view.who ? " selected" : ""}>${x}</option>`).join("")}</select></div>` : ""}
      <div><label>Market</label>
        <select id="stat">${opt.stats.map(x =>
          `<option${x === view.stat ? " selected" : ""}>${x}</option>`).join("")}</select></div>
    </div>

    ${n ? `<div class="summary">
      <div class="big">${view.mode === "players" ? view.who : f.teams[view.team].n}
        &middot; ${view.stat.toLowerCase()}</div>
      <div class="chips">
        <span class="chip">games <b>${n}</b></span>
        <span class="chip">median <b>${median % 1 ? median.toFixed(1) : median}</b></span>
        <span class="chip">average <b>${mean.toFixed(1)}</b></span>
        <span class="chip">best <b>${sorted[n - 1]}</b></span>
      </div>
      <div class="seq">${values.join("  ")}</div>
    </div>

    <table>
      <thead><tr><th>Line</th><th>Record</th><th>Rate</th>
        <th>Over</th><th>Under</th><th>Hold out</th></tr></thead>
      <tbody>${body}</tbody>
    </table>
    <p class="note"><b>Over</b> and <b>Under</b> are fair prices &mdash; one over
      the rate, and one over what is left. They are break-even, not an edge:
      back a line only where the book pays more than the number here.
      <b>Hold out</b> is the over price once the sample size is paid for, which
      on a short record is a long way further out. Lines the record never
      settles between are collapsed to the bigger number.</p>`
    : `<p class="empty">No record for that market.</p>`}`;

  $("#back").addEventListener("click", () => {
    history.replaceState(null, "", location.pathname + location.search);
    renderList();
  });
  document.querySelectorAll("#mode button").forEach(b =>
    b.addEventListener("click", () => { view.mode = b.dataset.mode; view.stat = ""; renderFixture(); }));
  document.querySelectorAll("#venue button").forEach(b =>
    b.addEventListener("click", () => { view.venue = b.dataset.venue; renderFixture(); }));
  document.querySelectorAll("#teams button").forEach(b =>
    b.addEventListener("click", () => { view.team = +b.dataset.team; view.who = ""; view.stat = ""; renderFixture(); }));
  const who = $("#who");
  if (who) who.addEventListener("change", () => { view.who = who.value; view.stat = ""; renderFixture(); });
  $("#stat").addEventListener("change", () => { view.stat = $("#stat").value; renderFixture(); });
}

$("#theme").addEventListener("click", () => {
  const now = document.documentElement.getAttribute("data-theme");
  const next = now === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try { localStorage.setItem("pickTheme", next); } catch (e) {}
});
try {
  const saved = localStorage.getItem("pickTheme");
  if (saved) document.documentElement.setAttribute("data-theme", saved);
} catch (e) {}

/* Open straight onto a fixture when the index sent us to one, and keep the
   address bar honest as you move around, so a link to a match is a link to
   that match rather than to the list it lives in. */
function fromHash() {
  const id = (location.hash.match(/^#e(\d+)/) || [])[1];
  if (!id) return false;
  const i = D.findIndex(f => String(f.id) === id);
  if (i < 0) return false;
  view = { fixture: i, mode: "players", team: 0, who: "", stat: "", venue: "all" };
  renderFixture();
  return true;
}
window.addEventListener("hashchange", () => { if (!fromHash()) renderList(); });
if (!fromHash()) renderList();
"""


def build(slug: str, label: str, data: list[dict]) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{label} &middot; pick a bet</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>{label}</h1>
    <span class="sub">pick a bet</span>
    <button class="ghost" id="theme">Theme</button>
  </header>
  <div id="main"></div>
</div>
<script>{JS.replace("__DATA__", json.dumps(data, separators=(",", ":")))
           .replace("__LEAGUE__", json.dumps(label))
           .replace("__REPORT__", json.dumps(f"{slug}.html"))}</script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> None:
    wanted = [a.lower() for a in (sys.argv[1:] if argv is None else argv)]
    made = 0
    for path in sorted(REPORTS.glob("*.html")):
        if path.name.startswith(("_", "pick-")):
            continue
        slug = path.stem
        if wanted and not any(w in slug for w in wanted):
            continue
        match = re.search(r"const ALL = (\{.*?\});\n", path.read_text(encoding="utf-8"), re.S)
        if not match:
            continue
        payload = json.loads(match.group(1))
        label = (payload["fixtures"][0]["fixture"].get("competition") or slug).split(",")[0]
        data = slim(payload)
        out = REPORTS / f"pick-{slug}.html"
        out.write_text(build(slug, label, data), encoding="utf-8")
        made += 1
        print(f"  {out.name:34} {len(data):3} fixtures  {out.stat().st_size / 1e6:.1f} MB")
    print(f"{made} picker page(s) written")


if __name__ == "__main__":
    main()
