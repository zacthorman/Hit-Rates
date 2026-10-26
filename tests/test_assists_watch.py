"""assists_watch.py, assists 1+ as a long shot, and the thin-market watch in rule_review.py.

    python -B -m unittest tests.test_assists_watch

Synthetic rows and pplog files only, written to temporary folders. The page
check runs report.py's verdictOf in node and is skipped without it.
"""
import gzip
import json
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import assists_watch as W  # noqa: E402
import rule_review as R  # noqa: E402

NODE = shutil.which("node")
T0 = 1_780_000_000            # June 2026, before W.CONFIRM_FROM


def js_function(source: str, name: str) -> str:
    """One top-level function from the page's script (tests/test_rule_review.py's helper)."""
    start = source.index(f"function {name}(")
    end = source.index("\n}\n", start) + 3
    return source[start:end]


class AssistsAreLongShots(unittest.TestCase):

    def test_mirror(self):
        self.assertTrue(R.runs_high("Assists", 0.5))
        self.assertFalse(R.runs_high("Assists", 0.5, sport="basketball"))   # NBA assists are not this line
        self.assertFalse(R.runs_high("Assists", 0.5, over=False))
        self.assertFalse(R.runs_high("Shots", 0.5))
        self.assertTrue(R.runs_high("Fouls", 1.5))                          # the old lines unchanged
        self.assertFalse(R.runs_high("Fouls", 0.5))

    def test_verdict(self):
        self.assertEqual(R.pp_verdict(0.56, 1.80, stat="Assists", line=0.5), "long")
        self.assertEqual(R.pp_verdict(0.56, 1.80, stat="Assists", line=0.5, sport="basketball"), "ok")
        self.assertEqual(R.pp_verdict(0.56, 1.60, stat="Assists", line=0.5), "avoid")   # 10% short stays avoid
        self.assertEqual(R.pp_verdict(0.30, 3.40, stat="Assists", line=0.5), "long")

    @unittest.skipUnless(NODE, "node not installed")
    def test_page_agrees_with_mirror(self):
        src = (ROOT / "report.py").read_text()
        consts = 'const RUNS_HIGH_STATS = new Set(["Fouls", "Fouled", "Tackles"]);\n'
        self.assertIn(consts.strip(), src)
        fns = js_function(src, "verdictOf") + js_function(src, "RUNS_HIGH")
        rng = random.Random(11)
        grid = [[round(rng.uniform(0.3, 0.95), 3), round(rng.uniform(1.05, 4), 2),
                 rng.choice(["Assists", "Fouls", "Tackles", "Shots", None]), rng.choice([0.5, 1.5]),
                 rng.choice(["football", "basketball"]), rng.random() < 0.85] for _ in range(3000)]
        d = Path(tempfile.mkdtemp())
        try:
            (d / "v.js").write_text(consts + fns + f"""
globalThis.DATA = {{ fixture: {{ staleDays: 0 }} }};
const grid = {json.dumps(grid)};
console.log(JSON.stringify(grid.map(([p, price, stat, line, sport, over]) => {{
  globalThis.SPORT = sport;
  return verdictOf({{ p, price, n: 5, stat, line, over }});
}})));
""")
            got = json.loads(subprocess.run([NODE, str(d / "v.js")], capture_output=True, text=True,
                                            check=True).stdout)
        finally:
            shutil.rmtree(d)
        for (p, price, stat, line, sport, over), v in zip(grid, got):
            self.assertEqual(v, R.pp_verdict(p, price, 5, stat=stat, line=line, sport=sport, over=over),
                             (p, price, stat, line, sport, over))


def row(i, p, won, ts=T0, stat="Assists", line=0.5, started=True, pos="M", tid=17):
    return {"event_id": i, "ts": ts, "tid": tid, "stat": stat, "line": line, "p": p, "won": won,
            "started": started, "pos": pos, "k10": 1, "n10": 10}


