"""gamestate.py against the page: the Line-ups tab's numbers, both ways.

Run from the repo root with the repo's own Python (node must be installed):

    .venv/bin/python -m unittest tests.test_gamestate

The page is the reference. The test lifts the Line-ups tab's own JavaScript
(gsState, gsFactor, gsRows, gsSquads, luPairs, matchupProfile and the helpers
they call) out of the script report.py renders, unchanged, runs it in node on
three saved reports, and requires every row gamestate.py prints to match it to
3 decimal places. If the page's JavaScript changes, this fails until the
Python matches.

The saved reports are in tests/fixtures/gamestate/, trimmed from
reports/premier-league.html on 12 Oct 2026:

    confirmed   Man City v Ipswich. No report held a confirmed XI that day, so
                this is the real predicted XI copied in as the confirmed one
                with one change (Anderson out, Foden in), the way
                lineup_data.attach() stores both.
    predicted   Coventry v Newcastle (predicted XI) and Newcastle v Villa (no
                line-up), so Newcastle's records sit in two fixtures of one
                file, as they do in a midweek round.
    no-lineup   Spurs v Coventry, regular starters only.

GAMESTATE_LIVE=1 also runs every football fixture in reports/.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gamestate  # noqa: E402
import report  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "gamestate"
DRIVER = ROOT / "tests" / "gamestate_driver.js"

# Everything the Line-ups tab's player lines read, by the name it has in the
# page. Each is a top-level declaration in report.py's script.
PAGE_NAMES = [
    "POSITION_NAME", "FOULS_ON", "FOULED_BY", "MATCHUP_PAIRING",
    "MATCHUP_MIN_MATCHES", "MATCHUP_INDEX", "MATCHUP_CACHE", "matchupIndex",
    "matchupProfile", "MIN_MINUTES", "ZERO_FILL", "reportsMinutes",
    "escapeHtml", "luRecords", "luRate", "luShape", "luOpponents",
    "luSurname", "luVs", "luPairs", "GS_MARKETS", "GS_TEAM", "GS_MIN_MODEL",
    "GS_MIN_RECORD", "GS_CACHE", "gsAvg", "gsVal", "gsState", "gsFactor",
    "gsPoisAtLeast", "gsSquads", "gsRows", "gsCardHtml",
]

PLACES = 3


def page_script(payload: dict) -> str:
    """The <script> report.py renders for this payload, exactly as served."""
    html = report.build_html(payload)
    return html[html.rindex("<script>") + len("<script>"):html.rindex("</script>")]


def declaration(script: str, name: str) -> str:
    """One top-level declaration, by name, as the page has it.

    Top-level code in the page starts at column 0 and everything inside it is
    indented, so a declaration runs from its first line to the line before the
    next thing at column 0, keeping a closing brace or bracket there."""
    lines = script.split("\n")
    start = re.compile(rf"^(?:function {name}\(|const {name}\b|let {name}\b)")
    hits = [i for i, ln in enumerate(lines) if start.match(ln)]
    if len(hits) != 1:
        raise AssertionError(f"{name}: {len(hits)} declarations in the page")
    i = hits[0]
    out = [lines[i]]
    for ln in lines[i + 1:]:
        if ln and not ln[0].isspace() and ln[0] not in "}])":
            break
        out.append(ln)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def run_page(payload: dict, tmp: Path) -> list:
    """The page's own answer for every football fixture in the payload."""
    script = page_script(payload)
    data = tmp / "payload.json"
    data.write_text(json.dumps(payload), encoding="utf-8")
    prog = tmp / "page.js"
    prog.write_text(
        'const ALL = JSON.parse(require("fs").readFileSync(process.argv[2], "utf8"));\n'
        "let DATA = null;\n\n"
        + "\n\n".join(declaration(script, n) for n in PAGE_NAMES)
        + "\n\n" + DRIVER.read_text(encoding="utf-8"),
        encoding="utf-8")
    done = subprocess.run(["node", str(prog), str(data)], capture_output=True,
                          text=True, timeout=600)
    if done.returncode:
        raise AssertionError(f"node failed:\n{done.stderr[-3000:]}")
    return json.loads(done.stdout)


