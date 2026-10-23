"""
The last word before anything is published: is this site fit to go live?

    python site_guard.py snapshot          # keep a copy of every good page
    python site_guard.py vet               # check reports/, put back bad ones
    python site_guard.py gate STAGE_DIR    # check exactly what is about to be pushed

update.py and publish.sh call these; nothing here touches the network, and
nothing here changes a number on any page. It only decides whether a page is
whole enough to replace the one already live.

Why it exists. publish.sh force-pushes the whole site as one commit, so
whatever is on disk at that moment becomes the site. A league whose fetch came
back empty, a report cut off half way through being written, or an index that
lists nothing all look like a quiet day from the outside, and you would bet off
them. The rule this file enforces is simple: a page that fails a check never
replaces the one that is live. The publish stops, the reason is said in one
line, and yesterday's page stays where it was, both on the site (nothing is
pushed) and on disk (the last good copy is put back), so tomorrow's run cannot
pick the broken one up by accident either.

The checks are about shape, never about content: does the page end, does its
data parse, does it hold fixtures with the fields every other script reads,
does it hold any statistics at all. A page that passes can still be wrong, but
one that fails is certainly broken.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import time
from pathlib import Path

import pagedata

ROOT = Path(__file__).parent
REPORTS = ROOT / "reports"
# The most recent copy of each page that passed every check. Taken at the
# start of each run, so it holds what was live after the last good publish.
LAST_GOOD = ROOT / ".last_good"
# Where a broken page goes when there is no good copy to put back. Moved
# rather than deleted, so whatever broke it can still be looked at.
REJECTED = ROOT / ".rejected"

# Exit code run.py uses for "the fetch failed", as opposed to "nothing on".
# update.py treats it as fatal even in the steps that are otherwise optional.
BAD_FETCH = 3

# A real report inlines its own CSS and JavaScript and runs to hundreds of
# kilobytes before any data. Anything this small is a stub or a truncation.
MIN_REPORT_BYTES = 20_000
MIN_INDEX_BYTES = 5_000

# A round with at least this many fixtures, most of them missing one team's
# record entirely, is a fetch that died part way. A single one-sided fixture
# is allowed: a club's first ever game in a competition has no record in it.
ONE_SIDED_MIN_FIXTURES = 4

# A freshly built report whose every fixture kicked off longer ago than this
# was built from a stale cache: the "next fixtures" it read were last week's.
STALE_AFTER_HOURS = 6

# pagedata's two str.find calls, not the lazy regex: they return the same
# payload, and the regex costs about half a second per report, which this file
# would pay several times a run over every report (code-health, PAGEDATA).
REPORT_PAYLOAD = pagedata.PAYLOAD
INDEX_PAYLOAD = re.compile(r"const DATA = (\{.*?\});\n", re.S)

REQUIRED_FIXTURE_FIELDS = ("id", "home", "away", "kickoff")


def atomic_write(path: Path, text: str) -> None:
    """Write a page so that it is either the old file or the new one, whole.

    write_text truncates first and then writes, so a run killed part way (a
    crash, a full disk, the Mac going to sleep under launchd) leaves a page
    cut off in the middle that every later step reads as real. Writing beside
    it and renaming over it means a failure leaves yesterday's page untouched.
    """
    import os
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _ends(text: str) -> bool:
    return text.rstrip().lower().endswith("</html>")


def report_payload(path: Path) -> tuple[dict | None, str | None]:
    """The data inside a report, or None and the reason it cannot be read."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "file is missing"
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"cannot be read ({type(exc).__name__})"
    if not text.strip():
        return None, "file is empty"
    if len(text.encode("utf-8")) < MIN_REPORT_BYTES:
        return None, f"only {len(text)} bytes, a real report is far larger"
    if not _ends(text):
        return None, "does not end in </html>, the write was cut off"
    match = REPORT_PAYLOAD.search(text)
    if not match:
        return None, "has no data payload"
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        return None, f"data payload does not parse ({exc.msg})"
    if not isinstance(data, dict):
        return None, "data payload is not an object"
    return data, None


