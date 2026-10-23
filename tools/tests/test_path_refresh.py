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
import sys
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

        # The cached announce is held open across the drop, so the five-minute
        # cache cleaner cannot delete it while the entry is unreferenced. The
        # filesystem side is covered separately; here it only needs to be
        # callable, and to happen in the right order.
        def cached_announce_for(entry):
            self.events.append("read_cache")
            return ("/cache/announce", b"announce")

        def restore_cached_announce(cached):
            self.events.append("restore_cache")

        obj = types.SimpleNamespace(
            reticulum=self.reticulum,
            PATH_REFRESH_SETTLE_SECONDS=0.5,
            PATH_REFRESH_POLL_SECONDS=0.01,
            cached_announce_for=cached_announce_for,
            restore_cached_announce=restore_cached_announce,
        )
        return asyncio.run(ns["refresh_path"](obj, DEST, timeout))


# --- the ordering that makes the whole thing work ----------------------------
h = Harness(answers_after=1)
result = h.run()
check("a known path is dropped before anything is asked of the network",
      h.events[:3] == ["read_cache", "drop", "request"])
# The cached announce has to be read while the entry still references it.
# clean_announce_cache() deletes any announce the path table does not point at
# and runs every five minutes, so reading after the drop could find it already
# gone -- and then the restore would put back an entry pointing at nothing.
check("and the cached announce is read before the drop, not after",
      h.events.index("read_cache") < h.events.index("drop"))
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

# --- the escalation rung -----------------------------------------------------
#
# A path request is answered from cache by the first transport node that holds
# an entry (Transport.py:3459, which precedes and excludes the recursive search
# at 3531), so it never crosses a hop. A failed link does: the transport node
# that relayed the LINKREQUEST takes the lr_taken_hops == 1 branch when the
# proof never arrives, and handle_disovery_path_requests then asks on every
# interface except the one it came in on (Transport.py:1260-1263). Opportunistic
# delivery builds no link, so none of that fires.

import ast as _ast

_tree = _ast.parse((ROOT / "meshchat.py").read_text(encoding="utf-8"))
_cls = next(n for n in _ast.walk(_tree)
            if isinstance(n, _ast.ClassDef) and n.name == "ReticulumMeshChat")
_funcs = {n.name: n for n in _cls.body
          if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))}


def _class_constants(class_node):
    """Class-level constants, skipping anything that is not a plain literal.

    literal_eval raises on an expression like `3 * 3600`, which is an ordinary
    way to write a constant, so a comprehension over every assignment in the
    class is a tripwire for whoever adds one next.
    """
    found = {}
    for node in class_node.body:
        if not isinstance(node, _ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, _ast.Name):
                continue
            try:
                found[target.id] = _ast.literal_eval(node.value)
            except Exception:
                pass
    return found


consts = _class_constants(_cls)


def _body(name):
    return _ast.unparse(_funcs[name]) if name in _funcs else ""


print()
check("method present: send_failed_message_over_direct_link",
      "send_failed_message_over_direct_link" in _funcs)

_failed = _body("on_lxmf_sending_failed")
check("a failed opportunistic send escalates to a link",
      "send_failed_message_over_direct_link" in _failed)
check("only opportunistic sends escalate, since a link already failed otherwise",
      "LXMF.LXMessage.OPPORTUNISTIC" in _failed)
check("the escalation is tried before the path request, which cannot cross a hop",
      _failed.index("send_failed_message_over_direct_link")
      < _failed.index("queue_failed_message_for_path_request"))
check("an already-propagated message is not escalated back to a link",
      "not already_propagated" in _failed)
check("the rung can be turned off",
      "direct_link_on_send_failure_enabled" in _failed)

_escalate = _body("send_failed_message_over_direct_link")
check("the escalation switches the delivery method to DIRECT",
      "LXMF.LXMessage.DIRECT" in _escalate)
check("and resets the LXMF send state so the attempt actually happens",
      "packed = None" in _escalate and "delivery_attempts = 0" in _escalate)
check("propagation stays armed, so this inserts a rung rather than replacing one",
      "try_propagation_on_fail" not in _escalate)
# Never inline: fail_message calls this from inside process_outbound's own
# outbound lock, and handle_outbound spins on that lock, so a direct call here
# deadlocks LXMF's outbound thread permanently.
check("the same message object is re-sent, so nothing is duplicated",
      "submit_outbound(lxmf_message)" in _escalate)
check("and it is resubmitted off-thread, since this runs inside LXMF's own lock",
      "handle_outbound" not in _escalate)

_slot = _body("path_entry_packet_slot")
check("the announce hash slot is located rather than hardcoded",
      "HASHLENGTH" in _slot and "IDX_PT_PACKET" not in _slot)
check("and is distinguished from the truncated hashes in the same entry",
      "len(value) == RNS.Identity.HASHLENGTH // 8" in _slot)



# --- announce when nothing answers -------------------------------------------
#
# A path request stops at the first transport node holding an entry, so an empty
# result means there is nothing further to ask. An announce is the opposite
# shape: rebroadcast by every node that hears it, carrying a fresh emission
# timestamp, so it is accepted over any existing entry at every hop. It repairs
# their route to us, and LXMF delivers over an inbound link it files under
# backchannel_links (LXMRouter.py:1997, used at 2777-2781), so their next
# message carries ours back out.

print()
for _n in ["announce_for_unreachable_peer", "clear_unreachable_announce", "probe_link"]:
    check("method present: " + _n, _n in _funcs)

_ann = _body("announce_for_unreachable_peer")
check("the announce is throttled per peer",
      "ANNOUNCE_ON_UNREACHABLE_COOLDOWN_SECONDS" in _ann)
check("and floored across peers, so a batch of failures is not a burst",
      "ANNOUNCE_ON_UNREACHABLE_FLOOR_SECONDS" in _ann)
check("the cooldown is recorded before announcing, so a slow announce cannot double-fire",
      _ann.index("announce_for_unreachable_at[destination_hash] = now")
      < _ann.index("await self.announce()"))
check("it can be turned off",
      "announce_on_unreachable_peer_enabled" in _ann)
check("a failing announce is reported rather than raised into the caller",
      "except Exception" in _ann)

_worker = _body("request_path_for_failed_messages")
check("an empty rediscovery announces instead of just giving up",
      "announce_for_unreachable_peer" in _worker)

_clear = _body("clear_path_request_attempts")
check("hearing from a peer clears its announce cooldown too",
      "clear_unreachable_announce" in _clear)

_probe = _body("probe_link")
check("the link is attempted even with no path, since the failure is the point",
      "has_path" not in _probe)
check("a link that comes up is handed to LXMF rather than wasted",
      "direct_links[destination_hash] = link" in _probe)
check("a link that does not come up is torn down",
      "link.teardown" in _probe)
check("a peer with no known identity is reported, not crashed on",
      "identity is None" in _probe)

check("announce budgets are sane: per-peer well above the global floor",
      consts["ANNOUNCE_ON_UNREACHABLE_COOLDOWN_SECONDS"]
      >= consts["ANNOUNCE_ON_UNREACHABLE_FLOOR_SECONDS"] * 5)
check("and the floor is long enough to protect a slow link",
      consts["ANNOUNCE_ON_UNREACHABLE_FLOOR_SECONDS"] >= 30)


print(f"\n{len(ok)} passed, {len(fail)} failed")
if fail:
    for f in fail:
        print("  FAILED: " + f)
    sys.exit(1)
