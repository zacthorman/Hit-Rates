"""news_watch.py: catches NBA injury news, keeps what can move a price tonight.

No network: ESPN answers are built here in the shape its feed returns, and
the NBA report is replaced by a fixtures list. Every file goes to a
temporary folder.
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import news_watch as nw  # noqa: E402

# Sunday 1 Nov 2026, 20:00 UK (GMT): inside the window
T = datetime(2026, 11, 1, 20, 0, tzinfo=nw.UK).timestamp()
TIP = T + 4 * 3600


def espn(*players):
    """ESPN's feed: players as (name, team, status[, date, comment])."""
    teams = {}
    for p in players:
        name, team, status = p[:3]
        date = p[3] if len(p) > 3 else "2026-11-01T19:50Z"
        comment = p[4] if len(p) > 4 else f"{name} update."
        teams.setdefault(team, []).append({
            "id": f"-{abs(hash(name)) % 99999}", "status": status, "date": date,
            "shortComment": comment, "athlete": {"displayName": name},
        })
    return {"injuries": [{"displayName": t, "injuries": v} for t, v in teams.items()]}


def rows(name, minutes, dates):
    return [{"player": name, "date": d, "minutes": minutes} for d in dates]


DATES = [f"2026-10-{d:02d}" for d in range(10, 31, 2)]   # 11 team games


def fixture(home="Orlando Magic", away="Boston Celtics", kickoff=TIP, home_rows=(), away_rows=()):
    entry = {"players": [list(home_rows), list(away_rows)]}
    meta = {"id": 16824789, "home": home, "away": away, "kickoff": kickoff}
    return entry, meta


def magic_squad():
    """A starter, a bench man, a long-term absentee, a returning man."""
    r = []
    r += rows("Paolo Banchero", 34.0, DATES)                 # starter, played every game
    r += rows("Jalen Suggs", 30.0, DATES[:6])                # out since 20 Oct: long absence
    r += rows("Noah Penda", 8.0, DATES)                      # bench, under 15 minutes
    r += rows("Franz Wagner", 33.0, DATES)
    return r


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.saved = {k: getattr(nw, k) for k in ("NEWS", "EVENTS", "SKIPPED", "STATE", "LOG", "RAW", "LOCK", "OFF")}
        nw.NEWS = d / "news"
        nw.EVENTS = nw.NEWS / "events.jsonl"
        nw.SKIPPED = nw.NEWS / "skipped.jsonl"
        nw.STATE = nw.NEWS / "espn_last.json"
        nw.LOG = nw.NEWS / "watch.log"
        nw.RAW = d / "cache" / "espn.json"
        nw.LOCK = d / "cache" / "lock"
        nw.OFF = d / ".news_off"
        self.fixtures = [fixture(home_rows=magic_squad())]
        self.p = mock.patch("builtins.print")
        self.p.start()

    def tearDown(self):
        self.p.stop()
        for k, v in self.saved.items():
            setattr(nw, k, v)
        self.tmp.cleanup()

    def run_tick(self, answer, t=T, **kw):
        if nw.RAW.exists():
            nw.RAW.unlink()          # each tick in a test is a fresh answer
        return nw.tick(t=t, fetch=lambda: answer, fixtures_loader=lambda _t: self.fixtures, **kw)

    def events(self):
        return nw._read_jsonl(nw.EVENTS)

    def skipped(self):
        return nw._read_jsonl(nw.SKIPPED)


