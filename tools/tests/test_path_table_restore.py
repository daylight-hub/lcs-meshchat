#!/usr/bin/env python3
"""
Tests the saved-path-table restore.

    python3 tools/tests/test_path_table_restore.py

Reticulum writes its path table on every clean shutdown but only reads it back
when transport mode is on, so a client restarted with transport off began with no
routes. This loads it regardless.

The valuable thing to check is the seven-element entry written into
Transport.path_table: its field order is defined by RNS's IDX_PT_* constants, and
getting it wrong would not fail loudly -- it would install corrupt routes. So the
real function is run against a stand-in RNS surface rather than only inspected.
"""

import ast
import pathlib
import sys
import tempfile
import types

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = ROOT / "meshchat.py"

import RNS.vendor.umsgpack as umsgpack

tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
klass = next((n for n in ast.walk(tree)
              if isinstance(n, ast.ClassDef) and n.name == "ReticulumMeshChat"), None)
if klass is None:
    raise SystemExit("ReticulumMeshChat not found")

wanted = {"restore_path_table", "is_path_blackholed"}
methods = {n.name: n for n in klass.body
           if isinstance(n, ast.FunctionDef) and n.name in wanted}
missing = wanted - set(methods)
if missing:
    raise SystemExit("missing from meshchat.py: " + ", ".join(sorted(missing)))

ok, fail = [], []


def check(name, cond):
    (ok if cond else fail).append(name)
    print(("  ok   " if cond else " FAIL  ") + name)


class FakeLock:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class Harness:
    """A stand-in for the RNS surfaces restore_path_table touches."""

    def __init__(self, entries, *, transport_on=False, shared=False,
                 interface=object(), packet=True, blackholed=None,
                 live=None, write_file=True):
        self.table = dict(live or {})
        self.restored_packets = []

        packet_obj = None
        if packet:
            packet_obj = types.SimpleNamespace(
                hops=3, packet_hash=b"PKT", unpack=lambda: True)

        transport = types.SimpleNamespace()
        transport.owner = types.SimpleNamespace(is_connected_to_shared_instance=shared)
        transport.path_table = self.table
        transport.path_table_lock = FakeLock()
        transport.find_interface_from_hash = lambda h: interface
        transport.get_cached_packet = lambda h, packet_type=None: packet_obj
        transport.blackholed_identities = list(blackholed or [])

        self.dir = tempfile.mkdtemp()
        if write_file:
            with open(self.dir + "/destination_table", "wb") as fh:
                fh.write(umsgpack.packb(entries))

        reticulum = types.SimpleNamespace(
            storagepath=self.dir,
            transport_enabled=staticmethod(lambda: transport_on),
            TRUNCATED_HASHLENGTH=128,
        )
        identity = types.SimpleNamespace(recall=lambda h, _no_use=False: ("ident", h))

        self.rns = types.SimpleNamespace(
            Transport=transport, Reticulum=reticulum, Identity=identity)
        self.interface = interface
        self.packet = packet_obj

    def run(self):
        ns = {"RNS": self.rns, "os": __import__("os"), "msgpack": umsgpack,
              "print": lambda *a, **k: None}
        mod = ast.Module(body=[methods["is_path_blackholed"], methods["restore_path_table"]],
                         type_ignores=[])
        ast.fix_missing_locations(mod)
        exec(compile(mod, "<meshchat>", "exec"), ns)  # noqa: S102
        obj = types.SimpleNamespace(
            is_path_blackholed=staticmethod(ns["is_path_blackholed"]))
        obj.is_path_blackholed = ns["is_path_blackholed"]
        return ns["restore_path_table"](obj)


# a saved entry: [dest, timestamp, received_from, hops, expires, blobs, if_hash, pkt_hash]
DEST = b"\x11" * 16
ENTRY = [DEST, 1000.0, b"NEXTHOP", 2, 9999.0, [b"blob"], b"IFHASH", b"PKT"]

# --- the happy path, and the field order that matters -------------------------
h = Harness([ENTRY])
count = h.run()
check("one saved entry is restored", count == 1)
check("and lands in the path table under its destination hash", DEST in h.table)

if DEST in h.table:
    row = h.table[DEST]
    check("the entry has exactly seven fields", len(row) == 7)
    check("field 0 is the timestamp", row[0] == 1000.0)
    check("field 1 is the next hop", row[1] == b"NEXTHOP")
    check("field 2 is the hop count", row[2] == 2)
    check("field 3 is the expiry", row[3] == 9999.0)
    check("field 4 is the random blobs", row[4] == [b"blob"])
    check("field 5 is the interface object, not its hash", row[5] is h.interface)
    check("field 6 is the announce packet hash", row[6] == b"PKT")
    check("the cached announce's hop count is incremented on restore",
          h.packet.hops == 4)

# --- the cases that must not restore -----------------------------------------
check("nothing is restored when another app owns the stack",
      Harness([ENTRY], shared=True).run() == 0)
check("nothing is restored when transport mode is on, since RNS already did it",
      Harness([ENTRY], transport_on=True).run() == 0)
check("no saved file means nothing to do",
      Harness([ENTRY], write_file=False).run() == 0)
check("an entry whose interface is gone is skipped",
      Harness([ENTRY], interface=None).run() == 0)
check("an entry whose cached announce has expired is skipped",
      Harness([ENTRY], packet=False).run() == 0)

# a blackholed identity must not have its route quietly restored
h = Harness([ENTRY], blackholed=[("ident", DEST)])
check("a blackholed identity's path is not restored", h.run() == 0)
check("and it is not written to the table", DEST not in h.table)

# --- a live entry is fresher than the file -----------------------------------
live = {DEST: ["LIVE"]}
h = Harness([ENTRY], live=live)
check("an entry already live is not overwritten", h.run() == 0)
check("and the live value is left intact", h.table[DEST] == ["LIVE"])

# --- malformed input must not lose the rest ----------------------------------
SHORT = [b"\x22" * 4, 1000.0, b"N", 1, 1.0, [], b"IF", b"PKT"]
OTHER = [b"\x33" * 16, 1000.0, b"N", 1, 1.0, [], b"IF", b"PKT"]
h = Harness([SHORT, ENTRY, OTHER])
count = h.run()
check(f"a wrong-length destination hash is skipped, the rest restored [{count}]",
      count == 2)

BROKEN = ["not-a-list"]
h = Harness([BROKEN, ENTRY])
check("a structurally broken row is skipped and the good one still restored",
      h.run() == 1)

h = Harness([])
check("an empty saved table restores nothing and does not raise", h.run() == 0)

print(f"\n{len(ok)} passed, {len(fail)} failed")
if fail:
    for f in fail:
        print("  FAILED: " + f)
    sys.exit(1)
