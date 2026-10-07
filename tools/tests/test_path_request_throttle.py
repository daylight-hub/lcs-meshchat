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

print(f"\n{len(ok)} passed, {len(fail)} failed")
if fail:
    for f in fail:
        print("  FAILED: " + f)
    sys.exit(1)
