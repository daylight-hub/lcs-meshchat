<p align="center">
<img src="./logo/logo-chat-bubble.png" width="150">
</p>

<h2 align="center">LCS MeshChat</h2>

<p align="center">
A Liberty Communication Systems, Inc. distribution of Reticulum MeshChat.<br/>
built on MeshChat by Liam Cottle · <a href="https://lcs.network">lcs.network</a>
</p>

---

**LCS MeshChat** is Liberty Communication Systems' branded distribution of
Reticulum MeshChat, with additional features for LCS network deployments. It is
built on the open-source [Reticulum MeshChat](https://github.com/liamcottle/reticulum-meshchat)
by Liam Cottle (MIT licensed — see `LICENSE`).

## Documentation

| | |
|---|---|
| [**Docker**](docs/DOCKER.md) | Container install, the HTTPS reverse proxy for OpenWrt and Debian, reaching the console through it, troubleshooting |
| [**Voice calls**](docs/VOICE.md) | Full duplex, push-to-talk, switching codec mid-call, and what each link speed can carry |
| [**RNS console bridge**](docs/rns-console-bridge.md) | How remote node management over Reticulum works, and the one-time setup each node needs |
| [**Code signing**](docs/code-signing.md) | The Windows download warning, and where signing stands |
| [**Changelog**](docs/CHANGELOG.md) | Version history |
| [Raspberry Pi](docs/meshchat_on_raspberry_pi.md) · [Android/Termux](docs/meshchat_on_android_with_termux.md) | Upstream platform guides |

## Install

**Desktop** — download the installer for Windows, macOS or Linux from
[Releases](https://github.com/daylight-hub/reticulum-meshchat/releases).

**Docker** — see [docs/DOCKER.md](docs/DOCKER.md). The short version:

```sh
docker run -d --name reticulum-meshchat --restart unless-stopped \
  -e LCS_DOCKER=1 -p 8082:8000 -v /opt/reticulum-meshchat:/config \
  ghcr.io/daylight-hub/reticulum-meshchat:latest \
  python meshchat.py --host=0.0.0.0 --port=8000 \
  --reticulum-config-dir=/config/.reticulum \
  --storage-dir=/config/.meshchat --headless
```

Voice calls in Docker need an HTTPS reverse proxy, because browsers only give a page
microphone access in a secure context. That setup is in the Docker guide.

---

## Features

### Branding and navigation

- LCS logo throughout, "LCS MeshChat" naming, brand accent styling. Reports as LCS
  MeshChat, and the About page shows the LXST version.
- **Add LCS Interfaces** — a header button opens a dialog to add LCS network
  interfaces to Reticulum. Choose which to add, whether to enable them immediately,
  and auto-detect a connected RNode's serial port:
  - **LCS Gateway Client** — `public.lcs.network` (TCP, gateway mode)
  - **IP RNode** — `iprnode.local:4545` (TCP, network-attached RNode)
  - **RNode LoRa** — direct serial LoRa radio (914.875 MHz, SF11), added disabled
    unless a serial port is provided.
- **Restart button** (Docker builds only) — restarts the app process, relying on the
  container's `restart: unless-stopped` policy. Does not need the Docker socket.
- **Back button**, **incoming call ringtone**, and a **Buy RNode Radios** link in the
  sidebar and Tools.

### Voice — [full guide](docs/VOICE.md)

- **Full duplex and half duplex.** Half duplex is push-to-talk: one side transmits at
  a time, with a hold-to-talk button and a clear transmitting indicator. It roughly
  halves what the link carries and is what makes voice workable over LoRa.
- **Switch call mode during a call.** The toggle is live on the call screen and the
  change is negotiated with the other end, so a call that started full duplex can
  drop to PTT when conditions worsen instead of being hung up and redialled.
- **Switch codec mid-call.** Call Quality moves between Codec2 bitrates and Opus
  while the call is up, signalled to the peer and applied on the next audio frame.
  The call screen shows the codec the remote end is actually sending.
- **Voice clips** for links too slow for a live call — recorded and sent as LXMF
  messages, so they work at any speed and when the other end is offline.
- Preset guidance per link speed, from Ethernet down to Long Slow, in the voice
  guide and in Tools.

### Transport Node Console — Tools → Transport Console

The same console whether the node is on your desk or across the mesh. Local and
remote management differ only in which transport you pick.

- **Local** — Serial (USB-C), Bluetooth, or a LAN WebSocket. All tabs available.
- **Remote over Reticulum** — MeshChat answers the console's `rns.link.*` protocol at
  `/rns/ws` and turns it into Reticulum Link and Request traffic aimed at a node's
  `/provision` handler. It runs on the RNS instance and identity MeshChat already
  has: no sidecar daemon, no second identity store, no extra port. Node Status and
  Transport Config are available; Logs and Node Config need a local transport,
  because they rely on legacy KISS frames that do not cross the Reticulum hop.
- **Auto-connect** — the console finds the bridge itself, in three tiers: this page's
  own address first, then this computer, then a sweep of the local network for
  `.local` names on the proxy port. Hosts that have worked before are tried first.
  When a browser blocks the connection it names the actual cause, and offers a box to
  type an address into.
- **Setup guidance** — selecting the LCS MeshChat transport explains the one-time
  wired step of adding your Identity Hash to the node's remote-management allow list.
- **Frequency presets** on Node Config and Transport Config, with the same labels as
  the app's RNode interface dropdown. On a node reached over the mesh, selecting one
  asks for confirmation first and warns that saving will take the node off the mesh
  permanently.
- **Deep links** — `?dest=`, `?aspect=`, `?transport=`, `?ws=`, `?hosts=`, `?port=`,
  `?token=`, `?identify=0`.

### Blackhole management

- **Block Contact** in a conversation's three-dot menu, backed by the same Reticulum
  calls `rnpath -B/-U/-b` drives. Blocks are permanent until removed.
- Identity resolution without needing a recent announce: RNS's persisted
  known-destinations table, then MeshChat's own announce records, then a path request.
- **Block an identity directly** by pasting its hash in Settings. The
  `<angle bracket>` form RNS prints is accepted, as is colon-delimited hex.
- **Publish** your blocked list for others to subscribe to, served at
  `rnstransport.info.blackhole`, and **subscribe** to lists from transport instances
  you trust, with a configurable update interval.
- Blocking is identity-scoped and applies to your own network segments only. Publish
  and subscribe settings are read by Reticulum at startup and need a restart;
  blocking and unblocking do not.

### Deployment

- Runs behind an HTTPS reverse proxy with no extra configuration — the bridge accepts
  same-origin WebSocket connections and tolerates a proxy that strips the port from
  the `Host` header.
- Origin allowlist on the bridge, since WebSockets bypass CORS, plus an optional
  `--rns-bridge-token` shared secret.
- Draft releases get a generated body: the matching section of `docs/CHANGELOG.md`,
  followed by the commits since the previous tag.

## Privacy

LCS MeshChat does not collect, transmit or sell personal information. There is no
telemetry, no analytics, no crash reporting and no account. Your identity keys,
messages and configuration stay in your own storage directory on your own machine.
Network traffic goes only to the Reticulum interfaces you configure yourself. The
application is open source and the code in this repository is what is built into the
released binaries.

**A note on the Windows download warning.** Microsoft Edge and SmartScreen may warn
that the installer is not commonly downloaded. This is a reputation check on the
signature of the file, not a finding about its content — it appears for any new
unsigned binary regardless of what it does. See
[docs/code-signing.md](docs/code-signing.md) for the status of signing.

## Build & deploy

- **Docker** — GitHub Actions builds a multi-arch image on every push to the `lcs`
  branch, pushed to `ghcr.io/<owner>/reticulum-meshchat:latest` and `:lcs`.
- **Desktop apps** (Windows/Mac/Linux) — built on a version tag push, or via the
  Actions "Run workflow" button with the desktop-build option enabled. All desktop
  artifacts attach to a single release. Mac builds install `codec2` via Homebrew so
  the `pycodec2` dependency compiles.
- **Transport console** — the console is a vendored single-file build with two LCS
  scripts appended. Edit the sources in `tools/console/`, then:

  ```sh
  sh tools/console/run_tests.sh
  ```

  which rebuilds `src/frontend/public/transport-console/index.html` and drives the
  result in a headless browser to check the additions still attach. Never hand-edit
  the built console.

## License

The LCS name, logos, branding, and additions are the property of Liberty
Communication Systems, Inc. The underlying Reticulum MeshChat remains MIT licensed;
that notice is retained in `LICENSE` as required.

MIT
