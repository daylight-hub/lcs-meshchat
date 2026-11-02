#!/usr/bin/env python3
"""
Tests for Tor (src/backend/lcs_tor.py, its use in lcs_global.py) and the update notice
(src/backend/update_check.py).

    python3 tools/tests/test_tor_and_update.py

A tiny SOCKS5 server stands in for Tor, so nothing here touches the real Tor network.
"""

import json
import os
import pathlib
import socket
import struct
import sys
import tempfile
import threading
import types

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "tests"))

import RNS  # noqa: E402

from src.backend import lcs_tor  # noqa: E402
from src.backend.lcs_tor import TorClient, socks5_connect  # noqa: E402
from src.backend.update_check import UpdateChecker, parse_version  # noqa: E402

ok, fail = [], []


def check(name, cond):
    (ok if cond else fail).append(name)
    if not cond:
        print("FAIL:", name)


def serve(handler) -> int:
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)

    def loop():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=handler, args=(c,), daemon=True).start()
    threading.Thread(target=loop, daemon=True).start()
    return srv.getsockname()[1]


def echo(c):
    with c:
        while True:
            d = c.recv(4096)
            if not d:
                return
            c.sendall(d)


ECHO_PORT = serve(echo)
SEEN = []


def fake_socks(c):
    """SOCKS5 'Tor': a name ending in .onion goes to the echo server."""
    try:
        assert c.recv(3) == b"\x05\x01\x00"
        c.sendall(b"\x05\x00")
        head = c.recv(4)
        n = c.recv(1)[0]
        name = c.recv(n).decode()
        port = struct.unpack(">H", c.recv(2))[0]
        SEEN.append((name, port))
        if not name.endswith(".onion"):
            c.sendall(b"\x05\x04\x00\x01" + b"\0" * 6)
            c.close()
            return
        up = socket.create_connection(("127.0.0.1", ECHO_PORT))
        c.sendall(b"\x05\x00\x00\x01" + b"\0" * 6)

        def pipe(a, b):
            try:
                while True:
                    d = a.recv(4096)
                    if not d:
                        break
                    b.sendall(d)
            except OSError:
                pass
            finally:
                a.close(); b.close()
        threading.Thread(target=pipe, args=(c, up), daemon=True).start()
        pipe(up, c)
    except Exception:  # noqa: BLE001
        c.close()


SOCKS_PORT = serve(fake_socks)
ONION = "a" * 56 + ".onion"

# ---- SOCKS5 client
s = socks5_connect(SOCKS_PORT, ONION, 4247, timeout=5)
s.sendall(b"ping")
check("socks: reaches an onion address", s.recv(4) == b"ping")
s.close()
try:
    socks5_connect(SOCKS_PORT, "example.com", 80, timeout=5)
    check("socks: refusal is an error", False)
except OSError as e:
    check("socks: refusal is an error", "reached" in str(e))
check("socks: a SOCKS5 proxy is recognised", lcs_tor.socks_is_tor(SOCKS_PORT))
check("socks: an echo server is not", not lcs_tor.socks_is_tor(ECHO_PORT))

# ---- the relay Reticulum connects to
prefs = {}
tmp = tempfile.mkdtemp()
tor = TorClient(tmp, prefs.get, prefs.__setitem__)
tor.state, tor.socks_port = "ready", SOCKS_PORT
tor.relay.set_target(ONION, 4247)
rport = tor.relay.start()
c = socket.create_connection(("127.0.0.1", rport), timeout=5)
c.sendall(b"hello reticulum")
check("relay: carries the connection through Tor", c.recv(64) == b"hello reticulum")
c.close()
check("relay: asked Tor for the onion address and port", (ONION, 4247) in SEEN)
check("relay: port remembered for next time", prefs.get("relay_port") == rport)
tor.relay.stop()

