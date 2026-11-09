"""role.py: a footballer's role from the formation and his slot (8 Nov 2026)."""
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import role  # noqa: E402


def side(formation, ids, gk=1):
    """Starters in SofaScore's order: the goalkeeper, then each line right to left."""
    players = [{"player": {"id": gk, "position": "G"}, "position": "G"}]
    players += [{"player": {"id": i, "position": "D"}, "position": "D"} for i in ids]
    return {"formation": formation, "players": players}


class Roles(unittest.TestCase):
    def roles(self, formation):
        n = sum(int(x) for x in formation.split("-"))
        s = side(formation, list(range(2, 2 + n)))
        r = role.roles(s["formation"], s["players"])
        return [r[i] for i in range(1, 2 + n)]

    def test_back_four_right_to_left(self):
        # Trippier is slot 2 (right-back), Van Dijk slot 4 (left centre-back).
        self.assertEqual(self.roles("4-2-3-1"),
                         ["GK", "FB", "CB", "CB", "FB", "DM", "DM", "W", "AM", "W", "ST"])

    def test_four_three_three(self):
        # Saka slot 9, Haaland slot 10, Martinelli slot 11.
        self.assertEqual(self.roles("4-3-3")[5:], ["CM", "CM", "CM", "W", "ST", "W"])

    def test_back_three_wing_backs_are_in_the_midfield_line(self):
        # Udogie slot 8 in a 3-4-2-1: the left end of the four.
        self.assertEqual(self.roles("3-4-2-1"),
                         ["GK", "CB", "CB", "CB", "WB", "CM", "CM", "WB", "AM", "AM", "ST"])

    def test_back_five(self):
        self.assertEqual(self.roles("5-4-1")[:6], ["GK", "WB", "CB", "CB", "CB", "WB"])
        self.assertEqual(self.roles("5-4-1")[6:], ["W", "CM", "CM", "W", "ST"])

    def test_four_four_two(self):
        self.assertEqual(self.roles("4-4-2")[5:], ["W", "CM", "CM", "W", "ST", "ST"])

    def test_never_guesses_when_the_eleven_do_not_add_up(self):
        s = side("4-2-3-1", list(range(2, 11)))          # nine outfielders
        self.assertEqual(role.roles(s["formation"], s["players"]), {})
        self.assertEqual(role.roles("", side("4-4-2", list(range(2, 12)))["players"]), {})


class LineRole(unittest.TestCase):
    """Mukiele, 8 Nov: centre-back today, a record split between two roles."""

    def setUp(self):
        role._memo.clear()
        self.pid = 99

        def lu(slot_of_99):
            ids = list(range(2, 12))
            ids[slot_of_99 - 2] = self.pid
            return {"confirmed": True, "home": side("4-2-3-1", ids), "away": {}}

        # past matches 1..12: odd at right-back (slot 2), even at centre-back (slot 3)
        for m in range(1, 13):
            role._memo[m] = lu(2 if m % 2 else 3)
        role._memo[100] = lu(3)                              # today: centre-back
        # shots: 2 at full-back every time, 0 at centre-back except matches 10 and 12
        self.rows = [{"player_id": self.pid, "match_id": m, "started": True, "minutes": 90,
                      "date": f"2026-01-{m:02d}", "stats": {"Shots": 2 if m % 2 or m in (10, 12) else 0}}
                     for m in range(1, 13)]

    def tearDown(self):
        role._memo.clear()

    def test_record_at_todays_role_only(self):
        rl = role.line_role(100, self.rows, "Shots", 0.5, True, frozenset({"Shots"}), 45)
        self.assertEqual((rl["role"], rl["family"], rl["xi"]), ("CB", "CB", "confirmed"))
        self.assertEqual((rl["k"], rl["n"]), (2, 6))        # the six centre-back starts
        self.assertEqual(rl["usual"], "CB")                 # 5-5 over ten, the latest wins
        self.assertFalse(rl["change"])

    def test_change_when_usually_elsewhere(self):
        rows = [r for r in self.rows if r["match_id"] % 2]  # only his full-back starts
        rl = role.line_role(100, rows, "Shots", 0.5, True, frozenset({"Shots"}), 45)
        self.assertEqual(rl["usual"], "FB")
        self.assertTrue(rl["change"])
        self.assertEqual((rl["k"], rl["n"]), (0, 0))
        self.assertIn("Centre-back today, usually full-back", role.badge_text(rl))
        self.assertIn("no record there", role.badge_text(rl))

    def test_not_in_the_line_up(self):
        rows = [dict(r, player_id=7777) for r in self.rows]
        self.assertIsNone(role.line_role(100, rows, "Shots", 0.5))


class TagRoles(unittest.TestCase):
    def test_rows_get_the_family_they_started_in(self):
        if "sofascore_api" not in sys.modules:
            try:
                import sofascore_api  # noqa: F401
            except Exception:  # noqa: BLE001 - not needed for this test
                sys.modules["sofascore_api"] = types.ModuleType("sofascore_api")
        import lineup_data
        role._memo.clear()
        ids = list(range(2, 12))
        role._memo[5] = {"home": side("4-2-3-1", ids), "away": {}}
        entry = {"fixture": {"sport": "football"},
                 "players": [[{"player_id": 3, "match_id": 5, "started": True},
                              {"player_id": 9, "match_id": 5, "started": True},
                              {"player_id": 3, "match_id": 5, "started": False}], []]}
        lineup_data._tag_roles(entry)
        rows = entry["players"][0]
        self.assertEqual(rows[0]["role"], "CB")
        self.assertEqual(rows[1]["role"], "AM")              # slot 9 in a 4-2-3-1: the No. 10
        self.assertNotIn("role", rows[2])                    # a sub has no slot
        role._memo.clear()


if __name__ == "__main__":
    unittest.main()
