#!/usr/bin/env python

import argparse
import asyncio
import base64
import io
import json
import os
import shutil
import platform
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from typing import Callable, List

import LXMF
import LXST
import RNS
import RNS.vendor.umsgpack as msgpack
import numpy
from LXMF import LXMRouter
from LXST import Telephone
from LXST.Primitives.Telephony import Profiles
from aiohttp import web, WSMessage, WSMsgType, WSCloseCode
from peewee import SqliteDatabase
from serial.tools import list_ports

import database
from src.backend.announce_handler import AnnounceHandler
from src.backend.async_utils import AsyncUtils
from src.backend.audio_call_manager import AudioCall, AudioCallManager
from src.backend.colour_utils import ColourUtils
from src.backend.interface_config_parser import InterfaceConfigParser
from src.backend.interface_editor import InterfaceEditor
from src.backend.lxmf_message_fields import LxmfImageField, LxmfFileAttachmentsField, LxmfFileAttachment, LxmfAudioField
from src.backend.rns_link_bridge import BridgeConfig, LocalBackend, attach_to_app, run_standalone
from src.backend.blackhole import BlackholeManager
from src.backend.sideband_commands import SidebandCommands

# hack to avoid below error on windows from soundcard/mediafoundation.py in self._record_chunk()
# ValueError: The binary mode of fromstring is removed, use frombuffer instead
numpy.fromstring = numpy.frombuffer


# NOTE: this is required to be able to pack our app with cxfreeze as an exe, otherwise it can't access bundled assets
# this returns a file path based on if we are running meshchat.py directly, or if we have packed it as an exe with cxfreeze
# https://cx-freeze.readthedocs.io/en/latest/faq.html#using-data-files
def get_file_path(filename):
    if getattr(sys, "frozen", False):
        datadir = os.path.dirname(sys.executable)
    else:
        datadir = os.path.dirname(__file__)
    return os.path.join(datadir, filename)


