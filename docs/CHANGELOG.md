# Changelog

Version history for LCS MeshChat. The release workflow reads the
section matching the version being built and uses it as the release body.

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
