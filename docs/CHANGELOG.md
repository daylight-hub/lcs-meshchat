# Changelog

Version history for LCS MeshChat. The release workflow reads the
section matching the version being built and uses it as the release body.

### What's new in v2.0.3

**Path requests now actually repair a broken route.** Until now, both the Path
Request button and the automatic request after a failed send asked the network for
a route and then watched `has_path` for a change. Against the case they exist for —
a route we already hold that no longer works — that could never do anything.

Reticulum answers a path request by replaying the announce it has in cache, and
`Transport.inbound` refuses an announce it has heard before: every branch of its
acceptance test needs either a random blob it has not seen or no existing entry at
all. The replay is the very announce the bad entry was built from, so the table was
never updated. Worse, `has_path` is membership in that table, so it was already true
before the request, during it and after. The automatic retry therefore returned
within milliseconds reporting success and re-sent the message down the route that
had just failed, three times, and gave up. The button reported "Path found" having
confirmed nothing.

Both now drop the entry first. With it gone the replayed announce is accepted
unconditionally and the route is rebuilt around whichever next hop answers now. The
second benefit is an honest answer: with nothing in the table, `has_path` going true
again can only mean a reply arrived. The button says "Path refreshed" only when that
happened, and says so plainly when nothing answered rather than presenting the old
route as a fresh one. If the network stays silent the previous entry is put back, so
a failed request never costs a route that was working.

This is the same approach LXMF itself takes when an opportunistic delivery stalls
(`drop_path`, settle, `request_path`) and the one Liberty Chat already uses for
NomadNet page loads — neither app was using it for messaging.

**Repeat requests are paced to the network, not to the user.** RNS 1.5.5 added an
in-flight gate: a transport node that is already carrying a path request for a
destination batches any further request for up to 45 seconds and takes no action.
Tapping the button again inside that window does nothing but spend airtime, so the
60-second cooldown on automatic requests is now documented against that limit, and
the button's "no reply" message says to wait before retrying.

**Fixed:** the AutoInterface recovery test suite could not run on Python 3.13 — it
re-wrapped an already-decorated class method, which 3.13 refuses to call. All four
suites pass again (152 checks).

### What's new in v2.0.2

**The saved path table is now loaded, so startup barely needs to ask the network
anything.** v2.0.0 recovered from the lost-paths problem by requesting a route for
each recent peer — about twenty small packets spread over seventy seconds, on every
launch. That was more airtime than the problem deserved.

Reticulum writes the path table on every clean shutdown; it just refuses to read it
back unless transport mode is on. So the fix is to read it ourselves, which is what
Liberty Chat does in `event_bridge.restore_path_table`, and this is a port of that
approach. It runs right after the Reticulum instance is built, mirrors upstream's own
loader in `Transport.start` field for field — re-resolving each entry's interface by
hash and bumping the cached announce's hop count — and declines to overwrite anything
already live, since a route learned since this process started is fresher than one on
disk. Blackholed identities are dropped, as upstream does, because restoring a route
to one would quietly undo the blackhole.

**Startup path requests are now a backstop rather than the mechanism.** They still
run, and still skip any peer already reachable — which after a successful restore is
most or all of them. What remains is the handful whose cached announce has expired and
so could not be reconstructed. With a healthy saved table, startup sends nothing.

Why not do this in the first place: the earlier reasoning was that a restored route
can be present but dead, and a dead-but-present route is worse than none, because
`has_path()` returns true and the first send goes down a route that no longer exists.
That is true, but it was the wrong weighting — v1.9.9 already requests a path and
retries when a send fails, so the cost of a stale entry is one failed message rather
than a stranded conversation. One retry beats twenty path requests per launch.

`tools/tests/test_path_table_restore.py` adds 23 checks, run against a stand-in
Reticulum rather than only inspected. The important one asserts the seven-element
entry's field order against RNS's `IDX_PT_*` constants: getting that wrong would not
fail loudly, it would install corrupt routes.

### What's new in v2.0.1

**AutoInterface recovery now covers a stale interface while others still work.**
v2.0.0 only reloaded when *every* adopted interface had gone quiet, so the case that
matters most on a laptop was missed: ethernet into the mesh goes stale while wifi is
still up, wifi keeps hearing its own multicast echoes and so looks healthy, and the
dead ethernet is never rebuilt.

A single stale interface is now acted on too, but on a longer fuse. If everything has
gone quiet nothing is working and it reloads within a minute, as before. If one
interface is quiet while others are carrying traffic it waits five minutes first,
because a reload interrupts the healthy ones as well — and an interface that recovers
on its own inside that window is left alone, with its timer reset.

