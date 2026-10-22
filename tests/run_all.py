"""Run every test file in tests/, unittest and plain-function alike.

    .venv/bin/python -B tests/run_all.py

Most files here are unittest. test_exchange.py is written as bare test_
functions for pytest, which is not installed, so `python -m unittest`
reports "NO TESTS RAN" for it and passes. This runs those functions too, so
"every test passed" means every test ran.
"""
import importlib
import inspect
import sys
import traceback
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))


def main() -> int:
    # learner.model() refits and rewrites learned.json whenever the picks are
    # built, and several tests build them. Pointed at a scratch file so that
    # running the tests never changes the committed model.
    import tempfile
    import learner
    learner.OUT = Path(tempfile.mkdtemp()) / "learned.json"

    failed = 0
    for path in sorted(HERE.glob("test_*.py")):
        name = path.stem
        module = importlib.import_module(name)
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
        bare = [f for n, f in inspect.getmembers(module, inspect.isfunction)
                if n.startswith("test_") and f.__module__ == name]
        print(f"== {path.name}")
        if suite.countTestCases():
            result = unittest.TextTestRunner(verbosity=0, stream=sys.stdout).run(suite)
            failed += len(result.failures) + len(result.errors)
        for func in bare:
            try:
                func()
            except Exception:
                failed += 1
                print(f"FAIL {name}.{func.__name__}")
                traceback.print_exc()
        if bare:
            print(f"Ran {len(bare)} plain test function(s)")
    print("\nALL PASSED" if not failed else f"\n{failed} FAILURE(S)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
