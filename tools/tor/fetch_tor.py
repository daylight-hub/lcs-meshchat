#!/usr/bin/env python3
"""Fetch the official Tor for the desktop build, verify it, and put it in ./tor.

    python tools/tor/fetch_tor.py            (run by the GitHub build before `npm run dist`)

Uses the Tor Project's own "Tor Expert Bundle" for this platform (Windows x86_64, macOS arm64 /
x86_64, Linux x86_64): the same tor the Tor Project builds reproducibly from the source release.
Refuses to continue unless ALL of these hold:

  1. sha256sums-signed-build.txt carries a good OpenPGP signature from the Tor Browser signing key
     (fingerprint pinned below), fetched by WKD and checked against that fingerprint;
  2. the bundle's SHA-256 matches its line in that signed file;
  3. the extracted `tor --version` is exactly TOR_VERSION.

It then records tor's SHA-256 in tor/manifest.json. MeshChat checks the shipped tor against it
before starting it, so a tor file changed after installation is never run.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(ROOT, "tor")

TOR_VERSION = "0.4.9.15"          # the release reviewed for LCS MeshChat 2.1.0
TB_KEY_FPR = "EF6E286DDA85EA2A4BA7DE684E2C6E8793298290"   # Tor Browser Developers (signing key)
TB_KEY_EMAIL = "torbrowser@torproject.org"
DOWNLOADS_JSON = "https://aus1.torproject.org/torbrowser/update_3/release/downloads.json"
DIST = "https://dist.torproject.org/torbrowser/{tb}/"
ARCHIVE = "https://archive.torproject.org/tor-package-archive/torbrowser/{tb}/"


def die(msg: str):
    print("fetch_tor: " + msg, file=sys.stderr)
    sys.exit(1)


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "lcs-meshchat-build"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def get_any(urls: list[str]) -> bytes:
    last = None
    for url in urls:
        try:
            return get(url)
        except Exception as e:  # noqa: BLE001
            last = e
    die(f"couldn't download {urls[0].rsplit('/', 1)[-1]}: {last}")


def platform_tag() -> str:
    machine = platform.machine().lower()
    if sys.platform == "win32":
        return "windows-x86_64"
    if sys.platform == "darwin":
        return "macos-aarch64" if machine in ("arm64", "aarch64") else "macos-x86_64"
    if machine in ("x86_64", "amd64"):
        return "linux-x86_64"
    die(f"no official Tor Expert Bundle for {sys.platform}/{machine}; MeshChat will use a system tor instead")


def gpg(*args: str, cwd: str | None = None, check=True) -> subprocess.CompletedProcess:
    exe = shutil.which("gpg") or shutil.which("gpg2")
    if not exe:
        die("gpg is needed to check the Tor Project's signature")
    return subprocess.run([exe, "--batch", *args], capture_output=True, text=True, check=check, cwd=cwd)


def verify_signature(home: str, data_path: str, sig_path: str):
    """gpg runs inside the folder that holds everything and is only given names relative to it.
    Git for Windows' gpg is an MSYS program and misreads Windows paths (C:\\... and C:/... alike)
    as relative ones, so no absolute path is ever passed to it."""
    work = os.path.dirname(home)
    rel = lambda p: os.path.relpath(p, work).replace("\\", "/")  # noqa: E731
    os.environ.pop("GNUPGHOME", None)
    r = gpg("--homedir", rel(home), "--auto-key-locate", "nodefault,wkd", "--locate-keys", TB_KEY_EMAIL,
            cwd=work, check=False)
    if r.returncode != 0:  # WKD unreachable: try the keyserver (the fingerprint is checked below either way)
        r2 = gpg("--homedir", rel(home), "--keyserver", "hkps://keys.openpgp.org", "--recv-keys", TB_KEY_FPR,
                 cwd=work, check=False)
        if r2.returncode != 0:
            die("couldn't fetch the Tor Browser signing key:\n" + r.stderr + r2.stderr)
    r = gpg("--homedir", rel(home), "--status-fd", "1", "--verify", rel(sig_path), rel(data_path),
            cwd=work, check=False)
    good = [ln for ln in r.stdout.splitlines() if ln.startswith("[GNUPG:] VALIDSIG ")]
    # VALIDSIG <signing (sub)key fpr> ... <primary key fpr> (last field)
    if r.returncode != 0 or not good or good[0].split()[-1].upper() != TB_KEY_FPR:
        die("the checksum file's signature is NOT valid for the Tor Browser key:\n" + r.stdout + r.stderr)
    print("fetch_tor: signature OK (Tor Browser Developers, " + TB_KEY_FPR + ")")


EXEC_MAGIC = (b"\x7fELF", b"MZ", b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe")


def find_tor_program(root: str, exe_name: str) -> str | None:
    """The real tor program in the bundle. Newer bundles also carry a "debug" folder with a file
    of the same name (debug symbols), and the data folder may have one too: skip those."""
    found = []
    for d, _, files in os.walk(root):
        if exe_name not in files:
            continue
        parts = os.path.relpath(d, root).replace("\\", "/").lower().split("/")
        if "debug" in parts or "data" in parts:
            continue
        path = os.path.join(d, exe_name)
        with open(path, "rb") as fh:
            if not fh.read(4).startswith(EXEC_MAGIC):
                continue
        found.append((0 if os.path.basename(d).lower() == "tor" else 1, len(parts), path))
    return sorted(found)[0][2] if found else None


def main():
    tag = platform_tag()
    tb = os.environ.get("TOR_BROWSER_VERSION") or json.loads(get(DOWNLOADS_JSON))["version"]
    bundle = f"tor-expert-bundle-{tag}-{tb}.tar.gz"
    print(f"fetch_tor: Tor Browser {tb}, {bundle}")
    with tempfile.TemporaryDirectory() as tmp:
        sums = os.path.join(tmp, "sha256sums-signed-build.txt")
        sig = sums + ".asc"
        bases = [DIST.format(tb=tb), ARCHIVE.format(tb=tb)]
        with open(sums, "wb") as fh:
            fh.write(get_any([b + "sha256sums-signed-build.txt" for b in bases]))
        with open(sig, "wb") as fh:
            fh.write(get_any([b + "sha256sums-signed-build.txt.asc" for b in bases]))
        home = os.path.join(tmp, "gnupg")
        os.makedirs(home, mode=0o700)
        verify_signature(home, sums, sig)

        expected = None
        for line in open(sums, encoding="utf-8"):
            parts = line.split()
            if len(parts) == 2 and parts[1].lstrip("*") == bundle:
                expected = parts[0].lower()
        if not expected:
            die(f"{bundle} isn't listed in the signed checksums")
        blob = get_any([b + bundle for b in bases])
        if hashlib.sha256(blob).hexdigest() != expected:
            die(f"{bundle} doesn't match its signed checksum")
        print("fetch_tor: bundle checksum OK")

        path = os.path.join(tmp, bundle)
        with open(path, "wb") as fh:
            fh.write(blob)
        ex = os.path.join(tmp, "x")
        with tarfile.open(path) as tf:
            for m in tf.getmembers():  # no absolute paths or ../ escapes
                if m.name.startswith(("/", "\\")) or ".." in m.name.replace("\\", "/").split("/"):
                    die(f"unexpected path in the bundle: {m.name}")
            tf.extractall(ex)

        exe_name = "tor.exe" if sys.platform == "win32" else "tor"
        tor_bin = find_tor_program(ex, exe_name)
        if not tor_bin:
            die("no tor program in the bundle")
        print(f"fetch_tor: using {os.path.relpath(tor_bin, ex)}")
        shutil.rmtree(OUT, ignore_errors=True)
        shutil.copytree(os.path.dirname(tor_bin), OUT)
        for d, _, files in os.walk(ex):
            for name in ("geoip", "geoip6"):
                if name in files:
                    shutil.copy2(os.path.join(d, name), os.path.join(OUT, name))

    tor_path = os.path.join(OUT, exe_name)
    env = dict(os.environ)
    for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        env[var] = OUT
    out = subprocess.run([tor_path, "--version"], capture_output=True, text=True, env=env).stdout
    first = out.splitlines()[0] if out else ""
    # e.g. "Tor version 0.4.9.15." or "Tor version 0.4.9.15 (git-4d8efff53a86670b)."
    found = re.match(r"Tor version (\d+\.\d+\.\d+\.\d+)\b", first)
    if not found or found.group(1) != TOR_VERSION:
        shutil.rmtree(OUT, ignore_errors=True)
        die(f"the bundle's tor is {first or 'unknown'}, not {TOR_VERSION}. Set TOR_BROWSER_VERSION to the "
            f"Tor Browser release that ships tor {TOR_VERSION}, or update TOR_VERSION after reviewing the new release.")
    # Tor's license (3-clause BSD) must travel with the binary: take it from the reviewed source release
    src = os.path.join(HERE, f"tor-{TOR_VERSION}.tar.gz")
    if os.path.exists(src):
        with tarfile.open(src) as tf:
            member = tf.extractfile(f"tor-{TOR_VERSION}/LICENSE")
            with open(os.path.join(OUT, "LICENSE"), "wb") as fh:
                fh.write(member.read())
    digest = hashlib.sha256(open(tor_path, "rb").read()).hexdigest()
    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump({"version": TOR_VERSION, "sha256": digest, "bundle": bundle, "bundle_sha256": expected}, fh, indent=2)
    print(f"fetch_tor: {first} -> {OUT} (sha256 {digest})")


if __name__ == "__main__":
    main()