**Virtual interfaces no longer cause churn.** A container starting brings up a `veth`
with a link-local address, and a VPN brings up a `tun`. v2.0.0 read each of those as
"a new interface appeared" and reloaded, repeatedly, on any Docker host. Interfaces
named `veth*`, `docker*`, `br-*`, `virbr*`, `tun*`, `tap*`, `zt*`, `wg*`,
`tailscale*`, `utun*`, `bridge*`, `vmnet*`, `lo*`, `awdl*` and `llw*` no longer
trigger a reload on arrival. This only suppresses the trigger: AutoInterface still
adopts and uses them exactly as before, and staleness on one is still acted on.

Test suite for the recovery logic doubles to 48 checks, including the wifi-up /
ethernet-stale case end to end, recovery inside the grace period, a second spell of
staleness starting a fresh timer, and the container-churn case.

### What's new in v2.0.0

**AutoInterface recovers by itself.** Two problems that both ended in "restart
MeshChat", with one root cause: `AutoInterface` enumerates the system's network
interfaces once in its constructor, and joins its discovery multicast group once
there too (`IPV6_JOIN_GROUP`). Nothing ever redoes either.

- Plug ethernet in after launch and that interface is never adopted. `peer_jobs`
  only iterates the interfaces adopted at startup, so it is never picked up.
- If a link drops and comes back, the kernel drops the socket's multicast group
  membership. The link-local address is usually derived from the MAC, so it returns
  unchanged — which means `peer_jobs`' address-change branch never fires, the socket
  is never recreated, and nothing rejoins the group. Multicast echoes stop for good:
  *Multicast echo timeout. Carrier lost.* and it never recovers. This is the
  "AutoInterface goes stale after a while" case.

Reticulum cannot be restarted in-process — `Reticulum.__init__` raises
`OSError("Attempt to reinitialise Reticulum, when it was already running")` and the
singleton is never cleared, not even by `exit_handler()`. But `reload_interface()`
is supported: it detaches and re-attaches one interface, re-synthesising it from
config, which re-runs the constructor and so re-enumerates interfaces *and* rejoins
the multicast group. One mechanism, both problems.

A reload drops peers and links on that interface, so it is deliberately reluctant:
the problem must persist across two checks 30 seconds apart, reloads are limited to
one every five minutes and four an hour, an active call blocks one outright, and
partial trouble is left alone — if one of two interfaces has timed out, the other is
still carrying traffic and gets to keep doing so. Toggle under Settings → Messages.

The decision logic has its own test suite
(`tools/tests/test_autointerface_recovery.py`, 24 checks) covering both detection
cases, the user's own ignore and allow lists, partial versus total carrier loss, the
rate limits, and the active-call guard.

**Why paths disappeared after a restart.** Reticulum does save its path table —
LCS MeshChat shuts down cleanly and `Transport.exit_handler()` writes it. The
problem is the other end: `Transport.start()` only *reads* that file back when
transport mode is enabled, and transport mode defaults to off. So a normal client
saved its paths faithfully and then ignored them on every start, which is why it sat
there waiting for the other side to announce again.

Two fixes, both optional under Settings → Messages:

- **Request paths on startup.** Ten seconds after launch, LCS MeshChat asks for a
  route to each peer you have exchanged messages with in the last 30 days — the 20
  most recent, skipping any already reachable, spaced three seconds apart so a LoRa
  segment is not flooded. Conversations work again in about a minute instead of
  waiting hours for an announce.
- **Save paths as they are learned.** Reticulum writes the table on clean shutdown
  and otherwise only every 12 hours (`PERSIST_INTERVAL`), so an unclean kill — a
  Docker stop timeout, a power cut — could lose most of a day's learned routes. The
  table is now written shortly after new paths appear, debounced by 30 seconds and
  floored at one write every five minutes, off the event loop so a large table does
  not stall the UI.

Neither changes your node's role on the network. Enabling transport mode would also
make Reticulum reload the table itself, but it would make you route other people's
traffic too, which on a LoRa segment is not a small thing.

**Paths expiring while running** is separate and mostly not what was happening: with
the default interface mode the expiry is a week (`PATHFINDER_E`). It is six hours
only if an interface is set to `roaming`, and one day for `access point`.

Nothing in this release breaks compatibility: the storage directory is unchanged,
identities and databases carry over, and no API was removed.

### What's new in v1.9.9

