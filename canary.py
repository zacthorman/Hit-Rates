#!/usr/bin/env python3
"""One request. Is SofaScore answering us or not?

    python canary.py

That is the whole program, and the point is what it does NOT do.

When you are blocked, the instinct is to try the thing you wanted and see.
That thing is twenty requests, and twenty refusals is how a few hours of
cooling off becomes a few days -- a block escalates on repeated failures, so
the checking is itself the damage. check.py probes a list of paths and is the
wrong tool here for exactly that reason.

So: one request, for a fixed cheap endpoint, no retries, no backoff, no
cache. Then it stops and tells you. If it says no, wait longer. Do not run it
in a loop.
"""
import sys, time

PATH = "unique-tournament/17/seasons"      # small, static, uncontroversial


def main() -> int:
    import sofascore_api as api
    session = api._get_session()
    url = f"{api.BASE}/{PATH}" if hasattr(api, "BASE") else \
          f"https://api.sofascore.com/api/v1/{PATH}"
    started = time.time()
    try:
        response = session.get(url, timeout=20)
    except Exception as exc:
        print(f"no answer at all: {type(exc).__name__}: {exc}")
        return 2

    took = time.time() - started
    body = (response.content or b"")
    print(f"  {response.status_code}  {len(body)} bytes  {took:.2f}s  {PATH}")
    print(f"  impersonating: {api.IMPERSONATE}")
    print(f"  cookies held after warm-up: {len(getattr(session, 'cookies', []) or [])}")

    # The body of a refusal names who refused. A Cloudflare challenge is
    # kilobytes of HTML; a short JSON blob is the origin's own rate limiter;
    # a proxy notice is neither. Printing it is the difference between
    # diagnosing this and guessing at it for two days.
    print("  body: " + body[:300].decode("utf-8", "replace").replace("\n", " "))
    for h in ("server", "cf-ray", "cf-mitigated", "retry-after", "via",
              "x-cache", "content-type"):
        v = response.headers.get(h)
        if v:
            print(f"  {h}: {v}")
    if response.status_code == 200:
        print("\nOpen. Start with ONE fixture, not a league:")
        print('  SOFA_DELAY_MIN=8 SOFA_DELAY_MAX=14 .venv/bin/python run.py --teams <id> --players')
        return 0
    if response.status_code in (403, 429):
        print("\nStill refused. Leave it alone -- every attempt while blocked")
        print("makes the block longer. Try again in a few hours, and check")
        print("the scheduled update is not firing in the meantime.")
        return 1
    print("\nSomething else. Not a block, but not a healthy answer either.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
