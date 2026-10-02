#!/usr/bin/env python3
"""One request to Oddschecker through FlareSolverr. Does it get through?

    .venv/bin/python oddschecker_probe.py
    .venv/bin/python oddschecker_probe.py https://www.oddschecker.com/football/english/premier-league

One page, no retries, no loop. Same rule as canary.py: if it says no, leave it
alone for a few hours rather than trying again, because repeated refusals are
how a block gets longer. Nothing is cached or saved.
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request

URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.oddschecker.com/american-football/nfl"
FLARE = "http://localhost:8191/v1"


def call(payload, timeout):
    req = urllib.request.Request(FLARE, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def main() -> int:
    try:
        call({"cmd": "sessions.list"}, 10)
    except Exception as exc:
        print(f"FlareSolverr not answering at {FLARE} ({type(exc).__name__}). Start Docker first.")
        return 2

    print(f"fetching {URL}")
    started = time.time()
    try:
        out = call({"cmd": "request.get", "url": URL, "maxTimeout": 60000}, 90)
    except urllib.error.HTTPError as exc:
        # FlareSolverr answers 500 when it could not get through, with the
        # reason in the body. That reason is the whole point of the test.
        try:
            reason = json.loads(exc.read().decode()).get("message", "")
        except Exception:
            reason = ""
        print(f"  flaresolverr: HTTP {exc.code} after {time.time() - started:.1f}s")
        print(f"  reason:       {reason or '(none given)'}")
        print("\nBLOCKED: FlareSolverr could not get past Oddschecker's protection."
              "\nLeave it alone for a few hours rather than retrying.")
        return 1
    except (TimeoutError, OSError) as exc:
        print(f"  flaresolverr: no answer after {time.time() - started:.0f}s ({type(exc).__name__})")
        print("\nBLOCKED: FlareSolverr was still stuck on the challenge when the time ran out.")
        return 1
    took = time.time() - started
    sol = out.get("solution") or {}
    body = sol.get("response") or ""
    status = sol.get("status")
    title = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
    title = title.group(1).strip() if title else "(none)"

    print(f"  flaresolverr: {out.get('status')}  {out.get('message', '')}")
    print(f"  http status:  {status}   {len(body):,} bytes   {took:.1f}s")
    print(f"  page title:   {title[:100]}")

    lower = body.lower()
    blocked = [m for m in ("just a moment", "cf-challenge", "captcha", "access denied",
                           "attention required", "verify you are human") if m in lower]
    # Oddschecker marks each price with data-odig (decimal) on its odds grid.
    prices = re.findall(r'data-odig="([\d.]+)"', body)
    books = sorted(set(re.findall(r'data-bk="([A-Z0-9]+)"', body)))
    links = len(re.findall(r'href="/american-football/[^"]+/(?:winner|[a-z-]+)"', body))

    if blocked:
        print(f"\nBLOCKED: page contains {', '.join(blocked)}. FlareSolverr did not get through.")
        return 1
    if out.get("status") != "ok" or (status and status >= 400):
        print("\nRefused. Leave it a few hours before trying again.")
        return 1
    print(f"\n  prices on page:   {len(prices)}" + (f"  e.g. {', '.join(prices[:6])}" if prices else ""))
    print(f"  bookmaker codes:  {', '.join(books) or 'none found'}")
    print(f"  match links:      {links}")
    if prices:
        print("\nGOT THROUGH, with prices. Next: one match page, to see if player props are there.")
    else:
        print("\nGot a page but no price grid. Might be a listing page (try a match URL),"
              "\nor the prices load by script after the page and need a different approach.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
