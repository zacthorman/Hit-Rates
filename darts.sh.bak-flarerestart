#!/usr/bin/env bash
#
# Build the darts page: every PDC match in the next few days, one report.
#
#     ./darts.sh          # next 3 days
#     ./darts.sh 7        # next 7 days
#
# Same shape as nfl_fit.sh. Start it whenever and walk away: it waits for
# update.py's lock to clear before touching the network.
#
# Darts has no league table, so this asks a seed list of PDC players for their next matches instead of
# --league, and each player's form is drawn from every competition he has
# played in (Players Championships, Euro Tour, majors). Modus, WDF, Challenge
# and Development Tour and the Women's Series are skipped by name, see
# DARTS_SKIP in run.py.
#
# What it costs: one request per day of schedule, then about 20 per player for
# a first build. A Players Championship day is 64 players, so the first run of
# a floor event is the expensive one. After that it is mostly cache.
#
# It writes reports/darts.html and rebuilds the index. It does not publish.
# Look at it first, then: ./publish.sh

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

DAYS="${1:-3}"
PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"

export SOFA_DELAY_MIN=5
export SOFA_DELAY_MAX=10

# Every request goes through FlareSolverr, same as the nightly job (the plist
# sets this for launchd; a run from Terminal does not inherit it). Override
# with SOFA_FLARESOLVERR=http://host:port/v1 if the container lives elsewhere.
export SOFA_FLARESOLVERR="${SOFA_FLARESOLVERR:-1}"
FLARE_URL="$SOFA_FLARESOLVERR"
case "$FLARE_URL" in 1|true|yes) FLARE_URL="http://localhost:8191/v1" ;; esac

say() { echo "$(date '+%H:%M:%S')  $*"; }

# Check it is actually up before waiting on the lock or touching SofaScore.
# Without this the first request dies on a refused connection and the run
# reports it as a network fault, which it is not.
if ! curl -s -m 10 -o /dev/null "${FLARE_URL%/v1}/"; then
  say "FlareSolverr is not answering at ${FLARE_URL%/v1}."
  say "Start Docker Desktop and the flaresolverr container, then run this again."
  exit 1
fi
say "FlareSolverr is up at ${FLARE_URL%/v1}"

waited=0
while [ -f .update.lock ]; do
  if [ "$waited" -eq 0 ]; then
    say "the football job is still running, waiting for it to finish"
  fi
  sleep 300
  waited=$((waited + 300))
  if [ "$waited" -ge 43200 ]; then
    say "twelve hours and the lock is still there. Giving up rather than"
    say "assuming it is stale. Check whether update.py is actually running."
    exit 1
  fi
done
[ "$waited" -gt 0 ] && say "lock cleared after $((waited / 60)) minutes"

say "building darts for the next ${DAYS} day(s), pacing ${SOFA_DELAY_MIN}-${SOFA_DELAY_MAX}s"

# Deliberately no curl_cffi fallback: if FlareSolverr drops mid-run the
# circuit breaker stops the build rather than hammering SofaScore direct.
RUN=("$PY" run.py --darts "$DAYS" --games 20 --h2h --no-open)
if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -i "${RUN[@]}"
else
  "${RUN[@]}"
fi
status=$?

if [ $status -ne 0 ]; then
  say "the build failed (exit $status). Nothing has been indexed or published."
  say "No PDC darts in the window is also a non-zero exit; try ./darts.sh 7."
  exit $status
fi

say "building the index"
"$PY" make_index.py || exit $?

say "done. Nothing is published yet. Check reports/darts.html, then: ./publish.sh"
