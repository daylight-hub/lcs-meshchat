#!/usr/bin/env python3
"""
Tests that reloading an AutoInterface does not destroy the routes learned on it.

    python3 tools/tests/test_path_preserving_reload.py

Transport.jobs() culls every path table entry whose attached interface has left
Transport.interfaces -- "removed since the attached interface no longer exists"
(Transport.py:983) -- and Reticulum._reload_interface is a detach followed by an
attach, so the interface object every entry points at is gone within a second of
a reload. The path table is only read from storage inside Transport.start, so a
reload, unlike a restart, has nothing behind it to recover from. Worse, MeshChat
persists the path table, so the loss gets written through to disk.

The two pure helpers are lifted by source and exercised directly; the rest is
checked structurally, since running it would need RNS, LXMF and a live
Reticulum instance.
"""

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = ROOT / "meshchat.py"

ok, fail = [], []


def check(label, condition):
    (ok if condition else fail).append(label)
    print(("  ok   " if condition else "  FAIL ") + label)


tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
klass = next((n for n in ast.walk(tree)
              if isinstance(n, ast.ClassDef) and n.name == "ReticulumMeshChat"), None)
if klass is None:
    raise SystemExit("ReticulumMeshChat not found in meshchat.py")

funcs = {n.name: n for n in klass.body
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def class_constants(class_node, ast_module=ast):
    """Class-level constants, skipping anything not a plain literal.

    Written as an expression over literal_eval, which raises on a value like
    `3 * 3600` and took the whole suite down with it the first time someone
    wrote a constant that way.
    """
    found = {}
    for node in class_node.body:
        if not isinstance(node, ast_module.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast_module.Name):
                continue
            try:
                found[target.id] = ast_module.literal_eval(node.value)
            except Exception:
                pass
    return found


consts = class_constants(klass)


def body_of(name):
    if name not in funcs:
        return ""
    return ast.unparse(funcs[name])


# ---------------------------------------------------------------------------
# The two pure helpers, lifted and run for real.
# ---------------------------------------------------------------------------

class FakeInterface:
    """Stands in for RNS.Interfaces.Interface.Interface."""
    def __init__(self, name=None, addr=None, ifname=None, parent=None):
        self.name = name
        if addr is not None:
            self.addr = addr
        if ifname is not None:
            self.ifname = ifname
        if parent is not None:
            self.parent_interface = parent


class FakeInterfaceModule:
    Interface = type("Inner", (), {"Interface": FakeInterface})


namespace = {"RNS": type("RNS", (), {"Interfaces": FakeInterfaceModule})}
for name in ["path_entry_interface_slot", "autointerface_peer_key"]:
    if name not in funcs:
        raise SystemExit("{} not found in meshchat.py".format(name))
    node = funcs[name]
    node.decorator_list = []
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, "<lifted>", "exec"), namespace)

slot_of = namespace["path_entry_interface_slot"]
key_of = namespace["autointerface_peer_key"]

print("\nFinding the interface slot in a path table entry")

iface = FakeInterface(name="AutoInterface")
# RNS 1.5.5 layout: timestamp, next_hop, hops, expires, randblobs, rcvd_if, packet
entry = [1000.0, b"\x01" * 8, 2, 2000.0, [], iface, b"\x02" * 16]
check("the slot is found in the current RNS layout [index 5]", slot_of(entry) == 5)

# the whole point of searching rather than hardcoding: layouts have moved
shifted = [1000.0, b"\x01" * 8, 2, iface, b"\x02" * 16]
check("and is still found when the layout shifts", slot_of(shifted) == 3)

check("an entry with no interface reports no slot, rather than guessing",
      slot_of([1000.0, b"\x01" * 8, 2, 2000.0, [], None, b""]) is None)
check("an empty entry does not raise", slot_of([]) is None)

print("\nIdentifying a spawned peer across a rebuild")

peer = FakeInterface(addr="fe80::1", ifname="eth0")
check("a peer is keyed by its local interface and link-local address",
      key_of(peer) == ("eth0", "fe80::1"))
