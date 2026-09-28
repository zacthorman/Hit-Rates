#!/usr/bin/env bash
#
# Publish the reports to GitHub Pages without growing the repo.
#
#     ./publish.sh
#
# The problem this solves: a league report is about 3.5 MB, and committing a
# fresh one every gameweek writes 3.5 MB into git history that can never be
# reclaimed. Six leagues across a season is the better part of a gigabyte of
# history, for files that can be regenerated from the cache in seconds.
#
# So the built site does not live in main's history at all. This script
# force-pushes it to a gh-pages branch as a single commit, replacing whatever
# was there. main keeps only source, and stays small forever.
#
# The force-push is deliberate and safe: everything on gh-pages is generated
# output. Never put anything you cannot rebuild on that branch.

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SRC"

if [ ! -d reports ] || [ -z "$(ls -A reports/*.html 2>/dev/null)" ]; then
  echo "No reports to publish. Build some first:"
  echo "  python run.py --league premier_league --adjust"
  exit 1
fi

REMOTE="$(git remote get-url origin)"
echo "Publishing to ${REMOTE}"

# Pick an interpreter rather than assuming "python" exists.
#
# It does in your shell, because the virtualenv is activated. It does not
# under launchd, which gives a job a bare environment with no profile and no
# venv, so a scheduled run died here with "python: command not found" after
# fourteen hours of fetching, having already committed and pushed. Prefer the
# project's own venv, then python3, then python.
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
elif command -v python >/dev/null 2>&1; then
  PY="python"
else
  echo "No Python interpreter found. Tried .venv/bin/python, python3, python." >&2
  exit 1
fi

"$PY" make_index.py

# The small page.
#
# Everything else here is megabytes of report that only a real browser can
# read. tonight.html is about twenty kilobytes of rendered answers, which is
# what makes it usable on a phone on mobile data and readable by anything that
# fetches a URL. It is built last so it sees whatever make_index just did.
"$PY" tonight.py --hours 8 || echo "  tonight.html not rebuilt (continuing)"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

cp index.html "$STAGE"/
# `[ -f x ] && cp x y` is a trap under `set -e`: when the file is missing the
# whole list returns 1 and the script exits, so a page that failed to build
# would silently stop the entire publish.
if [ -f tonight.html ]; then cp tonight.html "$STAGE"/; fi
cp -R reports "$STAGE"/
# Stops GitHub running the site through Jekyll, which it has no need to do
# and which is the piece that failed during the outage.
touch "$STAGE"/.nojekyll

cd "$STAGE"
git init -q
git checkout -q -b gh-pages
git add -A
git -c user.name="publish.sh" -c user.email="publish@local" \
    commit -q -m "Publish $(date -u '+%Y-%m-%d %H:%M UTC')"
git remote add origin "$REMOTE"

# Retry the push.
#
# The build takes hours, the push takes seconds, so losing a whole day to a
# thirty second network blip is the worst trade in this script. On 29 August
# 2026 exactly that happened: the fetch layer rode out a wave of DNS errors
# from 17:50 onwards and finished all eleven reports, then this line died on
# "Could not resolve host: github.com" and the site sat two days stale.
#
# Retrying is safe because this is a force-push of a freshly built branch.
# Repeating it either fails again or lands the same commit.
PUSH_TRIES="${PUSH_TRIES:-5}"
delay=10
attempt=1
until git push -f -q origin gh-pages; do
  if [ "$attempt" -ge "$PUSH_TRIES" ]; then
    echo "Push failed after ${attempt} attempts, giving up." >&2
    exit 1
  fi
  echo "  push failed, retrying in ${delay}s (attempt ${attempt} of ${PUSH_TRIES})"
  sleep "$delay"
  attempt=$((attempt + 1))
  delay=$((delay * 2))
done

COUNT=$(ls reports/*.html | wc -l | tr -d ' ')
SIZE=$(du -sh reports | cut -f1)
echo "Published ${COUNT} report(s), ${SIZE}, to the gh-pages branch."
echo
echo "One-time setup: Settings > Pages > Source: Deploy from a branch"
echo "                Branch: gh-pages   Folder: / (root)"

# Check the site actually serves what was just pushed.
#
# A push can report success while the live pages 404, and the two look
# identical from here. That is how a broken deploy went unnoticed until
# someone else tried to use the site and hit a wall of missing pages: the
# index was advertising report files that were no longer on the branch.
#
# Pages needs a moment to build, so this waits, then asks for the index and a
# couple of the reports it links to. Anything other than a 200 fails the
# script, which means update.py marks the run failed instead of logging
# "done" over a site nobody can read.
if [ "${SKIP_VERIFY:-}" = "1" ]; then
  echo
  echo "SKIP_VERIFY=1, not checking the live site."
  exit 0
fi

BASE="$(echo "$REMOTE" \
  | sed -E 's#(https://|git@)github\.com[:/]([^/]+)/([^/.]+)(\.git)?#https://\2.github.io/\3#')"

if [ "$BASE" = "$REMOTE" ]; then
  echo
  echo "Could not work out the Pages URL from the remote, skipping the check."
  exit 0
fi

echo
echo "Waiting for Pages to rebuild, then checking ${BASE}/"
sleep 45

# A HEAD request, deliberately.
#
# This used to GET the whole page and throw the body away, with a twenty
# second cap. A report is one to twenty megabytes and the site is over a
# hundred, so a page that was serving perfectly well would time out mid-body
# -- and then `|| echo 000` appended three more digits to the status curl had
# already printed, producing "FAIL bundesliga.html (HTTP 200000)". That is a
# 200 with 000 stuck on the end: the page was fine and the check said it was
# broken, in a code that does not exist. Two bugs wearing each other's coat.
#
# A HEAD asks for the status and nothing else, so size stops mattering, and
# the exit status is now read separately from the status line instead of being
# concatenated onto it.
check() {
  local code
  code="$(curl -s -I -o /dev/null -w '%{http_code}' --max-time 20 "$1")" || code="000"
  case "$code" in
    ''|*[!0-9]*) code="000" ;;
  esac
  if [ "$code" = "200" ]; then
    echo "  ok   $2"
    return 0
  fi
  if [ "$code" = "000" ]; then
    echo "  FAIL $2  (no answer: timed out or DNS)"
  else
    echo "  FAIL $2  (HTTP $code)"
  fi
  return 1
}

# The first few reports the index links to. Names come from the staged copy,
# so this checks the files that were actually published.
verify_round() {
  local failed=0
  check "${BASE}/" "index" || failed=1
  check "${BASE}/tonight.html" "tonight.html" || failed=1
  for name in $(ls reports/*.html | head -3 | xargs -n1 basename); do
    check "${BASE}/reports/${name}" "$name" || failed=1
  done
  return "$failed"
}

# Two rounds, because Pages can still be building. One slow deploy is not a
# reason to mark the run failed and leave yesterday's site up.
if ! verify_round; then
  echo
  echo "Not serving yet. Waiting 60s and checking once more."
  sleep 60
  if ! verify_round; then
    echo
    echo "The push succeeded but the site is not serving those pages." >&2
    echo "Pages can lag by a minute; if a retry also fails, check" >&2
    echo "Settings > Pages is set to the gh-pages branch, root folder." >&2
    exit 1
  fi
fi

echo
echo "Live site verified."
