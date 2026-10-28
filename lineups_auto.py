#!/usr/bin/env python3
"""Pull confirmed line-ups about an hour before kick-off, then publish.

Run by launchd every 15 minutes (com.zacthorman.lineups.plist). Almost every
run does nothing: it only acts when a big-league fixture kicks off in the next
20 to 80 minutes and its confirmed XI is not in the report yet. Once a fixture
has its confirmed line-up it is never fetched again.

Big games only: the leagues in update.json plus the Nations League, the NFL
(inactives) and MLB (batting orders and starting pitchers). Darts has no
line-up to pull, so darts.html is skipped. A run never overlaps the nightly
build, and never publishes unless something actually changed.
"""
from __future__ import annotations

import glob
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
import pagedata

ROOT = Path(__file__).parent
LOG = ROOT / "lineups_auto.log"
SKIP = {"darts.html"}
WINDOW = (5 * 60, 80 * 60)
# NFL inactives are announced 90 minutes before kick-off.
NFL_WINDOW = (15 * 60, 95 * 60)
# MLB batting orders and the starting pitcher are posted anywhere from about
# four hours to one hour before first pitch, so the window opens early and
# the 15-minute retry catches it whenever it lands.
MLB_WINDOW = (15 * 60, 240 * 60)


def window(entry):
    sport = entry["fixture"].get("sport") or "football"
    if sport == "american-football":
        return NFL_WINDOW
    if sport == "baseball":
        return MLB_WINDOW
    return WINDOW


def say(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def due():
    """{report path: payload} for reports with a fixture needing its XI now."""
    now = time.time()
    out = {}
    for f in sorted(glob.glob(str(ROOT / "reports" / "*.html"))):
        name = Path(f).name
        if name.startswith("pick-") or name in SKIP:
            continue
        text = Path(f).read_text(encoding="utf-8")
        m = pagedata.search(text)
        if not m:
            continue
        payload = json.loads(m.group(1))
        for entry in payload.get("fixtures", []):
            ko = entry["fixture"].get("kickoff") or 0
            w = window(entry)
            if w[0] < ko - now < w[1] and not (entry.get("lineups") or {}).get("confirmed"):
                out[Path(f)] = payload
                break
    return out


# ------------------------------------------------------------ prices refresh
# 27 Oct 2026: Paddy Power's lines used to arrive only with the morning build,
# so the evening's NBA list meant running the price fetch by hand. Now, between
# PRICE_HOURS, every PRICE_EVERY hours, if Paddy has games to fetch (not
# locked out, cap not spent), this runs publish.sh: it fetches the next batch
# of games, logs every line, logs and settles the best selections, rebuilds
# tonight.html and pushes the site. Then a Mac notification lists the
# selections that are new since the last one.
PRICE_EVERY = 2.0 * 3600
PRICE_HOURS = (11, 23)          # local hours, start inclusive, end exclusive
PRICE_MARK = ROOT / "cache" / ".prices_refresh"
NOTIFIED = ROOT / "selections" / "notified.json"


def prices_due() -> bool:
    if not (PRICE_HOURS[0] <= datetime.now().hour < PRICE_HOURS[1]):
        return False
    if PRICE_MARK.exists() and time.time() - PRICE_MARK.stat().st_mtime < PRICE_EVERY:
        return False
    try:
        import paddypower_prices as pp
        st = pp.load_state()
        if pp.blocked(st):
            return False
        left = pp.MAX_PER_DAY - pp.count_today(st)
        todo = pp.candidates(st)
        far = [c for c in todo if c[0] - time.time() >= 3 * 3600]
        close = [c for c in todo if c[0] - time.time() < 3 * 3600]
        return bool(close and left > 0) or bool(far and left > pp.RESERVE_CLOSE)
    except Exception as exc:  # noqa: BLE001
        say(f"prices check failed ({type(exc).__name__}: {exc})")
        return False


def notify_selections() -> None:
    """A Mac notification for best selections not announced before."""
    try:
        import selections
        picks = selections.tonight()
        seen = set(json.loads(NOTIFIED.read_text())) if NOTIFIED.exists() else set()
        new = [p for p in picks if selections._key(p) not in seen]
        if not new:
            return
        lines = [f"{p['player']} {p['label'].lower()} {p['stat'].lower()} @ {p['_price']:.2f}" for p in new[:4]]
        more = f" (+{len(new) - 4} more)" if len(new) > 4 else ""
        body = "; ".join(lines) + more
        title = f"{len(new)} new best selection{'s' if len(new) != 1 else ''}"
        subprocess.run(["osascript", "-e", f'display notification {json.dumps(body)} with title {json.dumps(title)} sound name "Glass"'],
                       capture_output=True, timeout=20)
        NOTIFIED.parent.mkdir(exist_ok=True)
        NOTIFIED.write_text(json.dumps(sorted(seen | {selections._key(p) for p in picks})))
        say(f"notified: {title}: {body}")
    except Exception as exc:  # noqa: BLE001
        say(f"selection notification failed ({type(exc).__name__}: {exc})")


def refresh_prices() -> None:
    PRICE_MARK.parent.mkdir(exist_ok=True)
    PRICE_MARK.touch()
    say("prices refresh: fetching Paddy Power and publishing")
    r = subprocess.run(["./publish.sh"], cwd=ROOT, capture_output=True, text=True)
    say("prices refresh published" if r.returncode == 0 else f"prices refresh publish failed: {r.stderr[-300:]}")
    notify_selections()


def main() -> None:
    if (ROOT / ".update.lock").exists():
        return                      # the nightly build is running; next tick
    todo = due()
    if not todo:
        if prices_due():
            refresh_prices()
        else:
            notify_selections()     # e.g. after the morning build published
        return
    import update                   # for the FlareSolverr health check
    update.say = say
    if not update.ensure_flaresolverr():
        say("FlareSolverr not healthy, line-ups skipped this time")
        return
    import lineup_data
    import report
    now = time.time()
    changed = 0
    for path, payload in todo.items():
        got = []
        for entry in payload["fixtures"]:
            ko = entry["fixture"].get("kickoff") or 0
            w = window(entry)
            if w[0] < ko - now < w[1] and not (entry.get("lineups") or {}).get("confirmed"):
                lineup_data.attach(entry, max_age_hours=0.05)
                if (entry["fixture"].get("sport") or "") == "american-football":
                    # Inactives can change who starts at QB; recompute.
                    try:
                        import nfl_injuries
                        nfl_injuries.attach(entry)
                    except Exception:
                        pass
                try:
                    import team_news   # who is out, from the line-up just fetched
                    team_news.attach(entry)
                except Exception:
                    pass
                if (entry.get("lineups") or {}).get("confirmed"):
                    got.append(f'{entry["fixture"]["home"]} v {entry["fixture"]["away"]}')
        if got:
            report.write_report(payload, path)
            changed += len(got)
            say(f"{path.name}: confirmed XI for {', '.join(got)}")
        else:
            say(f"{path.name}: not confirmed yet, will retry in 5 minutes")
    if changed:
        r = subprocess.run(["./publish.sh"], cwd=ROOT, capture_output=True, text=True)
        say("published" if r.returncode == 0 else f"publish failed: {r.stderr[-300:]}")
        PRICE_MARK.parent.mkdir(exist_ok=True)
        PRICE_MARK.touch()          # that publish fetched prices too
        notify_selections()
    elif prices_due():
        refresh_prices()


if __name__ == "__main__":
    main()