check("the key is stable for an identical peer seen after a reload",
      key_of(peer) == key_of(FakeInterface(addr="fe80::1", ifname="eth0")))
check("a different address is a different peer",
      key_of(peer) != key_of(FakeInterface(addr="fe80::2", ifname="eth0")))
check("so is the same address on another local interface",
      key_of(peer) != key_of(FakeInterface(addr="fe80::1", ifname="eth1")))

# The parent AutoInterface has no addr/ifname, and its process_outgoing is a
# no-op, so there is nothing to rebind a route to. It must not produce a key.
check("the parent AutoInterface has no key, since it cannot carry traffic",
      key_of(FakeInterface(name="AutoInterface")) is None)
check("a half-formed peer has no key either",
      key_of(FakeInterface(addr="fe80::1")) is None)

# ---------------------------------------------------------------------------
# Structure.
# ---------------------------------------------------------------------------

print("\nThe reload preserves routes")

for name in ["snapshot_paths_for_interface", "spawned_peer_interfaces",
             "restore_paths_after_reload", "find_autointerface_by_name",
             "reload_autointerface"]:
    check("method present: " + name, name in funcs)

reload_body = body_of("reload_autointerface")

check("routes are snapshotted before the interface is torn down",
      reload_body.index("snapshot_paths_for_interface")
      < reload_body.index("reload_interface"))
check("and restored after it comes back",
      reload_body.index("reload_interface")
      < reload_body.index("restore_paths_after_reload"))

# A path request asks about a destination and says nothing about the asker, so
# it cannot repair the far side's route back to us. Only an announce does that,
# and every peer lost its route to us at the moment the interface was detached.
check("an announce follows the reload, since every peer lost its route to us",
      "self.announce()" in reload_body
      and reload_body.index("restore_paths_after_reload") < reload_body.index("self.announce()"))
check("a failing announce does not fail the reload",
      "could not announce after reloading" in reload_body)

check("persistence is suspended across the reload",
      "path_restore_in_progress = True" in reload_body)
check("and always resumed, so saving cannot stop permanently",
      "finally:" in reload_body and "path_restore_in_progress = False" in reload_body)

persist = body_of("schedule_path_table_persist")
check("the saver refuses to write while a restore is in flight",
      "path_restore_in_progress" in persist)

snapshot = body_of("snapshot_paths_for_interface")
check("the snapshot covers the parent's spawned peers, not just the parent",
      "parent_interface" in snapshot)
check("the interface slot is located rather than hardcoded",
      "path_entry_interface_slot" in snapshot
      and "IDX_PT_RVCD_IF" not in snapshot)
check("entries with no rebindable peer are skipped rather than stored",
      "key is None" in snapshot)
check("the snapshot copies each entry, so later culling cannot empty it",
      "list(entry)" in snapshot)

restore = body_of("restore_paths_after_reload")
check("the restore waits for peers to come back before giving up",
      "AUTOINTERFACE_PATH_RESTORE_TIMEOUT_SECONDS" in restore)
check("a route relearned while waiting wins over the snapshot",
      "in RNS.Transport.path_table" in restore and "continue" in restore)
check("a route whose peer did not return is left dropped, not faked",
      "interface is None" in restore)
check("restored entries are rebound to the new peer object",
      "entry[slot] = interface" in restore)

print("\nBudgets")

check("the restore timeout covers a full peer discovery round",
      consts.get("AUTOINTERFACE_PATH_RESTORE_TIMEOUT_SECONDS", 0) >= 22)
check("and is bounded, so a reload cannot block forever",
      consts.get("AUTOINTERFACE_PATH_RESTORE_TIMEOUT_SECONDS", 999) <= 120)
check("polling is frequent enough to be responsive",
      0 < consts.get("AUTOINTERFACE_PATH_RESTORE_POLL_SECONDS", 99) <= 2.0)

print(f"\n{len(ok)} passed, {len(fail)} failed")
if fail:
    for f in fail:
        print("  FAILED: " + f)
    sys.exit(1)
