# Changelog

Version history for LCS MeshChat. The release workflow reads the
section matching the version being built and uses it as the release body.

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
