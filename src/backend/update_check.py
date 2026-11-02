"""Tells the person when a newer LCS MeshChat is available.

Checked once when MeshChat starts (and at most once every 12 hours after that), in two places:

* GitHub: the latest *published* release (drafts and pre-releases are ignored);
* the LCS mirror (https://public.lcs.network/downloads/): the newest file of the same kind.

Each download link points at the same kind of file that's installed now (Windows installer or
portable, Mac for this processor, Linux AppImage), since the file names stay the same apart from
the version number. With "Connect through Tor" on, both checks go through Tor too; while Tor
isn't ready they wait. Nothing about this computer is sent.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request

REPO = os.environ.get("LCS_UPDATE_REPO", "daylight-hub/lcs-meshchat")
MIRROR = os.environ.get("LCS_UPDATE_MIRROR", "https://public.lcs.network/downloads/")
ARTIFACT = "LCS-ReticulumMeshChat-v{version}-{suffix}"
SUFFIXES = {
    "win-installer": "win-installer.exe",
    "win-portable": "win-portable.exe",
    "mac-arm64": "mac-arm64.dmg",
    "mac-x64": "mac-x64.dmg",
    "linux-appimage": "linux.AppImage",
}
CHECK_EVERY = 12 * 3600


def parse_version(text: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", str(text or ""))
    return tuple(int(n) for n in nums[:4]) if nums else ()


def install_kind() -> str:
    """Which download this is. The desktop app tells the backend; otherwise it's worked out here."""
    kind = os.environ.get("LCS_INSTALL_KIND", "").strip().lower()
    if kind:
        return kind
    if os.environ.get("LCS_DOCKER") == "1" or os.path.exists("/.dockerenv"):
        return "docker"
    return "source"


class UpdateChecker:

    def __init__(self, storage_dir: str, current_version: str, fetch=None, tor_port=None):
        """fetch(url) -> bytes, for tests. tor_port() -> SOCKS port, None (direct) or 0 (Tor on, not ready)."""
        self.path = os.path.join(storage_dir, "app_update.json")
        self.current = current_version
        self.kind = install_kind()
        self.release: dict | None = None
        self.mirror_files: list[str] = []
        self.checked_at = 0.0
        self._fetch = fetch
        self._tor_port = tor_port or (lambda: None)

    # ------------------------------------------------------------------ "don't show again"

    def _prefs(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
                return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def dismiss(self, version: str):
        """Stays quiet about this version; a later release is shown again."""
        prefs = self._prefs()
        prefs["dismissed"] = str(version)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(prefs, fh)
        os.replace(tmp, self.path)

    # ------------------------------------------------------------------ fetching

    def _get(self, url: str, accept: str = "*/*") -> bytes:
        if self._fetch is not None:
            return self._fetch(url)
        from .lcs_global import TLS  # same trusted roots as LCS Global
        headers = {"Accept": accept, "User-Agent": "LCS-MeshChat"}
        port = self._tor_port()
        if port == 0:
            raise OSError("Tor isn't ready yet")
        if port:
            from .lcs_tor import HTTPSOverTor
            u = urllib.parse.urlsplit(url)
            conn = HTTPSOverTor(u.hostname, port, TLS, timeout=60)
            try:
                conn.request("GET", (u.path or "/") + (f"?{u.query}" if u.query else ""), headers=headers)
                resp = conn.getresponse()
                if resp.status != 200:
                    raise OSError(f"HTTP {resp.status}")
                return resp.read()
            finally:
                conn.close()
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15, context=TLS) as resp:
            return resp.read()

    def check(self, force: bool = False) -> dict:
        """Blocking (call from a worker thread)."""
        if self.checked_at and not force and time.time() - self.checked_at < CHECK_EVERY:
            return self.status()
        if self._fetch is None and self._tor_port() == 0:
            return {**self.status(), "waiting": True}  # Tor is on but still connecting: ask again soon
        got_any = False
        try:
            self.release = json.loads(self._get(f"https://api.github.com/repos/{REPO}/releases/latest",
                                                "application/vnd.github+json").decode())
            got_any = True
        except Exception:  # noqa: BLE001 - offline, private repository, rate limit: say nothing
            pass
        try:
            page = self._get(MIRROR).decode("utf-8", "replace")
            self.mirror_files = sorted(set(re.findall(r'href="(LCS-ReticulumMeshChat-v[0-9][^"/]*)"', page)))
            got_any = True
        except Exception:  # noqa: BLE001
            pass
        if got_any:
            self.checked_at = time.time()
        return self.status()

    # ------------------------------------------------------------------ result

    def _github_download(self) -> dict | None:
        release = self.release or {}
        version = str(release.get("tag_name") or "").lstrip("vV")
        if not version or parse_version(version) <= parse_version(self.current):
            return None
        out = {"source": "GitHub", "version": version, "file": None, "url": None,
               "page": release.get("html_url") or f"https://github.com/{REPO}/releases/latest"}
        suffix = SUFFIXES.get(self.kind)
        if suffix:
            name = ARTIFACT.format(version=version, suffix=suffix)
            asset = next((a for a in release.get("assets") or [] if a.get("name") == name), None)
            if asset:
                out["file"], out["url"] = asset["name"], asset.get("browser_download_url")
        return out

    def _mirror_download(self) -> dict | None:
        suffix = SUFFIXES.get(self.kind)
        if not suffix:
            return None
        best = None
        for name in self.mirror_files:
            m = re.fullmatch(r"LCS-ReticulumMeshChat-v(\d+(?:\.\d+)+)-" + re.escape(suffix), urllib.parse.unquote(name))
            if m and (best is None or parse_version(m.group(1)) > parse_version(best[0])):
                best = (m.group(1), urllib.parse.unquote(name))
        if not best or parse_version(best[0]) <= parse_version(self.current):
            return None
        return {"source": "lcs.network", "version": best[0], "file": best[1],
                "url": urllib.parse.urljoin(MIRROR, urllib.parse.quote(best[1])), "page": MIRROR}

    def status(self) -> dict:
        downloads = [d for d in (self._github_download(), self._mirror_download()) if d]
        latest = max((d["version"] for d in downloads), key=parse_version, default=None)
        return {
            "available": bool(latest),
            "current": self.current,
            "latest": latest,
            "kind": self.kind,
            "downloads": downloads,
            "notes": ((self.release or {}).get("body") or "")[:4000]
                     if any(d["source"] == "GitHub" and d["version"] == latest for d in downloads) else "",
            "dismissed": bool(latest) and self._prefs().get("dismissed") == latest,
        }
