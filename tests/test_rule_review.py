"""The betting-rule review (RULE-REVIEW.md) and the rule changes it made.

Run from the repo root with the repo's own Python (node must be installed for
the two page checks, which are skipped without it):

    .venv/bin/python -m unittest tests.test_rule_review

Three things are held here:
  * the value claim against Betfair is off everywhere it is printed (the
    index's JavaScript, the "Value on Betfair" list, tonight.py), while the
    figure itself and the bad-price guard that uses it still work;
  * the Paddy Power verdict never says take, and marks a 5%+ edge avoid, in
    the page's own JavaScript, lifted out of report.py and run in node, and
    in the Python mirror rule_review.py scores the record with;
  * rule_review.py's sums: the rules as they stood, the return and closing
    value, the train/test split and the choice made on it, and the Paddy
    Power page reader.
"""

from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import rule_review as R  # noqa: E402
import tonight  # noqa: E402
import weekend  # noqa: E402

NODE = shutil.which("node")


def js_function(source: str, name: str) -> str:
    """One top-level function from a page's script, up to its closing brace
    at the start of a line."""
    start = source.index(f"function {name}(")
    end = source.index("\n}\n", start) + 3
    return source[start:end]


def run_node(script: str):
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def leg(value, **kw):
    """A leg the value list would take on every other count."""
    base = {"team": "Arsenal", "stat": "Goals", "period": "ALL", "line": 1.5, "over": True,
            "hits": 12, "total": 15, "fair": 1.8, "teamIndex": 0, "pExchange": 0.6, "venue": "home",
            "need": 1.8, "source": "model", "evidence": 0.5, "crossLeague": False,
            "fixture": {"id": 1, "home": "Arsenal", "away": "Spurs"},
            "exchange": {"p": 0.55, "back": 1.9, "tight": True, "kind": "exchange"},
            "value": value}
    base.update(kw)
    return base


# ------------------------------------------------------------ the value claim

class ValueClaimOff(unittest.TestCase):
    def test_no_figure_is_claimed(self):
        self.assertIsNone(weekend.VALUE_SHOW)
        for v in (0.006, 0.03, 0.2, 1.0):
            self.assertFalse(weekend.value_claimed(v))
        self.assertFalse(weekend.value_claimed(None))

    def test_value_list_is_empty(self):
        out = weekend.best_value([leg(0.08), leg(0.05, fixture={"id": 2, "home": "A", "away": "B"})])
        self.assertEqual(out["legs"], [])
        self.assertEqual(out["quoted"], 2)
        self.assertIsNone(out["show"])

    def test_list_comes_back_when_the_bar_does(self):
        # The gate is the only thing that changed: switched back on, the same
        # leg makes the list, so the other filters are untouched.
        with mock.patch.object(weekend, "VALUE_SHOW", 0.005):
            out = weekend.best_value([leg(0.08)])
            self.assertEqual(len(out["legs"]), 1)
            self.assertTrue(weekend.value_claimed(0.006))
            self.assertFalse(weekend.value_claimed(0.005))

    def test_bad_price_guard_still_works(self):
        ok = leg(-0.04)
        bad = leg(-0.06)
        self.assertTrue(weekend._headline_ok(ok))
        self.assertFalse(weekend._headline_ok(bad))

    def test_tonight_prints_no_value(self):
        row = tonight.leg_row(leg(0.04))
        self.assertIn("no value", row)
        self.assertNotIn("% value", row)

    @unittest.skipUnless(NODE, "node not installed")
    def test_index_never_claims_value(self):
        src = (ROOT / "make_index.py").read_text()
        self.assertNotIn("0.005", src, "a hard-coded value bar is back in the index script")
        fn = js_function(src, "valueClaimed")
        got = run_node(fn + """
const out = [];
for (const bar of [null, undefined, 0.005]) {
  globalThis.DATA = { picks: bar === undefined ? {} : { valueShow: bar } };
  out.push([0.004, 0.006, 0.2, null].map(v => valueClaimed(v)));
}
globalThis.DATA = {};
out.push([valueClaimed(0.2)]);
console.log(JSON.stringify(out));
""")
        self.assertEqual(got[0], [False, False, False, False])     # off
        self.assertEqual(got[1], [False, False, False, False])     # older data, no bar
        self.assertEqual(got[2], [False, True, True, False])       # bar back at 0.5%
        self.assertEqual(got[3], [False])                           # no picks at all


