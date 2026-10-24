#!/usr/bin/env python3
"""
Release readiness check: build the pages offline from main and from the
branch stack, then compare them. Read-only for the repo and the site.

    python release_check.py prepare WORK            # merge the stack, unpack both trees
    python release_check.py prepare WORK release    # redo only main-with-the-stack, keep the other builds
    python release_check.py prepare WORK release --release-ref main-sync   # the release from a merged branch
    python release_check.py build WORK main|stack|release   # build one side offline, timed
    python release_check.py check WORK main|stack|release   # node, a headless browser, links, staging gate
    python release_check.py tests WORK main|stack|release [--no-cache]   # every test file, one at a time
    python release_check.py compare WORK            # what a visitor would see change

WORK is a scratch folder outside the repo. It needs the cache extracted into
WORK/cache (cache_backtest.tar.zst, or the Mac's cache/ copied or linked).

prepare makes a git worktree in WORK/merge from origin/oct21-work and merges
STACK into it in order with --no-ff (it stops at the first conflict), then
unpacks origin/main and the merged result with `git archive` into WORK/main
and WORK/stack. It never commits to a real branch and never pushes. The
worktree's branch is a local scratch one, release-merge-scratch.

build runs one side's own daily build, the steps of its update.py and then
its publish.sh, through that side's replay_build.py harness from the stack
(code-health): the clock frozen at AT (libfaketime), every SofaScore request
answered from the cache, every other request sent to a closed port. Price
fetchers, Betfair settling and fitting, the tactics fetch, git and the push
are left out. Both sides get the same committed Betfair snapshot (PRICES) as
market_prices.json, so the value and verdict code has prices for the weekend.

check runs every page's scripts through `node --check` and in headless
Chromium, records console errors and uncaught exceptions, counts the Paddy
Power verdict badges by opening every player profile on every report, follows
every local link, and stages the site the way publish.sh does and runs the
stack's site_guard.py gate on it (both sides).

compare writes WORK/compare.json and prints the differences: picks, value
claims, verdict counts, accumulators, table columns, sections, timings.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
STACK = ["case-score", "team-model-check", "exchange-log", "code-health", "scorer-audit", "pipeline-tests",
         "acca-correlation", "darts-model", "bookie-imports", "rule-review", "parlay-check", "test-hygiene",
         "acceptable-check", "supersub-check"]
AT = "2026-10-17 06:00"
PRICES = "f252396"           # market_prices.json as committed on 16 Oct, covering that weekend

# Each side's own build: update.py's steps, then publish.sh's, offline only.
COMMON_HEAD = [
    ("bettrack settle", ["bettrack.py", "settle"]),
    ("besttrack settle", ["besttrack.py", "settle"]),
    ("linelog settle", ["linelog.py", "settle"]),
    ("reports (run.py build)", ["replay_build.py", "_reports"]),
    ("rerender", ["rerender.py"]),
    ("make_index --prune", ["make_index.py", "--prune"]),
]
STEPS = {
    "main": COMMON_HEAD + [
        ("team_news", ["team_news.py"]),
        ("fmodel_live", ["fmodel_live.py"]),
        ("usmodel_live", ["usmodel_live.py"]),
        ("markets_sidecar", ["markets_sidecar.py"]),
        ("gamestate_live", ["gamestate_live.py"]),
        ("pplog settle", ["pplog.py", "settle"]),
        ("pplog snapshot", ["pplog.py", "snapshot"]),
        ("teamlog settle", ["teamlog.py", "settle"]),
        ("teamlog snapshot", ["teamlog.py", "snapshot"]),
        ("sharp stamp", ["sharp.py", "stamp"]),
        ("pplog page", ["pplog.py", "page"]),
        ("papertrade page", ["papertrade.py", "--page"]),
        ("make_index", ["make_index.py"]),
        ("exchange_eval page", ["exchange_eval.py", "page"]),
        ("tonight --hours 8", ["tonight.py", "--hours", "8"]),
        ("besttrack snapshot", ["besttrack.py", "snapshot"]),
        ("linelog snapshot", ["linelog.py", "snapshot"]),
        ("bets_page", ["bets_page.py"]),
    ],
    "stack": COMMON_HEAD + [
        ("oddschecker_import", ["oddschecker_import.py"]),
        ("team_news", ["team_news.py"]),
        ("fmodel_live", ["fmodel_live.py"]),
        ("usmodel_live", ["usmodel_live.py"]),
        ("markets_sidecar", ["markets_sidecar.py"]),
        ("pplog settle", ["pplog.py", "settle"]),
        ("pplog snapshot", ["pplog.py", "snapshot"]),
        ("teamlog settle", ["teamlog.py", "settle"]),
        ("teamlog snapshot", ["teamlog.py", "snapshot"]),
        ("pplog page", ["pplog.py", "page"]),
        ("make_index", ["make_index.py"]),
        ("exchange_eval page", ["exchange_eval.py", "page"]),
        ("tonight --hours 8", ["tonight.py", "--hours", "8"]),
        ("besttrack snapshot", ["besttrack.py", "snapshot"]),
        ("linelog snapshot", ["linelog.py", "snapshot"]),
        ("bets_page", ["bets_page.py"]),
    ],
}
# main with the stack merged in: main's publish.sh steps plus the stack's
# Oddschecker import (site_guard's gate is run by check, on the staged site).
STEPS["release"] = STEPS["main"][:6] + [("oddschecker_import", ["oddschecker_import.py"])] + STEPS["main"][6:]
# main's update.py also builds the Conference League; the stack's does not,
# and the merge keeps main's.
EXTRA_GROUPS = {side: '("conference league", (17015,), 3, FOOTBALL_FLAGS, None),' for side in ("main", "release")}
SIDES = ("main", "stack", "release")
# What publish.sh copies into the site, besides reports/.
STAGED = ["index.html", "darts.html", "nfl.html", "bets.html", "tonight.html", "best-bets-summary.html",
          "market-check.html", "pp-results.html", "papertrade.html"]


def git(*args, cwd=HERE, check=True) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check).stdout


# ================================================================= prepare

def prepare(work: Path, only: str | None = None, release_ref: str | None = None) -> dict:
    """Merge, then unpack every side (or only one: the others' builds are kept).

    release_ref: take the release side from a committed branch that already
    has main merged in (main-sync), rather than the scratch merge below."""
    work.mkdir(parents=True, exist_ok=True)
    merge = work / "merge"
    for b in ["main", "oct21-work", *STACK]:
        git("fetch", "-q", "origin", b)
    if not merge.exists():
        git("worktree", "add", "-q", "-B", "release-merge-scratch", str(merge), "origin/oct21-work")
    log = []
    for b in STACK:
        r = subprocess.run(["git", "merge", "-q", "--no-ff", "--no-edit", f"origin/{b}"], cwd=merge,
                           capture_output=True, text=True)
        if r.returncode:
            files = git("diff", "--name-only", "--diff-filter=U", cwd=merge).split()
            log.append({"branch": b, "clean": False, "conflicts": files})
            git("merge", "--abort", cwd=merge, check=False)
            break
        log.append({"branch": b, "clean": True, "head": git("rev-parse", "--short", "HEAD", cwd=merge).strip()})
    for side, ref in (("main", "origin/main"), ("stack", "release-merge-scratch")):
        if only and side != only:
            continue
        dest = work / side
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir()
        tar = subprocess.run(["git", "archive", ref], cwd=HERE, capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", str(dest)], input=tar, check=True)
        prices = subprocess.run(["git", "show", f"{PRICES}:market_prices.json"], cwd=HERE,
                                capture_output=True, check=True).stdout
        (dest / "market_prices.json").write_bytes(prices)
    # The release itself: main with the stack merged in. Its conflicts are
    # listed, then resolved here for this check only (resolve_release), and
    # the result unpacked as WORK/release. Nothing is committed.
    rel = work / "release-tree"
    if not rel.exists():
        git("worktree", "add", "-q", "--detach", str(rel), "origin/main")
    git("merge", "--abort", cwd=rel, check=False)
    git("reset", "-q", "--hard", "origin/main", cwd=rel)
    r = subprocess.run(["git", "merge", "--no-ff", "--no-commit", "release-merge-scratch"], cwd=rel,
                       capture_output=True, text=True)
    conflicts = git("diff", "--name-only", "--diff-filter=U", cwd=rel).split()
    release = {"clean": r.returncode == 0, "conflicts": conflicts,
               "resolved_for_check": resolve_release(rel, conflicts)}
    dest = work / "release"
    if not only or only == "release":
        if dest.exists():
            shutil.rmtree(dest)
        if release_ref:
            dest.mkdir()
            tar = subprocess.run(["git", "archive", release_ref], cwd=HERE, capture_output=True, check=True).stdout
            subprocess.run(["tar", "-x", "-C", str(dest)], input=tar, check=True)
            release["from_ref"] = f"{release_ref} {git('rev-parse', '--short', release_ref).strip()}"
        else:
            shutil.copytree(rel, dest, ignore=shutil.ignore_patterns(".git"))
        dest.joinpath("market_prices.json").write_bytes(
            subprocess.run(["git", "show", f"{PRICES}:market_prices.json"], cwd=HERE, capture_output=True,
                           check=True).stdout)
    git("merge", "--abort", cwd=rel, check=False)
    out = {"stack": log, "release_into_main": release,
           "main": git("rev-parse", "--short", "origin/main").strip(),
           "oct21_work": git("rev-parse", "--short", "origin/oct21-work").strip()}
    (work / "prepare.json").write_text(json.dumps(out, indent=1))
    return out


def resolve_release(rel: Path, conflicts: list[str]) -> dict:
    """A scratch resolution of the three conflicts main and the stack have,
    good enough to build and look at, not a substitute for the real merge.

    tonight.py: main's team and player split, each ranked the stack's way
    (sport-aware chance, one leg per player); main's folding warning with the
    stack's evidence on multiples. USAGE.md: both sections. best_bets.json:
    main's copy (the newer record; the real merge should combine them)."""
    done = {}
    t = rel / "tonight.py"
    if "tonight.py" in conflicts:
        s = t.read_text()
        a = s.index("<<<<<<< HEAD\n        own = rank(pool)")
        b = s.index(">>>>>>> release-merge-scratch\n", a) + len(">>>>>>> release-merge-scratch\n")
        s = s[:a] + RESOLVED_RANK + s[b:]
        a = s.index('<<<<<<< HEAD\n<details class="warn">')
        b = s.index(">>>>>>> release-merge-scratch\n", a) + len(">>>>>>> release-merge-scratch\n")
        mid = s[a:b]
        stack_text = mid[mid.index('<div class="warn">\n') + len('<div class="warn">\n'):mid.index("</div>")]
        s = s[:a] + '<details class="warn"><summary>Why multiples are worse than their legs</summary>\n' \
            + stack_text + "</details>\n" + s[b:]
        # Not a textual conflict, a semantic one: main still defines its own
        # tonight_chance(l) inside build(), which shadows the stack's
        # module-level tonight_chance(l, sport) (with the darts fix). Git
        # merges both without complaint; the inner one has to go.
        inner = ("    def tonight_chance(l):\n        g = l.get(\"gs\")\n        if g:\n"
                 "            return g[\"chance\"]\n        c = weekend.chance(l) if (l.get(\"pStrength\") or "
                 "l.get(\"pShrunk\") or l.get(\"pExchange\")) else None\n        return c if c is not None else 0\n\n")
        if inner in s:
            s = s.replace(inner, "")
            done["tonight.py (semantic)"] = "main's inner tonight_chance removed: it shadowed the stack's"
        t.write_text(s)
        done["tonight.py"] = "main's team/player split, ranked as the stack ranks; stack's text on multiples"
    if "USAGE.md" in conflicts:
        u = rel / "USAGE.md"
        s = u.read_text().replace("<<<<<<< HEAD\n", "").replace(">>>>>>> release-merge-scratch\n", "")
        u.write_text(re.sub(r"^=======\n", "\n", s, flags=re.M))
        done["USAGE.md"] = "both sections kept"
    if "best_bets.json" in conflicts:
        git("checkout", "--ours", "best_bets.json", cwd=rel)
        done["best_bets.json"] = "main's copy"
    return done


RESOLVED_RANK = '''        sport_k = weekend.sport_of(entry)

        def rank_here(p):
            return value_cap.cap_per_player(sorted(p, key=lambda l: (-tonight_chance(l, sport_k) * (l.get("fair") or 1) ** 0.5,
                                                                    -(l.get("total") or 0))))
        own = rank_here(pool)[:SINGLES_PER_FIXTURE]
        lead_log.append(({**meta, "sport": sport_k}, own[0] if own else None,
                         tonight_chance(own[0], sport_k) if own else None))
        team_pool = rank_here([l for l in pool if not l.get("player")])
        player_pool = rank_here([l for l in pool if l.get("player")])
        team_legs_all.extend(l for l in legs if not l.get("player"))
        player_legs_all.extend(l for l in legs if l.get("player"))
'''


# =================================================================== build

def build(work: Path, side: str) -> dict:
    """Run one side's build through the stack's replay_build.py harness."""
    tools = work / f"tools-{side}"
    tools.mkdir(exist_ok=True)
    src = (work / "stack" / "replay_build.py").read_text()
    steps = "STEPS = " + json.dumps([[label, argv] for label, argv in STEPS[side]]) + "\n"
    groups = ("GROUPS = GROUPS + (" + EXTRA_GROUPS[side] + ")\n") if side in EXTRA_GROUPS else ""
    (tools / "replay_build.py").write_text(src + "\n\n# release_check.py: this side's own steps\n" + steps + groups)
    if not (tools / "cache").exists():
        (tools / "cache").symlink_to((work / "cache").resolve())
    sys.path.insert(0, str(tools))
    import importlib
    rb = importlib.import_module("replay_build")
    workdir = work / side
    mark = time.time()
    rb.run_all(workdir, AT)
    # Did anything write into the shared cache? The two sides read the same one.
    touched = [str(p) for p in (work / "cache").rglob("*") if p.is_file() and p.stat().st_mtime > mark]
    t = json.loads((workdir / "_replay" / "timings.json").read_text())
    t["cache_written"] = touched[:50]
    t["errors"] = {}
    for s in t["steps"]:
        slug = re.sub(r"[^a-z0-9]+", "_", s["step"].lower()).strip("_")
        text = (workdir / "_replay" / f"{slug}.log").read_text(errors="replace")
        tb = text.rfind("Traceback")
        if tb >= 0:
            t["errors"][s["step"]] = text[tb:].strip().splitlines()[-1][:300]
    (workdir / "_replay" / "timings.json").write_text(json.dumps(t, indent=1))
    return t


# =================================================================== check

def stage(work: Path, side: str) -> Path:
    """The site as publish.sh stages it: the top-level pages and reports/."""
    src, dest = work / side, work / f"site-{side}"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir()
    for name in STAGED:
        if (src / name).exists():
            shutil.copy2(src / name, dest / name)
    if (src / "reports").exists():
        shutil.copytree(src / "reports", dest / "reports")
    (dest / ".nojekyll").touch()
    return dest


class _Refs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs, self.scripts, self._in = [], [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for key in ("href", "src"):
            if a.get(key):
                self.refs.append(a[key])
        if tag == "script" and not a.get("src") and a.get("type", "text/javascript") in ("text/javascript", "module", ""):
            self._in = []

    def handle_data(self, data):
        if self._in is not None:
            self._in.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._in is not None:
            self.scripts.append("".join(self._in))
            self._in = None


def links_and_scripts(site: Path, tmp: Path) -> dict:
    """Every local link that points at nothing, and every inline script that
    node cannot parse."""
    out = {"broken": [], "syntax": [], "pages": 0, "scripts": 0}
    tmp.mkdir(exist_ok=True)
    for page in sorted(site.rglob("*.html")):
        p = _Refs()
        p.feed(page.read_text(errors="replace"))
        out["pages"] += 1
        for ref in p.refs:
            if re.match(r"^(https?:|mailto:|javascript:|data:|#|//)", ref) or "${" in ref:
                continue
            target = (page.parent / ref.split("#")[0].split("?")[0]).resolve()
            if ref.split("#")[0].split("?")[0] and not target.exists():
                out["broken"].append(f"{page.relative_to(site)} -> {ref}")
        for i, js in enumerate(p.scripts):
            if not js.strip():
                continue
            out["scripts"] += 1
            f = tmp / f"{page.stem}-{i}.js"
            f.write_text(js)
            r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
            if r.returncode:
                out["syntax"].append(f"{page.relative_to(site)} script {i}: "
                                     + (r.stderr.strip().splitlines() or ["?"])[-1][:200])
    out["broken"] = sorted(set(out["broken"]))
    return out


VERDICTS_JS = r"""
async () => {
  const out = { fixtures: 0, profiles: 0, take: 0, ok: 0, long: 0, avoid: 0, errors: [] };
  const count = html => { for (const k of ["take", "ok", "long", "avoid"])
    out[k] += (html.match(new RegExp(`class="vd vd-${k}"`, "g")) || []).length; };
  if (typeof ALL === "undefined" || typeof profileView !== "function") return null;
  for (let i = 0; i < ALL.fixtures.length; i++) {
    try {
      DATA = ALL.fixtures[i];
      out.fixtures++;
      pState = { fx: DATA, team: null, player: null };
      count(squadHome());
      for (const t of [0, 1]) {
        for (const name of squadPlayers(t).keys()) {
          pState = { fx: DATA, team: t, player: name };
          count(profileView(t, name));
          out.profiles++;
        }
      }
    } catch (e) { out.errors.push(`fixture ${i}: ${e && e.message}`); }
  }
  return out;
}
"""


def browse(site: Path) -> dict:
    """Open every page in headless Chromium over a local server, click every
    tab, and on each report count the verdicts by opening every profile."""
    import http.server
    import socketserver
    import threading
    from functools import partial
    from playwright.sync_api import sync_playwright

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = partial(Quiet, directory=str(site))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    exe = "/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None
    pages = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=exe, args=["--no-proxy-server"])
            for page_path in sorted(site.rglob("*.html")):
                rel = str(page_path.relative_to(site))
                info = {"console": [], "exceptions": [], "missing": [], "tabs": {}}
                pg = browser.new_page()
                pg.on("console", lambda m, i=info: i["console"].append(m.text[:200])
                      if m.type == "error" and "favicon" not in (m.location or {}).get("url", "") else None)
                pg.on("pageerror", lambda e, i=info: i["exceptions"].append(str(e)[:300]))
                pg.on("response", lambda r, i=info: i["missing"].append(r.url.split(str(port))[-1])
                      if r.status >= 400 and not r.url.endswith("/favicon.ico") else None)
                t0 = time.perf_counter()
                try:
                    pg.goto(f"http://127.0.0.1:{port}/{rel}", wait_until="networkidle", timeout=60000)
                except Exception as e:
                    info["exceptions"].append(f"load: {e}"[:300])
                info["load_s"] = round(time.perf_counter() - t0, 2)
                info["text_len"] = pg.evaluate("document.body ? document.body.innerText.length : 0")
                for tab in pg.query_selector_all("[data-tab]"):
                    name = tab.get_attribute("data-tab")
                    if not tab.is_visible():
                        info["tabs"][name] = "hidden"
                        continue
                    try:
                        tab.click(timeout=5000)
                        pg.wait_for_timeout(150)
                        info["tabs"][name] = pg.evaluate(
                            "n => { const el = document.getElementById(n); return el ? el.innerText.trim().length : null; }",
                            name)
                    except Exception as e:
                        info["exceptions"].append(f"tab {name}: {e}"[:300])
                if rel.startswith("reports/"):
                    try:
                        info["verdicts"] = pg.evaluate(VERDICTS_JS)
                    except Exception as e:
                        info["exceptions"].append(f"verdicts: {e}"[:300])
                pg.close()
                pages[rel] = info
            browser.close()
    finally:
        httpd.shutdown()
    return pages


def gate(work: Path, site: Path) -> dict:
    """The stack's site_guard.py gate on a staged copy (it may swap files)."""
    copy = site.parent / (site.name + "-gate")
    if copy.exists():
        shutil.rmtree(copy)
    shutil.copytree(site, copy)
    r = subprocess.run([sys.executable, "site_guard.py", "gate", str(copy)], cwd=work / "stack",
                       capture_output=True, text=True)
    return {"exit": r.returncode, "output": (r.stdout + r.stderr).strip().splitlines()[-15:]}


def guard(work: Path, side: str) -> dict:
    """update.py's own checks from the stack (site_guard.report_problems on
    every report as just built, index_problems on the index), read-only, with
    the clock at the frozen build time."""
    import importlib.util
    from datetime import datetime, timezone
    sys.path.insert(0, str(work / "stack"))
    try:
        spec = importlib.util.spec_from_file_location("site_guard_stack", work / "stack" / "site_guard.py")
        sg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sg)
    finally:
        sys.path.remove(str(work / "stack"))
    now = datetime.strptime(AT, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp()
    reports = work / side / "reports"
    out = {"reports": {}, "index": sg.index_problems(work / side / "index.html", reports)}
    for f in sg._report_files(reports):
        problems = sg.report_problems(f, now=now, fresh=True)
        if problems:
            out["reports"][f.name] = problems
    return out


def check(work: Path, side: str) -> dict:
    site = stage(work, side)
    out = {"links": links_and_scripts(site, work / f"js-{side}"), "gate": gate(work, site),
           "guard": guard(work, side), "pages": browse(site)}
    (work / f"check-{side}.json").write_text(json.dumps(out, indent=1))
    return out


# ================================================================= compare

def index_picks(path: Path) -> dict:
    """The picks the index shows, per sport, from its embedded payload."""
    if not path.exists():
        return {}
    text = path.read_text(errors="replace")
    i = text.find("const DATA = ")
    if i < 0:
        return {}
    data, _ = json.JSONDecoder().raw_decode(text[i + len("const DATA = "):])
    picks = data.get("picks") or {}

    def leg(l):
        who = l.get("player") or l.get("team") or "?"
        side = "over" if l.get("over", True) else "under"
        return f"{who} {l.get('stat')} {side} {l.get('line')}"

    out = {"fixtures": len(data.get("fixtures") or []), "valueShow": picks.get("valueShow", "absent"), "sports": {}}
    for s in picks.get("sports") or []:
        o = {}
        for key in ("single", "banker"):
            if s.get(key):
                o[key] = f"{leg(s[key])} @ {s[key].get('fair', 0):.2f}"
        for key in ("double", "acca", "builder", "parlay"):
            x = s.get(key)
            if x:
                legs = x.get("legs") or []
                price = x.get("combined") or x.get("fair") or x.get("price")
                o[key] = f"{len(legs)} legs @ {price:.2f}" if isinstance(price, (int, float)) else f"{len(legs)} legs"
        v = s.get("value") or {}
        o["value_list"] = len(v.get("legs") or [])
        o["value_positive"] = v.get("positive")
        out["sports"][s.get("sport")] = o
    return out


VALUE_RX = re.compile(r"[+−-]\d+(?:\.\d)?% value|value \+\d+%|no value")


def page_features(path: Path) -> dict:
    text = path.read_text(errors="replace")
    heads = re.findall(r"<(?:h1|h2|h3|summary)[^>]*>(.*?)</(?:h1|h2|h3|summary)>", text, re.S)
    clean = lambda s: re.sub(r"\s+", " ", re.sub(r"<[^>]+>|\$\{[^}]*\}", "", s)).strip()[:80]
    return {
        "bytes": len(text),
        "headings": sorted({clean(h) for h in heads if clean(h)}),
        "columns": sorted({clean(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", text, re.S) if clean(h)}),
        "tabs": re.findall(r'data-tab="([^"]+)"', text),
        "value_claims": {k: len(re.findall(rx, text)) for k, rx in (
            ("+n% value", r"\+\d+(?:\.\d)?% value"), ("-n% value", r"(?:&minus;|−|-)\d+(?:\.\d)?% value"),
            ("value +n% (index)", r"value \+\d+%"), ("no value", r"no value"))},
    }


def compare(work: Path) -> dict:
    out = {"prepare": json.loads((work / "prepare.json").read_text())}
    for side in SIDES:
        if not (work / side / "_replay" / "timings.json").exists():
            continue
        t = json.loads((work / side / "_replay" / "timings.json").read_text())
        chk = json.loads((work / f"check-{side}.json").read_text()) if (work / f"check-{side}.json").exists() else {}
        site = work / f"site-{side}"
        pages = {str(p.relative_to(site)): page_features(p) for p in sorted(site.rglob("*.html"))} if site.exists() else {}
        verdicts = {"take": 0, "ok": 0, "long": 0, "avoid": 0, "profiles": 0}
        for rel, info in (chk.get("pages") or {}).items():
            v = info.get("verdicts") or {}
            for k in verdicts:
                verdicts[k] += v.get(k, 0) if k != "profiles" else v.get("profiles", 0)
        out[side] = {"timings": t, "index": index_picks(work / side / "index.html"), "pages": pages,
                     "verdicts": verdicts,
                     "js": {rel: {"exceptions": i["exceptions"], "console": i["console"][:5],
                                  "missing": sorted(set(i["missing"]))[:10]}
                            for rel, i in (chk.get("pages") or {}).items()
                            if i["exceptions"] or i["console"] or i["missing"]},
                     "empty_tabs": {rel: [k for k, n in i["tabs"].items() if n == 0]
                                    for rel, i in (chk.get("pages") or {}).items()
                                    if any(n == 0 for n in i["tabs"].values())},
                     "links": chk.get("links"), "gate": chk.get("gate"), "guard": chk.get("guard")}
    (work / "compare.json").write_text(json.dumps(out, indent=1))
    return out


def run_tests(work: Path, side: str, with_cache: bool = True) -> dict:
    """Every tests/test_*.py of one side, one file per process (all at once
    holds every built report in memory), with or without the cache linked."""
    tree = work / side
    link = tree / "cache"
    if with_cache and not link.exists():
        link.symlink_to((work / "cache").resolve())
    moved = None
    if not with_cache and link.exists():
        moved = tree / "cache.off"
        link.rename(moved)
    out = {}
    try:
        for f in sorted((tree / "tests").glob("test_*.py")):
            r = subprocess.run([sys.executable, "-m", "pytest", str(f.relative_to(tree)), "-q", "-p", "no:cacheprovider"],
                               cwd=tree, capture_output=True, text=True, timeout=900)
            lines = r.stdout.strip().splitlines()
            out[f.name] = {"exit": r.returncode, "summary": lines[-1] if lines else "",
                           "failed": [x for x in lines if x.startswith("FAILED")]}
    finally:
        if moved:
            moved.rename(link)
    (work / f"tests-{side}-{'cache' if with_cache else 'nocache'}.json").write_text(json.dumps(out, indent=1))
    return out


def main(argv=None):
    a = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    a.add_argument("cmd", choices=("prepare", "build", "check", "tests", "compare"))
    a.add_argument("--no-cache", action="store_true", help="tests: without the cache linked")
    a.add_argument("--release-ref", help="prepare: the release side from this committed ref (e.g. main-sync)")
    a.add_argument("work", type=Path)
    a.add_argument("side", nargs="?", choices=SIDES)
    args = a.parse_args(argv)
    work = args.work.resolve()
    if args.cmd in ("build", "check", "tests") and not args.side:
        a.error("build and check need a side: main, stack or release")
    if args.cmd == "prepare":
        print(json.dumps(prepare(work, args.side, args.release_ref), indent=1))
    elif args.cmd == "build":
        t = build(work, args.side)
        print(json.dumps({"total": t["total"], "errors": t["errors"], "cache_written": t["cache_written"]}, indent=1))
    elif args.cmd == "check":
        c = check(work, args.side)
        print(json.dumps({"links": c["links"], "gate": c["gate"], "guard": c["guard"]}, indent=1))
    elif args.cmd == "tests":
        res = run_tests(work, args.side, not args.no_cache)
        bad = {k: v for k, v in res.items() if v["exit"] not in (0, 5)}
        print(json.dumps({"files": len(res), "failing": bad}, indent=1))
    else:
        compare(work)
        print(f"written {work / 'compare.json'}")


if __name__ == "__main__":
    main()
