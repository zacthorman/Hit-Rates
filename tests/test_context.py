"""context.py: the reel-style case for a fixture.

    .venv/bin/python -B -m unittest tests.test_context

Synthetic entries only, except the last test, which reads the built
Champions League report if there is one and is skipped otherwise.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import context  # noqa: E402


def rec(i, date, gf, ga, venue="home", tid=7, shots_against=10.0, xg=1.0, xga=1.0, opp="X"):
    return {"id": i, "date": date, "competition": "UEFA Champions League", "tournament_id": tid,
            "opponent": opp, "opponent_id": 100 + i, "venue": venue, "goals_for": gf,
            "goals_against": ga, "result": "W" if gf > ga else "L" if gf < ga else "D",
            "stats": {"ALL": {"Expected goals": xg}},
            "against": {"ALL": {"Expected goals": xga, "Total shots": shots_against}}}


def entry(home_recs, away_recs, kickoff=1792609200):
    return {"fixture": {"kickoff": kickoff, "tournamentId": 7, "competition": "UEFA Champions League"},
            "teams": [{"name": "Napoli", "id": 1, "side": "home"},
                      {"name": "Bodo", "id": 2, "side": "away"}],
            "records": [home_recs, away_recs], "players": [[], []], "injuries": {}}


class Counts(unittest.TestCase):
    def test_counts_and_form(self):
        rs = [rec(i, f"2026-09-{10 + i:02d}", gf, ga) for i, (gf, ga) in
              enumerate([(1, 0), (2, 2), (0, 1), (3, 1), (0, 0)])]
        c = context.counts(rs)
        self.assertEqual((c["n"], c["won"], c["lost"], c["btts"], c["clean"], c["failed"]),
                         (5, 2, 1, 2, 2, 2))
        f = context.form(rs)
        self.assertEqual([x["res"] for x in f], ["W", "D", "L", "W", "D"])

    def test_records_stop_at_kickoff(self):
        rs = [rec(1, "2026-10-01", 1, 0), rec(2, "2026-10-30", 5, 0)]
        e = entry(rs, [])
        self.assertEqual(len(context.records(e, 0, before=1792609200)), 1)   # 21 Oct 2026


class OppAllows(unittest.TestCase):
    def test_reads_opponent_away_games_in_this_competition(self):
        away = [rec(i, f"2026-0{1 + i}-01", 0, 2, venue="away", shots_against=25.0) for i in range(6)]
        away += [rec(20, "2026-09-01", 0, 0, venue="home", shots_against=5.0)]   # home: ignored
        e = entry([], away)
        leg = {"team": "Napoli", "stat": "Total shots", "period": "ALL", "line": 14.5, "over": True}
        a = context.opp_allows(leg, e)
        self.assertEqual((a["n"], a["hits"], a["scope"]), (6, 6, "in this competition"))
        self.assertAlmostEqual(a["avg"], 25.0)
        self.assertIn("Bodo allow 25.0 total shots a game away", a["text"])

    def test_player_and_match_legs_have_none(self):
        e = entry([], [rec(i, f"2026-0{1 + i}-01", 0, 2, venue="away") for i in range(6)])
        self.assertIsNone(context.opp_allows({"team": "Napoli", "player": "Kvara", "stat": "Shots"}, e))
        self.assertIsNone(context.opp_allows({"team": "Napoli", "stat": "Match goals"}, e))

    def test_too_few_games_is_none(self):
        e = entry([], [rec(1, "2026-01-01", 0, 2, venue="away")])
        leg = {"team": "Napoli", "stat": "Total shots", "period": "ALL", "line": 14.5, "over": True}
        self.assertIsNone(context.opp_allows(leg, e))


class Score(unittest.TestCase):
    def test_split_hits_the_edge(self):
        lh, la = context._split_to(3.0, 0.3)
        self.assertAlmostEqual(lh + la, 3.0, places=6)
        self.assertGreater(lh, la)

    def test_call_is_inside_the_likeliest_result(self):
        e = {"projection": {"ALL": {"Goals": [2.4, 0.6]}}}
        sc = context.score(e, [], [])
        self.assertGreater(sc["ph"], sc["pa"])
        self.assertGreater(sc["home"], sc["away"])


class ScoreModel(unittest.TestCase):
    """context.score() reads the fitted model first, the old route after.

    A tiny league is fitted and put in place of the cache-wide model, so
    these never depend on what is in cache/."""

    def setUp(self):
        import scoremodels
        ms, ts = [], 1_700_000_000
        for _ in range(6):
            for h, a, hg, ag in ((1, 2, 3, 0), (2, 1, 0, 2), (1, 3, 2, 1), (3, 1, 0, 1),
                                 (2, 3, 1, 1), (3, 2, 1, 1)):
                ms.append({"home": h, "away": a, "hg": hg, "ag": ag, "ts": ts})
                ts += 86400
        self.saved = dict(context._SCORE_MODEL)
        context._SCORE_MODEL["m"] = scoremodels.TeamGoals("poisson", 1460, 2.0).fit(ms, ts)

    def tearDown(self):
        context._SCORE_MODEL.clear()
        context._SCORE_MODEL.update(self.saved)

    def test_model_route_when_both_sides_are_known(self):
        sc = context.score(entry([], []), [], [])     # Napoli id 1 at home to Bodo id 2
        self.assertEqual(sc["source"], "team attack and defence ratings (backtested)")
        self.assertAlmostEqual(sc["ph"] + sc["pd"] + sc["pa"], 1.0, places=6)
        self.assertGreater(sc["ph"], sc["pa"])
        self.assertGreater(sc["home"], sc["away"])
        self.assertGreater(sc["lh"], sc["la"])

    def test_unknown_side_falls_back_to_the_projection(self):
        e = entry([], [])
        e["teams"][1]["id"] = 999
        e["projection"] = {"ALL": {"Goals": [0.5, 2.5]}}
        sc = context.score(e, [], [])
        self.assertEqual(sc["source"], "goals projection")
        self.assertGreater(sc["away"], sc["home"])

    def test_no_model_falls_back(self):
        context._SCORE_MODEL["m"] = None
        e = entry([], [])
        e["projection"] = {"ALL": {"Goals": [2.4, 0.6]}}
        self.assertEqual(context.score(e, [], [])["source"], "goals projection")


class Case(unittest.TestCase):
    def test_pass_when_nothing_qualified(self):
        self.assertTrue(context.case(None, {"facts": []}, None).startswith("Nothing for us here"))

    def test_cards_bet_ignores_goals_facts(self):
        b = {"facts": ["Napoli have conceded in 9 of their last 10 (1 clean sheet).",
                       "Referee A averages 5.1 yellows a game over 300 games."], "story": []}
        text = context.case({"team": "Napoli", "stat": "Yellow cards"}, b, None)
        self.assertIn("Referee", text)
        self.assertNotIn("conceded", text)


class Live(unittest.TestCase):
    def test_brief_on_built_report(self):
        path = Path(__file__).resolve().parent.parent / "reports" / "uefa-champions-league.html"
        if not path.exists():
            self.skipTest("no built Champions League report")
        import make_index
        es = make_index.read_entries(path)
        if not es:
            self.skipTest("report has no fixtures")
        b = context.brief(*es[0])
        self.assertEqual(len(b["home"]["form"]), 5)
        self.assertTrue(b["story"])


class GameState(unittest.TestCase):
    def test_nb_tail_is_monotone_and_poisson_at_zero_alpha(self):
        a = [context._nb_at_least(k, 2.0, 0.1) for k in (1, 2, 3, 4)]
        self.assertTrue(all(x > y for x, y in zip(a, a[1:])))
        self.assertAlmostEqual(context._nb_at_least(1, 2.0, 0.0), 1 - 2.718281828 ** -2, places=6)

    def test_ball_factor_direction(self):
        self.assertGreater(context._ball(60, 50, +1), 1)
        self.assertLess(context._ball(60, 50, -1), 1)
        self.assertEqual(context._ball(None, 50, +1), 1.0)

    def test_model_switches_off_unhelpful_game_state(self):
        context._FIT.clear()
        context._FIT.update({"team": {"Fouls": {"coef": [0.1, 0.5, 0.4, 0.0, 0.5], "alpha": 0.0, "use": False}}})
        m = context._model("team", "Fouls", 11.0, 11.0, 1.3, home=True)
        self.assertAlmostEqual(m["mu"], m["plain"])
        context._FIT.clear()

    def test_half_time_legs_are_not_reached(self):
        self.assertIsNone(context.gs_adjust({"period": "1ST", "team": "Napoli"}, {}, {"fitted": True}))


class Streaks(unittest.TestCase):
    def test_current_run_only(self):
        rs = [rec(i, f"2026-0{1 + i // 28}-{1 + i % 28:02d}", 1, 1) for i in range(9)]
        rs.append(rec(20, "2026-09-01", 3, 2))           # breaks under 2.5 but not under 3.5... 5 goals breaks both
        out = [t for _, t in context.streaks("Napoli", rs)]
        self.assertFalse(any("under 3.5" in t for t in out))
        rs2 = [rec(i, f"2026-0{1 + i // 28}-{1 + i % 28:02d}", 1, 1) for i in range(9)]
        self.assertTrue(any("under 3.5 goals in 9 straight" in t for _, t in context.streaks("Napoli", rs2)))


class Tactics(unittest.TestCase):
    def test_shape_reads_pivots(self):
        import teamstyle
        self.assertEqual(teamstyle.shape("4-2-3-1")["pivot"], 2)
        self.assertEqual(teamstyle.shape("4-3-3")["pivot"], 1)
        self.assertEqual(teamstyle.shape("3-4-2-1")["pivot"], 2)
        self.assertEqual(teamstyle.shape("3-4-2-1")["back3"], 1.0)

    def test_context_shape_names_the_pivot(self):
        xi = [{"name": "GK", "pos": "G"}] + [{"name": f"D{i}", "pos": "D"} for i in range(4)] \
            + [{"name": "P1", "pos": "M"}, {"name": "P2", "pos": "M"}] \
            + [{"name": f"A{i}", "pos": "M"} for i in range(3)] + [{"name": "ST", "pos": "F"}]
        e = {"lineups": {"confirmed": {"confirmed": True, "home": {"formation": "4-2-3-1", "xi": xi}}}}
        sh = context.shape(e, "home")
        self.assertEqual(sh["pivot"], ["P1", "P2"])
        self.assertEqual(sh["attack_mids"], ["A0", "A1", "A2"])

    def test_team_model_is_loadable_when_present(self):
        meta = Path(__file__).resolve().parent.parent / "teammodel" / "meta.json"
        if not meta.exists():
            self.skipTest("no team model exported")
        import json
        m = json.loads(meta.read_text())
        self.assertTrue(any(v["use"] == "gbm" for v in m["stats"].values()))


if __name__ == "__main__":
    unittest.main()
