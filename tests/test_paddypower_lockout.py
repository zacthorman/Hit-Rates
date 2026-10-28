"""paddypower_prices.py: a lone server error locks out briefly, refusals for a day."""
import io
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paddypower_prices as pp  # noqa: E402


def http_error(code):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b""))


class Lockout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._state = pp.STATE
        pp.STATE = Path(self.tmp.name) / "state.json"
        self.t = 1_800_000_000.0
        self._now = pp.now
        pp.now = lambda: self.t

    def tearDown(self):
        pp.STATE = self._state
        pp.now = self._now
        self.tmp.cleanup()

    def hours_left(self, st):
        return (st["lockoutUntil"] - self.t) / 3600

    def test_server_errors_raise_server_error(self):
        for code in (500, 502, 504):
            with mock.patch("urllib.request.urlopen", side_effect=http_error(code)):
                with self.assertRaises(pp.ServerError):
                    pp.fetch_event(1)

    def test_refusals_stay_refusals(self):
        for code in (403, 429, 503):
            with mock.patch("urllib.request.urlopen", side_effect=http_error(code)):
                with self.assertRaises(pp.Refused) as cm:
                    pp.fetch_event(1)
                self.assertNotIsInstance(cm.exception, pp.ServerError)

    def test_lone_server_error_is_two_hours(self):
        st = {}
        pp.lockout(st, "HTTP 500", server_error=True)
        self.assertEqual(self.hours_left(st), pp.SERVER_ERROR_HOURS)

    def test_second_server_error_in_a_day_is_a_full_lockout(self):
        st = {}
        pp.lockout(st, "HTTP 500", server_error=True)
        self.t += 3 * 3600
        pp.lockout(st, "HTTP 502", server_error=True)
        self.assertEqual(self.hours_left(st), pp.LOCKOUT_HOURS)
        self.t += 30 * 3600
        pp.lockout(st, "HTTP 500", server_error=True)
        self.assertEqual(self.hours_left(st), pp.SERVER_ERROR_HOURS)

    def test_refusal_is_a_full_day(self):
        st = {}
        pp.lockout(st, "HTTP 403")
        self.assertEqual(self.hours_left(st), pp.LOCKOUT_HOURS)


if __name__ == "__main__":
    unittest.main()