class ReticulumMeshChat:

    def __init__(self, identity: RNS.Identity, storage_dir, reticulum_config_dir,
                 identity_file_path=None):

        # LCS: path-request-on-send-failure bookkeeping, keyed by destination hash.
        # Each entry is {"at": <unix seconds of last attempt>, "count": <attempts>}.
        # A resend creates fresh messages, which can fail again and call straight
        # back into here, so both a cooldown and an attempt cap are required or
        # one unreachable peer would spin indefinitely.
        self.path_request_attempts = {}

        # Failed messages waiting on the outcome of a path request, keyed by
        # destination hash, plus the destinations currently being asked about. One
        # unreachable peer fails every queued message for it, and all of those must
        # be resolved by a single request rather than each triggering its own.
        self.pending_path_requests = {}
        self.path_requests_in_flight = set()

        # the file the running identity was loaded from, so it can be replaced by
        # the identity reset. None when the identity came from --identity-base64,
        # which has no file to rewrite.
        self.identity_file_path = identity_file_path

        # when providing a custom storage_dir, files will be saved as
        # <storage_dir>/identities/<identity_hex>/
        # <storage_dir>/identities/<identity_hex>/database.db

        # if storage_dir is not provided, we will use ./storage instead
        # ./storage/identities/<identity_hex>/
        # ./storage/identities/<identity_hex>/database.db

        # ensure a storage path exists for the loaded identity
        self.storage_dir = storage_dir or os.path.join("storage")
        self.storage_path = os.path.join(self.storage_dir, "identities", identity.hash.hex())
        print("Using Storage Path: {}".format(self.storage_path))
        os.makedirs(self.storage_path, exist_ok=True)

        # define path to files based on storage path
        self.database_path = os.path.join(self.storage_path, "database.db")
        lxmf_router_path = os.path.join(self.storage_path, "lxmf_router")

        # check if database already exists, before initialization
        database_already_exists = os.path.exists(self.database_path)

        # init database
        sqlite_database = SqliteDatabase(self.database_path)
        database.database.initialize(sqlite_database)
        self.db = database.database
        self.db.connect()
        self.db.create_tables([
            database.Config,
            database.Announce,
            database.CustomDestinationDisplayName,
            database.FavouriteDestination,
            database.LxmfMessage,
            database.LxmfConversationReadState,
            database.LxmfUserIcon,
        ])

        # init config
        self.config = Config()

        # if database already existed before init, and we don't have a previous version set, we are on version 1
        if database_already_exists and self.config.database_version.get() is None:
            self.config.database_version.set(1)

        # if database didn't already exist, it was just fully migrated when it was created, so set the current version
        if not database_already_exists:
            self.config.database_version.set(database.latest_version)

        # migrate database
        current_database_version = self.config.database_version.get()
        migrated_database_version = database.migrate(current_version=current_database_version)
        self.config.database_version.set(migrated_database_version)

        # vacuum database on start to shrink its file size
        sqlite_database.execute_sql("VACUUM")

        # lxmf messages in outbound or sending state should be marked as failed when app starts as they are no longer being processed
        (database.LxmfMessage.update(state="failed")
         .where(database.LxmfMessage.state == "outbound")
         .orwhere((database.LxmfMessage.state == "sent") & (database.LxmfMessage.method == "opportunistic"))
         .orwhere(database.LxmfMessage.state == "sending").execute())

        # init reticulum
        self.reticulum = RNS.Reticulum(reticulum_config_dir)
        self.identity = identity

        # init lxmf router
        self.message_router = LXMF.LXMRouter(identity=self.identity, storagepath=lxmf_router_path)
        self.message_router.PROCESSING_INTERVAL = 1

        # increase limit for incoming lxmf messages (received over a resource), to allow receiving larger attachments
        # the lxmf router expects delivery_per_transfer_limit to be provided in kilobytes, so we will do that...
        self.message_router.delivery_per_transfer_limit = self.config.lxmf_delivery_transfer_limit_in_bytes.get() / 1000

        # register lxmf identity
        self.local_lxmf_destination = self.message_router.register_delivery_identity(
            identity=self.identity,
            display_name=self.config.display_name.get(),
        )

        # set a callback for when an lxmf message is received
        self.message_router.register_delivery_callback(self.on_lxmf_delivery)

        # update active propagation node
        self.set_active_propagation_node(self.config.lxmf_preferred_propagation_node_destination_hash.get())

        # enable propagation node (we don't call with false if disabled, as no need to announce disabled state every launch)
        if self.config.lxmf_local_propagation_node_enabled.get():
            self.enable_local_propagation_node()

        # handle received announces based on aspect
        RNS.Transport.register_announce_handler(AnnounceHandler("call.audio", self.on_audio_call_announce_received))
        RNS.Transport.register_announce_handler(AnnounceHandler("lxmf.delivery", self.on_lxmf_announce_received))
        RNS.Transport.register_announce_handler(AnnounceHandler("lxmf.propagation", self.on_lxmf_propagation_announce_received))
        RNS.Transport.register_announce_handler(AnnounceHandler("nomadnetwork.node", self.on_nomadnet_node_announce_received))

        # remember websocket clients
        self.websocket_clients: List[web.WebSocketResponse] = []

        # register audio call identity
        self.audio_call_manager = AudioCallManager(identity=self.identity)
        self.audio_call_manager.register_incoming_call_callback(self.on_incoming_audio_call)

        # init telephone if enabled
        self.telephone = None
        if self.config.telephone_enabled.get():
            self.init_telephone()

        # start background thread for auto announce loop
        thread = threading.Thread(target=asyncio.run, args=(self.announce_loop(),))
        thread.daemon = True
        thread.start()

        # start background thread for auto syncing propagation nodes
        thread = threading.Thread(target=asyncio.run, args=(self.announce_sync_propagation_nodes(),))
        thread.daemon = True
        thread.start()

    # adds the LCS preset interfaces (public TCP backbone + RNode LoRa template) to the
    # reticulum config using the config object. append-only and idempotent: an interface is
    # only added if not already present; existing interfaces are never modified. returns the
    # list of interface names that were added.
    def add_lcs_preset_interfaces(self, selected=None, enable=True, rnode_host=None, rnode_port=None, rnode_serial_port=None):

        # default: add all three presets
        if selected is None:
            selected = ["lcs_gateway", "ip_rnode", "rnode_lora"]

        added = []
        updated = []

        # ensure interfaces section exists
        if "interfaces" not in self.reticulum.config:
            self.reticulum.config["interfaces"] = {}
        interfaces = self.reticulum.config["interfaces"]

        enabled_value = "yes" if enable else "no"

        # LCS Gateway Client
        gateway_name = "LCS Gateway Client: public.lcs.network"
        if "lcs_gateway" in selected:
            if gateway_name not in interfaces:
                interfaces[gateway_name] = {
                    "type": "TCPClientInterface",
                    "enabled": enabled_value,
                    "mode": "gateway",
                    "target_host": "public.lcs.network",
                    "target_port": "4243",
                }
                added.append(gateway_name)
            elif interfaces[gateway_name].get("enabled") != enabled_value:
                # already present - just update the enabled status (no duplicate)
                interfaces[gateway_name]["enabled"] = enabled_value
                updated.append(gateway_name)

        # Command Center PRO Client
        # Reticulum accepts either "interface_enabled" or "enabled" (Reticulum.py
        # line 1104), and the sibling blocks here use "enabled", so the enable and
        # disable toggle below works the same way for all of them.
        command_center_name = "Command Center PRO Client"
        if "command_center" in selected:
            if command_center_name not in interfaces:
                interfaces[command_center_name] = {
                    "type": "TCPClientInterface",
                    "enabled": enabled_value,
                    "target_host": "liberty.local",
                    "target_port": "4246",
                }
                added.append(command_center_name)
            elif interfaces[command_center_name].get("enabled") != enabled_value:
                interfaces[command_center_name]["enabled"] = enabled_value
                updated.append(command_center_name)

        # LCS IP RNode TCP interface
        iprnode_name = "IP RNode"
        if "ip_rnode" in selected:
            if iprnode_name not in interfaces:
                interfaces[iprnode_name] = {
                    "type": "TCPClientInterface",
                    "enabled": enabled_value,
                    "target_host": rnode_host or "iprnode.local",
                    "target_port": rnode_port or "4545",
                }
                added.append(iprnode_name)
            elif interfaces[iprnode_name].get("enabled") != enabled_value:
                interfaces[iprnode_name]["enabled"] = enabled_value
                updated.append(iprnode_name)

        # LCS RNode LoRa (serial)
        rnode_name = "RNode LoRa Interface"
        if "rnode_lora" in selected:
            if rnode_name not in interfaces:
                lora_port = rnode_serial_port or ""
                interfaces[rnode_name] = {
                    "type": "RNodeInterface",
                    "mode": "gateway",
                    "enabled": "yes" if (enable and lora_port) else "no",
                    "port": lora_port,
                    "frequency": "914875000",
                    "bandwidth": "250000",
                    # 17 dBm, not 22: SX127x boards (LilyGo T-Beam, LoRa32 v2.1)
                    # clamp anything higher, and Reticulum then rejects the
                    # mismatch and refuses to bring the interface up at all.
                    "txpower": "17",
                    "spreadingfactor": "11",
                    "codingrate": "5",
                }
                added.append(rnode_name)
            else:
                # already present - update enabled status (and serial port if provided)
                changed = False
                if rnode_serial_port:
                    if interfaces[rnode_name].get("port") != rnode_serial_port:
                        interfaces[rnode_name]["port"] = rnode_serial_port
                        changed = True
                new_enabled = "yes" if (enable and (rnode_serial_port or interfaces[rnode_name].get("port"))) else "no"
                if interfaces[rnode_name].get("enabled") != new_enabled:
                    interfaces[rnode_name]["enabled"] = new_enabled
                    changed = True
                if changed:
                    updated.append(rnode_name)

        # write config only if something changed
        if len(added) > 0 or len(updated) > 0:
            self.reticulum.config.write()
            if added:
                RNS.log(f"Added LCS preset interface(s): {', '.join(added)}", RNS.LOG_NOTICE)
            if updated:
                RNS.log(f"Updated LCS preset interface(s): {', '.join(updated)}", RNS.LOG_NOTICE)

        return {"added": added, "updated": updated}

    # returns True when running inside a docker container
    def is_docker(self):
        # detect containerized environments robustly. /.dockerenv isn't always present
        # (depends how the image is built/run), so check several signals and allow an
        # explicit override via environment variable.
        try:
            env_flag = os.environ.get("LCS_DOCKER") or os.environ.get("RUNNING_IN_DOCKER")
            if env_flag is not None:
                return str(env_flag).strip().lower() in ("1", "true", "yes", "on")
            if os.path.exists("/.dockerenv"):
                return True
            # container runtimes leave traces in cgroup info
            for path in ("/proc/1/cgroup", "/proc/self/cgroup"):
                try:
                    with open(path, "r") as f:
                        contents = f.read()
                    if "docker" in contents or "containerd" in contents or "kubepods" in contents:
                        return True
                except Exception:
                    pass
        except Exception:
            pass
        return False

    # init telephone
    def init_telephone(self):
        self.telephone = Telephone(identity=self.identity)
        self.telephone.set_busy_tone_time(0) # disable busy tone played on caller side when remote side rejects, or doesn't answer
        self.telephone.set_ringing_callback(self.on_telephone_ringing)
        self.telephone.set_established_callback(self.on_telephone_call_established)
        self.telephone.set_ended_callback(self.on_telephone_call_ended)

        # LCS: wrap switch_mode so that ANY change of call mode - including one initiated
        # by the REMOTE party via signalling - restores the transmit path. Without this,
        # after using push-to-talk in half duplex, going back to full duplex left the
        # microphone muted, because LXST only unsquelches the packetizer and knows nothing
        # about the transmit mute the PTT button applied.
        try:
            original_switch_mode = self.telephone.switch_mode

            def switch_mode_wrapper(mode=None, from_signalling=False, *args, **kwargs):
                result = original_switch_mode(mode, from_signalling=from_signalling, *args, **kwargs)
                try:
                    self.restore_transmit_for_call_mode(mode)
                except Exception as e:
                    RNS.log(f"LCS: could not restore transmit after mode switch: {e}", RNS.LOG_DEBUG)
                return result

            self.telephone.switch_mode = switch_mode_wrapper
        except Exception as e:
            RNS.log(f"LCS: could not wrap switch_mode: {e}", RNS.LOG_WARNING)

        # LCS: in Docker there is no microphone or PulseAudio, so LXST's server-side
        # audio can't work. Install the WebSocket audio bridge so the browser provides
        # the mic and speaker instead. Desktop builds keep normal server-side audio.
        if self.is_docker():
            try:
                from src.backend.webrtc_audio_bridge import AudioBridge, install_bridge_on_telephone
                self.audio_bridge = AudioBridge()
                install_bridge_on_telephone(self.telephone, self.audio_bridge)
                RNS.log("LCS: WebSocket audio bridge installed for Docker telephone", RNS.LOG_NOTICE)
            except Exception as e:
                RNS.log(f"LCS: failed to install WebSocket audio bridge: {e}", RNS.LOG_ERROR)
                self.audio_bridge = None
        else:
            self.audio_bridge = None

    # enable telephone
    def enable_telephone(self):

        # mark as enabled in config
        self.config.telephone_enabled.set(True)

        # do nothing if already enabled
        if self.telephone is not None:
            return

        # start instance
        self.init_telephone()

    # disable telephone
    def disable_telephone(self):

        # teardown telephone instance
        if self.telephone is not None:
            AsyncUtils.run_async(asyncio.to_thread(self.telephone.teardown))

        # mark as disabled in config
        self.config.telephone_enabled.set(False)

        # clear instance
        self.telephone = None

    # handle receiving a new telephone call
    def on_telephone_ringing(self, caller_identity: RNS.Identity):
        print("on_telephone_ringing: {}".format(caller_identity.hash.hex()))
        AsyncUtils.run_async(self.websocket_broadcast(json.dumps({
            "type": "telephone_ringing",
        })))

    # handle telephone call established
    def on_telephone_call_established(self, caller_identity: RNS.Identity):
        print("on_telephone_call_established: {}".format(caller_identity.hash.hex()))
        AsyncUtils.run_async(self.websocket_broadcast(json.dumps({
            "type": "telephone_call_established",
            # tell the browser whether it must provide mic/speaker (Docker has no
            # server-side audio). authoritative from the backend, so the browser
            # doesn't depend on possibly-stale app_info.
            "use_browser_audio": self.is_docker(),
        })))

    # LCS: keep the transmit path consistent with the active call mode.
    # Full duplex = always transmitting, so the mic must be unmuted and unsquelched.
    # Half duplex = push-to-talk, so start silent until the PTT button is held.
    def restore_transmit_for_call_mode(self, call_mode=None):
        try:
            if call_mode is None:
                call_mode = getattr(self.telephone, "active_mode", None)

            active_call = self.telephone.active_call
            is_half_duplex = (call_mode == 2)

            if is_half_duplex:
                # start squelched - the PTT button opens it
                if active_call is not None and hasattr(active_call, "packetizer"):
                    active_call.packetizer.squelch()
                self.telephone.mute_transmit(True)
            else:
                # full duplex - the mic must be live again
                if active_call is not None and hasattr(active_call, "packetizer"):
                    active_call.packetizer.unsquelch()
                self.telephone.mute_transmit(False)
                RNS.log("LCS: full duplex - microphone re-enabled", RNS.LOG_DEBUG)
        except Exception as e:
            RNS.log(f"restore_transmit_for_call_mode failed: {e}", RNS.LOG_DEBUG)

    # handle telephone call ended
    def on_telephone_call_ended(self, caller_identity: RNS.Identity = None):
        if caller_identity is not None:
            print("on_telephone_ended: {}".format(caller_identity.hash.hex()))
        else:
            print("on_telephone_ended: (no identity)")
        # LCS: stop the browser audio bridge when the call ends
        if getattr(self, "audio_bridge", None) is not None:
            try:
                self.audio_bridge.deactivate()
            except Exception:
                pass

        # LCS: drop the speaker sink so the next call gets a fresh one. LXST does not
        # always clear audio_output between calls, and reusing a released sink means the
        # next call silently drops audio frames.
        if self.is_docker():
            try:
                audio_output = getattr(self.telephone, "audio_output", None)
                if audio_output is not None and getattr(audio_output, "released", False):
                    self.telephone.audio_output = None
            except Exception:
                pass
        AsyncUtils.run_async(self.websocket_broadcast(json.dumps({
            "type": "telephone_call_ended",
        })))

    # gets app version from package.json
    def get_app_version(self) -> str:
        with open(get_file_path("package.json")) as f:
            package_json = json.load(f)
            return package_json["version"]

    # LXST does not expose __version__, so read it from the installed package metadata
    def get_lxst_version(self) -> str:
        try:
            from importlib.metadata import version
            return version("lxst")
        except Exception:
            return "unknown"

    # automatically announces based on user config
    async def announce_loop(self):
        while True:

            should_announce = False

            # check if auto announce is enabled
            if self.config.auto_announce_enabled.get():

                # check if we have announced recently
                last_announced_at = self.config.last_announced_at.get()
                if last_announced_at is not None:

                    # determine when next announce should be sent
                    auto_announce_interval_seconds = self.config.auto_announce_interval_seconds.get()
                    next_announce_at = last_announced_at + auto_announce_interval_seconds

                    # we should announce if current time has passed next announce at timestamp
                    if time.time() > next_announce_at:
                        should_announce = True

                else:
                    # last announced at is null, so we have never announced, lets do it now
                    should_announce = True

            # announce
            if should_announce:
                await self.announce()

            # wait 1 second before next loop
            await asyncio.sleep(1)

    # automatically syncs propagation nodes based on user config
    async def announce_sync_propagation_nodes(self):
        while True:

            should_sync = False

            # check if auto sync is enabled
            auto_sync_interval_seconds = self.config.lxmf_preferred_propagation_node_auto_sync_interval_seconds.get()
            if auto_sync_interval_seconds > 0:

                # check if we have synced recently
                last_synced_at = self.config.lxmf_preferred_propagation_node_last_synced_at.get()
                if last_synced_at is not None:

                    # determine when next sync should happen
                    next_sync_at = last_synced_at + auto_sync_interval_seconds

                    # we should sync if current time has passed next sync at timestamp
                    if time.time() > next_sync_at:
                        should_sync = True

                else:
                    # last synced at is null, so we have never synced, lets do it now
                    should_sync = True

            # sync
            if should_sync:
                await self.sync_propagation_nodes()

            # wait 1 second before next loop
            await asyncio.sleep(1)

    # uses the provided destination hash as the active propagation node
    def set_active_propagation_node(self, destination_hash: str | None):

        # set outbound propagation node
        if destination_hash is not None and destination_hash != "":
            try:
                self.message_router.set_outbound_propagation_node(bytes.fromhex(destination_hash))
            except:
                # failed to set propagation node, clear it to ensure we don't use an old one by mistake
                self.remove_active_propagation_node()
                pass

        # stop using propagation node
        else:
            self.remove_active_propagation_node()

    # stops the in progress propagation node sync
    def stop_propagation_node_sync(self):
        self.message_router.cancel_propagation_node_requests()

    # stops and removes the active propagation node
    def remove_active_propagation_node(self):
        # fixme: it's possible for internal transfer state to get stuck if we change propagation node during a sync
        # this still happens even if we cancel the propagation node requests
        # for now, the user can just manually cancel syncing in the ui if they think it's stuck...
        self.stop_propagation_node_sync()
        self.message_router.outbound_propagation_node = None

    # enables or disables the local lxmf propagation node
    def enable_local_propagation_node(self, enabled: bool = True):
        try:
            if enabled:
                self.message_router.enable_propagation()
            else:
                self.message_router.disable_propagation()
        except:
            print("failed to enable or disable propagation node")
            pass

    # handle receiving a new audio call
    def on_incoming_audio_call(self, audio_call: AudioCall):
        print("on_incoming_audio_call: {}".format(audio_call.link.hash.hex()))
        AsyncUtils.run_async(self.websocket_broadcast(json.dumps({
            "type": "incoming_audio_call",
        })))

    # web server has shutdown, likely ctrl+c, but if we don't do the following, the script never exits
    async def shutdown(self, app):

        # force close websocket clients
        for websocket_client in self.websocket_clients:
            await websocket_client.close(code=WSCloseCode.GOING_AWAY)

        # stop reticulum
        RNS.Transport.detach_interfaces()
        self.reticulum.exit_handler()
        RNS.exit()

    def run(self, host, port, launch_browser: bool, rns_bridge_options: dict = None):

        # create route table
        routes = web.RouteTableDef()

        # serve index.html
        @routes.get("/")
        async def index(request):
            return web.FileResponse(path=get_file_path("public/index.html"), headers={
                # don't allow browser to store page in cache, otherwise new app versions may get stale ui
                "Cache-Control": "no-cache, no-store",
            })

        # serve ping
        @routes.get("/api/v1/status")
        async def index(request):
            return web.json_response({
                "status": "ok",
            })

        # enable telephone
        @routes.get("/api/v1/telephone/enable")
        async def index(request):
            self.enable_telephone()
            return web.json_response({
                "message": "Telephone has been enabled.",
            })

        # disable telephone
        @routes.get("/api/v1/telephone/disable")
        async def index(request):
            self.disable_telephone()
            return web.json_response({
                "message": "Telephone has been disabled.",
            })

        # serve telephone status
        @routes.get("/api/v1/telephone/status")
        async def index(request):

            # make sure telephone is enabled
            if self.telephone is None:
                return web.json_response({
                    "enabled": False,
                    "message": "Telephone is disabled",
                })

            # get active call info
            active_call = None
            telephone_active_call = self.telephone.active_call
            if telephone_active_call is not None:

                # get remote identity hash
                remote_identity_hash = None
                remote_identity_name = None
                remote_identity = telephone_active_call.get_remote_identity()
                if remote_identity is not None:
                    remote_identity_hash = remote_identity.hash.hex()
                    remote_identity_name = self.get_name_for_identity_hash(remote_identity_hash)

                active_call = {
                    "hash": telephone_active_call.hash.hex(),
                    "status": self.telephone.call_status,
                    "is_incoming": telephone_active_call.is_incoming,
                    "is_outgoing": telephone_active_call.is_outgoing,
                    "remote_identity_hash": remote_identity_hash,
                    "remote_identity_name": remote_identity_name,
                    "audio_profile_id": self.telephone.active_profile,
                    "call_mode": getattr(self.telephone, "active_mode", None),
                    "is_receive_muted": self.telephone.receive_muted,
                    "is_transmit_muted": self.telephone.transmit_muted,
                    "tx_packets": telephone_active_call.tx,
                    "rx_packets": telephone_active_call.rx,
                    "tx_bytes": telephone_active_call.txbytes,
                    "rx_bytes": telephone_active_call.rxbytes,
                }

            return web.json_response({
                "enabled": True,
                "is_busy": self.telephone.busy,
                "call_status": self.telephone.call_status,
                "active_call": active_call,
            })

        # answer incoming telephone call
        @routes.get("/api/v1/telephone/answer")
        async def index(request):

            # get incoming caller identity
            caller_identity = self.telephone.active_call.get_remote_identity()

            # answer call
            AsyncUtils.run_async(asyncio.to_thread(self.telephone.answer, caller_identity))

            return web.json_response({
                "message": "Answering call...",
            })

        # hangup active telephone call
        @routes.get("/api/v1/telephone/hangup")
        async def index(request):
            AsyncUtils.run_async(asyncio.to_thread(self.telephone.hangup))
            return web.json_response({
                "message": "Hanging up call...",
            })

        # LCS: browser <-> server audio bridge websocket (Docker builds only).
        # the browser sends microphone PCM frames (binary) and receives call audio
        # (binary) to play back. only meaningful when the audio bridge is installed.
        @routes.get("/api/v1/telephone/audio-bridge")
        async def index(request):
            websocket_response = web.WebSocketResponse()
            await websocket_response.prepare(request)

            bridge = getattr(self, "audio_bridge", None)
            if bridge is None:
                await websocket_response.close(code=WSCloseCode.POLICY_VIOLATION,
                                               message=b"audio bridge not available")
                return websocket_response

            bridge.activate()

            # tell the browser the mic frame size once, up front (matches the mixer target
            # so Opus AND Codec2 frame durations line up). best-effort - must never break
            # the audio stream.
            try:
                initial_target = getattr(bridge, "target_frame_samples", None)
                if initial_target:
                    await websocket_response.send_json({
                        "type": "frame_config",
                        "frame_samples": initial_target,
                    })
            except Exception as e:
                RNS.log(f"audio-bridge: could not send initial frame_config: {e}", RNS.LOG_DEBUG)

            # task: push speaker frames (call audio) down to the browser
            async def pump_speaker():
                last_target_sent = getattr(bridge, "target_frame_samples", None)
                try:
                    while not websocket_response.closed:
                        # if the target changes mid-session (profile switch), notify browser
                        target = getattr(bridge, "target_frame_samples", None)
                        if target is not None and target != last_target_sent:
                            try:
                                await websocket_response.send_json({
                                    "type": "frame_config",
                                    "frame_samples": target,
                                })
                            except Exception:
                                pass
                            last_target_sent = target
                        frames = bridge.drain_speaker_frames(max_frames=10)
                        if len(frames) == 0:
                            await asyncio.sleep(0.01)
                            continue
                        for frame in frames:
                            if websocket_response.closed:
                                break
                            # frame may be bytes or a buffer-like object
                            try:
                                await websocket_response.send_bytes(bytes(frame))
                            except Exception:
                                pass
                except Exception as e:
                    RNS.log(f"audio-bridge speaker pump ended: {e}", RNS.LOG_DEBUG)

            speaker_task = asyncio.ensure_future(pump_speaker())

            try:
                async for msg in websocket_response:
                    if msg.type == WSMsgType.BINARY:
                        # microphone frame from the browser -> LXST transmit pipeline
                        bridge.push_mic_frame(msg.data)
                    elif msg.type == WSMsgType.ERROR:
                        break
            except Exception as e:
                RNS.log(f"audio-bridge websocket error: {e}", RNS.LOG_DEBUG)
            finally:
                speaker_task.cancel()

            return websocket_response

        # switch outbound audio profile
        @routes.get("/api/v1/telephone/switch-audio-profile/{audio_profile_id}")
        async def index(request):
            audio_profile_id = int(request.match_info.get("audio_profile_id"))
            AsyncUtils.run_async(asyncio.to_thread(self.telephone.switch_profile, audio_profile_id))
            return web.json_response({
                "message": "ok",
            })

        # LCS: switch between full duplex and half duplex (push-to-talk) call modes.
        # LXST 0.5.1+ signals the mode to the other party, so both ends stay in sync.
        @routes.get("/api/v1/telephone/switch-call-mode/{call_mode}")
        async def index(request):
            call_mode = int(request.match_info.get("call_mode"))
            # switch_mode is wrapped in init_telephone() so the transmit path (mute +
            # squelch) is restored for the new mode, whichever side initiated the change.
            AsyncUtils.run_async(asyncio.to_thread(self.telephone.switch_mode, call_mode))
            return web.json_response({
                "message": "ok",
            })

        # LCS: push-to-talk. In half duplex the packetizer is squelched (not transmitting);
        # holding the PTT button unsquelches it so audio is sent, releasing re-squelches.
        @routes.get("/api/v1/telephone/push-to-talk/{transmitting}")
        async def index(request):
            transmitting = request.match_info.get("transmitting") == "true"

            def set_ptt():
                try:
                    active_call = self.telephone.active_call
                    if active_call is not None and hasattr(active_call, "packetizer"):
                        if transmitting:
                            active_call.packetizer.unsquelch()
                        else:
                            active_call.packetizer.squelch()
                    # also lift/apply the transmit mute so the mixer follows the button
                    self.telephone.mute_transmit(not transmitting)
                except Exception as e:
                    RNS.log(f"push-to-talk failed: {e}", RNS.LOG_DEBUG)

            AsyncUtils.run_async(asyncio.to_thread(set_ptt))
            return web.json_response({
                "message": "ok",
            })

        # mute received audio
        @routes.get("/api/v1/telephone/mute-receive")
        async def index(request):
            AsyncUtils.run_async(asyncio.to_thread(self.telephone.mute_receive, True))
            return web.json_response({
                "message": "ok",
            })

        # unmute received audio
        @routes.get("/api/v1/telephone/unmute-receive")
        async def index(request):
            AsyncUtils.run_async(asyncio.to_thread(self.telephone.mute_receive, False))
            return web.json_response({
                "message": "ok",
            })

        # mute transmit audio
        @routes.get("/api/v1/telephone/mute-transmit")
        async def index(request):
            AsyncUtils.run_async(asyncio.to_thread(self.telephone.mute_transmit, True))
            return web.json_response({
                "message": "ok",
            })

        # unmute transmit audio
        @routes.get("/api/v1/telephone/unmute-transmit")
        async def index(request):
            AsyncUtils.run_async(asyncio.to_thread(self.telephone.mute_transmit, False))
            return web.json_response({
                "message": "ok",
            })

        # initiate a telephone call
        @routes.get("/api/v1/telephone/call/{identity_hash}")
        async def index(request):

            # make sure telephone enabled
            if self.telephone is None:
                return web.json_response({
                    "message": "Telephone has been disabled.",
                }, status=503)

            # get path params
            identity_hash_hex = request.match_info.get("identity_hash", "")
            timeout_seconds = int(request.query.get("timeout", 15))
            input_device_name = request.query.get("input_device_name", None)
            output_device_name = request.query.get("output_device_name", None)
            audio_profile_id = int(request.query.get("audio_profile_id", None))

            # convert hash to bytes
            identity_hash = bytes.fromhex(identity_hash_hex)

            # find destination identity
            destination_identity = RNS.Identity.recall(identity_hash, from_identity_hash=True)
            if destination_identity is None:
                # couldn't find as identity hash, try finding as destination hash
                destination_identity = RNS.Identity.recall(identity_hash, from_identity_hash=False)

            # ensure identity was found
            if destination_identity is None:
                return web.json_response({
                    "message": "Call Failed: Destination identity not found.",
                }, status=503)

            # create telephony destination, only used to determine if we have a path
            telephony_destination = RNS.Destination(
                destination_identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                LXST.APP_NAME,
                LXST.Primitives.Telephony.PRIMITIVE_NAME
            )
            telephony_destination_hash = telephony_destination.hash

            # determine when to timeout
            timeout_after_seconds = time.time() + timeout_seconds

            # check if we have a path to the destination
            if not RNS.Transport.has_path(telephony_destination_hash):

                # we don't have a path, so we need to request it
                RNS.Transport.request_path(telephony_destination_hash)

                # wait until we have a path, or give up after the configured timeout
                while not RNS.Transport.has_path(telephony_destination_hash) and time.time() < timeout_after_seconds:
                    await asyncio.sleep(0.1)

            # if we still don't have a path, call will fail, so bail out
            if not RNS.Transport.has_path(telephony_destination_hash):
                return web.json_response({
                    "message": "Call Failed: Could not find path to destination.",
                }, status=503)

            # set audio devices
            self.telephone.set_microphone(input_device_name)
            self.telephone.set_speaker(output_device_name)

            # initiate call
            AsyncUtils.run_async(asyncio.to_thread(self.telephone.call, destination_identity, audio_profile_id))

            return web.json_response({
                "message": "Calling...",
            })

        # serve list of available input/output devices
        @routes.get("/api/v1/telephone/audio-devices")
        async def index(request):

            # LCS: in Docker there is no server-side audio hardware (PulseAudio),
            # so device enumeration throws. return empty lists instead of a 500 -
            # the browser audio bridge provides the mic/speaker in that case.
            try:
                # get default input device
                default_input_device = self.telephone.default_input()
                if default_input_device is not None:
                    default_input_device = default_input_device.name

                # get default output device
                default_output_device = self.telephone.default_output()
                if default_output_device is not None:
                    default_output_device = default_output_device.name

                # get input devices
                input_devices = []
                for input_device in self.telephone.available_inputs():
                    input_devices.append(input_device.name)

                # get output devices
                output_devices = []
                for output_device in self.telephone.available_outputs():
                    output_devices.append(output_device.name)
            except Exception as e:
                RNS.log(f"audio-devices unavailable (expected in Docker): {e}", RNS.LOG_DEBUG)
                return web.json_response({
                    "default_input_device": None,
                    "default_output_device": None,
                    "input_devices": [],
                    "output_devices": [],
                    "browser_audio": self.is_docker(),
                })

            return web.json_response({
                "default_input_device": default_input_device,
                "default_output_device": default_output_device,
                "input_devices": input_devices,
                "output_devices": output_devices,
            })

        # serve list of available audio profiles
        @routes.get("/api/v1/telephone/audio-profiles")
        async def index(request):

            # get audio profiles
            audio_profiles = []
            for available_profile in Profiles.available_profiles():
                audio_profiles.append({
                    "id": available_profile,
                    "name": Profiles.profile_name(available_profile)
                })

            # LCS: available call modes (Full Duplex / Half Duplex PTT). Guarded so the
            # app still works if running against an LXST without duplex mode support.
            call_modes = []
            try:
                for available_mode in Profiles.available_modes():
                    call_modes.append({
                        "id": available_mode,
                        "name": Profiles.mode_name(available_mode),
                        "abbreviation": Profiles.mode_abbrevation(available_mode),
                    })
            except Exception:
                call_modes = []

            return web.json_response({
                "default_audio_profile_id": Profiles.DEFAULT_PROFILE,
                "audio_profiles": audio_profiles,
                # LCS: available call modes (LXST 0.5.1+): Full Duplex / Half Duplex (PTT)
                "default_call_mode": getattr(Profiles, "DEFAULT_MODE", None),
                "call_modes": call_modes,
            })

        # fetch com ports
        @routes.get("/api/v1/comports")
        async def index(request):

            comports = []
            for comport in list_ports.comports():
                comports.append({
                    "device": comport.device,
                    "product": comport.product,
                    "serial_number": comport.serial_number,
                })

            return web.json_response({
                "comports": comports,
            })

        # fetch reticulum interfaces
        @routes.get("/api/v1/reticulum/interfaces")
        async def index(request):

            interfaces = {}
            if "interfaces" in self.reticulum.config:
                interfaces = self.reticulum.config["interfaces"]

            processed_interfaces = {}
            for interface_name, interface in interfaces.items():
                interface_data = interface.copy()

                # handle sub-interfaces for RNodeMultiInterface
                if interface_data.get("type") == "RNodeMultiInterface":
                    sub_interfaces = []
                    for sub_name, sub_config in interface_data.items():
                        if sub_name not in {"type", "port", "interface_enabled", "selected_interface_mode", "configured_bitrate"}:
                            if isinstance(sub_config, dict):
                                sub_config["name"] = sub_name
                                sub_interfaces.append(sub_config)

                    # add sub-interfaces to the main interface data
                    interface_data["sub_interfaces"] = sub_interfaces

                    for sub in sub_interfaces:
                        del interface_data[sub["name"]]

                processed_interfaces[interface_name] = interface_data

            return web.json_response({
                "interfaces": processed_interfaces,
            })

        # enable reticulum interface
        @routes.post("/api/v1/reticulum/interfaces/enable")
        async def index(request):

            # get request data
            data = await request.json()
            interface_name = data.get('name')

            # enable interface
            if "interfaces" in self.reticulum.config:
                interface = self.reticulum.config["interfaces"][interface_name]
                if "enabled" in interface:
                    interface["enabled"] = "true"
                if "interface_enabled" in interface:
                    interface["interface_enabled"] = "true"

            # save config
            self.reticulum.config.write()

            return web.json_response({
                "message": "Interface is now enabled",
            })

        # disable reticulum interface
        @routes.post("/api/v1/reticulum/interfaces/disable")
        async def index(request):

            # get request data
            data = await request.json()
            interface_name = data.get('name')

            # disable interface
            if "interfaces" in self.reticulum.config:
                interface = self.reticulum.config["interfaces"][interface_name]
                if "enabled" in interface:
                    interface["enabled"] = "false"
                if "interface_enabled" in interface:
                    interface["interface_enabled"] = "false"

            # save config
            self.reticulum.config.write()

            return web.json_response({
                "message": "Interface is now disabled",
            })

        # restart the app (docker builds). exits the process so docker's
        # "restart: unless-stopped" policy brings the container back up. this avoids
        # mounting the docker socket into the container, which would be a security risk.
        @routes.post("/api/v1/app/restart")
        async def index(request):
            # only meaningful inside docker (where the restart policy relaunches us)
            if not os.path.exists("/.dockerenv"):
                return web.json_response({
                    "message": "Restart is only available in the Docker build.",
                }, status=400)

            async def do_exit():
                await asyncio.sleep(1)
                # hard-exit; docker restart policy will relaunch the container
                os._exit(0)

            asyncio.ensure_future(do_exit())
            return web.json_response({
                "message": "Restarting MeshChat... the app will be back in a few seconds.",
            })

        # add LCS preset interfaces (selection + options come from the dialog)
        @routes.post("/api/v1/reticulum/interfaces/add-lcs-presets")
        async def index(request):
            try:
                # accept an optional json body from the dialog; fall back to defaults
                try:
                    data = await request.json()
                except Exception:
                    data = {}
                selected = data.get("selected")  # e.g. ["lcs_gateway","ip_rnode"]
                enable = data.get("enable", True)
                rnode_host = data.get("rnode_host")
                rnode_port = data.get("rnode_port")
                rnode_serial_port = data.get("rnode_serial_port")

                result = self.add_lcs_preset_interfaces(
                    selected=selected,
                    enable=enable,
                    rnode_host=rnode_host,
                    rnode_port=rnode_port,
                    rnode_serial_port=rnode_serial_port,
                )
                added = result.get("added", [])
                updated = result.get("updated", [])

                if len(added) == 0 and len(updated) == 0:
                    return web.json_response({
                        "message": "No changes - those LCS interface(s) are already set the way you selected.",
                        "added": [],
                        "updated": [],
                    })

                parts = []
                if added:
                    parts.append("Added: " + ", ".join(added))
                if updated:
                    parts.append("Updated: " + ", ".join(updated))
                return web.json_response({
                    "message": ". ".join(parts) + ". Please restart MeshChat for the changes to take effect.",
                    "added": added,
                    "updated": updated,
                })
            except Exception as e:
                return web.json_response({
                    "message": f"Failed to add LCS preset interfaces: {e}",
                }, status=500)

        # list available serial ports (for the RNode port-finder in the dialog)
        @routes.get("/api/v1/reticulum/serial-ports")
        async def index(request):
            ports = []
            try:
                # pyserial ships with pyserial; list_ports enumerates real devices
                from serial.tools import list_ports
                for p in list_ports.comports():
                    ports.append({
                        "device": p.device,
                        "description": p.description or "",
                        "hwid": p.hwid or "",
                    })
            except Exception as e:
                return web.json_response({
                    "ports": [],
                    "message": f"Could not enumerate serial ports: {e}",
                })
            return web.json_response({"ports": ports})

        # delete reticulum interface
        @routes.post("/api/v1/reticulum/interfaces/delete")
        async def index(request):

            # get request data
            data = await request.json()
            interface_name = data.get('name')

            # delete interface
            if "interfaces" in self.reticulum.config:
                del self.reticulum.config["interfaces"][interface_name]

            # save config
            self.reticulum.config.write()

            return web.json_response({
                "message": "Interface has been deleted",
            })

        # add reticulum interface
        @routes.post("/api/v1/reticulum/interfaces/add")
        async def index(request):

            # get request data
            data = await request.json()
            interface_name = data.get('name')
            interface_type = data.get('type')
            allow_overwriting_interface = data.get('allow_overwriting_interface', False)

            # ensure name is provided
            if interface_name is None or interface_name == "":
                return web.json_response({
                    "message": "Name is required",
                }, status=422)

            # ensure type name provided
            if interface_type is None or interface_type == "":
                return web.json_response({
                    "message": "Type is required",
                }, status=422)

            # get existing interfaces
            interfaces = {}
            if "interfaces" in self.reticulum.config:
                interfaces = self.reticulum.config["interfaces"]

            # ensure name is not for an existing interface, to prevent overwriting
            if allow_overwriting_interface is False and interface_name in interfaces:
                return web.json_response({
                    "message": "Name is already in use by another interface",
                }, status=422)

            # get existing interface details if available
            interface_details = {}
            if interface_name in interfaces:
                interface_details = interfaces[interface_name]

            # update interface details
            interface_details["type"] = interface_type

            # if interface doesn't have enabled or interface_enabled setting already, enable it by default
            if "enabled" not in interface_details and "interface_enabled" not in interface_details:
                interface_details["interface_enabled"] = "true"

            # handle AutoInterface
            if interface_type == "AutoInterface":

                # set optional AutoInterface options
                InterfaceEditor.update_value(interface_details, data, "group_id")
                InterfaceEditor.update_value(interface_details, data, "multicast_address_type")
                InterfaceEditor.update_value(interface_details, data, "devices")
                InterfaceEditor.update_value(interface_details, data, "ignored_devices")
                InterfaceEditor.update_value(interface_details, data, "discovery_scope")
                InterfaceEditor.update_value(interface_details, data, "discovery_port")
                InterfaceEditor.update_value(interface_details, data, "data_port")

            # handle TCPClientInterface
            if interface_type == "TCPClientInterface":

                # ensure target host provided
                interface_target_host = data.get('target_host')
                if interface_target_host is None or interface_target_host == "":
                    return web.json_response({
                        "message": "Target Host is required",
                    }, status=422)

                # ensure target port provided
                interface_target_port = data.get('target_port')
                if interface_target_port is None or interface_target_port == "":
                    return web.json_response({
                        "message": "Target Port is required",
                    }, status=422)

                # set required TCPClientInterface options
                interface_details["target_host"] = interface_target_host
                interface_details["target_port"] = interface_target_port

                # set optional TCPClientInterface options
                InterfaceEditor.update_value(interface_details, data, "kiss_framing")
                InterfaceEditor.update_value(interface_details, data, "i2p_tunneled")

            # handle I2P interface
            if interface_type == "I2PInterface":
                interface_details['connectable'] = "True"
                interface_details["peers"] = data.get('peers')

            # handle tcp server interface
            if interface_type == "TCPServerInterface":

                # ensure listen ip provided
                interface_listen_ip = data.get('listen_ip')
                if interface_listen_ip is None or interface_listen_ip == "":
                    return web.json_response({
                        "message": "Listen IP is required",
                    }, status=422)

                # ensure listen port provided
                interface_listen_port = data.get('listen_port')
                if interface_listen_port is None or interface_listen_port == "":
                    return web.json_response({
                        "message": "Listen Port is required",
                    }, status=422)

                # set required TCPServerInterface options
                interface_details["listen_ip"] = interface_listen_ip
                interface_details["listen_port"] = interface_listen_port

                # set optional TCPServerInterface options
                InterfaceEditor.update_value(interface_details, data, "device")
                InterfaceEditor.update_value(interface_details, data, "prefer_ipv6")

            # handle udp interface
            if interface_type == "UDPInterface":

                # ensure listen ip provided
                interface_listen_ip = data.get('listen_ip')
                if interface_listen_ip is None or interface_listen_ip == "":
                    return web.json_response({
                        "message": "Listen IP is required",
                    }, status=422)

                # ensure listen port provided
                interface_listen_port = data.get('listen_port')
                if interface_listen_port is None or interface_listen_port == "":
                    return web.json_response({
                        "message": "Listen Port is required",
                    }, status=422)

                # ensure forward ip provided
                interface_forward_ip = data.get('forward_ip')
                if interface_forward_ip is None or interface_forward_ip == "":
                    return web.json_response({
                        "message": "Forward IP is required",
                    }, status=422)

                # ensure forward port provided
                interface_forward_port = data.get('forward_port')
                if interface_forward_port is None or interface_forward_port == "":
                    return web.json_response({
                        "message": "Forward Port is required",
                    }, status=422)

                # set required UDPInterface options
                interface_details["listen_ip"] = interface_listen_ip
                interface_details["listen_port"] = interface_listen_port
                interface_details["forward_ip"] = interface_forward_ip
                interface_details["forward_port"] = interface_forward_port

                # set optional UDPInterface options
                InterfaceEditor.update_value(interface_details, data, "device")

            # handle RNodeInterface
            if interface_type == "RNodeInterface":

                # ensure port provided
                interface_port = data.get('port')
                if interface_port is None or interface_port == "":
                    return web.json_response({
                        "message": "Port is required",
                    }, status=422)

                # ensure frequency provided
                interface_frequency = data.get('frequency')
                if interface_frequency is None or interface_frequency == "":
                    return web.json_response({
                        "message": "Frequency is required",
                    }, status=422)

                # ensure bandwidth provided
                interface_bandwidth = data.get('bandwidth')
                if interface_bandwidth is None or interface_bandwidth == "":
                    return web.json_response({
                        "message": "Bandwidth is required",
                    }, status=422)

                # ensure txpower provided
                interface_txpower = data.get('txpower')
                if interface_txpower is None or interface_txpower == "":
                    return web.json_response({
                        "message": "TX power is required",
                    }, status=422)

                # ensure spreading factor provided
                interface_spreadingfactor = data.get('spreadingfactor')
                if interface_spreadingfactor is None or interface_spreadingfactor == "":
                    return web.json_response({
                        "message": "Spreading Factor is required",
                    }, status=422)

                # ensure coding rate provided
                interface_codingrate = data.get('codingrate')
                if interface_codingrate is None or interface_codingrate == "":
                    return web.json_response({
                        "message": "Coding Rate is required",
                    }, status=422)

                # set required RNodeInterface options
                interface_details["port"] = interface_port
                interface_details["frequency"] = interface_frequency
                interface_details["bandwidth"] = interface_bandwidth
                interface_details["txpower"] = interface_txpower
                interface_details["spreadingfactor"] = interface_spreadingfactor
                interface_details["codingrate"] = interface_codingrate

                # set optional RNodeInterface options
                InterfaceEditor.update_value(interface_details, data, "callsign")
                InterfaceEditor.update_value(interface_details, data, "id_interval")
                InterfaceEditor.update_value(interface_details, data, "airtime_limit_long")
                InterfaceEditor.update_value(interface_details, data, "airtime_limit_short")

            # handle RNodeMultiInterface
            if interface_type == "RNodeMultiInterface":

                # required settings
                interface_port = data.get("port")
                sub_interfaces = data.get("sub_interfaces", [])

                # ensure port provided
                if interface_port is None or interface_port == "":
                    return web.json_response({
                        "message": "Port is required",
                    }, status=422)

                # ensure sub interfaces provided
                if not isinstance(sub_interfaces, list) or not sub_interfaces:
                    return web.json_response({
                        "message": "At least one sub-interface is required",
                    }, status=422)

                # set required RNodeMultiInterface options
                interface_details["port"] = interface_port

                # remove any existing sub interfaces, which can be found by finding keys that contain a dict value
                # this allows us to replace all sub interfaces with the ones we are about to add, while also ensuring
                # that we do not remove any existing config values from the main interface config
                for key in interface_details:
                    value = interface_details[key]
                    if isinstance(value, dict):
                        del interface_details[key]

                # process each provided sub interface
                for idx, sub_interface in enumerate(sub_interfaces):

                    # ensure required fields for sub-interface provided
                    missing_fields = []
                    required_subinterface_fields = ["name", "frequency", "bandwidth", "txpower", "spreadingfactor", "codingrate", "vport"]
                    for field in required_subinterface_fields:
                        if field not in sub_interface or sub_interface.get(field) is None or sub_interface.get(field) == "":
                            missing_fields.append(field)
                    if missing_fields:
                        return web.json_response({
                            "message": f"Sub-interface {idx + 1} is missing required field(s): {', '.join(missing_fields)}"
                        }, status=422)

                    sub_interface_name = sub_interface.get("name")
                    interface_details[sub_interface_name] = {
                        "interface_enabled": "true",
                        "frequency": int(sub_interface["frequency"]),
                        "bandwidth": int(sub_interface["bandwidth"]),
                        "txpower": int(sub_interface["txpower"]),
                        "spreadingfactor": int(sub_interface["spreadingfactor"]),
                        "codingrate": int(sub_interface["codingrate"]),
                        "vport": int(sub_interface["vport"]),
                    }

                interfaces[interface_name] = interface_details

            # handle SerialInterface, KISSInterface, and AX25KISSInterface
            if interface_type == "SerialInterface" or interface_type == "KISSInterface" or interface_type == "AX25KISSInterface":

                # ensure port provided
                interface_port = data.get('port')
                if interface_port is None or interface_port == "":
                    return web.json_response({
                        "message": "Port is required",
                    }, status=422)

                # set required options
                interface_details["port"] = interface_port

                # set optional options
                InterfaceEditor.update_value(interface_details, data, "speed")
                InterfaceEditor.update_value(interface_details, data, "databits")
                InterfaceEditor.update_value(interface_details, data, "parity")
                InterfaceEditor.update_value(interface_details, data, "stopbits")

                # Handle KISS and AX25KISS specific options
                if interface_type == "KISSInterface" or interface_type == "AX25KISSInterface":

                    # set optional options
                    InterfaceEditor.update_value(interface_details, data, "preamble")
                    InterfaceEditor.update_value(interface_details, data, "txtail")
                    InterfaceEditor.update_value(interface_details, data, "persistence")
                    InterfaceEditor.update_value(interface_details, data, "slottime")
                    InterfaceEditor.update_value(interface_details, data, "callsign")
                    InterfaceEditor.update_value(interface_details, data, "ssid")

            # FIXME: move to own sections
            # RNode Airtime limits and station ID
            InterfaceEditor.update_value(interface_details, data, "callsign")
            InterfaceEditor.update_value(interface_details, data, "id_interval")
            InterfaceEditor.update_value(interface_details, data, "airtime_limit_long")
            InterfaceEditor.update_value(interface_details, data, "airtime_limit_short")

            # handle Pipe Interface
            if interface_type == "PipeInterface":

                # ensure command provided
                interface_command = data.get('command')
                if interface_command is None or interface_command == "":
                    return web.json_response({
                        "message": "Command is required",
                    }, status=422)

                # ensure command provided
                interface_respawn_delay = data.get('respawn_delay')
                if interface_respawn_delay is None or interface_respawn_delay == "":
                    return web.json_response({
                        "message": "Respawn delay is required",
                    }, status=422)

                # set required options
                interface_details["command"] = interface_command
                interface_details["respawn_delay"] = interface_respawn_delay

            # set common interface options
            InterfaceEditor.update_value(interface_details, data, "bitrate")
            InterfaceEditor.update_value(interface_details, data, "mode")
            InterfaceEditor.update_value(interface_details, data, "network_name")
            InterfaceEditor.update_value(interface_details, data, "passphrase")
            InterfaceEditor.update_value(interface_details, data, "ifac_size")

            # merge new interface into existing interfaces
            interfaces[interface_name] = interface_details
            self.reticulum.config["interfaces"] = interfaces

            # save config
            self.reticulum.config.write()

            if allow_overwriting_interface:
                return web.json_response({
                    "message": "Interface has been saved. Please restart MeshChat for these changes to take effect.",
                })
            else:
                return web.json_response({
                    "message": "Interface has been added. Please restart MeshChat for these changes to take effect.",
                })
        
        # export interfaces
        @routes.post("/api/v1/reticulum/interfaces/export")
        async def export_interfaces(request):
            try:

                # get request data
                selected_interface_names = None
                try:
                    data = await request.json()
                    selected_interface_names = data.get('selected_interface_names')
                except:
                    # request data was not json, but we don't care
                    pass

                # format interfaces for export
                output = []
                for interface_name, interface in self.reticulum.config["interfaces"].items():

                    # skip interface if not selected
                    if selected_interface_names is not None and selected_interface_names != "":
                        if interface_name not in selected_interface_names:
                            continue

                    # add interface to output
                    output.append(f"[[{interface_name}]]")
                    for key, value in interface.items():
                        if not isinstance(value, dict):
                            output.append(f"    {key} = {value}")
                    output.append("")

                    # Handle sub-interfaces for RNodeMultiInterface
                    if interface.get("type") == "RNodeMultiInterface":
                        for sub_name, sub_config in interface.items():
                            if sub_name in {"type", "port", "interface_enabled"}:
                                continue
                            if isinstance(sub_config, dict):
                                output.append(f"  [[[{sub_name}]]]")
                                for sub_key, sub_value in sub_config.items():
                                    output.append(f"      {sub_key} = {sub_value}")
                                output.append("")


                return web.Response(
                    text="\n".join(output),
                    content_type="text/plain",
                    headers={
                        "Content-Disposition": "attachment; filename=meshchat_interfaces"
                    }
                )

            except Exception as e:
                return web.json_response({
                    "message": f"Failed to export interfaces: {str(e)}"
                }, status=500)

        # preview importable interfaces
        @routes.post("/api/v1/reticulum/interfaces/import-preview")
        async def import_interfaces_preview(request):
            try:

                # get request data
                data = await request.json()
                config = data.get('config')

                # parse interfaces from config
                interfaces = InterfaceConfigParser.parse(config)
                    
                return web.json_response({
                    "interfaces": interfaces
                })
                
            except Exception as e:
                return web.json_response({
                    "message": f"Failed to parse config file: {str(e)}"
                }, status=500)

        # import interfaces from config
        @routes.post("/api/v1/reticulum/interfaces/import")
        async def import_interfaces(request):
            try:

                # get request data
                data = await request.json()
                config = data.get('config')
                selected_interface_names = data.get('selected_interface_names')

                # parse interfaces from config
                interfaces = InterfaceConfigParser.parse(config)

                # find selected interfaces
                selected_interfaces = []
                for interface in interfaces:
                    if interface["name"] in selected_interface_names:
                        selected_interfaces.append(interface)

                # convert interfaces to object
                interface_config = {}
                for interface in selected_interfaces:

                    # add interface and keys/values
                    interface_name = interface["name"]
                    interface_config[interface_name] = {}
                    for key, value in interface.items():
                        interface_config[interface_name][key] = value

                    # unset name which isn't part of the config
                    del interface_config[interface_name]["name"]

                    # force imported interface to be enabled by default
                    interface_config[interface_name]["interface_enabled"] = "true"

                    # remove enabled config value in favour of interface_enabled
                    if "enabled" in interface_config[interface_name]:
                        del interface_config[interface_name]["enabled"]

                # update reticulum config with new interfaces
                self.reticulum.config["interfaces"].update(interface_config)
                self.reticulum.config.write()

                return web.json_response({
                    "message": "Interfaces imported successfully",
                })
                
            except Exception as e:
                return web.json_response({
                    "message": f"Failed to import interfaces: {str(e)}"
                }, status=500)

        # handle websocket clients
        @routes.get("/ws")
        async def ws(request):

            # prepare websocket response
            websocket_response = web.WebSocketResponse(
                # set max message size accepted by server to 50 megabytes
                max_msg_size=50 * 1024 * 1024,
            )
            await websocket_response.prepare(request)

            # add client to connected clients list
            self.websocket_clients.append(websocket_response)

            # send config to all clients
            await self.send_config_to_websocket_clients()

            # handle websocket messages until disconnected
            async for msg in websocket_response:
                msg: WSMessage = msg
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self.on_websocket_data_received(websocket_response, data)
                    except Exception as e:
                        # ignore errors while handling message
                        print("failed to process client message")
                        print(e)
                elif msg.type == WSMsgType.ERROR:
                    # ignore errors while handling message
                    print('ws connection error %s' % websocket_response.exception())

            # websocket closed
            self.websocket_clients.remove(websocket_response)

            return websocket_response

        # get app info
        @routes.get("/api/v1/app/info")
        async def index(request):
            return web.json_response({
                "app_info": {
                    "version": self.get_app_version(),
                    "lxmf_version": LXMF.__version__,
                    "rns_version": RNS.__version__,
                    "lxst_version": self.get_lxst_version(),
                    "python_version": platform.python_version(),
                    "storage_path": self.storage_path,
                    "database_path": self.database_path,
                    "database_file_size": os.path.getsize(self.database_path),
                    "reticulum_config_path": self.reticulum.configpath,
                    "is_connected_to_shared_instance": self.reticulum.is_connected_to_shared_instance,
                    "is_transport_enabled": self.reticulum.transport_enabled(),
                    "is_docker": self.is_docker(),
                },
            })

        # get config
        @routes.get("/api/v1/config")
        async def index(request):
            return web.json_response({
                "config": self.get_config_dict(),
            })

        # LCS: replace the Reticulum identity with a freshly generated one.
        #
        # The LXMF address is derived from the same identity (it is registered on
        # it by message_router.register_delivery_identity), so regenerating the
        # Reticulum identity regenerates the LXMF address with it. There is no
        # separate LXMF key to clear.
        #
        # Nothing is deleted. The previous identity is kept alongside the new one
        # as identity.replaced-<timestamp>, and because per-identity data lives in
        # <storage_dir>/identities/<identity_hash>/, the old database stays exactly
        # where it is under the old hash. Restoring the saved file and restarting
        # puts everything back.
        #
        # The running RNS instance, the LXMF router and every destination were all
        # built from the old identity at startup, so this takes effect on restart
        # rather than live. Rebuilding them in place would leave half-migrated
        # destinations announcing under the wrong key.
        @routes.post("/api/v1/identity/reset")
        async def index(request):

            if self.identity_file_path is None:
                return web.json_response({
                    "message": "This instance was started with --identity-base64, so there is no "
                               "identity file to replace. Start it with --identity-file or let it "
                               "use the default storage directory, then try again.",
                }, status=409)

            try:
                data = await request.json()
            except Exception:
                data = {}

            # the UI asks for explicit confirmation; require it on the wire too, so
            # a stray POST cannot replace someone's identity
            if data.get("confirm") is not True:
                return web.json_response({
                    "message": "Refusing to reset without confirmation.",
                }, status=422)

            previous_hash = self.identity.hash.hex()

            try:
                backup_path = "{}.replaced-{}".format(
                    self.identity_file_path, int(time.time()),
                )

                # keep the old key before writing anything
                if os.path.exists(self.identity_file_path):
                    shutil.copy2(self.identity_file_path, backup_path)
                else:
                    backup_path = None

                new_identity = RNS.Identity(create_keys=True)
                with open(self.identity_file_path, "wb") as file:
                    file.write(new_identity.get_private_key())

            except Exception as e:
                return web.json_response({
                    "message": "Failed to write the new identity: {}".format(e),
                }, status=500)

            print("Reticulum Identity <{}> replaced with <{}>. Previous key saved to {}".format(
                previous_hash, new_identity.hash.hex(), backup_path,
            ))

            return web.json_response({
                "message": "Identity replaced. Restart LCS MeshChat for it to take effect.",
                "previous_identity_hash": previous_hash,
                "new_identity_hash": new_identity.hash.hex(),
                "previous_identity_backup_path": backup_path,
                "restart_required": True,
            })

        # update config
        @routes.patch("/api/v1/config")
        async def index(request):

            # get request body as json
            data = await request.json()

            # update config
            await self.update_config(data)

            return web.json_response({
                "config": self.get_config_dict(),
            })

        # enable transport mode
        @routes.post("/api/v1/reticulum/enable-transport")
        async def index(request):

            # enable transport mode
            self.reticulum.config["reticulum"]["enable_transport"] = True
            self.reticulum.config.write()

            return web.json_response({
                "message": "Transport has been enabled. MeshChat must be restarted for this change to take effect.",
            })

        # disable transport mode
        @routes.post("/api/v1/reticulum/disable-transport")
        async def index(request):

            # disable transport mode
            self.reticulum.config["reticulum"]["enable_transport"] = False
            self.reticulum.config.write()

            return web.json_response({
                "message": "Transport has been disabled. MeshChat must be restarted for this change to take effect.",
            })

        # get calls
        @routes.get("/api/v1/calls")
        async def index(request):

            # get audio calls
            audio_calls = []
            for audio_call in self.audio_call_manager.audio_calls:
                audio_calls.append(self.convert_audio_call_to_dict(audio_call))

            return web.json_response({
                "audio_calls": audio_calls,
            })

        # clear call history
        @routes.post("/api/v1/calls/clear-call-history")
        async def index(request):

            # delete inactive calls, which are classed as call history
            for audio_call in self.audio_call_manager.audio_calls:
                if audio_call.is_active() is False:
                    self.audio_call_manager.delete_audio_call(audio_call)

            return web.json_response({
                "message": "Call history has been cleared",
            })

        # hangup all calls
        @routes.get("/api/v1/calls/hangup-all")
        async def index(request):
            self.audio_call_manager.hangup_all()
            return web.json_response({
                "message": "All calls have been hungup",
            })

        # get call
        @routes.get("/api/v1/calls/{audio_call_link_hash}")
        async def index(request):

            # get path params
            audio_call_link_hash = request.match_info.get("audio_call_link_hash", "")

            # convert hash to bytes
            audio_call_link_hash = bytes.fromhex(audio_call_link_hash)

            # find audio call
            audio_call = self.audio_call_manager.find_audio_call_by_link_hash(audio_call_link_hash)
            if audio_call is None:
                return web.json_response({
                    "message": "audio call not found",
                }, status=404)

            return web.json_response({
                "audio_call": self.convert_audio_call_to_dict(audio_call),
            })

        # delete call
        @routes.delete("/api/v1/calls/{audio_call_link_hash}")
        async def index(request):

            # get path params
            audio_call_link_hash = request.match_info.get("audio_call_link_hash", "")

            # convert hash to bytes
            audio_call_link_hash = bytes.fromhex(audio_call_link_hash)

            # delete audio call
            self.audio_call_manager.delete_audio_call_by_link_hash(audio_call_link_hash)

            return web.json_response({
                "message": "audio call deleted",
            })

        # initiate a call to the provided destination
        @routes.get("/api/v1/calls/initiate/{destination_hash}")
        async def index(request):

            # get path params
            destination_hash = request.match_info.get("destination_hash", "")
            timeout_seconds = int(request.query.get("timeout", 15))

            # convert destination hash to bytes
            destination_hash = bytes.fromhex(destination_hash)

            # initiate audio call
            try:

                audio_call = await self.audio_call_manager.initiate(destination_hash, timeout_seconds)
                return web.json_response({
                    "audio_call": self.convert_audio_call_to_dict(audio_call),
                })

            except Exception as e:

                return web.json_response({
                    "message": "Call Failed: {}".format(str(e)),
                }, status=503)

        # handle websocket client for sending and receiving audio packets in a call
        @routes.get("/api/v1/calls/{audio_call_link_hash}/audio")
        async def ws(request):

            # get path params
            audio_call_link_hash = request.match_info.get("audio_call_link_hash", "")

            # convert hash to bytes
            audio_call_link_hash = bytes.fromhex(audio_call_link_hash)

            # find audio call, this will be null until the link is established
            audio_call = self.audio_call_manager.find_audio_call_by_link_hash(audio_call_link_hash)
            if audio_call is None:
                # fixme: web browser expects websocket, so this won't be useful
                return web.json_response({
                    "message": "audio call not found",
                }, status=404)

            # send audio received from call initiator to call receiver websocket
            def on_audio_packet(data):
                if websocket_response.closed is False:
                    try:
                        AsyncUtils.run_async(websocket_response.send_bytes(data))
                    except:
                        # ignore errors sending audio packets to websocket
                        pass

            # close websocket when call is hungup
            def on_hangup():
                if websocket_response.closed is False:
                    try:
                        AsyncUtils.run_async(websocket_response.close(code=WSCloseCode.GOING_AWAY))
                    except:
                        # ignore errors closing websocket
                        pass

            # register audio packet listener
            audio_call.register_audio_packet_listener(on_audio_packet)
            audio_call.register_hangup_listener(on_hangup)

            # prepare websocket response
            websocket_response = web.WebSocketResponse()
            await websocket_response.prepare(request)

            # handle websocket messages until disconnected
            # FIXME: we should send a type with the message, so we can send other data as well
            async for msg in websocket_response:
                msg: WSMessage = msg
                if msg.type == WSMsgType.BINARY:
                    try:
                        audio_call.send_audio_packet(msg.data)
                    except Exception as e:
                        # ignore errors while handling message
                        print("failed to process client message")
                        print(e)
                elif msg.type == WSMsgType.ERROR:
                    # ignore errors while handling message
                    print('ws connection error %s' % websocket_response.exception())

            # unregister audio packet handler now that the websocket has been closed
            audio_call.register_audio_packet_listener(on_audio_packet)

            return websocket_response

        # hangup calls
        @routes.get("/api/v1/calls/{audio_call_link_hash}/hangup")
        async def index(request):

            # get path params
            audio_call_link_hash = request.match_info.get("audio_call_link_hash", "")

            # convert hash to bytes
            audio_call_link_hash = bytes.fromhex(audio_call_link_hash)

            # find audio call
            audio_call = self.audio_call_manager.find_audio_call_by_link_hash(audio_call_link_hash)
            if audio_call is None:
                return web.json_response({
                    "message": "audio call not found",
                }, status=404)

            # hangup the call
            audio_call.hangup()

            return web.json_response({
                "message": "Call has been hungup",
            })

        # announce
        @routes.get("/api/v1/announce")
        async def index(request):

            await self.announce()

            return web.json_response({
                "message": "announcing",
            })

        # serve announces
        @routes.get("/api/v1/announces")
        async def index(request):

            # get query params
            aspect = request.query.get("aspect", None)
            identity_hash = request.query.get("identity_hash", None)
            destination_hash = request.query.get("destination_hash", None)
            limit = request.query.get("limit", None)

            # build announces database query
            query = database.Announce.select()

            # filter by provided aspect
            if aspect is not None:
                query = query.where(database.Announce.aspect == aspect)

            # filter by provided identity hash
            if identity_hash is not None:
                query = query.where(database.Announce.identity_hash == identity_hash)

            # filter by provided destination hash
            if destination_hash is not None:
                query = query.where(database.Announce.destination_hash == destination_hash)

            # limit results
            if limit is not None:
                query = query.limit(limit)

            # order announces latest to oldest
            query_results = query.order_by(database.Announce.updated_at.desc())

            # process announces
            announces = []
            for announce in query_results:
                announces.append(self.convert_db_announce_to_dict(announce))

            return web.json_response({
                "announces": announces,
            })

        # serve favourites
        @routes.get("/api/v1/favourites")
        async def index(request):

            # get query params
            aspect = request.query.get("aspect", None)

            # build favourites database query
            query = database.FavouriteDestination.select()

            # filter by provided aspect
            if aspect is not None:
                query = query.where(database.FavouriteDestination.aspect == aspect)

            # order favourites alphabetically
            query_results = query.order_by(database.FavouriteDestination.display_name.asc())

            # process favourites
            favourites = []
            for favourite in query_results:
                favourites.append(self.convert_db_favourite_to_dict(favourite))

            return web.json_response({
                "favourites": favourites,
            })

        # add favourite
        @routes.post("/api/v1/favourites/add")
        async def index(request):

            # get request data
            data = await request.json()
            destination_hash = data.get("destination_hash", None)
            display_name = data.get("display_name", None)
            aspect = data.get("aspect", None)

            # destination hash is required
            if destination_hash is None:
                return web.json_response({
                    "message": "destination_hash is required",
                }, status=422)

            # display name is required
            if display_name is None:
                return web.json_response({
                    "message": "display_name is required",
                }, status=422)

            # aspect is required
            if aspect is None:
                return web.json_response({
                    "message": "aspect is required",
                }, status=422)

            # upsert favourite
            self.db_upsert_favourite(destination_hash, display_name, aspect)
            return web.json_response({
                "message": "Favourite has been added!",
            })

        # rename favourite
        @routes.post("/api/v1/favourites/{destination_hash}/rename")
        async def index(request):

            # get path params
            destination_hash = request.match_info.get("destination_hash", "")

            # get request data
            data = await request.json()
            display_name = data.get("display_name")

            # update display name if provided
            if len(display_name) > 0:
                database.FavouriteDestination.update(display_name=display_name).where(database.FavouriteDestination.destination_hash == destination_hash).execute()

            return web.json_response({
                "message": "Favourite has been renamed",
            })

        # delete favourite
        @routes.delete("/api/v1/favourites/{destination_hash}")
        async def index(request):

            # get path params
            destination_hash = request.match_info.get("destination_hash", "")

            # delete favourite
            database.FavouriteDestination.delete().where(database.FavouriteDestination.destination_hash == destination_hash).execute()
            return web.json_response({
                "message": "Favourite has been added!",
            })

        # propagation node status
        @routes.get("/api/v1/lxmf/propagation-node/status")
        async def index(request):
            return web.json_response({
                "propagation_node_status": {
                    "state": self.convert_propagation_node_state_to_string(self.message_router.propagation_transfer_state),
                    "progress": self.message_router.propagation_transfer_progress * 100,  # convert to percentage
                    "messages_received": self.message_router.propagation_transfer_last_result,
                },
            })

        # sync propagation node
        @routes.get("/api/v1/lxmf/propagation-node/sync")
        async def index(request):

            # ensure propagation node is configured before attempting to sync
            if self.message_router.get_outbound_propagation_node() is None:
                return web.json_response({
                    "message": "A propagation node must be configured to sync messages.",
                }, status=400)

            # request messages from propagation node
            await self.sync_propagation_nodes()

            return web.json_response({
                "message": "Sync is starting",
            })

        # stop syncing propagation node
        @routes.get("/api/v1/lxmf/propagation-node/stop-sync")
        async def index(request):

            self.stop_propagation_node_sync()

            return web.json_response({
                "message": "Sync is stopping",
            })

        # serve propagation nodes
        @routes.get("/api/v1/lxmf/propagation-nodes")
        async def index(request):

            # get query params
            limit = request.query.get("limit", None)

            # get lxmf.propagation announces
            query = database.Announce.select().where(database.Announce.aspect == "lxmf.propagation")

            # limit results
            if limit is not None:
                query = query.limit(limit)

            # order announces latest to oldest
            query_results = query.order_by(database.Announce.updated_at.desc())

            # process announces
            lxmf_propagation_nodes = []
            for announce in query_results:

                # find an lxmf.delivery announce for the same identity hash, so we can use that as an "operater by" name
                lxmf_delivery_announce = (database.Announce.select()
                                          .where(database.Announce.aspect == "lxmf.delivery")
                                          .where(database.Announce.identity_hash == announce.identity_hash)
                                          .get_or_none())

                # find a nomadnetwork.node announce for the same identity hash, so we can use that as an "operated by" name
                nomadnetwork_node_announce = (database.Announce.select()
                                          .where(database.Announce.aspect == "nomadnetwork.node")
                                          .where(database.Announce.identity_hash == announce.identity_hash)
                                          .get_or_none())

                # get a display name from other announces belonging to the propagation nodes identity
                operator_display_name = None
                if lxmf_delivery_announce is not None and lxmf_delivery_announce.app_data is not None:
                    operator_display_name = self.parse_lxmf_display_name(lxmf_delivery_announce.app_data, None)
                elif nomadnetwork_node_announce is not None and nomadnetwork_node_announce.app_data is not None:
                    operator_display_name = self.parse_nomadnetwork_node_display_name(nomadnetwork_node_announce.app_data, None)

                # parse app_data so we can see if propagation is enabled or disabled for this node
                is_propagation_enabled = None
                per_transfer_limit = None
                propagation_node_data = self.parse_lxmf_propagation_node_app_data(announce.app_data)
                if propagation_node_data is not None:
                    is_propagation_enabled = propagation_node_data["enabled"]
                    per_transfer_limit = propagation_node_data["per_transfer_limit"]

                lxmf_propagation_nodes.append({
                    "destination_hash": announce.destination_hash,
                    "identity_hash": announce.identity_hash,
                    "operator_display_name": operator_display_name,
                    "is_propagation_enabled": is_propagation_enabled,
                    "per_transfer_limit": per_transfer_limit,
                    "created_at": announce.created_at,
                    "updated_at": announce.updated_at,
                })

            return web.json_response({
                "lxmf_propagation_nodes": lxmf_propagation_nodes,
            })

        # get path to destination
        @routes.get("/api/v1/destination/{destination_hash}/path")
        async def index(request):

            # get path params
            destination_hash = request.match_info.get("destination_hash", "")

            # convert destination hash to bytes
            destination_hash = bytes.fromhex(destination_hash)

            # check if user wants to request the path from the network right now
            request_query_param = request.query.get("request", "false")
            should_request_now = request_query_param == "true" or request_query_param == "1"

            # LCS: force=true asks even when a path is already known. A known but
            # stale entry is the usual reason sending fails while the UI still shows
            # a hop count, and the response to the request refreshes it.
            force_query_param = request.query.get("force", "false")
            should_force = force_query_param == "true" or force_query_param == "1"

            path_was_known = RNS.Transport.has_path(destination_hash)
            path_was_requested = False

            if should_request_now or should_force:

                # determine how long we should wait for a path response
                timeout_seconds = int(request.query.get("timeout", 15))
                timeout_after_seconds = time.time() + timeout_seconds

                # request path if we don't have it, or if asked to regardless
                if should_force or not path_was_known:
                    RNS.Transport.request_path(destination_hash)
                    path_was_requested = True

                if path_was_known and should_force:
                    # nothing will flip from false to true, so just give the
                    # response time to arrive rather than polling for a change
                    await asyncio.sleep(min(2, timeout_seconds))
                else:
                    # wait until we have a path, or give up after the configured timeout
                    while not RNS.Transport.has_path(destination_hash) and time.time() < timeout_after_seconds:
                        await asyncio.sleep(0.1)

            # ensure path is known
            if not RNS.Transport.has_path(destination_hash):
                return web.json_response({
                    "path": None,
                    "path_was_known": path_was_known,
                    "path_was_requested": path_was_requested,
                })

            # determine next hop and hop count
            hops = RNS.Transport.hops_to(destination_hash)
            next_hop_bytes = self.reticulum.get_next_hop(destination_hash)

            # ensure next hop provided
            if next_hop_bytes is None:
                return web.json_response({
                    "path": None,
                    "path_was_known": path_was_known,
                    "path_was_requested": path_was_requested,
                })

            next_hop = next_hop_bytes.hex()
            next_hop_interface = self.reticulum.get_next_hop_if_name(destination_hash)

            return web.json_response({
                "path": {
                    "hops": hops,
                    "next_hop": next_hop,
                    "next_hop_interface": next_hop_interface,
                },
                "path_was_known": path_was_known,
                "path_was_requested": path_was_requested,
            })

        # drop path to destination
        @routes.post("/api/v1/destination/{destination_hash}/drop-path")
        async def index(request):

            # get path params
            destination_hash = request.match_info.get("destination_hash", "")

            # convert destination hash to bytes
            destination_hash = bytes.fromhex(destination_hash)

            # drop path
            self.reticulum.drop_path(destination_hash)

            return web.json_response({
                "message": "Path has been dropped",
            })

        # get signal metrics for a destination by checking the latest announce or lxmf message received from them
        @routes.get("/api/v1/destination/{destination_hash}/signal-metrics")
        async def index(request):

            # get path params
            destination_hash = request.match_info.get("destination_hash", "")

            # signal metrics to return
            snr = None
            rssi = None
            quality = None
            updated_at = None

            # get latest announce from database for the provided destination hash
            latest_announce = (database.Announce.select()
                               .where(database.Announce.destination_hash == destination_hash)
                               .get_or_none())

            # get latest lxmf message from database sent to us from the provided destination hash
            latest_lxmf_message = (database.LxmfMessage.select()
                                   .where(database.LxmfMessage.destination_hash == self.local_lxmf_destination.hexhash)
                                   .where(database.LxmfMessage.source_hash == destination_hash)
                                   .order_by(database.LxmfMessage.id.desc())
                                   .get_or_none())

            # determine when latest announce was received
            latest_announce_at = None
            if latest_announce is not None:
                latest_announce_at = datetime.fromisoformat(latest_announce.updated_at)

            # determine when latest lxmf message was received
            latest_lxmf_message_at = None
            if latest_lxmf_message is not None:
                latest_lxmf_message_at = datetime.fromisoformat(latest_lxmf_message.created_at)

            # get signal metrics from latest announce
            if latest_announce is not None:
                snr = latest_announce.snr
                rssi = latest_announce.rssi
                quality = latest_announce.quality
                # using updated_at from announce because this is when the latest announce was received
                updated_at = latest_announce.updated_at

            # get signal metrics from latest lxmf message if it's more recent than the announce
            if latest_lxmf_message is not None and (latest_announce_at is None or latest_lxmf_message_at > latest_announce_at):
                snr = latest_lxmf_message.snr
                rssi = latest_lxmf_message.rssi
                quality = latest_lxmf_message.quality
                # using created_at from lxmf message because this is when the message was received
                updated_at = latest_lxmf_message.created_at

            return web.json_response({
                "signal_metrics": {
                    "snr": snr,
                    "rssi": rssi,
                    "quality": quality,
                    "updated_at": updated_at,
                },
            })

        # pings an lxmf.delivery destination by sending empty data and waiting for the recipient to send a proof back
        # the lxmf router proves all received packets, then drops them if they can't be decoded as lxmf messages
        # this allows us to ping/probe any active lxmf.delivery destination and get rtt/snr/rssi data on demand
        # https://github.com/markqvist/LXMF/blob/9ff76c0473e9d4107e079f266dd08144bb74c7c8/LXMF/LXMRouter.py#L234
        # https://github.com/markqvist/LXMF/blob/9ff76c0473e9d4107e079f266dd08144bb74c7c8/LXMF/LXMRouter.py#L1374
        @routes.get("/api/v1/ping/{destination_hash}/lxmf.delivery")
        async def index(request):

            # get path params
            destination_hash = request.match_info.get("destination_hash", "")

            # convert destination hash to bytes
            destination_hash = bytes.fromhex(destination_hash)

            # determine how long until we should time out
            timeout_seconds = int(request.query.get("timeout", 15))
            timeout_after_seconds = time.time() + timeout_seconds

            # request path if we don't have it
            if not RNS.Transport.has_path(destination_hash):
                RNS.Transport.request_path(destination_hash)

            # wait until we have a path, or give up after the configured timeout
            while not RNS.Transport.has_path(destination_hash) and time.time() < timeout_after_seconds:
                await asyncio.sleep(0.1)

            # find destination identity
            destination_identity = RNS.Identity.recall(destination_hash)
            if destination_identity is None:
                return web.json_response({
                    "message": "Ping failed. Could not find path to destination.",
                }, status=503)

            # create outbound destination
            request_destination = RNS.Destination(
                destination_identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                "lxmf",
                "delivery",
            )

            # send empty packet to destination
            packet = RNS.Packet(request_destination, b"")
            receipt = packet.send()

            # wait until delivered, or give up after time out
            while receipt.status != RNS.PacketReceipt.DELIVERED and time.time() < timeout_after_seconds:
                await asyncio.sleep(0.1)

            # ping failed if not delivered
            if receipt.status != RNS.PacketReceipt.DELIVERED:
                return web.json_response({
                    "message": f"Ping failed. Timed out after {timeout_seconds} seconds.",
                }, status=503)

            # get number of hops to destination and back from destination
            hops_there = RNS.Transport.hops_to(destination_hash)
            hops_back = receipt.proof_packet.hops

            # get rssi
            rssi = receipt.proof_packet.rssi
            if rssi is None:
                rssi = self.reticulum.get_packet_rssi(receipt.proof_packet.packet_hash)

            # get snr
            snr = receipt.proof_packet.snr
            if snr is None:
                snr = self.reticulum.get_packet_snr(receipt.proof_packet.packet_hash)

            # get signal quality
            quality = receipt.proof_packet.q
            if quality is None:
                quality = self.reticulum.get_packet_q(receipt.proof_packet.packet_hash)

            # get and format round trip time
            rtt = receipt.get_rtt()
            rtt_milliseconds = round(rtt * 1000, 3)
            rtt_duration_string = f"{rtt_milliseconds} ms"

            return web.json_response({
                "message": f"Valid reply from {receipt.destination.hash.hex()}\nDuration: {rtt_duration_string}\nHops There: {hops_there}\nHops Back: {hops_back}",
                "ping_result": {
                    "rtt": rtt,
                    "hops_there": hops_there,
                    "hops_back": hops_back,
                    "rssi": rssi,
                    "snr": snr,
                    "quality": quality,
                    "receiving_interface": str(receipt.proof_packet.receiving_interface),
                },
            })

        # get custom destination display name
        @routes.get("/api/v1/destination/{destination_hash}/custom-display-name")
        async def index(request):

            # get path params
            destination_hash = request.match_info.get("destination_hash", "")

            return web.json_response({
                "custom_display_name": self.get_custom_destination_display_name(destination_hash),
            })

        # set custom destination display name
        @routes.post("/api/v1/destination/{destination_hash}/custom-display-name/update")
        async def index(request):

            # get path params
            destination_hash = request.match_info.get("destination_hash", "")

            # get request data
            data = await request.json()
            display_name = data.get('display_name')

            # update display name if provided
            if len(display_name) > 0:
                self.db_upsert_custom_destination_display_name(destination_hash, display_name)
                return web.json_response({
                    "message": "Custom display name has been updated",
                })

            # otherwise remove display name
            else:
                database.CustomDestinationDisplayName.delete().where(database.CustomDestinationDisplayName.destination_hash == destination_hash).execute()
                return web.json_response({
                    "message": "Custom display name has been removed",
                })

        # get lxmf stamp cost for the provided lxmf.delivery destination hash
        @routes.get("/api/v1/destination/{destination_hash}/lxmf-stamp-info")
        async def index(request):

            # get path params
            destination_hash = request.match_info.get("destination_hash", "")

            # convert destination hash to bytes
            destination_hash = bytes.fromhex(destination_hash)

            # get lxmf stamp cost from announce in database
            lxmf_stamp_cost = None
            announce = database.Announce.get_or_none(database.Announce.destination_hash == destination_hash.hex())
            if announce is not None:
                lxmf_stamp_cost = self.parse_lxmf_stamp_cost(announce.app_data)

            # get outbound ticket expiry for this lxmf destination
            lxmf_outbound_ticket_expiry = self.message_router.get_outbound_ticket_expiry(destination_hash)

            return web.json_response({
                "lxmf_stamp_info": {
                    "stamp_cost": lxmf_stamp_cost,
                    "outbound_ticket_expiry": lxmf_outbound_ticket_expiry,
                },
            })

        # get interface stats
        @routes.get("/api/v1/interface-stats")
        async def index(request):

            # get interface stats
            interface_stats = self.reticulum.get_interface_stats()

            # ensure transport_id is hex as json_response can't serialize bytes
            if "transport_id" in interface_stats:
                interface_stats["transport_id"] = interface_stats["transport_id"].hex()

            # ensure network_id is hex as json_response can't serialize bytes
            if "network_id" in interface_stats and interface_stats["network_id"] is not None:
                interface_stats["network_id"] = interface_stats["network_id"].hex()

            # ensure probe_responder is hex as json_response can't serialize bytes
            if "probe_responder" in interface_stats and interface_stats["probe_responder"] is not None:
                interface_stats["probe_responder"] = interface_stats["probe_responder"].hex()
            
            # ensure ifac_signature is hex as json_response can't serialize bytes
            for interface in interface_stats["interfaces"]:

                if "short_name" in interface:
                    interface["interface_name"] = interface["short_name"]

                if "parent_interface_name" in interface and interface["parent_interface_name"] is not None:
                    interface["parent_interface_hash"] = interface["parent_interface_hash"].hex()

                if "ifac_signature" in interface and interface["ifac_signature"]:
                    interface["ifac_signature"] = interface["ifac_signature"].hex()

                if "hash" in interface and interface["hash"]:
                    interface["hash"] = interface["hash"].hex()

            return web.json_response({
                "interface_stats": interface_stats,
            })

        # get path table
        @routes.get("/api/v1/path-table")
        async def index(request):

            # get path table, making sure hash and via are in hex as json_response can't serialize bytes
            path_table = []
            for path in self.reticulum.get_path_table():
                path["hash"] = path["hash"].hex()
                path["via"] = path["via"].hex()
                path_table.append(path)

            return web.json_response({
                "path_table": path_table,
            })

        # send lxmf message
        @routes.post("/api/v1/lxmf-messages/send")
        async def index(request):

            # get request body as json
            data = await request.json()

            # get delivery method
            delivery_method = None
            if "delivery_method" in data:
                delivery_method = data["delivery_method"]

            # get data from json
            destination_hash = data["lxmf_message"]["destination_hash"]
            content = data["lxmf_message"]["content"]
            fields = {}
            if "fields" in data["lxmf_message"]:
                fields = data["lxmf_message"]["fields"]

            # parse image field
            image_field = None
            if "image" in fields:
                image_type = data["lxmf_message"]["fields"]["image"]["image_type"]
                image_bytes = base64.b64decode(data["lxmf_message"]["fields"]["image"]["image_bytes"])
                image_field = LxmfImageField(image_type, image_bytes)

            # parse audio field
            audio_field = None
            if "audio" in fields:
                audio_mode = data["lxmf_message"]["fields"]["audio"]["audio_mode"]
                audio_bytes = base64.b64decode(data["lxmf_message"]["fields"]["audio"]["audio_bytes"])
                audio_field = LxmfAudioField(audio_mode, audio_bytes)

            # parse file attachments field
            file_attachments_field = None
            if "file_attachments" in fields:

                file_attachments = []
                for file_attachment in data["lxmf_message"]["fields"]["file_attachments"]:
                    file_name = file_attachment["file_name"]
                    file_bytes = base64.b64decode(file_attachment["file_bytes"])
                    file_attachments.append(LxmfFileAttachment(file_name, file_bytes))

                file_attachments_field = LxmfFileAttachmentsField(file_attachments)

            try:

                # send lxmf message to destination
                lxmf_message = await self.send_message(
                    destination_hash=destination_hash,
                    content=content,
                    image_field=image_field,
                    audio_field=audio_field,
                    file_attachments_field=file_attachments_field,
                    delivery_method=delivery_method
                )

                return web.json_response({
                    "lxmf_message": self.convert_lxmf_message_to_dict(lxmf_message),
                })

            except Exception as e:
                return web.json_response({
                    "message": "Sending Failed: {}".format(str(e)),
                }, status=503)

        # cancel sending lxmf message
        @routes.post("/api/v1/lxmf-messages/{hash}/cancel")
        async def index(request):

            # get path params
            hash = request.match_info.get("hash", None)

            # convert hash to bytes
            hash_as_bytes = bytes.fromhex(hash)

            # cancel outbound message by lxmf message hash
            self.message_router.cancel_outbound(hash_as_bytes)

            # get lxmf message from database
            lxmf_message = None
            db_lxmf_message = database.LxmfMessage.get_or_none(database.LxmfMessage.hash == hash)
            if db_lxmf_message is not None:
                lxmf_message = self.convert_db_lxmf_message_to_dict(db_lxmf_message)

            return web.json_response({
                "message": "ok",
                "lxmf_message": lxmf_message,
            })

        # identify self on existing nomadnetwork link
        @routes.post("/api/v1/nomadnetwork/{destination_hash}/identify")
        async def index(request):

            # get path params
            destination_hash = request.match_info.get("destination_hash", "")

            # convert destination hash to bytes
            destination_hash = bytes.fromhex(destination_hash)

            # identify to existing active link
            if destination_hash in nomadnet_cached_links:
                link = nomadnet_cached_links[destination_hash]
                if link.status is RNS.Link.ACTIVE:
                    link.identify(self.identity)
                    return web.json_response({
                        "message": "Identity has been sent!",
                    })

            # failed to identify
            return web.json_response({
                "message": "Failed to identify. No active link to destination.",
            }, status=500)

        # delete lxmf message
        @routes.delete("/api/v1/lxmf-messages/{hash}")
        async def index(request):

            # get path params
            hash = request.match_info.get("hash", None)

            # hash is required
            if hash is None:
                return web.json_response({
                    "message": "hash is required",
                }, status=422)

            # delete lxmf messages from db where hash matches
            database.LxmfMessage.delete().where((database.LxmfMessage.hash == hash)).execute()

            return web.json_response({
                "message": "ok",
            })

        # serve lxmf messages for conversation
        @routes.get("/api/v1/lxmf-messages/conversation/{destination_hash}")
        async def index(request):

            # get path params
            destination_hash = request.match_info.get("destination_hash", "")
            order = request.query.get("order", "asc")
            count = request.query.get("count")
            after_id = request.query.get("after_id")

            # get source hash from local lxmf destination
            source_hash = self.local_lxmf_destination.hash.hex()

            # get lxmf messages from db where "source to destination" or "destination to source" and ordered by oldest to newest
            db_lxmf_messages = (database.LxmfMessage.select()
                     .where((database.LxmfMessage.source_hash == source_hash) & (database.LxmfMessage.destination_hash == destination_hash))
                     .orwhere((database.LxmfMessage.destination_hash == source_hash) & (database.LxmfMessage.source_hash == destination_hash))
                     .order_by(database.LxmfMessage.id.asc() if order == "asc" else database.LxmfMessage.id.desc()))

            # limit how many messages to return
            if count is not None:
                db_lxmf_messages = db_lxmf_messages.limit(count)

            # only get records after provided id, based on query order
            if after_id is not None:
                if order == "asc":
                    db_lxmf_messages = db_lxmf_messages.where((database.LxmfMessage.id > after_id))
                else:
                    db_lxmf_messages = db_lxmf_messages.where((database.LxmfMessage.id < after_id))

            # convert to response json
            lxmf_messages = []
            for db_lxmf_message in db_lxmf_messages:
                lxmf_messages.append(self.convert_db_lxmf_message_to_dict(db_lxmf_message))

            return web.json_response({
                "lxmf_messages": lxmf_messages,
            })

        # delete lxmf messages for conversation
        @routes.delete("/api/v1/lxmf-messages/conversation/{destination_hash}")
        async def index(request):

            # get path params
            destination_hash = request.match_info.get("destination_hash", "")

            # get source hash from local lxmf destination
            source_hash = self.local_lxmf_destination.hash.hex()

            # delete lxmf messages from db where "source to destination" or "destination to source"
            (database.LxmfMessage.delete()
             .where((database.LxmfMessage.source_hash == source_hash) & (database.LxmfMessage.destination_hash == destination_hash))
             .orwhere((database.LxmfMessage.destination_hash == source_hash) & (database.LxmfMessage.source_hash == destination_hash))
             .execute())

            return web.json_response({
                "message": "ok",
            })

        # get unqiue lxmf conversations
        @routes.get("/api/v1/lxmf/conversations")
        async def index(request):

            # sql query to fetch unique source/destination hash pairs ordered by the most recently updated message
            query = """
            WITH NormalizedMessages AS (
                SELECT
                    CASE WHEN source_hash < destination_hash THEN source_hash ELSE destination_hash END AS normalized_source,
                    CASE WHEN source_hash < destination_hash THEN destination_hash ELSE source_hash END AS normalized_destination,
                    MAX(created_at) AS most_recent_created_at
                FROM lxmf_messages
                GROUP BY normalized_source, normalized_destination
            )
            SELECT
                normalized_source AS source_hash,
                normalized_destination AS destination_hash,
                most_recent_created_at
            FROM NormalizedMessages
            ORDER BY most_recent_created_at DESC;
            """

            # execute sql query
            cursor = database.database.execute_sql(query)

            # parse results to get a list of conversations we have sent or received a message from
            conversations = []
            for row in cursor.fetchall():

                # get data from row
                source_hash = row[0]
                destination_hash = row[1]
                created_at = row[2]

                # determine destination hash of other user
                if source_hash == self.local_lxmf_destination.hexhash:
                    other_user_hash = destination_hash
                else:
                    other_user_hash = source_hash

                # find lxmf user icon from database
                lxmf_user_icon = None
                db_lxmf_user_icon = database.LxmfUserIcon.get_or_none(database.LxmfUserIcon.destination_hash == other_user_hash)
                if db_lxmf_user_icon is not None:
                    lxmf_user_icon = {
                        "icon_name": db_lxmf_user_icon.icon_name,
                        "foreground_colour": db_lxmf_user_icon.foreground_colour,
                        "background_colour": db_lxmf_user_icon.background_colour,
                    }

                # add to conversations
                conversations.append({
                    "display_name": self.get_lxmf_conversation_name(other_user_hash),
                    "custom_display_name": self.get_custom_destination_display_name(other_user_hash),
                    "destination_hash": other_user_hash,
                    "is_unread": self.is_lxmf_conversation_unread(other_user_hash),
                    "failed_messages_count": self.lxmf_conversation_failed_messages_count(other_user_hash),
                    "lxmf_user_icon": lxmf_user_icon,
                    # we say the conversation was updated when the latest message was created
                    # otherwise this will go crazy when sending a message, as the updated_at on the latest message changes very frequently
                    "updated_at": created_at,
                })

            return web.json_response({
                "conversations": conversations,
            })

        # mark lxmf conversation as read
        @routes.get("/api/v1/lxmf/conversations/{destination_hash}/mark-as-read")
        async def index(request):

            # get path params
            destination_hash = request.match_info.get("destination_hash", "")

            # mark lxmf conversation as read
            self.db_mark_lxmf_conversation_as_read(destination_hash)

            return web.json_response({
                "message": "ok",
            })

        # called when web app has started
        async def on_startup(app):

            # remember main event loop
            AsyncUtils.set_main_loop(asyncio.get_event_loop())

            # auto launch web browser
            if launch_browser:
                try:
                    webbrowser.open("http://127.0.0.1:{}".format(port))
                except:
                    print("failed to launch web browser")

        # create and run web app
        # blackhole management
        # blocking works on identity hashes and applies to this node's own
        # network segments only, exactly as rnpath -B/-U/-b does
        @routes.get("/api/v1/blackhole")
        async def index(request):
            manager = self.get_blackhole_manager()
            return web.json_response({
                "blackholed": manager.list(),
                "config": manager.get_config(),
            })

        @routes.post("/api/v1/blackhole")
        async def index(request):

            data = await request.json()

            # duration arrives in hours, matching rnpath --duration
            until = None
            duration_hours = data.get("duration_hours")
            if duration_hours is not None and str(duration_hours).strip() != "":
                try:
                    until = time.time() + (float(duration_hours) * 3600)
                except (TypeError, ValueError):
                    return web.json_response({"message": "duration_hours must be a number"}, status=422)

            manager = self.get_blackhole_manager()

            try:

                # resolve the identity first, asking the network for an announce if
                # it is not already known locally, then block the identity itself
                identity_hash = await manager.resolve_identity_hash_async(
                    identity_hash=data.get("identity_hash"),
                    destination_hash=data.get("destination_hash"),
                    request_timeout=float(data.get("request_timeout", 15)),
                )

                result = manager.block(
                    identity_hash=identity_hash.hex(),
                    reason=data.get("reason"),
                    until=until,
                )

            except ValueError as e:
                return web.json_response({"message": str(e)}, status=422)

            return web.json_response(result)

        @routes.delete("/api/v1/blackhole/{identity_hash}")
        async def index(request):
            try:
                result = self.get_blackhole_manager().unblock(
                    identity_hash=request.match_info.get("identity_hash", ""))
            except ValueError as e:
                return web.json_response({"message": str(e)}, status=422)
            return web.json_response(result)

        @routes.get("/api/v1/blackhole/config")
        async def index(request):
            return web.json_response({"config": self.get_blackhole_manager().get_config()})

        @routes.patch("/api/v1/blackhole/config")
        async def index(request):
            data = await request.json()
            try:
                config = self.get_blackhole_manager().set_config(
                    publish_blackhole=data.get("publish_blackhole"),
                    blackhole_sources=data.get("blackhole_sources"),
                    blackhole_update_interval=data.get("blackhole_update_interval"),
                )
            except ValueError as e:
                return web.json_response({"message": str(e)}, status=422)
            return web.json_response({"config": config})

        app = web.Application(client_max_size=1024 * 1024 * 50)  # allow uploading files up to 50mb
        app.add_routes(routes)

        # mount the rns link bridge and the microreticulum rnode console.
        # this has to happen before the catch-all static route below, otherwise
        # the static resource matches /console and /rns/ws first and 404s them.
        self.setup_rns_bridge(app, host, rns_bridge_options)

        app.add_routes([web.static('/', get_file_path("public/"))])  # serve anything in public folder
        app.on_shutdown.append(self.shutdown)  # need to force close websockets and stop reticulum now
        app.on_startup.append(on_startup)
        web.run_app(app, host=host, port=port)

    # blackhole manager, created on first use so it always wraps the live
    # reticulum instance rather than a copy captured at startup
    def get_blackhole_manager(self):
        if getattr(self, "blackhole_manager", None) is None:
            self.blackhole_manager = BlackholeManager(
                self.reticulum,
                identity_hash_lookup=self.find_identity_hash_for_destination,
            )
        return self.blackhole_manager

    # every announce meshchat has ever seen is stored with the identity hash that
    # sent it, so a peer can be resolved without asking the network at all
    def find_identity_hash_for_destination(self, destination_hash):
        announce = database.Announce.get_or_none(
            database.Announce.destination_hash == destination_hash)
        return announce.identity_hash if announce is not None else None

    # sets up the websocket bridge that lets the microreticulum rnode console
    # open reticulum links to remote transport nodes through this meshchat
    # instance, plus the local copy of the console itself.
    def setup_rns_bridge(self, app, host, rns_bridge_options: dict = None):

        options = rns_bridge_options or {}
        if options.get("enabled", True) is False:
            return

        # the console drives reboot, eeprom wipe and radio reconfiguration on
        # remote nodes, and websockets are not subject to cors, so every page
        # in every tab can reach this endpoint. the origin allow list below is
        # what stops that; loopback origins and file:// pages are allowed, and
        # anything else has to be named explicitly.
        config = BridgeConfig(
            token=options.get("token"),
            allowed_origins=tuple(options.get("allowed_origins") or ()),
            request_timeout=options.get("request_timeout") or 30.0,
        )

        # identity matters here: this is the identity presented to the remote
        # node when the console asks to authenticate, so it needs to be the one
        # the node operator put in their /provision allow list. using the same
        # identity meshchat announces means the hash the user already knows is
        # the hash that gets allowed.
        def backend_factory():
            return LocalBackend(identity=self.identity)

        attach_to_app(
            app,
            backend_factory=backend_factory,
            config=config,
        )

        if host not in ["127.0.0.1", "localhost", "::1"] and config.token is None:
            print("WARNING: the RNS console bridge is reachable from the network "
                  "because --host is not loopback. Pass --rns-bridge-token to require a token.")

        # optional second listener on a fixed port, for a console opened from
        # disk or from a hosted copy, where meshchat's port is not known in
        # advance. off by default: the electron app already runs meshchat
        # itself on 9337, so a second listener there would collide.
        # bound to loopback regardless of --host.
        bridge_port = options.get("port")
        if bridge_port is None:
            return

        async def start_rns_bridge_listener(app):
            try:
                app["rns_bridge_runner"] = await run_standalone(
                    backend_factory=backend_factory,
                    config=config,
                    host="127.0.0.1",
                    port=bridge_port,
                )
                print("RNS console bridge listening on ws://127.0.0.1:{}/ws".format(bridge_port))
            except Exception as e:
                # a busy port must not stop meshchat from starting, the bridge
                # is still available on meshchat's own port at /rns/ws
                print("failed to start RNS console bridge on port {}: {}".format(bridge_port, e))

        async def stop_rns_bridge_listener(app):
            runner = app.get("rns_bridge_runner")
            if runner is not None:
                await runner.cleanup()

        app.on_startup.append(start_rns_bridge_listener)
        app.on_cleanup.append(stop_rns_bridge_listener)

    # handle announcing
    async def announce(self):

        # update last announced at timestamp
        self.config.last_announced_at.set(int(time.time()))

        # send announce for lxmf (ensuring name is updated before announcing)
        self.local_lxmf_destination.display_name = self.config.display_name.get()
        self.message_router.announce(destination_hash=self.local_lxmf_destination.hash)

        # send announce for local propagation node (if enabled)
        if self.config.lxmf_local_propagation_node_enabled.get():
            self.message_router.announce_propagation_node()

        # send announce for audio call
        self.audio_call_manager.announce(app_data=self.config.display_name.get().encode("utf-8"))

        # send announce for telephone if enabled
        if self.telephone is not None:
            self.telephone.announce()

        # tell websocket clients we just announced
        await self.send_announced_to_websocket_clients()

    # handle syncing propagation nodes
    async def sync_propagation_nodes(self):

        # update last synced at timestamp
        self.config.lxmf_preferred_propagation_node_last_synced_at.set(int(time.time()))

        # request messages from propagation node
        self.message_router.request_messages_from_propagation_node(self.identity)

        # send config to websocket clients (used to tell ui last synced at)
        await self.send_config_to_websocket_clients()

    async def update_config(self, data):

        # update display name in config
        if "display_name" in data and data["display_name"] != "":
            self.config.display_name.set(data["display_name"])

        # update theme in config
        if "theme" in data and data["theme"] != "":
            self.config.theme.set(data["theme"])

        # update auto announce interval
        if "auto_announce_interval_seconds" in data:

            # auto auto announce interval
            auto_announce_interval_seconds = int(data["auto_announce_interval_seconds"])
            self.config.auto_announce_interval_seconds.set(data["auto_announce_interval_seconds"])

            # enable or disable auto announce based on interval
            if auto_announce_interval_seconds > 0:
                self.config.auto_announce_enabled.set(True)
            else:
                self.config.auto_announce_enabled.set(False)

        if "auto_resend_failed_messages_when_announce_received" in data:
            value = bool(data["auto_resend_failed_messages_when_announce_received"])
            self.config.auto_resend_failed_messages_when_announce_received.set(value)

        if "allow_auto_resending_failed_messages_with_attachments" in data:
            value = bool(data["allow_auto_resending_failed_messages_with_attachments"])
            self.config.allow_auto_resending_failed_messages_with_attachments.set(value)

        if "auto_send_failed_messages_to_propagation_node" in data:
            value = bool(data["auto_send_failed_messages_to_propagation_node"])
            self.config.auto_send_failed_messages_to_propagation_node.set(value)

        if "show_suggested_community_interfaces" in data:
            value = bool(data["show_suggested_community_interfaces"])
            self.config.show_suggested_community_interfaces.set(value)

        if "message_alert_enabled" in data:
            value = bool(data["message_alert_enabled"])
            self.config.message_alert_enabled.set(value)

        if "path_request_on_send_failure_enabled" in data:
            value = bool(data["path_request_on_send_failure_enabled"])
            self.config.path_request_on_send_failure_enabled.set(value)

        if "lxmf_preferred_propagation_node_destination_hash" in data:

            # update config value
            value = data["lxmf_preferred_propagation_node_destination_hash"]
            self.config.lxmf_preferred_propagation_node_destination_hash.set(value)

            # update active propagation node
            self.set_active_propagation_node(value)

            # LCS: manually setting/clearing the node stops auto-selecting (respect the
            # user's explicit choice) - unless they're also explicitly setting the toggle
            # in the same request, in which case that explicit value wins (handled below).
            if "auto_select_propagation_node" not in data:
                self.config.auto_select_propagation_node.set(False)

        # LCS: explicit auto-select toggle from Settings
        if "auto_select_propagation_node" in data:
            self.config.auto_select_propagation_node.set(bool(data["auto_select_propagation_node"]))

        # update auto sync interval
        if "lxmf_preferred_propagation_node_auto_sync_interval_seconds" in data:
            value = int(data["lxmf_preferred_propagation_node_auto_sync_interval_seconds"])
            self.config.lxmf_preferred_propagation_node_auto_sync_interval_seconds.set(value)

        if "lxmf_local_propagation_node_enabled" in data:

            # update config value
            value = bool(data["lxmf_local_propagation_node_enabled"])
            self.config.lxmf_local_propagation_node_enabled.set(value)

            # enable or disable local propagation node
            self.enable_local_propagation_node(value)

        # update lxmf user icon name in config
        if "lxmf_user_icon_name" in data:
            self.config.lxmf_user_icon_name.set(data["lxmf_user_icon_name"])

        # update lxmf user icon foreground colour in config
        if "lxmf_user_icon_foreground_colour" in data:
            self.config.lxmf_user_icon_foreground_colour.set(data["lxmf_user_icon_foreground_colour"])

        # update lxmf user icon background colour in config
        if "lxmf_user_icon_background_colour" in data:
            self.config.lxmf_user_icon_background_colour.set(data["lxmf_user_icon_background_colour"])

        # send config to websocket clients
        await self.send_config_to_websocket_clients()

    # converts nomadnetwork page variables from a string to a map
    # converts: "field1=123|field2=456"
    # to the following map:
    # - var_field1: 123
    # - var_field2: 456
    def convert_nomadnet_string_data_to_map(self, path_data: str | None):
        data = {}
        if path_data is not None:
            for field in path_data.split("|"):
                if "=" in field:
                    variable_name, variable_value = field.split("=")
                    data[f'var_{variable_name}'] = variable_value
                else:
                    print(f"unhandled field: {field}")
        return data

    def convert_nomadnet_field_data_to_map(self, field_data):
        data = {}
        if field_data is not None or "{}":
            try:
                json_data = field_data 
                if isinstance(json_data, dict):
                    # add the prefixed keys to the result dictionary
                    data = {f"field_{key}": value for key, value in json_data.items()}
                else:
                    return None
            except Exception as e:
                print(f"skipping invalid field data: {e}")
        
        return data

    # handle data received from websocket client
    async def on_websocket_data_received(self, client, data):

        # get type from client data
        _type = data["type"]

        # handle ping
        if _type == "ping":
            AsyncUtils.run_async(client.send_str(json.dumps({
                "type": "pong",
            })))

        # handle updating config
        elif _type == "config.set":

            # get config from websocket
            config = data["config"]

            # update config
            await self.update_config(config)

        # handle downloading a file from a nomadnet node
        elif _type == "nomadnet.file.download":

            # get data from websocket client
            destination_hash = data["nomadnet_file_download"]["destination_hash"]
            file_path = data["nomadnet_file_download"]["file_path"]

            # convert destination hash to bytes
            destination_hash = bytes.fromhex(destination_hash)

            # handle successful file download
            def on_file_download_success(file_name, file_bytes):
                AsyncUtils.run_async(client.send_str(json.dumps({
                    "type": "nomadnet.file.download",
                    "nomadnet_file_download": {
                        "status": "success",
                        "destination_hash": destination_hash.hex(),
                        "file_path": file_path,
                        "file_name": file_name,
                        "file_bytes": base64.b64encode(file_bytes).decode("utf-8"),
                    },
                })))

            # handle file download failure
            def on_file_download_failure(failure_reason):
                AsyncUtils.run_async(client.send_str(json.dumps({
                    "type": "nomadnet.file.download",
                    "nomadnet_file_download": {
                        "status": "failure",
                        "failure_reason": failure_reason,
                        "destination_hash": destination_hash.hex(),
                        "file_path": file_path,
                    },
                })))

            # handle file download progress
            def on_file_download_progress(progress):
                AsyncUtils.run_async(client.send_str(json.dumps({
                    "type": "nomadnet.file.download",
                    "nomadnet_file_download": {
                        "status": "progress",
                        "progress": progress,
                        "destination_hash": destination_hash.hex(),
                        "file_path": file_path,
                    },
                })))

            # download the file
            downloader = NomadnetFileDownloader(destination_hash, file_path, on_file_download_success, on_file_download_failure, on_file_download_progress)
            AsyncUtils.run_async(downloader.download())

        # handle downloading a page from a nomadnet node
        elif _type == "nomadnet.page.download":

            # get data from websocket client
            destination_hash = data["nomadnet_page_download"]["destination_hash"]
            page_path = data["nomadnet_page_download"]["page_path"]
            field_data = data["nomadnet_page_download"]["field_data"]
       
            combined_data = {}
            # parse data from page path
            # example: hash:/page/index.mu`field1=123|field2=456
            page_data = None
            page_path_to_download = page_path
            if "`" in page_path:
                page_path_parts = page_path.split("`")
                page_path_to_download = page_path_parts[0]
                page_data = self.convert_nomadnet_string_data_to_map(page_path_parts[1])

            # Field data
            field_data = self.convert_nomadnet_field_data_to_map(field_data)

            # Combine page data and field data
            if page_data is not None:
                combined_data.update(page_data)
            if field_data is not None:
                combined_data.update(field_data)


            # convert destination hash to bytes
            destination_hash = bytes.fromhex(destination_hash)


            # handle successful page download
            def on_page_download_success(page_content):
                AsyncUtils.run_async(client.send_str(json.dumps({
                    "type": "nomadnet.page.download",
                    "nomadnet_page_download": {
                        "status": "success",
                        "destination_hash": destination_hash.hex(),
                        "page_path": page_path,
                        "page_content": page_content,
                    },
                })))

            # handle page download failure
            def on_page_download_failure(failure_reason):
                AsyncUtils.run_async(client.send_str(json.dumps({
                    "type": "nomadnet.page.download",
                    "nomadnet_page_download": {
                        "status": "failure",
                        "failure_reason": failure_reason,
                        "destination_hash": destination_hash.hex(),
                        "page_path": page_path,
                    },
                })))

            # handle page download progress
            def on_page_download_progress(progress):
                AsyncUtils.run_async(client.send_str(json.dumps({
                    "type": "nomadnet.page.download",
                    "nomadnet_page_download": {
                        "status": "progress",
                        "progress": progress,
                        "destination_hash": destination_hash.hex(),
                        "page_path": page_path,
                    },
                })))

            # download the page
            downloader = NomadnetPageDownloader(destination_hash, page_path_to_download, combined_data, on_page_download_success, on_page_download_failure, on_page_download_progress)
            AsyncUtils.run_async(downloader.download())

        # unhandled type
        else:
            print("unhandled client message type: " + _type)

    # broadcast provided data to all connected websocket clients
    async def websocket_broadcast(self, data):
        for websocket_client in self.websocket_clients:
            try:
                await websocket_client.send_str(data)
            except:
                # do nothing if failed to broadcast to a specific websocket client
                pass

    # broadcasts config to all websocket clients
    async def send_config_to_websocket_clients(self):
        await self.websocket_broadcast(json.dumps({
            "type": "config",
            "config": self.get_config_dict(),
        }))

    # broadcasts to all websocket clients that we just announced
    async def send_announced_to_websocket_clients(self):
        await self.websocket_broadcast(json.dumps({
            "type": "announced",
        }))

    # returns a dictionary of config
    def get_config_dict(self):
        return {
            "display_name": self.config.display_name.get(),
            "identity_hash": self.identity.hexhash,
            "lxmf_address_hash": self.local_lxmf_destination.hexhash,
            "audio_call_address_hash": self.audio_call_manager.audio_call_receiver.destination.hexhash,
            "is_transport_enabled": self.reticulum.transport_enabled(),
            "auto_announce_enabled": self.config.auto_announce_enabled.get(),
            "auto_announce_interval_seconds": self.config.auto_announce_interval_seconds.get(),
            "last_announced_at": self.config.last_announced_at.get(),
            "theme": self.config.theme.get(),
            "message_alert_enabled": self.config.message_alert_enabled.get(),
            "path_request_on_send_failure_enabled": self.config.path_request_on_send_failure_enabled.get(),
            "auto_resend_failed_messages_when_announce_received": self.config.auto_resend_failed_messages_when_announce_received.get(),
            "allow_auto_resending_failed_messages_with_attachments": self.config.allow_auto_resending_failed_messages_with_attachments.get(),
            "auto_send_failed_messages_to_propagation_node": self.config.auto_send_failed_messages_to_propagation_node.get(),
            "show_suggested_community_interfaces": self.config.show_suggested_community_interfaces.get(),
            "lxmf_local_propagation_node_enabled": self.config.lxmf_local_propagation_node_enabled.get(),
            "lxmf_local_propagation_node_address_hash": self.message_router.propagation_destination.hexhash,
            "lxmf_preferred_propagation_node_destination_hash": self.config.lxmf_preferred_propagation_node_destination_hash.get(),
            "auto_select_propagation_node": self.config.auto_select_propagation_node.get(),
            "lxmf_preferred_propagation_node_auto_sync_interval_seconds": self.config.lxmf_preferred_propagation_node_auto_sync_interval_seconds.get(),
            "lxmf_preferred_propagation_node_last_synced_at": self.config.lxmf_preferred_propagation_node_last_synced_at.get(),
            "lxmf_user_icon_name": self.config.lxmf_user_icon_name.get(),
            "lxmf_user_icon_foreground_colour": self.config.lxmf_user_icon_foreground_colour.get(),
            "lxmf_user_icon_background_colour": self.config.lxmf_user_icon_background_colour.get(),
        }

    # convert audio call to dict
    def convert_audio_call_to_dict(self, audio_call: AudioCall):

        # get remote identity hash
        remote_identity_hash = None
        remote_identity = audio_call.get_remote_identity()
        if remote_identity is not None:
            remote_identity_hash = remote_identity.hash.hex()

        # get remote destination hash
        # we need to know the remote identity to determine their destination hash
        remote_destination_hash = None
        remote_destination_hash_hex = None
        if remote_identity is not None:
            remote_destination_hash = RNS.Destination.hash(remote_identity, "call", "audio")
            remote_destination_hash_hex = remote_destination_hash.hex()

        # determine path to remote destination
        path = None
        if remote_destination_hash is not None:

            # determine next hop and hop count
            hops = RNS.Transport.hops_to(remote_destination_hash)
            next_hop_bytes = self.reticulum.get_next_hop(remote_destination_hash)

            # ensure next hop provided
            if next_hop_bytes is not None:
                next_hop = next_hop_bytes.hex()
                next_hop_interface = self.reticulum.get_next_hop_if_name(remote_destination_hash)
                path = {
                    "hops": hops,
                    "next_hop": next_hop,
                    "next_hop_interface": next_hop_interface,
                }

        return {
            "hash": audio_call.link.hash.hex(),
            "remote_destination_hash": remote_destination_hash_hex,
            "remote_identity_hash": remote_identity_hash,
            "is_active": audio_call.is_active(),
            "is_outbound": audio_call.is_outbound,
            "path": path,
        }

    # convert an lxmf message to a dictionary, for sending over websocket
    def convert_lxmf_message_to_dict(self, lxmf_message: LXMF.LXMessage):

        # handle fields
        fields = {}
        message_fields = lxmf_message.get_fields()
        for field_type in message_fields:

            value = message_fields[field_type]

            # handle file attachments field
            if field_type == LXMF.FIELD_FILE_ATTACHMENTS:

                # process file attachments
                file_attachments = []
                for file_attachment in value:
                    file_name = file_attachment[0]
                    file_bytes = base64.b64encode(file_attachment[1]).decode("utf-8")
                    file_attachments.append({
                        "file_name": file_name,
                        "file_bytes": file_bytes,
                    })

                # add to fields
                fields["file_attachments"] = file_attachments

            # handle image field
            if field_type == LXMF.FIELD_IMAGE:
                image_type = value[0]
                image_bytes = base64.b64encode(value[1]).decode("utf-8")
                fields["image"] = {
                    "image_type": image_type,
                    "image_bytes": image_bytes,
                }

            # handle audio field
            if field_type == LXMF.FIELD_AUDIO:
                audio_mode = value[0]
                audio_bytes = base64.b64encode(value[1]).decode("utf-8")
                fields["audio"] = {
                    "audio_mode": audio_mode,
                    "audio_bytes": audio_bytes,
                }

        # convert 0.0-1.0 progress to 0.00-100 percentage
        progress_percentage = round(lxmf_message.progress * 100, 2)

        # get rssi
        rssi = lxmf_message.rssi
        if rssi is None:
            rssi = self.reticulum.get_packet_rssi(lxmf_message.hash)

        # get snr
        snr = lxmf_message.snr
        if snr is None:
            snr = self.reticulum.get_packet_snr(lxmf_message.hash)

        # get quality
        quality = lxmf_message.q
        if quality is None:
            quality = self.reticulum.get_packet_q(lxmf_message.hash)

        return {
            "hash": lxmf_message.hash.hex(),
            "source_hash": lxmf_message.source_hash.hex(),
            "destination_hash": lxmf_message.destination_hash.hex(),
            "is_incoming": lxmf_message.incoming,
            "state": self.convert_lxmf_state_to_string(lxmf_message),
            "progress": progress_percentage,
            "method": self.convert_lxmf_method_to_string(lxmf_message),
            "delivery_attempts": lxmf_message.delivery_attempts,
            "next_delivery_attempt_at": getattr(lxmf_message, "next_delivery_attempt", None),  # attribute may not exist yet
            "title": lxmf_message.title.decode('utf-8'),
            "content": lxmf_message.content.decode('utf-8'),
            "fields": fields,
            "timestamp": lxmf_message.timestamp,
            "rssi": rssi,
            "snr": snr,
            "quality": quality,
        }

    # convert lxmf state to a human friendly string
    def convert_lxmf_state_to_string(self, lxmf_message: LXMF.LXMessage):

        # convert state to string
        lxmf_message_state = "unknown"
        if lxmf_message.state == LXMF.LXMessage.GENERATING:
            lxmf_message_state = "generating"
        elif lxmf_message.state == LXMF.LXMessage.OUTBOUND:
            lxmf_message_state = "outbound"
        elif lxmf_message.state == LXMF.LXMessage.SENDING:
            lxmf_message_state = "sending"
        elif lxmf_message.state == LXMF.LXMessage.SENT:
            lxmf_message_state = "sent"
        elif lxmf_message.state == LXMF.LXMessage.DELIVERED:
            lxmf_message_state = "delivered"
        elif lxmf_message.state == LXMF.LXMessage.REJECTED:
            lxmf_message_state = "rejected"
        elif lxmf_message.state == LXMF.LXMessage.CANCELLED:
            lxmf_message_state = "cancelled"
        elif lxmf_message.state == LXMF.LXMessage.FAILED:
            lxmf_message_state = "failed"

        return lxmf_message_state

    # convert lxmf method to a human friendly string
    def convert_lxmf_method_to_string(self, lxmf_message: LXMF.LXMessage):

        # convert method to string
        lxmf_message_method = "unknown"
        if lxmf_message.method == LXMF.LXMessage.OPPORTUNISTIC:
            lxmf_message_method = "opportunistic"
        elif lxmf_message.method == LXMF.LXMessage.DIRECT:
            lxmf_message_method = "direct"
        elif lxmf_message.method == LXMF.LXMessage.PROPAGATED:
            lxmf_message_method = "propagated"
        elif lxmf_message.method == LXMF.LXMessage.PAPER:
            lxmf_message_method = "paper"

        return lxmf_message_method

    def convert_propagation_node_state_to_string(self, state):

        # map states to strings
        state_map = {
            LXMRouter.PR_IDLE: "idle",
            LXMRouter.PR_PATH_REQUESTED: "path_requested",
            LXMRouter.PR_LINK_ESTABLISHING: "link_establishing",
            LXMRouter.PR_LINK_ESTABLISHED: "link_established",
            LXMRouter.PR_REQUEST_SENT: "request_sent",
            LXMRouter.PR_RECEIVING: "receiving",
            LXMRouter.PR_RESPONSE_RECEIVED: "response_received",
            LXMRouter.PR_COMPLETE: "complete",
            LXMRouter.PR_NO_PATH: "no_path",
            LXMRouter.PR_LINK_FAILED: "link_failed",
            LXMRouter.PR_TRANSFER_FAILED: "transfer_failed",
            LXMRouter.PR_NO_IDENTITY_RCVD: "no_identity_received",
            LXMRouter.PR_NO_ACCESS: "no_access",
            LXMRouter.PR_FAILED: "failed",
        }

        # return string for state, or fallback to unknown
        if state in state_map:
            return state_map[state]
        else:
            return "unknown"

    # convert database announce to a dictionary
    def convert_db_announce_to_dict(self, announce: database.Announce):

        # parse display name from announce
        display_name = None
        if announce.aspect == "lxmf.delivery":
            display_name = self.parse_lxmf_display_name(announce.app_data)
        elif announce.aspect == "nomadnetwork.node":
            display_name = self.parse_nomadnetwork_node_display_name(announce.app_data)

        # find lxmf user icon from database
        lxmf_user_icon = None
        db_lxmf_user_icon = database.LxmfUserIcon.get_or_none(database.LxmfUserIcon.destination_hash == announce.destination_hash)
        if db_lxmf_user_icon is not None:
            lxmf_user_icon = {
                "icon_name": db_lxmf_user_icon.icon_name,
                "foreground_colour": db_lxmf_user_icon.foreground_colour,
                "background_colour": db_lxmf_user_icon.background_colour,
            }

        # get current hops away
        hops = RNS.Transport.hops_to(bytes.fromhex(announce.destination_hash))

        return {
            "id": announce.id,
            "destination_hash": announce.destination_hash,
            "aspect": announce.aspect,
            "identity_hash": announce.identity_hash,
            "identity_public_key": announce.identity_public_key,
            "app_data": announce.app_data,
            "hops": hops,
            "rssi": announce.rssi,
            "snr": announce.snr,
            "quality": announce.quality,
            "display_name": display_name,
            "custom_display_name": self.get_custom_destination_display_name(announce.destination_hash),
            "lxmf_user_icon": lxmf_user_icon,
            "created_at": announce.created_at,
            "updated_at": announce.updated_at,
        }

    # convert database favourite to a dictionary
    def convert_db_favourite_to_dict(self, favourite: database.FavouriteDestination):
        return {
            "id": favourite.id,
            "destination_hash": favourite.destination_hash,
            "display_name": favourite.display_name,
            "aspect": favourite.aspect,
            "created_at": favourite.created_at,
            "updated_at": favourite.updated_at,
        }

    # convert database lxmf message to a dictionary
    def convert_db_lxmf_message_to_dict(self, db_lxmf_message: database.LxmfMessage):

        return {
            "id": db_lxmf_message.id,
            "hash": db_lxmf_message.hash,
            "source_hash": db_lxmf_message.source_hash,
            "destination_hash": db_lxmf_message.destination_hash,
            "is_incoming": db_lxmf_message.is_incoming,
            "state": db_lxmf_message.state,
            "progress": db_lxmf_message.progress,
            "method": db_lxmf_message.method,
            "delivery_attempts": db_lxmf_message.delivery_attempts,
            "next_delivery_attempt_at": db_lxmf_message.next_delivery_attempt_at,
            "title": db_lxmf_message.title,
            "content": db_lxmf_message.content,
            "fields": json.loads(db_lxmf_message.fields),
            "timestamp": db_lxmf_message.timestamp,
            "rssi": db_lxmf_message.rssi,
            "snr": db_lxmf_message.snr,
            "quality": db_lxmf_message.quality,
            "created_at": db_lxmf_message.created_at,
            "updated_at": db_lxmf_message.updated_at,
        }

    # updates the lxmf user icon for the provided destination hash
    def update_lxmf_user_icon(self, destination_hash: str, icon_name: str, foreground_colour: str, background_colour: str):

        # log
        print(f"updating lxmf user icon for {destination_hash} to icon_name={icon_name}, foreground_colour={foreground_colour}, background_colour={background_colour}")

        # prepare data to insert or update
        data = {
            "destination_hash": destination_hash,
            "icon_name": icon_name,
            "foreground_colour": foreground_colour,
            "background_colour": background_colour,
            "updated_at": datetime.now(timezone.utc),
        }

        # upsert to database
        query = database.LxmfUserIcon.insert(data)
        query = query.on_conflict(conflict_target=[database.LxmfUserIcon.destination_hash], update=data)
        query.execute()

    # handle an lxmf delivery from reticulum
    # NOTE: cant be async, as Reticulum doesn't await it
    def on_lxmf_delivery(self, lxmf_message: LXMF.LXMessage):
        try:

            # check if this lxmf message contains a telemetry request command from sideband
            is_sideband_telemetry_request = False
            lxmf_fields = lxmf_message.get_fields()
            if LXMF.FIELD_COMMANDS in lxmf_fields:
                for command in lxmf_fields[LXMF.FIELD_COMMANDS]:
                    if SidebandCommands.TELEMETRY_REQUEST in command:
                        is_sideband_telemetry_request = True

            # ignore telemetry requests from sideband
            if is_sideband_telemetry_request:
                print("Ignoring received LXMF message as it is a telemetry request command")
                return

            # upsert lxmf message to database
            self.db_upsert_lxmf_message(lxmf_message)

            # update lxmf user icon if icon appearance field is available
            try:
                message_fields = lxmf_message.get_fields()
                if LXMF.FIELD_ICON_APPEARANCE in message_fields:
                    icon_appearance = message_fields[LXMF.FIELD_ICON_APPEARANCE]
                    icon_name = icon_appearance[0]
                    foreground_colour = "#" + icon_appearance[1].hex()
                    background_colour = "#" + icon_appearance[2].hex()
                    self.update_lxmf_user_icon(lxmf_message.source_hash.hex(), icon_name, foreground_colour, background_colour)
            except Exception as e:
                print("failed to update lxmf user icon from lxmf message")
                print(e)
                pass

            # find message from database
            db_lxmf_message = database.LxmfMessage.get_or_none(database.LxmfMessage.hash == lxmf_message.hash.hex())
            if db_lxmf_message is None:
                return

            # send received lxmf message data to all websocket clients
            AsyncUtils.run_async(self.websocket_broadcast(json.dumps({
                "type": "lxmf.delivery",
                "lxmf_message": self.convert_db_lxmf_message_to_dict(db_lxmf_message),
            })))

        except Exception as e:
            # do nothing on error
            print("lxmf_delivery error: {}".format(e))

    # handle delivery status update for an outbound lxmf message
    def on_lxmf_sending_state_updated(self, lxmf_message):

        # LCS: this destination is reachable again, so give it a fresh set of
        # path-request attempts next time it breaks
        if lxmf_message.state in [LXMF.LXMessage.DELIVERED, LXMF.LXMessage.SENT]:
            self.clear_path_request_attempts(lxmf_message.destination_hash.hex())

        # upsert lxmf message to database
        self.db_upsert_lxmf_message(lxmf_message)

        # send lxmf message state to all websocket clients
        AsyncUtils.run_async(self.websocket_broadcast(json.dumps({
            "type": "lxmf_message_state_updated",
            "lxmf_message": self.convert_lxmf_message_to_dict(lxmf_message),
        })))

    # handle delivery failed for an outbound lxmf message
    def on_lxmf_sending_failed(self, lxmf_message):

        if lxmf_message.state == LXMF.LXMessage.FAILED:

            # does this message have a propagation node to fall back to
            wants_propagation = bool(getattr(lxmf_message, "try_propagation_on_fail", False))

            # LCS: a propagated message that failed did so because the propagation
            # node could not be reached, not the recipient, and LXMF already
            # requests a path to its own propagation node and retries
            # (LXMRouter.process_outbound, MAX_DELIVERY_ATTEMPTS attempts spaced by
            # PATH_REQUEST_WAIT). Asking for a path to the recipient here would be
            # aimed at the wrong destination, and retrying would only repeat the
            # propagation attempt, since the delivery method is unchanged.
            already_propagated = getattr(lxmf_message, "desired_method", None) == LXMF.LXMessage.PROPAGATED

            # LCS: try to recover a direct route first. Direct delivery is better
            # than propagation when it is achievable -- lower latency, and the
            # message is not left sitting on a third party's node -- so propagation
            # is kept as the fallback it is meant to be.
            #
            # Reticulum only learns a route when something asks or the peer
            # announces, so without this a message that failed on a stale path sits
            # failed until that peer announces again.
            if self.config.path_request_on_send_failure_enabled.get() and not already_propagated:
                self.queue_failed_message_for_path_request(lxmf_message, wants_propagation)

            # path requests turned off, so behave as before
            elif wants_propagation:
                self.send_failed_message_via_propagation_node(lxmf_message)

        # update state
        self.on_lxmf_sending_state_updated(lxmf_message)

    # LCS: how hard to try recovering a route after a send failure.
    PATH_REQUEST_COOLDOWN_SECONDS = 60      # minimum gap between attempts per destination
    PATH_REQUEST_MAX_ATTEMPTS = 3           # attempts before leaving it to an announce
    PATH_REQUEST_TIMEOUT_SECONDS = 15       # how long to wait for a path response
    PATH_REQUEST_RESET_SECONDS = 1800       # quiet period after which the count restarts
    PATH_REQUEST_MAX_PENDING = 100          # per destination, so a backlog cannot grow without bound

    # LCS: decide whether a destination is due another path request.
    #
    # Pure and side effect free so it can be tested directly -- getting this wrong
    # either strands failed messages or floods a slow link, and a resend produces
    # one failure callback per message, so the throttling has to hold.
    #
    # Returns (allowed, attempt), where attempt is the record to store when allowed.
    @classmethod
    def next_path_request_attempt(cls, attempt, now):

        attempt = attempt or {"at": 0, "count": 0}

        # a long quiet spell means whatever went wrong before is not what is going
        # wrong now, so start counting again
        if now - attempt["at"] > cls.PATH_REQUEST_RESET_SECONDS:
            attempt = {"at": 0, "count": 0}

        # one resend produces several failures in a row, one per message; only the
        # first should reach the network
        if now - attempt["at"] < cls.PATH_REQUEST_COOLDOWN_SECONDS:
            return False, attempt

        # stop asking. An incoming announce still triggers the existing resend, so
        # the messages are not stranded, they just stop costing airtime.
        if attempt["count"] >= cls.PATH_REQUEST_MAX_ATTEMPTS:
            return False, attempt

        return True, {"at": now, "count": attempt["count"] + 1}

    # LCS: hold a failed message until we know whether a route can be recovered.
    #
    # A single destination going unreachable fails every queued message for it, one
    # callback each. They are collected per destination and resolved together by one
    # path request, so the network is asked once and no message is either sent twice
    # or dropped.
    def queue_failed_message_for_path_request(self, lxmf_message, wants_propagation: bool):

        destination_hash = lxmf_message.destination_hash.hex()
        pending = self.pending_path_requests.setdefault(destination_hash, [])

        if len(pending) < self.PATH_REQUEST_MAX_PENDING:
            pending.append((lxmf_message, wants_propagation))
        elif wants_propagation:
            # the queue is full, so this one goes straight to its fallback rather
            # than being silently forgotten
            self.send_failed_message_via_propagation_node(lxmf_message)
            return

        # a request for this destination is already in flight; its result will
        # resolve everything queued above
        if destination_hash in self.path_requests_in_flight:
            return

        now = time.time()
        allowed, attempt = self.next_path_request_attempt(
            self.path_request_attempts.get(destination_hash), now,
        )

        if not allowed:
            # not asking again yet, so resolve what is queued using the fallback
            self.resolve_pending_path_request(destination_hash, path_found=False)
            return

        self.path_request_attempts[destination_hash] = attempt
        self.path_requests_in_flight.add(destination_hash)
        AsyncUtils.run_async(self.request_path_for_failed_messages(destination_hash, attempt))

    # LCS: ask the network for a route to a destination whose sends just failed,
    # then resolve everything queued for it.
    async def request_path_for_failed_messages(self, destination_hash: str, attempt: dict):

        path_found = False
        try:
            raw_destination_hash = bytes.fromhex(destination_hash)

            # Asked for unconditionally, including when a path is already known: a
            # known-but-stale entry is exactly the case this is here to fix, and the
            # response refreshes it.
            RNS.Transport.request_path(raw_destination_hash)
            print("Requesting path to {} after a send failure (attempt {} of {})".format(
                destination_hash, attempt["count"], self.PATH_REQUEST_MAX_ATTEMPTS,
            ))

            timeout_after_seconds = time.time() + self.PATH_REQUEST_TIMEOUT_SECONDS
            while not RNS.Transport.has_path(raw_destination_hash) and time.time() < timeout_after_seconds:
                await asyncio.sleep(0.25)

            path_found = RNS.Transport.has_path(raw_destination_hash)
            if path_found:
                # give the refreshed entry a moment to settle before using it
                await asyncio.sleep(0.5)
                print("Path to {} found, retrying failed messages".format(destination_hash))
            else:
                print("No path to {} after the request timed out".format(destination_hash))

        except Exception as e:
            # never leave messages stuck in the pending queue on an error
            print("request_path_for_failed_messages error: {}".format(e))

        finally:
            self.path_requests_in_flight.discard(destination_hash)
            try:
                self.resolve_pending_path_request(destination_hash, path_found=path_found)
            except Exception as e:
                print("resolve_pending_path_request error: {}".format(e))

    # LCS: act on the messages queued against a destination.
    #
    # Path found: retry each one on the refreshed route. The same message object is
    # re-sent rather than a copy, so nothing is duplicated, the UI updates in place,
    # and try_propagation_on_fail survives -- if the retry fails too, propagation
    # still happens, which is the whole point of trying direct first.
    #
    # No path: hand each message to its propagation fallback, where it has one.
    def resolve_pending_path_request(self, destination_hash: str, path_found: bool):

        pending = self.pending_path_requests.pop(destination_hash, [])

        for lxmf_message, wants_propagation in pending:
            try:
                if path_found:
                    self.retry_failed_message(lxmf_message)
                elif wants_propagation:
                    self.send_failed_message_via_propagation_node(lxmf_message)
            except Exception as e:
                print("failed to resolve message for {}: {}".format(destination_hash, e))

    # LCS: send a failed message again over whatever route it was using, on the
    # assumption that the route has just changed. Same reset as the propagation
    # fallback does, without changing the delivery method.
    def retry_failed_message(self, lxmf_message: LXMF.LXMessage):

        lxmf_message.packed = None
        lxmf_message.delivery_attempts = 0
        if hasattr(lxmf_message, "next_delivery_attempt"):
            del lxmf_message.next_delivery_attempt

        self.message_router.handle_outbound(lxmf_message)

    # LCS: a destination that is reachable again should get a fresh set of attempts
    # the next time it breaks.
    def clear_path_request_attempts(self, destination_hash: str):
        self.path_request_attempts.pop(destination_hash, None)

    # sends a previously failed message via a propagation node
    def send_failed_message_via_propagation_node(self, lxmf_message: LXMF.LXMessage):

        # reset internal message state
        lxmf_message.packed = None
        lxmf_message.delivery_attempts = 0
        if hasattr(lxmf_message, "next_delivery_attempt"):
            del lxmf_message.next_delivery_attempt

        # this message should now be sent via a propagation node
        lxmf_message.desired_method = LXMF.LXMessage.PROPAGATED
        lxmf_message.try_propagation_on_fail = False

        # resend message
        self.message_router.handle_outbound(lxmf_message)

    # upserts the provided lxmf message to the database
    def db_upsert_lxmf_message(self, lxmf_message: LXMF.LXMessage):

        # convert lxmf message to dict
        lxmf_message_dict = self.convert_lxmf_message_to_dict(lxmf_message)

        # prepare data to insert or update
        data = {
            "hash": lxmf_message_dict["hash"],
            "source_hash": lxmf_message_dict["source_hash"],
            "destination_hash": lxmf_message_dict["destination_hash"],
            "is_incoming": lxmf_message_dict["is_incoming"],
            "state": lxmf_message_dict["state"],
            "progress": lxmf_message_dict["progress"],
            "method": lxmf_message_dict["method"],
            "delivery_attempts": lxmf_message_dict["delivery_attempts"],
            "next_delivery_attempt_at": lxmf_message_dict["next_delivery_attempt_at"],
            "title": lxmf_message_dict["title"],
            "content": lxmf_message_dict["content"],
            "fields": json.dumps(lxmf_message_dict["fields"]),
            "timestamp": lxmf_message_dict["timestamp"],
            "rssi": lxmf_message_dict["rssi"],
            "snr": lxmf_message_dict["snr"],
            "quality": lxmf_message_dict["quality"],
            "updated_at": datetime.now(timezone.utc),
        }

        # upsert to database
        query = database.LxmfMessage.insert(data)
        query = query.on_conflict(conflict_target=[database.LxmfMessage.hash], update=data)
        query.execute()

    # upserts the provided announce to the database
    def db_upsert_announce(self, identity: RNS.Identity, destination_hash: bytes, aspect: str, app_data: bytes, announce_packet_hash: bytes):

        # get rssi, snr and signal quality if available
        rssi = self.reticulum.get_packet_rssi(announce_packet_hash)
        snr = self.reticulum.get_packet_snr(announce_packet_hash)
        quality = self.reticulum.get_packet_q(announce_packet_hash)

        # prepare data to insert or update
        data = {
            "destination_hash": destination_hash.hex(),
            "aspect": aspect,
            "identity_hash": identity.hash.hex(),
            "identity_public_key": base64.b64encode(identity.get_public_key()).decode("utf-8"),
            "rssi": rssi,
            "snr": snr,
            "quality": quality,
            "updated_at": datetime.now(timezone.utc),
        }

        # only set app data if provided, as we don't want to wipe existing data when we request keys from the network
        if app_data is not None:
            # save app data as base64 string
            data["app_data"] = base64.b64encode(app_data).decode("utf-8")

        # upsert to database
        query = database.Announce.insert(data)
        query = query.on_conflict(conflict_target=[database.Announce.destination_hash], update=data)
        query.execute()

    # upserts a custom destination display name to the database
    def db_upsert_custom_destination_display_name(self, destination_hash: str, display_name: str):

        # prepare data to insert or update
        data = {
            "destination_hash": destination_hash,
            "display_name": display_name,
            "updated_at": datetime.now(timezone.utc),
        }

        # upsert to database
        query = database.CustomDestinationDisplayName.insert(data)
        query = query.on_conflict(conflict_target=[database.CustomDestinationDisplayName.destination_hash], update=data)
        query.execute()

    # upserts a custom destination display name to the database
    def db_upsert_favourite(self, destination_hash: str, display_name: str, aspect: str):

        # prepare data to insert or update
        data = {
            "destination_hash": destination_hash,
            "display_name": display_name,
            "aspect": aspect,
            "updated_at": datetime.now(timezone.utc),
        }

        # upsert to database
        query = database.FavouriteDestination.insert(data)
        query = query.on_conflict(conflict_target=[database.FavouriteDestination.destination_hash], update=data)
        query.execute()

    # upserts lxmf conversation read state to the database
    def db_mark_lxmf_conversation_as_read(self, destination_hash: str):

        # prepare data to insert or update
        data = {
            "destination_hash": destination_hash,
            "last_read_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        # upsert to database
        query = database.LxmfConversationReadState.insert(data)
        query = query.on_conflict(conflict_target=[database.LxmfConversationReadState.destination_hash], update=data)
        query.execute()

    # handle sending an lxmf message to reticulum
    async def send_message(self, destination_hash: str, content: str,
                           image_field: LxmfImageField = None,
                           audio_field: LxmfAudioField = None,
                           file_attachments_field: LxmfFileAttachmentsField = None,
                           delivery_method: str = None) -> LXMF.LXMessage:

        # convert destination hash to bytes
        destination_hash = bytes.fromhex(destination_hash)

        # determine when to timeout finding path
        timeout_after_seconds = time.time() + 10

        # check if we have a path to the destination
        if not RNS.Transport.has_path(destination_hash):

            # we don't have a path, so we need to request it
            RNS.Transport.request_path(destination_hash)

            # wait until we have a path, or give up after the configured timeout
            while not RNS.Transport.has_path(destination_hash) and time.time() < timeout_after_seconds:
                await asyncio.sleep(0.1)

        # find destination identity from hash
        destination_identity = RNS.Identity.recall(destination_hash)
        if destination_identity is None:

            # we have to bail out of sending, since we don't have the identity/path yet
            raise Exception("Could not find path to destination. Try again later.")

        # create destination for recipients lxmf delivery address
        lxmf_destination = RNS.Destination(destination_identity, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery")

        # determine how the user wants to send the message
        desired_delivery_method = None
        if delivery_method == "direct":
            desired_delivery_method = LXMF.LXMessage.DIRECT
        elif delivery_method == "opportunistic":
            desired_delivery_method = LXMF.LXMessage.OPPORTUNISTIC
        elif delivery_method == "propagated":
            desired_delivery_method = LXMF.LXMessage.PROPAGATED

        # determine how to send the message if the user didn't provide a method
        if desired_delivery_method is None:

            # send messages over a direct link by default
            desired_delivery_method = LXMF.LXMessage.DIRECT
            if not self.message_router.delivery_link_available(destination_hash) and RNS.Identity.current_ratchet_id(destination_hash) != None:

                # since there's no link established to the destination, it's faster to send opportunistically
                # this is because it takes several packets to establish a link, and then we still have to send the message over it
                # oppotunistic mode will send the message in a single packet (if the message is small enough, otherwise it falls back to a direct link)
                # we will only do this if an encryption ratchet is available, so single packet delivery is more secure
                desired_delivery_method = LXMF.LXMessage.OPPORTUNISTIC

        # create lxmf message
        lxmf_message = LXMF.LXMessage(lxmf_destination, self.local_lxmf_destination, content, desired_method=desired_delivery_method)
        lxmf_message.try_propagation_on_fail = self.config.auto_send_failed_messages_to_propagation_node.get()

        lxmf_message.fields = {}

        # add file attachments field
        if file_attachments_field is not None:

            # create array of [[file_name, file_bytes], [file_name, file_bytes], ...]
            file_attachments = []
            for file_attachment in file_attachments_field.file_attachments:
                file_attachments.append([file_attachment.file_name, file_attachment.file_bytes])

            # set field attachments field
            lxmf_message.fields[LXMF.FIELD_FILE_ATTACHMENTS] = file_attachments

        # add image field
        if image_field is not None:
            lxmf_message.fields[LXMF.FIELD_IMAGE] = [
                image_field.image_type,
                image_field.image_bytes,
            ]

        # add audio field
        if audio_field is not None:
            lxmf_message.fields[LXMF.FIELD_AUDIO] = [
                audio_field.audio_mode,
                audio_field.audio_bytes,
            ]

        # add icon appearance if configured
        # fixme: we could save a tiny amount of bandwidth here, but this requires more effort...
        # we could keep track of when the icon appearance was last sent to this destination, and when it last changed
        # we could save 6 bytes for the 2x colours, and also however long the icon name is, but not today!
        lxmf_user_icon_name = self.config.lxmf_user_icon_name.get()
        lxmf_user_icon_foreground_colour = self.config.lxmf_user_icon_foreground_colour.get()
        lxmf_user_icon_background_colour = self.config.lxmf_user_icon_background_colour.get()
        if (lxmf_user_icon_name is not None
                and lxmf_user_icon_foreground_colour is not None
                and lxmf_user_icon_background_colour is not None):
            lxmf_message.fields[LXMF.FIELD_ICON_APPEARANCE] = [
                lxmf_user_icon_name,
                ColourUtils.hex_colour_to_byte_array(lxmf_user_icon_foreground_colour),
                ColourUtils.hex_colour_to_byte_array(lxmf_user_icon_background_colour),
            ]

        # register delivery callbacks
        lxmf_message.register_delivery_callback(self.on_lxmf_sending_state_updated)
        lxmf_message.register_failed_callback(self.on_lxmf_sending_failed)

        # send lxmf message to be routed to destination
        self.message_router.handle_outbound(lxmf_message)

        # upsert lxmf message to database
        self.db_upsert_lxmf_message(lxmf_message)

        # tell all websocket clients that old failed message was deleted so it can remove from ui
        await self.websocket_broadcast(json.dumps({
            "type": "lxmf_message_created",
            "lxmf_message": self.convert_lxmf_message_to_dict(lxmf_message),
        }))

        # handle lxmf message progress loop without blocking or awaiting
        # otherwise other incoming websocket packets will not be processed until sending is complete
        # which results in the next message not showing up until the first message is finished
        AsyncUtils.run_async(self.handle_lxmf_message_progress(lxmf_message))

        return lxmf_message

    # updates lxmf message in database and broadcasts to websocket until it's delivered, or it fails
    async def handle_lxmf_message_progress(self, lxmf_message):

        # FIXME: there's no register_progress_callback on the lxmf message, so manually send progress until delivered, propagated or failed
        # we also can't use on_lxmf_sending_state_updated method to do this, because of async/await issues...
        should_update_message = True
        while should_update_message:

            # wait 1 second between sending updates
            await asyncio.sleep(1)

            # upsert lxmf message to database (as we want to update the progress in database too)
            self.db_upsert_lxmf_message(lxmf_message)

            # send update to websocket clients
            await self.websocket_broadcast(json.dumps({
                "type": "lxmf_message_state_updated",
                "lxmf_message": self.convert_lxmf_message_to_dict(lxmf_message),
            }))

            # check message state
            has_delivered = lxmf_message.state == LXMF.LXMessage.DELIVERED
            has_propagated = lxmf_message.state == LXMF.LXMessage.SENT and lxmf_message.method == LXMF.LXMessage.PROPAGATED
            has_failed = lxmf_message.state == LXMF.LXMessage.FAILED
            is_cancelled = lxmf_message.state == LXMF.LXMessage.CANCELLED

            # check if we should stop updating
            if has_delivered or has_propagated or has_failed or is_cancelled:
                should_update_message = False

    # handle an announce received from reticulum, for an audio call address
    # NOTE: cant be async, as Reticulum doesn't await it
    def on_audio_call_announce_received(self, aspect, destination_hash, announced_identity, app_data, announce_packet_hash):

        # log received announce
        print("Received an announce from " + RNS.prettyhexrep(destination_hash) + " for [call.audio]")

        # upsert announce to database
        self.db_upsert_announce(announced_identity, destination_hash, aspect, app_data, announce_packet_hash)

        # find announce from database
        announce = database.Announce.get_or_none(database.Announce.destination_hash == destination_hash.hex())
        if announce is None:
            return

        # send database announce to all websocket clients
        AsyncUtils.run_async(self.websocket_broadcast(json.dumps({
            "type": "announce",
            "announce": self.convert_db_announce_to_dict(announce),
        })))

    # handle an announce received from reticulum, for an lxmf address
    # NOTE: cant be async, as Reticulum doesn't await it
    def on_lxmf_announce_received(self, aspect, destination_hash, announced_identity, app_data, announce_packet_hash):

        # log received announce
        print("Received an announce from " + RNS.prettyhexrep(destination_hash) + " for [lxmf.delivery]")

        # upsert announce to database
        self.db_upsert_announce(announced_identity, destination_hash, aspect, app_data, announce_packet_hash)

        # find announce from database
        announce = database.Announce.get_or_none(database.Announce.destination_hash == destination_hash.hex())
        if announce is None:
            return

        # send database announce to all websocket clients
        AsyncUtils.run_async(self.websocket_broadcast(json.dumps({
            "type": "announce",
            "announce": self.convert_db_announce_to_dict(announce),
        })))

        # LCS: the peer is clearly reachable, so stop rationing path requests to it
        self.clear_path_request_attempts(destination_hash.hex())

        # resend all failed messages that were intended for this destination
        if self.config.auto_resend_failed_messages_when_announce_received.get():
            AsyncUtils.run_async(self.resend_failed_messages_for_destination(destination_hash.hex()))

    # handle an announce received from reticulum, for an lxmf propagation node address
    # NOTE: cant be async, as Reticulum doesn't await it
    def on_lxmf_propagation_announce_received(self, aspect, destination_hash, announced_identity, app_data, announce_packet_hash):

        # log received announce
        print("Received an announce from " + RNS.prettyhexrep(destination_hash) + " for [lxmf.propagation]")

        # upsert announce to database
        self.db_upsert_announce(announced_identity, destination_hash, aspect, app_data, announce_packet_hash)

        # LCS: auto-select a propagation node if the user hasn't set one yet.
        # adopts the first discovered lxmf.propagation node, then stops (won't override
        # a node the user later chooses). controlled by auto_select_propagation_node.
        try:
            if self.config.auto_select_propagation_node.get():
                current = self.config.lxmf_preferred_propagation_node_destination_hash.get()
                if current is None or current == "":
                    node_hash = destination_hash.hex()
                    self.config.lxmf_preferred_propagation_node_destination_hash.set(node_hash)
                    self.set_active_propagation_node(node_hash)
                    RNS.log(f"LCS: auto-selected preferred propagation node {node_hash}", RNS.LOG_NOTICE)
        except Exception as e:
            RNS.log(f"LCS: auto-select propagation node failed: {e}", RNS.LOG_DEBUG)

        # find announce from database
        announce = database.Announce.get_or_none(database.Announce.destination_hash == destination_hash.hex())
        if announce is None:
            return

        # send database announce to all websocket clients
        AsyncUtils.run_async(self.websocket_broadcast(json.dumps({
            "type": "announce",
            "announce": self.convert_db_announce_to_dict(announce),
        })))

    # resends all messages that previously failed to send to the provided destination hash
    async def resend_failed_messages_for_destination(self, destination_hash: str):

        # get messages that failed to send to this destination
        failed_messages = (database.LxmfMessage.select()
                           .where(database.LxmfMessage.state == "failed")
                           .where(database.LxmfMessage.destination_hash == destination_hash)
                           .order_by(database.LxmfMessage.id.asc()))

        # resend failed messages
        for failed_message in failed_messages:
            try:

                # parse fields as json
                fields = json.loads(failed_message.fields)

                # parse image field
                image_field = None
                if "image" in fields:
                    image_field = LxmfImageField(fields["image"]["image_type"], base64.b64decode(fields["image"]["image_bytes"]))

                # parse audio field
                audio_field = None
                if "audio" in fields:
                    audio_field = LxmfAudioField(fields["audio"]["audio_mode"], base64.b64decode(fields["audio"]["audio_bytes"]))

                # parse file attachments field
                file_attachments_field = None
                if "file_attachments" in fields:
                    file_attachments = []
                    for file_attachment in fields["file_attachments"]:
                        file_attachments.append(LxmfFileAttachment(file_attachment["file_name"], base64.b64decode(file_attachment["file_bytes"])))
                    file_attachments_field = LxmfFileAttachmentsField(file_attachments)

                # don't resend message with attachments if not allowed
                if not self.config.allow_auto_resending_failed_messages_with_attachments.get():
                    if image_field is not None or audio_field is not None or file_attachments_field is not None:
                        print("Not resending failed message with attachments, as setting is disabled")
                        continue

                # send new message with failed message content
                await self.send_message(
                    failed_message.destination_hash,
                    failed_message.content,
                    image_field,
                    audio_field,
                    file_attachments_field,
                )

                # remove original failed message from database
                database.LxmfMessage.delete().where((database.LxmfMessage.hash == failed_message.hash)).execute()

                # tell all websocket clients that old failed message was deleted so it can remove from ui
                await self.websocket_broadcast(json.dumps({
                    "type": "lxmf_message_deleted",
                    "hash": failed_message.hash,
                }))

            except Exception as e:
                print("Error resending failed message: " + str(e))
                pass


    # handle an announce received from reticulum, for a nomadnet node
    # NOTE: cant be async, as Reticulum doesn't await it
    def on_nomadnet_node_announce_received(self, aspect, destination_hash, announced_identity, app_data, announce_packet_hash):

        # log received announce
        print("Received an announce from " + RNS.prettyhexrep(destination_hash) + " for [nomadnetwork.node]")

        # upsert announce to database
        self.db_upsert_announce(announced_identity, destination_hash, aspect, app_data, announce_packet_hash)

        # find announce from database
        announce = database.Announce.get_or_none(database.Announce.destination_hash == destination_hash.hex())
        if announce is None:
            return

        # send database announce to all websocket clients
        AsyncUtils.run_async(self.websocket_broadcast(json.dumps({
            "type": "announce",
            "announce": self.convert_db_announce_to_dict(announce),
        })))

    # try and get a name for the provided identity hash
    def get_name_for_identity_hash(self, identity_hash: str):

        # recall identity
        identity = RNS.Identity.recall(bytes.fromhex(identity_hash), from_identity_hash=True)
        if identity is None:
            return None

        # get lxmf.delivery destination hash
        lxmf_destination_hash = RNS.Destination.hash(identity, "lxmf", "delivery").hex()

        # use custom name if available
        custom_name = self.get_custom_destination_display_name(lxmf_destination_hash)
        if custom_name is not None:
            return custom_name

        # use lxmf name if available
        lxmf_name = self.get_lxmf_conversation_name(lxmf_destination_hash, default_name=None)
        if lxmf_name is not None:
            return lxmf_name

        # couldn't find a name for this identity
        return None

    # gets the custom display name a user has set for the provided destination hash
    def get_custom_destination_display_name(self, destination_hash: str):

        # get display name from database
        db_destination_display_name = database.CustomDestinationDisplayName.get_or_none(database.CustomDestinationDisplayName.destination_hash == destination_hash)
        if db_destination_display_name is not None:
            return db_destination_display_name.display_name

        return None

    # get name to show for an lxmf conversation
    # currently, this will use the app data from the most recent announce
    # TODO: we should fetch this from our contacts database, when it gets implemented, and if not found, fallback to app data
    def get_lxmf_conversation_name(self, destination_hash, default_name:str|None="Anonymous Peer"):

        # get lxmf.delivery announce from database for the provided destination hash
        lxmf_announce = (database.Announce.select()
                         .where(database.Announce.aspect == "lxmf.delivery")
                         .where(database.Announce.destination_hash == destination_hash)
                         .get_or_none())

        # if app data is available in database, it should be base64 encoded text that was announced
        # we will return the parsed lxmf display name as the conversation name
        if lxmf_announce is not None and lxmf_announce.app_data is not None:
            return self.parse_lxmf_display_name(app_data_base64=lxmf_announce.app_data)

        # announce did not have app data, so provide a fallback name
        return default_name

    # reads the lxmf display name from the provided base64 app data
    def parse_lxmf_display_name(self, app_data_base64: str, default_value: str | None = "Anonymous Peer"):

        try:
            app_data_bytes = base64.b64decode(app_data_base64)
            display_name = LXMF.display_name_from_app_data(app_data_bytes)
            if display_name is not None:
                return display_name
        except:
            pass

        return default_value

    # reads the lxmf stamp cost from the provided base64 app data
    def parse_lxmf_stamp_cost(self, app_data_base64: str):
        try:
            app_data_bytes = base64.b64decode(app_data_base64)
            return LXMF.stamp_cost_from_app_data(app_data_bytes)
        except:
            return None

    # reads the nomadnetwork node display name from the provided base64 app data
    def parse_nomadnetwork_node_display_name(self, app_data_base64: str, default_value: str | None = "Anonymous Node"):
        try:
            app_data_bytes = base64.b64decode(app_data_base64)
            return app_data_bytes.decode("utf-8")
        except:
            return default_value

    # parses lxmf propagation node app data
    def parse_lxmf_propagation_node_app_data(self, app_data_base64: str):
        try:
            app_data_bytes = base64.b64decode(app_data_base64)
            data = msgpack.unpackb(app_data_bytes)
            return {
                "enabled": bool(data[0]),
                "timebase": int(data[1]),
                "per_transfer_limit": int(data[2]),
            }
        except:
            return None

    # returns true if the conversation has messages newer than the last read at timestamp
    def is_lxmf_conversation_unread(self, destination_hash):

        # get lxmf conversation read state from database for the provided destination hash
        lxmf_conversation_read_state = (database.LxmfConversationReadState.select()
                         .where(database.LxmfConversationReadState.destination_hash == destination_hash)
                         .get_or_none())

        # get most recent incoming message from destination hash
        latest_incoming_lxmf_message = (database.LxmfMessage.select()
                        .where(database.LxmfMessage.source_hash == destination_hash)
                        .order_by(database.LxmfMessage.created_at.desc())
                        .get_or_none())

        # there's no incoming message, so it can't be unread
        if latest_incoming_lxmf_message is None:
            return False

        # user has never read this conversation, so it's unread
        if lxmf_conversation_read_state is None:
            return True

        # conversation is unread if last read at is before the latest incoming message creation date
        conversation_last_read_at = datetime.strptime(lxmf_conversation_read_state.last_read_at, "%Y-%m-%d %H:%M:%S.%f%z")
        conversation_latest_message_at = datetime.strptime(latest_incoming_lxmf_message.created_at, "%Y-%m-%d %H:%M:%S.%f%z")
        return conversation_last_read_at < conversation_latest_message_at

    # returns number of messages that failed to send in a conversation
    def lxmf_conversation_failed_messages_count(self, destination_hash: str):
        return (database.LxmfMessage.select()
                .where(database.LxmfMessage.state == "failed")
                .where(database.LxmfMessage.destination_hash == destination_hash)
                .count())

    # find an interface by name
    def find_interface_by_name(self, name: str):
        for interface in RNS.Transport.interfaces:
            interface_name = str(interface)
            if name == interface_name:
                return interface

        return None

# class to manage config stored in database
class Config:

    @staticmethod
    def get(key: str, default_value=None) -> str | None:

        # get config value from database
        config_item = database.Config.get_or_none(database.Config.key == key)

        # return value if available
        if config_item is not None:
            return config_item.value

        # fallback to returning default value
        return default_value

    @staticmethod
    def set(key: str, value: str | None):

        # if none, delete the config entry
        if value is None:
            database.Config.delete().where(database.Config.key == key).execute()
            return

        # prepare data to insert or update
        data = {
            "key": key,
            "value": value,
            "updated_at": datetime.now(timezone.utc),
        }

        # upsert to database
        query = database.Config.insert(data)
        query = query.on_conflict(conflict_target=[database.Config.key], update=data)
        query.execute()

    # handle config values that should be strings
    class StringConfig:

        def __init__(self, key: str, default_value: str | None = None):
            self.key = key
            self.default_value = default_value

        def get(self, default_value: str = None) -> str | None:
            _default_value = default_value or self.default_value
            return Config.get(self.key, default_value=_default_value)

        def set(self, value: str | None):
            Config.set(self.key, value)

    # handle config values that should be bools
    class BoolConfig:

        def __init__(self, key: str, default_value: bool = False):
            self.key = key
            self.default_value = default_value

        def get(self) -> bool:

            # get string value, or return default
            config_value = Config.get(self.key, default_value=None)
            if config_value is None:
                return self.default_value

            return config_value == "true"

        def set(self, value: bool):

            # determine string value for bool
            if value is True:
                config_value = "true"
            else:
                config_value = "false"

            Config.set(self.key, config_value)

    # handle config values that should be integers
    class IntConfig:

        def __init__(self, key: str, default_value: int | None = 0):
            self.key = key
            self.default_value = default_value

        def get(self) -> int | None:

            # get string value, or return default
            config_value = Config.get(self.key, default_value=None)
            if config_value is None:
                return self.default_value

            return int(config_value)

        def set(self, value: int):
            Config.set(self.key, str(value))

    # all possible config items
    database_version = IntConfig("database_version", None)
    display_name = StringConfig("display_name", "Anonymous Peer")
    auto_announce_enabled = BoolConfig("auto_announce_enabled", True)
    auto_announce_interval_seconds = IntConfig("auto_announce_interval_seconds", 21600)
    last_announced_at = IntConfig("last_announced_at", None)
    theme = StringConfig("theme", "light")
    auto_resend_failed_messages_when_announce_received = BoolConfig("auto_resend_failed_messages_when_announce_received", True)
    allow_auto_resending_failed_messages_with_attachments = BoolConfig("allow_auto_resending_failed_messages_with_attachments", True)
    auto_send_failed_messages_to_propagation_node = BoolConfig("auto_send_failed_messages_to_propagation_node", True)
    show_suggested_community_interfaces = BoolConfig("show_suggested_community_interfaces", True)
    lxmf_delivery_transfer_limit_in_bytes = IntConfig("lxmf_delivery_transfer_limit_in_bytes", 1000 * 1000 * 10)  # 10MB
    lxmf_preferred_propagation_node_destination_hash = StringConfig("lxmf_preferred_propagation_node_destination_hash", None)
    auto_select_propagation_node = BoolConfig("auto_select_propagation_node", True)
    lxmf_preferred_propagation_node_auto_sync_interval_seconds = IntConfig("lxmf_preferred_propagation_node_auto_sync_interval_seconds", 21600)
    lxmf_preferred_propagation_node_last_synced_at = IntConfig("lxmf_preferred_propagation_node_last_synced_at", None)
    lxmf_local_propagation_node_enabled = BoolConfig("lxmf_local_propagation_node_enabled", False)
    lxmf_user_icon_name = StringConfig("lxmf_user_icon_name", None)
    lxmf_user_icon_foreground_colour = StringConfig("lxmf_user_icon_foreground_colour", None)
    lxmf_user_icon_background_colour = StringConfig("lxmf_user_icon_background_colour", None)
    telephone_enabled = BoolConfig("telephone_enabled", True)
    message_alert_enabled = BoolConfig("message_alert_enabled", True)
    path_request_on_send_failure_enabled = BoolConfig("path_request_on_send_failure_enabled", True)

# FIXME: we should probably set this as an instance variable of ReticulumMeshChat so it has a proper home, and pass it in to the constructor?
nomadnet_cached_links = {}
class NomadnetDownloader:

    def __init__(self, destination_hash: bytes, path: str, data: str|None, on_download_success: Callable[[RNS.RequestReceipt], None], on_download_failure: Callable[[str], None], on_progress_update: Callable[[float], None], timeout: int|None = None):
        self.app_name = "nomadnetwork"
        self.aspects = "node"
        self.destination_hash = destination_hash
        self.path = path
        self.data = data
        self.timeout = timeout
        self.on_download_success = on_download_success
        self.on_download_failure = on_download_failure
        self.on_progress_update = on_progress_update

    # setup link to destination and request download
    async def download(self, path_lookup_timeout: int = 15, link_establishment_timeout: int = 15):

        # use existing established link if it's active
        if self.destination_hash in nomadnet_cached_links:
            link = nomadnet_cached_links[self.destination_hash]
            if link.status is RNS.Link.ACTIVE:
                print("[NomadnetDownloader] using existing link for request")
                self.link_established(link)
                return

        # determine when to timeout
        timeout_after_seconds = time.time() + path_lookup_timeout

        # check if we have a path to the destination
        if not RNS.Transport.has_path(self.destination_hash):

            # we don't have a path, so we need to request it
            RNS.Transport.request_path(self.destination_hash)

            # wait until we have a path, or give up after the configured timeout
            while not RNS.Transport.has_path(self.destination_hash) and time.time() < timeout_after_seconds:
                await asyncio.sleep(0.1)

        # if we still don't have a path, we can't establish a link, so bail out
        if not RNS.Transport.has_path(self.destination_hash):
            self.on_download_failure("Could not find path to destination.")
            return

        # create destination to nomadnet node
        identity = RNS.Identity.recall(self.destination_hash)
        destination = RNS.Destination(
            identity,
            RNS.Destination.OUT,
            RNS.Destination.SINGLE,
            self.app_name,
            self.aspects,
        )

        # create link to destination
        print("[NomadnetDownloader] establishing new link for request")
        link = RNS.Link(destination, established_callback=self.link_established)

        # determine when to timeout
        timeout_after_seconds = time.time() + link_establishment_timeout

        # wait until we have established a link, or give up after the configured timeout
        while link.status is not RNS.Link.ACTIVE and time.time() < timeout_after_seconds:
            await asyncio.sleep(0.1)

        # if we still haven't established a link, bail out
        if link.status is not RNS.Link.ACTIVE:
            self.on_download_failure("Could not establish link to destination.")

    # link to destination was established, we should now request the download
    def link_established(self, link):

        # cache link for using in future requests
        nomadnet_cached_links[self.destination_hash] = link

        # request download over link
        link.request(
            self.path,
            data=self.data,
            response_callback=self.on_response,
            failed_callback=self.on_failed,
            progress_callback=self.on_progress,
            timeout=self.timeout,
        )

    # handle successful download
    def on_response(self, request_receipt: RNS.RequestReceipt):
        self.on_download_success(request_receipt)

    # handle failure
    def on_failed(self, request_receipt=None):
        self.on_download_failure("request_failed")

    # handle download progress
    def on_progress(self, request_receipt):
        self.on_progress_update(request_receipt.progress)


class NomadnetPageDownloader(NomadnetDownloader):

    def __init__(self, destination_hash: bytes, page_path: str, data: str | None, on_page_download_success: Callable[[str], None], on_page_download_failure: Callable[[str], None], on_progress_update: Callable[[float], None], timeout: int|None = None):
        self.on_page_download_success = on_page_download_success
        self.on_page_download_failure = on_page_download_failure
        super().__init__(destination_hash, page_path, data, self.on_download_success, self.on_download_failure, on_progress_update, timeout)

    # page download was successful, decode the response and send to provided callback
    def on_download_success(self, request_receipt: RNS.RequestReceipt):
        micron_markup_response = request_receipt.response.decode("utf-8")
        self.on_page_download_success(micron_markup_response)

    # page download failed, send error to provided callback
    def on_download_failure(self, failure_reason):
        self.on_page_download_failure(failure_reason)


class NomadnetFileDownloader(NomadnetDownloader):

    def __init__(self, destination_hash: bytes, page_path: str, on_file_download_success: Callable[[str, bytes], None], on_file_download_failure: Callable[[str], None], on_progress_update: Callable[[float], None], timeout: int|None = None):
        self.on_file_download_success = on_file_download_success
        self.on_file_download_failure = on_file_download_failure
        super().__init__(destination_hash, page_path, None, self.on_download_success, self.on_download_failure, on_progress_update, timeout)

    # file download was successful, decode the response and send to provided callback
    def on_download_success(self, request_receipt: RNS.RequestReceipt):

        # get response
        response = request_receipt.response

        # handle buffered reader response
        if isinstance(response, io.BufferedReader):

            # get file name from metadata
            file_name = "downloaded_file"
            metadata = request_receipt.metadata
            if metadata is not None and "name" in metadata:
                file_path = metadata["name"].decode("utf-8")
                file_name = os.path.basename(file_path)

            # get file data
            file_data: bytes = response.read()

            self.on_file_download_success(file_name, file_data)
            return

        # check for list response with bytes in position 0, and metadata dict in position 1
        # e.g: [file_bytes, {name: "filename.ext"}]
        if isinstance(response, list) and isinstance(response[1], dict):

            file_data: bytes = response[0]
            metadata: dict = response[1]

            # get file name from metadata
            file_name = "downloaded_file"
            if metadata is not None and "name" in metadata:
                file_path = metadata["name"].decode("utf-8")
                file_name = os.path.basename(file_path)

            self.on_file_download_success(file_name, file_data)
            return

        # try using original response format
        # unsure if this is actually used anymore now that a buffered reader is provided
        # have left here just in case...
        try:
            file_name: str = response[0]
            file_data: bytes = response[1]
            self.on_file_download_success(file_name, file_data)
        except:
            self.on_download_failure("unsupported_response")

    # page download failed, send error to provided callback
    def on_download_failure(self, failure_reason):
        self.on_file_download_failure(failure_reason)


def main():

    # parse command line args
    parser = argparse.ArgumentParser(description="ReticulumMeshChat")
    parser.add_argument("--host", nargs='?', default="127.0.0.1", type=str, help="The address the web server should listen on.")
    parser.add_argument("--port", nargs='?', default="8000", type=int, help="The port the web server should listen on.")
    parser.add_argument("--headless", action='store_true', help="Web browser will not automatically launch when this flag is passed.")
    parser.add_argument("--disable-rns-bridge", action='store_true', help="Disables the RNS console bridge used by the microReticulum RNode Console.")
    parser.add_argument("--rns-bridge-port", nargs='?', default=None, type=int, help="Also serve the RNS console bridge on this fixed loopback port. Off by default; the bridge is always available on MeshChat's own port at /rns/ws.")
    parser.add_argument("--rns-bridge-token", type=str, help="Require this token as a ?token= query param on the RNS console bridge WebSocket.")
    parser.add_argument("--rns-bridge-allow-origin", action='append', help="Allow an extra browser Origin to use the RNS console bridge. Can be passed multiple times.")
    parser.add_argument("--identity-file", type=str, help="Path to a Reticulum Identity file to use as your LXMF address.")
    parser.add_argument("--identity-base64", type=str, help="A base64 encoded Reticulum Identity to use as your LXMF address.")
    parser.add_argument("--generate-identity-file", type=str, help="Generates and saves a new Reticulum Identity to the provided file path and then exits.")
    parser.add_argument("--generate-identity-base64", action='store_true', help="Outputs a randomly generated Reticulum Identity as base64 and then exits.")
    parser.add_argument("--reticulum-config-dir", type=str, help="Path to a Reticulum config directory for the RNS stack to use (e.g: ~/.reticulum)")
    parser.add_argument("--storage-dir", type=str, help="Path to a directory for storing databases and config files (default: ./storage)")
    parser.add_argument("--test-exception-message", type=str, help="Throws an exception. Used for testing the electron error dialog")
    parser.add_argument('args', nargs=argparse.REMAINDER)  # allow unknown command line args
    args = parser.parse_args()

    # check if we want to test exception messages
    if args.test_exception_message is not None:
        raise Exception(args.test_exception_message)

    # util to generate reticulum identity and save to file without using rnid
    if args.generate_identity_file is not None:

        # do not overwrite existing files, otherwise user could lose existing keys
        if os.path.exists(args.generate_identity_file):
            print("DANGER: the provided identity file path already exists, not overwriting!")
            return

        # generate a new identity and save to provided file path
        identity = RNS.Identity(create_keys=True)
        with open(args.generate_identity_file, "wb") as file:
            file.write(identity.get_private_key())

        print("A new Reticulum Identity has been saved to: {}".format(args.generate_identity_file))
        return

    # util to generate reticulum identity as base64 without using rnid
    if args.generate_identity_base64 is True:
        identity = RNS.Identity(create_keys=True)
        print(base64.b64encode(identity.get_private_key()).decode("utf-8"))
        return

    # use provided identity, or fallback to a random one
    identity_file_path = None
    if args.identity_file is not None:
        identity = RNS.Identity(create_keys=False)
        identity.load(args.identity_file)
        identity_file_path = args.identity_file
        print("Reticulum Identity <{}> has been loaded from file {}.".format(identity.hash.hex(), args.identity_file))
    elif args.identity_base64 is not None:
        identity = RNS.Identity(create_keys=False)
        identity.load_private_key(base64.b64decode(args.identity_base64))
        print("Reticulum Identity <{}> has been loaded from base64.".format(identity.hash.hex()))
    else:

        # ensure provided storage dir exists, or the default storage dir exists
        base_storage_dir = args.storage_dir or os.path.join("storage")
        os.makedirs(base_storage_dir, exist_ok=True)

        # configure path to default identity file
        default_identity_file = os.path.join(base_storage_dir, "identity")

        # if default identity file does not exist, generate a new identity and save it
        if not os.path.exists(default_identity_file):
            identity = RNS.Identity(create_keys=True)
            with open(default_identity_file, "wb") as file:
                file.write(identity.get_private_key())
            print("Reticulum Identity <{}> has been randomly generated and saved to {}.".format(identity.hash.hex(), default_identity_file))

        # default identity file exists, load it
        identity = RNS.Identity(create_keys=False)
        identity.load(default_identity_file)
        identity_file_path = default_identity_file
        print("Reticulum Identity <{}> has been loaded from file {}.".format(identity.hash.hex(), default_identity_file))

    # init app
    reticulum_meshchat = ReticulumMeshChat(identity, args.storage_dir, args.reticulum_config_dir,
                                          identity_file_path=identity_file_path)
    reticulum_meshchat.run(args.host, args.port, launch_browser=args.headless is False, rns_bridge_options={
        "enabled": args.disable_rns_bridge is False,
        "port": args.rns_bridge_port,
        "token": args.rns_bridge_token,
        "allowed_origins": args.rns_bridge_allow_origin,
    })


if __name__ == "__main__":
    main()
