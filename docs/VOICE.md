# Voice calls

LCS MeshChat carries voice over Reticulum with LXST. Calls work on anything from
Ethernet down to LoRa, provided the call is matched to what the link can carry —
which is what the two controls below are for.

- [Full duplex and half duplex (PTT)](#full-duplex-and-half-duplex-ptt)
- [Switching codec mid-call](#switching-codec-mid-call)
- [Choosing for the link you have](#choosing-for-the-link-you-have)
- [When the link is too slow for a live call](#when-the-link-is-too-slow-for-a-live-call)
- [Requirements](#requirements)

---

## Full duplex and half duplex (PTT)

Every call has a **Call Mode**, set before dialling and changeable at any point
during the call from the toggle on the call screen.

**Full duplex** is an ordinary phone call. Both ends transmit continuously and
either side can interrupt the other. It needs enough capacity for two simultaneous
audio streams and is the right choice on Wi-Fi, Ethernet, TCP, and on LoRa at Short
Fast or better.

**Half duplex** is push-to-talk. Only one side transmits at a time. Entering half
duplex starts you squelched — listening, not transmitting — and a large **Hold to
Talk** button appears. Hold it to transmit, release to go back to listening. The
button turns red while transmitting so there is no doubt which way the channel is
pointing.

Because only one direction is live at a time, half duplex roughly halves what the
link has to carry, and it removes the feedback and collision problems that make
continuous two-way audio unusable on a slow shared channel. On LoRa it is usually
the difference between a call that works and one that does not.

The mode is negotiated, so both ends follow the switch. Toggling back to full duplex
restores continuous transmission rather than leaving you silently squelched.

Half duplex needs LXST 0.5.1 or later on both ends. Against an older peer the Call
Mode control is simply absent and calls are full duplex.

---

## Switching codec mid-call

**Call Quality** selects the audio profile — the codec and bitrate. It is set before
dialling and, unlike most voice systems, **can be changed while the call is up**,
from the dropdown on the call screen. The change is signalled to the other end and
takes effect on the next audio frame; the call is not dropped and re-established.

The profiles on offer come from LXST and span Codec2 at its various bitrates through
to Opus at speech and full-quality settings. Low-bitrate Codec2 sounds thin and
robotic but survives a link that would carry nothing else; Opus is transparent and
needs real bandwidth.

Being able to move between them without hanging up is what makes voice usable on a
mesh where conditions change. If a node reroutes onto a slower path and audio starts
breaking up, drop the quality and carry on talking. If a call starts on LoRa and the
peer comes back on Wi-Fi, raise it. The call screen shows the codec the remote end is
actually sending, so you can see the effect of a change rather than guess at it.

---

## Choosing for the link you have

| Link | Mode | Quality |
|---|---|---|
| Ethernet, Wi-Fi, TCP | Full duplex | Opus, any profile |
| LoRa — Short Turbo, Short Fast | Full duplex | Codec2, mid-rate |
| LoRa — Average, Medium Fast | Half duplex | Codec2, low rate |
| LoRa — Long Fast and slower | Voice clips, not a live call | — |

**Long Fast** (≈1.07 kbps) is the general-purpose LCS preset for text and is the
default on LCS nodes, but it cannot sustain a live call in either mode. Short Fast is
the fastest preset that still has useful range and is the practical floor for
real-time voice over LoRa.

Presets are set per node from the app's RNode interface dialog, and on a transport
node from the **Transport Console**, which carries the same preset list under
Transport Config → the RNode radio namespace. See
[Managing transport nodes](#managing-transport-nodes-over-the-same-mesh) below.

---

## When the link is too slow for a live call

Record a **voice clip** instead. Clips are recorded, encoded and sent as ordinary
LXMF messages, so they travel the same way text does: store-and-forward, retried,
delivered whenever a path exists. They work on any link at any speed, including Long
Slow, and they work when the other end is offline.

For a slow mesh this is usually the right tool. A live call demands a path that stays
up for its whole duration; a clip does not.

---

## Managing transport nodes over the same mesh

Voice and node management run over the same Reticulum instance, so the mesh that
carries a call is the mesh that carries the Transport Node Console.

The console is at **Tools → Transport Console**, and it is the same console whether
the node is on the bench or on a hilltop:

- **Locally** — connect over **Serial** (USB-C), **Bluetooth**, or a **LAN
  WebSocket**. All tabs are available, including Logs and Node Config.
- **Remotely** — connect over **RNS (via LCS MeshChat)** and reach any node on the
  mesh, at any distance, with no sidecar daemon, no second identity and no extra
  port. Node Status and Transport Config are available; Logs and Node Config are not,
  because they rely on legacy KISS frames that do not cross the Reticulum hop.

Everything else is identical: the same fields, the same namespaces, the same
frequency presets with the same labels as the app's own RNode dropdown. So the node
you provisioned over a cable is configured the same way a year later from across the
network.

One caveat, and the console states it plainly on the page: **do not change radio
parameters on a node you reached over the air.** Frequency, bandwidth, spreading
factor and coding rate are how that node reaches the mesh you are talking to it
through. Change one, save it, and the node applies it, stops matching everything
around it and goes silent — with no path left to undo it. Selecting a frequency
preset over Reticulum asks for confirmation first. Recovering a node that has been
taken off its own mesh means physically reaching it with a USB-C cable.

Commissioning a node's radio settings is a wired job. Everything after that is not.

---

## Requirements

- **A secure context.** Browsers only grant microphone access over HTTPS or on
  `localhost`. Desktop builds satisfy this automatically. A Docker deployment needs
  an HTTPS reverse proxy — see [DOCKER.md](DOCKER.md).
- **Codec2.** Desktop builds bundle it; macOS builds install it from Homebrew so
  `pycodec2` compiles.
- **LXST 0.5.1+ on both ends** for the Call Mode control. Codec switching and
  full-duplex calling work without it.
- **A link with enough capacity** for the mode and profile chosen, per the table
  above.