# ------------------------------------------------------------ Paddy Power

class Verdict(unittest.TestCase):
    CASES = [
        # p, price, heuristic, expected
        (0.60, 2.00, False, "avoid"),      # +20%: was take
        (0.55, 1.85, False, "ok"),         # +1.75%: about fair
        (0.55, 1.75, False, "ok"),         # -3.75%
        (0.55, 1.70, False, "avoid"),      # -6.5%
        (0.40, 3.00, False, "long"),       # under 50%, however big the edge
        (0.60, 2.00, True, "avoid"),       # the card estimate, +20%: was acceptable
        (0.60, 1.70, True, "long"),        # the card estimate, about fair
        (0.50, 2.10, False, "avoid"),      # exactly 50%, +5%
    ]

    def test_python_mirror(self):
        for p, price, heur, want in self.CASES:
            with self.subTest(p=p, price=price, heuristic=heur):
                self.assertEqual(R.pp_verdict(p, price, heuristic=heur), want)

    def test_before_called_these_take(self):
        self.assertEqual(R.pp_verdict_before(0.60, 2.00, 5), "take")
        self.assertEqual(R.pp_verdict_before(0.60, 2.00, 4), "ok")
        self.assertEqual(R.pp_verdict_before(0.60, 2.00, 5, heuristic=True), "ok")

    @unittest.skipUnless(NODE, "node not installed")
    def test_page_matches_mirror_and_never_takes(self):
        src = (ROOT / "report.py").read_text()
        fn = ('const RUNS_HIGH_STATS = new Set(["Fouls", "Fouled", "Tackles"]);\n'
              + js_function(src, "verdictOf") + js_function(src, "RUNS_HIGH"))
        rng = random.Random(1)
        grid = [(round(rng.uniform(0.05, 0.98), 3), round(rng.uniform(1.02, 12), 2), rng.random() < 0.2,
                 rng.randint(0, 10), rng.random() < 0.3) for _ in range(2000)]
        grid += [(p, price, h, 5, False) for p, price, h, _ in self.CASES]
        got = run_node(fn + f"""
globalThis.DATA = {{ fixture: {{ staleDays: 0 }} }};
globalThis.SPORT = "basketball";
const grid = {json.dumps(grid)};
console.log(JSON.stringify(grid.map(([p, price, heuristic, n, unadjusted]) =>
  verdictOf({{ p, price, heuristic, n, unadjusted }}))));
""")
        self.assertNotIn("take", got)
        for (p, price, heur, n, unadj), v in zip(grid, got):
            self.assertEqual(v, R.pp_verdict(p, price, n, heur), (p, price, heur, n, unadj))

    @unittest.skipUnless(NODE, "node not installed")
    def test_team_lines_keep_their_backtested_rule(self):
        # Team lines go through teamlines.verdict's gate (TEAM-LINES.md), not
        # the player-line evidence in RULE-REVIEW.md: take inside a passed
        # market's window, acceptable outside it, never the new avoid.
        fn = js_function((ROOT / "report.py").read_text(), "verdictOf")
        cases = [
            # p, price, tested, threshold, staleDays, expected
            (0.60, 1.77, True, 0.06, 0, "take"),     # +6.2%, in the window
            (0.60, 1.72, True, 0.06, 0, "ok"),       # +3.2%, below the threshold
            (0.60, 2.30, True, 0.06, 0, "ok"),       # +38%, past the 30% cap
            (0.60, 1.90, False, 0.06, 0, "ok"),      # +14%, market not passed
            (0.60, 1.90, True, 0.06, 90, "ok"),      # stale data
            (0.60, 1.50, True, 0.06, 0, "avoid"),    # -10%
            (0.45, 3.00, True, 0.06, 0, "long"),
        ]
        got = run_node(fn + f"""
const cases = {json.dumps(cases)};
globalThis.SPORT = "football";
console.log(JSON.stringify(cases.map(([p, price, tested, threshold, staleDays]) => {{
  globalThis.DATA = {{ fixture: {{ staleDays }} }};
  return verdictOf({{ p, price, team: true, tested, threshold, n: 10 }});
}})));
""")
        self.assertEqual(got, [c[-1] for c in cases])


