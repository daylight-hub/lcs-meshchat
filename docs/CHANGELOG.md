# Changelog

Version history for LCS MeshChat. The release workflow reads the
section matching the version being built and uses it as the release body.

### What's new in v2.0.8

**MeshChat now announces once at startup, which is the fix for a restart
leaving you unreachable.** This is the headline, and it is worth explaining
rather than just listing, because it is not what the saved path table does.

The saved path table is *ours*. Restoring it tells this node "to reach that
peer, hand the packet to the Command Center" — and that is the whole of what it
tells anyone. The Command Center keeps its own path table, the far side's
Command Center keeps another, and the peer keeps a third. A message only lands
if all of those hold a live route, and a delivery proof only comes home if the
route back to *us* is live at every hop too. Restoring our own table repairs
exactly one of those four, and not the half that gets the answer back.

A path request cannot repair the rest either. The first transport node holding
any entry for the destination answers it out of its own packet cache and stops
it there, so it never crosses a hop.

An announce is the only packet we emit that every transport node rebroadcasts
rather than consumes, and it carries a fresh emission timestamp, so it is
accepted over whatever stale entry each hop was holding. One announce repairs
the route to us the whole way along.

The bug was that `last_announced_at` is saved to disk. After a restart the
auto-announce timer carried on from *before* the restart, so MeshChat stayed
silent for the remainder of the interval — up to three hours on the old default
— and during that window the far side had no route back. Sends failed waiting
for a proof that could not reach us. It also explains the oldest symptom in
this fork: announcing by hand made messages start flowing again.

It announces about fifteen seconds after launch, once interfaces are up and
AutoInterface has found its peers, and skips it if we announced within the last
five minutes so repeated restarts do not put a burst on the air. There is a
toggle in Settings under Messages.

**The default announce interval is now 1 hour, down from 3.** The interval is
the worst case for how long a peer can be unable to reach us across a transport
node whose entry has gone stale, and on an RF leg the announce is the only
repair there is. Liberty Chat moved to an hour for the same reason, which keeps
the two in step. Only affects installs that never set it; a saved value wins.

**The early-escalation watchdog from the first 2.0.8 is gone.** It pulled a
message out of LXMF's `pending_outbound` when a deadline passed and handed it
to the link rung early. That was my deviation — Liberty Chat does not do it,
and v2.0.7 did not either — and it made sending worse rather than faster,
because it raced the state machine that owns that queue and cut across LXMF's
own drop-and-rediscover step mid-flight.

The ladder is back to where v2.0.7 had it: the escalation to a link runs from
LXMF's failed callback, after its opportunistic retries are spent. Same order
as Liberty Chat's — opportunistic, link, rediscover, retry, propagation,
announce, fail. The minute that costs should matter much less now that the
route back is repaired at startup. If it still does, that is worth measuring
before tuning rather than guessing at again.

**Propagation node switching is off by default and far narrower when on.** The
first 2.0.8 replaced a selected node when it had gone quiet, and when it was
missing from the announce table altogether. Both were wrong, and the second one
is how people lost a working relay: a node absent from the announces is not a
node known to be broken. It can be a hash typed in by hand, an announce that
has been pruned, or your own local propagation node before it has announced —
and the first 2.0.8 also excluded your own local node from the candidates,
which guaranteed that reading for anyone using it.

Your own local node is a candidate again, absence never unseats a selection,
and silence never does either. The only thing that replaces a node in use is a
visibly closer one on a route we actually hold — and that behaviour is now
opt-in. Out of the box, auto-select fills an empty selection and then leaves it
alone, which is exactly what Liberty Chat does.

**Kept from the first 2.0.8:** the propagation announce parser fix, which was
reading the three field layout LXMF used years ago against announces that have
carried seven since 0.5 — field 0 is the legacy-support flag, hardcoded
`False`, and reading it as "enabled" made **every modern propagation node
display as Disabled by Operator**, while field 2, the real enabled flag, showed
up as the per-transfer limit. With the current layout parsed, the node's
advertised name and stamp cost become reachable, so the nodes page shows the
advertised name, the operator name beneath it, and the hop count, and the
settings page shows the same for the node in use.

Also kept: Ping going through `refresh_path` instead of a bare `request_path`
when no route is known, and reporting what actually failed. Ping measures a
route; Link Request repairs one. They are not duplicates.

**Link Request always tries twice.** The second attempt is a second chance
after the search the first failure provokes, and it cannot affect sending
because it only runs when you press the button. No longer a setting.

