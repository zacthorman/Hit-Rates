"""
Replay the daily page build from cache/ alone, timed, for before-and-after checks.

    python replay_build.py run WORKDIR                # build everything in WORKDIR, timed
    python replay_build.py compare BEFORE AFTER       # diff two finished runs
    python replay_build.py run WORKDIR --at "2026-10-17 06:00"
    python replay_build.py run WORKDIR --profile      # and a cProfile per step

WORKDIR is a checkout of the code to test (for example `git archive` of a
branch unpacked somewhere). Its cache/ is symlinked to this checkout's cache/,
so extract cache_backtest.tar.zst into cache/ first.

Why it exists. The real build (update.py, then publish.sh) starts by asking
SofaScore for each league's next round, which needs the network and returns
something different every day, so two runs of it can never be compared. This
replays the same steps against a fixed weekend that is already in the cache:

  * the clock is frozen at --at for every step (libfaketime, if installed:
    `pip install libfaketime`), so "next 8 hours" and every "built at" stamp
    mean the same thing in both runs;
  * every SofaScore request is answered from cache/ or not at all, and every
    other request is pointed at a closed port, so nothing leaves the machine
    and nothing a step does depends on what a website said today;
  * the fixtures are the cached matches that kicked off in the window after
    --at, presented as not yet started, grouped and flagged the way
    update.json builds them.

It never runs publish.sh, never touches git, and writes only inside WORKDIR.
Python's hash seed is fixed so set ordering cannot differ between runs.

`compare` walks both trees and reports every output file that differs
(source files, *.py, *.sh, *.md and tests/, are left out: those are what
changed on purpose). Text files
that differ only in timestamps are compared again with the timestamps masked
and every number rounded to 12 significant figures, and reported separately.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_AT = "2026-10-17 06:00"

# The competitions update.json builds, by uniqueTournament id, with the
# window and the flags each one is built with there.
FOOTBALL = (17, 18, 8, 23, 35, 34, 242, 325)
FOOTBALL_FLAGS = dict(games=38, players=True, h2h=True, adjust=True,
                      tiers=True, referee=True)
GROUPS = (
    # (name, tournament ids or sport slug, days ahead, flags, out_name)
    ("football", FOOTBALL, 4, FOOTBALL_FLAGS, None),
    ("champions league", (7,), 3, FOOTBALL_FLAGS, None),
    ("europa league", (679,), 3, FOOTBALL_FLAGS, None),
    ("nfl", (9464,), 7, dict(games=20, players=True, adjust=True, h2h=True), None),
    ("mlb", (11205,), 3, dict(games=20, players=True, adjust=True, h2h=True), None),
    ("nba", (132,), 2, dict(games=20, players=True, adjust=True, h2h=True), None),
    ("darts", "darts", 3, dict(games=20, h2h=True), "darts"),
)

# update.py's steps, then publish.sh's, minus everything that fetches prices,
# commits or pushes. Each is (label, argv after the interpreter).
STEPS = (
    ("bettrack settle", ["bettrack.py", "settle"]),
    ("besttrack settle", ["besttrack.py", "settle"]),
    ("linelog settle", ["linelog.py", "settle"]),
    ("reports (run.py build)", ["replay_build.py", "_reports"]),
    ("rerender", ["rerender.py"]),
    ("make_index --prune", ["make_index.py", "--prune"]),
    ("team_news", ["team_news.py"]),
    ("fmodel_live", ["fmodel_live.py"]),
    ("usmodel_live", ["usmodel_live.py"]),
    ("markets_sidecar", ["markets_sidecar.py"]),
    ("pplog settle", ["pplog.py", "settle"]),
    ("pplog snapshot", ["pplog.py", "snapshot"]),
    ("teamlog settle", ["teamlog.py", "settle"]),
    ("teamlog snapshot", ["teamlog.py", "snapshot"]),
    ("pplog page", ["pplog.py", "page"]),
    ("make_index", ["make_index.py"]),
    ("exchange_eval page", ["exchange_eval.py", "page"]),
    ("tonight --hours 8", ["tonight.py", "--hours", "8"]),
    ("besttrack snapshot", ["besttrack.py", "snapshot"]),
    ("linelog snapshot", ["linelog.py", "snapshot"]),
    ("bets_page", ["bets_page.py"]),
)


def _at(text: str) -> float:
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(
        tzinfo=timezone.utc).timestamp()


# ------------------------------------------------------------ inside a step

def install_cache_only() -> None:
    """Answer every SofaScore request from cache/, ignoring age, never fetching."""
    import sofascore_api as api

    def cache_only(path, max_age_hours=None, verbose=True):
        cache_file = api._cache_file(path)
        try:
            return json.loads(cache_file.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    api.get_json = cache_only


def cached_events() -> dict[int, dict]:
    import sofascore_api as api
    found: dict[int, dict] = {}
    for path in sorted(api.CACHE_DIR.glob("team_*_events_last_*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for event in data.get("events") or []:
            if event.get("id") is not None:
                found.setdefault(event["id"], event)
    return found


def as_upcoming(event: dict) -> dict:
    event = json.loads(json.dumps(event))
    event["status"] = {"code": 0, "description": "Not started", "type": "notstarted"}
    for key in ("homeScore", "awayScore", "winnerCode"):
        event.pop(key, None)
    return event


def build_reports(at: float) -> None:
    import run

    events = cached_events()
    built = 0
    for name, which, days, flags, out_name in GROUPS:
        until = at + days * 86400
        chosen = []
        for event in events.values():
            start = event.get("startTimestamp") or 0
            if not at <= start <= until:
                continue
            tournament = event.get("tournament") or {}
            unique = (tournament.get("uniqueTournament") or {}).get("id")
            sport = ((tournament.get("category") or {}).get("sport") or {}).get("slug")
            if which == "darts":
                if sport != "darts" or any(
                        w in (tournament.get("name") or "").lower() for w in run.DARTS_SKIP):
                    continue
            elif unique not in which:
                continue
            chosen.append(as_upcoming(event))
        chosen.sort(key=lambda e: (e.get("startTimestamp") or 0, e["id"]))
        if not chosen:
            print(f"replay: no {name} fixtures in the window")
            continue
        if which is FOOTBALL:
            # --leagues builds one report per division.
            by_comp: dict[int, list] = {}
            for event in chosen:
                unique = event["tournament"]["uniqueTournament"]["id"]
                by_comp.setdefault(unique, []).append(event)
            batches = [by_comp[k] for k in which if k in by_comp]
        else:
            batches = [chosen]
        for batch in batches:
            print(f"replay: {name}, {len(batch)} fixture(s)")
            run.build(batch, flags.get("games", 10), False, flags.get("players", False),
                      flags.get("h2h", False), flags.get("adjust", False), False,
                      flags.get("tiers", False), False, flags.get("referee", False),
                      out_name=out_name)
            built += 1
    print(f"replay: {built} report(s) built")


def exec_step(argv: list[str]) -> None:
    """Run one of the build's scripts with the network cut off at the source."""
    out = os.environ.get("REPLAY_PROFILE")
    if out:
        import cProfile
        profiler = cProfile.Profile()
        try:
            profiler.runcall(_exec_step, argv)
        finally:
            profiler.dump_stats(out)
        return
    _exec_step(argv)


