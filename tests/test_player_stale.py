"""Player staleness (freshness.py), its use in pplog and rule_review, and the
page's mirror in report.py run in node. Synthetic data only.

    python -B -m unittest tests.test_player_stale
    python -m pytest tests/test_player_stale.py
"""
import gzip
import json
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import freshness as F  # noqa: E402
import player_stale as PS  # noqa: E402
import pplog  # noqa: E402
import rule_review as R  # noqa: E402
import run  # noqa: E402

NODE = shutil.which("node")


def d(s, days=0):
    return (date.fromisoformat(s) + timedelta(days=days)).isoformat()


# Last season every 4 days to 24 May, then 3 games from 16 August.
OLD = [d("2026-02-14", 4 * i) for i in range(25)]
NEW = ["2026-08-16", "2026-08-23", "2026-08-30"]


class Freshness(unittest.TestCase):
    def test_break_after_the_summer(self):
        self.assertEqual(F.break_date(OLD + NEW, "2026-09-05"), "2026-08-16")
        f = F.window((OLD + NEW)[-10:], "2026-08-16")
        self.assertEqual((f["fresh"], f["n"]), (3, 10))
        self.assertTrue(F.is_stale(f["share"]))

    def test_first_game_of_the_season_is_all_stale(self):
        # His last game was 24 May: the break is the kick-off itself.
        self.assertEqual(F.break_date(OLD, "2026-08-16"), "2026-08-16")
        self.assertEqual(F.window(OLD[-10:], "2026-08-16")["share"], 0.0)

    def test_no_break(self):
        self.assertIsNone(F.break_date(OLD, OLD[-1]))
        self.assertEqual(F.window(OLD[-10:], None)["share"], 1.0)
        self.assertFalse(F.is_stale(1.0))
        self.assertFalse(F.is_stale(None))
        self.assertEqual(F.window([], None), {"fresh": 0, "n": 0, "share": None})

    def test_gap_edges_and_timestamps(self):
        self.assertIsNone(F.break_date(["2026-01-01", d("2026-01-01", 44)], d("2026-01-01", 50)))
        self.assertEqual(F.break_date(["2026-01-01", d("2026-01-01", 45)], d("2026-01-01", 50)), d("2026-01-01", 45))
        ts = 1786838400   # 2026-08-16 00:00 UTC
        self.assertEqual(F.break_date([ts - 90 * 86400, ts], ts + 86400), "2026-08-16")
        # a long injury mid-season counts the same as the summer
        self.assertEqual(F.break_date(["2026-10-01", "2026-10-08", "2026-12-20"], "2026-12-27"), "2026-12-20")

    def test_player_breaks_and_run_helper(self):
        rows = [{"player": "A", "date": x} for x in OLD + NEW] + [{"player": "B", "date": x} for x in OLD]
        self.assertEqual(F.player_breaks(rows, "2026-09-05"), {"A": "2026-08-16", "B": "2026-09-05"})
        entry = {"fixture": {"national": False}}
        self.assertEqual(run.player_breaks_for(entry, [rows, []], {"startTimestamp": 1788566400}),
                         [{"A": "2026-08-16", "B": "2026-09-05"}, {}])
        self.assertIsNone(run.player_breaks_for({"fixture": {"national": True}}, [rows, []], {}))


class Verdicts(unittest.TestCase):
    def test_python_mirror(self):
        V = R.pp_verdict
        self.assertEqual(V(0.6, 1.70, fresh=0.3), "stale")
        self.assertEqual(V(0.6, 1.70, fresh=0.5), "ok")
        self.assertEqual(V(0.6, 1.70), "ok")
        self.assertEqual(V(0.6, 1.40, fresh=0.0), "avoid")         # price too short: still avoid
        self.assertEqual(V(0.45, 2.30, fresh=0.0), "long")         # under 50%: still a long shot
        self.assertEqual(V(0.6, 1.70, stat="Fouls", line=1.5, fresh=0.0), "long")

    def test_pplog_fresh_and_value(self):
        rows = [{"date": x, "minutes": 90} for x in OLD + NEW]
        entry = {"fixture": {}, "playerBreaks": [{"A": "2026-08-16"}, {}]}
        self.assertEqual(pplog._fresh(entry, 0, "A", rows, 45, 1788566400), 0.3)
        # no break carried for him: worked out from his rows, the same answer
        self.assertEqual(pplog._fresh({"fixture": {}}, 0, "A", rows, 45, 1788566400), 0.3)
        self.assertIsNone(pplog._fresh({"fixture": {"national": True}}, 0, "A", rows, 45, 1788566400))
        r = {"sport": "football", "stat": "Shots", "n10": 10,
             "first": {"chance": 0.6, "edge": 0.08}}
        self.assertTrue(pplog.is_value(r))
        self.assertTrue(pplog.is_value(dict(r, fresh=0.6)))
        self.assertFalse(pplog.is_value(dict(r, fresh=0.3)))