# ---- finding Tor; the built-in copy must match its fingerprint
os.environ.pop("LCS_TOR_PATH", None)
orig_bundled, orig_which, orig_ports = lcs_tor.bundled_tor_dir, lcs_tor.shutil.which, lcs_tor.SYSTEM_SOCKS_PORTS
lcs_tor.bundled_tor_dir = lambda: None
lcs_tor.shutil.which = lambda name: None
lcs_tor.SYSTEM_SOCKS_PORTS = [1]
t2 = TorClient(tmp, {}.get, lambda k, v: None)
t2.start()
check("find: nothing available is reported, not crashed", t2.state == "unavailable" and "Tor Browser" in t2.message)
lcs_tor.SYSTEM_SOCKS_PORTS = [SOCKS_PORT]
how, where = t2.find()
check("find: falls back to a running Tor Browser / service", how == "tor-service" and where == str(SOCKS_PORT))

bdir = os.path.join(tmp, "bundle")
os.makedirs(bdir)
fake = os.path.join(bdir, "tor.exe" if sys.platform == "win32" else "tor")
with open(fake, "wb") as fh:
    fh.write(b"#!/bin/sh\nexit 0\n")
with open(os.path.join(bdir, "manifest.json"), "w") as fh:
    json.dump({"version": "0.4.9.15", "sha256": "0" * 64}, fh)
lcs_tor.bundled_tor_dir = lambda: bdir
t3 = TorClient(tmp, {}.get, lambda k, v: None)
t3.start()
check("built-in: a changed tor file is never started", t3.state == "error" and "fingerprint" in t3.message and t3.proc is None)
with open(os.path.join(bdir, "manifest.json"), "w") as fh:
    json.dump({"version": "0.4.9.15", "sha256": lcs_tor.sha256_of(fake)}, fh)
check("built-in: a matching tor file passes", t3._check_built_in(fake) is None and t3.version == "0.4.9.15")
lcs_tor.bundled_tor_dir, lcs_tor.shutil.which, lcs_tor.SYSTEM_SOCKS_PORTS = orig_bundled, orig_which, orig_ports

# ---- LCS Global with Tor switched on
from test_lcs_global import make_app  # noqa: E402  (also runs those checks quietly first)
app, lg = make_app("[interfaces]\n")
lg.set_pref("tor", True)
lg.tor.state, lg.tor.socks_port = "ready", SOCKS_PORT
raw, sig = lg._signed_body(app.identity, "session")
check("tor on: requests say via=tor (server answers with the onion address)", json.loads(raw)["via"] == "tor")
lg.apply_session({"host": ONION, "port": 4247, "network_name": "lcs-gateway", "passphrase": "p"})
sec = app.reticulum.config["interfaces"]["LCS Global"]
check("tor on: interface points at the local relay", sec["target_host"] == "127.0.0.1" and sec["target_port"] == str(lg.tor.relay.port))
check("tor on: relay aims at the onion address", lg.tor.relay.target == (ONION, 4247))
check("tor on: the relay address isn't treated as an LCS server", not lg.is_reserved_host("127.0.0.1"))
check("tor on: status shows the switch", lg.ui_status()["tor"]["enabled"] is True)
lg.tor.state = "unavailable"
check("tor on but unavailable: no direct fallback", lg.cycle() == 60)
lg.tor.relay.stop()
lg.set_pref("tor", False)
raw, _ = lg._signed_body(app.identity, "session")
check("tor off: no via field", "via" not in json.loads(raw))

# ---- update notice (GitHub + LCS mirror)
check("versions compare numerically", parse_version("v2.10.0") > parse_version("2.9.9") and parse_version("2.1.0") > parse_version("2.0.9"))
SUFS = ("win-installer.exe", "win-portable.exe", "mac-arm64.dmg", "mac-x64.dmg", "linux.AppImage")
release = {"tag_name": "v2.1.0", "html_url": "https://github.com/x/y/releases/tag/v2.1.0", "body": "New: Tor",
           "assets": [{"name": f"LCS-ReticulumMeshChat-v2.1.0-{suf}", "browser_download_url": f"https://dl/{suf}"} for suf in SUFS]}
