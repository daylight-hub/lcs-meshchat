"""LCS Global: the paid internet connection to the Liberty network, for LCS MeshChat.

Works the same way as in Liberty Chat:

* MeshChat proves who it is by signing each request with its own Reticulum identity (the
  same identity as its LXMF address), so there are no accounts, passwords or codes.
* The LCS server says where this identity stands (free trial, paid, payment due, ended).
  While it has access, the server opens its firewall for this computer's internet address
  and hands back the gateway's address, port and current passphrase. They change (the
  passphrase every month), so MeshChat keeps the "LCS Global" interface up to date itself
  and reloads it without a restart. When access ends, the interface is switched off.
* Paying happens on lcs.network in the browser. MeshChat sends a one-time device code with
  the checkout link, so the purchase is tied to this identity and connects by itself within
  seconds of paying.

Nothing here is a secret worth extracting: the address and passphrase only come from the
server after a signed request from an identity that has access, and the passphrase rotates.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import json
import os
import secrets
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request

import RNS

PRODUCT_NAME = "LCS Global"
INTERFACE_NAME = "LCS Global"
API_BASE = os.environ.get("LCS_GLOBAL_API", "https://update.lcs.network").rstrip("/")
TRIAL_DAYS = 7
DAY = 86400

# Hand-made interfaces may never point at these (or anything under lcs.network): LCS Global is
# reached only through the managed interface. Their addresses are looked up and remembered too,
# so typing the raw IP doesn't get around it.
def _tls_context() -> ssl.SSLContext:
    """The system's trusted roots plus certifi's. Python on Windows only sees the roots Windows
    has already downloaded, so a root it hasn't fetched yet (e.g. ISRG Root X1) would fail."""
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except Exception:  # noqa: BLE001 - certifi missing: the system roots alone
        pass
    return ctx


TLS = _tls_context()


def friendly_error(exc: Exception) -> str:
    text = str(getattr(exc, "reason", exc))
    if "CERTIFICATE_VERIFY_FAILED" in text:
        return "Couldn't make a secure connection to LCS. Check this computer's date and time, then try again."
    if "getaddrinfo" in text or "Name or service not known" in text or "nodename nor servname" in text:
        return "Couldn't reach LCS. Check your internet connection and try again."
    if "timed out" in text:
        return "LCS took too long to answer. Try again in a moment."
    return "Couldn't reach LCS. Check your internet connection and try again."


RESERVED_DOMAIN = "lcs.network"
RESERVED_NAMES = ["lcs.network", "public.lcs.network", "server.lcs.network", "start.lcs.network",
                  "update.lcs.network"]
RESERVED_MESSAGE = (f"This server is reserved for {PRODUCT_NAME}. Add {PRODUCT_NAME} from Interfaces "
                    f"(Add Interface > {PRODUCT_NAME}) instead.")

# Interfaces earlier versions added by hand for the old free gateway. They become LCS Global.
LEGACY_NAMES = {"LCS Gateway", "LCS Gateway Client: public.lcs.network"}

# Shown if the plan list can't be fetched (prices really come from Square via the LCS server).
FALLBACK_PLANS = [
    {"plan": "monthly", "name": "Monthly", "lines": 1, "label": "$5/month", "per_line": ""},
    {"plan": "yearly", "name": "Yearly", "lines": 1, "label": "$49/year", "per_line": ""},
    {"plan": "family2-monthly", "name": "Family (2 lines), monthly", "lines": 2, "label": "$6/month", "per_line": "$3/month per line"},
    {"plan": "family2", "name": "Family (2 lines), yearly", "lines": 2, "label": "$59/year", "per_line": "$29.50/year per line"},
    {"plan": "family5-monthly", "name": "Family (5 lines), monthly", "lines": 5, "label": "$10/month", "per_line": "$2/month per line"},
    {"plan": "family5", "name": "Family (5 lines), yearly", "lines": 5, "label": "$99/year", "per_line": "$19.80/year per line"},
]

