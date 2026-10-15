#!/usr/bin/env python3
"""
Tests the decision logic behind AutoInterface recovery.

    python3 tools/tests/test_autointerface_recovery.py

This decides whether to tear down and rebuild a working network interface, so it
is worth testing directly rather than reasoning about. A false positive drops
peers and links for no reason; a false negative leaves the user restarting the
app, which is the bug being fixed.

The methods are lifted out of meshchat.py by source and bound to a stand-in
object, because importing the module needs RNS, LXMF, LXST and a live Reticulum
instance. The netinfo shim matches the shape of RNS.Interfaces.netinfo.
"""

import ast
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = ROOT / "meshchat.py"

CONSTANTS = [
    "AUTOINTERFACE_CHECK_INTERVAL_SECONDS",
    "AUTOINTERFACE_STRIKES_BEFORE_RELOAD",
    "AUTOINTERFACE_RELOAD_COOLDOWN_SECONDS",
    "AUTOINTERFACE_MAX_RELOADS_PER_HOUR",
]
METHODS = [
    "usable_link_local_interfaces",
    "autointerface_problem",
    "may_reload_autointerface",
]

source_text = SOURCE.read_text(encoding="utf-8")
tree = ast.parse(source_text)
klass = next((n for n in ast.walk(tree)
              if isinstance(n, ast.ClassDef) and n.name == "ReticulumMeshChat"), None)
if klass is None:
    raise SystemExit("ReticulumMeshChat not found")

constants = {}
methods = {}
for node in klass.body:
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in CONSTANTS:
                constants[target.id] = ast.literal_eval(node.value)
    if isinstance(node, ast.FunctionDef) and node.name in METHODS:
        methods[node.name] = node

missing = [c for c in CONSTANTS if c not in constants] + [m for m in METHODS if m not in methods]
if missing:
    raise SystemExit("missing from meshchat.py: " + ", ".join(missing))

# compile the methods in a namespace holding the few globals they touch
import RNS  # the real thing, for platformutils

namespace = {"RNS": RNS, "print": lambda *a, **k: None}
module = ast.Module(body=[methods[m] for m in METHODS], type_ignores=[])
ast.fix_missing_locations(module)
exec(compile(module, "<meshchat>", "exec"), namespace)  # noqa: S102


class Recovery:
    """Stand-in carrying the real constants and the real methods."""
    def __init__(self, telephone=None):
        self.autointerface_state = {}
        self.telephone = telephone


for name, value in constants.items():
    setattr(Recovery, name, value)
for name in METHODS:
    setattr(Recovery, name, namespace[name])


def netinfo_with(interface_addresses):
    """A netinfo shim shaped like RNS.Interfaces.netinfo."""
    shim = types.SimpleNamespace()
    shim.AF_INET6 = "AF_INET6"
    shim.interfaces = lambda: list(interface_addresses.keys())
    shim.ifaddresses = lambda ifname: (
        {shim.AF_INET6: [{"addr": a} for a in interface_addresses[ifname]]}
        if interface_addresses.get(ifname) else {}
    )
    return shim


class FakeAutoInterface:
    ALL_IGNORE_IFS = ["lo0"]
    DARWIN_IGNORE_IFS = ["awdl0", "llw0", "lo0", "en5"]
    ANDROID_IGNORE_IFS = ["dummy0", "lo"]

    def __init__(self, system, adopted, timed_out=None,
                 ignored=None, allowed=None, name="Default Interface"):
        self.name = name
        self.detached = False
        self.netinfo = netinfo_with(system)
        self.adopted_interfaces = dict(adopted)
        self.timed_out_interfaces = dict(timed_out or {})
        self.ignored_interfaces = list(ignored or [])
        self.allowed_interfaces = list(allowed or [])


# FakeAutoInterface must be seen as an AutoInterface by name-based detection
FakeAutoInterface.__name__ = "AutoInterface"

ok, fail = [], []


def check(name, cond):
    (ok if cond else fail).append(name)
    print(("  ok   " if cond else " FAIL  ") + name)


print(f"    check every {constants['AUTOINTERFACE_CHECK_INTERVAL_SECONDS']}s, "
      f"{constants['AUTOINTERFACE_STRIKES_BEFORE_RELOAD']} strikes, "
      f"cooldown {constants['AUTOINTERFACE_RELOAD_COOLDOWN_SECONDS']}s, "
      f"max {constants['AUTOINTERFACE_MAX_RELOADS_PER_HOUR']}/hour")
print()

r = Recovery()

# --- constants are coherent ----------------------------------------------------
confirm_delay = (constants["AUTOINTERFACE_CHECK_INTERVAL_SECONDS"]
                 * constants["AUTOINTERFACE_STRIKES_BEFORE_RELOAD"])
check(f"a problem must persist before acting [{confirm_delay}s]", confirm_delay >= 45)
check("the cooldown is longer than the confirmation window",
      constants["AUTOINTERFACE_RELOAD_COOLDOWN_SECONDS"] > confirm_delay)
check("the hourly cap allows recovery but not thrashing",
      1 <= constants["AUTOINTERFACE_MAX_RELOADS_PER_HOUR"] <= 10)

# --- a healthy interface is left alone -----------------------------------------
healthy = FakeAutoInterface(
    system={"eth0": ["fe80::1"], "lo0": ["fe80::ffff"]},
    adopted={"eth0": "fe80::1"},
    timed_out={"eth0": False},
)
check("a healthy interface reports no problem",
      r.autointerface_problem(healthy) is None)
