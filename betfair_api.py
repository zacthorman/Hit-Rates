"""
Betfair Exchange prices, through the official API.

Credentials live in .betfair.env next to this file (git-ignored, never
committed), three lines:

    BETFAIR_USER=your-betfair-username
    BETFAIR_PASS=your-betfair-password
    BETFAIR_APP_KEY=your-delayed-app-key

The delayed key is free. Its prices can lag the live exchange by a few
seconds to a few minutes, which is irrelevant for pre-match value checks.

No FlareSolverr and no scraping: this is Betfair's own published API, called
with your own account, which is what it is for.

What the exchange does and does not carry, so nothing downstream assumes too
much: match odds, goal lines, both teams to score, corner and booking markets
on the bigger football fixtures, and NFL match odds, spreads and totals.
Player props (shots on target by a player, receiving yards) are mostly NOT on
the exchange. betfair_probe.py lists exactly which market types exist for the
fixtures this tool covers.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
ENV = HERE / ".betfair.env"
SESSION = HERE / ".betfair_session"
LOGIN_URL = "https://identitysso.betfair.com/api/login"
API_URL = "https://api.betfair.com/exchange/betting/json-rpc/v1"
SESSION_HOURS = 6        # Betfair sessions last longer, but re-login is cheap

FOOTBALL = 1
AMERICAN_FOOTBALL = 6423


def _env() -> dict:
    vals = {k: os.environ.get(k) for k in ("BETFAIR_USER", "BETFAIR_PASS", "BETFAIR_APP_KEY")}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                vals.setdefault(k.strip(), None)
                if not vals.get(k.strip()):
                    vals[k.strip()] = v.strip().strip('"').strip("'")
    missing = [k for k, v in vals.items() if not v]
    if missing:
        raise SystemExit(f"Missing {', '.join(missing)}. Put them in {ENV.name} (see betfair_api.py).")
    return vals


def login(force: bool = False) -> str:
    """Session token, reusing a recent one so we do not log in on every call."""
    if not force and SESSION.exists() and time.time() - SESSION.stat().st_mtime < SESSION_HOURS * 3600:
        return SESSION.read_text().strip()
    cfg = _env()
    body = urllib.parse.urlencode({"username": cfg["BETFAIR_USER"],
                                   "password": cfg["BETFAIR_PASS"]}).encode()
    req = urllib.request.Request(LOGIN_URL, data=body, headers={
        "X-Application": cfg["BETFAIR_APP_KEY"], "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.load(r)
    if out.get("status") != "SUCCESS":
        hint = {"INVALID_USERNAME_OR_PASSWORD": "wrong username or password "
                "(with 2-step verification on, add the 6-digit code to the end of the password)",
                "ACCOUNT_NOW_LOCKED": "too many bad attempts, the account is locked for 20 minutes",
                "KYC_SUSPEND": "the account needs identity checks finishing on the Betfair site",
                }.get(out.get("error"), "")
        raise SystemExit(f"Betfair login failed: {out.get('error')}. {hint}")
    SESSION.write_text(out["token"])
    try:
        SESSION.chmod(0o600)
    except OSError:
        pass
    return out["token"]


def call(method: str, params: dict, _retry: bool = True):
    cfg = _env()
    payload = {"jsonrpc": "2.0", "method": f"SportsAPING/v1.0/{method}",
               "params": params, "id": 1}
    req = urllib.request.Request(API_URL, data=json.dumps(payload).encode(), headers={
        "X-Application": cfg["BETFAIR_APP_KEY"], "X-Authentication": login(),
        "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.load(r)
    err = out.get("error")
    if err:
        code = ((err.get("data") or {}).get("APINGException") or {}).get("errorCode", "")
        if code in ("INVALID_SESSION_INFORMATION", "NO_SESSION") and _retry:
            login(force=True)
            return call(method, params, _retry=False)
        raise SystemExit(f"Betfair {method} failed: {code or err}")
    return out["result"]


def events(event_type: int = FOOTBALL, hours: int = 48, text: str | None = None) -> list[dict]:
    """Fixtures starting in the next `hours`."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    until = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + hours * 3600))
    f = {"eventTypeIds": [str(event_type)], "marketStartTime": {"from": now, "to": until}}
    if text:
        f["textQuery"] = text
    return [e["event"] | {"marketCount": e.get("marketCount")}
            for e in call("listEvents", {"filter": f})]


def markets(event_id: str, max_results: int = 200) -> list[dict]:
    """Every market on one fixture, with its runners."""
    return call("listMarketCatalogue", {
        "filter": {"eventIds": [str(event_id)]}, "maxResults": max_results,
        "marketProjection": ["MARKET_DESCRIPTION", "RUNNER_DESCRIPTION", "MARKET_START_TIME"]})


def prices(market_ids: list[str]) -> list[dict]:
    """Best back and lay for each runner. Up to 40 markets per call is safe."""
    out = []
    for i in range(0, len(market_ids), 40):
        out += call("listMarketBook", {
            "marketIds": market_ids[i:i + 40],
            "priceProjection": {"priceData": ["EX_BEST_OFFERS"], "virtualise": True}})
    return out


def best(book: dict) -> dict:
    """{selectionId: (best back, best lay, back size)} for one market book."""
    res = {}
    for r in book.get("runners", []):
        ex = r.get("ex") or {}
        back = (ex.get("availableToBack") or [{}])[0]
        lay = (ex.get("availableToLay") or [{}])[0]
        res[r["selectionId"]] = (back.get("price"), lay.get("price"), back.get("size"))
    return res