class Levels(unittest.TestCase):
    def test_statuses(self):
        self.assertEqual(nw.level("Out"), nw.OUT)
        self.assertEqual(nw.level("Doubtful"), nw.OUT)
        self.assertEqual(nw.level("Suspension"), nw.OUT)
        self.assertEqual(nw.level("Day-To-Day"), nw.DOUBT)
        self.assertEqual(nw.level("Questionable"), nw.DOUBT)
        self.assertEqual(nw.level("Probable"), nw.FIT)
        self.assertEqual(nw.level(nw.NOT_LISTED), nw.FIT)
        self.assertEqual(nw.level("Something new"), nw.DOUBT)

    def test_kinds(self):
        self.assertEqual(nw.kind(nw.FIT, nw.OUT), "out")
        self.assertEqual(nw.kind(nw.DOUBT, nw.OUT), "out")
        self.assertEqual(nw.kind(nw.OUT, nw.FIT), "back")
        self.assertEqual(nw.kind(nw.OUT, nw.DOUBT), "back")
        self.assertEqual(nw.kind(nw.FIT, nw.DOUBT), "downgrade")
        self.assertEqual(nw.kind(nw.DOUBT, nw.FIT), "upgrade")
        self.assertIsNone(nw.kind(nw.OUT, nw.OUT))

    def test_window_crosses_midnight(self):
        at = lambda h, m: datetime(2026, 11, 2, h, m, tzinfo=nw.UK).timestamp()
        self.assertTrue(nw.in_window(at(16, 0)))
        self.assertTrue(nw.in_window(at(23, 59)))
        self.assertTrue(nw.in_window(at(3, 29)))
        self.assertFalse(nw.in_window(at(3, 30)))
        self.assertFalse(nw.in_window(at(12, 0)))

    def test_window_keeps_uk_time_in_summer(self):
        # 16:30 BST is 15:30 UTC: inside the window, read as UK time
        t = datetime(2026, 7, 1, 16, 30, tzinfo=nw.UK).timestamp()
        self.assertTrue(nw.in_window(t))

    def test_nicknames_match_across_sources(self):
        self.assertEqual(nw._nickname("LA Clippers"), nw._nickname("Los Angeles Clippers"))
        self.assertEqual(nw._nickname("Portland Trail Blazers"), "blazers")