class Replay(unittest.TestCase):
    def test_choose_and_confirm(self):
        rng = random.Random(5)
        rows = []
        for i in range(6000):
            season = 2023 if i < 3600 else 2025
            month = 8 if i % 3 == 0 else 11
            ts = int(__import__("datetime").datetime(season, month, 10).timestamp()) + i
            fresh = 0.2 if i % 3 == 0 else 1.0
            p = 0.62
            land = 0.50 if fresh < 0.5 else 0.63
            rows.append({"event_id": i // 4, "ts": ts, "p": p, "won": rng.random() < land, "fresh": fresh,
                         "stat": "Shots", "line": 0.5, "started": True, "rest": 3})
        tmp = Path(tempfile.mkdtemp())
        try:
            path = tmp / "rows.json.gz"
            with gzip.open(path, "wt") as fh:
                json.dump(rows, fh)
            text = "\n".join(l for l in PS.replay_report(path) if l is not None)
        finally:
            shutil.rmtree(tmp)
        self.assertIn("Chosen: 0.3.", text)
        self.assertIn("**Confirmed on the later seasons:** yes", text)

    def test_pp_by_market(self):
        html = """<main><h2>Value bets by market</h2><table><tbody>
<tr><td>basketball · Points over</td><td>26</td><td>12%</td><td>65%</td><td>-18.3u</td><td>-71%</td></tr>
<tr><td>football · Shots over</td><td>10</td><td>50%</td><td>60%</td><td>-1.0u</td><td>-10%</td></tr>
</tbody></table><h2>Is the model honest?</h2></main>"""
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "p.html").write_text(html, encoding="utf-8")
            got = PS.pp_by_market(tmp / "p.html")
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(got, [{"sport": "basketball", "market": "Points over", "n": 26, "won": 3, "said": 0.65},
                               {"sport": "football", "market": "Shots over", "n": 10, "won": 5, "said": 0.6}])


def js_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    end = source.index("\n}\n", start) + 3
    return source[start:end]