def _exec_step(argv: list[str]) -> None:
    sys.path.insert(0, str(Path.cwd()))
    install_cache_only()
    if argv[:2] == ["replay_build.py", "_reports"]:
        build_reports(float(os.environ["REPLAY_AT"]))
        return
    sys.argv = list(argv)
    try:
        runpy.run_path(argv[0], run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


# ------------------------------------------------------------- the driver

def faketime_lib() -> str | None:
    try:
        import libfaketime
    except ImportError:
        return None
    for path in Path(libfaketime.__file__).parent.rglob("libfaketime.so.1"):
        return str(path)
    return None


def run_all(workdir: Path, at_text: str, profile: bool = False) -> None:
    workdir = workdir.resolve()
    cache = workdir / "cache"
    if not cache.exists():
        cache.symlink_to(HERE / "cache")
    shutil.copy2(HERE / "replay_build.py", workdir / "replay_build.py")
    # Price fetchers stay off even if something calls them.
    for flag in (".paddypower_off", ".bet365_off"):
        (workdir / flag).touch()

    at = _at(at_text)
    env = dict(os.environ)
    env.update({
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "TZ": "UTC",
        "REPLAY_AT": str(at),
        "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",
        "http_proxy": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9",
        "NO_PROXY": "", "no_proxy": "",
        "SOFA_DELAY_MIN": "0", "SOFA_DELAY_MAX": "0",
    })
    lib = faketime_lib()
    if lib:
        env["LD_PRELOAD"] = lib
        env["FAKETIME"] = "@" + datetime.fromtimestamp(at, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S")
        env["FAKETIME_DONT_FAKE_MONOTONIC"] = "1"
    else:
        print("libfaketime not installed: the clock is real, so time-dependent "
              "output will differ between runs")

    logs = workdir / "_replay"
    logs.mkdir(exist_ok=True)
    timings = []
    total = time.perf_counter()
    for label, argv in STEPS:
        slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
        if profile:
            env["REPLAY_PROFILE"] = str(logs / f"{slug}.prof")
        started = time.perf_counter()
        with open(logs / f"{slug}.log", "w") as log:
            code = subprocess.call(
                [sys.executable, str(workdir / "replay_build.py"), "_exec", *argv],
                cwd=workdir, env=env, stdout=log, stderr=subprocess.STDOUT)
        took = time.perf_counter() - started
        timings.append({"step": label, "seconds": round(took, 2), "exit": code})
        print(f"  {took:8.2f}s  {'ok ' if code == 0 else f'exit {code}'}  {label}",
              flush=True)
    total = time.perf_counter() - total
    print(f"  {total:8.2f}s  total")
    (logs / "timings.json").write_text(json.dumps(
        {"at": at_text, "total": round(total, 2), "steps": timings}, indent=1))


# ------------------------------------------------------------ the compare

SKIP_PARTS = {"cache", "_replay", "__pycache__", ".git", "tests"}
# Source, not output: the two trees are expected to differ here.
SKIP_SUFFIXES = {".py", ".sh", ".md", ".ipynb"}
STAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2}| ?UTC)?"
    r"|\b\d{1,2}:\d{2}(:\d{2})? ?UTC\b"
    r"|\b1[78]\d{8}(\.\d+)?\b")