check("the loopback is not mistaken for an unadopted interface",
      "lo0" not in r.usable_link_local_interfaces(healthy))

# --- case 1: an interface appeared after startup -------------------------------
plugged_in = FakeAutoInterface(
    system={"eth0": ["fe80::1"], "wlan0": ["fe80::2"]},
    adopted={"wlan0": "fe80::2"},
    timed_out={"wlan0": False},
)
problem = r.autointerface_problem(plugged_in)
check("ethernet plugged in after launch is detected", problem is not None)
check("and the reason names the interface",
      problem is not None and "eth0" in problem and "not using" in problem)

# an interface present but with no link-local yet is not usable, so not a problem
no_address_yet = FakeAutoInterface(
    system={"eth0": [], "wlan0": ["fe80::2"]},
    adopted={"wlan0": "fe80::2"},
    timed_out={"wlan0": False},
)
check("an interface with no link-local address yet is not flagged",
      r.autointerface_problem(no_address_yet) is None)

# --- case 2: carrier lost and never recovered ----------------------------------
stale = FakeAutoInterface(
    system={"eth0": ["fe80::1"]},
    adopted={"eth0": "fe80::1"},
    timed_out={"eth0": True},
)
problem = r.autointerface_problem(stale)
check("an interface whose multicast echo stopped is detected", problem is not None)
check("and the reason says carrier lost",
      problem is not None and "carrier lost" in problem and "eth0" in problem)

# partial loss is left alone: the healthy interface is still carrying traffic
partial = FakeAutoInterface(
    system={"eth0": ["fe80::1"], "wlan0": ["fe80::2"]},
    adopted={"eth0": "fe80::1", "wlan0": "fe80::2"},
    timed_out={"eth0": True, "wlan0": False},
)
check("one interface timing out of two is not enough to reload",
      r.autointerface_problem(partial) is None)

both_stale = FakeAutoInterface(
    system={"eth0": ["fe80::1"], "wlan0": ["fe80::2"]},
    adopted={"eth0": "fe80::1", "wlan0": "fe80::2"},
    timed_out={"eth0": True, "wlan0": True},
)
check("both interfaces timing out is a problem",
      r.autointerface_problem(both_stale) is not None)

# --- the user's own filters are respected --------------------------------------
ignored = FakeAutoInterface(
    system={"eth0": ["fe80::1"], "docker0": ["fe80::3"]},
    adopted={"eth0": "fe80::1"},
    timed_out={"eth0": False},
    ignored=["docker0"],
)
check("an interface the user ignored is not flagged as unadopted",
      r.autointerface_problem(ignored) is None)

restricted = FakeAutoInterface(
    system={"eth0": ["fe80::1"], "wlan0": ["fe80::2"]},
    adopted={"eth0": "fe80::1"},
    timed_out={"eth0": False},
    allowed=["eth0"],
)
check("with an allow list, interfaces outside it are not flagged",
      r.autointerface_problem(restricted) is None)

# --- rate limiting -------------------------------------------------------------
NOW = 1_000_000.0
r = Recovery()

allowed, reason = r.may_reload_autointerface("Default Interface", NOW)
check("a first reload is allowed", allowed is True)

state = r.autointerface_state["Default Interface"]
state["reloads"].append(NOW)

allowed, reason = r.may_reload_autointerface("Default Interface", NOW + 10)
check("a second reload moments later is refused", allowed is False)

allowed, _ = r.may_reload_autointerface(
    "Default Interface", NOW + constants["AUTOINTERFACE_RELOAD_COOLDOWN_SECONDS"] + 1)
check("and allowed once the cooldown has passed", allowed is True)

# fill the hourly budget
r = Recovery()
state = r.autointerface_state.setdefault("Default Interface", {"strikes": 0, "reloads": []})
spacing = constants["AUTOINTERFACE_RELOAD_COOLDOWN_SECONDS"] + 1
for i in range(constants["AUTOINTERFACE_MAX_RELOADS_PER_HOUR"]):
    state["reloads"].append(NOW + i * spacing)
last = state["reloads"][-1]

allowed, reason = r.may_reload_autointerface("Default Interface", last + spacing)
check("the hourly cap refuses further reloads", allowed is False)
check("and says why",
      reason is not None and "hour" in reason)

allowed, _ = r.may_reload_autointerface("Default Interface", last + 3601)
check("reloads older than an hour stop counting", allowed is True)

# --- an active call blocks a reload outright -----------------------------------
in_a_call = Recovery(telephone=types.SimpleNamespace(active_call=object()))
allowed, reason = in_a_call.may_reload_autointerface("Default Interface", NOW)
check("a reload never interrupts an active call", allowed is False)
check("and says so", reason is not None and "call" in reason)

idle = Recovery(telephone=types.SimpleNamespace(active_call=None))
allowed, _ = idle.may_reload_autointerface("Default Interface", NOW)
check("with no call in progress a reload is allowed", allowed is True)

# a telephone that raises must not block recovery
class AngryTelephone:
    @property
    def active_call(self):
        raise RuntimeError("telephone unavailable")

resilient = Recovery(telephone=AngryTelephone())
allowed, _ = resilient.may_reload_autointerface("Default Interface", NOW)
check("a telephone that raises does not prevent recovery", allowed is True)

print(f"\n{len(ok)} passed, {len(fail)} failed")
if fail:
    for f in fail:
        print("  FAILED: " + f)
    sys.exit(1)