STATUS_INTERVAL = 6 * 3600      # nothing to do: check again in 6 hours
RETRY_INTERVAL = 15 * 60        # server unreachable
WATCH_INTERVAL = 15             # just sent to checkout: look every 15 seconds
WATCH_SECONDS = 45 * 60
TRANSFER_PREFIX = b"lcs-gw-transfer-v1:"


def normalise_host(host) -> str:
    h = str(host or "").strip().lower()
    for prefix in ("http://", "https://"):
        if h.startswith(prefix):
            h = h[len(prefix):]
    h = h.split("/")[0]
    if h.startswith("["):
        h = h[1:].split("]")[0]
    elif h.count(":") == 1:
        h = h.split(":")[0]
    return h.rstrip(".")


def canonical_ip(text: str) -> str | None:
    try:
        return str(ipaddress.ip_address(text.split("%")[0]))
    except ValueError:
        return None


def hardware_id() -> str:
    """The MAC addresses of this machine's physical network ports (Linux), for spotting a copied card."""
    macs = set()
    base = "/sys/class/net"
    try:
        names = os.listdir(base)
    except OSError:
        names = []
    for name in names:
        if not os.path.exists(os.path.join(base, name, "device")):
            continue
        try:
            with open(os.path.join(base, name, "address"), encoding="utf-8") as fh:
                mac = fh.read().strip().lower()
        except OSError:
            continue
        if mac and mac != "00:00:00:00:00:00":
            macs.add(mac)
    return hashlib.sha256(",".join(sorted(macs)).encode()).hexdigest()


