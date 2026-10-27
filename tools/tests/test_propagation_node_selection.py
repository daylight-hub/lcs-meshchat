#!/usr/bin/env python3
"""
Tests how a propagation node is read off the wire and which one gets used.

    python3 tools/tests/test_propagation_node_selection.py

Two things are pinned here.

The announce parser. MeshChat was reading the three field layout LXMF used
years ago against announces that have carried seven fields since 0.5, so the
"enabled" flag it displayed was really the legacy-support flag -- hardcoded
False in LXMRouter -- and the per-transfer limit it displayed was really the
enabled boolean. Every modern node showed as Disabled by Operator with a limit
of True. The name the operator gave the node sits in the metadata dict those
seven fields end with, which is the field this app had no way to reach.

The selection. Adopting the first node ever heard and never looking again
pins you to whichever one happened to announce first, which on startup is
close to random. Reconsidering is the fix, but reconsidering on every announce
is how you get two equidistant nodes trading the slot back and forth, and each
handover cancels an in-flight sync. So: closer wins, more recent breaks a tie
among candidates, and recency on its own only rescues us from a node that has
gone quiet.
"""

import ast
import base64
import pathlib
import sys
import time
import types

# the same packer meshchat.py uses. The pip msgpack refuses integer map keys
# by default, and the propagation node metadata dict is keyed by integers, so
# testing against that one would be testing a different parser.
import RNS.vendor.umsgpack as msgpack

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = ROOT / "meshchat.py"

tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
klass = next((n for n in ast.walk(tree)
              if isinstance(n, ast.ClassDef) and n.name == "ReticulumMeshChat"), None)
if klass is None:
    raise SystemExit("ReticulumMeshChat not found in meshchat.py")

funcs = {n.name: n for n in klass.body
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


ARITHMETIC = (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Div, ast.Pow, ast.USub)


def const_value(node):
    """A constant's value, including one written as arithmetic.

    literal_eval refuses `3 * 3600`, which is a perfectly ordinary way to write
    a timeout, so this folds the arithmetic itself rather than forcing every
    constant in meshchat.py to be a bare number for the tests' benefit.
    """
    if isinstance(node, ast.BinOp) and isinstance(node.op, ARITHMETIC):
        left, right = const_value(node.left), const_value(node.right)
        if left is None or right is None:
            return None
        return eval(compile(ast.Expression(node), "<const>", "eval"),  # noqa: S307
                    {"__builtins__": {}}, {})
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ARITHMETIC):
        return const_value(node.operand)
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def class_constants(class_node):
    found = {}
    for node in class_node.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            value = const_value(node.value)
            if value is not None:
                found[target.id] = value
    return found


consts = class_constants(klass)

ok, fail = [], []


def check(name, cond):
    (ok if cond else fail).append(name)
    print(("  ok   " if cond else " FAIL  ") + name)


def body_of(name):
    return ast.unparse(funcs[name]) if name in funcs else ""


def lift(name, namespace):
    """Pull one method out of meshchat.py and make it callable."""
    if name not in funcs:
        raise SystemExit(name + " not found in meshchat.py")
    node = funcs[name]
    mod = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(mod)
    exec(compile(mod, "<meshchat>", "exec"), namespace)  # noqa: S102
    return namespace[name]


PN_META_NAME = 0x01


def modern_announce(*, enabled=True, name=None, timebase=1700000000,
                    per_transfer_limit=256, stamp_cost=16):
    metadata = {}
    if name is not None:
        metadata[PN_META_NAME] = name.encode("utf-8")
    return base64.b64encode(msgpack.packb([
        False,                      # 0: legacy LXMF propagation support
        timebase,                   # 1: node timebase
        enabled,                    # 2: propagation enabled
        per_transfer_limit,         # 3: per-transfer limit
        4096,                       # 4: per-sync limit
        [stamp_cost, 3, 18],        # 5: stamp costs
        metadata,                   # 6: metadata
    ])).decode("utf-8")


