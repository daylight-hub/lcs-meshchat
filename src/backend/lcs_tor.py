"""Tor for LCS Global: an optional, built-in Tor client.

Off by default. When the person switches on "Connect through Tor" on the LCS Global page:

* MeshChat starts its own private Tor (the copy shipped with the app; otherwise a `tor` program
  on this computer, or an already running Tor Browser / Tor service). It runs as a client only:
  it listens on this computer alone (127.0.0.1), never relays anyone's traffic, and exits by
  itself if MeshChat goes away.
* The LCS server is asked over Tor too, so it answers with the gateway's onion address and never
  sees this computer's internet address.
* Reticulum can't use a SOCKS proxy, so a tiny relay on 127.0.0.1 passes the LCS Global
  connection through Tor to the onion address. The interface simply points at that relay.

When the switch is off, nothing here runs at all.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time

import RNS

SYSTEM_SOCKS_PORTS = [9050, 9150]  # a Tor service, and Tor Browser
BOOTSTRAP_RE = re.compile(r"Bootstrapped (\d+)%(?: \([^)]*\))?:? ?(.*)")


def _exe_name() -> str:
    return "tor.exe" if sys.platform == "win32" else "tor"


def bundled_tor_dir() -> str | None:
    """The tor folder shipped next to MeshChat's backend (desktop builds), or in a source tree."""
    here = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    candidates = [os.path.join(here, "tor"),                                   # frozen: build/exe/tor
                  os.path.join(here, "..", "..", "tor")]                        # source: <repo>/tor
    for d in candidates:
        if os.path.isfile(os.path.join(d, _exe_name())):
            return os.path.normpath(d)
    return None


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def socks5_connect(proxy_port: int, host: str, port: int, timeout: float = 60.0) -> socket.socket:
    """A TCP connection to host:port through the SOCKS5 proxy on 127.0.0.1 (names resolve inside Tor)."""
    s = socket.create_connection(("127.0.0.1", proxy_port), timeout=timeout)
    try:
        s.sendall(b"\x05\x01\x00")
        if s.recv(2) != b"\x05\x00":
            raise OSError("Tor's proxy refused the connection")
        name = host.encode("idna")
        s.sendall(b"\x05\x01\x00\x03" + bytes([len(name)]) + name + struct.pack(">H", port))
        head = _recv_exact(s, 4)
        if head[1] != 0:
            raise OSError({1: "Tor failure", 4: "the address can't be reached through Tor",
                           5: "connection refused", 6: "Tor timed out"}.get(head[1], f"SOCKS error {head[1]}"))
        atyp = head[3]
        _recv_exact(s, {1: 4, 4: 16}.get(atyp, 0) or _recv_exact(s, 1)[0])
        _recv_exact(s, 2)
        s.settimeout(None)
        return s
    except Exception:
        s.close()
        raise


def _recv_exact(s: socket.socket, n: int) -> bytes:
    out = b""
    while len(out) < n:
        chunk = s.recv(n - len(out))
        if not chunk:
            raise OSError("Tor closed the connection")
        out += chunk
    return out