**Path request on send failure.** Reticulum only learns a route when something asks
for one or the peer announces, so a message that failed while its path was stale sat
failed until that peer next announced. Now, when a send fails, LCS MeshChat asks the
network where that destination is and resends if a path comes back. The request goes
out even when a path is already known, because a stale entry is exactly the case
this is for and the response refreshes it.

It is throttled, because a resend creates fresh messages that can fail and call
straight back in: at most one request per peer per minute, three per peer, and the
budget resets after 30 minutes of quiet. A successful delivery or an incoming
announce from that peer clears the count immediately. Messages are never stranded by
the cap — the existing resend-on-announce still applies. Settings → Messages has a
toggle, and the throttling and ordering have their own test suite
(`tools/tests/test_path_request_throttle.py`, 36 checks).

**Propagation stays the fallback it is meant to be.** The path request is tried
first, because direct delivery beats leaving a message on a third party's node. If a
route comes back the message is retried on it — the same message, re-sent rather than
copied, so nothing is duplicated and `try_propagation_on_fail` survives: should the
retry fail too, propagation still happens. If no route comes back, or the throttle
has already spent its attempts, the message goes to propagation immediately. With
path requests turned off, behaviour is exactly as it was before.

One unreachable peer fails every message queued for it, one callback each. Those are
collected per destination and resolved together by a single path request, so the
network is asked once and no message is either sent twice or quietly dropped.

**Reaching the propagation node is LXMF's job, and it already does it.** If a
propagated message fails because the propagation node itself is unreachable, LXMF
requests a path to that node and retries — five attempts, seven seconds apart
(`LXMRouter.process_outbound`). So a message that has already gone to propagation is
left alone here: asking for a path to the *recipient* at that point would be aimed at
the wrong destination, and retrying would only repeat the propagation attempt.

**Path Request button** in each conversation, beside the peer's identity at the top.
Asks the network for a route to that peer on demand and reports what came back —
hop count and interface, or that nothing answered. Useful before sending something
large, or when the header shows a hop count but messages are failing anyway.

`GET /api/v1/destination/<hash>/path` gained `force=true`, which issues the request
even when a path is already known, and now reports `path_was_known` and
`path_was_requested` so a caller can tell what actually happened.

### What's new in v1.9.8

**Transmit power now matches what the board can actually do.** Setting 20 dBm on a
LilyGo and finding it would not transmit was not a limit in LCS MeshChat — there
was none. The RNode firmware silently clamps anything above a board's own ceiling,
Reticulum then compares what it asked for against what the radio reports back
(`RNodeInterface.py`, the `TX power mismatch` check), the values differ, and the
interface never comes up. SX127x boards, which is what the LilyGo T-Beam and
LoRa32 v2.1 are, cap at **17 dBm**.

- The RNode interface form has a **Radio Board** picker that holds transmit power
  at or below that board's ceiling: SX127x 17, SX1262 22, Heltec v4 28, SX1280
  13, SX1280 with PA 20.
- **Allow up to 30 dBm** overrides the ceiling deliberately, and the form explains
  exactly how the failure presents if you exceed what the radio accepts.
- **Presets no longer set transmit power.** Every preset used to force 22 dBm,
  which is what broke SX127x boards the moment a preset was selected. Transmit
  power is a property of the board, so it is now set once, separately.
- The bundled **RNode LoRa** interface now uses 17 dBm instead of 22.

**Modem presets reworked**, and the app and both Transport Console dropdowns are
now generated from one file (`src/frontend/js/rnode-presets.json`), so they cannot
drift apart again.

- New **Long Range / Turbo** (SF11 / 500 kHz / CR 4:8), between Medium Slow and
  Long Fast.
- **Average - Recommended for Speed** is called **Short Slow** again.
- **Short Slow**, **Medium Fast** and **Medium Slow** are marked
  ★ *good range and speed with high repeaters*.
- **Long Fast** is marked ★ *Default; good balance in dense terrain*, replacing
  *LCS Recommended*. It remains the default.
- The country presets are gone from both console dropdowns, which now show the
  same nine presets as the app, Short Turbo through Long Slow.

**New message sound.** A short chime plays when a message arrives, generated in
the browser so there is no audio file to ship or to be blocked from autoplaying.
It is distinct from the call ringtone and fires once. Settings → Notifications has
an on/off toggle and a test button.

**Reset Identity**, at the end of Settings. Generates a new Reticulum identity,
and with it a new LXMF address, after two confirmations. Nothing is deleted: the
previous key is saved beside the new one as `identity.replaced-<timestamp>`, and
because per-identity data lives under `identities/<identity_hash>/`, the old
database stays where it is. Takes effect on restart.