def compare(page, mine, path="") -> list[str]:
    """Every difference between the page's value and gamestate.py's.

    Floats to 3 decimal places; everything else exactly. Only the keys the
    page produced are compared, and gamestate.py must have every one."""
    if isinstance(page, dict):
        if not isinstance(mine, dict):
            return [f"{path}: page has an object, gamestate.py has {mine!r}"]
        diffs = []
        for k, v in page.items():
            if k not in mine:
                diffs.append(f"{path}.{k}: missing from gamestate.py")
            else:
                diffs += compare(v, mine[k], f"{path}.{k}")
        return diffs
    if isinstance(page, list):
        if not isinstance(mine, list) or len(page) != len(mine):
            n = len(mine) if isinstance(mine, list) else mine
            return [f"{path}: page has {len(page)} rows, gamestate.py {n}"]
        diffs = []
        for i, (a, b) in enumerate(zip(page, mine)):
            diffs += compare(a, b, f"{path}[{i}]")
        return diffs
    if isinstance(page, bool) or page is None or isinstance(page, str):
        return [] if page == mine else [f"{path}: page {page!r}, gamestate.py {mine!r}"]
    if isinstance(page, (int, float)):
        if isinstance(mine, bool) or not isinstance(mine, (int, float)):
            return [f"{path}: page {page!r}, gamestate.py {mine!r}"]
        if math.isclose(page, mine, rel_tol=0, abs_tol=0.5 * 10 ** -PLACES):
            return []
        return [f"{path}: page {page!r}, gamestate.py {mine!r}"]
    return [f"{path}: cannot compare {page!r}"]


def load(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class PageParity(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def check(self, payload: dict, label: str) -> list:
        page = run_page(payload, self.tmp)
        mine = [gamestate.fixture_lines(payload, i)
                for i, fx in enumerate(payload["fixtures"])
                if (fx["fixture"].get("sport") or "football") == "football"]
        self.assertEqual([p["event"] for p in page], [m["event"] for m in mine], label)
        for p, m in zip(page, mine):
            diffs = compare(p, m, f"{label}:{p['event']}")
            self.assertFalse(diffs, "\n".join(diffs[:40]))
        return mine

    def rows(self, fx) -> int:
        return sum(len(v["lines"]) + len(v["works_against"]) for v in fx["markets"].values())

    def test_confirmed_xi(self):
        mine = self.check(load(FIXTURES / "confirmed.json.gz"), "confirmed")
        self.assertEqual(mine[0]["xi"], "confirmed")
        self.assertIn("Phil Foden", mine[0]["squads"][0])
        self.assertTrue(mine[0]["foul_pairs"])
        self.assertTrue(self.rows(mine[0]))

    def test_predicted_xi(self):
        mine = self.check(load(FIXTURES / "predicted.json.gz"), "predicted")
        by = {m["home"]: m for m in mine}
        self.assertEqual(by["Coventry City"]["xi"], "predicted")
        self.assertEqual(by["Newcastle United"]["xi"], "regular starters")
        self.assertIsNotNone(by["Coventry City"]["foul_pairs"])
        self.assertTrue(self.rows(by["Coventry City"]))
        # The matchup cell is filled somewhere, or the test proves nothing.
        self.assertTrue(any(r["matchup"] for m in mine for v in m["markets"].values()
                            for r in v["lines"]))

    def test_no_lineup(self):
        mine = self.check(load(FIXTURES / "no-lineup.json.gz"), "no-lineup")
        self.assertEqual(mine[0]["xi"], "regular starters")
        self.assertIsNone(mine[0]["foul_pairs"])
        self.assertTrue(self.rows(mine[0]))

    @unittest.skipUnless(os.environ.get("GAMESTATE_LIVE"), "GAMESTATE_LIVE not set")
    def test_live_reports(self):
        for path in sorted((ROOT / "reports").glob("*.html")):
            payload = gamestate.payload_of(path)
            if not payload or not any((fx["fixture"].get("sport") or "football") == "football"
                                      for fx in payload["fixtures"]):
                continue
            with self.subTest(report=path.name):
                self.check(payload, path.name)


class ReadOnly(unittest.TestCase):
    """gamestate.py reads reports and prints. Nothing else."""

    def test_no_writes_or_fetches(self):
        src = (ROOT / "gamestate.py").read_text(encoding="utf-8")
        for banned in ("write_text", "write_bytes", "open(", "sofascore_api",
                       "requests", "urllib", "curl_cffi", "bettrack", "challenge",
                       "betfair", "subprocess"):
            self.assertNotIn(banned, src, banned)


if __name__ == "__main__":
    unittest.main()
