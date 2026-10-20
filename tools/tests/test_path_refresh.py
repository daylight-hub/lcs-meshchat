#!/usr/bin/env python3
"""
Tests refresh_path, the repair for a route we already hold.

    python3 tools/tests/test_path_refresh.py

A path request cannot replace an entry Reticulum already has: the answer is a
replay of the announce the entry was built from, and Transport.inbound rejects an
announce it has heard before. So "request and wait for has_path" was a no-op --
has_path was already true, the wait returned on its first check, and the caller
was told a path had been found when nothing had answered.

refresh_path drops the entry first. That makes the replay acceptable, and it is
also what makes the result mean something: with the entry gone, has_path going
true again can only be a reply. The ordering is the whole feature, so it is what
these tests pin down, along with not leaving the peer worse off when the network
stays silent.
"""

import ast
import asyncio
import pathlib
import time
import types

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = ROOT / "meshchat.py"

tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
klass = next((n for n in ast.walk(tree)
              if isinstance(n, ast.ClassDef) and n.name == "ReticulumMeshChat"), None)
if klass is None:
    raise SystemExit("ReticulumMeshChat not found")

method = next((n for n in klass.body
               if isinstance(n, ast.AsyncFunctionDef) and n.name == "refresh_path"), None)
if method is None:
    raise SystemExit("refresh_path not found in meshchat.py")

ok, fail = [], []


def check(name, cond):
    (ok if cond else fail).append(name)
    print(("  ok   " if cond else " FAIL  ") + name)


class FakeLock:
    def __enter__(self): return self
    def __exit__(self, *a): return False


DEST = b"\x22" * 16
OLD_ENTRY = [1000.0, b"NEXTHOP", 2, 9999.0, [b"blob"], "iface", b"PKT"]


class Harness:
    """A stand-in for the RNS surfaces refresh_path touches.

    answers_after: how many has_path polls after the request before a path
    appears, or None for a network that never replies.
    clears_on_drop: whether the job loop actually culls the dropped entry.
    """

    def __init__(self, *, start_with_path=True, answers_after=None,
                 clears_on_drop=True):
        self.events = []
        self.table = {DEST: list(OLD_ENTRY)} if start_with_path else {}
        self.answers_after = answers_after
        self.clears_on_drop = clears_on_drop
        self.requested = 0
        self.dropped = 0
        self.polls_since_request = 0

        transport = types.SimpleNamespace()
        transport.path_table = self.table
        transport.path_table_lock = FakeLock()
        transport.has_path = self.has_path
        transport.request_path = self.request_path
        self.rns = types.SimpleNamespace(Transport=transport)

        self.reticulum = types.SimpleNamespace(drop_path=self.drop_path)

    def has_path(self, destination_hash):
        if self.requested:
            self.polls_since_request += 1
            if (self.answers_after is not None
                    and self.polls_since_request > self.answers_after
                    and destination_hash not in self.table):
                self.table[destination_hash] = ["fresh"]
                self.events.append("answered")
        return destination_hash in self.table

    def request_path(self, destination_hash):
        self.requested += 1
        self.events.append("request")

    def drop_path(self, destination_hash):
        self.dropped += 1
        self.events.append("drop")
        if self.clears_on_drop:
            self.table.pop(destination_hash, None)

    def run(self, timeout=1.0):
        ns = {
            "RNS": self.rns,
            "time": time,
            "asyncio": asyncio,
            "print": lambda *a, **k: None,
        }
        mod = ast.Module(body=[method], type_ignores=[])
        ast.fix_missing_locations(mod)
        exec(compile(mod, "<meshchat>", "exec"), ns)  # noqa: S102

        obj = types.SimpleNamespace(
            reticulum=self.reticulum,
            PATH_REFRESH_SETTLE_SECONDS=0.5,
            PATH_REFRESH_POLL_SECONDS=0.01,
        )
        return asyncio.run(ns["refresh_path"](obj, DEST, timeout))


# --- the ordering that makes the whole thing work ----------------------------
h = Harness(answers_after=1)
result = h.run()
check("a known path is dropped before anything is asked of the network",
      h.events[:2] == ["drop", "request"])
check("exactly one request goes out, since a transport node batches repeats",
      h.requested == 1)
check("a reply after the drop is reported as a refresh", result is True)

# --- a silent network must not cost us the route we had ----------------------
h = Harness(answers_after=None)
result = h.run(timeout=0.2)
check("no reply is reported as a failure, not as a path found", result is False)
check("and the entry we dropped is put back", h.table.get(DEST) == OLD_ENTRY)
check("the restored entry is the original, not a placeholder",
      h.table.get(DEST) is not None and h.table[DEST][1] == b"NEXTHOP")

# --- an announce that lands while we wait wins over the old entry ------------
h = Harness(answers_after=None)


def steal(destination_hash):
    h.events.append("drop")
    h.dropped += 1
    h.table.pop(destination_hash, None)
    # an announce arrives after the drop and installs a better route
    h.table[destination_hash] = ["from announce"]


h.reticulum.drop_path = steal
result = h.run(timeout=0.2)
check("a route learned while waiting is kept rather than overwritten",
      h.table.get(DEST) == ["from announce"])

# --- nothing held for this peer: no drop, just ask ---------------------------
h = Harness(start_with_path=False, answers_after=1)
result = h.run()
check("with no entry held, nothing is dropped", h.dropped == 0)
check("the request still goes out", h.requested == 1)
check("and a reply is reported", result is True)

h = Harness(start_with_path=False, answers_after=None)
check("with no entry held and no reply, the result is false",
      h.run(timeout=0.2) is False)

# --- the entry refusing to clear (shared instance) ---------------------------
h = Harness(clears_on_drop=False, answers_after=None)
result = h.run(timeout=0.3)
check("a drop that does not take effect still sends a request",
      h.requested == 1)
check("and falls back to the optimistic answer rather than a false negative",
      result is True)

print("\n{} passed, {} failed".format(len(ok), len(fail)))
raise SystemExit(1 if fail else 0)