**Command Center PRO Client** added to Add LCS Interfaces, below LCS Gateway
Client — a TCP client to `liberty.local:4246`, off by default.

**Reticulum updated to 1.5.5.** The blackhole API is unchanged from 1.5.4 and
every Reticulum call this app makes still resolves, so nothing else moves.

### What's new in v1.9.7

- **Moved to its own repository.** LCS MeshChat now lives at
  `daylight-hub/lcs-meshchat` rather than as a fork. The **Check for Updates**
  button on the About page points there, and releases are published there.
- **Docker image renamed** to `ghcr.io/daylight-hub/lcs-meshchat`. Update the
  `image:` line in your compose file and pull again; nothing else changes. Your
  config volume, Reticulum identity and message history are untouched.
- **`lcs-meshchat.local` added to the console's address sweep**, alongside the
  names it already tried.

Upgrading from v1.9.6 needs no migration. The storage directory
(`~/.reticulum-meshchat` on desktop, `/config` in the container) is deliberately
unchanged, so identities and message history carry over as-is.

### What's new in v1.9.6

- **The frequency preset dropdown now appears.** It was never reaching the page: the
  script looked for `.panel` / `.tabbody` / `.tab-content`, and the console has none
  of those. It now anchors on the console's real markup and sits directly above the
  Frequency field on the RNode radio namespace, under Transport Config. The
  modem-parameter warning was failing the same way and is fixed with it.
- **Auto-discovery sweeps the local network.** Discovery now runs in three tiers —
  this page's own address, then this computer, then a sweep of `.local` names on the
  proxy port 8443 and the usual published container ports. Hosts that have answered
  before are remembered and tried first, and `?hosts=depot.local` adds a name of your
  own. This is for Docker deployments reached by mDNS name.
- **Docker connection failures now say which side is at fault.** If the bridge answers
  over HTTPS on the same address but the WebSocket will not open, the console says so
  and points at the self-signed certificate, with a link to accept it. Every failure
  banner now carries a box to type an address into directly, so a failed discovery
  never leaves you stuck. `window.__lcsBridgeDiscovery` records every address tried
  and why each failed.
- **The console is built from source, and tested.** The two LCS scripts now live in
  `tools/console/` and are injected by `tools/console/build_console.py`, which also
  verifies that every selector they depend on still exists in the console bundle.
  `sh tools/console/run_tests.sh` drives the built console in a headless browser: 44
  checks covering the preset dropdown, the warnings and end-to-end discovery against
  a real WebSocket server. The preset dropdown shipped broken twice because nothing
  ever loaded the page.
- **Documentation reorganised.** Docker install, the reverse proxy for OpenWrt 24.10
  and Debian, reaching the console through it and troubleshooting are now in
  [`docs/DOCKER.md`](DOCKER.md). Voice — full duplex, push-to-talk half duplex,
  switching codec mid-call, and what each link speed can carry — is in
  [`docs/VOICE.md`](VOICE.md). The README is a feature list and an index again.

### What's new in v1.9.5

- **README restructured** — a single feature list replaces the version-by-version
  sections, and the reverse proxy setup for OpenWrt 24.10 and Debian is now inline
  rather than in a separate file.
- **Version history moved to `docs/CHANGELOG.md`**, which is where the release
  workflow now reads the release body from.

### What's new in v1.9.4

- **Reverse proxy fix** — the same-origin check now tolerates a proxy that strips
  the port from the `Host` header, which is what nginx's `proxy_set_header Host
  $host` does. v1.9.3 refused those connections with a 403.
- **Docker and reverse proxy documentation** — the README now carries the full
  Docker compose and nginx setup for OpenWrt 24.10 and Debian inline.
- **Corrected code signing guidance** in `docs/code-signing.md`: EV certificates
  have not granted instant SmartScreen reputation since 2024.

### What's new in v1.9.3

- **Works behind a reverse proxy** — the console bridge now accepts same-origin
  WebSocket connections, so a proxied deployment such as
  `https://liberty.local:8443` works with no extra configuration.
  `X-Forwarded-Host` is honoured. Cross-origin requests are still rejected.
- **Frequency presets are back on Transport Config**, and usable over Reticulum,
  but selecting one while connected over the mesh asks for confirmation first and
  spells out that saving will take the node off the mesh permanently.
- **Preset labels now carry their parameters** in the app's RNode interface
  dropdown, matching the console: `Long Fast — SF11 / 250 kHz / CR 4:5 (★ LCS
  Recommended)`. Long Fast remains the default.