def socks_is_tor(port: int) -> bool:
    """Something on 127.0.0.1:port answers like a SOCKS5 proxy."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.5) as s:
            s.sendall(b"\x05\x01\x00")
            return s.recv(2) == b"\x05\x00"
    except OSError:
        return False


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class HTTPSOverTor(http.client.HTTPSConnection):
    """An HTTPS connection whose TCP part goes through Tor."""

    def __init__(self, host: str, socks_port: int, context: ssl.SSLContext, timeout: float = 60):
        super().__init__(host, 443, timeout=timeout, context=context)
        self._socks_port = socks_port
        self._ctx = context

    def connect(self):
        raw = socks5_connect(self._socks_port, self.host, self.port, timeout=self.timeout)
        raw.settimeout(self.timeout)
        self.sock = self._ctx.wrap_socket(raw, server_hostname=self.host)


class Relay:
    """127.0.0.1:<port> -> Tor -> target. Reticulum's LCS Global interface connects here."""

    def __init__(self, tor: "TorClient"):
        self.tor = tor
        self.target: tuple[str, int] | None = None
        self.port = 0
        self._server: socket.socket | None = None
        self._conns: set[socket.socket] = set()
        self._lock = threading.Lock()

    def start(self) -> int:
        if self._server:
            return self.port
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", self.tor.prefs_port("relay_port")))
        srv.listen(8)
        self._server, self.port = srv, srv.getsockname()[1]
        self.tor.remember_port("relay_port", self.port)
        threading.Thread(target=self._accept, name="lcs-tor-relay", daemon=True).start()
        return self.port

    def set_target(self, host: str, port: int):
        new = (host, int(port))
        if new != self.target:
            self.target = new
            self.drop_all()  # reconnect to the new place

    def drop_all(self):
        with self._lock:
            for c in list(self._conns):
                try:
                    c.close()
                except OSError:
                    pass
            self._conns.clear()

    def stop(self):
        self.drop_all()
        if self._server:
            try:
                self._server.close()
            except OSError:
                pass
        self._server = None

    def _accept(self):
        srv = self._server
        while srv is not None and self._server is srv:
            try:
                client, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(client,), daemon=True).start()

    def _serve(self, client: socket.socket):
        target, socks = self.target, self.tor.socks_port
        if not target or not socks or not self.tor.ready:
            client.close()
            return
        try:
            upstream = socks5_connect(socks, target[0], target[1])
        except OSError as e:
            RNS.log(f"LCS Global over Tor: couldn't reach the gateway: {e}", RNS.LOG_WARNING)
            client.close()
            return
        with self._lock:
            self._conns |= {client, upstream}
        a = threading.Thread(target=self._pipe, args=(client, upstream), daemon=True)
        b = threading.Thread(target=self._pipe, args=(upstream, client), daemon=True)
        a.start(); b.start()

    def _pipe(self, src: socket.socket, dst: socket.socket):
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for s in (src, dst):
                try:
                    s.close()
                except OSError:
                    pass
            with self._lock:
                self._conns.discard(src)
                self._conns.discard(dst)