class LcsGlobal:

    def __init__(self, app, client: str = "meshchat", client_version: str = ""):
        self.app = app
        self.client = os.environ.get("LCS_GLOBAL_CLIENT", client)  # "commandcenter" on a router
        self.client_version = client_version
        # Command Center fleet key: from the environment, or a file next to MeshChat's storage
        # (so a master SD card can carry it)
        self.enroll_key = os.environ.get("LCS_CC_ENROLL_KEY", "").strip()
        key_file = os.path.join(app.storage_dir, "lcs_cc_enroll_key")
        if not self.enroll_key and os.path.exists(key_file):
            with open(key_file, encoding="utf-8") as fh:
                self.enroll_key = fh.read().strip()
        self.prefs_path = os.path.join(app.storage_dir, "lcs_global.json")
        self.lock = threading.RLock()
        self.prefs = self._load_prefs()
        self.status: dict | None = None
        self.status_at = 0.0
        self.message: str | None = None
        self.busy = False
        self.watch_until = 0.0
        self.known_ips: set[str] = set(self.prefs.get("reserved_ips", []))
        self.kick_event: asyncio.Event | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.plans = self.prefs.get("plans") or FALLBACK_PLANS

    # ------------------------------------------------------------------ prefs

    def _load_prefs(self) -> dict:
        try:
            with open(self.prefs_path, encoding="utf-8") as fh:
                prefs = json.load(fh)
                if isinstance(prefs, dict):
                    return prefs
        except (OSError, ValueError):
            pass
        return {}

    def _save_prefs(self):
        with self.lock:
            tmp = self.prefs_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.prefs, fh)
            os.replace(tmp, self.prefs_path)

    def pref(self, key, default=None):
        return self.prefs.get(key, default)

    def set_pref(self, key, value):
        self.prefs[key] = value
        self._save_prefs()

    def device_hash(self) -> str:
        """Stable for this install, across identity resets: a free trial is once per computer.
        As a Command Center it is also tied to the hardware, so a copied SD card in another
        router signs in as a separate Command Center."""
        secret = self.prefs.get("device_secret")
        if self.client == "commandcenter":
            hw = hardware_id()
            if secret and self.prefs.get("device_hw") not in (None, hw):
                RNS.log("LCS Global: this storage was copied from another device; using a new device id", RNS.LOG_NOTICE)
                secret = None
            if self.prefs.get("device_hw") != hw:
                self.set_pref("device_hw", hw)
        if not secret:
            secret = secrets.token_hex(32)
            self.set_pref("device_secret", secret)
        salt = b"lcs-cc-v1:" if self.client == "commandcenter" else b"lcs-gw-v1:meshchat-"
        return hashlib.sha256(salt + secret.encode()).hexdigest()

    # ------------------------------------------------------------------ reserved hosts

    def is_reserved_host(self, host) -> bool:
        h = normalise_host(host)
        if not h:
            return False
        if h == RESERVED_DOMAIN or h.endswith("." + RESERVED_DOMAIN):
            return True
        live = self.live_host()
        if live and h == normalise_host(live):
            return True
        ip = canonical_ip(h)
        return ip is not None and ip in self.known_ips

    def is_reserved_resolved(self, host) -> bool:
        """Also checks what a name resolves to now (may do DNS: call from a worker thread)."""
        if self.is_reserved_host(host):
            return True
        h = normalise_host(host)
        if not h or h.endswith(".onion") or not self.known_ips or canonical_ip(h):
            return False
        try:
            return any(canonical_ip(info[4][0]) in self.known_ips for info in socket.getaddrinfo(h, None))
        except OSError:
            return False

    def refresh_reserved_ips(self):
        fresh = set()
        for name in RESERVED_NAMES:
            try:
                fresh |= {canonical_ip(info[4][0]) for info in socket.getaddrinfo(name, None)}
            except OSError:
                pass
        fresh.discard(None)
        if fresh - self.known_ips:
            # keep old addresses too, so a DNS change doesn't reopen one
            self.known_ips |= fresh
            self.set_pref("reserved_ips", sorted(self.known_ips))

    # ------------------------------------------------------------------ the interface

    def interfaces(self):
        if "interfaces" not in self.app.reticulum.config:
            self.app.reticulum.config["interfaces"] = {}
        return self.app.reticulum.config["interfaces"]

    def has_interface(self) -> bool:
        return INTERFACE_NAME in self.interfaces()

    def live_host(self) -> str | None:
        section = self.app.reticulum.config.get("interfaces", {}).get(INTERFACE_NAME)
        return section.get("target_host") if section else None

    @staticmethod
    def is_live(name: str) -> bool:
        return any(getattr(i, "name", None) == name for i in RNS.Transport.interfaces)

    def prepare_config(self):
        """At startup, once Reticulum has loaded its config: turn the old hand-made LCS gateway
        into LCS Global, and switch off anything else hand-made that points at LCS."""
        interfaces = self.interfaces()
        changed = False
        for name in list(interfaces.keys()):
            section = interfaces[name]
            if not isinstance(section, dict) or name == INTERFACE_NAME:
                continue
            host = section.get("target_host")
            legacy = name in LEGACY_NAMES or normalise_host(host) == "public.lcs.network"
            if legacy and INTERFACE_NAME not in interfaces:
                # Same as Liberty Chat: existing users move onto the free trial automatically.
                RNS.log(f"LCS Global: replacing the old \"{name}\" interface", RNS.LOG_NOTICE)
                del interfaces[name]
                interfaces[INTERFACE_NAME] = self.placeholder_section()
                if self.pref("auto_trial") is None:
                    self.set_pref("auto_trial", True)
                self._detach(name)
                changed = True
            elif legacy or self.is_reserved_host(host):
                RNS.log(f"LCS Global: \"{name}\" points at an LCS server and was switched off", RNS.LOG_NOTICE)
                if legacy:
                    del interfaces[name]
                else:
                    section["enabled"] = "no"
                    section.pop("interface_enabled", None)
                self._detach(name)
                changed = True
        if changed:
            self.app.reticulum.config.write()

    @staticmethod
    def placeholder_section() -> dict:
        return {
            "type": "TCPClientInterface",
            "enabled": "no",
            "target_host": "gateway.lcs.invalid",
            "target_port": "4245",
            "mode": "full",
            "bootstrap_only": "no",
        }

    def ensure_interface(self):
        if self.pref("paused", False):
            self.set_pref("paused", False)
        interfaces = self.interfaces()
        if INTERFACE_NAME not in interfaces:
            interfaces[INTERFACE_NAME] = self.placeholder_section()
            self.app.reticulum.config.write()

    def set_paused(self, paused: bool):
        """Switched off in Interfaces: stays off until switched back on (blocking)."""
        self.set_pref("paused", bool(paused))
        if paused:
            section = self.interfaces().get(INTERFACE_NAME)
            if section is not None:
                section["enabled"] = "no"
                self.app.reticulum.config.write()
            self._detach(INTERFACE_NAME)
        self.kick()

    def remove_interface(self):
        interfaces = self.interfaces()
        if INTERFACE_NAME in interfaces:
            del interfaces[INTERFACE_NAME]
            self.app.reticulum.config.write()
        self._detach(INTERFACE_NAME)
        self.set_pref("auto_trial", False)
        self.set_pref("paused", False)

    def _detach(self, name: str):
        if self.is_live(name):
            try:
                self.app.reticulum.detach_interface(name)
            except Exception as e:  # noqa: BLE001 - never let this stop the app
                RNS.log(f"LCS Global: could not detach \"{name}\": {e}", RNS.LOG_WARNING)

    def apply_session(self, session: dict) -> bool:
        """Write the gateway settings from a session into the interface. True if anything changed."""
        interfaces = self.interfaces()
        wanted = {
            "type": "TCPClientInterface",
            "enabled": "yes",
            "target_host": str(session["host"]),
            "target_port": str(int(session["port"])),
            "mode": "full",
            "bootstrap_only": "no",
        }
        if session.get("network_name"):
            wanted["network_name"] = str(session["network_name"])
        if session.get("passphrase"):
            wanted["passphrase"] = str(session["passphrase"])
        current = interfaces.get(INTERFACE_NAME) or {}
        # Reticulum adds its own runtime keys to the section, so compare only the ones we set.
        managed = set(wanted) | {"network_name", "passphrase"}
        same = all(str(current.get(k, "")) == str(wanted.get(k, "")) for k in managed)
        if same and self.is_live(INTERFACE_NAME):
            return False
        interfaces[INTERFACE_NAME] = wanted
        self.app.reticulum.config.write()
        self._attach_or_reload()
        return True

    def disable_interface(self):
        interfaces = self.interfaces()
        section = interfaces.get(INTERFACE_NAME)
        if section is None:
            return
        if section.get("enabled") != "no" or "passphrase" in section:
            # Access ended: switch it off and forget the passphrase.
            interfaces[INTERFACE_NAME] = self.placeholder_section()
            self.app.reticulum.config.write()
        self._detach(INTERFACE_NAME)

    def _attach_or_reload(self):
        r = self.app.reticulum
        try:
            if self.is_live(INTERFACE_NAME):
                r.reload_interface(INTERFACE_NAME)
            else:
                r.attach_interface(INTERFACE_NAME)
            RNS.log("LCS Global: gateway settings applied", RNS.LOG_NOTICE)
        except Exception as e:  # noqa: BLE001
            RNS.log(f"LCS Global: could not load the interface yet: {e}", RNS.LOG_WARNING)
        if getattr(r, "is_connected_to_shared_instance", False):
            self.message = ("MeshChat is using a shared Reticulum instance, which loads interfaces from its own "
                            "config. Run MeshChat with its own Reticulum instance to use LCS Global.")

    # ------------------------------------------------------------------ talking to LCS

    def _signed_body(self, ident, action: str, extra: dict | None = None) -> tuple[bytes, str]:
        body = {
            "v": 1,
            "action": action,
            "pub": base64.b64encode(ident.get_public_key()).decode(),
            "dev": self.device_hash(),
            "ts": int(time.time()) + int(self.prefs.get("clock_offset", 0)),
            "nonce": secrets.token_hex(16),
            "client": self.client,
            "client_version": self.client_version,
        }
        if self.client == "commandcenter" and self.enroll_key:
            body["enroll_key"] = self.enroll_key
        if extra:
            body.update(extra(body) if callable(extra) else extra)
        raw = json.dumps(body, separators=(",", ":")).encode()
        return raw, base64.b64encode(ident.sign(raw)).decode()

    def _post(self, path: str, raw: bytes, signature: str) -> tuple[int, dict]:
        req = urllib.request.Request(API_BASE + path, data=raw, method="POST", headers={
            "Content-Type": "application/json", "X-LCS-Signature": signature,
            "User-Agent": f"LCS-MeshChat/{self.client_version}",
        })
        try:
            with urllib.request.urlopen(req, timeout=20, context=TLS) as resp:
                self.offline = False
                return resp.status, json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            self.offline = False
            try:
                return e.code, json.loads(e.read().decode() or "{}")
            except ValueError:
                return e.code, {}
        except (OSError, ValueError) as e:
            RNS.log(f"LCS Global: {path} failed: {e}", RNS.LOG_WARNING)
            self.offline = True
            return 0, {"message": friendly_error(e)}

    def call(self, path: str, action: str, extra=None, ident=None) -> tuple[int, dict]:
        """Blocking. Signs with the running identity and retries once if this clock is off."""
        ident = ident or self.app.identity
        code, body = self._post(path, *self._signed_body(ident, action, extra))
        if code == 401 and body.get("error") == "clock_skew" and "server_time" in body:
            self.set_pref("clock_offset", int(body["server_time"]) - int(time.time()))
            code, body = self._post(path, *self._signed_body(ident, action, extra))
        if "state" in body:
            self.status = body
            self.status_at = time.time()
        return code, body

    def fetch_plans(self):
        try:
            with urllib.request.urlopen(API_BASE + "/v1/plans", timeout=15, context=TLS) as resp:
                plans = json.loads(resp.read().decode()).get("plans") or []
            if plans:
                self.plans = plans
                self.set_pref("plans", plans)
        except (OSError, ValueError):
            pass
        return self.plans

    # ------------------------------------------------------------------ the cycle

    def cycle(self) -> float:
        """One round (blocking). Returns seconds until the next one."""
        self.try_pending_transfer()
        if not self.has_interface() or self.pref("paused", False):
            if self.status is None or time.time() - self.status_at > 3600:
                self.call("/v1/status", "status")
            return STATUS_INTERVAL
        code, body = self.call("/v1/gateway/session", "session")
        if code == 402 and body.get("state") == "none" and body.get("trial_available") and self.pref("auto_trial", False):
            t_code, t_body = self.call("/v1/trial/start", "trial_start")
            if t_code == 409:
                self.set_pref("auto_trial", False)
            self.message = t_body.get("message") if t_code != 200 else None
            if t_code == 200 and t_body.get("gateway_open"):
                code, body = self.call("/v1/gateway/session", "session")
        if code == 200 and "host" in body:
            self.apply_session(body)
            self.watch_until = 0  # paid and connected: stop watching
            return max(300, min(int(body.get("refresh_in", 14400)), STATUS_INTERVAL))
        if code == 402:
            self.disable_interface()
            return WATCH_INTERVAL if time.time() < self.watch_until else STATUS_INTERVAL
        RNS.log(f"LCS Global: server not reachable ({code}): {body.get('message', '')}", RNS.LOG_WARNING)
        return WATCH_INTERVAL if time.time() < self.watch_until else RETRY_INTERVAL

    async def run(self):
        """Started once with the web server; keeps the interface in step with the subscription."""
        self.loop = asyncio.get_running_loop()
        self.kick_event = asyncio.Event()
        await asyncio.to_thread(self.refresh_reserved_ips)
        while True:
            try:
                wait = await asyncio.to_thread(self.cycle)
            except Exception as e:  # noqa: BLE001 - keep going whatever happens
                RNS.log(f"LCS Global: cycle failed: {e}", RNS.LOG_ERROR)
                wait = RETRY_INTERVAL
            try:
                await asyncio.wait_for(self.kick_event.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass
            self.kick_event.clear()

    def kick(self):
        if self.loop and self.kick_event:
            self.loop.call_soon_threadsafe(self.kick_event.set)

    # ------------------------------------------------------------------ user actions (blocking)

    def start_trial(self) -> tuple[bool, str]:
        self.set_pref("auto_trial", True)
        self.ensure_interface()
        code, body = self.call("/v1/trial/start", "trial_start")
        self.kick()
        if code == 200:
            return True, f"Your {TRIAL_DAYS}-day free trial has started. {PRODUCT_NAME} connects in a moment."
        if code == 409:
            self.set_pref("auto_trial", False)
        return False, body.get("message") or "Couldn't reach LCS. Check your internet connection and try again."

    def link_code(self) -> tuple[dict | None, str]:
        code, body = self.call("/v1/link-code", "link_code")
        if code != 200:
            return None, body.get("message") or "Couldn't reach LCS. Check your internet connection and try again."
        return body, ""

    def subscribe_url(self, plan: str) -> tuple[str | None, str]:
        """Checkout on lcs.network, tied to this identity: it connects as soon as payment goes through."""
        self.set_pref("auto_trial", False)
        self.ensure_interface()
        link, message = self.link_code()
        if link is None:
            return None, message
        prefix = link.get("subscribe_url_prefix")
        url = (prefix + plan) if prefix else (link["subscribe_monthly_url"] if plan == "monthly" else link["subscribe_yearly_url"])
        self.watch_until = time.time() + WATCH_SECONDS
        self.kick()
        return url + "&lcs_app=meshchat", ""

    def manage_url(self) -> str:
        fallback = (self.status or {}).get("account_url") or "https://lcs.network/my-account/lcs-global/"
        code, body = self.call("/v1/account-link", "account_link")
        return body.get("url") or fallback if code == 200 else fallback

    def link_device_url(self) -> tuple[str | None, str]:
        self.ensure_interface()
        link, message = self.link_code()
        if link is None:
            return None, message
        self.watch_until = time.time() + WATCH_SECONDS
        self.kick()
        return link["link_device_url"] + "&lcs_app=meshchat", f"Your device code is {link['code']}"

    def redeem(self, code_text: str) -> tuple[bool, str]:
        self.set_pref("auto_trial", False)
        self.ensure_interface()
        code, body = self.call("/v1/redeem", "redeem", {"code": code_text.strip()})
        self.kick()
        return code == 200, body.get("message") or ("Redeemed." if code == 200 else "Couldn't reach LCS. Try again.")

    # ------------------------------------------------------------------ identity reset

    def remember_identity_reset(self, old_identity_path: str | None):
        """Called when the identity is replaced: at the next start, move the trial or plan from the
        old identity to the new one (both sign), so nothing has to be entered again."""
        if old_identity_path:
            self.set_pref("pending_transfer", old_identity_path)

    def try_pending_transfer(self):
        path = self.prefs.get("pending_transfer")
        if not path:
            return
        old = RNS.Identity.from_file(path) if os.path.exists(path) else None
        if old is None or old.hash == self.app.identity.hash:
            self.set_pref("pending_transfer", None)
            return
        to_hash = self.app.identity.hash.hex()

        def consent(body):
            statement = TRANSFER_PREFIX + f"{to_hash}:{body['ts']}:{body['nonce']}".encode()
            return {"from_pub": base64.b64encode(old.get_public_key()).decode(),
                    "from_sig": base64.b64encode(old.sign(statement)).decode()}

        code, body = self.call("/v1/transfer", "transfer", consent)
        if code in (200, 409, 401):
            # 409: the old identity had nothing to move. Either way, don't try again.
            self.set_pref("pending_transfer", None)
            if code == 200:
                RNS.log("LCS Global: moved the subscription to the new identity", RNS.LOG_NOTICE)
                self.ensure_interface()

    # ------------------------------------------------------------------ for the UI

    def ui_status(self) -> dict:
        s = self.status or {}
        return {
            "product_name": PRODUCT_NAME,
            "trial_days": TRIAL_DAYS,
            "status": self.status,
            "has_interface": self.has_interface(),
            "connected": any(getattr(i, "name", None) == INTERFACE_NAME and getattr(i, "online", False)
                             for i in RNS.Transport.interfaces),
            "paused": bool(self.pref("paused", False)),
            "lxmf_address": s.get("lxmf_address") or RNS.Destination.hash(self.app.identity, "lxmf", "delivery").hex(),
            "message": self.message,
            "plans": self.plans,
            "popup_dismissed": bool(self.pref("popup_dismissed", False)),
            "watching": time.time() < self.watch_until,
            "offline": bool(getattr(self, "offline", False)),
        }