def report_problems(path: Path, now: float | None = None,
                    fresh: bool = False) -> list[str]:
    """Everything wrong with one report. An empty list means fit to publish.

    fresh says the report was written by this run, which adds the staleness
    check: a page built today whose games all finished long ago was built from
    an old fixture list.
    """
    data, why = report_payload(path)
    if data is None:
        return [why]

    fixtures = data.get("fixtures")
    if not isinstance(fixtures, list):
        return ["has no fixtures list"]
    if not fixtures:
        return ["holds zero fixtures"]

    problems: list[str] = []
    with_data = one_sided = 0
    for i, entry in enumerate(fixtures):
        fixture = entry.get("fixture") if isinstance(entry, dict) else None
        if not isinstance(fixture, dict):
            problems.append(f"fixture {i} has no fixture block")
            continue
        missing = [k for k in REQUIRED_FIXTURE_FIELDS if not fixture.get(k)]
        if missing:
            name = f"{fixture.get('home', '?')} v {fixture.get('away', '?')}"
            problems.append(f"fixture {i} ({name}) is missing {', '.join(missing)}")
            continue
        if not isinstance(fixture["kickoff"], (int, float)):
            problems.append(f"fixture {i} has a kick-off that is not a timestamp")
            continue
        records = entry.get("records")
        if not isinstance(records, list) or len(records) != 2 \
                or not all(isinstance(r, list) for r in records):
            problems.append(f"fixture {i} ({fixture['home']} v {fixture['away']}) "
                            "has no home and away records")
            continue
        if any(records):
            with_data += 1
        # Darts and the Nations League draw form from every competition and
        # often meet a player or side with no record at all, so a one-sided
        # fixture there is normal and is not counted.
        if not all(records) and not fixture.get("crossLeague"):
            one_sided += 1
    if problems:
        return problems

    if not with_data:
        return [f"none of its {len(fixtures)} fixture(s) has any statistics"]
    if len(fixtures) >= ONE_SIDED_MIN_FIXTURES and one_sided * 2 > len(fixtures):
        return [f"{one_sided} of {len(fixtures)} fixtures are missing one team's "
                "record, the fetch died part way"]

    if fresh:
        now = time.time() if now is None else now
        latest = max(entry["fixture"]["kickoff"] for entry in fixtures)
        if latest < now - STALE_AFTER_HOURS * 3600:
            return ["built this run, yet every fixture in it kicked off more than "
                    f"{STALE_AFTER_HOURS} hours ago: the fixture list came from a "
                    "stale cache"]
    return []


