"""Shared set-up for pytest runs of the suite.

Points learner.py's output (learned.json) at a temporary file before any test
module is imported, so no test can rewrite the committed learned.json. The
live pipeline never sets HITRATES_LEARNED_JSON and keeps writing the real
file. At the end of the session the real learned.json is compared with how
it started, and the run fails if it changed.

Plain unittest runs do not read this file; tests/test_tracked_files.py checks
those by running the whole suite without it.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEARNED = ROOT / "learned.json"

_TMP = Path(tempfile.mkdtemp(prefix="hitrates-tests-"))
os.environ["HITRATES_LEARNED_JSON"] = str(_TMP / "learned.json")
if "learner" in sys.modules:          # imported before this file: move it too
    sys.modules["learner"].OUT = _TMP / "learned.json"
_BEFORE = LEARNED.read_bytes() if LEARNED.exists() else None


def pytest_sessionfinish(session, exitstatus):
    after = LEARNED.read_bytes() if LEARNED.exists() else None
    shutil.rmtree(_TMP, ignore_errors=True)
    if after != _BEFORE:
        print("\nlearned.json was changed by this test run; a test is writing a tracked file")
        session.exitstatus = 1
