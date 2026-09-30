#!/usr/bin/env bash
#
# Rebuild whatever last night's job did not, then index and publish.
#
#     ./catchup.sh
#
# The nightly run is all-or-nothing about publishing: if any league fails it
# exits without touching the site, so one bad league leaves everything stale.
# On 15 September four leagues died on DNSError inside the first thirty
# seconds -- the machine had not finished waking up -- and the other four
# built perfectly but never went live.
#
# This builds only the leagues whose report is older than the newest one on
# disk, so it costs a fraction of a full run and can be re-run safely: every
# match already fetched comes off disk.
#
# It waits for the nightly lock, paces itself, and publishes only if every
# league it attempted succeeded.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"

export SOFA_DELAY_MIN=${SOFA_DELAY_MIN:-4}
export SOFA_DELAY_MAX=${SOFA_DELAY_MAX:-8}

say() { echo "$(date '+%H:%M:%S')  $*"; }

waited=0
while [ -f .update.lock ]; do
  [ "$waited" -eq 0 ] && say "the nightly job is running, waiting for it"
  sleep 120; waited=$((waited + 120))
  if [ "$waited" -ge 10800 ]; then
    say "three hours and the lock is still there; check whether update.py is alive"
    exit 1
  fi
done

# Which leagues are behind. A report more than six hours older than the
# freshest one on disk did not get built in the last run.
STALE=$("$PY" - <<'PYEOF'
import json, time
from pathlib import Path

SLUG = {
    "Premier League": "premier-league", "Championship": "championship",
    "La Liga": "laliga", "Serie A": "serie-a", "Bundesliga": "bundesliga",
    "Ligue 1": "ligue-1", "MLS": "mls", "Brasileirao": "brasileirao-betano",
}
leagues = json.load(open("update.json"))["leagues"]
reports = Path("reports")
ages = {}
for name in leagues:
    p = reports / f"{SLUG.get(name, '')}.html"
    ages[name] = p.stat().st_mtime if p.exists() else 0
newest = max(ages.values(), default=0)
behind = [n for n, t in ages.items() if newest - t > 6 * 3600]
print(",".join(behind))
PYEOF
)

if [ -z "$STALE" ]; then
  say "every league is current. Nothing to rebuild."
  say "building the index and publishing anyway, in case the last run died before it could"
else
  say "behind: $STALE"
  IFS=',' read -ra LEAGUES <<< "$STALE"
  for league in "${LEAGUES[@]}"; do
    say "building $league"
    RUN=("$PY" run.py --league "$league" --games 38 --players --adjust --tiers --h2h --no-open)
    if command -v caffeinate >/dev/null 2>&1; then
      caffeinate -i "${RUN[@]}"
    else
      "${RUN[@]}"
    fi
    status=$?
    if [ $status -ne 0 ]; then
      say "$league failed (exit $status). Stopping before anything is published."
      say "If it says it could not reach SofaScore, that is the network, not a ban:"
      say "wait a minute and run ./catchup.sh again -- it will pick up where it left off."
      exit $status
    fi
  done
fi

say "building the index"
"$PY" make_index.py || exit $?

say "publishing"
./publish.sh
