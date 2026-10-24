"""tonight.py has one tonight_chance, the module-level one with the darts fix.

Run from the repo root with the repo's own Python:

    .venv/bin/python -m unittest tests.test_tonight_definitions

main and oct21-work each had a tonight_chance. The branch moved it to module
level and taught it darts (weekend.chance, not 0); main kept its own copy
inside build(). Git merged both without a conflict, and the inner copy
shadowed the module-level one: the tonight step crashed where the branch's
call passed a sport, and silently dropped the darts fix everywhere else
(RELEASE-CHECK.md). These tests fail if a second definition appears, by
name or by shadowing, and check that the one left is the one with the fix.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SOURCE = (ROOT / "tonight.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def all_defs(tree):
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


class OneDefinition(unittest.TestCase):
    def test_tonight_chance_is_defined_once_at_module_level(self):
        found = [n for n in all_defs(TREE) if n.name == "tonight_chance"]
        self.assertEqual(len(found), 1, f"tonight_chance defined {len(found)} times, lines "
                                        f"{[n.lineno for n in found]}")
        self.assertIn(found[0], TREE.body, "tonight_chance must be the module-level function")

    def test_no_nested_function_shadows_a_module_function(self):
        top = {n.name for n in TREE.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        nested = [(n.name, n.lineno) for parent in TREE.body
                  if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef))
                  for n in all_defs(parent) if n is not parent and n.name in top]
        self.assertEqual(nested, [], "a function inside another shadows the module-level one of the same name")

    def test_the_one_left_has_the_darts_fix_and_takes_a_sport(self):
        import tonight
        import weekend
        leg = {"hits": 7, "total": 10, "fair": 1.5}
        self.assertEqual(tonight.tonight_chance(leg), 0)                 # nothing calibrated: last
        self.assertAlmostEqual(tonight.tonight_chance(leg, "darts"), weekend.chance(leg))
        self.assertEqual(tonight.tonight_chance({"gs": {"chance": 0.61}}, "football"), 0.61)


if __name__ == "__main__":
    unittest.main()
