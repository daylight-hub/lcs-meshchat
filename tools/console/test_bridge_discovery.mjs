// Serves the real console over HTTP next to a stand-in bridge that speaks the
// same ping/pong handshake as src/backend/rns_link_bridge.py, then checks that
// the auto-discovery script finds it and fills the console's own field in.
//
//   node tools/console/test_bridge_discovery.mjs
//
// This is the path that failed behind the Docker reverse proxy: the console is
// served from the same origin as the bridge, so discovery must settle on
// <same origin>/rns/ws on its first try. Everything here is stdlib -- a
// hand-rolled WebSocket server, because the point is to test the browser side.

import http from "http";
import crypto from "crypto";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const here = path.dirname(fileURLToPath(import.meta.url));
const consoleFile = path.resolve(here, "../../src/frontend/public/transport-console/index.html");

let chromium;
try {
  ({ chromium } = await import("playwright"));
} catch {
  const { execSync } = await import("child_process");
  const root = execSync("npm root -g", { encoding: "utf-8" }).trim();
  const mod = await import("file://" + path.join(root, "playwright", "index.js"));
  chromium = mod.chromium || (mod.default && mod.default.chromium);
}

// --- minimal WebSocket server ------------------------------------------------

const GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

function decodeFrames(buf) {
  const out = [];
  let i = 0;
  while (i + 2 <= buf.length) {
    const opcode = buf[i] & 0x0f;
    const masked = (buf[i + 1] & 0x80) !== 0;
    let len = buf[i + 1] & 0x7f;
    let j = i + 2;
    if (len === 126) { len = buf.readUInt16BE(j); j += 2; }
    else if (len === 127) { len = Number(buf.readBigUInt64BE(j)); j += 8; }
    let mask = null;
    if (masked) { mask = buf.subarray(j, j + 4); j += 4; }
    if (j + len > buf.length) break;
    const payload = Buffer.from(buf.subarray(j, j + len));
    if (mask) for (let k = 0; k < payload.length; k++) payload[k] ^= mask[k % 4];
    out.push({ opcode, payload });
    i = j + len;
  }
  return { frames: out, rest: buf.subarray(i) };
}

function encodeText(str) {
  const payload = Buffer.from(str, "utf-8");
  let header;
  if (payload.length < 126) {
    header = Buffer.from([0x81, payload.length]);
  } else {
    header = Buffer.alloc(4);
    header[0] = 0x81; header[1] = 126;
    header.writeUInt16BE(payload.length, 2);
  }
  return Buffer.concat([header, payload]);
}

const seen = { upgrades: [], origins: [] };

const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://" + req.headers.host);
  if (url.pathname === "/rns/health") {
    res.writeHead(200, { "content-type": "application/json" });
    return res.end(JSON.stringify({ ok: true, backend: "test" }));
  }
  if (url.pathname === "/transport-console/index.html" || url.pathname === "/") {
    res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    return res.end(fs.readFileSync(consoleFile));
  }
  res.writeHead(404).end("nope");
});

server.on("upgrade", (req, socket) => {
  const url = new URL(req.url, "http://" + req.headers.host);
  seen.upgrades.push(url.pathname);
  seen.origins.push(req.headers.origin || "");

  if (url.pathname !== "/rns/ws") {
    socket.end("HTTP/1.1 404 Not Found\r\n\r\n");
    return;
  }
  const accept = crypto.createHash("sha1")
    .update(req.headers["sec-websocket-key"] + GUID).digest("base64");
  socket.write(
    "HTTP/1.1 101 Switching Protocols\r\n" +
    "Upgrade: websocket\r\nConnection: Upgrade\r\n" +
    "Sec-WebSocket-Accept: " + accept + "\r\n\r\n");

  let buf = Buffer.alloc(0);
  socket.on("data", (chunk) => {
    buf = Buffer.concat([buf, chunk]);
    const { frames, rest } = decodeFrames(buf);
    buf = rest;
    for (const f of frames) {
      if (f.opcode === 0x8) return socket.end();
      if (f.opcode !== 0x1) continue;
      let msg;
      try { msg = JSON.parse(f.payload.toString("utf-8")); } catch { continue; }
      if (msg && msg.type === "ping") {
        socket.write(encodeText(JSON.stringify({ type: "pong", t: Date.now() / 1000 })));
      }
    }
  });
  socket.on("error", () => {});
});

await new Promise((r) => server.listen(0, "127.0.0.1", r));
const port = server.address().port;
const origin = `http://127.0.0.1:${port}`;

// --- drive the console -------------------------------------------------------

const fail = [], ok = [];
function check(name, cond) {
  (cond ? ok : fail).push(name);
  console.log(`${cond ? "  ok  " : " FAIL "} ${name}`);
}

const browser = await chromium.launch();
const page = await browser.newPage();
page.on("pageerror", (e) => fail.push("page error: " + e.message));
await page.goto(origin + "/transport-console/index.html");

await page.waitForFunction(
  () => {
    const b = document.getElementById("bridge-banner");
    return b && /found|not found/i.test(b.textContent);
  },
  { timeout: 20000 }
).catch(() => {});

const bannerText = await page.locator("#bridge-banner").innerText().catch(() => "");
console.log("    banner: " + bannerText.split("\n")[0]);

check("discovery succeeded", /RNS bridge found/i.test(bannerText));
check("settled on this origin's /rns/ws",
  bannerText.includes(`ws://127.0.0.1:${port}/rns/ws`));
check("bridge saw exactly one upgrade attempt", seen.upgrades.length === 1);
check("upgrade was to /rns/ws", seen.upgrades[0] === "/rns/ws");
check("browser sent the page's Origin", seen.origins[0] === origin);

check("console's WebSocket URL field was filled",
  await page.inputValue('input[title="LCS MeshChat WebSocket URL"]')
    === `ws://127.0.0.1:${port}/rns/ws`);
check("transport switched to RNS",
  await page.locator(".topbar select").inputValue() === "rns");
check("endpoint remembered for next time",
  await page.evaluate(() => localStorage.getItem("meshchat_rns_bridge_url"))
    === `ws://127.0.0.1:${port}/rns/ws`);
check("host remembered for the .local sweep",
  JSON.parse(await page.evaluate(() => localStorage.getItem("meshchat_rns_known_hosts")) || "[]")
    .includes(`127.0.0.1:${port}`));

// --- failure path: nothing listening ----------------------------------------

const page2 = await browser.newPage();
await page2.goto("about:blank");
await page2.goto(origin + "/transport-console/index.html?ws=ws://127.0.0.1:1/rns/ws");
// ?ws= wins, everything else is still swept, so this exercises the whole
// candidate chain including the .local names before giving up.
await page2.waitForSelector("#bridge-banner", { timeout: 30000 }).catch(() => {});
await page2.waitForFunction(
  () => /not found|found/i.test(document.getElementById("bridge-banner")?.textContent || ""),
  { timeout: 40000 }
).catch(() => {});
const t2 = await page2.locator("#bridge-banner").innerText().catch(() => "");
// same-origin is in the candidate list, so this one should still succeed --
// which is exactly the behaviour that matters: a stale ?ws= does not strand you.
check("a dead ?ws= override falls through to the working same-origin endpoint",
  /RNS bridge found/i.test(t2));

await browser.close();
server.close();

console.log(`\n${ok.length} passed, ${fail.length} failed`);
if (fail.length) {
  for (const f of fail) console.log("  FAILED: " + f);
  process.exit(1);
}
