#!/usr/bin/env python3
"""
Tests how long a send is allowed to go nowhere before the ladder moves on.

    python3 tools/tests/test_delivery_pacing.py

Two timings are pinned here, both about the same thing: the useful step was
queued behind the useless one.

Sending. A message goes out opportunistically first, as a single packet, which
is right when the route is good. When it is not, LXMF's opportunistic branch
repeats that packet up to MAX_DELIVERY_ATTEMPTS (5) at DELIVERY_RETRY_WAIT
(10s) apart, with one drop-and-rediscover and a PATH_REQUEST_WAIT (7s) pause
folded in, all paced by a PROCESSING_INTERVAL (4s) job loop -- about a minute
before fail_message fires. fail_message is what starts the link attempt, and
the link attempt is the only step in the whole ladder that makes a transport
node go and ask the rest of the network. So the thing that could fix it waits
behind five repeats of the thing that cannot.

The Link Request button. The same inversion in miniature. A link request that
goes unanswered is what provokes the search, so the route it finds lands
seconds after the attempt that failed. Reporting failure at that moment
describes the network as it was before the button was pressed.
"""

import ast
import pathlib
import sys
import threading
import time
import types

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = ROOT / "meshchat.py"

tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
klass = next((n for n in ast.walk(tree)
              if isinstance(n, ast.ClassDef) and n.name == "ReticulumMeshChat"), None)
if klass is None:
    raise SystemExit("ReticulumMeshChat not found in meshchat.py")