**Four settings are gone, and what they controlled is now fixed.** Each of
them was a way to turn off something there is no good reason to turn off, and
every one was a way for an install to end up quietly broken.

*Path request on send failure* is now always on. Off, a message that failed on
a stale path waited for the peer's next announce — an hour away at best — which
from the outside is indistinguishable from the message being lost.

*Save paths as they are learned* is now always on. Reticulum writes its path
table on a clean shutdown and otherwise every twelve hours, so off meant a hard
kill threw away most of what had been learned.

*Request paths on startup* is now permanently off, and the saved path table is
still loaded at startup exactly as before — they were always separate things.
The sweep could not do what matters after a restart anyway: a path request is
answered from the cache of the first node holding an entry and never crosses a
hop, so it repairs nothing further out. The startup announce does that instead.
The code is still there behind a constant, so it can come back if a network
ever turns up where it earns its airtime.

*Retry the Link Request button* is now always on, as above.

**One more parity fix.** The escalation now checks both of LXMF's method
fields — `desired_method`, what was asked for, and `method`, what LXMF
actually used — which is what Liberty Chat does. Either being opportunistic
means the message went out as a single packet, and so no transport node along
the way holds a link table entry for it.

361 checks across eight suites.

### What's new in v2.0.7

**Fixes a hang introduced in 2.0.6 that could stop MeshChat sending entirely.**
If you are on 2.0.6, update.

`LXMRouter.handle_outbound` waits for the router's own outbound lock with a
blocking sleep:

```python
while not unknown_path_requested and self.outbound_processing_lock.locked():
    time.sleep(0.05)
```

That made handing a message back to LXMF wrong in both of the places MeshChat
was doing it.

From a failure handler it was a deadlock. `fail_message` runs *inside*
`process_outbound`'s `with self.outbound_processing_lock` and calls the failed
callback synchronously, so 2.0.6's escalation to a link waited on a lock held by
its own call stack and spun forever — taking LXMF's outbound thread with it.
After that nothing sent again until a restart, which is why sends hung rather
than failing.

From the web server it froze the UI. The same spin ran on the asyncio event
loop, so while `process_outbound` held the lock nothing else on the loop ran,
every API call the frontend made hung, and the interfaces, announces and
conversations emptied out of the screen. This one predates 2.0.6 — the original
send path had always called `handle_outbound` on the loop — but the new rungs
made it far easier to hit.

Every resubmit now goes out on a worker thread, so the callback returns at once
and the lock is released. The original send is awaited on a thread instead,
which keeps the ordering the database row depends on.

Everything else that could stall the loop went the same way: dropping a path
(an RPC round trip when attached to a shared instance), reading and restoring
the cached announce around a refresh, and building or tearing down a link — in
the link probe and in the NomadNet downloader. A test now walks every async
function in `meshchat.py` and fails if any of them calls a blocking Reticulum or
LXMF entry point without `asyncio.to_thread`, so this class of freeze cannot
come back unnoticed.

**Messages always try opportunistic first now, whatever links exist.** The
delivery method used to depend on whether a link was available, which meant a
link — once established — became the carrier for every later message, so
pressing Link Request silently switched that conversation to DIRECT. The link is
there to provoke the network into finding a route, not to become the route. A
known ratchet is now the only condition for single-packet delivery, and the
ladder still escalates to a link, then a path refresh, then propagation if the
packet fails.

Worth stating because it is the reason this is safe: a peer's ratchet only ever
arrives on an announce from that peer (`Identity.py:597`), so a link cannot
supply one and there is nothing to gain by waiting for a link before going
opportunistic. What a link *can* do is get a route rediscovered — which is the
whole point of the button, and why it should leave the sending behaviour alone.

**A refused path request now announces too.** The per-peer attempt budget
stopping us from asking again is exactly when announcing matters most: asking is
over for that peer, so making ourselves findable is the only move left. The
announce keeps its own longer throttle, so this costs nothing.

**A remembered link is no longer mistaken for a working one.**
`LXMRouter.delivery_link_available` only asks whether the peer appears in
`direct_links` or `backchannel_links`; it never checks the link's status, so a
link that has closed or never came up keeps answering yes until `clean_links`
retires it. MeshChat used that to pick the delivery method, so a dead entry
meant choosing DIRECT and then spending the full establishment timeout per hop
before getting anywhere — the "direct takes forever" case, while the same
message sent opportunistically arrived at once. Only an ACTIVE link now counts.

### What's new in v2.0.6

