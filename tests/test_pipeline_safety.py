"""The publish pipeline refuses to put a broken or empty page live.

    .venv/bin/python -B -m unittest tests.test_pipeline_safety
    .venv/bin/python -B tests/run_all.py            # every test file

Each test feeds one step of update.py's pipeline bad input (an empty or
refused fetch, a body missing its fields, a renamed competition, a stale
cache, a page cut off part way) and checks that the guard for it fires. The
"control" tests feed the same steps good input and check nothing fires, so a
guard that blocks everything cannot pass either. No network, no git, and
publish.sh is never run: every request is answered by a fake session and
every command update.py would launch is answered by a fake runner.

PIPELINE-SAFETY.md maps each failure path to the test here that covers it.
"""
import copy
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import learner  # noqa: E402
import make_index  # noqa: E402
import report  # noqa: E402
import run  # noqa: E402
import site_guard  # noqa: E402
import sofascore_api as api  # noqa: E402
import update  # noqa: E402

NOW = time.time()
FUTURE = int(NOW + 3 * 86400)
PAST = int(NOW - 3 * 86400)
PL = api.tournament_id_for("Premier League")


def quiet(func, *args, **kwargs):
    """Call func with its chatter swallowed; return (result, output)."""
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(out):
        return func(*args, **kwargs), out.getvalue()


class Pages:
    """A real report and index, built once from run.py's synthetic data."""
    good_report: str = ""
    payload: dict = {}

    @classmethod
    def build(cls):
        if cls.good_report:
            return
        tmp = Path(tempfile.mkdtemp())
        with mock.patch.object(run, "OUT_DIR", tmp), \
                mock.patch.object(learner, "OUT", tmp / "learned.json"):
            path, _ = quiet(run.demo)
        cls.good_report = path.read_text(encoding="utf-8")
        cls.payload = json.loads(site_guard.REPORT_PAYLOAD.search(cls.good_report).group(1))
        for entry in cls.payload["fixtures"]:
            entry["fixture"]["tournamentId"] = PL
            entry["fixture"]["kickoff"] = FUTURE
        cls.good_report = with_payload(cls.good_report, cls.payload)
        shutil.rmtree(tmp, ignore_errors=True)


def with_payload(text: str, payload) -> str:
    """The same page with its embedded data swapped for payload."""
    match = site_guard.REPORT_PAYLOAD.search(text)
    body = payload if isinstance(payload, str) else json.dumps(payload)
    return text[:match.start(1)] + body + text[match.end(1):]


def index_page(fixtures: list[dict]) -> str:
    data = json.dumps({"fixtures": fixtures, "competitions": [], "built": "now",
                       "stamp": "1", "picks": None}, separators=(",", ":"))
    return make_index.PAGE.replace("__PAYLOAD__", data).replace("__RESEARCH__", "")


def payload_with(mutate) -> dict:
    data = copy.deepcopy(Pages.payload)
    mutate(data)
    return data


class Tmp(unittest.TestCase):
    def setUp(self):
        Pages.build()
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.reports = self.dir / "reports"
        self.reports.mkdir()
        self.keep = self.dir / ".last_good"
        self.rejected = self.dir / ".rejected"
        for name, value in (("ROOT", self.dir), ("REPORTS", self.reports),
                            ("LAST_GOOD", self.keep), ("REJECTED", self.rejected)):
            patcher = mock.patch.object(site_guard, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, name: str, text: str) -> Path:
        path = self.reports / name
        path.write_text(text, encoding="utf-8")
        return path


# --------------------------------------------------------------- the fetch

class FakeResponse:
    def __init__(self, status: int, body):
        self.status_code = status
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self):
        return json.loads(self.text)


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, url, timeout=30):
        self.calls += 1
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item