class Tick(Base):
    def test_first_run_is_a_baseline_only(self):
        res = self.run_tick(espn(("Paolo Banchero", "Orlando Magic", "Out")))
        self.assertTrue(res["baseline"])
        self.assertEqual(self.events(), [])
        self.assertTrue(nw.STATE.exists())

    def test_starter_ruled_out_is_news(self):
        self.run_tick(espn(("Franz Wagner", "Orlando Magic", "Day-To-Day")))
        self.run_tick(espn(("Franz Wagner", "Orlando Magic", "Out", "2026-11-01T19:52Z")))
        ev = self.events()
        self.assertEqual(len(ev), 1)
        e = ev[0]
        self.assertEqual((e["kind"], e["player"], e["side"]), ("out", "Franz Wagner", "home"))
        self.assertEqual(e["fixture"], "Orlando Magic v Boston Celtics")
        self.assertEqual(e["from_status"], "Day-To-Day")
        self.assertEqual(e["avg_minutes"], 33.0)
        self.assertEqual(e["lag_min"], 8.0)          # stamped 19:52, seen 20:00
        self.assertEqual(e["mins_to_tip"], 240)
        self.assertIsNone(e["paddy"])

    def test_newly_listed_out_is_news(self):
        self.run_tick(espn(("Jalen Suggs", "Orlando Magic", "Out")))
        self.run_tick(espn(("Jalen Suggs", "Orlando Magic", "Out"),
                           ("Paolo Banchero", "Orlando Magic", "Out")))
        self.assertEqual([e["player"] for e in self.events()], ["Paolo Banchero"])
        self.assertEqual(self.events()[0]["from_status"], nw.NOT_LISTED)

    def test_taken_off_the_list_is_back(self):
        self.run_tick(espn(("Paolo Banchero", "Orlando Magic", "Out"),
                           ("Jalen Suggs", "Orlando Magic", "Out")))
        self.run_tick(espn(("Jalen Suggs", "Orlando Magic", "Out")))
        ev = self.events()
        self.assertEqual([(e["player"], e["kind"], e["to_status"]) for e in ev],
                         [("Paolo Banchero", "back", nw.NOT_LISTED)])
        self.assertIsNone(ev[0]["lag_min"])          # no date of his own once removed

    def test_long_absence_is_not_news(self):
        self.run_tick(espn(("Franz Wagner", "Orlando Magic", "Out")))
        self.run_tick(espn(("Franz Wagner", "Orlando Magic", "Out"),
                           ("Jalen Suggs", "Orlando Magic", "Out")))
        self.assertEqual(self.events(), [])
        sk = self.skipped()
        self.assertEqual(len(sk), 1)
        self.assertIn("already priced", sk[0]["reason"])

    def test_long_absentee_coming_back_is_news(self):
        self.run_tick(espn(("Jalen Suggs", "Orlando Magic", "Out")))
        self.run_tick(espn(("Jalen Suggs", "Orlando Magic", "Probable")))
        self.assertEqual([(e["player"], e["kind"]) for e in self.events()], [("Jalen Suggs", "back")])

    def test_bench_player_is_not_news(self):
        self.run_tick(espn(("Franz Wagner", "Orlando Magic", "Out")))
        self.run_tick(espn(("Franz Wagner", "Orlando Magic", "Out"),
                           ("Noah Penda", "Orlando Magic", "Out")))
        self.assertEqual(self.events(), [])
        self.assertIn("under 15", self.skipped()[0]["reason"])

    def test_team_not_playing_is_not_news(self):
        self.run_tick(espn(("Franz Wagner", "Orlando Magic", "Out")))
        self.run_tick(espn(("Franz Wagner", "Orlando Magic", "Out"),
                           ("Jayson Tatum", "Miami Heat", "Out")))
        self.assertEqual(self.events(), [])
        self.assertIn("no game", self.skipped()[0]["reason"])

    def test_game_beyond_the_horizon_does_not_count(self):
        self.fixtures = []          # what load_fixtures returns past HORIZON
        self.run_tick(espn(("Franz Wagner", "Orlando Magic", "Day-To-Day")))
        self.run_tick(espn(("Franz Wagner", "Orlando Magic", "Out")))
        self.assertEqual(self.events(), [])

    def test_matched_by_team_when_not_in_the_squad(self):
        # a man with no rows (just signed): placed by team, then skipped for no record
        self.run_tick(espn(("Franz Wagner", "Orlando Magic", "Out")))
        self.run_tick(espn(("Franz Wagner", "Orlando Magic", "Out"),
                           ("New Signing", "Orlando Magic", "Out")))
        sk = self.skipped()
        self.assertEqual(sk[0]["fixture"], "Orlando Magic v Boston Celtics")
        self.assertIn("no appearances", sk[0]["reason"])

    def test_doubt_moves_are_kept_but_labelled(self):
        self.run_tick(espn(("Franz Wagner", "Orlando Magic", "Out")))
        self.run_tick(espn(("Franz Wagner", "Orlando Magic", "Out"),
                           ("Paolo Banchero", "Orlando Magic", "Day-To-Day")))
        self.assertEqual([e["kind"] for e in self.events()], ["downgrade"])

    def test_no_change_logs_nothing(self):
        a = espn(("Franz Wagner", "Orlando Magic", "Out"))
        self.run_tick(a)
        res = self.run_tick(a)
        self.assertEqual(res["changes"], 0)
        self.assertEqual(self.events(), [])

    def test_same_news_is_never_logged_twice(self):
        self.run_tick(espn(("Franz Wagner", "Orlando Magic", "Day-To-Day")))
        out = espn(("Franz Wagner", "Orlando Magic", "Out", "2026-11-01T19:52Z"))
        self.run_tick(out)
        # the snapshot is lost and the old one comes back: the same change again
        nw.save_state(nw.listing(espn(("Franz Wagner", "Orlando Magic", "Day-To-Day"))), T)
        self.run_tick(out, t=T + 180)
        self.assertEqual(len(self.events()), 1)

    def test_broken_short_answer_is_ignored(self):
        many = [(f"Player {chr(97 + i)}", "Miami Heat", "Out") for i in range(20)]
        self.run_tick(espn(*many))
        res = self.run_tick(espn(*many[:5]))
        self.assertTrue(res["ignored"])
        self.assertEqual(len(nw.load_state()["players"]), 20)   # the snapshot is kept
        self.assertEqual(self.events() + self.skipped(), [])

    def test_fetch_failure_is_not_fatal_and_changes_nothing(self):
        self.run_tick(espn(("Franz Wagner", "Orlando Magic", "Out")))
        before = nw.STATE.read_text()
        nw.RAW.unlink()

        def boom():
            raise OSError("no route")
        res = nw.tick(t=T + 180, fetch=boom, fixtures_loader=lambda _t: self.fixtures)
        self.assertEqual(res["error"], "OSError")
        self.assertEqual(nw.STATE.read_text(), before)
        self.assertIn("ESPN not fetched", nw.LOG.read_text())

    def test_report_failure_holds_the_change_for_next_tick(self):
        self.run_tick(espn(("Franz Wagner", "Orlando Magic", "Day-To-Day")))
        out = espn(("Franz Wagner", "Orlando Magic", "Out"))

        def broken(_t):
            raise ValueError("half-written page")
        nw.RAW.unlink()
        res = nw.tick(t=T, fetch=lambda: out, fixtures_loader=broken)
        self.assertEqual(res["held"], 1)
        self.run_tick(out, t=T + 180)
        self.assertEqual([e["player"] for e in self.events()], ["Franz Wagner"])

    def test_fresh_answer_is_reused_inside_three_minutes(self):
        calls = []

        def fetch():
            calls.append(1)
            return espn(("Franz Wagner", "Orlando Magic", "Out"))
        nw.tick(t=T, fetch=fetch, fixtures_loader=lambda _t: self.fixtures)
        os.utime(nw.RAW, (T, T))
        nw.tick(t=T + 60, fetch=fetch, fixtures_loader=lambda _t: self.fixtures)
        self.assertEqual(len(calls), 1)
        nw.tick(t=T + nw.FRESH + 1, fetch=fetch, fixtures_loader=lambda _t: self.fixtures)
        self.assertEqual(len(calls), 2)

    def test_off_switch_and_window(self):
        nw.OFF.touch()
        self.assertFalse(self.run_tick(espn())["ran"])
        nw.OFF.unlink()
        noon = datetime(2026, 11, 1, 12, 0, tzinfo=nw.UK).timestamp()
        self.assertFalse(self.run_tick(espn(), t=noon)["ran"])
        self.assertTrue(self.run_tick(espn(), t=noon, force=True)["ran"])

    def test_dry_run_writes_nothing(self):
        self.run_tick(espn(("Franz Wagner", "Orlando Magic", "Day-To-Day")))
        before = nw.STATE.read_text()
        res = self.run_tick(espn(("Franz Wagner", "Orlando Magic", "Out")), dry=True)
        self.assertEqual(res["events"], 1)
        self.assertEqual(self.events(), [])
        self.assertEqual(nw.STATE.read_text(), before)

    def test_status_reads_what_was_logged(self):
        self.run_tick(espn(("Franz Wagner", "Orlando Magic", "Day-To-Day")))
        self.run_tick(espn(("Franz Wagner", "Orlando Magic", "Out")))
        nw.status()     # prints; must not raise


