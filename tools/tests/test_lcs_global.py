#!/usr/bin/env python3
"""
Tests for LCS Global (src/backend/lcs_global.py).

    python3 tools/tests/test_lcs_global.py

Covers what can be checked without the LCS server: hand-made interfaces can't point at
lcs.network, the old LCS Gateway interface becomes LCS Global on first start, a session
is written into the interface and only reloads it when something really changed, and
access ending switches it off and forgets the passphrase.
"""

import os
import pathlib
import sys
import tempfile
import types

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import RNS  # noqa: E402
from RNS.vendor.configobj import ConfigObj  # noqa: E402

from src.backend import lcs_global  # noqa: E402
from src.backend.lcs_global import LcsGlobal, INTERFACE_NAME  # noqa: E402

ok, fail = [], []


def check(name, cond):
    (ok if cond else fail).append(name)
    if not cond:
        print("FAIL:", name)


class FakeReticulum:
    def __init__(self, path):
        self.config = ConfigObj(path)
        self.attached, self.reloaded, self.detached = [], [], []
        self.is_connected_to_shared_instance = False

    def attach_interface(self, name):
        self.attached.append(name)
        RNS.Transport.interfaces.append(types.SimpleNamespace(name=name, online=True))

    def reload_interface(self, name):
        self.reloaded.append(name)

    def detach_interface(self, name):
        self.detached.append(name)
        RNS.Transport.interfaces[:] = [i for i in RNS.Transport.interfaces if getattr(i, "name", None) != name]


def make_app(config_text):
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "config")
    with open(path, "w") as fh:
        fh.write(config_text)
    app = types.SimpleNamespace(storage_dir=tmp, identity=RNS.Identity(), reticulum=FakeReticulum(path))
    RNS.Transport.interfaces[:] = []
    return app, LcsGlobal(app, client_version="test")


# ---- reserved hosts
app, lg = make_app("[interfaces]\n")
for host in ["lcs.network", "LCS.Network.", "update.lcs.network", "x.y.lcs.network", "https://lcs.network/path",
             "public.lcs.network:4245"]:
    check(f"reserved: {host}", lg.is_reserved_host(host))
for host in ["example.com", "notlcs.network", "lcs.network.example.com", "", None, "liberty.local"]:
    check(f"not reserved: {host}", not lg.is_reserved_host(host))
lg.known_ips = {"134.209.36.59"}
check("reserved: a remembered gateway address", lg.is_reserved_host("134.209.36.59"))

# ---- first start: the old gateway becomes LCS Global, hand-made LCS interfaces go off
app, lg = make_app("""[interfaces]
  [[LCS Gateway]]
    type = TCPClientInterface
    enabled = yes
    target_host = public.lcs.network
    target_port = 4243
  [[Mine]]
    type = TCPClientInterface
    enabled = yes
    target_host = update.lcs.network
    target_port = 4245
  [[Friend]]
    type = TCPClientInterface
    enabled = yes
    target_host = example.org
    target_port = 4242
""")
lg.prepare_config()
ifs = app.reticulum.config["interfaces"]
check("old gateway removed", "LCS Gateway" not in ifs)
check("LCS Global created", INTERFACE_NAME in ifs and ifs[INTERFACE_NAME]["enabled"] == "no")
check("legacy users get the trial", lg.pref("auto_trial") is True)
check("hand-made LCS interface switched off", ifs["Mine"]["enabled"] == "no")
check("other interfaces untouched", ifs["Friend"]["enabled"] == "yes")
check("written to disk", "LCS Global" in open(app.reticulum.config.filename).read())

# ---- a session is applied, then left alone unless it changes
session = {"host": "public.lcs.network", "port": 4247, "network_name": "lcs-gateway", "passphrase": "p1"}
check("first session applies", lg.apply_session(session) is True)
check("first session attaches", app.reticulum.attached == [INTERFACE_NAME])
section = app.reticulum.config["interfaces"][INTERFACE_NAME]
check("settings written", section["target_port"] == "4247" and section["passphrase"] == "p1" and section["enabled"] == "yes")
section["selected_interface_mode"] = "1"  # Reticulum adds its own keys at runtime
check("same session: nothing reloaded", lg.apply_session(session) is False and app.reticulum.reloaded == [])
check("new passphrase: reloaded in place", lg.apply_session(dict(session, passphrase="p2")) is True
      and app.reticulum.reloaded == [INTERFACE_NAME])

# ---- access ended
lg.disable_interface()
section = app.reticulum.config["interfaces"][INTERFACE_NAME]
check("access ended: off", section["enabled"] == "no")
check("access ended: passphrase forgotten", "passphrase" not in section)
check("access ended: detached", INTERFACE_NAME in app.reticulum.detached)

# ---- paused by the user, and removed
lg.apply_session(session)
lg.set_paused(True)
check("paused: off and detached", app.reticulum.config["interfaces"][INTERFACE_NAME]["enabled"] == "no"
      and not lg.is_live(INTERFACE_NAME))
lg.ensure_interface()
check("adding it again un-pauses", lg.pref("paused") is False)
lg.remove_interface()
check("removed", INTERFACE_NAME not in app.reticulum.config["interfaces"] and lg.pref("auto_trial") is False)

# ---- signed requests look like Liberty Chat's
raw, sig = lg._signed_body(app.identity, "status")
import base64, json  # noqa: E401,E402
body = json.loads(raw)
check("signed: client is meshchat", body["client"] == "meshchat" and body["action"] == "status")
check("signed: device id is stable", body["dev"] == json.loads(lg._signed_body(app.identity, "status")[0])["dev"])
check("signed: signature verifies", app.identity.validate(base64.b64decode(sig), raw))

print()
print(f"{len(ok)} passed, {len(fail)} failed")
sys.exit(1 if fail else 0)