funcs = {n.name: n for n in klass.body
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

ok, fail = [], []


def check(name, cond):
    (ok if cond else fail).append(name)
    print(("  ok   " if cond else " FAIL  ") + name)


def body_of(name):
    return ast.unparse(funcs[name]) if name in funcs else ""


def lift(name, namespace):
    if name not in funcs:
        raise SystemExit(name + " not found in meshchat.py")
    mod = ast.Module(body=[funcs[name]], type_ignores=[])
    ast.fix_missing_locations(mod)
    exec(compile(mod, "<meshchat>", "exec"), namespace)  # noqa: S102
    return namespace[name]


# the LXMessage state and method constants, by value, so the lifted code
# compares against the same things it will at runtime
class FakeLXMessage:
    OPPORTUNISTIC = 0x01
    DIRECT = 0x02
    PROPAGATED = 0x03
    GENERATING = 0x00
    OUTBOUND = 0x01
    SENDING = 0x02
    SENT = 0x04
    DELIVERED = 0x08
    REJECTED = 0xFD
    CANCELLED = 0xFE
    FAILED = 0xFF


FakeLXMF = types.SimpleNamespace(LXMessage=FakeLXMessage)


class FakeConfigValue:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class FakeMessage:
    def __init__(self, method=FakeLXMessage.OPPORTUNISTIC, state=FakeLXMessage.OUTBOUND):
        self.desired_method = method
        self.state = state
        self.destination_hash = b"\x11" * 16


class Harness:
    """Enough of the app for the escalation watchdog to run, with the
    deadline set to a fraction of a second so the test does not wait."""

    def __init__(self, *, deadline=0.2, enabled=True, queued=True,
                 message=None):
        self.message = message if message is not None else FakeMessage()
        self.escalated = []
        self.config = types.SimpleNamespace(
            opportunistic_escalation_seconds=FakeConfigValue(deadline),
            direct_link_on_send_failure_enabled=FakeConfigValue(enabled),
        )
        self.message_router = types.SimpleNamespace(
            pending_outbound=[self.message] if queued else [],
            outbound_processing_lock=threading.Lock(),
        )
        self.OPPORTUNISTIC_ESCALATION_POLL_SECONDS = 0.02

    def send_failed_message_over_direct_link(self, lxmf_message):
        self.escalated.append(lxmf_message)


arm_ns = {
    "LXMF": FakeLXMF,
    "time": time,
    "threading": threading,
    "print": lambda *a, **k: None,
}
arm = lift("arm_opportunistic_escalation", arm_ns)


def run(h, wait=0.6):
    arm(h, h.message)
    time.sleep(wait)


# --- the deadline ------------------------------------------------------------

h = Harness()
run(h)
check("a send that has gone nowhere by the deadline is escalated",
      len(h.escalated) == 1)
check("and is taken out of the outbound queue, so LXMF does not send it twice",
      h.message not in h.message_router.pending_outbound)

h = Harness()
arm(h, h.message)
h.message.state = FakeLXMessage.DELIVERED
time.sleep(0.6)
check("a send that lands before the deadline is left alone", h.escalated == [])
check("and stays in the queue for LXMF to retire normally",
      h.message in h.message_router.pending_outbound)

h = Harness()
arm(h, h.message)
h.message.state = FakeLXMessage.FAILED
time.sleep(0.6)
check("a send LXMF already failed is left to the failure callback",
      h.escalated == [])

h = Harness()
arm(h, h.message)
h.message.state = FakeLXMessage.CANCELLED
time.sleep(0.6)
check("a cancelled send is not revived", h.escalated == [])

# SENT is not a finish line for an opportunistic message: the packet is out,
# but LXMF keeps it queued and keeps retrying until a proof comes back, so
# treating it as settled would disarm the watchdog on every single send
h = Harness()
arm(h, h.message)
h.message.state = FakeLXMessage.SENT
time.sleep(0.6)
check("a sent-but-unproven opportunistic packet is still escalated",
      len(h.escalated) == 1)

# --- what must not be escalated ---------------------------------------------

print()

h = Harness(message=FakeMessage(method=FakeLXMessage.DIRECT))
run(h)
check("a direct send is not escalated, since it is already on that rung",
      h.escalated == [])

h = Harness(message=FakeMessage(method=FakeLXMessage.PROPAGATED))
run(h)
check("a propagated send is not escalated to a link to the recipient",
      h.escalated == [])

h = Harness(enabled=False)
run(h)
check("nothing happens when the link rung is turned off", h.escalated == [])

h = Harness(deadline=0)
run(h, wait=0.3)
check("a deadline of zero leaves LXMF's own ladder alone", h.escalated == [])

h = Harness(queued=False)
run(h)
check("a message no longer in the queue is not escalated out from under LXMF",
      h.escalated == [])

# the method can be changed by a failure that beats the deadline
h = Harness()
arm(h, h.message)
h.message.desired_method = FakeLXMessage.DIRECT
time.sleep(0.6)
check("a send already moved to a link by a failure is not moved again",
      h.escalated == [])


# --- wiring ------------------------------------------------------------------

print()

_arm = body_of("arm_opportunistic_escalation")
check("the queue is only touched under the router's own outbound lock",
      "outbound_processing_lock" in _arm)
check("the deadline is configurable rather than baked in",
      "opportunistic_escalation_seconds" in _arm)
check("the watchdog runs on its own thread, not the event loop",
      "threading.Thread" in _arm and "daemon=True" in _arm)

_send = body_of("send_message")
check("a new send arms the deadline", "arm_opportunistic_escalation" in _send)

_submit = body_of("submit_outbound")
check("a resubmitted send arms it too, so a retry is paced the same way",
      "arm_opportunistic_escalation" in _submit)

_escalate = body_of("send_failed_message_over_direct_link")
check("escalating switches to a link, which is the rung that provokes a search",
      "LXMF.LXMessage.DIRECT" in _escalate)
check("and leaves propagation armed, so this shortens a wait rather than "
      "removing a fallback",
      "try_propagation_on_fail" not in _escalate)


# --- the link request button -------------------------------------------------

print()

_endpoint = ast.unparse(tree)
check("the route is sampled after the refresh and before the link attempt",
      "route_before = self.route_snapshot(destination_hash)" in _endpoint)
check("a failed link is followed by a second attempt",
      "link_retried = True" in _endpoint)
check("which waits for the search the first failure provoked",
      "wait_for_route_change" in _endpoint)
check("the retry can be turned off", "link_request_retry_enabled" in _endpoint)
check("the announce is still the last resort, after both attempts",
      _endpoint.index("link_retried = True")
      < _endpoint.index("announced = await self.announce_for_unreachable_peer"))

_snapshot = body_of("route_snapshot")
check("a route is identified by the announce behind it, not by has_path",
      "path_entry_packet_slot" in _snapshot and "has_path" not in _snapshot)
check("and by hop count, which also moves when a route is relearned",
      "hops_to" in _snapshot)
check("the path table is read under its own lock",
      "path_table_lock" in _snapshot)

_wait = body_of("wait_for_route_change")
check("the wait gives up rather than hanging on a silent network",
      "deadline" in _wait and "return False" in _wait)
check("and yields to the event loop while it waits",
      "await asyncio.sleep" in _wait)

# giving up on the wait must not mean giving up on the retry: a route can be
# repaired further out without our own entry changing at all
_retry_block = _endpoint[_endpoint.index("route_changed = await self.wait_for_route_change"):]
check("the second attempt happens whether or not our own route changed",
      _retry_block.index("link_retried = True")
      < _retry_block.index("await self.probe_link"))


print(f"\n{len(ok)} passed, {len(fail)} failed")
if fail:
    for f in fail:
        print("  FAILED: " + f)
    sys.exit(1)