**A failed opportunistic send now escalates to a link before falling back to a
propagation node.** This is the rung that makes a multi-hop mesh recover without
waiting for the far side to announce, and MeshChat did not have it.

A path request cannot cross a hop. The first transport node holding any entry
answers it from its own cache and stops it — `Transport.py:3459` precedes and
excludes the recursive search at `3531` — so it never reaches a radio and never
tests the route.

A failed link does cross. When a transport node relays a `LINKREQUEST` and the
proof never comes back, `Transport.jobs()` takes the `lr_taken_hops == 1` branch,
records the interface the request arrived on as `blocked_if`, and
`handle_disovery_path_requests` then asks on every *other* interface
(`Transport.py:1260-1263`). For a gateway bridging a local network to a radio,
"every other interface" is the radio. The link failure is what provokes the
network into looking.

MeshChat sends opportunistically whenever no link is up and a ratchet is known,
which is the common case. Opportunistic delivery builds no link, so the transport
node never gets a link table entry and that rediscovery never fires. The ladder
ran opportunistic, path request, propagation, and none of those three reaches
past the first hop — which is why the modem stayed silent while messages failed.
The ladder is now opportunistic, link, path request, propagation. It can be
turned off with `direct_link_on_send_failure_enabled`.

**Discover Path is now Link Request.** The old button could not do what it
appeared to do, for the reason above: a path request is answered from cache by
the first transport node that holds an entry, so it never crosses a hop, never
reaches a radio and never tests the route. It reported what your nearest
transport node believed and nothing more.

The new button refreshes the route and then opens a real link over it —
*whether or not a path came back*. Declining to try when no path is known would
throw away the only lever that reaches past the first hop, because a link
request that dies in transit is exactly what makes the transport nodes along the
way go looking on your behalf. A link that comes up is handed to LXMF rather
than torn down, so the next message reuses it instead of paying for another
handshake. The result is reported honestly: established or not, hop count, and
the interface it went out on.

**When nothing answers, MeshChat announces instead of giving up.** An empty
rediscovery means there is nothing further to ask — the request stopped at the
first hop. An announce is the opposite shape: every node that hears it
rebroadcasts it, and it carries a fresh emission timestamp, so it is accepted
over any existing entry at every hop out to the edge. That repairs *their* route
to this node rather than this node's route to them, which turns out to be
enough: LXMF files an inbound link under `backchannel_links` and delivers over
it, so once they can reach you, their next message opens a link and anything
queued for them goes back out on it. Throttled to one per peer per ten minutes,
with a one-minute floor across all peers so a batch of failures cannot become a
burst of announces on a slow link, and cleared as soon as that peer is heard
from. Turn it off with `announce_on_unreachable_peer_enabled`.

**A path request no longer risks destroying the cached announce behind the route
it is refreshing.** `clean_announce_cache()` deletes every cached announce the
path table does not reference, and runs every five minutes. Dropping the entry
left its announce unreferenced, so a cleaning pass landing in that window deleted
the file permanently, and restoring the entry afterwards left it pointing at
nothing. That is the state where a node answers a path request with neither a
reply nor a search, because `answered = True` is set at `3463` before the cache
lookup is checked at `3466`. The announce is now read before the drop and put
back with the entry.

### What's new in v2.0.5

**Reloading an AutoInterface no longer throws away every route learned on it.**
This was introduced in v2.0.3 by the link-change reload itself, and it is the
reason messages worked for a while after a restart and then stopped until an
announce was sent by hand.

`Transport.jobs()` culls every path table entry whose attached interface has
left `Transport.interfaces` — "removed since the attached interface no longer
exists" — and `Reticulum._reload_interface` is a detach followed by an attach,
so the interface object every entry points at is gone within a second of the
reload. A restart survives this because the path table is read back from storage
inside `Transport.start`; a reload has nothing behind it, so the routes were
simply gone. MeshChat then persisted the emptied table, making the loss
permanent.

The reload now snapshots the affected entries first and rebinds them afterwards.
AutoInterface does not carry traffic itself — its `process_outgoing` is a no-op —
so entries are rebound to the respawned peer they were actually learned through,
matched on its local interface name and link-local address, and only once that
peer has been rediscovered. A route whose peer did not come back is left
dropped, because it genuinely is gone, and anything relearned while waiting wins
over the snapshot. Saving the path table is suspended until the restore
finishes. The interface slot in each entry is located by type rather than by a
fixed offset, since that layout has moved between RNS releases and writing the
wrong field would corrupt routing silently.

