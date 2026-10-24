"""The parsers behind the team model: teamstyle.load and tactics_fetch.py.

    .venv/bin/python -B -m unittest tests.test_tactics_parsers

Every parser is run on a file in the shape the cache holds and on shapes it
must refuse. The SofaScore and Understat samples are small hand-made copies
of those responses' shapes (the backtest cache holds no tactics files yet);
a shape the parser does not know must raise ShapeError, never parse empty.
"""
import io
import json
import shutil
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tactics_fetch as TF  # noqa: E402
import teamstyle as TS  # noqa: E402


def stats_file(home_shots=12, away_shots=8):
    return {"statistics": [
        {"period": "ALL", "groups": [
            {"groupName": "Match overview", "statisticsItems": [
                {"name": "Ball possession", "home": "55%", "away": "45%", "homeValue": 55, "awayValue": 45},
                {"name": "Total shots", "home": str(home_shots), "away": str(away_shots),
                 "homeValue": home_shots, "awayValue": away_shots},
                {"name": "Expected goals", "homeValue": 1.42, "awayValue": 0.61}]}]},
        {"period": "1ST", "groups": [{"statisticsItems": [{"name": "Total shots", "homeValue": 5, "awayValue": 3}]}]}]}


def lineups_file(fh="4-2-3-1", fa=None):
    return {"confirmed": True, "home": {"players": [], "formation": fh},
            "away": {"players": [], "formation": fa}, "statisticalVersion": 1}


def event(i, ts, home=1, away=2, status="finished"):
    return {"id": i, "startTimestamp": ts, "homeTeam": {"id": home}, "awayTeam": {"id": away},
            "status": {"type": status}, "homeScore": {"current": 2}, "awayScore": {"current": 1},
            "tournament": {"category": {"sport": {"slug": "football"}}}}


class CacheDir(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir)

    def put(self, name, data):
        (self.dir / name).write_text(data if isinstance(data, str) else json.dumps(data))


class TeamstyleStatisticsTest(unittest.TestCase):
    def test_cache_shape(self):
        items = TS.parse_statistics(stats_file())
        self.assertEqual(items["Total shots"], (12.0, 8.0))
        self.assertEqual(items["Ball possession"], (55.0, 45.0))
        self.assertEqual(items["Expected goals"], (1.42, 0.61))

    def test_error_body_and_empty_list_are_no_data(self):
        self.assertIsNone(TS.parse_statistics({"error": {"code": 404, "message": "Not Found"}}))
        self.assertIsNone(TS.parse_statistics({"statistics": []}))

    def test_refuses_unknown_shapes(self):
        bad = [
            [],                                                     # not an object
            {"stats": []},                                          # key renamed
            {"statistics": {"ALL": []}},                            # periods as a dict
            {"statistics": [{"period": "FULL", "groups": []}]},     # period renamed
            {"statistics": [{"period": "ALL", "groups": {}}]},
            {"statistics": [{"period": "ALL", "groups": [{"items": []}]}]},
            {"statistics": [{"period": "ALL", "groups": [{"statisticsItems": [{"title": "x"}]}]}]},
            {"statistics": [{"period": "ALL", "groups": [{"statisticsItems": [{"name": "Fouls", "home": "3"}]}]}]},
        ]
        for d in bad:
            with self.subTest(d=d), self.assertRaises(TS.ShapeError):
                TS.parse_statistics(d, "x")


class TeamstyleLineupsTest(unittest.TestCase):
    def test_cache_shape(self):
        self.assertEqual(TS.parse_lineups(lineups_file()), ["4-2-3-1", ""])

    def test_error_body(self):
        self.assertIsNone(TS.parse_lineups({"error": {"code": 404}}))

    def test_refuses_unknown_shapes(self):
        for d in ([], {"home": {}}, {"home": [], "away": {}}, {"home": {"formation": 4231}, "away": {}}):
            with self.subTest(d=d), self.assertRaises(TS.ShapeError):
                TS.parse_lineups(d)


