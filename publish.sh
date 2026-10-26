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

# Betfair Exchange prices for every fixture in the reports, before the
# index and the picks are built, so they blend them in (market_prices.py).
# Optional: without .betfair.env the site runs on the model alone.
if [ -f .betfair.env ]; then
  "$PY" market_prices.py --days 3 >/dev/null && echo "  exchange prices refreshed" \
    || echo "  exchange prices not fetched (continuing with the model alone)"
fi
# Paddy Power's real prices for games in the next 30 hours (paddypower_prices.py).
# Deliberately gentle: 15 to 30 seconds between games, capped per run and per
# day, nothing refetched inside 4 hours, and a 24 hour stop on the first
# refusal. `touch .paddypower_off` switches it off completely.
"$PY" paddypower_prices.py || echo "  paddypower prices not fetched (continuing)"
# Bet365's player prices via Oddschecker (bet365_prices.py), for games whose
# match page was saved with `python bet365_prices.py --add URL`. One batched
# request per game, refetched at most every 4 hours (45 minutes close to
# kick-off), paced and capped per day by oddschecker_client.py. Needs
# FlareSolverr only when the saved cookies have expired. `touch .bet365_off`
# switches it off.
"$PY" bet365_prices.py || echo "  bet365 prices not fetched (continuing)"
# Pinnacle's prices as margin-free chances (pinnacle_prices.py): result,
# goals, team goals, corners and bookings for every game in the site's
# leagues, two requests a league, each league at most every 90 minutes, capped
# at 150 a day, locked out for a day on any refusal. The sharp reference for
# the soft books' lines. `touch .pinnacle_off` switches it off.
"$PY" pinnacle_prices.py || echo "  pinnacle prices not fetched (continuing)"
# The backtested player model (fmodel_live.py): a chance for every starter in
# the predicted or confirmed XI of each football fixture in the next week, at
# 15 lines. Read by the pages and by pplog below. Reads the cache only, no
# requests. Without it the pages fall back to their own chances.
# Team news (team_news.py): who is out in each game in the next 36 hours,
# written into the reports before the models score them. NBA and NFL take
# one SofaScore request a game (cached two hours) and ESPN's injury report
# (cached three hours); football reuses the line-ups already fetched.
"$PY" team_news.py || echo "  team news not refreshed (continuing with what the reports hold)"
"$PY" fmodel_live.py || echo "  fmodel.json not written (continuing with the site's own chances)"
"$PY" usmodel_live.py || echo "  usmodel.json not written (NBA and NFL keep the site's own chances)"
# The same prices for the pages themselves, read in the browser: match odds,
# Betfair's player markets and Paddy Power's (markets_sidecar.py).
"$PY" markets_sidecar.py || echo "  reports/markets.json not written (continuing)"
# The Game state tab on every football report (gamestate_live.py): result and
# goals from the score model, how the game goes, and the lines it backs.
"$PY" gamestate_live.py || echo "  reports/gamestate.json not written (continuing)"
# The Paddy Power record (pplog.py): settle what finished, log every line on
# games not yet started with our chance at it, then the results page.
"$PY" pplog.py settle || echo "  pp log not settled (continuing)"
# The models learn from every settled line (learn.py): fitted on older games,
# used only where it beats the model on the newest unseen ones. LEARNING.md.
"$PY" learn.py fit || echo "  learn: not refitted (continuing)"
"$PY" pplog.py snapshot || echo "  pp log not updated (continuing)"
"$PY" teamlog.py settle || echo "  team log not settled (continuing)"
"$PY" teamlog.py snapshot || echo "  team log not updated (continuing)"
# Each of those Paddy Power lines checked against Betfair's price (sharp.py):
# the soft-v-sharp check the value bots run, written into the same rows.
"$PY" sharp.py stamp || echo "  betfair check not stamped (continuing)"
"$PY" pplog.py page >/dev/null || echo "  pp-results.html not rebuilt (continuing)"
# Fixed rules on trial (ruletrack.py): the record per rule, history v live.
"$PY" ruletrack.py report >/dev/null || echo "  RULES_TRACK.md not rebuilt (continuing)"
# Best selections (selections.py): log tonight's short list before kick-off, settle earlier ones.
"$PY" selections.py log || echo "  selections not logged (continuing)"
"$PY" papertrade.py --page >/dev/null || echo "  papertrade.html not rebuilt (continuing)"
# Score the model against Betfair (exchange_eval.py): settle what finished,
# refit the blend weights from the results, so the picks below use them.
if [ -f .betfair.env ]; then
  "$PY" exchange_eval.py settle || echo "  exchange log not settled (continuing)"
  "$PY" exchange_eval.py fit >/dev/null || echo "  exchange weights not refit (continuing)"
