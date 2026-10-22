"""Tests for cards_model.py, the cards wiring in context.py and fmodel_live.py.

    python -B -m unittest tests.test_cards_model
"""
import json
import math
import random
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cards_model as C  # noqa: E402

TID = 17


def _items(pairs):
    return [{"name": n, "homeValue": h, "awayValue": a} for n, (h, a) in pairs.items()]


def write_cache(path: Path, matches):
    """A minimal SofaScore cache: one events file, and statistics and line-ups per match.

    matches: [(id, ts, home, away, yellows or None, fouls, players)] where
    players is {"home": [(pid, pos, sub, minutes, fouls)], "away": [...]}."""
    events = []
    for mid, ts, h, a, y, f, players in matches:
        events.append({"id": mid, "startTimestamp": ts, "status": {"type": "finished"},
                       "tournament": {"category": {"sport": {"slug": "football"}}, "uniqueTournament": {"id": TID}},
                       "homeTeam": {"id": h}, "awayTeam": {"id": a},
                       "homeScore": {"current": 1}, "awayScore": {"current": 0}})
        allp = {"Fouls": f}
        if y is not None:
            allp["Yellow cards"] = y
        half = {"Fouls": (f[0] / 2, f[1] / 2)}
        if y is not None:
            half["Yellow cards"] = (y[0] / 2, y[1] / 2)
        stats = {"statistics": [{"period": p, "groups": [{"statisticsItems": _items(d)}]}
                                for p, d in (("ALL", allp), ("1ST", half), ("2ND", half))]}
        (path / f"event_{mid}_statistics.json").write_text(json.dumps(stats))
        lu = {side: {"players": [{"player": {"id": pid}, "position": pos, "substitute": sub,
                                  "statistics": {"minutesPlayed": mins, "fouls": fl}}
                                 for pid, pos, sub, mins, fl in players[side]]}
              for side in ("home", "away")}
        (path / f"event_{mid}_lineups.json").write_text(json.dumps(lu))
    (path / "team_1_events_last_0.json").write_text(json.dumps({"events": events}))


def squad(team, rng):
    out = [(team * 100, "G", False, 90, 0)]
    for i in range(1, 11):
        out.append((team * 100 + i, "DMF"[i % 3], False, 90 if i < 9 else 70, rng.randint(0, 3)))
    out.append((team * 100 + 11, "M", True, 20, 0))
    return out


def league(n_rounds=12, seed=3):
    rng = random.Random(seed)
    teams = [1, 2, 3, 4]
    out, mid, ts = [], 1000, 1_700_000_000
    for _ in range(n_rounds):
        rng.shuffle(teams)
        for h, a in ((teams[0], teams[1]), (teams[2], teams[3])):
            y = None if rng.random() < 0.15 else (float(rng.randint(0, 4)), float(rng.randint(0, 4)))
            f = (float(rng.randint(8, 16)), float(rng.randint(8, 16)))
            out.append((mid, ts, h, a, y, f, {"home": squad(h, rng), "away": squad(a, rng)}))
            mid += 1
            ts += 3600
        ts += 86400
    return out


class TestData(unittest.TestCase):
    def test_missing_cards_row_with_fouls_is_a_nil_nil(self):
        self.assertEqual(C.cards_pair({"Fouls": (10.0, 12.0)}), (0.0, 0.0))

    def test_no_fouls_no_cards_is_unknown(self):
        self.assertIsNone(C.cards_pair({"Ball possession": (50.0, 50.0)}))

    def test_cards_row_read_as_is(self):
        self.assertEqual(C.cards_pair({"Yellow cards": (2.0, 3.0), "Fouls": (10.0, 9.0)}), (2.0, 3.0))

    def test_load_keeps_nil_nils_and_the_competition(self):
        with tempfile.TemporaryDirectory() as d:
            ms = league()
            write_cache(Path(d), ms)
            got = C.load(Path(d))
        self.assertEqual(len(got), len(ms))
        missing = [m for m in ms if m[4] is None]
        self.assertTrue(missing)
        by = {m["id"]: m for m in got}
        for m in missing:
            self.assertEqual(by[m[0]]["y"], (0.0, 0.0))
        self.assertEqual({m["tid"] for m in got}, {TID})
        self.assertEqual([m["ts"] for m in got], sorted(m["ts"] for m in got))