@unittest.skipUnless(NODE, "node not installed")
class Page(unittest.TestCase):
    """report.py's JavaScript, lifted out and run in node, against freshness.py and pp_verdict."""

    def run_js(self, body: str):
        src = (ROOT / "report.py").read_text()
        consts = ['const BREAK_DAYS = 45, STALE_SHARE = 0.5;',
                  'const RUNS_HIGH_STATS = new Set(["Fouls", "Fouled", "Tackles"]);']
        for c in consts:
            self.assertIn(c, src)
        nat = next(l for l in src.splitlines() if l.startswith("const NATIONAL_COMP = "))
        fns = "".join(js_function(src, n) for n in ("dayOf", "breakDateOf", "windowFreshness", "nationalFixture",
                                                     "freshnessOf", "staleNoteHtml", "verdictOf", "RUNS_HIGH",
                                                     "verdictHtml", "allPlayed"))
        iso = next(l for l in src.splitlines() if l.startswith("function isoOfDay("))
        script = Path(tempfile.mkdtemp()) / "t.js"
        script.write_text("\n".join(consts) + "\n" + nat.replace("\\\\", "\\") + "\n" + iso + "\n" + fns + body)
        try:
            out = subprocess.run([NODE, str(script)], capture_output=True, text=True, check=True)
        finally:
            shutil.rmtree(script.parent)
        return json.loads(out.stdout)

    def test_break_dates_agree_with_python(self):
        rng = random.Random(11)
        cases = []
        for _ in range(400):
            start = date(2025, 1, 1) + timedelta(days=rng.randrange(500))
            ds, cur = [], start
            for _k in range(rng.randrange(1, 25)):
                cur += timedelta(days=rng.choice([3, 4, 7, 7, 14, 30, 50, 90]))
                ds.append(cur.isoformat())
            ko = (cur + timedelta(days=rng.choice([2, 5, 40, 46, 120]))).isoformat()
            cases.append([ds, ko])
        got = self.run_js(f"""
const cases = {json.dumps(cases)};
console.log(JSON.stringify(cases.map(([ds, ko]) => {{
  const b = breakDateOf(ds, ko);
  return [b, windowFreshness(ds.slice(-10), b).share];
}})));""")
        for (ds, ko), (b, share) in zip(cases, got):
            pb = F.break_date(ds, ko)
            self.assertEqual(b, pb, (ds, ko))
            ps = F.window(ds[-10:], pb)["share"]
            self.assertAlmostEqual(share, ps, places=9)

    def test_verdict_agrees_with_python_and_labels(self):
        rng = random.Random(7)
        grid = [[round(rng.uniform(0.3, 0.95), 3), round(rng.uniform(1.05, 4), 2),
                 rng.choice(["Fouls", "Shots", "Points", None]), rng.choice([0.5, 1.5]),
                 rng.choice(["football", "basketball", "american-football"]),
                 rng.choice([None, 0.0, 0.2, 0.4, 0.5, 0.8, 1.0])] for _ in range(2000)]
        got = self.run_js(f"""
globalThis.DATA = {{ fixture: {{ staleDays: 0 }} }};
const grid = {json.dumps(grid)};
console.log(JSON.stringify(grid.map(([p, price, stat, line, sport, fresh]) => {{
  globalThis.SPORT = sport;
  return verdictOf({{ p, price, n: 5, stat, line, over: true, fresh }});
}})));""")
        for (p, price, stat, line, sport, fresh), v in zip(grid, got):
            self.assertEqual(v, R.pp_verdict(p, price, 5, False, stat, line, sport, True, fresh),
                             (p, price, stat, line, sport, fresh))
        self.assertIn("stale", got)
        self.assertNotIn("take", got)

    def test_freshness_of_a_player_and_the_label(self):
        out = self.run_js(f"""
const old = {json.dumps(OLD)}, nw = {json.dumps(NEW)};
const rows = old.concat(nw).map(date => ({{ player: "A", date }}));
const res = [];
globalThis.SPORT = "football";
globalThis.DATA = {{ fixture: {{ kickoff: 1788566400, competition: "Premier League" }}, players: [rows, []] }};
res.push(freshnessOf(0, "A", rows.slice(-10)));                       // worked out from his rows
DATA.playerBreaks = [{{ A: null }}, {{}}];
res.push(freshnessOf(0, "A", rows.slice(-10)));                       // the payload says no break
DATA.playerBreaks = [{{ A: "2026-08-16" }}, {{}}];
const f = freshnessOf(0, "A", rows.slice(-10));
res.push(f);
res.push(staleNoteHtml(f));
res.push(verdictHtml({{ p: 0.6, price: 1.7, n: 5, fresh: f.share }}));
DATA.fixture.national = true;
res.push(freshnessOf(0, "A", rows.slice(-10)));
delete DATA.fixture.national;
DATA.fixture.competition = "UEFA Nations League";
res.push(freshnessOf(0, "A", rows.slice(-10)));
console.log(JSON.stringify(res));""")
        self.assertEqual((out[0]["fresh"], out[0]["n"], out[0]["brk"]), (3, 10, "2026-08-16"))
        self.assertEqual(out[1]["share"], 1)
        self.assertEqual(out[2]["share"], 0.3)
        self.assertIn("old record: 3 of 10 games since his break (16 Aug)", out[3])
        self.assertIn("Old record", out[4])
        self.assertIn("vd-stale", out[4])
        self.assertIsNone(out[5])
        self.assertIsNone(out[6])

    def test_rendered_page_parses(self):
        import report
        js = report.JS
        for k, v in (("__PAYLOAD__", "{}"), ("__BETTABLE__", "[]"), ("__ZERO_FILL__", "[]"),
                     ("__PLAYER_SCAN_ALLOW__", "[]"), ("__MIN_MINUTES__", "10"), ("__SPORT__", '"football"'),
                     ("__SITE_CALIB__", "{}")):
            js = js.replace(k, v)
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "page.js").write_text(js)
            done = subprocess.run([NODE, "--check", str(tmp / "page.js")], capture_output=True, text=True)
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