class TorClient:
    """Starts and watches the Tor client. All methods are thread-safe and never raise to callers."""

    def __init__(self, storage_dir: str, prefs_get, prefs_set):
        self.storage_dir = storage_dir
        self._get, self._set = prefs_get, prefs_set
        self.proc: subprocess.Popen | None = None
        self.socks_port: int | None = None
        self.source = ""          # "built-in", "system", "tor-browser" or "tor-service"
        self.state = "off"        # off | starting | ready | unavailable | error
        self.progress = 0
        self.message = ""
        self.version = ""
        self.relay = Relay(self)
        self._lock = threading.RLock()

    @property
    def ready(self) -> bool:
        return self.state == "ready"

    def prefs_port(self, key: str) -> int:
        """Reuse the last port when it's still free, so Reticulum's config doesn't change every start."""
        port = int(self._get(key) or 0)
        if port:
            try:
                with socket.socket() as s:
                    s.bind(("127.0.0.1", port))
                return port
            except OSError:
                pass
        return 0

    def remember_port(self, key: str, port: int):
        if int(self._get(key) or 0) != port:
            self._set(key, port)

    # ------------------------------------------------------------------ finding Tor

    def find(self) -> tuple[str, str] | tuple[None, None]:
        """(how, where): a tor program to start, or an already running proxy port."""
        custom = os.environ.get("LCS_TOR_PATH", "").strip()
        if custom and os.path.isfile(custom):
            # the Docker image sets this to the tor built into it
            return ("built-in-image" if os.environ.get("LCS_DOCKER") == "1" else "system"), custom
        d = bundled_tor_dir()
        if d:
            return "built-in", os.path.join(d, _exe_name())
        found = shutil.which("tor")
        if found:
            return "system", found
        for port in SYSTEM_SOCKS_PORTS:
            if socks_is_tor(port):
                return ("tor-browser" if port == 9150 else "tor-service"), str(port)
        return None, None

    def _check_built_in(self, path: str) -> str | None:
        """The shipped tor must match the fingerprint recorded when MeshChat was built."""
        manifest = os.path.join(os.path.dirname(path), "manifest.json")
        try:
            with open(manifest, encoding="utf-8") as fh:
                info = json.load(fh)
        except (OSError, ValueError):
            return "The built-in Tor is missing its fingerprint file, so it won't be started."
        if sha256_of(path) != info.get("sha256"):
            return "The built-in Tor doesn't match its fingerprint (the file was changed), so it won't be started."
        self.version = str(info.get("version", ""))
        return None

    # ------------------------------------------------------------------ start / stop

    def start(self):
        with self._lock:
            if self.state in ("starting", "ready"):
                return
            how, where = self.find()
            if how is None:
                self.state, self.message = "unavailable", (
                    "Tor isn't available on this computer. Install Tor Browser and leave it open, "
                    "or use a MeshChat download that includes Tor.")
                return
            if how in ("tor-browser", "tor-service"):
                self.source, self.socks_port, self.progress = how, int(where), 100
                self.state, self.message = "ready", ("Using the Tor Browser that's open on this computer."
                                                     if how == "tor-browser" else "Using the Tor service on this computer.")
                self.relay.start()
                return
            if how == "built-in":
                problem = self._check_built_in(where)
                if problem:
                    self.state, self.message = "error", problem
                    RNS.log("LCS Global: " + problem, RNS.LOG_ERROR)
                    return
            self.source = how
            self.socks_port = self.prefs_port("socks_port") or free_port()
            self.remember_port("socks_port", self.socks_port)
            data_dir = os.path.join(self.storage_dir, "tor")
            os.makedirs(data_dir, exist_ok=True)
            try:
                os.chmod(data_dir, 0o700)
            except OSError:
                pass
            torrc = os.path.join(data_dir, "torrc")
            lines = [
                f"SocksPort 127.0.0.1:{self.socks_port}",
                f"DataDirectory {data_dir}",
                "ClientOnly 1",                 # never a relay, bridge or exit
                "AvoidDiskWrites 1",
                "Log notice stdout",
                f"__OwningControllerProcess {os.getpid()}",  # exit if MeshChat goes away
            ]
            tor_dir = os.path.dirname(where)
            for name, opt in (("geoip", "GeoIPFile"), ("geoip6", "GeoIPv6File")):
                for p in (os.path.join(tor_dir, name), os.path.join(tor_dir, "..", "share", "tor", name)):
                    if os.path.isfile(p):
                        lines.append(f"{opt} {os.path.normpath(p)}")
                        break
            with open(torrc, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
            env = dict(os.environ)
            if how == "built-in":
                # the bundle's own libraries sit next to tor
                for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
                    env[var] = tor_dir + (os.pathsep + env[var] if env.get(var) else "")
            flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
            try:
                self.proc = subprocess.Popen([where, "-f", torrc, "--ignore-missing-torrc"], cwd=data_dir, env=env,
                                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                             text=True, encoding="utf-8", errors="replace", creationflags=flags)
            except OSError as e:
                self.state, self.message = "error", f"Couldn't start Tor: {e}"
                return
            self.state, self.progress, self.message = "starting", 0, "Starting Tor…"
            threading.Thread(target=self._watch, args=(self.proc,), name="lcs-tor", daemon=True).start()
            self.relay.start()

    def _watch(self, proc: subprocess.Popen):
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.strip()
            m = BOOTSTRAP_RE.search(line)
            if m:
                self.progress = int(m.group(1))
                if self.progress >= 100:
                    self.state, self.message = "ready", "Connected to the Tor network."
                    RNS.log("LCS Global: Tor is ready", RNS.LOG_NOTICE)
                else:
                    self.message = f"Connecting to the Tor network ({self.progress}%)"
            elif "[err]" in line or "[warn]" in line:
                RNS.log(f"Tor: {line}", RNS.LOG_WARNING if "[warn]" in line else RNS.LOG_ERROR)
            m2 = re.search(r"Tor (\d+\.\d+\.\d+\.\d+)", line)
            if m2 and not self.version:
                self.version = m2.group(1)
        code = proc.wait()
        with self._lock:
            if self.proc is proc:
                self.proc = None
                if self.state != "off":
                    self.state, self.message = "error", f"Tor stopped unexpectedly (exit code {code})."

    def stop(self):
        with self._lock:
            self.relay.stop()
            proc, self.proc = self.proc, None
            self.state, self.progress, self.message, self.source = "off", 0, "", ""
            self.socks_port = None
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass

    def wait_ready(self, seconds: float) -> bool:
        end = time.time() + seconds
        while time.time() < end and self.state == "starting":
            time.sleep(0.5)
        return self.ready

    def ui(self) -> dict:
        return {"state": self.state, "progress": self.progress, "message": self.message,
                "source": self.source, "version": self.version}