class Replay(unittest.TestCase):

    def rows(self, said, landed, n=400, later=False):
        ts = W.CONFIRM_FROM + 86400 if later else T0
        return [row(i + (10_000 if later else 0), said, i < landed * n, ts) for i in range(n)]

    def test_block_and_interval(self):
        b = W.block(self.rows(0.55, 0.25))
        self.assertAlmostEqual(b["said"], 0.55)
        self.assertAlmostEqual(b["landed"], 0.25)
        self.assertLess(b["hi"], 0)
        self.assertTrue(b["lo"] <= b["gap"] <= b["hi"])

    def test_rule_needs_both_periods(self):
        both = self.rows(0.55, 0.2) + self.rows(0.55, 0.2, later=True)
        self.assertTrue(W.rule(both)["holds"])
        late_fine = self.rows(0.55, 0.2) + self.rows(0.55, 0.55, later=True)
        self.assertFalse(W.rule(late_fine)["holds"])

    def test_rule_reads_starters_at_50_only(self):
        low = [dict(r, p=0.3) for r in self.rows(0.3, 0.05)] + \
              [dict(r, p=0.3) for r in self.rows(0.3, 0.05, later=True)]
        self.assertFalse(W.rule(low)["holds"])           # under 50%: already long shots
        subs = [dict(r, started=False) for r in self.rows(0.55, 0.2) + self.rows(0.55, 0.2, later=True)]
        self.assertFalse(W.rule(subs)["holds"])

    def test_load_keeps_report_competitions_and_priced_lines(self):
        rows = [row(1, 0.2, True), row(2, 0.0, False), row(3, 0.2, True, tid=999),
                row(4, 0.2, True, stat="Tackles", line=1.5)]
        d = Path(tempfile.mkdtemp())
        try:
            with gzip.open(d / "r.json.gz", "wt", encoding="utf-8") as fh:
                json.dump(rows, fh)
            got = W.load(d / "r.json.gz")
        finally:
            shutil.rmtree(d)
        self.assertEqual([r["event_id"] for r in got], [1])

    def test_platt_recovers_a_squeeze(self):
        """Chances pushed towards 50% (a slope of 0.4 on the log-odds) come
        back near where they started."""
        rnd = random.Random(3)
        rows = []
        for i in range(6000):
            true = rnd.uniform(0.02, 0.2)
            z = W._logit(true)
            said = 1 / (1 + __import__("math").exp(-(0.45 * z + 0.4)))
            rows.append({"p": said, "won": rnd.random() < true})
        a, b = W.platt(rows)
        self.assertAlmostEqual(b, 1 / 0.45, delta=0.5)


def pp(i, stat, line, chance, won, sport="football", kickoff=1_790_000_000, player="A"):
    return {"event_id": i, "kickoff": kickoff, "sport": sport, "player": player, "stat": stat, "line": line,
            "over": True, "result": "win" if won else "lose", "first": {"chance": chance, "price": 2.0}}


class Watch(unittest.TestCase):

    def test_groups_wait_until_fifty(self):
        rows = [pp(i, "Assists", 0.5, 0.55, i % 5 == 0) for i in range(49)]
        g = R.watch_groups(rows)
        self.assertEqual(g[0]["call"], "waiting (49 of 50)")
        self.assertIsNone(g[0]["lo"])

    def test_running_short_long_and_in_line(self):
        rows = ([pp(i, "Assists", 0.5, 0.55, i % 5 == 0) for i in range(120)]
                + [pp(1000 + i, "Shots", 0.5, 0.55, i % 20 != 0) for i in range(120)]
                + [pp(2000 + i, "Points", 14.5, 0.5, i % 2 == 0, sport="basketball") for i in range(120)])
        calls = {x["group"]: x["call"] for x in R.watch_groups(rows)}
        self.assertEqual(calls["football · Assists 1+"], "running short")
        self.assertEqual(calls["football · Shots 1+"], "running long")
        self.assertEqual(calls["basketball · Points 15+"], "in line")

    def test_team_lines_and_unsettled_left_out(self):
        rows = [pp(i, "Corners", 9.5, 0.5, True, player=None) for i in range(60)]
        rows += [dict(pp(100 + i, "Shots", 0.5, 0.5, True), result=None) for i in range(60)]
        self.assertEqual(R.watch_groups(rows), [])
        self.assertIn("No settled", R.watch_text(rows))

    def test_command_reads_pplog_folder(self):
        import contextlib
        import io
        d = Path(tempfile.mkdtemp())
        try:
            (d / "2026-10.jsonl").write_text("\n".join(json.dumps(pp(i, "Assists", 0.5, 0.55, i % 5 == 0))
                                                       for i in range(60)))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                R.main(["watch", "--pplog", str(d)])
        finally:
            shutil.rmtree(d)
        self.assertIn("running short", buf.getvalue())
        self.assertIn("football · Assists 1+", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
