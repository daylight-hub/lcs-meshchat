#!/usr/bin/env python3
"""
Tests the throttling on path-request-on-send-failure.

    python3 tools/tests/test_path_request_throttle.py

This is the part of the feature that can misbehave expensively. A resend creates
fresh messages, each of which can fail and call straight back into the same code,
so without a cooldown and an attempt cap one unreachable peer would issue path
requests in a loop -- on a LoRa link that is other people's airtime.

The decision is a pure classmethod on ReticulumMeshChat, so it is lifted out of
meshchat.py by source rather than importing the module, which would need RNS,
LXMF, LXST and a Reticulum instance.
"""

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = ROOT / "meshchat.py"

CONSTANTS = [
    "PATH_REQUEST_COOLDOWN_SECONDS",
    "PATH_REQUEST_MAX_ATTEMPTS",
    "PATH_REQUEST_TIMEOUT_SECONDS",
    "PATH_REQUEST_RESET_SECONDS",
]


def load_decision():
    """Build a stand-in class carrying the real constants and the real method."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))

    cls = next((n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == "ReticulumMeshChat"), None)
    if cls is None:
        raise SystemExit("ReticulumMeshChat not found in meshchat.py")

    wanted = {}
    method = None
    for node in cls.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in CONSTANTS:
                    wanted[target.id] = ast.literal_eval(node.value)
        if isinstance(node, ast.FunctionDef) and node.name == "next_path_request_attempt":
            method = node

    missing = [c for c in CONSTANTS if c not in wanted]
    if missing:
        raise SystemExit("missing constants in meshchat.py: " + ", ".join(missing))
    if method is None:
        raise SystemExit("next_path_request_attempt not found in meshchat.py")

    # drop the @classmethod decorator; it is re-applied below
    method.decorator_list = []
    module = ast.Module(body=[method], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {}
    exec(compile(module, "<meshchat>", "exec"), namespace)  # noqa: S102

    attrs = dict(wanted)
    attrs["next_path_request_attempt"] = classmethod(namespace["next_path_request_attempt"])
    return type("Decision", (), attrs)


D = load_decision()

ok, fail = [], []


def check(name, cond):
    (ok if cond else fail).append(name)
    print(("  ok   " if cond else " FAIL  ") + name)


print(f"    cooldown={D.PATH_REQUEST_COOLDOWN_SECONDS}s "
      f"max={D.PATH_REQUEST_MAX_ATTEMPTS} "
      f"timeout={D.PATH_REQUEST_TIMEOUT_SECONDS}s "
      f"reset={D.PATH_REQUEST_RESET_SECONDS}s")

NOW = 1_000_000.0

# --- the thresholds are sane relative to each other ----------------------------
check("cooldown is longer than the request timeout, so attempts cannot overlap",
      D.PATH_REQUEST_COOLDOWN_SECONDS > D.PATH_REQUEST_TIMEOUT_SECONDS)
check("reset window is longer than the whole attempt budget",
      D.PATH_REQUEST_RESET_SECONDS
      > D.PATH_REQUEST_COOLDOWN_SECONDS * D.PATH_REQUEST_MAX_ATTEMPTS)
check("at least one attempt is allowed", D.PATH_REQUEST_MAX_ATTEMPTS >= 1)

# --- first failure for an unseen destination -----------------------------------
allowed, attempt = D.next_path_request_attempt(None, NOW)
check("a destination never seen before is allowed through", allowed is True)
check("the stored attempt records the time and a count of 1",
      attempt == {"at": NOW, "count": 1})

# --- the burst a single resend produces ----------------------------------------
# resend_failed_messages_for_destination sends every failed message, so several
# failures land within milliseconds. Only the first may reach the network.
state = None
granted = 0
for i in range(25):
    allowed, state = D.next_path_request_attempt(state, NOW + i * 0.01)
    if allowed:
        granted += 1
check(f"25 failures in a quarter of a second grant exactly 1 request [{granted}]",
      granted == 1)

# --- repeated failures over a long outage --------------------------------------
state = None
granted = 0
t = NOW
# one failure a second for an hour
for _ in range(3600):
    allowed, state = D.next_path_request_attempt(state, t)
    if allowed:
        granted += 1
    t += 1
check(f"an hour of continuous failure grants at most MAX_ATTEMPTS per reset window "
      f"[{granted}]",
      granted <= D.PATH_REQUEST_MAX_ATTEMPTS
      * (1 + 3600 // D.PATH_REQUEST_RESET_SECONDS))
check("and grants at least MAX_ATTEMPTS, so it does try",
      granted >= D.PATH_REQUEST_MAX_ATTEMPTS)

# --- the cap is exactly MAX_ATTEMPTS when spaced past the cooldown -------------
state = None
granted = 0
t = NOW
for _ in range(10):
    allowed, state = D.next_path_request_attempt(state, t)
    if allowed:
        granted += 1
    t += D.PATH_REQUEST_COOLDOWN_SECONDS + 1
check(f"ten well-spaced failures stop at MAX_ATTEMPTS [{granted}]",
      granted == D.PATH_REQUEST_MAX_ATTEMPTS)

# --- exhausted, then a quiet spell --------------------------------------------
state = {"at": NOW, "count": D.PATH_REQUEST_MAX_ATTEMPTS}
allowed, _ = D.next_path_request_attempt(state, NOW + D.PATH_REQUEST_COOLDOWN_SECONDS + 1)
check("an exhausted destination is refused even once the cooldown passes",
      allowed is False)

allowed, attempt = D.next_path_request_attempt(
    state, NOW + D.PATH_REQUEST_RESET_SECONDS + 1)
check("after the reset window it is allowed again", allowed is True)
check("and the count restarts at 1", attempt["count"] == 1)

# --- boundaries ---------------------------------------------------------------
allowed, _ = D.next_path_request_attempt(
    {"at": NOW, "count": 1}, NOW + D.PATH_REQUEST_COOLDOWN_SECONDS - 0.001)
check("refused just inside the cooldown", allowed is False)

allowed, _ = D.next_path_request_attempt(
    {"at": NOW, "count": 1}, NOW + D.PATH_REQUEST_COOLDOWN_SECONDS + 0.001)
check("allowed just past the cooldown", allowed is True)

# --- a cleared destination behaves like a new one -----------------------------
# clear_path_request_attempts pops the key, so the next lookup yields None
allowed, attempt = D.next_path_request_attempt(None, NOW + 5)
check("a cleared destination gets a full budget again",
      allowed is True and attempt["count"] == 1)

# --- refusal must not mutate the stored record --------------------------------
original = {"at": NOW, "count": 2}
allowed, returned = D.next_path_request_attempt(dict(original), NOW + 1)
check("a refusal returns the record unchanged",
      allowed is False and returned == original)




# ------------------------------------------------------------------------------
# Ordering and queue behaviour, read out of the source.
#
# These are structural checks rather than behavioural ones: exercising the real
# queue needs an LXMF router and a Reticulum instance. They exist because the
# ordering between a path request and the propagation fallback is the part most
# likely to be silently reversed by a later edit, and a reversal is invisible
# until someone's message is sitting on a propagation node that was never needed.
# ------------------------------------------------------------------------------

source = SOURCE.read_text(encoding="utf-8")
tree = ast.parse(source)
klass = next(n for n in ast.walk(tree)
             if isinstance(n, ast.ClassDef) and n.name == "ReticulumMeshChat")
funcs = {n.name: n for n in klass.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def body_of(name):
    assert name in funcs, "missing method: " + name
    return ast.get_source_segment(source, funcs[name]) or ""


# class-level constants, skipping anything that is not a plain literal
consts = {}
for _node in klass.body:
    if not isinstance(_node, ast.Assign):
        continue
    for _target in _node.targets:
        if not isinstance(_target, ast.Name):
            continue
        try:
            consts[_target.id] = ast.literal_eval(_node.value)
        except Exception:
            pass


print()
for name in ["on_lxmf_sending_failed", "queue_failed_message_for_path_request",
             "request_path_for_failed_messages", "resolve_pending_path_request",
             "retry_failed_message", "clear_path_request_attempts"]:
    check("method present: " + name, name in funcs)

failed = body_of("on_lxmf_sending_failed")

# the path request must be reached before the propagation fallback
check("the failure handler tries the path request before propagating",
      failed.index("queue_failed_message_for_path_request")
      < failed.index("send_failed_message_via_propagation_node"))

# Recovering the route after a failure is no longer optional. As a setting it
# could be turned off, and then a message that failed on a stale path waited
# for the peer's next announce -- hours away -- which is indistinguishable
# from the message being lost.
check("recovering the route after a failure is not a setting any more",
      "path_request_on_send_failure_enabled" not in SOURCE.read_text(encoding="utf-8"))

# with no propagation node configured there is nothing to ask a route about, so
# the message still falls through to whatever it was told to do on failure
check("propagation still happens when there is no node to recover a route to",
      "wants_propagation" in failed
      and "send_failed_message_via_propagation_node" in failed)

# A message that already went to a propagation node and failed did so because the
# propagation node was unreachable, not the recipient. LXMF requests a path to its
# own propagation node and retries that itself, so asking here would target the
# wrong destination and the retry would only repeat the propagation attempt.
check("an already-propagated message does not ask about the recipient",
      "already_propagated" in failed
      and "not already_propagated" in failed)
check("and that check reads the delivery method, not the fallback flag",
      "desired_method" in failed and "PROPAGATED" in failed)

# It asks about the node instead. LXMF does not cover this: its propagated branch
# requests a path only when it has none, so against a stale entry it goes straight
# to RNS.Link, fails, and retries the same dead route until the attempts run out.
# There is no drop-and-rediscover there either -- that is opportunistic-only. The
# node was the one destination in the ladder with no recovery at all.
check("a failed propagated message asks for a path to the propagation node",
      "get_outbound_propagation_node" in failed
      and "path_destination_hash" in failed)
check("and does nothing when no propagation node is configured",
      "propagation_node is None" in failed)

queue_signature = source.split("def queue_failed_message_for_path_request(")[1].split(")")[0]
check("the queue can be keyed on a destination other than the recipient",
      "path_destination_hash" in queue_signature)

updated = body_of("on_lxmf_sending_state_updated")
check("a propagated message that was accepted resets the node's attempts too",
      "get_outbound_propagation_node" in updated
      and "clear_path_request_attempts" in updated)

queue = body_of("queue_failed_message_for_path_request")

check("a request already in flight does not start a second one",
      "path_requests_in_flight" in queue)
check("a throttled destination resolves immediately instead of stalling",
      "if not allowed" in queue and "resolve_pending_path_request" in queue)
check("a full queue falls back to propagation rather than dropping the message",
      "PATH_REQUEST_MAX_PENDING" in queue
      and "send_failed_message_via_propagation_node" in queue)

worker = body_of("request_path_for_failed_messages")

check("the worker always resolves its queue, even on error",
      "finally:" in worker and "resolve_pending_path_request" in worker)
check("the in-flight marker is always cleared",
      "path_requests_in_flight.discard" in worker)
# The worker used to call request_path directly and then poll has_path. That could
# never work against the entry it exists to replace: the reply is a replay of the
# announce the entry was built from, which Reticulum discards as already heard, and
# has_path was true throughout, so the poll returned at once and the message was
# retried over the route that had just failed. refresh_path drops the entry first.
check("the worker refreshes the route rather than only asking for it",
      "refresh_path" in worker)
check("and no longer polls has_path itself, which could not detect a change",
      "RNS.Transport.has_path" not in worker)
check("the bare request_path call is gone from the worker",
      "RNS.Transport.request_path" not in worker)

resolve = body_of("resolve_pending_path_request")

check("a found path retries the message rather than propagating it",
      "retry_failed_message" in resolve)
check("no path falls back to propagation where the message has one",
      "wants_propagation" in resolve
      and "send_failed_message_via_propagation_node" in resolve)
check("the queue is removed as it is resolved, so nothing is handled twice",
      "pending_path_requests.pop" in resolve)

retry = body_of("retry_failed_message")

check("the retry re-sends the same message object, so nothing is duplicated",
      "submit_outbound(lxmf_message)" in retry)
check("the retry does not change the delivery method, leaving propagation armed",
      "desired_method" not in retry)
check("the retry resets the LXMF send state the way the propagation fallback does",
      "packed = None" in retry and "delivery_attempts = 0" in retry)

# The last rung is its own case on both outcomes. A message already aimed at a
# propagation node has to go back out as propagated rather than as whatever it
# was before, and when the node stays unreachable there is no further fallback
# to hand it to -- so it used to fall off the bottom of the resolve loop and do
# nothing at all, which is how a propagated message could vanish silently.
for name in ["resolve_propagated_message", "propagation_node_stamp_cost"]:
    check("method present: " + name, name in funcs)

check("an already-propagated message is resolved by its own branch",
      "already_propagated" in resolve and "resolve_propagated_message" in resolve)
check("that branch is reached before the generic retry, which would re-send "
      "a propagated message as whatever it used to be",
      resolve.index("resolve_propagated_message") < resolve.index("retry_failed_message"))
check("nothing falls off the bottom of the loop unreported",
      "else:" in resolve and "leaving the message failed" in resolve)

propagated = body_of("resolve_propagated_message")

check("no route to the node leaves the message failed rather than re-sending",
      "if not path_found" in propagated and "return" in propagated)
check("a recovered route re-sends as propagated, not as the original method",
      "send_failed_message_via_propagation_node" in propagated)

# LXMF will not queue a propagated message until it has built a propagation
# stamp, and it reads the cost for that out of the node's cached announce rather
# than off the wire. With no usable copy, process_deferred_stamps fails the
# message before any link is attempted -- a delivery failure with no delivery
# tried. Re-sending into that is pointless, so the cost is checked first.
check("the stamp cost is checked before re-sending, since LXMF fails without it",
      "propagation_node_stamp_cost" in propagated
      and propagated.index("propagation_node_stamp_cost")
      < propagated.index("send_failed_message_via_propagation_node"))
check("an unusable announce is reported rather than retried into",
      "stamp_cost is None" in propagated)

cost = body_of("propagation_node_stamp_cost")

check("the cost is read from the same cached announce LXMF reads it from",
      "recall_app_data" in cost)
check("and validated the way LXMF validates it, so None means LXMF would fail too",
      "pn_announce_data_is_valid" in cost)
check("a missing validator does not crash the failure path",
      "getattr(LXMF" in cost)
check("every read is guarded, since this runs inside a failure handler",
      cost.count("except Exception") >= 2)

handoff = body_of("send_failed_message_via_propagation_node")

check("the first hand-off also warns when no stamp cost is cached",
      "propagation_node_stamp_cost" in handoff)
check("and the warning cannot break the hand-off itself",
      "except Exception" in handoff
      and handoff.index("except Exception") < handoff.index("submit_outbound"))




# ------------------------------------------------------------------------------
# Startup path warming and debounced persistence.
#
# Reticulum saves its path table on clean shutdown but Transport.start() only
# reads it back when transport mode is enabled, and that defaults to off. So a
# client restart begins with no paths. These check the two mitigations: asking
# for the paths that matter at startup, and writing the table as paths are
# learned rather than only every 12 hours.
# ------------------------------------------------------------------------------

WARM = ["PATH_WARM_START_DELAY_SECONDS", "PATH_WARM_INTERVAL_SECONDS",
        "PATH_WARM_MAX_DESTINATIONS", "PATH_WARM_MAX_AGE_DAYS",
        "PATH_PERSIST_DEBOUNCE_SECONDS", "PATH_PERSIST_MIN_INTERVAL_SECONDS"]

warm = {}
for node in klass.body:
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in WARM:
                warm[target.id] = ast.literal_eval(node.value)

print()
for name in WARM:
    check("constant present: " + name, name in warm)

if len(warm) == len(WARM):
    print(f"    warm: delay={warm['PATH_WARM_START_DELAY_SECONDS']}s "
          f"interval={warm['PATH_WARM_INTERVAL_SECONDS']}s "
          f"max={warm['PATH_WARM_MAX_DESTINATIONS']} "
          f"age={warm['PATH_WARM_MAX_AGE_DAYS']}d")
    print(f"    persist: debounce={warm['PATH_PERSIST_DEBOUNCE_SECONDS']}s "
          f"floor={warm['PATH_PERSIST_MIN_INTERVAL_SECONDS']}s")

    # the whole warm run must finish in a sane time, and must not be a burst
    total = (warm["PATH_WARM_START_DELAY_SECONDS"]
             + warm["PATH_WARM_MAX_DESTINATIONS"] * warm["PATH_WARM_INTERVAL_SECONDS"])
    check(f"a full warm run spreads over a minute or two, not a burst [{total:.0f}s]",
          60 <= total <= 180)
    check("requests are spaced at least a second apart, for slow links",
          warm["PATH_WARM_INTERVAL_SECONDS"] >= 1.0)
    check("the startup delay lets interfaces come up first",
          warm["PATH_WARM_START_DELAY_SECONDS"] >= 5)
    check("the peer cap is bounded, so a large history cannot flood the link",
          1 <= warm["PATH_WARM_MAX_DESTINATIONS"] <= 50)
    check("the persist floor is well above the debounce, so bursts collapse",
          warm["PATH_PERSIST_MIN_INTERVAL_SECONDS"]
          >= warm["PATH_PERSIST_DEBOUNCE_SECONDS"] * 4)

for name in ["recent_conversation_destination_hashes", "warm_paths_for_known_peers",
             "schedule_path_table_persist", "persist_path_table_after_quiet_period"]:
    check("method present: " + name, name in funcs)

warm_body = body_of("warm_paths_for_known_peers")
# Off, and no longer a setting. The saved path table covers what it would have
# warmed, and a path request cannot repair anything past the first hop anyway
# -- the startup announce is what does that. Left in the source behind a
# constant rather than deleted.
check("warming is off behind a constant, not a setting",
      "PATH_WARM_ON_STARTUP" in warm_body
      and "path_warm_on_startup_enabled" not in warm_body)
check("and the constant is off",
      consts.get("PATH_WARM_ON_STARTUP") is False)
check("warming skips peers that already have a path, so it costs nothing when idle",
      "has_path" in warm_body)
check("warming sleeps between requests rather than firing them all at once",
      "asyncio.sleep(self.PATH_WARM_INTERVAL_SECONDS)" in warm_body)

recent = body_of("recent_conversation_destination_hashes")
check("the peer list excludes this node's own addresses",
      "own_hashes" in recent)
check("and is bounded by both a count and an age",
      "limit" in recent and "max_age_days" in recent)
check("the SQL is parameterised rather than string-formatted",
      "execute_sql(query, (" in recent)

sched = body_of("schedule_path_table_persist")
check("a pending write is not scheduled twice",
      "path_persist_pending" in sched)
check("a shared instance is left alone, since it does not own the path table",
      "is_connected_to_shared_instance" in sched)
# Saving learned paths is always on now. Reticulum otherwise writes its path
# table only on a clean shutdown or every 12 hours, so turning this off meant a
# hard kill threw away most of what had been learned.
check("saving learned paths is not a setting any more",
      "persist_paths_on_discovery_enabled" not in sched)

persist = body_of("persist_path_table_after_quiet_period")
check("the write is debounced",
      "PATH_PERSIST_DEBOUNCE_SECONDS" in persist)
check("and floored by a minimum interval",
      "PATH_PERSIST_MIN_INTERVAL_SECONDS" in persist)
check("disk I/O is kept off the event loop",
      "asyncio.to_thread" in persist)
check("the pending flag is always cleared, so writes cannot stop permanently",
      "finally:" in persist and "path_persist_pending = False" in persist)


# ------------------------------------------------------------------------------
# Resubmitting to LXMF without deadlocking it or freezing the UI.
#
# handle_outbound spins on the router's outbound lock with a blocking sleep:
#
#     while not unknown_path_requested and self.outbound_processing_lock.locked():
#         time.sleep(0.05)
#
# fail_message runs inside that lock (LXMRouter.py:2684, failing at 2761, 2842,
# 2851, 2899) and calls failed_callback synchronously, so a resubmit from a
# failure handler waits on a lock its own call stack holds and spins forever,
# killing LXMF's outbound thread. On the asyncio loop the same spin freezes the
# web server, which empties the UI. Neither is allowed to happen again.
# ------------------------------------------------------------------------------

print()
check("method present: submit_outbound", "submit_outbound" in funcs)
check("method present: active_delivery_link_available",
      "active_delivery_link_available" in funcs)

submit = body_of("submit_outbound")
check("the resubmit runs on its own thread, not the caller's",
      "threading.Thread" in submit and "daemon=True" in submit)
check("and cannot raise into LXMF's outbound thread",
      "except Exception" in submit)

for name in ["send_failed_message_over_direct_link",
             "send_failed_message_via_propagation_node",
             "retry_failed_message"]:
    b = body_of(name)
    check("{} resubmits off-thread".format(name), "submit_outbound" in b)
    check("{} never calls handle_outbound inline".format(name),
          "handle_outbound" not in b)

source = SOURCE.read_text(encoding="utf-8")
check("the only direct handle_outbound calls are off the event loop",
      source.count("message_router.handle_outbound") == 2
      and "asyncio.to_thread(self.message_router.handle_outbound" in source)

active = body_of("active_delivery_link_available")
check("an available link means an ACTIVE one, not merely a remembered one",
      "RNS.Link.ACTIVE" in active)
check("both link tables are checked, since either can carry a message",
      "direct_links" in active and "backchannel_links" in active)
check("a broken router does not stop a message being sent",
      "except Exception" in active)

send = body_of("send_message")
# Opportunistic first, always. Conditioning it on link availability made a link,
# once established, the carrier for every later message, so pressing Link
# Request silently switched the conversation to DIRECT. The link exists to
# provoke the network into finding a route, not to become the route.
check("a known ratchet is the only condition for sending opportunistically",
      "RNS.Identity.current_ratchet_id" in send
      and "LXMF.LXMessage.OPPORTUNISTIC" in send)
check("the choice does not consult link availability at all",
      "delivery_link_available" not in send)

# A ratchet only ever arrives on an announce from that peer (Identity.py:597,
# and Destination.py:288 for our own), so a link cannot supply one -- which is
# why there is nothing to gain by waiting for a link before going opportunistic.
check("the link-request response reports link state without acting on it",
      "link_active" in SOURCE.read_text(encoding="utf-8"))

queue = body_of("queue_failed_message_for_path_request")
check("a refused path request still announces, since asking is over for that peer",
      "announce_for_unreachable_peer" in queue)

probe = body_of("probe_link")
check("only a link that came up is registered with LXMF",
      probe.index("RNS.Link.ACTIVE") < probe.index("direct_links[destination_hash] = link"))


# Anything that stalls the asyncio loop stalls every request the frontend has in
# flight, and the UI renders an empty state -- no interfaces, no announces, no
# conversations. So no async function may call a blocking RNS/LXMF entry point
# directly; each must go through asyncio.to_thread.
import ast as _a
_src = SOURCE.read_text(encoding="utf-8")
_lines = _src.splitlines()
_BLOCKING = ["time.sleep", "handle_outbound", "drop_path", "RNS.Link", "teardown",
             "cached_announce_for", "restore_cached_announce"]
_onloop = []


class _Loop(_a.NodeVisitor):
    def visit_AsyncFunctionDef(self, node):
        for n in _a.walk(node):
            if isinstance(n, _a.Call):
                try:
                    called = _a.unparse(n.func)
                except Exception:
                    continue
                if any(called.endswith(b) for b in _BLOCKING):
                    if "to_thread" not in _lines[n.lineno - 1]:
                        _onloop.append("{}:{} {}".format(node.name, n.lineno, called))
        self.generic_visit(node)


_Loop().visit(_a.parse(_src))
check("no blocking RNS or LXMF call runs on the event loop [{}]".format(
      ", ".join(_onloop) if _onloop else "clean"), not _onloop)

print(f"\n{len(ok)} passed, {len(fail)} failed")
if fail:
    for f in fail:
        print("  FAILED: " + f)
    sys.exit(1)
