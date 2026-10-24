"""pagedata.search against the regex it replaced.

    python -B -m unittest tests.test_pagedata

Synthetic pages always; every built report in reports/ as well when there are
any.
"""
import random
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pagedata  # noqa: E402

OLD = re.compile(r"const ALL = (\{.*?\});\n", re.S)


def old(text):
    m = OLD.search(text)
    return None if m is None else m.group(1)


def new(text):
    m = pagedata.search(text)
    return None if m is None else m.group(1)


class SameAsRegex(unittest.TestCase):
    CASES = [
        "",
        "const ALL = {};\n",
        "const ALL = {}",
        "const ALL = {};",
        "x const ALL = {\"a\": 1};\nconst ALL = {\"b\": 2};\n",
        "const ALL = {\"a\": \"};\"};\n",
        "const ALL = {\"a\": {\"b\": 1}};\n tail };\n",
        "const ALL = {\n\"a\": 1\n};\n",
        "const ALL = [1];\nconst ALL = {\"x\": 1};\n",
        "const ALL = {\"no end\": 1}",
        "const ALL = {\"a\": 1}\n;\n};\n",
        "prefix\nconst ALL = {\"fixtures\": []};\n</script>",
        "const ALL = {};\n" * 3,
        "const ALL = { };\nconst ALL = {};\n",
    ]

    def test_cases(self):
        for text in self.CASES:
            self.assertEqual(new(text), old(text), repr(text))

    def test_random(self):
        rng = random.Random(22)
        alphabet = ["const ALL = {", "};\n", "}", ";", "\n", "{", "a", " ", "const ALL = "]
        for _ in range(5000):
            text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))
            self.assertEqual(new(text), old(text), repr(text))

    def test_pattern_object(self):
        text = "const ALL = {\"a\": 1};\n"
        self.assertEqual(pagedata.PAYLOAD.search(text).group(1), old(text))
        self.assertIsNone(pagedata.PAYLOAD.search("nothing here"))

    def test_built_reports(self):
        pages = sorted((ROOT / "reports").glob("*.html"))
        if not pages:
            self.skipTest("no built reports")
        for path in pages:
            text = path.read_text(encoding="utf-8")
            self.assertEqual(new(text), old(text), path.name)


if __name__ == "__main__":
    unittest.main()
