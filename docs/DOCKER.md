# Running LCS MeshChat in Docker

Everything needed to run LCS MeshChat in a container: the compose file, the HTTPS
reverse proxy that voice calls require, reaching the Transport Node Console through
that proxy, and what to do when something does not connect.

- [Quick start](#quick-start)
- [Why HTTPS is required](#why-https-is-required)
- [Reverse proxy — OpenWrt 24.10](#reverse-proxy--openwrt-2410)
- [Reverse proxy — Debian](#reverse-proxy--debian)
- [The Transport Node Console over the proxy](#the-transport-node-console-over-the-proxy)
- [Verifying the setup](#verifying-the-setup)
- [Troubleshooting](#troubleshooting)
- [Security notes](#security-notes)

---

## Quick start

```yaml
services:
  reticulum-meshchat:
    container_name: reticulum-meshchat
    image: ghcr.io/daylight-hub/reticulum-meshchat:latest
    restart: unless-stopped
    network_mode: bridge          # own namespace -> no host port conflicts
    environment:
      - LCS_DOCKER=1
    ports:
      - 8082:8000
    volumes:
      - /opt/reticulum-meshchat:/config
    command: >
      python meshchat.py --host=0.0.0.0 --port=8000
      --reticulum-config-dir=/config/.reticulum
      --storage-dir=/config/.meshchat --headless
```

```sh
docker compose up -d
```

The app is then on `http://<host>:8082` and the Transport Node Console on
`http://<host>:8082/transport-console/index.html`.

`LCS_DOCKER=1` tells the app it is containerised, so it uses the browser audio
bridge instead of looking for audio hardware it does not have. Leave it set.

Images are built for `linux/amd64` and `linux/arm64` on every push to the `lcs`
branch, and published as `:latest` and `:lcs`.

### What lives where

| Path | Contents |
|---|---|
| `/config/.reticulum` | Reticulum config and identity |
| `/config/.meshchat` | MeshChat database, storage, attachments |

Back up `/opt/reticulum-meshchat` and you have backed up the node.

---

## Why HTTPS is required

The container has no audio hardware, so calls use **your browser's** microphone and
speaker over a WebSocket audio bridge. Browsers only grant microphone access in a
**secure context** — HTTPS, or `localhost`. Reached over plain HTTP from another
machine, calls will connect and carry no audio.

So a container deployment needs an HTTPS reverse proxy in front of it. The two
configurations below both listen on **8443 (HTTPS)** and proxy to
**127.0.0.1:8082**, which Docker maps to the container's port 8000.

The same proxy is what lets the Transport Node Console reach the RNS bridge, so
setting it up solves both problems at once.

---

## Reverse proxy — OpenWrt 24.10

**1. Install nginx with SSL support**

```sh
opkg update
opkg install nginx-ssl
```

**2. Generate a self-signed certificate**

Use the hostname you will actually type in the browser — see
[Always use the hostname](#always-use-the-hostname-not-the-ip-address) below.

```sh
mkdir -p /etc/nginx/ssl
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/meshchat.key \
  -out /etc/nginx/ssl/meshchat.crt \
  -subj "/CN=liberty.local" \
  -addext "subjectAltName=DNS:liberty.local,IP:192.168.2.1"
```

**3. Create `/etc/nginx/conf.d/meshchat.conf`**

```nginx
server {
    listen 8443 ssl;
    server_name liberty.local;

    ssl_certificate     /etc/nginx/ssl/meshchat.crt;
    ssl_certificate_key /etc/nginx/ssl/meshchat.key;

    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:8082;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

**4. Test and restart**

OpenWrt's nginx is UCI-managed and runs with an explicit config path:

```sh
nginx -t -c /etc/nginx/uci.conf
/etc/init.d/nginx restart
/etc/init.d/nginx enable
```

**5. Allow port 8443 from the LAN**

```sh
uci add firewall rule
uci set firewall.@rule[-1].name='Allow-MeshChat-HTTPS'
uci set firewall.@rule[-1].src='lan'
uci set firewall.@rule[-1].proto='tcp'
uci set firewall.@rule[-1].dest_port='8443'
uci set firewall.@rule[-1].target='ACCEPT'
uci commit firewall
/etc/init.d/firewall restart
```

**6. Open the app**

```
https://liberty.local:8443
```

---

## Reverse proxy — Debian

**1. Install nginx**

```sh
sudo apt update
sudo apt install nginx openssl
```

**2. Create a certificate**

For a LAN host, self-signed (substitute your own hostname and IP):

```sh
sudo mkdir -p /etc/nginx/ssl
sudo openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/meshchat.key \
  -out /etc/nginx/ssl/meshchat.crt \
  -subj "/CN=meshchat.local" \
  -addext "subjectAltName=DNS:meshchat.local,IP:192.168.1.50"
sudo chmod 600 /etc/nginx/ssl/meshchat.key
```

If the machine has a public domain name, use Let's Encrypt instead and avoid
browser certificate warnings entirely:

```sh
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d meshchat.example.com
```

**3. Create `/etc/nginx/sites-available/meshchat`**

```nginx
server {
    listen 8443 ssl;
    listen [::]:8443 ssl;
    server_name meshchat.local;

    ssl_certificate     /etc/nginx/ssl/meshchat.crt;
    ssl_certificate_key /etc/nginx/ssl/meshchat.key;
    ssl_protocols       TLSv1.2 TLSv1.3;

    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:8082;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

**4. Enable the site and reload**

```sh
sudo ln -s /etc/nginx/sites-available/meshchat /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl enable nginx
```

**5. Allow port 8443** (if `ufw` is active)

```sh
sudo ufw allow 8443/tcp
```

**6. Open the app**

```
https://meshchat.local:8443
```

---

## The Transport Node Console over the proxy

The console is served from the same origin as the app:

```
https://liberty.local:8443/transport-console/index.html
```

It finds the RNS bridge by itself. Discovery runs in three tiers and stops at the
first address that answers a ping:

1. **This page's own address** — `?ws=` if given, then the endpoint that worked last
   time, then `<this origin>/rns/ws`. Behind the proxy this first tier is the one
   that hits, on the first try.
2. **This computer** — `localhost` and `127.0.0.1` on 9337, 8000, 8080 and 4000, for
   a desktop install.
3. **The local network** — a sweep of `.local` names on the proxy port 8443 over
   TLS, on the usual published container ports, and on plain 443. Hosts that have
   answered before are swept first, then any given with `?hosts=`, then the
   documented names: `liberty.local`, `meshchat.local`, `lcs.local`,
   `reticulum-meshchat.local`, `rns.local`, `openwrt.local`, `raspberrypi.local`,
   `nas.local`.

A green **RNS bridge found** banner names the address it settled on. No extra flag
is needed: the bridge accepts same-origin WebSocket connections and tolerates
`proxy_set_header Host $host` stripping the port. Cross-origin connections are
still refused.

If your container is on a hostname not in the list, either add it to the URL once:

```
https://liberty.local:8443/transport-console/index.html?hosts=depot.local
```

— it is remembered afterwards — or skip discovery entirely:

```
https://liberty.local:8443/transport-console/index.html?ws=wss://depot.local:8443/rns/ws
```

### Local and remote are the same console

Nothing about the console changes between managing a node on the bench and managing
one across the mesh. Same tabs, same fields, same presets. The **Transport**
selector at the top picks how it reaches the node:

| Transport | Reaches | Tabs available |
|---|---|---|
| **Serial** | a node on USB-C | all |
| **Bluetooth** | a node in BLE range | all |
| **WebSocket** | a node on the LAN | all |
| **RNS (via LCS MeshChat)** | any node on the mesh, any distance | Node Status, Transport Config |

Over Reticulum, Logs and Node Config are hidden because they rely on legacy KISS
frames that do not cross the Reticulum hop. Everything else — status, transport
configuration, the Reticulum namespace, reboot — works the same at 500 km as it
does over a cable.

A node only answers remote management requests from identities on its allow list,
and that list can only be set over a wired connection. The console spells the
one-time step out when you pick the RNS transport. See
[rns-console-bridge.md](rns-console-bridge.md).

---

## Verifying the setup

Check that the proxy reaches the app:

```sh
curl -skI https://liberty.local:8443/api/v1/app/info
```

`200 OK` means the proxy is routing correctly. For more detail:

```sh
curl -sk https://liberty.local:8443/api/v1/app/info
# {"version":"1.9.6", ..., "is_docker":true}
```

Check that the RNS bridge is up:

```sh
curl -skI https://liberty.local:8443/rns/health
```

Check that the proxy will actually upgrade a WebSocket:

```sh
curl -skI -o /dev/null -w '%{http_code}\n' \
  -H 'Connection: Upgrade' -H 'Upgrade: websocket' \
  -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
  -H 'Origin: https://liberty.local:8443' \
  https://liberty.local:8443/rns/ws
# 101
```

`101` means the whole server-side chain — container, proxy, bridge, origin check —
is working. Anything else is a server-side problem; see below.

Then open the app in a browser. If Docker is being detected properly, the **Add LCS
Interfaces** button is **absent** from the header — that button only appears on
desktop installs. Its absence confirms the browser audio bridge is active.

To confirm the microphone is available, open the browser console (F12) and run:

```js
navigator.mediaDevices.getUserMedia({ audio: true })
  .then(() => console.log("microphone OK"))
  .catch(e => console.log("microphone blocked:", e.name));
```

---

## Troubleshooting

### The console says "RNS bridge not found"

First find out which side is at fault, with the `101` check above.

**If `curl` returns `101` but the browser still fails**, the server is fine and the
browser is refusing the upgrade. The console says so in that case, and the usual
cause is the **self-signed certificate**: accepting the warning for a page does not
reliably carry over to a `wss://` connection on the same host. Open

```
https://liberty.local:8443/rns/health
```

in a new tab, accept the certificate there, and reload the console. If it still
fails, install the certificate as trusted on the device, or put a real domain name
and a Let's Encrypt certificate in front of the proxy.

Either way you are never stuck: the failure banner has a box to type the address
into directly.

```
wss://liberty.local:8443/rns/ws
```

**If `curl` does not return `101`**, the proxy is not upgrading. Check
`proxy_http_version 1.1` and the `Upgrade` / `Connection` headers — the same headers
the audio bridge needs.

**To see exactly what was tried**, open the browser console and read:

```js
__lcsBridgeDiscovery
// { candidates: [...], failures: [{url, reason}], found: null }
```

`reason` distinguishes `refused` (nothing listening, or TLS rejected) from
`timeout`, from `no-pong` (something is listening on that address, but it is not
this bridge).

### Calls connect but there is no audio

Almost always the WebSocket headers. `proxy_http_version 1.1` plus `Upgrade` and
`Connection` are what let the audio bridge at
`/api/v1/telephone/audio-bridge` work. Without them a call connects and no audio
passes in either direction.

Otherwise: the page is not in a secure context (check for `https://` in the address
bar), or the browser has not been granted microphone permission.

### The app loads but the API calls fail

#### Always use the hostname, not the IP address

The certificate is issued for a hostname (`liberty.local`). Browsing to
`https://192.168.2.1:8443` instead can make the browser silently block the app's API
and WebSocket requests even after the certificate warning is accepted — the page
loads, nothing else works. The `subjectAltName` in the commands above covers both
the hostname and the IP, but the hostname remains the reliable choice.

### Nothing at all on port 8443

Check the container is up (`docker compose ps`), that nginx is running and that the
firewall allows 8443 from the LAN. On OpenWrt, `nginx -t -c /etc/nginx/uci.conf` —
plain `nginx -t` reads a different file and will report success on a config that is
not the one being served.

---

## Security notes

**The bridge is reachable directly on port 8082.** `--host=0.0.0.0` inside the
container means the published port bypasses the proxy entirely. Browsers are stopped
by the origin check, but a scripted client can send any `Origin` it likes, and the
RNS bridge can reboot and reconfigure remote nodes.

Either publish the container port on loopback only, so all traffic has to go through
the HTTPS proxy:

```yaml
ports:
  - 127.0.0.1:8082:8000
```

or add a shared secret to the command:

```
--rns-bridge-token SECRET
```

and append `?token=SECRET` to the console's WebSocket address.

**Self-signed certificates show a browser warning.** Accept it once per device, or
install the certificate as trusted, or use Let's Encrypt with a real domain name.

**Blocking is identity-scoped and local.** Published blackhole lists are advisory:
subscribing to one applies it to your own network segments, it does not propagate.
