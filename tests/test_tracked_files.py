"""A test run leaves every tracked file as it found it.

    python -B -m unittest tests.test_tracked_files
    python -m pytest tests/test_tracked_files.py

Every session up to 23 Oct 2026 found that running the suite rewrote the
committed learned.json (tests/test_strength.py, through learner.model()).
This runs every other test file in a fresh process, without the conftest.py
redirect so the live default path is what is tested, and fails if
learned.json or any other tracked file differs afterwards. It takes as long
as the suite itself; set HITRATES_SKIP_TRACKED=1 to leave it out.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEARNED = ROOT / "learned.json"
INNER = "HITRATES_TRACKED_INNER"      # set in the child run, so this test does not recurse


def _digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _tracked_diff():
    """The working tree's diff against the index for tracked files, or None without git."""
    if not shutil.which("git") or not (ROOT / ".git").exists():
        return None
    done = subprocess.run(["git", "diff", "--no-ext-diff", "--binary"], cwd=ROOT,
                          capture_output=True, timeout=120)
    return hashlib.sha256(done.stdout).hexdigest() if done.returncode == 0 else None


@unittest.skipIf(os.environ.get(INNER), "inside the run this test starts")
@unittest.skipIf(os.environ.get("HITRATES_SKIP_TRACKED"), "HITRATES_SKIP_TRACKED set")
class TrackedFilesUntouched(unittest.TestCase):
    def test_suite_leaves_learned_json_and_tracked_files_alone(self):
        env = dict(os.environ, **{INNER: "1"})
        env.pop("HITRATES_LEARNED_JSON", None)       # the live default, not the redirect
        others = sorted(p.name for p in (ROOT / "tests").glob("test_*.py") if p.name != Path(__file__).name)
        try:
            import pytest  # noqa: F401
            cmd = [sys.executable, "-B", "-m", "pytest", "-q", "--noconftest", "-p", "no:cacheprovider",
                   *[f"tests/{n}" for n in others]]
        except ImportError:
            cmd = [sys.executable, "-B", "-m", "unittest", "-q", *[f"tests.{n[:-3]}" for n in others]]
        learned, diff = _digest(LEARNED), _tracked_diff()
        done = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=1800)
        self.assertEqual(_digest(LEARNED), learned,
                         "learned.json changed during a test run:\n" + done.stdout[-2000:])
        if diff is not None:
            self.assertEqual(_tracked_diff(), diff,
                             "a tracked file changed during a test run (see git status):\n" + done.stdout[-2000:])
        # The child's own pass or fail is reported by the normal run; this
        # test is only about what it left behind.


if __name__ == "__main__":
    unittest.main()
