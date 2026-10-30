"""Oddschecker all-odds API client with FlareSolverr as a Cloudflare fallback.

Order of attempts per call:
  1. Plain requests call, reusing the cf_clearance cookie saved from earlier runs.
  2. If Cloudflare blocks it, FlareSolverr solves the challenge, its cookies and
     user agent are adopted and saved to disk, and the plain call is retried.
  3. If that is still blocked, the JSON is read out of FlareSolverr's page body.

Keeping traffic low and steady is what avoids blocks, so the client also:
  - spaces every request (direct or FlareSolverr) by a minimum gap plus random
    jitter, tracked across runs, not just within one process
  - batches market IDs into as few calls as possible
  - caches each response briefly so repeated asks do not hit the site
  - backs off exponentially (with jitter) after a block, and honours Retry-After
  - keeps headers consistent with the user agent that solved the challenge

cf_clearance is bound to the IP and user agent that solved it, so FlareSolverr
must egress from the same IP as this script (same machine or same VPS).

Env:
  FLARESOLVERR_URL       default http://localhost:8191/v1
  ODDSCHECKER_STATE      default ~/.cache/oddschecker/state.json (kept out of the repo)
  ODDSCHECKER_MIN_GAP    minimum seconds between requests, default 6
  ODDSCHECKER_JITTER     extra random seconds on top, default 6
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import random
import re
import time
from pathlib import Path

import requests

log = logging.getLogger("oddschecker")

FLARESOLVERR_URL = os.getenv("FLARESOLVERR_URL", "http://localhost:8191/v1")
STATE_PATH = Path(os.getenv("ODDSCHECKER_STATE", Path.home() / ".cache" / "oddschecker" / "state.json"))
MIN_GAP = float(os.getenv("ODDSCHECKER_MIN_GAP", "15"))
JITTER = float(os.getenv("ODDSCHECKER_JITTER", "20"))

ODDS_ENDPOINT = "https://www.oddschecker.com/api/markets/v2/all-odds"
DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
)
CHALLENGE_MARKERS = ("Just a moment", "challenge-platform", "cf-chl", "Attention Required")
PRE_RE = re.compile(r"<pre[^>]*>(.*?)</pre>", re.DOTALL | re.IGNORECASE)


class CloudflareBlocked(Exception):
    pass


class BudgetExceeded(Exception):
    """The run's time budget is spent, or Oddschecker blocked twice in a row.

    Added 30 Oct 2026. Each call already had a timeout, but the waits stacked:
    FlareSolverr's 75 seconds, three backoff attempts of up to two minutes,
    and whatever Retry-After asked for, per saved game. On 29 Oct that held
    publish.sh for over an hour. Now every wait comes out of one budget
    (ODDSCHECKER_BUDGET seconds, default 300), and two blocked calls in a row
    end the run: callers catch this and carry on without Oddschecker."""
    pass


BUDGET = float(os.getenv("ODDSCHECKER_BUDGET", "300"))


def _browser_headers(ua: str) -> dict:
    """Headers a real Chrome tab sends for a same-site XHR, matched to the UA's platform."""
    platform = '"Linux"' if "Linux" in ua else '"macOS"' if "Mac OS" in ua else '"Windows"'
    m = re.search(r"Chrome/(\d+)", ua)
    major = m.group(1) if m else "152"
    return {
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-GB,en;q=0.9",
        "Referer": "https://www.oddschecker.com/",
        "Origin": "https://www.oddschecker.com",
        "sec-ch-ua": f'"Chromium";v="{major}", "Google Chrome";v="{major}", "Not.A/Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": platform,
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }


class OddscheckerClient:
    def __init__(
        self,
        flaresolverr_url: str = FLARESOLVERR_URL,
        timeout: float = 20,
        fs_timeout_ms: int = 60000,
        reuse_fs_browser: bool = True,
        min_gap: float = MIN_GAP,
        jitter: float = JITTER,
        cache_ttl: float = 45,
        batch_size: int = 10,
        max_attempts: int = 3,
        state_path: Path = STATE_PATH,
        budget: float | None = BUDGET,
    ):
        self.deadline = time.time() + budget if budget else None
        self._blocked_in_a_row = 0
        self.http = requests.Session()
        self.fs_url = flaresolverr_url
        self.timeout = timeout
        self.fs_timeout_ms = fs_timeout_ms
        self.reuse_fs_browser = reuse_fs_browser
        self.fs_session: str | None = None
        self.min_gap = min_gap
        self.jitter = jitter
        self.cache_ttl = cache_ttl
        self.batch_size = batch_size
        self.max_attempts = max_attempts
        self.state_path = Path(state_path)
        self._cache: dict[str, tuple[float, object]] = {}
        self._last_request = 0.0
        self._ua = DEFAULT_UA
        self._load_state()
        self.http.headers.update(_browser_headers(self._ua))

    # ---------- public ----------

    def get_many(self, market_ids, repub: str = "OC") -> list:
        """Fetch any number of markets, batched, paced, with backoff. Returns a flat list."""
        ids = list(dict.fromkeys(str(m) for m in market_ids))
        out: list = []
        for i in range(0, len(ids), self.batch_size):
            data = self._with_backoff(ids[i : i + self.batch_size], repub)
            out.extend(data if isinstance(data, list) else [data])
        return out

    def get_all_odds(self, market_ids, repub: str = "OC", force_flaresolverr: bool = False):
        ids = ",".join(str(m) for m in market_ids)
        # Built by hand so the commas are not encoded to %2C
        url = f"{ODDS_ENDPOINT}?market-ids={ids}&repub={repub}"

        hit = self._cache.get(url)
        if hit and time.time() - hit[0] < self.cache_ttl and not force_flaresolverr:
            return hit[1]

        data = self._fetch(url, force_flaresolverr)
        self._cache[url] = (time.time(), data)
        return data

    def close(self):
        self._save_state()
        if self.fs_session:
            try:
                requests.post(
                    self.fs_url,
                    json={"cmd": "sessions.destroy", "session": self.fs_session},
                    timeout=15,
                )
            except requests.RequestException:
                pass
            self.fs_session = None
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---------- budget ----------

    def left(self) -> float:
        """Seconds left in this run's budget (a large number when unbudgeted)."""
        return self.deadline - time.time() if self.deadline else 1e9

    def _sleep(self, wait: float, why: str):
        """Sleep, but never past the budget: if the wait does not fit, stop."""
        if wait >= self.left() - 5:
            raise BudgetExceeded(f"{why}: a {wait:.0f}s wait does not fit in the {max(self.left(), 0):.0f}s left")
        time.sleep(max(wait, 0))

    def get_html(self, url: str) -> str:
        """A page's HTML, direct with the saved cookies, else through FlareSolverr."""
        self._pace()
        try:
            r = self.http.get(url, timeout=self.timeout, headers={"Accept": "text/html,application/xhtml+xml"})
            if r.status_code == 200 and not any(m in r.text[:3000] for m in CHALLENGE_MARKERS):
                self._blocked_in_a_row = 0
                return r.text
        except requests.RequestException:
            pass
        sol = self._flaresolverr_get(url)
        self._adopt(sol)
        body = sol.get("response") or ""
        if any(m in body[:3000] for m in CHALLENGE_MARKERS):
            self._note_block()
            raise CloudflareBlocked("FlareSolverr returned the challenge page")
        self._blocked_in_a_row = 0
        return body

    def _note_block(self):
        self._blocked_in_a_row += 1
        if self._blocked_in_a_row >= 2:
            raise BudgetExceeded("blocked twice in a row, stopping for this run")

    # ---------- flow ----------

    def _with_backoff(self, ids, repub):
        for attempt in range(1, self.max_attempts + 1):
            try:
                return self.get_all_odds(ids, repub)
            except CloudflareBlocked as e:
                if attempt == self.max_attempts:
                    raise
                self._note_block()
                wait = 30 * 2 ** (attempt - 1) + random.uniform(0, 15)
                log.warning("Blocked (%s), backing off %.0fs before attempt %d", e, wait, attempt + 1)
                self._sleep(wait, "backoff")

    def _fetch(self, url: str, force_flaresolverr: bool):
        if not force_flaresolverr:
            try:
                return self._direct(url)
            except CloudflareBlocked as e:
                log.warning("Direct call blocked (%s), falling back to FlareSolverr", e)

        solution = self._flaresolverr_get(url)
        self._adopt(solution)

        if not force_flaresolverr:
            try:
                return self._direct(url)
            except CloudflareBlocked as e:
                log.warning("Still blocked with solved cookies (%s), using FlareSolverr body", e)

        return self._parse_fs_body(solution)

    # ---------- pacing ----------

    def _pace(self):
        if self.left() <= 0:
            raise BudgetExceeded("time budget spent")
        day = time.strftime("%Y-%m-%d")
        cap = int(os.getenv("ODDSCHECKER_DAILY_CAP", "150"))
        cfile = self.state_path.with_name("count.json")
        try:
            counts = json.loads(cfile.read_text())
        except (OSError, ValueError):
            counts = {}
        n = counts.get(day, 0)
        if n >= cap:
            raise SystemExit(f"Oddschecker daily cap of {cap} reached, stopping until tomorrow")
        cfile.parent.mkdir(parents=True, exist_ok=True)
        cfile.write_text(json.dumps({day: n + 1}))
        target = self._last_request + self.min_gap + random.uniform(0, self.jitter)
        wait = target - time.time()
        if wait > 0:
            log.debug("Pacing %.1fs", wait)
            self._sleep(wait, "pacing")
        self._last_request = time.time()

    # ---------- direct ----------

    def _direct(self, url: str):
        self._pace()
        try:
            r = self.http.get(url, timeout=min(self.timeout, max(self.left(), 1)))
        except requests.RequestException as e:
            raise CloudflareBlocked(f"request error: {e}") from e

        if r.status_code == 429:
            retry = r.headers.get("Retry-After", "")
            wait = min(float(retry) if retry.isdigit() else 60, 90)
            log.warning("HTTP 429, waiting %.0fs as asked", wait)
            self._sleep(wait + random.uniform(0, 5), "HTTP 429")
            raise CloudflareBlocked("HTTP 429")

        body_head = r.text[:3000]
        if (
            r.status_code in (403, 503)
            or r.headers.get("cf-mitigated", "") == "challenge"
            or any(m in body_head for m in CHALLENGE_MARKERS)
        ):
            raise CloudflareBlocked(f"HTTP {r.status_code}")

        r.raise_for_status()
        try:
            data = r.json()
        except ValueError as e:
            raise CloudflareBlocked("non-JSON body") from e
        self._save_state()  # __cf_bm rotates via Set-Cookie, keep the latest
        return data

    # ---------- FlareSolverr ----------

    def _fs_post(self, payload: dict) -> dict:
        if self.left() < 15:
            raise BudgetExceeded("no time left for FlareSolverr")
        if "maxTimeout" in payload:
            payload["maxTimeout"] = int(min(payload["maxTimeout"], (self.left() - 10) * 1000))
        r = requests.post(self.fs_url, json=payload,
                          timeout=min(self.fs_timeout_ms / 1000 + 15, max(self.left() - 5, 5)))
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "ok":
            raise RuntimeError(f"FlareSolverr error: {data.get('message')}")
        return data

    def _ensure_fs_session(self):
        if self.reuse_fs_browser and not self.fs_session:
            try:
                data = self._fs_post({"cmd": "sessions.create"})
            except (requests.RequestException, RuntimeError) as e:
                log.warning("FlareSolverr sessions.create failed (%s), continuing without a session", e)
                self.reuse_fs_browser = False
                return
            self.fs_session = data.get("session")
            log.info("FlareSolverr session %s created", self.fs_session)

    def _flaresolverr_get(self, url: str) -> dict:
        self._ensure_fs_session()
        self._pace()
        payload = {"cmd": "request.get", "url": url, "maxTimeout": self.fs_timeout_ms}
        if self.fs_session:
            payload["session"] = self.fs_session
        try:
            data = self._fs_post(payload)
        except (requests.RequestException, RuntimeError):
            # Session may have died (FlareSolverr restart). Retry once without it.
            if not self.fs_session:
                raise
            log.warning("FlareSolverr session failed, retrying without it")
            self.fs_session = None
            payload.pop("session", None)
            data = self._fs_post(payload)
        sol = data["solution"]
        log.info("FlareSolverr solved: HTTP %s, %d cookies", sol.get("status"), len(sol.get("cookies", [])))
        return sol

    def _adopt(self, sol: dict):
        ua = sol.get("userAgent")
        if ua:
            self._ua = ua
            self.http.headers.update(_browser_headers(ua))
        for c in sol.get("cookies", []):
            self.http.cookies.set(
                c["name"], c["value"], domain=c.get("domain", ".oddschecker.com"), path=c.get("path", "/")
            )
        self._save_state()

    @staticmethod
    def _parse_fs_body(sol: dict):
        body = sol.get("response") or ""
        try:
            return json.loads(body)
        except ValueError:
            pass
        # Chrome wraps raw JSON responses in <pre> inside an HTML page
        m = PRE_RE.search(body)
        if m:
            try:
                return json.loads(html.unescape(m.group(1)))
            except ValueError:
                pass
        if any(x in body for x in CHALLENGE_MARKERS):
            raise CloudflareBlocked("FlareSolverr returned the challenge page, not the API response")
        raise ValueError(f"Could not parse JSON from FlareSolverr body (first 300 chars): {body[:300]!r}")

    # ---------- state on disk ----------

    def _load_state(self):
        try:
            s = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return
        self._ua = s.get("user_agent") or DEFAULT_UA
        self._last_request = float(s.get("last_request", 0))
        for c in s.get("cookies", []):
            self.http.cookies.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"))
        log.info("Loaded %d saved cookie(s)", len(s.get("cookies", [])))

    def _save_state(self):
        cookies = [
            {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
            for c in self.http.cookies
            if "oddschecker" in (c.domain or "")
        ]
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps({"user_agent": self._ua, "last_request": self._last_request, "cookies": cookies})
            )
        except OSError as e:
            log.warning("Could not save state: %s", e)


