"""Shrink the published match pages (3 Nov 2026).

Each report inlines its whole dataset as `const ALL = {...};`. Most of that is
player and match rows, and most of each row is its key names repeated
("Shots on target":, "player": ...) plus floats to 12 decimal places. A 17 MB
page made a mid-range phone freeze for about 17 seconds while it parsed.

This runs on the publish stage only (publish.sh, after site_guard's gate passes), so
the reports in the repo, which a dozen modules read with pagedata, are never
touched. Long lists of objects become a key list plus value rows, nested
objects in those rows (the stats) get their own key list, and floats are
rounded to 5 decimal places. A small decoder put straight after the data
rebuilds exactly the same objects before any other script runs, so the page
code sees what it always saw.

    python packsite.py STAGE_DIR        # pack every report in STAGE_DIR/reports
    python packsite.py --check FILE     # pack one report and print the sizes
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pagedata

MIN_ROWS = 30          # shorter lists are not worth a key list
DECIMALS = 5
MARK = "/*hr-packed*/"

DECODER = (
    "function __hrUnpack(o){if(Array.isArray(o)){for(let i=0;i<o.length;i++)o[i]=__hrUnpack(o[i]);return o;}"
    "if(o&&typeof o==='object'){if(o.__p){const c=o.__p,s=o.__s||{},R=o.__r,out=new Array(R.length);"
    "for(let i=0;i<R.length;i++){const r=R[i],d={};for(let j=0;j<c.length;j++){let v=r[j];if(v==null)continue;"
    "const sc=s[j];if(sc){const sd={};for(let k=0;k<sc.length;k++){const w=v[k];if(w!=null)sd[sc[k]]=__hrUnpack(w);}v=sd;}"
    "else v=__hrUnpack(v);d[c[j]]=v;}out[i]=d;}return out;}for(const k in o)o[k]=__hrUnpack(o[k]);}return o;}"
    "__hrUnpack(ALL);"
)


def _round(v):
    if isinstance(v, float):
        r = round(v, DECIMALS)
        return int(r) if r.is_integer() and abs(r) < 2 ** 53 else r
    if isinstance(v, list):
        return [_round(x) for x in v]
    if isinstance(v, dict):
        return {k: _round(x) for k, x in v.items()}
    return v


def _has_none(v) -> bool:
    if v is None:
        return True
    if isinstance(v, list):
        return any(_has_none(x) for x in v)
    if isinstance(v, dict):
        return any(_has_none(x) for x in v.values())
    return False


def _trim(row: list) -> list:
    while row and row[-1] is None:
        row.pop()
    return row


def _pack_list(items: list):
    """A list of dicts as {"__p": keys, "__r": rows, "__s": {col: subkeys}}, or None
    when it cannot be packed losslessly (None values would read as missing)."""
    cols: dict[str, int] = {}
    for d in items:
        for k in d:
            if k not in cols:
                cols[k] = len(cols)
    keys = list(cols)
    # A column whose every present value is a dict gets its own key list.
    sub: dict[int, list[str]] = {}
    for j, k in enumerate(keys):
        vals = [d[k] for d in items if k in d]
        if vals and all(isinstance(v, dict) for v in vals):
            sk: dict[str, int] = {}
            for v in vals:
                for kk in v:
                    if kk not in sk:
                        sk[kk] = len(sk)
            if any(_has_none(x) for v in vals for x in v.values()):
                continue
            sub[j] = list(sk)
    for d in items:
        for j, k in enumerate(keys):
            if k in d and j not in sub and d[k] is None:
                return None
    rows = []
    for d in items:
        row = []
        for j, k in enumerate(keys):
            if k not in d:
                row.append(None)
            elif j in sub:
                v = d[k]
                row.append(_trim([pack(v[kk]) if kk in v else None for kk in sub[j]]))
            else:
                row.append(pack(d[k]))
        rows.append(_trim(row))
    out = {"__p": keys, "__r": rows}
    if sub:
        out["__s"] = {str(j): v for j, v in sub.items()}
    return out


def pack(v):
    if isinstance(v, list):
        if len(v) >= MIN_ROWS and all(isinstance(x, dict) for x in v):
            p = _pack_list(v)
            if p is not None:
                return p
        return [pack(x) for x in v]
    if isinstance(v, dict):
        if "__p" in v:
            raise ValueError("payload already uses the packing key")
        return {k: pack(x) for k, x in v.items()}
    return v


def unpack(v):
    """Python twin of the page's decoder, used to check every page before it ships."""
    if isinstance(v, list):
        return [unpack(x) for x in v]
    if isinstance(v, dict):
        if "__p" in v:
            cols, sub = v["__p"], {int(k): x for k, x in (v.get("__s") or {}).items()}
            out = []
            for r in v["__r"]:
                d = {}
                for j, c in enumerate(cols):
                    x = r[j] if j < len(r) else None
                    if x is None:
                        continue
                    if j in sub:
                        x = {sk: unpack(x[k]) for k, sk in enumerate(sub[j]) if k < len(x) and x[k] is not None}
                    else:
                        x = unpack(x)
                    d[c] = x
                out.append(d)
            return out
        return {k: unpack(x) for k, x in v.items()}
    return v


def pack_page(text: str) -> str | None:
    """The page with its payload packed, or None if it has no payload or is packed."""
    if MARK in text:
        return None
    raw = pagedata.payload_text(text)
    if raw is None:
        return None
    start = text.find(pagedata.START) + len(pagedata.START) - 1
    end = start + len(raw)
    data = _round(json.loads(raw))
    packed_obj = pack(data)
    if unpack(packed_obj) != data:          # never ship a page that would not read back the same
        raise ValueError("packed data does not unpack to the original")
    packed = json.dumps(packed_obj, separators=(",", ":"), ensure_ascii=False)
    # "</" inside the data would end the script tag.
    packed = packed.replace("</", "<\\/")
    assert text[end:end + 2] == ";\n", "payload is not followed by ';\\n'"
    # "};\n" stays straight after the data, so pagedata still finds it.
    return text[:start] + packed + ";\n" + MARK + DECODER + text[end + 1:]


def main(argv: list[str]) -> int:
    if argv[:1] == ["--check"]:
        p = Path(argv[1])
        t = p.read_text(encoding="utf-8")
        out = pack_page(t)
        if out is None:
            print("nothing to pack")
            return 0
        import gzip
        print(f"{p.name}: {len(t.encode()) / 1e6:.1f} MB -> {len(out.encode()) / 1e6:.1f} MB raw, "
              f"{len(gzip.compress(t.encode())) / 1e6:.2f} -> {len(gzip.compress(out.encode())) / 1e6:.2f} MB gzip")
        if len(argv) > 2:
            Path(argv[2]).write_text(out, encoding="utf-8")
        return 0
    stage = Path(argv[0]) if argv else None
    if stage is None or not (stage / "reports").is_dir():
        print("usage: packsite.py STAGE_DIR", file=sys.stderr)
        return 2
    before = after = 0
    for p in sorted((stage / "reports").glob("*.html")):
        if p.name.startswith("pick-"):
            continue
        t = p.read_text(encoding="utf-8")
        try:
            out = pack_page(t)
        except Exception as exc:   # a page that will not pack is published as it was
            print(f"  {p.name}: not packed ({type(exc).__name__}: {exc})")
            continue
        if out is None:
            continue
        p.write_text(out, encoding="utf-8")
        before += len(t)
        after += len(out)
    if before:
        print(f"packed reports: {before / 1e6:.0f} MB -> {after / 1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
