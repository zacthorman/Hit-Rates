"""confluence.py: the votes and the tiers frozen on 3 Nov 2026."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import confluence as C  # noqa: E402


def player(sport="basketball", price=2.0, chance=0.6, site=0.6, learned=0.6, k10=8, n10=10, k5=4, n5=5,
           adj=1.1, over=True, sharp=None, sharp_first=None, xi=None):
    snap = {"price": price, "chance": chance, "site_chance": site, "learned_chance": learned}
    if xi is not None:
        snap["confirmed_xi"] = xi
    r = {"event_id": 1, "player": "A Player", "sport": sport, "stat": "Points", "line": 20.5, "over": over,
         "label": "Over 20.5", "k10": k10, "n10": n10, "k5": k5, "n5": n5, "adj": adj, "first": dict(snap),
         "last": dict(snap), "kickoff": C.FREEZE + 3600}
    if sharp is not None:
        r["sharp_last"] = {"p": sharp, "beats_lay": False}
        r["sharp_first"] = {"p": sharp_first if sharp_first is not None else sharp, "beats_lay": False}
    return r


def team(price=2.0, expected=6.0, line=4.5, model_p=0.7, recent=(6, 7, 3, 8, 6, 5, 7, 6, 9, 6), sharp=None):
    r = {"event_id": 2, "team": "A Side", "scope": "home", "stat": "Corner kicks", "line": line, "over": True,
         "expected": expected, "basis": "projection", "model_p": model_p, "recent": list(recent),
         "first": {"price": price}, "last": {"price": price}, "kickoff": C.FREEZE + 3600}
    if sharp is not None:
        r["sharp_last"] = r["sharp_first"] = {"p": sharp, "beats_lay": False}
    return r


class Votes(unittest.TestCase):
    def test_every_source_votes_on_its_own_chance_against_the_price(self):
        v = C.votes(player())
        self.assertEqual(set(v["yes"]), {"model", "site", "learned", "form10", "form5", "adj"})

    def test_a_short_price_turns_the_votes_against(self):
        v = C.votes(player(price=1.4))       # implied 71%: every source at 60% says no
        self.assertNotIn("model", v["yes"])

    def test_the_opponent_adjustment_reverses_for_unders(self):
        self.assertIn("adj", C.votes(player(over=False, adj=0.9))["yes"])
        self.assertNotIn("adj", C.votes(player(over=False, adj=1.1))["yes"])

    def test_long_prices_are_left_alone(self):
        self.assertIsNone(C.votes(player(price=7.0)))

    def test_team_stats_projection_votes_for_team_lines(self):
        v = C.votes(team())
        self.assertIn("proj", v["yes"])
        self.assertEqual(v["kind"], "team")


class Tiers(unittest.TestCase):
    def test_nba_player_with_five_sources_is_on_trial(self):
        self.assertEqual(C.tier(C.votes(player())), "trial")

    def test_football_players_never_qualify_on_agreement_alone(self):
        self.assertIsNone(C.tier(C.votes(player(sport="football", xi=True))))

    def test_sharp_agreement_plus_two_more_is_strong_even_for_football(self):
        r = player(sport="football", chance=0.6, site=0.3, learned=0.3, k10=2, k5=1, adj=0.9, sharp=0.6)
        v = C.votes(r)
        self.assertEqual(set(v["yes"]), {"model", "sharp"})
        self.assertIsNone(C.tier(v))                      # sharp + 1 other is not enough
        r["sharp_first"] = {"p": 0.55}                    # the sharp price moved our way: a third vote
        self.assertEqual(C.tier(C.votes(r)), "strong")

    def test_the_sharp_price_is_a_veto(self):
        v = C.votes(player(sharp=0.4))                    # everything agrees except Betfair
        self.assertIs(v["V"]["sharp"], False)
        self.assertIsNone(C.tier(v))

    def test_team_lines_need_four_without_a_sharp_price(self):
        self.assertEqual(C.tier(C.votes(team())), "trial")
        self.assertIsNone(C.tier(C.votes(team(model_p=0.3, recent=(1, 2, 3, 2, 1, 2, 3, 2, 1, 2)))))


class Record(unittest.TestCase):
    def test_one_line_per_player_per_game_and_only_after_the_freeze(self):
        a = player(); a["result"] = "win"
        b = player(); b["line"] = 22.5; b["result"] = "lose"          # same player, same game
        old = player(); old["event_id"] = 9; old["kickoff"] = C.FREEZE - 10; old["result"] = "lose"
        rec = C.record(rows=[a, b, old])
        self.assertEqual(rec["trial"]["n"], 1)


if __name__ == "__main__":
    unittest.main()