def legacy_announce(*, enabled=True, timebase=1600000000, per_transfer_limit=128):
    return base64.b64encode(msgpack.packb([
        enabled, timebase, per_transfer_limit,
    ])).decode("utf-8")


# --- the announce parser -----------------------------------------------------

ns = {"base64": base64, "msgpack": msgpack, "LXMF_PN_META_NAME": PN_META_NAME}
parse = lift("parse_lxmf_propagation_node_app_data", ns)
obj = types.SimpleNamespace()

parsed = parse(obj, modern_announce(enabled=True, name="Liberty Hill Relay"))
check("a modern announce is read as enabled, not as its legacy-support flag",
      parsed is not None and parsed["enabled"] is True)
check("the per-transfer limit is a number rather than the enabled boolean",
      parsed["per_transfer_limit"] == 256)
check("the advertised name is read out of the metadata",
      parsed["name"] == "Liberty Hill Relay")
check("the stamp cost comes along, since it decides what a send to it costs",
      parsed["stamp_cost"] == 16)
check("the timebase still lines up", parsed["timebase"] == 1700000000)

parsed = parse(obj, modern_announce(enabled=False, name="Off Relay"))
check("a node its operator switched off is reported as disabled",
      parsed["enabled"] is False)

parsed = parse(obj, modern_announce(enabled=True))
check("a node that set no name reports none rather than guessing",
      parsed["name"] is None)

parsed = parse(obj, legacy_announce(enabled=True, per_transfer_limit=128))
check("an announce in the old three field layout is still understood",
      parsed is not None and parsed["enabled"] is True
      and parsed["per_transfer_limit"] == 128)

check("garbage returns None instead of raising into the announce handler",
      parse(obj, "not base64 at all") is None)
check("and so does an empty app_data", parse(obj, "") is None)

name_of = lift("propagation_node_name", ns)
obj.parse_lxmf_propagation_node_app_data = lambda data: parse(obj, data)
check("the name helper reads through the parser",
      name_of(obj, modern_announce(name="Command Center")) == "Command Center")
check("and returns None for an announce it cannot read",
      name_of(obj, "rubbish") is None)


# --- which node gets used ----------------------------------------------------

print()


class FakeConfigValue:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Harness:
    """Enough of the app for evaluate_auto_propagation_node to run."""

    def __init__(self, *, candidates, current=None, auto=True, switching=True,
                 busy=False, last_switch_at=0):
        self.candidates = candidates
        self.adopted = []
        self.config = types.SimpleNamespace(
            auto_select_propagation_node=FakeConfigValue(auto),
            auto_select_propagation_node_switching_enabled=FakeConfigValue(switching),
            lxmf_preferred_propagation_node_destination_hash=FakeConfigValue(current),
        )
        self.message_router = types.SimpleNamespace(
            propagation_transfer_state=0x05 if busy else 0x00,
        )
        self.last_propagation_node_switch_at = last_switch_at
        self.PROPAGATION_NODE_SWITCH_COOLDOWN_SECONDS = consts["PROPAGATION_NODE_SWITCH_COOLDOWN_SECONDS"]
        self.PROPAGATION_SYNC_BUSY_STATES = (0x01, 0x02, 0x03, 0x04, 0x05, 0x06)

    def propagation_node_candidates(self):
        return list(self.candidates)

    def adopt_propagation_node(self, node, reason):
        self.adopted.append((node["destination_hash"], reason))
        self.config.lxmf_preferred_propagation_node_destination_hash.set(
            node["destination_hash"])


evaluate_ns = {"time": time, "print": lambda *a, **k: None,
               "RNS": types.SimpleNamespace(
                   Transport=types.SimpleNamespace(PATHFINDER_M=128))}
evaluate = lift("evaluate_auto_propagation_node", evaluate_ns)

