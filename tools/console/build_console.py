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
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "src" / "frontend" / "public" / "transport-console" / "index.html"
# The pristine vendored console, before any LCS changes. index.html is a pure
# build artifact generated from this plus the scripts here, so every run is
# reproducible and --check is meaningful. Replace this file to vendor a new
# upstream console build.
PRESETS_JSON = ROOT / "src" / "frontend" / "js" / "rnode-presets.json"
HERE = pathlib.Path(__file__).resolve().parent
BASE = HERE / "console-base.html"

SCRIPTS = ["bridge-autoconnect.js", "console-extras.js"]

# The console has two preset dropdowns: one the vendored bundle builds itself on
# Node Config, and one this directory injects into Transport Config. Both are
# generated from src/frontend/js/rnode-presets.json, which the Vue app imports
# directly, so the app and the console cannot drift apart.
PRESET_PLACEHOLDER = "/*__LCS_PRESETS__*/[]"

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
    ("LCG1=[", "the bundle's own preset data"),
    (",LCG2=[", "the bundle's country preset data, which we remove"),
    ('const og2=Ae("optgroup"', "the bundle's second preset optgroup, which we remove"),
]


def load_presets() -> list:
    return json.loads(PRESETS_JSON.read_text(encoding="utf-8"))


def preset_label(preset: dict) -> str:
    """The console shows one line per preset, so name, params and note are joined."""
    label = "{} — {}".format(preset["name"], preset["params"])
    if preset.get("note"):
        label += "  (★ {})".format(preset["note"])
    elif preset.get("hint"):
        label += "  ({})".format(preset["hint"])
    return label


def preset_literal(presets: list) -> str:
    """A JS array literal in the shape the console's own preset code expects."""
    items = []
    for preset in presets:
        items.append(json.dumps({
            "l": preset_label(preset),
            "f": preset["frequency"],
            "bw": preset["bandwidth"],
            "sf": preset["spreadingfactor"],
            "cr": preset["codingrate"],
        }, ensure_ascii=True, separators=(",", ":")))
    return "[" + ",".join(items) + "]"


def retarget_presets(base: str, presets: list) -> str:
    """
    Point the vendored bundle's own preset dropdown at our list, and drop the
    country presets entirely.

    Two surgical replacements, both anchored on literals asserted by CONTRACT so
    a new console build cannot silently skip them:
      1. the LCG1/LCG2 data,
      2. the second optgroup, which would otherwise render as an empty group
         with a "country presets" heading.
    """
    literal = preset_literal(presets)

    data = re.compile(r"LCG1=\[.*?\],LCG2=\[.*?\];", re.S)
    replacement = "LCG1={},LCG2=[];".format(literal)
    base, n = data.subn(lambda _m: replacement, base, count=1)
    if n != 1:
        raise SystemExit("could not find the bundle's LCG1/LCG2 preset data")

    group = re.compile(r'const og2=Ae\("optgroup".*?psel\.appendChild\(og2\);', re.S)
    base, n = group.subn("", base, count=1)
    if n != 1:
        raise SystemExit("could not find the bundle's second preset optgroup")

    return base


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
    # html is the current artifact, used only by --check for comparison. The
    # content is always built from the pristine vendored bundle.
    base = BASE.read_text(encoding="utf-8")
    presets = load_presets()
    base = retarget_presets(base, presets)

    tail = "</body></html>"
    if not base.rstrip().endswith(tail):
        raise SystemExit("console does not end in </body></html>; refusing to guess")
    base = base.rstrip()[: -len(tail)].rstrip()

    literal = preset_literal(presets)

    parts = [base, "\n", BEGIN, "\n"]
    for name in SCRIPTS:
        src = (HERE / name).read_text(encoding="utf-8")
        if name == "console-extras.js":
            if PRESET_PLACEHOLDER not in src:
                raise SystemExit(
                    "console-extras.js no longer contains {}".format(PRESET_PLACEHOLDER))
            src = src.replace(PRESET_PLACEHOLDER, literal)
        parts.append("<script>\n")
        parts.append(src.rstrip())
        parts.append("\n</script>\n")
    parts.append(END)
    parts.append(tail)
    return "".join(parts)


def verify(html: str) -> list:
    """Return the contract entries the pristine console bundle does not satisfy."""
    base = BASE.read_text(encoding="utf-8")
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