class TeamstyleLoadTest(CacheDir):
    def write_match(self, i, ts):
        self.put(f"event_{i}_statistics.json", stats_file())
        self.put(f"event_{i}_lineups.json", lineups_file())

    def test_loads_the_cache_shape(self):
        self.put("team_1_events_last_0.json", {"events": [event(10, 100), event(11, 200, 2, 1),
                                                          event(12, 300, status="postponed")],
                                               "hasNextPage": False})
        self.write_match(10, 100)
        self.write_match(11, 200)
        self.put("event_12_statistics.json", {"error": {"code": 404}})
        m = TS.load(self.dir)
        self.assertEqual([x["match"] for x in m], [10, 11])
        self.assertEqual(m[0]["form"], ["4-2-3-1", ""])
        self.assertEqual(m[0]["items"]["Total shots"], (12.0, 8.0))

    def test_skips_a_match_not_fetched_yet_and_an_error_body(self):
        self.put("team_1_events_last_0.json", {"events": [event(10, 100), event(11, 200)]})
        self.write_match(10, 100)
        self.put("event_11_lineups.json", lineups_file())
        self.put("event_11_statistics.json", {"error": {"code": 404}})
        self.assertEqual([x["match"] for x in TS.load(self.dir)], [10])

    def test_raises_on_broken_json(self):
        self.put("team_1_events_last_0.json", {"events": [event(10, 100)]})
        self.write_match(10, 100)
        self.put("event_10_statistics.json", '{"statistics": [')
        with self.assertRaisesRegex(TS.ShapeError, "event_10_statistics.json: not JSON"):
            TS.load(self.dir)

    def test_raises_on_renamed_events_key(self):
        self.put("team_1_events_last_0.json", {"items": [event(10, 100)]})
        with self.assertRaisesRegex(TS.ShapeError, "team_1_events_last_0.json"):
            TS.load(self.dir)

    def test_raises_on_event_without_teams(self):
        e = event(10, 100)
        del e["homeTeam"]
        self.put("team_1_events_last_0.json", {"events": [e]})
        with self.assertRaisesRegex(TS.ShapeError, "homeTeam"):
            TS.load(self.dir)

    def test_raises_when_every_file_is_empty(self):
        self.put("team_1_events_last_0.json", {"events": []})
        with self.assertRaisesRegex(TS.ShapeError, "not one event"):
            TS.load(self.dir)

    def test_empty_cache_is_empty(self):
        self.assertEqual(TS.load(self.dir), [])


AVG = {"home": [{"player": {"id": 1, "name": "A"}, "averageX": 30.5, "averageY": 48.1, "pointsCount": 61}],
       "away": [{"player": {"id": 2, "name": "B"}, "averageX": 55.0, "averageY": 20.0, "pointsCount": 40}],
       "substitutions": []}
SHOTS = {"shotmap": [{"player": {"id": 1}, "isHome": True, "shotType": "goal", "situation": "fast-break",
                      "playerCoordinates": {"x": 10.2, "y": 48.0, "z": 0}, "xg": 0.31, "time": 23},
                     {"player": {"id": 2}, "isHome": False, "shotType": "miss", "situation": "corner",
                      "playerCoordinates": {"x": 8.0, "y": 50.0, "z": 0}, "time": 70}]}
GRAPH = {"graphPoints": [{"minute": 1, "value": 12}, {"minute": 1.5, "value": -40}], "periodTime": 45,
         "periodCount": 2}
INC = {"incidents": [{"incidentType": "period", "text": "FT", "time": 90},
                     {"incidentType": "card", "incidentClass": "yellow", "isHome": True, "time": 33}],
       "home": {}, "away": {}}


