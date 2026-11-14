#!/usr/bin/env python3

"""
Builds the body for the draft GitHub release.

Takes the "What's new in vX.Y.Z" section out of docs/CHANGELOG.md for the version
being released, and appends the commits since the previous tag. Falls back to just the
commit list if the README has no matching section, so a release never ends up
with an empty body.

Usage:  python .github/scripts/release_notes.py [tag] --output RELEASE_NOTES.md

Always writes UTF-8. The README contains characters outside cp1252 (arrows, em
dashes), and Python on the Windows runner defaults to cp1252 for stdout, so
redirecting output there fails. Writing the file directly avoids depending on
the console encoding at all.
"""

import json
import os
import re
import subprocess
import sys


def repo_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def package_version():
    try:
        with open(os.path.join(repo_root(), "package.json"), encoding="utf-8") as fh:
            return json.load(fh).get("version")
    except (OSError, ValueError):
        return None


# docs/CHANGELOG.md holds the version history. README.md is checked as a fallback
# so older tags, whose notes still lived in the README, keep generating a body.
NOTES_FILES = ("docs/CHANGELOG.md", "README.md")


def readme_section(version):
    """Pull '### What's new in vX.Y.Z' up to the next heading of the same level."""
    if not version:
        return None
    readme = None
    for candidate in NOTES_FILES:
        try:
            with open(os.path.join(repo_root(), candidate), encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        if ("What's new in v" + version) in text:
            readme = text
            break
    if readme is None:
        return None

    heading = re.compile(
        r"^###\s+What's new in v?" + re.escape(version) + r"\s*$",
        re.MULTILINE,
    )
    match = heading.search(readme)
    if match is None:
        return None

    rest = readme[match.end():]
    following = re.search(r"^#{1,3}\s+\S", rest, re.MULTILINE)
    body = rest[:following.start()] if following else rest
    return body.strip() or None


def git(*args):
    try:
        return subprocess.run(
            ["git"] + list(args),
            cwd=repo_root(),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return ""


def previous_tag(current_tag):
    tags = [t for t in git("tag", "--sort=-creatordate").splitlines() if t]
    if current_tag and current_tag in tags:
        index = tags.index(current_tag)
        return tags[index + 1] if index + 1 < len(tags) else None
    # building from a branch rather than a tag, so the newest tag is the baseline
    return tags[0] if tags else None


def commit_list(current_tag):
    previous = previous_tag(current_tag)
    span = f"{previous}..HEAD" if previous else "HEAD"
    log = git("log", span, "--no-merges", "--pretty=format:- %s (%h)")
    if not log:
        return None, previous
    lines = [line for line in log.splitlines() if line.strip()]
    return "\n".join(lines[:60]), previous


def parse_args(argv):
    tag = None
    output = None
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in ("-o", "--output"):
            index += 1
            output = argv[index] if index < len(argv) else None
        elif arg.startswith("--output="):
            output = arg.split("=", 1)[1]
        elif tag is None:
            tag = arg
        index += 1
    return tag or os.environ.get("RELEASE_TAG", ""), output


def main():
    tag, output = parse_args(sys.argv[1:])
    version = (tag or "").lstrip("v") or package_version()

    parts = []

    section = readme_section(version) or readme_section(package_version())
    if section:
        parts.append(section)

    commits, previous = commit_list(tag)
    if commits:
        since = f" since {previous}" if previous else ""
        parts.append(f"### Commits{since}\n\n{commits}")

    if not parts:
        parts.append("No release notes were generated for this build.")

    repo = os.environ.get("GITHUB_REPOSITORY", "daylight-hub/lcs-meshchat")
    parts.append(
        "### Verify your download\n\n"
        "These files were built on GitHub from the source code in this repository, "
        "and GitHub signed a record of the exact commit they came from. To check a "
        "file you downloaded, install the GitHub CLI and run:\n\n"
        "```\n"
        f"gh attestation verify <downloaded file> -R {repo}\n"
        "```"
    )

    body = "\n\n".join(parts) + "\n"

    if output:
        with open(output, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
        return

    # no output file given, so make stdout cope with non-cp1252 characters
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    sys.stdout.write(body)


if __name__ == "__main__":
    main()
