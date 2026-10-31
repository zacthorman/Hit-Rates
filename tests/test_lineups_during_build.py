"""lineups_auto: line-ups are fetched and published even while the nightly build holds .update.lock."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import lineups_auto as la  # noqa: E402


class DuringBuild(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "cache").mkdir()
        self._root = la.ROOT
        la.ROOT = self.tmp
        self.calls = []
        self.p = [mock.patch.object(la, "background_prices", lambda: self.calls.append("prices")),
                  mock.patch.object(la, "notify_selections", lambda: self.calls.append("notify")),
                  mock.patch.object(la, "say", lambda m: self.calls.append(m))]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()
        la.ROOT = self._root

    def test_nothing_due_during_build_holds_back_price_jobs(self):
        (self.tmp / ".update.lock").write_text("1")
        with mock.patch.object(la, "due", return_value={}):
            la.main()
        self.assertEqual(self.calls, [])

    def test_nothing_due_without_build_runs_price_jobs(self):
        with mock.patch.object(la, "due", return_value={}):
            la.main()
        self.assertEqual(self.calls, ["prices", "notify"])

    def test_line_ups_are_checked_during_the_build(self):
        (self.tmp / ".update.lock").write_text("1")
        seen = []
        fake_update = types.SimpleNamespace(ensure_flaresolverr=lambda: seen.append("checked") or False)
        with mock.patch.object(la, "due", return_value={"x.html": {"fixtures": []}}), \
                mock.patch.dict(sys.modules, {"update": fake_update}):
            la.main()
        self.assertEqual(seen, ["checked"])   # it went on to fetch, rather than returning at the lock


if __name__ == "__main__":
    unittest.main()