# ------------------------------------------------------------ the review's sums

def row(**kw):
    base = {"key": "k", "event_id": 1, "kickoff": R.TEST_FROM - 86400, "family": "team|Goals|exchange",
            "kind": "exchange", "stat": "Goals", "player": False, "over": True, "hits": 12, "total": 15,
            "back": 2.0, "tight": True, "w": 0.5, "model": 0.55, "site": 0.55, "market": 0.5,
            "blend": 0.525, "value": None, "disagree": None, "blend_value": None,
            "close": None, "won": None}
    base.update(kw)
    return base


class Rules(unittest.TestCase):
    def test_page_value_bar(self):
        self.assertFalse(R.page_value(row(value=0.005)))
        self.assertTrue(R.page_value(row(value=0.0051)))
        self.assertFalse(R.page_value(row(value=None)))

    def test_value_list_filters(self):
        self.assertTrue(R.value_list(row(value=0.03)))
        self.assertFalse(R.value_list(row(value=0.029)))
        self.assertFalse(R.value_list(row(value=0.05, disagree=0.2)))
        self.assertFalse(R.value_list(row(value=0.05, total=9)))
        self.assertFalse(R.value_list(row(value=0.05, back=6.5)))
        self.assertFalse(R.value_list(row(value=0.05, back=1.2)))
        self.assertFalse(R.value_list(row(value=0.05, stat="Receiving receptions")))

    def test_disagreement_and_bad_price(self):
        self.assertTrue(R.blocked_by_disagree(row(disagree=0.2, blend_value=0.1)))
        self.assertFalse(R.blocked_by_disagree(row(disagree=0.2, blend_value=-0.1)))
        self.assertFalse(R.blocked_by_disagree(row(blend_value=0.1)))
        self.assertTrue(R.bad_price(row(value=-0.051)))
        self.assertFalse(R.bad_price(row(value=-0.05)))
        self.assertTrue(R.kept_by_bad_price(row(value=-0.05)))


class Measure(unittest.TestCase):
    def test_return_and_close(self):
        rows = [row(event_id=1, back=2.0, won=True, close=0.5, value=0.02),
                row(event_id=2, back=2.0, won=False, close=0.6, value=0.04),
                row(event_id=3, back=3.0, won=None, close=None, value=0.03)]
        m = R.measure(rows, claim=lambda r: r["value"])
        self.assertEqual((m["n"], m["settled"], m["won"], m["clv_n"]), (3, 2, 1, 2))
        self.assertAlmostEqual(m["profit"], 0.95 - 1.0)
        self.assertAlmostEqual(m["roi"], -0.025)
        # Worth at close: 0.5 * 0.95 - 0.5 and 0.6 * 0.95 - 0.4.
        self.assertAlmostEqual(m["clv"], ((0.475 - 0.5) + (0.57 - 0.4)) / 2)
        self.assertAlmostEqual(m["said"], 0.03)
        self.assertLessEqual(m["clv_lo"], m["clv"])
        self.assertGreaterEqual(m["clv_hi"], m["clv"])

    def test_empty(self):
        m = R.measure([])
        self.assertEqual(m["n"], 0)
        self.assertIsNone(m["clv"])
        self.assertIsNone(m["roi"])


class HeldOut(unittest.TestCase):
    def _rows(self, close_shift):
        rows = []
        for i in range(60):
            ko = R.TEST_FROM + (i - 30) * 3600
            for j, v in enumerate((0.02, 0.04, 0.08, -0.03)):
                rows.append(row(key=f"{i}|{j}|True", event_id=i, kickoff=ko, value=v,
                                market=0.5, site=0.55, close=0.5 + close_shift,
                                won=(i + j) % 2 == 0))
        return rows

    def test_split_has_no_overlap(self):
        rows = self._rows(0.0)
        train, test = R.split(rows)
        self.assertTrue(all(r["kickoff"] < R.TEST_FROM for r in train))
        self.assertTrue(all(r["kickoff"] >= R.TEST_FROM for r in test))
        self.assertFalse({r["event_id"] for r in train} & {r["event_id"] for r in test})
        self.assertEqual(len(train) + len(test), len(rows))

    def test_nothing_adopted_when_the_close_says_no(self):
        h = R.held_out(self._rows(-0.05))
        self.assertEqual(h["choice"], "Betfair's chance alone (claims nothing)")

    def test_a_bar_is_adopted_when_the_close_agrees(self):
        # Prices that shorten a long way after the flag: positive at the close.
        h = R.held_out(self._rows(0.10))
        self.assertNotEqual(h["choice"], "Betfair's chance alone (claims nothing)")
        chosen = next(x for x in h["rows"] if x["rule"] == h["choice"])
        self.assertGreater(chosen["train"]["clv_lo"], 0)