fi
"$PY" make_index.py
# Then log every bet Betfair prices as it stands now, and render the page.
if [ -f .betfair.env ]; then
  "$PY" exchange_eval.py log || echo "  exchange log not updated (continuing)"
fi
"$PY" exchange_eval.py page >/dev/null || echo "  market-check.html not rebuilt (continuing)"

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
# Record the site's best bets as published (pre-kick-off only), then render
# the Best bets summary page that tracks how they actually did.
"$PY" besttrack.py snapshot || echo "  best bets not snapshotted (continuing)"
# And every line the model prices, not just the chosen ones (linelog.py).
"$PY" linelog.py snapshot || echo "  line log not snapshotted (continuing)"
"$PY" bets_page.py || echo "  best-bets-summary.html not rebuilt (continuing)"
if [ -f best-bets-summary.html ]; then cp best-bets-summary.html "$STAGE"/; fi
if [ -f market-check.html ]; then cp market-check.html "$STAGE"/; fi
if [ -f pp-results.html ]; then cp pp-results.html "$STAGE"/; fi
if [ -f papertrade.html ]; then cp papertrade.html "$STAGE"/; fi
cp -R reports "$STAGE"/
# Stops GitHub running the site through Jekyll, which it has no need to do
# and which is the piece that failed during the outage.
touch "$STAGE"/.nojekyll
# A stamp unique to this publish. The live check below fetches it back: a
# page answering 200 only proves SOMETHING is being served, and on 5 October
# GitHub failed two deploys ("job was not acquired by Runner") while the old
# site kept answering 200 and this script reported "verified".
STAMP="$(date -u '+%Y%m%dT%H%M%SZ')-$$"
echo "$STAMP" > "$STAGE"/build.txt

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
CORE_OK=0
verify_round() {
  local failed=0 core=0
  check "${BASE}/" "index" || { failed=1; core=1; }
  check "${BASE}/tonight.html" "tonight.html" || { failed=1; core=1; }
  [ "$core" = "0" ] && CORE_OK=1 || CORE_OK=0
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
    # The site itself is up and only report pages failed: almost always a
    # report with a brand-new filename (SofaScore renamed the Brasileirao,
    # which created campeonato-brasileiro-serie-a.html) that Pages has not
    # finished deploying, or a Pages build queued behind the previous push.
    # The push landed, so this is a warning, not a failed publish.
    if [ "$CORE_OK" = "1" ]; then
      echo
      echo "Pushed. The site is up; some report pages are still deploying."
      echo "They normally appear within a few minutes. Nothing to re-run."
      exit 0
    fi
    echo
    echo "The push succeeded but the site is not serving those pages." >&2
    echo "Pages can lag by a minute; if a retry also fails, check" >&2
    echo "Settings > Pages is set to the gh-pages branch, root folder." >&2
    exit 1
  fi
fi

# Is it THIS publish that is live, or an older one still being served?
fresh() {
  local live
  live="$(curl -s --max-time 20 "${BASE}/build.txt?nocache=$RANDOM" | tr -d '[:space:]')"
  [ "$live" = "$STAMP" ]
}
if ! fresh; then
  echo
  echo "Pages is still serving an older build. Waiting up to 4 minutes for this one..."
  ok=0
  for _ in 1 2 3 4; do
    sleep 60
    if fresh; then ok=1; break; fi
  done
  if [ "$ok" != "1" ]; then
    echo
    echo "GitHub has not deployed this publish. The push landed, but their" >&2
    echo "Pages build failed or is stuck (check the Actions tab). The site is" >&2
    echo "still showing the previous version. Run ./publish.sh again later." >&2
    exit 1
  fi
fi

echo
echo "Live site verified (build ${STAMP})."
