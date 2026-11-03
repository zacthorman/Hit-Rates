"""One header and footer for every page (3 Nov 2026).

Every generator passes its finished HTML through wrap() before writing it, so
the site has one way around it and one honest headline: the paper-trade
record, read from record.json (written by papertrade.py). wrap() is
idempotent, so pages that are re-read and re-written keep a single nav.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
THEME = ROOT / "sitenav.css"   # the colour layer, loaded after each page's own styles
RECORD = ROOT / "record.json"
MARK = "<!--sitenav-->"

LINKS = [
    ("index", "Fixtures", "index.html"),
    ("tonight", "Tonight", "tonight.html"),
    ("bets", "Best bets", "best-bets-summary.html"),
    ("record", "Track record", "papertrade.html"),
    ("pp", "Paddy Power log", "pp-results.html"),
    ("market", "Model v market", "market-check.html"),
]

CSS = """<style id="sitenav-css">
.hr-nav,.hr-foot{--hn-bg:#fcfcfb;--hn-fg:#111;--hn-mu:#6b6963;--hn-bd:rgba(0,0,0,.1);--hn-on:#111;--hn-onfg:#fff;--hn-pos:#15803d;--hn-neg:#b91c1c;
  font:14px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;color:var(--hn-fg)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .hr-nav,:root:not([data-theme="light"]) .hr-foot{
  --hn-bg:#141413;--hn-fg:#f2f2f0;--hn-mu:#9a988f;--hn-bd:rgba(255,255,255,.12);--hn-on:#f2f2f0;--hn-onfg:#111;--hn-pos:#4ade80;--hn-neg:#f87171}}
:root[data-theme="dark"] .hr-nav,:root[data-theme="dark"] .hr-foot{
  --hn-bg:#141413;--hn-fg:#f2f2f0;--hn-mu:#9a988f;--hn-bd:rgba(255,255,255,.12);--hn-on:#f2f2f0;--hn-onfg:#111;--hn-pos:#4ade80;--hn-neg:#f87171}
html{overflow-x:clip}
.hr-nav,.hr-foot{width:100vw;max-width:100vw;margin-left:calc(50% - 50vw);box-sizing:border-box}
.hr-nav{background:var(--hn-bg);border-bottom:1px solid var(--hn-bd);position:relative;z-index:40;margin-bottom:16px}
.hr-nav-in{max-width:1240px;margin:0 auto;padding:10px 16px;display:flex;align-items:center;gap:14px}
.hr-brand{font-weight:700;font-size:16px;color:var(--hn-fg)!important;text-decoration:none;white-space:nowrap;letter-spacing:-.01em}
.hr-brand i{display:inline-block;width:9px;height:9px;border-radius:3px;background:var(--hn-pos);margin-right:7px;vertical-align:1px}
.hr-links{display:flex;gap:2px;overflow-x:auto;scrollbar-width:none;flex:1 1 auto;min-width:0}
.hr-links::-webkit-scrollbar{display:none}
.hr-links a{padding:6px 10px;border-radius:999px;color:var(--hn-mu)!important;text-decoration:none!important;white-space:nowrap;font-weight:550;font-size:13.5px}
.hr-links a:hover{color:var(--hn-fg)!important;background:var(--hn-bd)}
.hr-links a[aria-current]{background:var(--hn-on);color:var(--hn-onfg)!important}
.hr-rec{white-space:nowrap;font-size:12.5px;color:var(--hn-mu)!important;text-decoration:none!important;border:1px solid var(--hn-bd);border-radius:999px;padding:4px 10px}
.hr-rec b{font-variant-numeric:tabular-nums}.hr-rec .pos{color:var(--hn-pos)}.hr-rec .neg{color:var(--hn-neg)}
.hr-foot{border-top:1px solid var(--hn-bd);margin-top:40px;background:var(--hn-bg)}
.hr-foot p{max-width:1240px;margin:0 auto;padding:16px;color:var(--hn-mu);font-size:12.5px}
.hr-foot a{color:var(--hn-mu)!important}
@media (max-width:720px){.hr-nav-in{flex-wrap:wrap;gap:8px 10px;padding:8px 12px}.hr-links{order:3;flex-basis:100%}.hr-rec{margin-left:auto}}
</style>"""


def _record() -> dict | None:
    try:
        return json.loads(RECORD.read_text())
    except (OSError, ValueError):
        return None


def header(active: str = "", prefix: str = "") -> str:
    links = "".join(
        f'<a href="{prefix}{href}"' + (' aria-current="page"' if key == active else "") + f">{label}</a>"
        for key, label, href in LINKS)
    rec = _record()
    pill = ""
    if rec and rec.get("n"):
        roi = rec["roi"] * 100
        cls = "pos" if roi > 0 else "neg" if roi < 0 else ""
        pill = (f'<a class="hr-rec" href="{prefix}papertrade.html" title="Every pick the site has made, at Paddy Power '
                f'prices, level stakes">Record <b class="{cls}">{roi:+.1f}%</b> on {rec["n"]:,} bets</a>')
    return (f'{MARK}<nav class="hr-nav" aria-label="Site"><div class="hr-nav-in">'
            f'<a class="hr-brand" href="{prefix}index.html"><i></i>Hit Rates</a>'
            f'<div class="hr-links">{links}</div>{pill}</div></nav>')


def footer(prefix: str = "") -> str:
    return ('<footer class="hr-foot"><p>Hit Rates is a stats project shared with mates, not betting advice. '
            f'Most lines on here lose money over time: the <a href="{prefix}papertrade.html">track record</a> '
            'shows it honestly. Prices change, so check before you bet. 18+, and if it stops being fun, '
            '<a href="https://www.begambleaware.org" rel="noopener">BeGambleAware.org</a>.</p></footer>')


def wrap(page: str, active: str = "", prefix: str = "", kind: str | None = None) -> str:
    """Add the shared header after <body ...> and the footer before </body>, once.
    kind names the page for the colour layer (html class hr-p-<kind>); it
    defaults to active, and match and pick pages pass "report" and "picker"."""
    if MARK in page or "<body" not in page:
        return page
    import re
    page = re.sub(r"<html(\s|>)", lambda m: f'<html class="hr-p-{kind or active or "page"}"{m.group(1)}', page, count=1)
    i = page.find("<body")
    j = page.find(">", i) + 1
    page = page[:j] + header(active, prefix) + page[j:]
    k = page.rfind("</body>")
    if k != -1:
        page = page[:k] + footer(prefix) + SCRIPT + page[k:]
    h = page.find("</head>")
    if h != -1:
        try:
            theme = f'<style id="hr-theme">{THEME.read_text(encoding="utf-8")}</style>'
        except OSError:
            theme = ""
        page = page[:h] + CSS + theme + page[h:]
    return page


# SCRIPT is defined below wrap(); wrap() reads it at call time.


def save_record(n: int, roi: float, bank: float, since: str = "") -> None:
    RECORD.write_text(json.dumps({"n": n, "roi": roi, "bank": bank, "since": since}) + "\n")


# On a phone the links scroll sideways; bring the current page's link into view.
SCRIPT = ("<script>(function(){var a=document.querySelector('.hr-links [aria-current]');"
          "if(a){var l=a.parentNode;l.scrollLeft=a.offsetLeft-l.offsetLeft-40;}})();</script>")