def summarise(markets: list) -> str:
    lines = []
    for m in markets:
        priced = [o for o in m.get("odds", []) if o.get("status") == "ACTIVE" and o.get("oddsDecimal")]
        best = max((o["oddsDecimal"] for o in priced), default=None)
        lines.append(f"  {m.get('marketName', '?'):55} {len(priced):3} prices  best {best}")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="Fetch Oddschecker all-odds for market IDs")
    p.add_argument("market_ids", nargs="*", default=["3587987298", "3587890557"])
    p.add_argument("--repub", default="OC")
    p.add_argument("--force-fs", action="store_true", help="skip the direct call, test the FlareSolverr path")
    p.add_argument("--watch", type=float, metavar="SECONDS", help="poll repeatedly, roughly every SECONDS (+/-20%%)")
    p.add_argument("--json", action="store_true", help="print raw JSON instead of a summary")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    with OddscheckerClient() as client:
        while True:
            if args.force_fs:
                data = client.get_all_odds(args.market_ids, repub=args.repub, force_flaresolverr=True)
            else:
                data = client.get_many(args.market_ids, repub=args.repub)
            print(json.dumps(data, indent=2)[:3000] if args.json else summarise(data if isinstance(data, list) else [data]))
            if not args.watch:
                break
            wait = args.watch * random.uniform(0.8, 1.2)
            log.info("Next poll in %.0fs", wait)
            time.sleep(wait)


if __name__ == "__main__":
    main()