class TestPieces(unittest.TestCase):
    def test_shrunk(self):
        self.assertAlmostEqual(C.shrunk([4, 4], 2.0, k=2), 3.0)
        self.assertAlmostEqual(C.shrunk([], 2.0), 2.0)

    def test_heuristic_matches_the_page(self):
        # report.py cardCase: fouls per 90 over gated apps, median minutes, x per foul x adjustment
        apps = [{"min": 90, "fouls": 2}, {"min": 80, "fouls": 1}, {"min": 60, "fouls": 0}, {"min": 20, "fouls": 3}]
        want = 3 / 230 * 90 * 80 / 90 * 0.13 * 1.1
        self.assertAlmostEqual(C.heuristic_lambda(apps, 0.13, 1.1), want)
        self.assertIsNone(C.heuristic_lambda(apps[:2], 0.13, 1.0))
        p = C.player_card_chance(apps, apps, 0.13, 1.1)
        self.assertAlmostEqual(p, 1 - math.exp(-want))

    def test_sf_against_direct_sums(self):
        mu = np.array([0.4, 1.7, 3.2])
        for line in (0.5, 1.5, 2.5, 3.5):
            k = int(line)
            pois = 1 - np.array([sum(math.exp(-m) * m ** i / math.factorial(i) for i in range(k + 1)) for m in mu])
            np.testing.assert_allclose(C.sf(line, mu, 0.0), np.clip(pois, 1e-4, 1 - 1e-4), atol=1e-12)
            a = 0.3
            r = 1 / a

            def nb(m, i):
                return math.exp(math.lgamma(i + r) - math.lgamma(r) - math.lgamma(i + 1)
                                + r * math.log(r / (r + m)) + i * math.log(m / (r + m)))
            want = 1 - np.array([sum(nb(m, i) for i in range(k + 1)) for m in mu])
            np.testing.assert_allclose(C.sf(line, mu, a), np.clip(want, 1e-4, 1 - 1e-4), atol=1e-12)

    def test_poisson_glm_recovers_coefficients(self):
        rng = np.random.default_rng(0)
        X = np.column_stack([np.ones(20000), rng.normal(size=20000), rng.binomial(1, .5, 20000)])
        b = np.array([0.7, 0.25, -0.15])
        y = rng.poisson(np.exp(X @ b))
        np.testing.assert_allclose(C.poisson_glm(X, y.astype(float)), b, atol=0.03)

    def test_xi_chances_add_up_to_the_side(self):
        w = [0.2, 0.1, 0.4, None, 0.3]
        ps = C.xi_chances(w, 2.0, 0.86)
        self.assertIsNone(ps[3])
        lam = [-math.log(1 - p) for p in ps if p is not None]
        fill = sum(x for x in w if x is not None) / 4
        # the unweighable starter keeps his share of the split, just no chance
        self.assertAlmostEqual(sum(lam) + 0.86 * 2.0 * fill / (1.0 + fill), 0.86 * 2.0)
        self.assertGreater(ps[2], ps[0])
        self.assertEqual(C.xi_chances([None, None], 2.0, 0.86), [None, None])

    def test_starter_share_between_minutes_and_one(self):
        with tempfile.TemporaryDirectory() as d:
            write_cache(Path(d), league())
            s = C.starter_share(C.load(Path(d)))
        self.assertTrue(0.8 < s < 1.0)


