#!/usr/bin/env python3
"""
Tests the fast AutoInterface reload, the one that fires on a link change.

    python3 tools/tests/test_link_change_reload.py

AutoInterface joins its multicast group once, in __init__, so an interface that
appears after start is never adopted however long you wait. Waiting for staleness
could take a minute and a half and only worked if the rest of the network had gone
quiet too. Plugging an ethernet cable back in should not need either.

What matters here is the judgement call: a change that brings something usable back
is worth tearing sockets down for, and a change that only takes something away is
not, because there is nothing to rebuild onto. Virtual interfaces are excluded from
both -- a container or a VPN coming up is routine. The budgets are the other half:
a carrier coming back is hard evidence and should not be throttled like an inference
drawn from silence.
"""

import ast
import pathlib
import types

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = ROOT / "meshchat.py"

tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
klass = next((n for n in ast.walk(tree)
              if isinstance(n, ast.ClassDef) and n.name == "ReticulumMeshChat"), None)
if klass is None:
    raise SystemExit("ReticulumMeshChat not found")

METHODS = ("is_virtual_interface_name", "link_change_is_additive",
           "may_reload_autointerface")
CONSTANTS = ("AUTOINTERFACE_VIRTUAL_IF_PREFIXES",
             "AUTOINTERFACE_RELOAD_COOLDOWN_SECONDS",
             "AUTOINTERFACE_MAX_RELOADS_PER_HOUR",
             "AUTOINTERFACE_LINK_RELOAD_COOLDOWN_SECONDS",
             "AUTOINTERFACE_MAX_LINK_RELOADS_PER_HOUR",
             "AUTOINTERFACE_POLL_SECONDS",
             "AUTOINTERFACE_LINK_SETTLE_SECONDS")

found = {n.name: n for n in klass.body
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in METHODS}
missing = set(METHODS) - set(found)
if missing:
    raise SystemExit("missing from meshchat.py: " + ", ".join(sorted(missing)))

constants = {}
for node in klass.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in CONSTANTS:
            constants[target.id] = ast.literal_eval(node.value)
missing = set(CONSTANTS) - set(constants)
if missing:
    raise SystemExit("missing constants: " + ", ".join(sorted(missing)))

namespace = {}
mod = ast.Module(body=[found[n] for n in METHODS], type_ignores=[])
ast.fix_missing_locations(mod)
exec(compile(mod, "<meshchat>", "exec"), namespace)  # noqa: S102


class Recovery:
    def __init__(self):
        self.autointerface_state = {}
        self.telephone = None


for name, value in constants.items():
    setattr(Recovery, name, value)
for name in METHODS:
    setattr(Recovery, name, namespace[name])

ok, fail = [], []


def check(name, cond):
    (ok if cond else fail).append(name)
    print(("  ok   " if cond else " FAIL  ") + name)


def entry(ifname, carrier=True, addrs=("fe80::1",)):
    return (ifname, carrier, tuple(addrs))


r = Recovery()

# --- what should trigger a reload --------------------------------------------
check("an ethernet interface appearing is additive",
      r.link_change_is_additive(
          frozenset({entry("wlan0")}),
          frozenset({entry("wlan0"), entry("eth0")})) is True)

check("a carrier coming back on an interface we already had is additive",
      r.link_change_is_additive(
          frozenset({entry("eth0", carrier=False)}),
          frozenset({entry("eth0", carrier=True)})) is True)

check("gaining a link-local address is additive",
      r.link_change_is_additive(
          frozenset({entry("eth0", addrs=())}),
          frozenset({entry("eth0", addrs=("fe80::1",))})) is True)

# --- what should not ----------------------------------------------------------
check("losing the cable is not additive, since there is nothing to rebuild onto",
      r.link_change_is_additive(
          frozenset({entry("wlan0"), entry("eth0")}),
          frozenset({entry("wlan0")})) is False)