NUMBER = re.compile(r"-?\d+\.\d+(e[-+]?\d+)?")


def _files(root: Path) -> dict[str, Path]:
    out = {}
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if (path.is_file() and not path.is_symlink() and not (set(rel.parts) & SKIP_PARTS)
                and path.suffix not in SKIP_SUFFIXES and ".bak-" not in path.name):
            out[str(rel)] = path
    return out


def _loose(text: str) -> str:
    text = STAMP.sub("<time>", text)
    return NUMBER.sub(lambda m: f"{float(m.group(0)):.12g}", text)


def compare(before: Path, after: Path) -> int:
    a, b = _files(before), _files(after)
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    same = loose = 0
    differ = []
    for rel in sorted(set(a) & set(b)):
        x, y = a[rel].read_bytes(), b[rel].read_bytes()
        if x == y:
            same += 1
            continue
        try:
            if _loose(x.decode()) == _loose(y.decode()):
                loose += 1
                print(f"  same once timestamps are masked: {rel}")
                continue
        except UnicodeDecodeError:
            pass
        differ.append(rel)
    print(f"{same} file(s) identical byte for byte")
    print(f"{loose} file(s) identical once timestamps are masked")
    for rel in only_a:
        print(f"  only in {before.name}: {rel}")
    for rel in only_b:
        print(f"  only in {after.name}: {rel}")
    for rel in differ:
        print(f"  DIFFERS: {rel}")
    return 1 if (differ or only_a or only_b) else 0


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "_exec":
        exec_step(sys.argv[2:])
        return
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("workdir", type=Path)
    r.add_argument("--at", default=DEFAULT_AT, help="UTC, YYYY-MM-DD HH:MM")
    r.add_argument("--profile", action="store_true",
                   help="also write a cProfile of each step to WORKDIR/_replay")
    c = sub.add_parser("compare")
    c.add_argument("before", type=Path)
    c.add_argument("after", type=Path)
    args = ap.parse_args()
    if args.cmd == "run":
        run_all(args.workdir, args.at, args.profile)
    else:
        raise SystemExit(compare(args.before, args.after))


if __name__ == "__main__":
    main()