class SofaScoreChecksTest(unittest.TestCase):
    def test_good_shapes(self):
        self.assertEqual(TF.check_average_positions(AVG), {"home": 1, "away": 1})
        self.assertEqual(TF.check_shotmap(SHOTS), {"shots": 2, "home": 1})
        self.assertEqual(TF.check_graph(GRAPH), {"points": 2})
        self.assertEqual(TF.check_incidents(INC), {"incidents": 2, "missing": False})

    def test_cards_backfill_placeholder_is_known(self):
        self.assertEqual(TF.check_incidents({"incidents": [], "missing": True}), {"incidents": 0, "missing": True})

    def test_refuses_unknown_shapes(self):
        bad = {
            "average-positions": [{"home": []}, {"home": [{"player": {}}], "away": []},
                                  {"home": [{"player": {}, "averageX": "30", "averageY": 1}], "away": []}, []],
            "shotmap": [{"shots": []}, {"shotmap": [{"isHome": 1, "shotType": "goal", "situation": "x"}]},
                        {"shotmap": [{"isHome": True, "shotType": "goal"}]},
                        {"shotmap": [{"isHome": True, "shotType": "goal", "situation": "x", "xg": "0.3"}]},
                        {"shotmap": ["shot"]}],
            "graph": [{"points": []}, {"graphPoints": [{"minute": 1}]}, {"graphPoints": {}}],
            "incidents": [{"events": []}, {"incidents": [{"type": "goal"}]}, None],
        }
        for ep, ds in bad.items():
            for d in ds:
                with self.subTest(ep=ep, d=d), self.assertRaises(TF.ShapeError):
                    TF.CHECKS[ep](d)


def understat_html(data, raw_title=None):
    s = json.dumps(data)
    if raw_title:
        s = s.replace("TITLE", raw_title)
    lit = "".join(c if c.isalnum() or ord(c) > 127 else "\\x%02X" % ord(c) for c in s)
    return f"<script>\n\tvar datesData = JSON.parse('\\x5B\\x5D');\n\tvar teamsData = JSON.parse('{lit}');\n</script>"


UNDERSTAT = {"89": {"id": "89", "title": "Manchester United", "history": [
    {"h_a": "h", "xG": 1.6, "xGA": 0.9, "npxG": 1.6, "npxGA": 0.9, "ppda": {"att": 250, "def": 25},
     "ppda_allowed": {"att": 300, "def": 20}, "deep": 9, "deep_allowed": 4, "scored": 2, "missed": 1,
     "xpts": 2.0, "result": "w", "date": "2025-08-16 19:00:00", "wins": 1, "draws": 0, "loses": 0,
     "pts": 3, "npxGD": 0.7}]}}


class UnderstatTest(CacheDir):
    def test_teams_data_case(self):
        d = TF.parse_understat_league(understat_html(UNDERSTAT))
        self.assertEqual(d["89"]["history"][0]["ppda"], {"att": 250, "def": 25})
        self.assertEqual(TF.check_understat_teams(d), {"Manchester United": 1})

    def test_accents_survive_escaped_and_raw(self):
        data = {"1": dict(UNDERSTAT["89"], title="Saint-Étienne")}
        self.assertEqual(TF.parse_understat_league(understat_html(data))["1"]["title"], "Saint-Étienne")
        data = {"1": dict(UNDERSTAT["89"], title="TITLE")}
        self.assertEqual(TF.parse_understat_league(understat_html(data, raw_title="Köln"))["1"]["title"], "Köln")

    def test_page_without_teams_data_raises(self):
        # The quiet case before: "no teamsData" printed only with -v, league skipped.
        with self.assertRaisesRegex(TF.ShapeError, "no teamsData"):
            TF.parse_understat_league("<html><script>var datesData = JSON.parse('\\x5B\\x5D');</script></html>")

    def test_unknown_teams_data_raises(self):
        bad = [{}, [], {"89": {"title": "X"}}, {"89": {"title": "X", "history": [{"ppda": 9.5}]}},
               {"89": {"title": "X", "history": [{"ppda": {"att": 1, "def": 1}, "xG": 1, "xGA": 1}]}}]
        for d in bad:
            with self.subTest(d=d), self.assertRaises(TF.ShapeError):
                TF.check_understat_teams(d)
        with self.assertRaisesRegex(TF.ShapeError, "not JSON"):
            TF.parse_understat_league("var teamsData = JSON.parse('\\x7Bnope');")

    def test_fetch_raises_instead_of_skipping(self):
        page = io.BytesIO(b"<html>moved to an XHR call</html>")
        with mock.patch.object(TF, "CACHE", self.dir), \
                mock.patch.object(TF.urllib.request, "urlopen", return_value=page), \
                self.assertRaisesRegex(TF.ShapeError, "understat EPL"):
            TF.fetch_understat(False)
        self.assertEqual(list(self.dir.glob("understat_*")), [])


