"""darts_legs.py and the checks in darts_legs_backtest.py.

    python -B -m unittest tests.test_darts_legs

Synthetic matches only, no cache needed.
"""
import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import darts_legs as L            # noqa: E402
import darts_legs_backtest as B   # noqa: E402

DAY = 86400


def match(i, ts, a, b, la, lb, fmt=("legs", 6), stats=None):
    sa, sb = la, lb
    return {"id": i, "ts": ts, "status": "finished", "a": a, "b": b,
            "a_name": f"P{a}", "b_name": f"P{b}", "sa": sa, "sb": sb, "fmt": fmt,
            "la": la, "lb": lb, "stats": stats}


def simulate(n_players=12, n_matches=1500, seed=3, fmt=("legs", 6)):
    """A tour where player k wins a leg against j with log-odds
    0.12 * (k - j), legs drawn one at a time, throw ignored."""
    rnd = random.Random(seed)
    out = []
    for i in range(n_matches):
        a, b = rnd.sample(range(n_players), 2)
        p = 1 / (1 + math.exp(-0.12 * (a - b)))
        la = lb = 0
        while la < fmt[1] and lb < fmt[1]:
            if rnd.random() < p:
                la += 1
            else:
                lb += 1
        legs = la + lb
        stats = {"a": {"Thrown 180": sum(rnd.random() < 0.3 for _ in range(legs)),
                       "Checkouts over 100": sum(rnd.random() < 0.1 for _ in range(la)),
                       "Highest checkout": max([rnd.randint(40, 130) for _ in range(la)] or [0]),
                       "Average 3 darts": 88 + a + rnd.gauss(0, 4)},
                 "b": {"Thrown 180": sum(rnd.random() < 0.3 for _ in range(legs)),
                       "Checkouts over 100": sum(rnd.random() < 0.1 for _ in range(lb)),
                       "Highest checkout": max([rnd.randint(40, 130) for _ in range(lb)] or [0]),
                       "Average 3 darts": 88 + b + rnd.gauss(0, 4)}}
        out.append(match(i, 1_700_000_000 + i * DAY // 4, a, b, la, lb, fmt, stats))
    return out


class MatchMaths(unittest.TestCase):

    def test_distribution_sums_to_one(self):
        for fmt in (("legs", 6), ("legs", 10), ("sets", 3, 3), ("sets", 4, 3)):
            d = L.match_distribution(0.4, 0.1, fmt)
            self.assertAlmostEqual(sum(d.values()), 1.0, places=9)

    def test_even_match_is_even(self):
        for fmt in (("legs", 6), ("sets", 3, 3)):
            s = L.summarise(L.match_distribution(0.0, 0.05, fmt), fmt)
            self.assertAlmostEqual(s["win"], 0.5, places=6)
            self.assertAlmostEqual(s["legsA"], s["legsB"], places=6)

    def test_longer_format_favours_the_better_player(self):
        short = L.summarise(L.match_distribution(0.3, 0.0, ("legs", 4)), ("legs", 4))["win"]
        long_ = L.summarise(L.match_distribution(0.3, 0.0, ("legs", 11)), ("legs", 11))["win"]
        self.assertGreater(long_, short)
        self.assertGreater(short, 0.5)

    def test_gap_uncertainty_pulls_towards_even(self):
        sharp = L.summarise(L.match_distribution(0.5, 0.0, ("legs", 6)), ("legs", 6))["win"]
        blur = L.summarise(L.match_distribution(0.5, 0.3, ("legs", 6)), ("legs", 6))["win"]
        self.assertLess(blur, sharp)
        self.assertGreater(blur, 0.5)

    def test_sets_legs_are_consistent(self):
        """Every outcome in a first to 3 sets of first to 3 legs has the
        winner on 3 sets and between 9 and 25 legs played."""
        for (sa, sb, la, lb), p in L.match_distribution(0.2, 0.1, ("sets", 3, 3)).items():
            self.assertEqual(max(sa, sb), 3)
            self.assertLess(min(sa, sb), 3)
            self.assertGreaterEqual(la + lb, 9)
            self.assertLessEqual(la + lb, 25)
            self.assertGreaterEqual(la, 3 * sa)

    def test_legs_format_score_equals_legs(self):
        for (sa, sb, la, lb), _ in L.match_distribution(0.1, 0.1, ("legs", 6)).items():
            self.assertEqual((sa, sb), (la, lb))


class Ratings(unittest.TestCase):

    def test_orders_players(self):
        r = L.LegRatings(simulate())
        order = sorted(r.mu, key=lambda pid: r.mu[pid])
        # Rank correlation with the truth (player id) should be near one.
        n = len(order)
        d2 = sum((rank - pid) ** 2 for rank, pid in enumerate(order))
        rho = 1 - 6 * d2 / (n * (n * n - 1))
        self.assertGreater(rho, 0.9)

    def test_no_lookahead(self):
        """The prediction for a match does not change when later matches are
        added."""
        ms = simulate(n_matches=600)
        early = L.LegRatings(ms[:400])
        full = L.LegRatings(ms)
        for m in ms[:400]:
            self.assertEqual(early.preds[m["id"]], full.preds[m["id"]])

    def test_new_player_shrunk_to_prior(self):
        r = L.LegRatings([])
        mu, var = r.state(999, 0)
        self.assertEqual((mu, var), (L.LEG["new"], L.LEG["var0"]))

    def test_uncertainty_grows_while_away(self):
        ms = simulate(n_matches=300)
        r = L.LegRatings(ms)
        pid = ms[-1]["a"]
        _, v_now = r.state(pid, r.last[pid])
        _, v_later = r.state(pid, r.last[pid] + 200 * DAY)
        self.assertGreater(v_later, v_now)
        self.assertLessEqual(v_later, L.VAR_CAP)

    def test_one_big_win_moves_a_newcomer_more_than_a_regular(self):
        ms = simulate(n_matches=400)
        r = L.LegRatings(ms)
        regular = ms[-1]["a"]
        ts = ms[-1]["ts"] + DAY
        before = r.mu[regular]
        r.update(match(10_000, ts, regular, 500, 6, 0))
        moved_regular = r.mu[regular] - before
        moved_new = L.LEG["new"] - r.mu[500]
        self.assertGreater(moved_new, moved_regular)


class StatLines(unittest.TestCase):

    def setUp(self):
        self.ms = simulate(n_matches=450)
        self.book = L.StatBook(self.ms)
        self.ts = self.ms[-1]["ts"] + DAY

    def test_rates_shrunk_towards_tour(self):
        tour = self.book.tour_rates(self.ts)
        self.assertAlmostEqual(tour["r180"], 0.3, delta=0.03)
        self.assertAlmostEqual(tour["r100"], 0.1, delta=0.02)
        fresh = self.book.player(12345, self.ts, tour)
        self.assertAlmostEqual(fresh["r180"], tour["r180"])
        self.assertAlmostEqual(fresh["avg"], tour["avg"])

    def test_average_follows_skill(self):
        tour = self.book.tour_rates(self.ts)
        lo = self.book.player(0, self.ts, tour)["avg"]
        hi = self.book.player(11, self.ts, tour)["avg"]
        self.assertGreater(hi - lo, 6)

    def test_more_legs_more_180s(self):
        tour = self.book.tour_rates(self.ts)
        pl = self.book.player(5, self.ts, tour)
        short = L.stat_chance("Thrown 180", 2.5, "a", L.match_distribution(0, 0.05, ("legs", 4)), pl)
        long_ = L.stat_chance("Thrown 180", 2.5, "a", L.match_distribution(0, 0.05, ("legs", 10)), pl)
        self.assertGreater(long_, short + 0.2)

    def test_chances_are_probabilities_and_fall_with_the_line(self):
        tour = self.book.tour_rates(self.ts)
        pl = self.book.player(5, self.ts, tour)
        dist = L.match_distribution(0.1, 0.05, ("legs", 6))
        for stat, lines in B.LINES.items():
            ps = [L.stat_chance(stat, x, "a", dist, pl, self.book, self.ts, tour) for x in lines]
            for p in ps:
                self.assertTrue(0 <= p <= 1, (stat, p))
            for x, y in zip(ps, ps[1:]):
                self.assertGreaterEqual(x + 1e-9, y, stat)

    def test_highest_checkout_needs_a_leg_won(self):
        tour = self.book.tour_rates(self.ts)
        pl = self.book.player(5, self.ts, tour)
        whitewash = {(0, 6, 0, 6): 1.0}
        self.assertEqual(L.stat_chance("Highest checkout", 60.5, "a", whitewash, pl,
                                       self.book, self.ts, tour), 0.0)

    def test_negbin_tail_matches_poisson_when_size_is_large(self):
        for lam in (0.5, 2.0, 5.0):
            for line in (0.5, 2.5, 4.5):
                self.assertAlmostEqual(L._negbin_tail(lam, 1e7, line), L._poisson_tail(lam, line), places=4)

    def test_record_chance_is_the_live_formula(self):
        rows = [{"Thrown 180": v} for v in (0, 1, 2, 3, 4)]
        p, n = L.record_chance(rows, "Thrown 180", 1.5)
        self.assertEqual(n, 5)
        self.assertAlmostEqual(p, 3.5 / 6)

    def test_simulated_stat_lines_beat_the_record(self):
        """On a tour generated by the model's own assumptions, the model
        should score better than the last-20 record."""
        rows = B.stat_rows(self.ms, start=self.ms[330]["ts"])
        c = B.compare(rows, "p_rec", "p_new", "sim")
        self.assertLess(c["ll_new"], c["ll_cur"])


class Checks(unittest.TestCase):

    def test_bootstrap_interval_contains_the_mean(self):
        a = [0.5 + 0.01 * (i % 7) for i in range(300)]
        b = [0.5] * 300
        d, lo, hi = B.bootstrap_diff(a, b)
        self.assertTrue(lo <= d <= hi)
        self.assertGreater(lo, 0)

    def test_calibration_bands(self):
        rows = [(0.15, 1), (0.15, 0), (0.85, 1)]
        cal = B.calibration(rows)
        self.assertEqual([c[2] for c in cal], [2, 1])
        self.assertAlmostEqual(cal[0][4], 0.5)


if __name__ == "__main__":
    unittest.main()