mirror_page = "<html>" + "".join(
    f'<a href="LCS-ReticulumMeshChat-v{v}-{suf}">x</a>' for v in ("2.0.9", "2.1.0", "2.1.1")
    for suf in ("win-installer.exe", "mac-arm64.dmg", "mac-x64.dmg", "linux.AppImage")) + '<a href="Sideband_1.9.7.apk">s</a></html>'


def fetch_both(url):
    return json.dumps(release).encode() if "api.github.com" in url else mirror_page.encode()


for kind, suf in (("win-installer", "win-installer.exe"), ("mac-arm64", "mac-arm64.dmg"), ("linux-appimage", "linux.AppImage")):
    os.environ["LCS_INSTALL_KIND"] = kind
    st = UpdateChecker(tempfile.mkdtemp(), "2.0.9", fetch=fetch_both).check()
    gh = next(d for d in st["downloads"] if d["source"] == "GitHub")
    mi = next(d for d in st["downloads"] if d["source"] == "lcs.network")
    check(f"update: {kind} gets the same kind of file from GitHub", gh["file"] == f"LCS-ReticulumMeshChat-v2.1.0-{suf}" and gh["url"] == f"https://dl/{suf}")
    check(f"update: {kind} gets the newest same-kind file from the mirror",
          mi["file"] == f"LCS-ReticulumMeshChat-v2.1.1-{suf}" and mi["url"] == f"https://public.lcs.network/downloads/LCS-ReticulumMeshChat-v2.1.1-{suf}")
    check(f"update: {kind} latest is the newest of both", st["available"] and st["latest"] == "2.1.1")
os.environ["LCS_INSTALL_KIND"] = "win-portable"
st = UpdateChecker(tempfile.mkdtemp(), "2.0.9", fetch=fetch_both).check()
check("update: portable isn't on the mirror, so only GitHub's portable is offered",
      [d["source"] for d in st["downloads"]] == ["GitHub"] and st["downloads"][0]["file"].endswith("win-portable.exe"))
os.environ["LCS_INSTALL_KIND"] = "docker"
st = UpdateChecker(tempfile.mkdtemp(), "2.0.9", fetch=fetch_both).check()
check("update: docker gets no file links (pull instead)", st["available"] and all(d["url"] is None for d in st["downloads"]))
os.environ["LCS_INSTALL_KIND"] = "win-installer"
check("update: same version is not offered", not UpdateChecker(tempfile.mkdtemp(), "2.1.1", fetch=fetch_both).check()["available"])


def mirror_only(url):
    if "api.github.com" in url:
        raise OSError("private repository")
    return mirror_page.encode()


st = UpdateChecker(tempfile.mkdtemp(), "2.0.9", fetch=mirror_only).check()
check("update: works from the mirror alone (e.g. private GitHub repo)", st["available"] and st["downloads"][0]["source"] == "lcs.network")
d = tempfile.mkdtemp()
u = UpdateChecker(d, "2.0.9", fetch=fetch_both)
u.check()
u.dismiss("2.1.1")
check("update: don't show again (for this version)", u.status()["dismissed"] is True)
mirror_page += '<a href="LCS-ReticulumMeshChat-v2.2.0-win-installer.exe">n</a>'
check("update: a later release is shown again", UpdateChecker(d, "2.0.9", fetch=fetch_both).check()["dismissed"] is False)
t = UpdateChecker(tempfile.mkdtemp(), "2.0.9", tor_port=lambda: 0)
check("update: with Tor on but not ready, it waits (no direct connection)", t.check().get("waiting") is True and t.checked_at == 0)


def broken(url):
    raise OSError("offline")


check("update: offline says nothing", UpdateChecker(tempfile.mkdtemp(), "2.0.9", fetch=broken).check()["available"] is False)

print()
print(f"{len(ok)} passed, {len(fail)} failed")
sys.exit(1 if fail else 0)