class FetchLayer(unittest.TestCase):
    """sofascore_api: a request that comes back with nothing usable is noted."""

    def setUp(self):
        self.cache = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cache, True)
        for target, name, value in ((api, "CACHE_DIR", self.cache),
                                    (api.time, "sleep", lambda s: None),
                                    (api, "_last_transport_error", None),
                                    (api, "_consecutive_blocks", 0)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.mark = api.failure_mark()

    def session(self, *responses):
        fake = FakeSession(*responses)
        patcher = mock.patch.object(api, "_get_session", lambda: fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def test_server_errors_until_the_retries_run_out_are_noted(self):
        self.session(FakeResponse(503, "Service Unavailable"))
        result, _ = quiet(api.get_json, "team/1/events/next/0")
        self.assertIsNone(result)
        self.assertIn("gave up", api.failures_since(self.mark)[0])

    def test_empty_body_that_is_not_json_is_noted(self):
        self.session(FakeResponse(200, ""))
        result, _ = quiet(api.get_json, "team/1/events/next/0")
        self.assertIsNone(result)
        self.assertIn("non-JSON", api.failures_since(self.mark)[0])

    def test_error_body_dressed_as_200_is_noted(self):
        self.session(FakeResponse(200, {"error": {"code": 500}}))
        quiet(api.get_json, "team/1/events/next/0")
        self.assertIn("error body 500", api.failures_since(self.mark)[0])

    def test_a_genuine_404_is_not_a_failure(self):
        # SofaScore's answer for "this team has no next fixture".
        self.session(FakeResponse(404, {"error": {"code": 404}}))
        quiet(api.get_json, "team/1/events/next/0")
        self.session(FakeResponse(200, {"error": {"code": 404}}))
        quiet(api.get_json, "team/2/events/next/0")
        self.assertEqual(api.failures_since(self.mark), [])

    def test_body_missing_the_events_field_is_noted(self):
        self.session(FakeResponse(200, {"matches": [{"id": 1}]}))
        events, _ = quiet(api.team_next_events, 1)
        self.assertEqual(events, [])
        self.assertIn("no 'events' field", api.failures_since(self.mark)[0])

    def test_empty_events_list_is_a_real_answer(self):
        self.session(FakeResponse(200, {"events": []}))
        events, _ = quiet(api.team_next_events, 1)
        self.assertEqual(events, [])
        self.assertEqual(api.failures_since(self.mark), [])

    def test_stale_cached_fixture_list_is_refetched(self):
        # Last week's answer with a fresh mtime, as after unpacking a cache.
        api._cache_file("team/1/events/next/0").write_text(
            json.dumps({"events": [{"id": 1, "startTimestamp": PAST}]}))
        fake = self.session(FakeResponse(200, {"events": [{"id": 2, "startTimestamp": FUTURE}]}))
        events, out = quiet(api.team_next_events, 1)
        self.assertEqual([e["id"] for e in events], [2])
        self.assertEqual(fake.calls, 1)
        self.assertIn("stale", out)

    def test_fresh_cached_fixture_list_is_used_without_a_request(self):
        api._cache_file("team/1/events/next/0").write_text(
            json.dumps({"events": [{"id": 1, "startTimestamp": FUTURE}]}))
        fake = self.session(FakeResponse(500, ""))
        events, _ = quiet(api.team_next_events, 1)
        self.assertEqual([e["id"] for e in events], [1])
        self.assertEqual(fake.calls, 0)

    def test_half_written_cache_file_is_refetched(self):
        api._cache_file("team/1/events/next/0").write_text('{"events": [')
        self.session(FakeResponse(200, {"events": []}))
        self.assertEqual(quiet(api.get_json, "team/1/events/next/0")[0], {"events": []})

    def test_repeated_refusals_raise_blocked(self):
        self.session(FakeResponse(403, "Forbidden"))
        with self.assertRaises(api.Blocked):
            quiet(api.get_json, "team/1/events/next/0")


# --------------------------------------------------------------- run.py

class RunBuild(Tmp):
    """run.py: a failed fetch exits as a failure, never as a quiet week."""

    def setUp(self):
        super().setUp()
        for target, name, value in ((run, "OUT_DIR", self.reports),
                                    (api, "_last_transport_error", None)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def main(self, *argv):
        with mock.patch.object(sys, "argv", ["run.py", *argv, "--no-open"]):
            return quiet(run.main)

    def fetch(self, events=None, failing=False, teams=(1, 2, 3, 4)):
        def next_events(team_id, page=0):
            if failing:
                api.note_failure(f"team/{team_id}/events/next/0", "gave up after 6 attempts")
            return list(events or [])
        for name, value in (("tournament_team_ids", lambda tid, season_id=None: list(teams)),
                            ("team_next_events", next_events)):
            patcher = mock.patch.object(api, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def status(self):
        return json.loads((self.dir / "status.json").read_text())

    def test_leagues_with_every_fixture_list_refused_is_a_failed_fetch(self):
        self.fetch(failing=True)
        with self.assertRaises(SystemExit) as ctx:
            self.main("--leagues", "Premier League",
                      "--status-file", str(self.dir / "status.json"))
        self.assertEqual(ctx.exception.code, site_guard.BAD_FETCH)
        self.assertIn("gave up", self.status()["bad_fetch"]["Premier League"])
        self.assertEqual(list(self.reports.glob("*.html")), [])

    def fake_leagues(self, outcomes):
        """main_for per league: "built" writes a page, "refused" fails the
        fetch, "blocked" trips the circuit breaker."""
        tried = []

        def main_for(sub):
            tried.append(sub.league)
            what = outcomes[sub.league]
            if what == "built":
                self.write(sub.league.lower().replace(" ", "-") + ".html", Pages.good_report)
            elif what == "refused":
                api.note_failure("team/1/events/next/0", "gave up after 6 attempts")
                raise SystemExit("No fixtures found for any of those teams.")
            elif what == "blocked":
                raise api.Blocked("5 refusals in a row")
        patcher = mock.patch.object(run, "main_for", main_for)
        patcher.start()
        self.addCleanup(patcher.stop)
        return tried

    def test_one_league_refused_the_others_still_build(self):
        self.fake_leagues({"Premier League": "built", "Brasileirao": "refused",
                           "La Liga": "built"})
        with self.assertRaises(SystemExit) as ctx:
            self.main("--leagues", "Premier League,Brasileirao,La Liga",
                      "--status-file", str(self.dir / "status.json"))
        self.assertEqual(ctx.exception.code, site_guard.BAD_FETCH)
        status = self.status()
        self.assertEqual(status["built"], ["Premier League", "La Liga"])
        self.assertEqual(list(status["bad_fetch"]), ["Brasileirao"])
        self.assertEqual(sorted(p.name for p in self.reports.glob("*.html")),
                         ["la-liga.html", "premier-league.html"])

    def test_blocked_marks_the_rest_without_asking_again(self):
        tried = self.fake_leagues({"Premier League": "built", "Serie A": "blocked",
                                   "La Liga": "built"})
        with self.assertRaises(SystemExit) as ctx:
            self.main("--leagues", "Premier League,Serie A,La Liga",
                      "--status-file", str(self.dir / "status.json"))
        self.assertEqual(ctx.exception.code, site_guard.BAD_FETCH)
        self.assertEqual(tried, ["Premier League", "Serie A"])
        self.assertEqual(list(self.status()["bad_fetch"]), ["Serie A", "La Liga"])

    def test_league_that_produced_no_data_is_still_fatal(self):
        # Not a fetch failure: exit 1, which update.py treats as a stop.
        def main_for(sub):
            raise SystemExit("\nNo fixture produced any data.")
        with mock.patch.object(run, "main_for", main_for):
            with self.assertRaises(SystemExit) as ctx:
                self.main("--leagues", "Premier League")
        self.assertIn("Failed: Premier League", str(ctx.exception.code))

    def test_leagues_quiet_week_still_passes(self):
        # Control: nothing failed and nothing was expected, so it is quiet.
        self.fetch(failing=False)
        _, out = self.main("--leagues", "Premier League")
        self.assertIn("Nothing on this week: Premier League", out)

    def test_renamed_competition_contradicting_yesterdays_page_fails(self):
        # Every team's next game sits under a new competition id, so nothing
        # matches the old one, while yesterday's page lists games to come.
        self.write("premier-league.html", Pages.good_report)
        moved = [{"id": 9, "startTimestamp": FUTURE,
                  "tournament": {"name": "Premier League", "uniqueTournament": {"id": 99999}},
                  "homeTeam": {"id": 1, "name": "A"}, "awayTeam": {"id": 2, "name": "B"}}]
        self.fetch(events=moved)
        with self.assertRaises(SystemExit) as ctx:
            self.main("--leagues", "Premier League",
                      "--status-file", str(self.dir / "status.json"))
        self.assertEqual(ctx.exception.code, site_guard.BAD_FETCH)
        self.assertIn("renamed", self.status()["bad_fetch"]["Premier League"])
        self.assertEqual(self.reports.joinpath("premier-league.html").read_text(),
                         Pages.good_report, "yesterday's page must be left as it was")

    def test_renamed_competition_in_update_json_fails(self):
        self.fetch()
        with self.assertRaises(SystemExit) as ctx:
            self.main("--leagues", "Premiership Football")
        self.assertIn("Failed: Premiership Football", str(ctx.exception.code))

    def test_single_league_bad_fetch_exits_bad_fetch(self):
        self.fetch(failing=True)
        with self.assertRaises(SystemExit) as ctx:
            self.main("--league", "NBA", "--within-days", "2")
        self.assertEqual(ctx.exception.code, site_guard.BAD_FETCH)

    def test_single_league_quiet_week_is_not_bad_fetch(self):
        self.fetch(failing=False)
        with self.assertRaises(SystemExit) as ctx:
            self.main("--league", "NBA", "--within-days", "2")
        self.assertNotEqual(ctx.exception.code, site_guard.BAD_FETCH)
        self.assertIn("No fixtures found", str(ctx.exception.code))

    def test_single_league_within_days_contradicted_by_page_on_disk(self):
        self.write("premier-league.html", Pages.good_report)
        self.fetch(failing=False)
        with self.assertRaises(SystemExit) as ctx:
            self.main("--league", "Premier League", "--within-days", "5")
        self.assertEqual(ctx.exception.code, site_guard.BAD_FETCH)

    def test_games_beyond_the_horizon_do_not_contradict(self):
        # Control: yesterday's page has games in 3 days, the build looked 1.
        self.write("premier-league.html", Pages.good_report)
        self.fetch(failing=False)
        with self.assertRaises(SystemExit) as ctx:
            self.main("--league", "Premier League", "--within-days", "1")
        self.assertNotEqual(ctx.exception.code, site_guard.BAD_FETCH)

    def test_blocked_exits_bad_fetch(self):
        def refused(tid, season_id=None):
            raise api.Blocked("5 refusals in a row")
        with mock.patch.object(api, "tournament_team_ids", refused):
            with self.assertRaises(SystemExit) as ctx:
                self.main("--league", "NFL")
        self.assertEqual(ctx.exception.code, site_guard.BAD_FETCH)

    def test_unreachable_schedule_exits_bad_fetch(self):
        with mock.patch.object(run, "nations_events", lambda days: []), \
                mock.patch.object(api, "_last_transport_error", "DNSError"):
            with self.assertRaises(SystemExit) as ctx:
                self.main("--nations", "7")
        self.assertEqual(ctx.exception.code, site_guard.BAD_FETCH)

    def test_empty_team_list_exits_bad_fetch(self):
        self.fetch(teams=())
        with self.assertRaises(SystemExit) as ctx:
            self.main("--league", "NFL")
        self.assertEqual(ctx.exception.code, site_guard.BAD_FETCH)


# --------------------------------------------------------------- the pages

class ReportChecks(Tmp):
    """site_guard.report_problems: what makes a report unfit to publish."""

    def problems(self, text, **kw):
        return site_guard.report_problems(self.write("r.html", text), **kw)

    def test_good_report_passes(self):
        self.assertEqual(self.problems(Pages.good_report), [])
        self.assertEqual(self.problems(Pages.good_report, fresh=True), [])

    def test_missing_file(self):
        self.assertIn("missing", site_guard.report_problems(self.reports / "nope.html")[0])

    def test_empty_file(self):
        self.assertIn("empty", self.problems("")[0])

    def test_stub(self):
        self.assertIn("bytes", self.problems("<html></html>")[0])

    def test_cut_off_part_way(self):
        half = Pages.good_report[: len(Pages.good_report) // 2]
        self.assertTrue(self.problems(half))

    def test_cut_off_after_the_payload(self):
        self.assertIn("</html>", self.problems(Pages.good_report[:-200])[0])

    def test_no_payload(self):
        text = Pages.good_report.replace("const ALL = ", "const NOPE = ")
        self.assertIn("no data payload", self.problems(text)[0])

    def test_payload_does_not_parse(self):
        text = with_payload(Pages.good_report, '{"fixtures": [')
        self.assertTrue(self.problems(text))

    def test_zero_fixtures(self):
        text = with_payload(Pages.good_report, {"fixtures": [], "periods": {}})
        self.assertIn("zero fixtures", self.problems(text)[0])

    def test_missing_fields(self):
        for field in site_guard.REQUIRED_FIXTURE_FIELDS:
            data = payload_with(lambda d: d["fixtures"][0]["fixture"].pop(field))
            got = self.problems(with_payload(Pages.good_report, data))
            self.assertTrue(got and field in got[0], (field, got))

    def test_missing_records(self):
        data = payload_with(lambda d: d["fixtures"][0].pop("records"))
        self.assertIn("records", self.problems(with_payload(Pages.good_report, data))[0])

    def test_no_statistics_at_all(self):
        def empty(d):
            for entry in d["fixtures"]:
                entry["records"] = [[], []]
        got = self.problems(with_payload(Pages.good_report, payload_with(empty)))
        self.assertIn("statistics", got[0])

    def test_most_fixtures_one_sided(self):
        def one_sided(d):
            base = d["fixtures"][0]
            d["fixtures"] = []
            for i in range(6):
                entry = copy.deepcopy(base)
                entry["fixture"]["id"] = i + 1
                entry["records"] = [entry["records"][0], []] if i < 4 else entry["records"]
                d["fixtures"].append(entry)
        got = self.problems(with_payload(Pages.good_report, payload_with(one_sided)))
        self.assertIn("missing one team", got[0])

    def test_one_debutant_is_allowed(self):
        # Control: one club with no record in the competition is normal.
        data = payload_with(lambda d: d["fixtures"][0].update(
            records=[d["fixtures"][0]["records"][0], []]))
        self.assertEqual(self.problems(with_payload(Pages.good_report, data)), [])

    def test_fresh_report_from_stale_cache(self):
        def stale(d):
            for entry in d["fixtures"]:
                entry["fixture"]["kickoff"] = PAST
        text = with_payload(Pages.good_report, payload_with(stale))
        self.assertIn("stale cache", self.problems(text, fresh=True)[0])
        # Control: the same page from an earlier run is merely finished, and
        # make_index prunes it as before.
        self.assertEqual(self.problems(text, fresh=False), [])


class IndexChecks(Tmp):
    def fixture(self, report="premier-league.html"):
        return {"id": 1, "home": "A", "away": "B", "kickoff": FUTURE, "report": report}

    def check(self, text):
        path = self.dir / "index.html"
        path.write_text(text, encoding="utf-8")
        return site_guard.index_problems(path, self.reports)

    def test_good_index_passes(self):
        self.write("premier-league.html", Pages.good_report)
        self.assertEqual(self.check(index_page([self.fixture()])), [])

    def test_zero_fixtures(self):
        self.assertIn("zero fixtures", self.check(index_page([]))[0])

    def test_link_to_missing_report(self):
        self.assertIn("not there", self.check(index_page([self.fixture("gone.html")]))[0])

    def test_cut_off(self):
        page = index_page([self.fixture()])
        self.assertTrue(self.check(page[: len(page) // 2]))

    def test_template_placeholder_left_in(self):
        self.assertTrue(self.check(make_index.PAGE))

    def test_missing(self):
        self.assertIn("missing", site_guard.index_problems(self.dir / "x.html", self.reports)[0])


class KeepYesterday(Tmp):
    """A bad page is swapped back to its last good copy, never published."""

    def test_snapshot_keeps_only_good_pages(self):
        self.write("good.html", Pages.good_report)
        self.write("bad.html", Pages.good_report[:-500])
        self.assertEqual(site_guard.snapshot(), 1)
        self.assertTrue((self.keep / "reports" / "good.html").exists())
        self.assertFalse((self.keep / "reports" / "bad.html").exists())

    def test_vet_puts_yesterdays_page_back(self):
        path = self.write("premier-league.html", Pages.good_report)
        site_guard.snapshot()
        path.write_text(with_payload(Pages.good_report, {"fixtures": []}), encoding="utf-8")
        problems = site_guard.vet()
        self.assertEqual(len(problems), 1)
        self.assertIn("yesterday's copy put back", problems[0])
        self.assertEqual(path.read_text(encoding="utf-8"), Pages.good_report)
        self.assertTrue((self.rejected / "premier-league.html").exists())

    def test_vet_without_a_good_copy_moves_the_page_aside(self):
        self.write("good.html", Pages.good_report)
        self.write("new-league.html", "")
        problems = site_guard.vet()
        self.assertIn("left out", problems[0])
        self.assertFalse((self.reports / "new-league.html").exists())

    def test_vet_passes_good_reports(self):
        self.write("premier-league.html", Pages.good_report)
        self.assertEqual(site_guard.vet(since=NOW - 60), [])

    def test_vet_with_no_reports_fails(self):
        self.assertTrue(site_guard.vet())

    def test_vet_only_applies_staleness_to_this_runs_reports(self):
        def stale(d):
            for entry in d["fixtures"]:
                entry["fixture"]["kickoff"] = PAST
        path = self.write("x.html", with_payload(Pages.good_report, payload_with(stale)))
        os.utime(path, (NOW - 86400, NOW - 86400))
        self.assertEqual(site_guard.vet(since=NOW - 60), [])
        os.utime(path, (NOW, NOW))
        self.assertTrue(site_guard.vet(since=NOW - 60))

    def test_gate_on_staged_site(self):
        live = self.write("premier-league.html", Pages.good_report)
        site_guard.snapshot()
        stage = self.dir / "stage"
        (stage / "reports").mkdir(parents=True)
        (stage / "reports" / "premier-league.html").write_text(Pages.good_report[:-300])
        live.write_text(Pages.good_report[:-300])          # rewritten inside publish.sh
        (stage / "index.html").write_text(index_page(
            [{"id": 1, "home": "A", "away": "B", "kickoff": FUTURE,
              "report": "premier-league.html"}]))
        problems = site_guard.gate(stage)
        self.assertIn("premier-league.html", problems[0])
        self.assertEqual(live.read_text(encoding="utf-8"), Pages.good_report)

    def test_gate_passes_a_good_site(self):
        stage = self.dir / "stage"
        (stage / "reports").mkdir(parents=True)
        (stage / "reports" / "premier-league.html").write_text(Pages.good_report)
        (stage / "index.html").write_text(index_page(
            [{"id": 1, "home": "A", "away": "B", "kickoff": FUTURE,
              "report": "premier-league.html"}]))
        (stage / "tonight.html").write_text("<html><body>quiet</body></html>\n")
        self.assertEqual(site_guard.gate(stage), [])

    def test_gate_catches_a_cut_off_small_page(self):
        stage = self.dir / "stage"
        (stage / "reports").mkdir(parents=True)
        (stage / "reports" / "premier-league.html").write_text(Pages.good_report)
        (stage / "index.html").write_text(index_page(
            [{"id": 1, "home": "A", "away": "B", "kickoff": FUTURE,
              "report": "premier-league.html"}]))
        (stage / "tonight.html").write_text("<html><body><table><tr>")
        self.assertIn("tonight.html", site_guard.gate(stage)[0])

    def test_gate_cli_exits_non_zero(self):
        stage = self.dir / "stage"
        stage.mkdir()
        with self.assertRaises(SystemExit) as ctx:
            quiet(site_guard.main, ["gate", str(stage)])
        self.assertEqual(ctx.exception.code, 1)


class AtomicWrites(Tmp):
    def test_failed_write_leaves_the_old_page_whole(self):
        path = self.write("premier-league.html", Pages.good_report)
        real = Path.write_text

        def dies(self_, text, *a, **kw):
            real(self_, text[:100], *a, **kw)
            raise OSError("No space left on device")
        with mock.patch.object(Path, "write_text", dies):
            with self.assertRaises(OSError):
                site_guard.atomic_write(path, "<html>new</html>")
        self.assertEqual(path.read_text(encoding="utf-8"), Pages.good_report)

    def test_write_report_is_atomic(self):
        path = self.write("premier-league.html", Pages.good_report)
        with mock.patch.object(report, "build_html", side_effect=RuntimeError("bug")):
            with self.assertRaises(RuntimeError):
                report.write_report({"fixtures": []}, path)
        self.assertEqual(path.read_text(encoding="utf-8"), Pages.good_report)


class IndexPrune(Tmp):
    """make_index --prune must not delete a report it simply could not read."""

    def test_unreadable_report_is_not_pruned(self):
        self.write("premier-league.html", Pages.good_report)
        self.write("la-liga.html", Pages.good_report[:-300].replace("const ALL = {", "const ALL = {x"))

        def played(d):
            for entry in d["fixtures"]:
                entry["fixture"]["kickoff"] = PAST
        self.write("serie-a.html", with_payload(Pages.good_report, payload_with(played)))
        make_index._PAYLOADS.clear()
        self.addCleanup(make_index._PAYLOADS.clear)
        with mock.patch.object(make_index, "REPORTS", self.reports), \
                mock.patch.object(make_index, "ROOT", self.dir), \
                mock.patch.object(make_index.picker, "main", lambda argv: None), \
                mock.patch.object(make_index.weekend, "picks", lambda *a, **k: None), \
                mock.patch.object(sys, "argv", ["make_index.py", "--prune"]):
            _, out = quiet(make_index.main)
        self.assertTrue((self.reports / "la-liga.html").exists(), out)
        self.assertFalse((self.reports / "serie-a.html").exists(), "prune still works")
        self.assertIn("would not read", out)
        self.assertEqual(site_guard.index_problems(self.dir / "index.html", self.reports), [])


# --------------------------------------------------------------- update.py

class UpdateRun(Tmp):
    """update.py end to end, with every command it launches faked.

    The fake runner stands in for run.py, rerender.py, make_index.py, git and
    publish.sh. Each test checks whether publish.sh was reached.
    """

    def setUp(self):
        super().setUp()
        config = self.dir / "update.json"
        config.write_text(json.dumps({
            "leagues": ["Premier League"], "push": True, "nations_days": 0,
            "champions_league_days": 0, "europa_league_days": 0,
            "nfl": True, "darts": 0, "mlb": False, "nba": False}))
        for name, value in (("ROOT", self.dir), ("CONFIG", config),
                            ("LOG", self.dir / "update.log"),
                            ("LOCK", self.dir / ".update.lock"),
                            ("STATUS", self.dir / ".last_run.json"),
                            ("ensure_flaresolverr", lambda: True),
                            ("notify", lambda t, m: None),
                            ("git_has_changes", lambda: True)):
            patcher = mock.patch.object(update, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.calls: list[str] = []
        self.build = lambda: self.write("premier-league.html", Pages.good_report)
        self.nfl_code = 1                     # "No fixtures found", a quiet week

    def runner(self, command, dry):
        line = " ".join(command)
        self.calls.append(line)
        if "--leagues" in line:
            self.status_file = Path(command[command.index("--status-file") + 1])
            code = self.build()             # a page writer returns a Path
            return code if isinstance(code, int) else 0
        elif "NFL" in line:
            return self.nfl_code
        elif "make_index.py" in line:
            (self.dir / "index.html").write_text(index_page(
                [{"id": 1, "home": "A", "away": "B", "kickoff": FUTURE,
                  "report": p.name} for p in self.reports.glob("*.html")]))
        return 0

    def go(self):
        with mock.patch.object(update, "run_code", self.runner), \
                mock.patch.object(sys, "argv", ["update.py"]):
            try:
                quiet(update.main)
                code = 0
            except SystemExit as exc:
                code = exc.code
        status = json.loads((self.dir / ".last_run.json").read_text())
        published = any("publish.sh" in c for c in self.calls)
        return code, status, published

    def test_good_run_publishes(self):
        code, status, published = self.go()
        self.assertEqual((code, status["ok"], published), (0, True, True))

    def test_empty_page_stops_the_publish_and_keeps_yesterdays(self):
        self.write("premier-league.html", Pages.good_report)
        self.build = lambda: self.write(
            "premier-league.html", with_payload(Pages.good_report, {"fixtures": []}))
        code, status, published = self.go()
        self.assertEqual((code, status["ok"], published), (1, False, False))
        self.assertIn("zero fixtures", status["message"])
        self.assertEqual((self.reports / "premier-league.html").read_text(), Pages.good_report)

    def test_page_cut_off_stops_the_publish(self):
        self.write("premier-league.html", Pages.good_report)
        self.build = lambda: self.write("premier-league.html", Pages.good_report[:5000])
        code, status, published = self.go()
        self.assertEqual((code, published), (1, False))
        self.assertEqual((self.reports / "premier-league.html").read_text(), Pages.good_report)

    def test_stale_cache_build_stops_the_publish(self):
        def stale(d):
            for entry in d["fixtures"]:
                entry["fixture"]["kickoff"] = PAST
        self.build = lambda: self.write(
            "premier-league.html", with_payload(Pages.good_report, payload_with(stale)))
        code, status, published = self.go()
        self.assertEqual((code, published), (1, False))
        self.assertIn("stale cache", status["message"])

    def test_one_sport_refused_keeps_its_pages_and_publishes_the_rest(self):
        nfl = self.write("nfl.html", Pages.good_report)
        os.utime(nfl, (NOW - 86400, NOW - 86400))
        self.nfl_code = site_guard.BAD_FETCH
        code, status, published = self.go()
        self.assertEqual((code, status["ok"], published), (0, True, True))
        self.assertIn("yesterday's pages kept for NFL", status["message"])
        self.assertEqual(nfl.read_text(), Pages.good_report)
        self.assertIn("WARNING: NFL", (self.dir / "update.log").read_text())

    def test_one_league_refused_keeps_its_page_and_publishes_the_rest(self):
        brazil = self.write("brasileirao.html", Pages.good_report)
        os.utime(brazil, (NOW - 86400, NOW - 86400))

        def build():
            self.write("premier-league.html", Pages.good_report)
            self.status_file.write_text(json.dumps({
                "built": ["Premier League"], "empty": [], "failed": [],
                "bad_fetch": {"Brasileirao": "gave up after 6 attempts"}}))
            return site_guard.BAD_FETCH
        self.build = build
        code, status, published = self.go()
        self.assertEqual((code, status["ok"], published), (0, True, True))
        self.assertIn("Brasileirao", status["message"])
        self.assertEqual(brazil.read_text(), Pages.good_report)

    def test_every_feed_refused_at_once_stops_the_publish(self):
        def build():
            self.status_file.write_text(json.dumps({
                "built": [], "empty": [], "failed": [],
                "bad_fetch": {"Premier League": "SofaScore is refusing"}}))
            return site_guard.BAD_FETCH
        self.build = build
        self.nfl_code = site_guard.BAD_FETCH
        code, status, published = self.go()
        self.assertEqual((code, status["ok"], published), (1, False, False))
        self.assertIn("every feed failed", status["message"])

    def test_one_sport_refused_does_not_excuse_an_empty_page(self):
        self.write("premier-league.html", Pages.good_report)
        self.build = lambda: self.write(
            "premier-league.html", with_payload(Pages.good_report, {"fixtures": []}))
        self.nfl_code = site_guard.BAD_FETCH
        code, status, published = self.go()
        self.assertEqual((code, published), (1, False))
        self.assertIn("zero fixtures", status["message"])

    def test_league_build_failing_for_another_reason_still_stops(self):
        self.build = lambda: 1
        code, status, published = self.go()
        self.assertEqual((code, published), (1, False))
        self.assertIn("league build failed", status["message"])

    def test_empty_index_stops_the_publish(self):
        orig = self.runner

        def runner(command, dry):
            code = orig(command, dry)
            if "make_index.py" in " ".join(command):
                (self.dir / "index.html").write_text(index_page([]))
            return code
        self.runner = runner
        code, status, published = self.go()
        self.assertEqual((code, published), (1, False))
        self.assertIn("zero fixtures", status["message"])

    def test_report_failure_is_not_resumed_as_a_publish(self):
        self.build = lambda: self.write("premier-league.html", "")
        self.go()
        self.calls.clear()
        self.build = lambda: self.write("premier-league.html", "")
        self.go()
        self.assertFalse(any("publish.sh" in c for c in self.calls))


class DryRun(unittest.TestCase):
    def test_dry_run_launches_nothing_and_passes(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.object(update, "LOG", tmp / "update.log"), \
                mock.patch.object(update, "STATUS", tmp / ".last_run.json"), \
                mock.patch.object(update.subprocess, "Popen",
                                  side_effect=AssertionError("launched a command")), \
                mock.patch.object(sys, "argv", ["update.py", "--dry-run"]):
            _, out = quiet(update.main)
        self.assertNotIn("FAILED", out)
        self.assertIn("publish.sh", out)
        self.assertFalse((tmp / ".last_run.json").exists())


class PublishScript(unittest.TestCase):
    """publish.sh is never run here. This reads it to check the gate is wired."""

    def test_gate_runs_after_staging_and_before_the_push(self):
        text = (ROOT / "publish.sh").read_text()
        self.assertIn("set -euo pipefail", text)
        gate = text.index('site_guard.py gate "$STAGE"')
        self.assertLess(text.index('cp -R reports "$STAGE"/'), gate)
        self.assertLess(text.index('cp index.html "$STAGE"/'), gate)
        self.assertLess(gate, text.index("git push -f -q origin gh-pages"))
        self.assertRegex(text[gate - 200:gate + 200], r"exit 1")


if __name__ == "__main__":
    unittest.main()
