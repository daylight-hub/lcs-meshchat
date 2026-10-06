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
| [**Changelog**](docs/CHANGELOG.md) | Version history |
| [Raspberry Pi](docs/meshchat_on_raspberry_pi.md) · [Android/Termux](docs/meshchat_on_android_with_termux.md) | Upstream platform guides |

## Install

**Desktop** — download the installer for Windows, macOS or Linux from
[Releases](https://github.com/daylight-hub/lcs-meshchat/releases).

**Docker** — see [docs/DOCKER.md](docs/DOCKER.md). The short version:

```sh
docker run -d --name lcs-meshchat --restart unless-stopped \
  -e LCS_DOCKER=1 -p 8082:8000 -v /opt/lcs-meshchat:/config \
  ghcr.io/daylight-hub/lcs-meshchat:latest \
  python meshchat.py --host=0.0.0.0 --port=8000 \
  --reticulum-config-dir=/config/.reticulum \
  --storage-dir=/config/.meshchat --headless
```

Voice calls in Docker need an HTTPS reverse proxy, because browsers only give a page
microphone access in a secure context. That setup is in the Docker guide.

---

## Features

### Branding and navigation

- Updated to the most recent RNS version 1.5.5, LXMF version 1.1.1, and LXST version 0.5.3.
- **Add LCS Interfaces** — a header button opens a dialog to add LCS network
  interfaces to Reticulum. Choose which to add, whether to enable them immediately,
  and auto-detect a connected RNode's serial port:
  - **LCS Gateway Client** — (TCP, gateway mode)
  - **Command Center PRO Client** — `liberty.local:4246` (TCP), off by default
  - **IP RNode** — `iprnode.local:4545` (TCP, network-attached RNode)
  - **RNode LoRa** — direct serial LoRa radio (914.875 MHz, 17 dBm), added disabled
    unless a serial port is provided.
- **Restart button** (Docker builds only) — restarts the app process, relying on the
  container's `restart: unless-stopped` policy. Does not need the Docker socket.
- **Incoming call ringtone added**
- **New message sound** — a short chime when a message arrives, generated in the
  browser rather than shipped as an audio file, and distinct from the call ringtone.
  Toggle and test button under Settings → Notifications.
- **Reset Identity** at the end of Settings — generates a new Reticulum identity and
  LXMF address after two confirmations. Nothing is deleted: the previous key is kept
  as `identity.replaced-<timestamp>` and the old database stays under its own
  identity hash. Takes effect on restart.
- **RNode management console** in tools

### Radio settings

- **Board-aware transmit power.** The RNode interface form has a Radio Board picker
  that holds TX power at or below what that board's radio will accept — SX127x
  17 dBm, SX1262 22, Heltec v4 28, SX1280 13, SX1280 with PA 20 — with a deliberate
  override up to 30 dBm. This matters because the failure is silent: the firmware
  clamps anything over the ceiling, Reticulum compares what it asked for against
  what the radio reports back, rejects the mismatch, and the interface never comes
  up. A LilyGo set to 20 dBm simply does not transmit. The form explains that where
  you set the value.
- **Presets set modem parameters only**, not transmit power, which belongs to the
  board rather than to the channel. Nine presets from Short Turbo to Long Slow,
  including **Long Range / Turbo** (SF11 / 500 kHz / CR 4:8), with **Long Fast** as
  the default. The app's list and both Transport Console dropdowns are generated
  from `src/frontend/js/rnode-presets.json`, so they cannot drift apart.

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

Use the same console whether the transport node is on your desk or remote across the mesh. Local and
remote management differ only in which transport you pick.

- **Local** — Serial (USB-C), Bluetooth, or a LAN WebSocket. All tabs available.
- **Remote over Reticulum** — MeshChat answers the console's `rns.link.*` protocol at
  `/rns/ws` and turns it into Reticulum Link and Request traffic aimed at a node's
  `/provision` handler. It runs on the RNS instance and identity MeshChat already
  has: no sidecar daemon, no second identity store, no extra port. Node Status and
  Transport Config are available; Logs and Node Config need a usb-c serial connection,
  because they rely on legacy KISS frames that do not cross the Reticulum hop.
- **Auto-connect** — the console finds the bridge itself, in three tiers: this page's
  own address first, then this computer, then a sweep of the local network for
  `.local` names on the proxy port. Hosts that have worked before are tried first.
  When a browser blocks the connection it names the actual cause, and offers a box to
  type an address into.
- **Setup Remote Management** — selecting the LCS MeshChat transport explains the one-time usb-c wire step of adding your Identity Hash (not LXMF address) to the node's remote-management allow list.
- **Network Visualizer** will show the microReticulum node. This is **not** the address to enter in the transport console. Click on the node to open its nomadnet page. You may have to click the button to identify yourself(the fingerprint button). Then click **General**. Copy the management destination listed and paste over in the transport console **destination hash** box. click **connect**.

### Blackhole management

- **Block Contact** in a conversation's three-dot menu, blocks permanently until removed.
- Identity resolution without needing a recent announce: RNS's persisted
  known-destinations table, then MeshChat's own announce records, then a path request.
- **Block an identity directly** by pasting its hash in Settings. The
  `<angle bracket>` form RNS prints is accepted, as is colon-delimited hex.
- **Publish** your blocked list for others to subscribe to, served at
  `rnstransport.info.blackhole'
  **Subscribe** to lists from transport instances
  you trust, with a configurable update interval.

### Deployment

- Runs behind an HTTPS reverse proxy with no extra configuration — the bridge accepts
  same-origin WebSocket connections and tolerates a proxy that strips the port from
  the `Host` header.
- Origin allowlist on the bridge, since WebSockets bypass CORS, plus an optional
  `--rns-bridge-token` shared secret.

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
unsigned binary regardless of what it does. The warning clears once a release
accumulates download reputation, or sooner with a code-signing certificate.

## License

The LCS name, logos, branding, and additions are the property of Liberty
Communication Systems, Inc. The underlying Reticulum MeshChat remains MIT licensed;
that notice is retained in `LICENSE` as required.

MIT