check("a carrier dropping is not additive",
      r.link_change_is_additive(
          frozenset({entry("eth0", carrier=True)}),
          frozenset({entry("eth0", carrier=False)})) is False)

check("an identical signature is not additive",
      r.link_change_is_additive(
          frozenset({entry("eth0")}), frozenset({entry("eth0")})) is False)

for virtual in ("veth1234", "docker0", "br-abc123", "tun0", "wg0", "tailscale0"):
    check("a {} appearing does not trigger a reload".format(virtual),
          r.link_change_is_additive(
              frozenset({entry("eth0")}),
              frozenset({entry("eth0"), entry(virtual)})) is False)

check("a real interface appearing alongside a container one still counts",
      r.link_change_is_additive(
          frozenset({entry("wlan0")}),
          frozenset({entry("wlan0"), entry("veth99"), entry("eth0")})) is True)

# --- carrier unknown (macOS, Windows): fall back to names and addresses -------
check("an interface appearing with no carrier info is still additive",
      r.link_change_is_additive(
          frozenset({entry("en0", carrier=None)}),
          frozenset({entry("en0", carrier=None), entry("en5", carrier=None)})) is True)

check("unknown carrier on both sides is not mistaken for a carrier change",
      r.link_change_is_additive(
          frozenset({entry("en0", carrier=None)}),
          frozenset({entry("en0", carrier=None)})) is False)

# --- the budgets --------------------------------------------------------------
check("a link change is allowed to reload sooner than staleness is",
      Recovery.AUTOINTERFACE_LINK_RELOAD_COOLDOWN_SECONDS
      < Recovery.AUTOINTERFACE_RELOAD_COOLDOWN_SECONDS)
check("and is allowed more reloads per hour",
      Recovery.AUTOINTERFACE_MAX_LINK_RELOADS_PER_HOUR
      > Recovery.AUTOINTERFACE_MAX_RELOADS_PER_HOUR)
check("the loop wakes often enough to notice a cable within a few seconds",
      Recovery.AUTOINTERFACE_POLL_SECONDS <= 5)
check("but settles before acting, so unplug-then-replug is one reload",
      Recovery.AUTOINTERFACE_LINK_SETTLE_SECONDS >= Recovery.AUTOINTERFACE_POLL_SECONDS)

r = Recovery()
allowed, _ = r.may_reload_autointerface("AutoInterface", 1000.0, link_change=True)
check("the first link-change reload is allowed", allowed is True)

r.autointerface_state["AutoInterface"]["reloads"].append(1000.0)
allowed, reason = r.may_reload_autointerface("AutoInterface", 1005.0, link_change=True)
check("a second one five seconds later is refused", allowed is False and reason == "reloaded too recently")

allowed, _ = r.may_reload_autointerface("AutoInterface", 1020.0, link_change=True)
check("but twenty seconds later is allowed, so replugging twice works", allowed is True)

allowed, reason = r.may_reload_autointerface("AutoInterface", 1020.0, link_change=False)
check("the staleness path still waits five minutes after that reload",
      allowed is False and reason == "reloaded too recently")

r = Recovery()
r.autointerface_state["AutoInterface"] = {
    "strikes": 0, "stale_since": {},
    "reloads": [1000.0 + i for i in range(Recovery.AUTOINTERFACE_MAX_LINK_RELOADS_PER_HOUR)],
}
allowed, reason = r.may_reload_autointerface("AutoInterface", 2000.0, link_change=True)
check("a flapping cable is capped per hour", allowed is False and "times in the last hour" in reason)

r = Recovery()
r.telephone = types.SimpleNamespace(active_call=object())
allowed, reason = r.may_reload_autointerface("AutoInterface", 1000.0, link_change=True)
check("a call still blocks a link-change reload outright",
      allowed is False and reason == "a call is in progress")

print("\n{} passed, {} failed".format(len(ok), len(fail)))
raise SystemExit(1 if fail else 0)