def index_problems(path: Path, reports_dir: Path) -> list[str]:
    """Everything wrong with the front page and the links on it."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ["index.html is missing"]
    except (OSError, UnicodeDecodeError) as exc:
        return [f"index.html cannot be read ({type(exc).__name__})"]
    if len(text.encode("utf-8")) < MIN_INDEX_BYTES:
        return [f"index.html is only {len(text)} bytes"]
    if not _ends(text):
        return ["index.html does not end in </html>, the write was cut off"]
    if "__PAYLOAD__" in text:
        return ["index.html still holds its template placeholder"]
    match = INDEX_PAYLOAD.search(text)
    if not match:
        return ["index.html has no data payload"]
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        return [f"index.html data does not parse ({exc.msg})"]
    fixtures = data.get("fixtures") if isinstance(data, dict) else None
    if not isinstance(fixtures, list):
        return ["index.html has no fixtures list"]
    if not fixtures:
        return ["index.html lists zero fixtures"]

    linked = sorted({f.get("report") for f in fixtures if isinstance(f, dict)} - {None})
    missing = [name for name in linked if not (reports_dir / name).exists()]
    if missing:
        return [f"index.html links to {len(missing)} report(s) that are not there: "
                + ", ".join(missing[:5])]
    return []


def page_problems(path: Path, name: str) -> list[str]:
    """The small pages: optional, but if present they must be whole."""
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{name} cannot be read ({type(exc).__name__})"]
    if not text.strip():
        return [f"{name} is empty"]
    if not _ends(text):
        return [f"{name} does not end in </html>, the write was cut off"]
    return []


def _report_files(reports_dir: Path) -> list[Path]:
    # Picker pages share the folder but are not fixture reports. make_index
    # skips the same names.
    return [p for p in sorted(reports_dir.glob("*.html"))
            if not p.name.startswith(("pick-", "_"))]


def snapshot(reports_dir: Path | None = None, keep: Path | None = None,
             root: Path | None = None) -> int:
    """Copy every page that passes today's checks into the last-good store.

    A page that fails is not copied, so a broken file can never become the
    thing a later run falls back to.
    """
    reports_dir, keep, root = reports_dir or REPORTS, keep or LAST_GOOD, root or ROOT
    (keep / "reports").mkdir(parents=True, exist_ok=True)
    kept = 0
    if reports_dir.exists():
        for path in _report_files(reports_dir):
            if not report_problems(path):
                shutil.copy2(path, keep / "reports" / path.name)
                kept += 1
    index = root / "index.html"
    if index.exists() and not index_problems(index, reports_dir):
        shutil.copy2(index, keep / "index.html")
    return kept


def restore(name: str, reports_dir: Path | None = None, keep: Path | None = None,
            rejected: Path | None = None) -> str:
    """Put yesterday's copy of one report back, or move the broken one aside.

    Returns what was done, for the message.
    """
    reports_dir, keep = reports_dir or REPORTS, keep or LAST_GOOD
    rejected = rejected or REJECTED
    bad = reports_dir / name
    if bad.exists():
        rejected.mkdir(parents=True, exist_ok=True)
        shutil.move(str(bad), str(rejected / name))
    good = keep / "reports" / name
    if good.exists():
        shutil.copy2(good, bad)
        return "yesterday's copy put back"
    return "no earlier copy, left out"


def restore_index(root: Path | None = None, keep: Path | None = None) -> bool:
    root, keep = root or ROOT, keep or LAST_GOOD
    good = keep / "index.html"
    if good.exists():
        shutil.copy2(good, root / "index.html")
        return True
    return False


def vet(reports_dir: Path | None = None, keep: Path | None = None,
        rejected: Path | None = None, since: float | None = None,
        now: float | None = None) -> list[str]:
    """Check every report; put back the last good copy of any that fail.

    since is when this run started: a report written after it counts as
    fresh, which adds the stale-cache check. Returns one line per bad report,
    empty when everything is fit to publish.
    """
    reports_dir = reports_dir or REPORTS
    if not reports_dir.exists():
        return ["there is no reports/ folder"]
    files = _report_files(reports_dir)
    if not files:
        return ["reports/ holds no reports"]
    out = []
    for path in files:
        fresh = since is not None and path.stat().st_mtime >= since
        problems = report_problems(path, now=now, fresh=fresh)
        if problems:
            done = restore(path.name, reports_dir, keep, rejected)
            out.append(f"{path.name}: {problems[0]} ({done})")
    return out


def gate(site: Path, root: Path | None = None, keep: Path | None = None,
         rejected: Path | None = None) -> list[str]:
    """Check the staged site exactly as it would be pushed.

    Run by publish.sh after every page is built and copied, so it also covers
    the scripts that rewrite reports inside publish.sh itself. Any bad report
    is also put back to its last good copy in the working folder, so the next
    publish does not stage it again.
    """
    root = root or ROOT
    problems = []
    reports = site / "reports"
    files = _report_files(reports) if reports.exists() else []
    if not files:
        problems.append("the staged site holds no reports")
    for path in files:
        bad = report_problems(path)
        if bad:
            done = restore(path.name, root / "reports", keep, rejected)
            problems.append(f"{path.name}: {bad[0]} ({done})")
    problems += index_problems(site / "index.html", reports)
    for name in ("tonight.html", "best-bets-summary.html",
                 "market-check.html", "pp-results.html"):
        problems += page_problems(site / name, name)
    return problems


def _say_and_exit(problems: list[str], what: str) -> None:
    if not problems:
        print(f"site guard: {what} passed")
        return
    print(f"site guard: {what} FAILED, nothing will be published and the live "
          "site keeps yesterday's pages:", file=sys.stderr)
    for line in problems:
        print(f"  {line}", file=sys.stderr)
    raise SystemExit(1)


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in ("snapshot", "vet", "gate"):
        raise SystemExit("usage: site_guard.py snapshot | vet | gate STAGE_DIR")
    command = argv[0]
    if command == "snapshot":
        print(f"site guard: kept a good copy of {snapshot()} report(s)")
    elif command == "vet":
        _say_and_exit(vet(), "report check")
    else:
        if len(argv) < 2:
            raise SystemExit("usage: site_guard.py gate STAGE_DIR")
        _say_and_exit(gate(Path(argv[1])), "publish gate")


if __name__ == "__main__":
    main()
