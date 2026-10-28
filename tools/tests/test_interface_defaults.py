#!/usr/bin/env python3
"""
Tests that AutoInterface defaults to gateway mode.

    python3 tools/tests/test_interface_defaults.py

Field result behind this: with Liberty Chat's AutoInterface in roaming, and
with both apps in full, MeshChat could not reach Liberty Chat while Liberty
Chat reached MeshChat fine. Gateway on both sides made messages flow.
Reticulum's own default config ships its AutoInterface with no mode, which is
full, so MeshChat fills it in -- and leaves any mode someone chose alone.
"""

import ast
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = ROOT / "meshchat.py"
source = SOURCE.read_text(encoding="utf-8")
tree = ast.parse(source)
klass = next(n for n in ast.walk(tree)
             if isinstance(n, ast.ClassDef) and n.name == "ReticulumMeshChat")
funcs = {n.name: n for n in klass.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

ok, fail = [], []


def check(name, cond):
    (ok if cond else fail).append(name)
    print(("  ok   " if cond else " FAIL  ") + name)


check("method present: ensure_autointerface_gateway_mode",
      "ensure_autointerface_gateway_mode" in funcs)

init = ast.unparse(funcs["__init__"])
check("it runs after Reticulum is constructed, which writes the default config",
      init.index("RNS.Reticulum(reticulum_config_dir)")
      < init.index("self.ensure_autointerface_gateway_mode()"))

# --- run it against a fake config and a fake running stack -------------------

GATEWAY, FULL, ROAMING = 6, 1, 4


class Section(dict):
    pass


class Config(dict):
    def __init__(self, interfaces):
        super().__init__(interfaces=interfaces)
        self.writes = []

    def write(self):
        # snapshot what would land on disk
        self.writes.append({n: dict(s) for n, s in self["interfaces"].items()})


class Iface:
    def __init__(self, name, mode, parent=None):
        self.name, self.mode, self.parent_interface = name, mode, parent


AutoInterface = type("AutoInterface", (Iface,), {})
TCPClientInterface = type("TCPClientInterface", (Iface,), {})


def run(interfaces, live):
    config = Config(interfaces)
    rns = types.SimpleNamespace(
        Interfaces=types.SimpleNamespace(Interface=types.SimpleNamespace(
            Interface=types.SimpleNamespace(MODE_GATEWAY=GATEWAY))),
        Transport=types.SimpleNamespace(interfaces=live),
    )
    ns = {"RNS": rns, "print": lambda *a, **k: None}
    mod = ast.Module(body=[funcs["ensure_autointerface_gateway_mode"]], type_ignores=[])
    ast.fix_missing_locations(mod)
    exec(compile(mod, "<meshchat>", "exec"), ns)  # noqa: S102
    obj = types.SimpleNamespace(reticulum=types.SimpleNamespace(config=config))
    ns["ensure_autointerface_gateway_mode"](obj)
    return config


default = Section(type="AutoInterface", enabled="Yes",
                  name="Default Interface", selected_interface_mode=FULL, configured_bitrate=None)
chosen = Section(type="AutoInterface", enabled="Yes", mode="roaming")
tcp = Section(type="TCPClientInterface", enabled="Yes", target_host="x")
parent = AutoInterface("Default Interface", FULL)
peer = AutoInterface("peer", FULL, parent=parent)
other = AutoInterface("Chosen", ROAMING)
client = TCPClientInterface("TCP", FULL)

cfg = run({"Default Interface": default, "Chosen": chosen, "TCP": tcp},
          [parent, peer, other, client])

check("an AutoInterface with no mode is set to gateway in the config",
      default.get("mode") == "gateway")
check("one with a mode already chosen is left alone",
      chosen.get("mode") == "roaming")
check("other interface types are left alone", "mode" not in tcp)
check("the config is written once", len(cfg.writes) == 1)
check("the runtime keys Reticulum adds are kept out of the saved file",
      all(k not in cfg.writes[0]["Default Interface"]
          for k in ("name", "selected_interface_mode", "configured_bitrate")))
check("and put back afterwards, since the running stack still uses them",
      default.get("name") == "Default Interface"
      and default.get("selected_interface_mode") == FULL)
check("the running AutoInterface switches to gateway now, not at the next start",
      parent.mode == GATEWAY)
check("and so does every peer it has already spawned", peer.mode == GATEWAY)
check("a running AutoInterface whose mode was chosen is not touched",
      other.mode == ROAMING)
check("a running non-AutoInterface is not touched", client.mode == FULL)

cfg = run({"Default Interface": Section(type="AutoInterface", mode="gateway")}, [])
check("nothing is written when there is nothing to change", cfg.writes == [])

legacy = Section(type="AutoInterface", interface_mode="full")
run({"Legacy": legacy}, [])
check("the older interface_mode key also counts as a choice",
      "mode" not in legacy and legacy["interface_mode"] == "full")

# --- the add-interface page --------------------------------------------------

vue = (ROOT / "src/frontend/components/interfaces/AddInterfacePage.vue").read_text(encoding="utf-8")
check("a new AutoInterface in the editor starts in gateway mode",
      'type === "AutoInterface"' in vue and 'sharedInterfaceSettings.mode = "gateway"' in vue)
check("but editing an existing one shows its real mode",
      "!this.isEditingInterface" in vue)

print(f"\n{len(ok)} passed, {len(fail)} failed")
if fail:
    for f in fail:
        print("  FAILED: " + f)
    sys.exit(1)
