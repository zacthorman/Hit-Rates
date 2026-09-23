#!/usr/bin/env bash
#
# Fit the NFL and build next week's slate, once the football job is out of the way.
#
#     ./nfl_fit.sh
#
# Start it whenever and walk away. It waits for update.py's lock to clear
# before touching the network, because two builds sharing one home connection
# is how a fourteen-hour run turns into a wall of 403s.
#
# What it costs: the opponent-adjusted fit needs every club's season, and only
# a handful are cached, so expect somewhere around an hour of fetching the
# first time. After that the ratings come off disk and every NFL fixture for
# the rest of the season is priced in seconds.
#
# It does not publish. Look at what it built first.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"

# Deliberately slower than the football job. This is an extra build on a day
# that already had one, and the whole point is to be forgettable.
export SOFA_DELAY_MIN=5
export SOFA_DELAY_MAX=10

say() { echo "$(date '+%H:%M:%S')  $*"; }

waited=0
while [ -f .update.lock ]; do
  if [ "$waited" -eq 0 ]; then
    say "the football job is still running, waiting for it to finish"
  fi
  sleep 300
  waited=$((waited + 300))
  if [ "$waited" -ge 43200 ]; then
    say "twelve hours and the lock is still there. Giving up rather than"
    say "assuming it is stale -- check whether update.py is actually running."
    exit 1
  fi
done
[ "$waited" -gt 0 ] && say "lock cleared after $((waited / 60)) minutes"

say "fitting the NFL and building the slate, pacing ${SOFA_DELAY_MIN}-${SOFA_DELAY_MAX}s"

# caffeinate -i: the Mac sleeping mid-run is what makes these finish at
# unpredictable times. -i keeps it awake for idle only, so closing the lid
# still suspends, which is the behaviour you want overnight on a desk.
RUN=("$PY" run.py --league NFL --games 20 --players --adjust --h2h --no-open)
if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -i "${RUN[@]}"
else
  "${RUN[@]}"
fi
status=$?

if [ $status -ne 0 ]; then
  say "the build failed (exit $status). Nothing has been indexed or published."
  say "If it was 403s, wait a few hours rather than retrying now."
  exit $status
fi

say "building the index"
"$PY" make_index.py || exit $?

say "done. Nothing is published yet -- check the report, then: ./publish.sh"