class PaddyPowerPage(unittest.TestCase):
    PAGE = """<body><p>9496 logged · 3904 settled · 5034 open · 558 void (did not play).
Updated Wed 21 Oct 23:31.</p>
<div class='card'><h3>Value bets</h3><div class='big neg'>-60.7u</div><div class='sub'>177 bets · 57 won · hit 32%
            (said 63%) · ROI <span class='neg'>-34%</span></div></div>
<div class='card'><h3>Every line</h3><div class='big neg'>-1489.4u</div><div class='sub'>3904 bets · 1111 won · hit 28%
            (said 35%) · ROI <span class='neg'>-38%</span></div></div>
<h2>Value bets by market</h2><table><tr><td>football · Shots over</td><td>33</td><td>27%</td><td>58%</td>
<td class='neg'>-13.1u</td><td class='neg'>-40%</td></tr><tr><td>basketball · Points over</td><td>26</td>
<td>12%</td><td>65%</td><td class='neg'>-18.3u</td><td class='neg'>-71%</td></tr></table>
<h2>Is the model honest? Every line</h2><table><tr><td>50-60%</td><td>474</td><td>47%</td></tr>
<tr><td>60-70%</td><td>291</td><td>54%</td></tr></table><h2>Recent value bets</h2></body>"""

    def test_parse(self):
        p = R.parse_pp_page(self.PAGE)
        self.assertEqual(p["updated"], "Wed 21 Oct 23:31")
        self.assertEqual(p["void"], 558)
        self.assertEqual(p["value"], {"profit": -60.7, "n": 177, "won": 57, "hit": 0.32, "said": 0.63,
                                      "roi": -0.34})
        self.assertEqual(p["all"]["n"], 3904)
        self.assertEqual([(m["sport"], m["stat"], m["n"]) for m in p["by_market"]],
                         [("football", "Shots", 33), ("basketball", "Points", 26)])
        self.assertEqual([(b["band"], b["n"]) for b in p["bands"]], [("50-60%", 474), ("60-70%", 291)])

    def test_slice_differences_cumulative_totals(self):
        a = {"n": 23, "won": 11, "profit": -4.3, "said": 0.68}
        b = {"n": 177, "won": 57, "profit": -60.7, "said": 0.63}
        s = R.pp_slice(a, b)
        self.assertEqual((s["n"], s["won"]), (154, 46))
        self.assertAlmostEqual(s["profit"], -56.4)
        self.assertAlmostEqual(s["said"], (0.63 * 177 - 0.68 * 23) / 154)
        self.assertLess(s["hit_lo"], 46 / 154)
        self.assertGreater(s["hit_hi"], 46 / 154)
        self.assertLess(s["roi_lo"], s["roi"])
        self.assertGreater(s["roi_hi"], s["roi"])

    def test_worst_case_reverses_football_losses(self):
        p = R.parse_pp_page(self.PAGE)
        w = R.pp_worst_case(p)
        # 33 football bets, 9 won (27%): 24 losses turned into wins.
        self.assertEqual((w["football"], w["football_won"], w["won"]), (33, 9, 57 + 24))

    def test_wilson(self):
        lo, hi = R.wilson(5, 10)
        self.assertAlmostEqual(lo, 0.2366, places=4)
        self.assertAlmostEqual(hi, 0.7634, places=4)
        self.assertEqual(R.wilson(0, 0), (None, None))


if __name__ == "__main__":
    unittest.main()