class FetchAndCacheTest(CacheDir):
    def setUp(self):
        super().setUp()
        self.patches = [mock.patch.object(TF, "CACHE", self.dir),
                        mock.patch.object(TF, "MISSING", self.dir / "tactics_missing.json")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        super().tearDown()

    def test_missing_file(self):
        self.assertEqual(TF.load_missing(), set())
        TF.save_missing({(5, "graph")})
        self.assertEqual(TF.load_missing(), {(5, "graph")})
        self.put("tactics_missing.json", "[[5, ")
        with self.assertRaisesRegex(TF.ShapeError, "not JSON"):
            TF.load_missing()
        self.put("tactics_missing.json", {"5": "graph"})
        with self.assertRaises(TF.ShapeError):
            TF.load_missing()

    def fake_api(self, responses):
        api = types.ModuleType("sofascore_api")

        def get_json(path, max_age_hours=None, verbose=True):
            d = responses.get(path)
            if d is not None:
                (self.dir / (path.replace("/", "_") + ".json")).write_text(json.dumps(d))
            return d
        api.get_json = get_json
        api.last_transport_error = lambda: None
        return api

    def test_fetch_checks_every_response(self):
        api = self.fake_api({"event/7/average-positions": AVG, "event/7/shotmap": SHOTS,
                             "event/7/graph": GRAPH})
        ev = [{"id": 7, "ts": 1, "home": 1, "away": 2}]
        self.put("event_7_statistics.json", stats_file())
        with mock.patch.dict(sys.modules, {"sofascore_api": api}), \
                mock.patch.object(TF, "finished_events", return_value=ev), \
                mock.patch.object(TF, "upcoming_teams", return_value=set()):
            r = TF.fetch_sofascore(10, False)
        self.assertEqual(r, {"fetched": 3, "none": 1, "left": 0})
        self.assertEqual(TF.load_missing(), {(7, "incidents")})

    def test_fetch_stops_on_a_new_shape_and_drops_the_file(self):
        api = self.fake_api({"event/7/average-positions": AVG, "event/7/shotmap": {"shots": []}})
        ev = [{"id": 7, "ts": 1, "home": 1, "away": 2}]
        self.put("event_7_statistics.json", stats_file())
        out = io.StringIO()
        with mock.patch.dict(sys.modules, {"sofascore_api": api}), \
                mock.patch.object(TF, "finished_events", return_value=ev), \
                mock.patch.object(TF, "upcoming_teams", return_value=set()), redirect_stdout(out):
            code = TF.main(["--budget", "10"])
        self.assertEqual(code, 2)
        self.assertIn("SHAPE ERROR", out.getvalue())
        self.assertIn("event 7 shotmap", out.getvalue())
        self.assertFalse((self.dir / "event_7_shotmap.json").exists())
        self.assertTrue((self.dir / "event_7_average-positions.json").exists())

    def test_finished_events_refuses_an_empty_parse(self):
        self.put("team_1_events_last_0.json", {"items": []})
        strength = types.ModuleType("strength")
        strength.load_events = lambda cache: []
        with mock.patch.dict(sys.modules, {"strength": strength}), \
                self.assertRaisesRegex(TF.ShapeError, "no finished match"):
            TF.finished_events()

    def test_check_cache(self):
        for ep, d in (("average-positions", AVG), ("shotmap", SHOTS), ("graph", GRAPH), ("incidents", INC)):
            self.put(f"event_7_{ep}.json", d)
        self.put("event_8_incidents.json", {"incidents": [], "missing": True})
        self.put("understat_EPL_2025.json", UNDERSTAT)
        self.assertEqual(TF.check_cache(), {"average-positions": 1, "shotmap": 1, "graph": 1, "incidents": 2,
                                            "understat": 1})
        self.put("event_9_graph.json", {"graphPoints": "none"})
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(TF.main(["--check"]), 2)
        self.assertIn("event_9_graph.json", out.getvalue())


if __name__ == "__main__":
    unittest.main()
