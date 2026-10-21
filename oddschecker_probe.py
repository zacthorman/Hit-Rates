"""One-off probe: load a few Oddschecker pages through FlareSolverr and report
where fixture and market IDs live, so discovery can be automated.

Uses the client's pacing and daily cap. Saves raw HTML to
~/.cache/oddschecker/probe/ (outside the repo) and prints a short summary to paste back.

  python3 oddschecker_probe.py                      # Premier League list page
  python3 oddschecker_probe.py <oddschecker url> ...
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from oddschecker_client import OddscheckerClient

DEFAULT_URLS = ["https://www.oddschecker.com/football/english/premier-league"]
OUT = Path.home() / ".cache" / "oddschecker" / "probe"

ID_RE = re.compile(r'"(marketId|subeventId|eventId|betTypeId|marketTypeId|ocMarketId)"\s*:\s*"?(\d+)')
API_RE = re.compile(r'/api/[A-Za-z0-9/_\-.]+')
LINK_RE = re.compile(r'href="(/(?:football|american-football)/[^"#?]+)"')
NEXT_RE = re.compile(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
STATE_RE = re.compile(r'window\.(__[A-Z_]+__)\s*=', re.DOTALL)


def slug(url: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", url.lower().split("oddschecker.com")[-1]).strip("-") or "root"


def summarise(url: str, html: str) -> None:
    print(f"\n=== {url}")
    print(f"size {len(html):,} chars")

    ids: dict[str, set] = {}
    for k, v in ID_RE.findall(html):
        ids.setdefault(k, set()).add(v)
    for k, vs in sorted(ids.items()):
        print(f"  {k:14} {len(vs):4} distinct  e.g. {', '.join(sorted(vs)[:5])}")

    apis = sorted(set(API_RE.findall(html)))
    print(f"  api paths ({len(apis)}):")
    for a in apis[:25]:
        print(f"    {a}")

    links = list(dict.fromkeys(LINK_RE.findall(html)))
    print(f"  fixture/market links ({len(links)}), first 20:")
    for l in links[:20]:
        print(f"    {l}")

    m = NEXT_RE.search(html)
    if m:
        try:
            data = json.loads(m.group(1))
            print(f"  __NEXT_DATA__ found, top keys: {list(data)[:10]}")
            props = data.get("props", {}).get("pageProps", {})
            print(f"  pageProps keys: {list(props)[:20]}")
        except ValueError:
            print("  __NEXT_DATA__ found but not valid JSON")
    for name in sorted(set(STATE_RE.findall(html))):
        print(f"  window.{name} present")


def main():
    urls = sys.argv[1:] or DEFAULT_URLS
    OUT.mkdir(parents=True, exist_ok=True)
    with OddscheckerClient() as c:
        for url in urls:
            sol = c._flaresolverr_get(url)
            c._adopt(sol)
            html = sol.get("response") or ""
            path = OUT / f"{slug(url)}.html"
            path.write_text(html)
            summarise(url, html)
            print(f"  saved {path}")
            print(f"\nrequests today: {(c.state_path.with_name('count.json')).read_text()}")


if __name__ == "__main__":
    main()