NOW = time.time()


def node(hash_hex, hops, age_seconds=0, name=None):
    return {
        "destination_hash": hash_hex,
        "name": name,
        "hops": hops,
        "announced_at": NOW - age_seconds,
    }


# nothing chosen yet
h = Harness(candidates=[node("aa", 4), node("bb", 2), node("cc", 7)])
evaluate(h)
check("with nothing selected, the closest node is adopted",
      h.adopted and h.adopted[0][0] == "bb")

# ties go to the one heard most recently
h = Harness(candidates=[node("aa", 2, age_seconds=900), node("bb", 2, age_seconds=30)])
evaluate(h)
check("at equal distance the most recently announced node wins",
      h.adopted and h.adopted[0][0] == "bb")

# a closer node appears
h = Harness(candidates=[node("aa", 4), node("bb", 1)], current="aa")
evaluate(h)
check("a closer node takes over from the one in use",
      h.adopted and h.adopted[0][0] == "bb")

# a farther node must not
h = Harness(candidates=[node("aa", 2), node("bb", 5)], current="aa")
evaluate(h)
check("a farther node does not", h.adopted == [])

# equal distance must not cause a switch, however fresh
h = Harness(candidates=[node("aa", 2, age_seconds=600),
                        node("bb", 2, age_seconds=1)], current="aa")
evaluate(h)
check("a fresher announce at the same distance does not cause a switch",
      h.adopted == [])
check("  (which is what stops two equidistant nodes trading the slot forever)",
      h.adopted == [])

# A node that has gone quiet is NOT replaced. v2.0.8 did replace it, and that
# is how people lost a working relay: silence in the announce table is not
# evidence the node is down -- announce intervals are hours long, and announces
# get pruned -- while a handover definitely costs an in-flight sync.
h = Harness(candidates=[node("aa", 2, age_seconds=4 * 3600),
                        node("bb", 4, age_seconds=30)], current="aa")
evaluate(h)
check("a node that has gone quiet is not replaced by a farther one",
      h.adopted == [])

# The node in use is absent from the announces entirely. This is the case that
# broke v2.0.8: it reads as "no longer advertising" but it is equally a hash
# typed in by hand, an announce that has been pruned, or our own local node
# before it has announced.
h = Harness(candidates=[node("bb", 6)], current="aa")
evaluate(h)
check("a node missing from the announces is left alone, not replaced",
      h.adopted == [])
check("  (it may be a hand-entered hash or a pruned announce, not a dead node)",
      h.adopted == []
      and h.config.lxmf_preferred_propagation_node_destination_hash.get() == "aa")

# a closer node with no route at all is no use
h = Harness(candidates=[node("aa", 6), node("bb", 128)], current="aa")
evaluate(h)
check("a node with no known route is never switched to",
      h.adopted == [])

# manual selection
h = Harness(candidates=[node("aa", 9), node("bb", 1)], current="aa", auto=False)
evaluate(h)
check("a hand-picked node is never overridden", h.adopted == [])

# switching turned off, which is the default
h = Harness(candidates=[node("aa", 9), node("bb", 1)], current="aa", switching=False)
evaluate(h)
check("with switching off, even a much closer node does not take over",
      h.adopted == [])

# ...but a first selection still happens with switching off
h = Harness(candidates=[node("bb", 1)], current=None, switching=False)
evaluate(h)
check("and an empty selection is still filled when switching is off",
      h.adopted and h.adopted[0][0] == "bb")

# debounce
h = Harness(candidates=[node("aa", 9), node("bb", 1)], current="aa",
            last_switch_at=NOW - 5)
evaluate(h)
check("a second switch within the cooldown is held off", h.adopted == [])

h = Harness(candidates=[node("aa", 9), node("bb", 1)], current="aa",
            last_switch_at=NOW - consts["PROPAGATION_NODE_SWITCH_COOLDOWN_SECONDS"] - 5)
