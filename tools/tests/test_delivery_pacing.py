#!/usr/bin/env python3
"""
Tests what makes a peer able to reach us, and when the delivery ladder moves.

    python3 tools/tests/test_delivery_pacing.py

The restart problem. Restoring the saved path table gives this node a route
out and nothing more. The route back lives in the path tables of the transport
nodes in between and of the peer itself, and a message only completes if those
hold a live route -- a delivery proof has to come home. Nothing local repairs
them, and a path request cannot either: the first node holding any entry
answers it from its own packet cache and stops it, so it never crosses a hop.

An announce is the only packet we emit that every transport node rebroadcasts
rather than consumes, and it carries a fresh emission timestamp, so it is
accepted over whatever stale entry each hop was holding. That makes it the only
thing that repairs the inbound half.

`last_announced_at` persists across a restart, so the auto-announce timer
carried on from before the restart and MeshChat could stay silent for the
remainder of the interval -- up to three hours on the old default -- while
every send failed waiting for a proof with no route home. Hence the startup
announce, and the shorter interval.

The ladder itself stays where it was in v2.0.7: the escalation to a link runs
from LXMF's failed callback, after LXMF's own opportunistic retries are spent.
v2.0.8 tried to cut those retries short with a watchdog that pulled messages
out of `pending_outbound` early, and that made sending worse rather than
faster. Liberty Chat does not do it either. The checks below pin the watchdog
out.
"""

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = ROOT / "meshchat.py"

source_text = SOURCE.read_text(encoding="utf-8")
tree = ast.parse(source_text)
klass = next((n for n in ast.walk(tree)
              if isinstance(n, ast.ClassDef) and n.name == "ReticulumMeshChat"), None)
if klass is None:
    raise SystemExit("ReticulumMeshChat not found in meshchat.py")

funcs = {n.name: n for n in klass.body
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

ARITHMETIC = (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Div, ast.Pow, ast.USub)


def const_value(node):
    """A constant's value, including one written as arithmetic."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ARITHMETIC):
        if const_value(node.left) is None or const_value(node.right) is None:
            return None
        return eval(compile(ast.Expression(node), "<const>", "eval"),  # noqa: S307
                    {"__builtins__": {}}, {})
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ARITHMETIC):
        return const_value(node.operand)
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


consts = {}
for node in klass.body:
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                value = const_value(node.value)
                if value is not None:
                    consts[target.id] = value

# config defaults live on their own class
config_class = next((n for n in ast.walk(tree)
                     if isinstance(n, ast.ClassDef) and n.name == "Config"), None)
defaults = {}
if config_class is not None:
    for node in config_class.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            args = [const_value(a) for a in node.value.args]
            if len(args) >= 2:
                defaults[target.id] = args[1]

ok, fail = [], []


def check(name, cond):
    (ok if cond else fail).append(name)
    print(("  ok   " if cond else " FAIL  ") + name)


def body_of(name):
    return ast.unparse(funcs[name]) if name in funcs else ""


# --- the startup announce ----------------------------------------------------

check("method present: startup_announce", "startup_announce" in funcs)

_startup = body_of("startup_announce")
check("it waits before announcing, so the interfaces are up first",
      "STARTUP_ANNOUNCE_DELAY_SECONDS" in _startup)
check("the wait is long enough for AutoInterface to have found its peers",
      consts.get("STARTUP_ANNOUNCE_DELAY_SECONDS", 0) >= 10)
check("it respects auto-announce being turned off entirely",
      "auto_announce_enabled" in _startup)
check("it is always on, not a setting",
      "announce_on_startup_enabled" not in source_text)
check("a restart moments after the last announce does not announce again",
      "STARTUP_ANNOUNCE_FLOOR_SECONDS" in _startup)
check("and that floor is long enough to cover a few restarts in a row",
      consts.get("STARTUP_ANNOUNCE_FLOOR_SECONDS", 0) >= 120)
check("a failing announce is reported rather than raised into the loop thread",
      "except Exception" in _startup)
check("it does not block the thread with a sleep",
      "time.sleep" not in _startup and "await asyncio.sleep" in _startup)

_loop = body_of("announce_loop")
check("the announce loop runs it before entering its wait",
      _loop.index("startup_announce") < _loop.index("while True"))


# The interval is the worst case for how long a peer can be unable to reach us
# across a transport node whose entry has gone stale, and on an RF leg the
# announce is the only repair there is. Liberty Chat moved to an hour for the
# same reason.
check("the auto-announce interval is an hour or less by default",
      defaults.get("auto_announce_interval_seconds", 99999) <= 3600)


# --- the ladder stays on the failed callback ---------------------------------

print()

check("the early-escalation watchdog is gone",
      "arm_opportunistic_escalation" not in source_text)
check("and so is its deadline setting",
      "opportunistic_escalation_seconds" not in source_text)
# Pulling a message out of pending_outbound from outside LXMF races the state
# machine that owns it. Nothing in here should be doing that.
check("nothing removes a message from LXMF's outbound queue behind its back",
      "pending_outbound.remove" not in source_text)

_failed = body_of("on_lxmf_sending_failed")
check("the escalation to a link still runs from the failure callback",
      "send_failed_message_over_direct_link" in _failed)
check("only an opportunistic send escalates, since a link already failed otherwise",
      "LXMF.LXMessage.OPPORTUNISTIC" in _failed)
# Liberty Chat checks both fields: desired_method is what was asked for, method
# is what LXMF used, and either being opportunistic means no transport node has
# a link table entry for this message.
check("both method fields are checked, matching Liberty Chat",
      "sent_opportunistically" in _failed
      and "getattr(lxmf_message, 'method', None)" in _failed
      and "getattr(lxmf_message, 'desired_method', None)" in _failed)
check("the link attempt comes before the path request, which cannot cross a hop",
      _failed.index("send_failed_message_over_direct_link")
      < _failed.index("queue_failed_message_for_path_request"))

_escalate = body_of("send_failed_message_over_direct_link")
check("escalating switches to a link, which is the rung that provokes a search",
      "LXMF.LXMessage.DIRECT" in _escalate)
check("and resets the send state so the attempt actually happens",
      "packed = None" in _escalate and "delivery_attempts = 0" in _escalate)
check("propagation stays armed, so this inserts a rung rather than replacing one",
      "try_propagation_on_fail" not in _escalate)
check("it is resubmitted off-thread, since this runs inside LXMF's own lock",
      "submit_outbound(lxmf_message)" in _escalate
      and "handle_outbound" not in _escalate)


# --- the link request button -------------------------------------------------

print()

_endpoint = ast.unparse(tree)
check("the route is sampled after the refresh and before the link attempt",
      "route_before = self.route_snapshot(destination_hash)" in _endpoint)
check("a failed link is followed by a second attempt",
      "link_retried = True" in _endpoint)
check("which waits for the search the first failure provoked",
      "wait_for_route_change" in _endpoint)
check("the retry is unconditional, not a setting",
      "link_request_retry_enabled" not in source_text)
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