class TestIncidents(unittest.TestCase):
    def test_booked_reads_card_incidents(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "event_5_incidents.json").write_text(json.dumps({"incidents": [
                {"incidentType": "card", "incidentClass": "yellow", "player": {"id": 11}},
                {"incidentType": "card", "incidentClass": "red", "player": {"id": 12}},
                {"incidentType": "goal", "player": {"id": 13}},
                {"incidentType": "card", "player": {}}]}))
            (p / "event_6_incidents.json").write_text(json.dumps({"incidents": [], "missing": True}))
            self.assertEqual(C.booked(p, 5), {11, 12})
            self.assertIsNone(C.booked(p, 6))
            self.assertIsNone(C.booked(p, 7))

    def test_rows_carry_who_was_booked(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            ms = league()
            write_cache(p, ms)
            last = ms[-1]
            (p / f"event_{last[0]}_incidents.json").write_text(json.dumps({"incidents": [
                {"incidentType": "card", "player": {"id": last[2] * 100 + 1}}]}))
            rows = C.rows_from(C.load(p))
        row = next(r for r in rows if r["match"] == last[0] and r["team"] == last[2])
        flags = {s["pid"]: s["booked"] for s in row["starters"]}
        self.assertTrue(flags[last[2] * 100 + 1])
        self.assertFalse(flags[last[2] * 100 + 2])
        other = next(r for r in rows if r["match"] != last[0])
        self.assertTrue(all(s["booked"] is None for s in other["starters"]))

    def test_score_players(self):
        rng = random.Random(4)
        apps = [{"min": 90, "fouls": 1}] * 5
        rows, lams = [], []
        for i in range(40):
            st = [{"pid": j, "recent": apps, "played": apps, "booked": rng.random() < 0.18} for j in range(10)]
            rows.append({"match": i, "starters": st})
            lams.append([0.2] * 10)
        out = C.score_players(rows, np.full(40, 2.0), lams, [0.86] * 40)
        self.assertEqual(out["n"], 400)
        self.assertAlmostEqual(out["model"][2], 1 - math.exp(-0.172))
        self.assertAlmostEqual(out["heuristic"][2], 1 - math.exp(-0.2))
        self.assertIn("boot", out)
        self.assertEqual(C.score_players(rows[:5], np.full(5, 2.0), lams[:5], [0.86] * 5), {"n": 50})


class TestLive(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.path = Path(self.d.name)
        self.ms = league(n_rounds=14)
        write_cache(self.path, self.ms)
        rows = C.rows_from(C.load(self.path))
        m = C.GLMCards(C.VARIANTS["N4 +fouls+elo"]).fit(rows)
        self.fit = {"variant": "N4 +fouls+elo", "columns": C.VARIANTS["N4 +fouls+elo"],
                    "coef": [float(v) for v in m.b], "alpha": m.alpha, "starter_share": 0.86}
        self.rows = rows

    def tearDown(self):
        self.d.cleanup()

    def test_live_features_equal_the_backtest_row(self):
        """The last match, replayed as upcoming from a cache that stops before it."""
        last = self.ms[-1]
        with tempfile.TemporaryDirectory() as d2:
            write_cache(Path(d2), self.ms[:-1])
            live = C.Live(Path(d2), self.fit)
        row = next(r for r in self.rows if r["match"] == last[0] and r["team"] == last[2])
        got = live.side_mu(last[2], last[3], True, TID)
        for k in C.VARIANTS["N4 +fouls+elo"] + ["home"]:
            self.assertAlmostEqual(got["x"][k], row[k], places=12, msg=k)
        self.assertAlmostEqual(got["mu"], float(np.exp(C.design([row], self.fit["columns"]) @ np.array(self.fit["coef"]))[0]))
        self.assertEqual(got["x"]["own_Yellow cards"], row["own_y10"])

    def test_player_chances_sum_to_the_side(self):
        live = C.Live(self.path, self.fit)
        team, opp = 1, 2
        xi = [{"pid": pid, "pos": pos} for pid, pos, sub, _, _ in squad(team, random.Random(1)) if not sub]
        ps = live.player_chances(team, opp, True, TID, xi)
        self.assertNotIn(team * 100, ps)                   # the keeper
        self.assertEqual(len(ps), 10)
        side = live.side_mu(team, opp, True, TID)
        lam = sum(-math.log(1 - p) for p in ps.values())
        self.assertAlmostEqual(lam, 0.86 * side["mu"], places=9)

    def test_too_few_games_gives_nothing(self):
        live = C.Live(self.path, self.fit)
        self.assertIsNone(live.side_mu(1, 999, True, TID))
        self.assertEqual(live.player_chances(1, 999, True, TID, [{"pid": 101, "pos": "M"}]), {})


class TestWiring(unittest.TestCase):
    def test_context_sends_yellow_cards_to_the_cards_model(self):
        import context

        class Fake:
            def side_mu(self, team, opp, home, tid):
                return {"mu": 2.5, "alpha": 0.0, "x": {"own_Yellow cards": 2.0, "opp_conc_Yellow cards": 2.2},
                        "kind": "cards model", "seen": (team, opp, home, tid)}
        saved = dict(context._CM)
        context._CM.clear()
        context._CM["live"] = Fake()
        try:
            r = context.team_model_mu("Yellow cards", 5, 6, True, "4-3-3", "4-4-2", tid=8)
            self.assertEqual(r["kind"], "cards model")
            self.assertEqual(r["seen"], (5, 6, True, 8))
        finally:
            context._CM.clear()
            context._CM.update(saved)

    def test_fmodel_live_adds_card_lines_to_known_starters(self):
        import fmodel_live

        class Fake:
            def side_mu(self, team, opp, home, tid):
                return {"mu": 2.0 if home else 1.5}

            def player_chances(self, team, opp, home, tid, xi):
                return {p["pid"]: 0.2 for p in xi if p["pos"] != "G"}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            ms = league(n_rounds=1)
            write_cache(path, ms)
            mid, _, h, a = ms[0][:4]
            saved = fmodel_live.CACHE, fmodel_live.team_ids
            fmodel_live.CACHE = path
            fmodel_live.team_ids = lambda: {mid: (h, a, TID)}
            try:
                events = {str(mid): {"players": {"Keeper": {"pid": h * 100, "lines": {}},
                                                 "Mid": {"pid": h * 100 + 1, "lines": {"Fouls": {"1": 0.6}}}}}}
                fmodel_live.add_cards(events, live=Fake())
            finally:
                fmodel_live.CACHE, fmodel_live.team_ids = saved
        ev = events[str(mid)]
        self.assertEqual(ev["players"]["Mid"]["lines"]["Card"], {"1": 0.2})
        self.assertEqual(ev["players"]["Mid"]["lines"]["Fouls"], {"1": 0.6})
        self.assertNotIn("Card", ev["players"]["Keeper"]["lines"])
        self.assertEqual(ev["cards"], {"home": 2.0, "away": 1.5})


if __name__ == "__main__":
    unittest.main()