- **Short Slow renamed to "Average - Recommended for Speed"** in all three preset
  dropdowns: the app's interface dropdown, the console's Node Config tab, and the
  console's Transport Config tab.
- **Reticulum 1.5.4 and LXST 0.5.3.**


### What's new in v1.9.2

- **Block an identity directly** — Settings → Blackhole takes an identity hash with
  an optional reason. No announce or prior contact is needed, since Reticulum blocks
  identities rather than destinations. The `<angle bracket>` form RNS prints is
  accepted, as is colon-delimited hex.
- **Block Contact no longer depends on a recent announce** — it resolves the peer's
  identity from RNS's persisted known-destinations table, then from MeshChat's own
  announce records, and finally by requesting a path so the announce is re-sent.
  It only fails if the destination has never been heard from at all, and says to
  paste the identity hash directly if so.
- **Release notes in the draft release** — the build workflow now generates the
  release body from this README's "What's new" section for the version being built,
  followed by the commits since the previous tag.
- **Clearer subscription wording** — the hash a subscriber adds as a source is the
  publisher's *transport instance* identity, which is a different key from your
  MeshChat identity.

### What's new in v1.9.1

**Blackhole management.** Conversations now have a **Block Contact** action in the
three-dot menu, and Settings gains a Blackhole section.

- **Block Contact** resolves the peer's destination hash to its identity hash and
  adds it to Reticulum's blackhole list — the same list `rnpath -B` writes.
  Announces from that identity are dropped and this node stops routing traffic to
  any of its destinations. It takes effect immediately.
- **Blocked list** in Settings shows everything blocked, whether you added it or a
  subscribed source did, with expiry and reason, and lets you unblock.
- **Publish** your list so other nodes can subscribe to it, served at
  `rnstransport.info.blackhole`.
- **Subscribe** to lists published by transport instances you trust, with a
  configurable update interval.

Blocking is identity-scoped and applies to your own network segments only. There is
no way to block anyone globally in Reticulum, and other nodes can still carry their
traffic. Publish and subscribe settings are read by Reticulum at startup, so those
need a restart; blocking and unblocking do not.

### What's new in v1.9.0

**Remote transport node management over Reticulum.** The Transport Node Console
in Tools can now reach RNode transport nodes anywhere on the mesh, not just ones
attached over USB, Bluetooth or the local network.

- **RNS console bridge** (`src/backend/rns_link_bridge.py`) — MeshChat's web
  server now answers the console's `rns.link.*` WebSocket protocol at `/rns/ws`
  and turns it into real Reticulum Link + Request traffic aimed at a node's
  `/provision` handler. It runs on the RNS instance and identity MeshChat
  already has: no extra daemon, no second identity store, no extra port.
- **Console auto-connect** — the Transport Node Console finds the bridge by
  itself. It probes the same origin first, so it works whether the console is
  opened from the Tools page, from disk, or from a hosted copy, and reports the
  actual cause when a browser blocks the connection rather than just failing.
- **Setup instructions** — selecting the LCS MeshChat transport now explains the
  one-time wired step: add your Identity Hash to the node's *Remote management
  allowed* list over USB-C serial before the node will answer you over the mesh.
- **Modem parameter warning** — Transport Config warns, when the node is reached
  over Reticulum, that changing frequency, bandwidth, SF or CR makes the node
  stop matching the mesh that carried the command, with no path left to undo it.
  Modem parameters need a USB-C serial connection.
- **Naming** — the console's transport is labelled "RNS (via LCS MeshChat)".
- **Deep links** — the console accepts `?dest=`, `?aspect=`, `?transport=`,
  `?ws=`, `?port=`, `?token=` and `?identify=0`, so a node can be linked to
  directly.
- **Origin allowlist** — WebSockets bypass CORS, so the bridge only accepts
  loopback origins and `file://` pages by default. `--rns-bridge-token` adds a
  shared secret, `--rns-bridge-allow-origin` permits a hosted console, and
  `--disable-rns-bridge` turns the whole thing off.

Over RNS the console exposes Node Status and Transport Config. Logs and Node
Config still need Serial, Bluetooth or a LAN WebSocket — they rely on legacy
KISS opcodes that don't survive the Reticulum hop. Nodes must be announcing on
`rnstransport.remote.management`, and your MeshChat identity hash has to be in
the node's `/provision` ALLOW_LIST.

See `docs/rns-console-bridge.md` for the protocol details and why
`attermann/ReticulumAPI` is not a drop-in substitute.
