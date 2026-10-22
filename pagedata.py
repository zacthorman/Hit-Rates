"""
The dataset embedded in a built report page, found without a regular expression.

Every report carries its data as `const ALL = {...};` followed by a newline,
and twelve modules each found it with their own copy of

    re.search(r"const ALL = (\\{.*?\\});\\n", text, re.S)

That lazy `.*?` steps through a page of up to 33 MB one character at a time
and cost about half a second a report, every time anything read one: make_index
twice, tonight, besttrack, linelog, rerender and more, each over every report.

search() returns exactly what that regex returned (an object whose group(1)
is the same text, or None) using two str.find calls. Why they agree: the
regex matches at the first "const ALL = {" that has a "};\\n" anywhere after
its brace, and the shortest such match ends at the first "};\\n" after it. If
the first "const ALL = {" has none after it, no later one can either.
tests/test_pagedata.py checks the two against each other.
"""

from __future__ import annotations

START = "const ALL = {"
END = "};\n"


class _Match:
    __slots__ = ("_text",)

    def __init__(self, text: str):
        self._text = text

    def group(self, index: int = 0) -> str:
        if index != 1:
            raise IndexError("only group(1), the payload, is kept")
        return self._text


def payload_text(text: str) -> str | None:
    """The JSON text after `const ALL = `, up to and including its closing
    brace, or None if the page has none."""
    start = text.find(START)
    if start < 0:
        return None
    end = text.find(END, start + len(START))
    if end < 0:
        return None
    return text[start + len(START) - 1:end + 1]


def search(text: str) -> _Match | None:
    """Drop-in for re.search(r"const ALL = (\\{.*?\\});\\n", text, re.S)."""
    found = payload_text(text)
    return None if found is None else _Match(found)


class _Pattern:
    """Drop-in for re.compile(r"const ALL = (\\{.*?\\});\\n", re.S)."""

    def search(self, text: str) -> _Match | None:
        return search(text)


PAYLOAD = _Pattern()
