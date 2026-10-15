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


print()
for name in ["on_lxmf_sending_failed", "queue_failed_message_for_path_request",
             "request_path_for_failed_messages", "resolve_pending_path_request",
             "retry_failed_message", "clear_path_request_attempts"]:
    check("method present: " + name, name in funcs)

failed = body_of("on_lxmf_sending_failed")

# the path request must be reached before the propagation fallback
check("the failure handler tries the path request before propagating",
      failed.index("path_request_on_send_failure_enabled")
      < failed.index("send_failed_message_via_propagation_node"))

# and propagation must still be reachable when path requests are disabled
check("propagation still happens when path requests are turned off",
      "elif wants_propagation" in failed
      and "send_failed_message_via_propagation_node" in failed)

# A message that already went to a propagation node and failed did so because the
# propagation node was unreachable, not the recipient. LXMF requests a path to its
# own propagation node and retries that itself, so asking here would target the
# wrong destination and the retry would only repeat the propagation attempt.
check("an already-propagated message does not trigger a path request",
      "already_propagated" in failed
      and "not already_propagated" in failed)
check("and that check reads the delivery method, not the fallback flag",
      "desired_method" in failed and "PROPAGATED" in failed)

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
check("the path is requested unconditionally, not only when absent",
      "RNS.Transport.request_path" in worker
      and "if not RNS.Transport.has_path" not in worker.split("request_path(")[0])

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
      "handle_outbound" in retry)
check("the retry does not change the delivery method, leaving propagation armed",
      "desired_method" not in retry)
check("the retry resets the LXMF send state the way the propagation fallback does",
      "packed = None" in retry and "delivery_attempts = 0" in retry)




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
check("warming is skippable from settings",
      "path_warm_on_startup_enabled" in warm_body)
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
check("persistence is skippable from settings",
      "persist_paths_on_discovery_enabled" in sched)

persist = body_of("persist_path_table_after_quiet_period")
check("the write is debounced",
      "PATH_PERSIST_DEBOUNCE_SECONDS" in persist)
check("and floored by a minimum interval",
      "PATH_PERSIST_MIN_INTERVAL_SECONDS" in persist)
check("disk I/O is kept off the event loop",
      "asyncio.to_thread" in persist)
check("the pending flag is always cleared, so writes cannot stop permanently",
      "finally:" in persist and "path_persist_pending = False" in persist)

print(f"\n{len(ok)} passed, {len(fail)} failed")
if fail:
    for f in fail:
        print("  FAILED: " + f)
    sys.exit(1)