**A reload is now followed by an announce.** Every peer lost its route to us at
the moment the interface was detached, and a path request cannot repair that — it
asks about a destination and says nothing about the asker. Announcing is what
makes this node reachable again so the far side can answer at all, which is
exactly why sending one by hand fixed things.

**Auto-announce now defaults to 3 hours, down from 6.** Routes back to this node
are lost on interface churn, not only on timeout, so six hours left long windows
in which nothing on the mesh could reach us. Liberty Chat announces every three
hours; matching it stops the two drifting apart. Only affects installs that never
changed the setting.

### What's new in v2.0.4

**A message handed to a propagation node no longer disappears once the node's
route is recovered.** v2.0.3 added the missing rung that asks the network about
the propagation node after a propagated send fails, and that part worked — the
route came back. What happened next did not. Two things were wrong.

The first is that a message already aimed at a node fell off the bottom of the
resolution loop. That loop had two outcomes, retry the message or hand it to its
propagation fallback, and a propagated message has no further fallback to hand it
to, so when the node stayed unreachable nothing ran at all: no retry, no report,
nothing in the log. It now has a branch of its own and says what it decided.

The second lost messages even when the route was repaired. LXMF will not queue a
propagated message until it has built a propagation stamp, and it reads the cost
for that stamp out of the node's cached announce rather than off the wire. With no
usable copy of that announce, `process_deferred_stamps` fails the message outright
— before any link is attempted — so it reads as a delivery failure while no
delivery was ever tried. LXMF's own recovery here is a bare
`Transport.request_path` followed by a poll of `recall_app_data`, which is exactly
the pattern v2.0.3 established cannot work against a destination already in the
table: the replayed announce is rejected as one already heard, so the cached data
it waits for never changes and the wait always times out.

Refreshing the node's path drops the entry first, so the announce does land again
and the cost becomes readable. The retry now reads it before re-sending, and when
it cannot, says which of the two things is wrong: a route that never came back, or
a route that came back behind an announce carrying no usable propagation config.
The first hand-off to a node warns in the same terms, so a failure that was never
a routing problem is no longer silent.

The retry also goes back out as propagated rather than through the generic retry,
which would have re-sent it as whatever delivery method it had before.

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

**A failed propagated message now asks about the propagation node.** Everything
falls back to the node, and it was the one destination in the whole delivery ladder
with no recovery at all: when a propagated send failed, the message simply stopped
there and nothing asked where the node had gone.

LXMF does not cover this. Its propagated branch requests a path only when it has
none — with a stale entry it goes straight to `RNS.Link`, the link fails, and it
retries the same dead route until the attempt count runs out, never asking. The
drop-and-rediscover that rescues opportunistic delivery does not exist in that
branch either. So the node now gets the same refresh the recipient gets, keyed on
its own hash so the two have separate attempt counters and cooldowns, and a
propagated message the node accepts resets the node's budget.

**AutoInterface now reloads within seconds of a cable moving, instead of up to a
minute and a half.** AutoInterface joins its multicast group once, in `__init__`, so
an interface that appears after startup is never adopted however long you wait —
unplugging ethernet and plugging it back in left it unused. Recovery previously came
from the staleness check, which looked every 30 seconds and wanted two consecutive
bad readings, and only noticed at all once everything else had gone quiet too.

The monitor now wakes every two seconds and compares what the system actually has:
interface names, their carrier state where the kernel exposes it (sysfs on Linux),
and their link-local addresses. A change that *adds* something usable triggers a
reload almost at once — that is unambiguous, and there is nothing to gain by
waiting. A change that only removes something does not, because there is nothing to
rebuild onto; the staleness path judges that case as before. Changes settle for three
seconds first, so unplug-then-replug is one reload rather than two.

Because a carrier coming back is hard evidence rather than something inferred from
silence, link-change reloads get their own budget: a 15-second gap and up to 12 an
hour, against five minutes and four an hour for staleness. An active call still
blocks a reload outright, and container and VPN interfaces still never trigger one.

**Startup no longer sends path requests by default.** The saved path table is loaded
at startup and covers every peer whose cached announce survived, so the sweep was
only adding anything for the handful it could not restore — and on a LoRa link that
is a burst of airtime for very little. It is now off unless you turn it on in
Settings. If you enabled it explicitly on an earlier version your setting is kept,
so turn it off there.

**Fixed:** the AutoInterface recovery test suite could not run on Python 3.13 — it
re-wrapped an already-decorated class method, which 3.13 refuses to call. All five
suites pass (181 checks).

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