class Listing(unittest.TestCase):
    def test_reads_espn_shape(self):
        data = {"injuries": [{"displayName": "Atlanta Hawks", "injuries": [{
            "id": "-60194", "status": "Day-To-Day", "date": "2026-11-01T04:52Z",
            "shortComment": "Landale (hip) won't return to Saturday's game against the Pelicans.",
            "athlete": {"displayName": "Jock Landale"}}]}]}
        got = nw.listing(data)
        self.assertEqual(got["jock landale"]["team"], "Atlanta Hawks")
        self.assertEqual(got["jock landale"]["status"], "Day-To-Day")
        self.assertEqual(nw._parse_espn_date("2026-11-01T04:52Z"),
                         datetime(2026, 11, 1, 4, 52, tzinfo=nw.timezone.utc).timestamp())

    def test_names_ignore_accents_and_suffixes(self):
        self.assertEqual(nw._norm("Nikola Jokić"), "nikola jokic")
        self.assertEqual(nw._norm("Jaren Jackson Jr."), "jaren jackson")

    def test_status_as_object(self):
        data = {"injuries": [{"displayName": "X", "injuries": [{
            "status": {"name": "Out"}, "athlete": {"displayName": "A B"}}]}]}
        self.assertEqual(nw.listing(data)["a b"]["status"], "Out")


if __name__ == "__main__":
    unittest.main()
