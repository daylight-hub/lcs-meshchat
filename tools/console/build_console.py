#!/usr/bin/env python3
"""
Rebuild src/frontend/public/transport-console/index.html from the upstream
console plus the LCS additions in this directory.

The console itself is a vendored single-file build. The LCS additions are
appended as two <script> blocks wrapped in marker comments, so this script is
idempotent: it strips whatever it added last time and appends the current
sources. Running it twice in a row produces the same file.

    python3 tools/console/build_console.py            # rebuild in place
    python3 tools/console/build_console.py --check    # exit 1 if out of date

Before this existed, the two scripts were pasted in by hand, and a selector
that matched nothing shipped twice without anyone noticing. --verify is here so
that cannot happen again: it asserts that every selector the injected scripts
depend on is actually present in the console bundle.
"""

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "src" / "frontend" / "public" / "transport-console" / "index.html"
HERE = pathlib.Path(__file__).resolve().parent

SCRIPTS = ["bridge-autoconnect.js", "console-extras.js"]

BEGIN = "<!-- LCS:BEGIN -->"
END = "<!-- LCS:END -->"

# Legacy markers: the first generation of injected scripts had no wrapper
# comments. They are identified by these strings, which only appear in them.
LEGACY_SIGNATURES = [
    "MeshChat RNS bridge auto-discovery",
    "LCS MeshChat console extras",
]

# Selectors and markup the injected scripts reach for. Each entry is
# (needle, why) and must appear literally in the upstream bundle.
CONTRACT = [
    ('title:"LCS MeshChat WebSocket URL"', "bridge URL field"),
    ('title:"Remote node destination hash (32 hex chars)"', "destination hash field"),
    ('title:"RNS destination aspect (dot-separated)"', "aspect field"),
    ('title:"Send local identity on link establishment', "authenticate checkbox"),
    ('class:"tabbar"', "tab bar"),
    ('class:"tab"', "tab buttons"),
    ('label:"Transport Config"', "Transport Config tab"),
    ('class:"tab-body config-tab no-pad"', "config tab body"),
    ('class:"sidenav-detail"', "namespace detail pane"),
    ('class:"sidenav-btn"', "namespace buttons"),
    ('class:"ns-h"', "namespace heading"),
    ('class:"unit"', "field unit label"),
    ('{class:"body"}', "single tab body host"),
]


def strip_previous(html: str) -> str:
    """Remove anything this script added on a previous run."""
    marked = re.compile(re.escape(BEGIN) + ".*?" + re.escape(END), re.S)
    html, n = marked.subn("", html)

    if n == 0:
        # First migration off the hand-pasted generation: cut each legacy
        # <script> block by locating its signature and walking back to the
        # opening tag.
        for sig in LEGACY_SIGNATURES:
            at = html.find(sig)
            if at < 0:
                continue
            start = html.rfind("<script>", 0, at)
            end = html.find("</script>", at)
            if start < 0 or end < 0:
                raise SystemExit(f"could not delimit legacy block for {sig!r}")
            html = html[:start] + html[end + len("</script>"):]

    return html


def build(html: str) -> str:
    base = strip_previous(html)

    tail = "</body></html>"
    if not base.rstrip().endswith(tail):
        raise SystemExit("console does not end in </body></html>; refusing to guess")
    base = base.rstrip()[: -len(tail)].rstrip()

    parts = [base, "\n", BEGIN, "\n"]
    for name in SCRIPTS:
        src = (HERE / name).read_text(encoding="utf-8")
        parts.append("<script>\n")
        parts.append(src.rstrip())
        parts.append("\n</script>\n")
    parts.append(END)
    parts.append(tail)
    return "".join(parts)


def verify(html: str) -> list:
    """Return the contract entries the console bundle does not satisfy."""
    base = strip_previous(html)
    return [(needle, why) for needle, why in CONTRACT if needle not in base]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the console is not up to date")
    ap.add_argument("--verify", action="store_true",
                    help="only check the selector contract, do not write")
    args = ap.parse_args()

    html = CONSOLE.read_text(encoding="utf-8")

    missing = verify(html)
    if missing:
        print("selector contract broken -- the console bundle changed:", file=sys.stderr)
        for needle, why in missing:
            print(f"  missing {why}: {needle}", file=sys.stderr)
        return 2
    print(f"selector contract OK ({len(CONTRACT)} anchors present)")

    if args.verify:
        return 0

    out = build(html)

    if args.check:
        if out != html:
            print("console is out of date; run tools/console/build_console.py",
                  file=sys.stderr)
            return 1
        print("console is up to date")
        return 0

    if out == html:
        print("console unchanged")
        return 0

    CONSOLE.write_text(out, encoding="utf-8")
    print(f"wrote {CONSOLE.relative_to(ROOT)} ({len(out)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