evaluate(h)
check("and allowed once the cooldown has passed",
      h.adopted and h.adopted[0][0] == "bb")

# mid-sync
h = Harness(candidates=[node("aa", 9), node("bb", 1)], current="aa", busy=True)
evaluate(h)
check("a switch waits rather than aborting a sync in progress", h.adopted == [])

# no candidates at all
h = Harness(candidates=[], current="aa")
evaluate(h)
check("no candidates means no change, not a cleared selection",
      h.adopted == []
      and h.config.lxmf_preferred_propagation_node_destination_hash.get() == "aa")


# --- wiring ------------------------------------------------------------------

print()

_candidates = body_of("propagation_node_candidates")
# Our own local node stays a candidate. Excluding it looked tidy and was
# wrong: someone running a local propagation node and using it as their relay
# had it taken away, because it was absent from the candidate list and so read
# as "no longer advertising".
check("our own local node is still a candidate",
      "propagation_destination.hexhash" not in _candidates)
check("a node its operator disabled is not a candidate",
      "enabled" in _candidates and "continue" in _candidates)
check("distance is measured live rather than read from the announce row",
      "hops_to" in _candidates)

_announce = body_of("on_lxmf_propagation_announce_received")
check("every propagation announce triggers a reconsideration",
      "evaluate_auto_propagation_node" in _announce)
check("the old first-one-wins adoption is gone",
      "auto-selected preferred propagation node" not in _announce)

_adopt = body_of("adopt_propagation_node")
check("adopting a node also makes it the active one",
      "set_active_propagation_node" in _adopt)
check("and records when, so the cooldown means something",
      "last_propagation_node_switch_at" in _adopt)
check("and tells the ui, so the settings page does not go stale",
      "send_config_to_websocket_clients" in _adopt)
check("but only once there is a loop to tell it on, since this also runs "
      "during startup",
      "AsyncUtils.main_loop" in _adopt and "is_running()" in _adopt)

_config = body_of("get_config_dict")
check("the config carries the advertised name of the node in use",
      "lxmf_preferred_propagation_node_name" in _config)
check("and how far away it is",
      "lxmf_preferred_propagation_node_hops" in _config)

_list = ast.unparse(tree)
check("the node list reports the advertised name alongside the operator name",
      "'name': node_name" in _list and "'operator_display_name'" in _list)
check("and how far away each node is, so the ranking is visible",
      "'hops': hops" in _list)

check("the switch cooldown is long enough not to thrash a sync",
      consts["PROPAGATION_NODE_SWITCH_COOLDOWN_SECONDS"] >= 60)

# Silence is no longer a reason to switch, so there is no staleness window to
# tune -- the whole idea went with it.
check("silence is not a switching criterion any more",
      "PROPAGATION_NODE_STALE_SECONDS" not in SOURCE.read_text(encoding="utf-8"))

# Liberty Chat selects once and stops. That is what MeshChat does out of the
# box now too, so an install that never touches Settings behaves identically.
_config_class = next((n for n in ast.walk(tree)
                      if isinstance(n, ast.ClassDef) and n.name == "Config"), None)
_defaults = {}
if _config_class is not None:
    for _node in _config_class.body:
        if not isinstance(_node, ast.Assign) or not isinstance(_node.value, ast.Call):
            continue
        for _target in _node.targets:
            if isinstance(_target, ast.Name) and len(_node.value.args) >= 2:
                _defaults[_target.id] = const_value(_node.value.args[1])

check("switching while running is off by default, matching Liberty Chat",
      _defaults.get("auto_select_propagation_node_switching_enabled") is False)
check("and auto-select itself is still on, so an empty selection gets filled",
      _defaults.get("auto_select_propagation_node") is True)


print(f"\n{len(ok)} passed, {len(fail)} failed")
if fail:
    for f in fail:
        print("  FAILED: " + f)
    sys.exit(1)
