// Checks the candidate list the mDNS-style sweep generates.
//
//   node tools/console/test_local_sweep.mjs
//
// Scope, and why it stops here: the probe machinery -- opening a socket,
// ping/pong, filling the console's field in, remembering the winner -- is
// covered end to end against a real server by test_bridge_discovery.mjs. What
// that test cannot cover is a bridge on another host, because Chromium applies
// --host-resolver-rules to navigations and fetches but not to WebSocket
// connections, and sends .local lookups through the system mDNS resolver on
// top of that. A swept hostname is therefore unreachable from any sandbox,
// however it is mapped.
//
// So this test asserts the part that is checkable without a network: that
// every address the sweep is supposed to try is in the list it publishes on
// window.__lcsBridgeDiscovery.candidates, in the right order, with the right
// scheme for the page it is running on.

import http from "http";
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

const DOCUMENTED = [
  "liberty.local", "meshchat.local", "lcs.local", "reticulum-meshchat.local",
  "rns.local", "openwrt.local", "raspberrypi.local", "nas.local"
];

const fail = [], ok = [];
function check(name, cond) {
  (cond ? ok : fail).push(name);
  console.log(`${cond ? "  ok  " : " FAIL "} ${name}`);
}

// Serve the console so the page has a real http:// origin.
const server = http.createServer((req, res) => {
  res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  res.end(fs.readFileSync(consoleFile));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const port = server.address().port;

const browser = await chromium.launch();

async function candidatesFor(query) {
  const page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${port}/transport-console/index.html${query}`);
  await page.waitForFunction(
    () => window.__lcsBridgeDiscovery && window.__lcsBridgeDiscovery.candidates,
    { timeout: 15000 });
  const c = await page.evaluate(() => window.__lcsBridgeDiscovery.candidates);
  await page.close();
  return c;
}

const c = await candidatesFor("");
console.log("    candidates: " + c.length);

check("same origin is tried first",
  c[0] === `ws://127.0.0.1:${port}/rns/ws`);

check("every documented .local name is swept on the proxy port 8443",
  DOCUMENTED.every((h) => c.includes(`wss://${h}:8443/rns/ws`)));

check("the proxy port is only ever tried over TLS",
  !c.some((u) => u.startsWith("ws://") && u.includes(":8443")));

check("documented names are also tried on the published container ports",
  DOCUMENTED.every((h) =>
    [8000, 8082, 8080, 9337].every((p) => c.includes(`ws://${h}:${p}/rns/ws`))));

check("documented names are tried on plain 443 for a real domain",
  DOCUMENTED.every((h) => c.includes(`wss://${h}/rns/ws`)));

check("loopback is not swept a second time as a LAN host",
  !c.some((u) => /^wss:\/\/(localhost|127\.0\.0\.1)/.test(u)));

check("loopback ports are still covered by their own tier",
  [9337, 8000, 8080, 4000].every((p) =>
    c.includes(`ws://localhost:${p}/rns/ws`) && c.includes(`ws://127.0.0.1:${p}/rns/ws`)));

check("the legacy /ws path is still tried on 9337",
  c.includes("ws://localhost:9337/ws") && c.includes("ws://127.0.0.1:9337/ws"));

check("loopback is tried before the LAN sweep",
  c.indexOf("ws://127.0.0.1:9337/rns/ws") < c.indexOf("wss://liberty.local:8443/rns/ws"));

check("no duplicates", new Set(c).size === c.length);

// ?hosts=
const c2 = await candidatesFor("?hosts=myrouter.local,depot.example");
check("?hosts= names are added to the sweep",
  c2.includes("wss://myrouter.local:8443/rns/ws") &&
  c2.includes("wss://depot.example:8443/rns/ws"));
check("?hosts= names are swept before the built-in ones",
  c2.indexOf("wss://myrouter.local:8443/rns/ws") <
  c2.indexOf("wss://liberty.local:8443/rns/ws"));

// ?ws= and ?token=
const c3 = await candidatesFor("?ws=wss://elsewhere.example/rns/ws");
check("?ws= wins outright", c3[0] === "wss://elsewhere.example/rns/ws");

const c4 = await candidatesFor("?token=sekrit");
check("?token= is appended to every candidate",
  c4.every((u) => u.includes("token=sekrit")));

// remembered hosts
const page = await browser.newPage();
await page.goto(`http://127.0.0.1:${port}/transport-console/index.html`);
await page.evaluate(() => localStorage.setItem(
  "meshchat_rns_known_hosts", JSON.stringify(["depot.local:8443"])));
await page.goto(`http://127.0.0.1:${port}/transport-console/index.html`);
await page.waitForFunction(
  () => window.__lcsBridgeDiscovery && window.__lcsBridgeDiscovery.candidates,
  { timeout: 15000 });
const c5 = await page.evaluate(() => window.__lcsBridgeDiscovery.candidates);
check("a remembered host is swept before the built-in names",
  c5.some((u) => u.includes("depot.local:8443")) &&
  c5.findIndex((u) => u.includes("depot.local")) <
  c5.findIndex((u) => u.includes("liberty.local")));
await page.close();

await browser.close();
server.close();

console.log(`\n${ok.length} passed, ${fail.length} failed`);
if (fail.length) { for (const f of fail) console.log("  FAILED: " + f); process.exit(1); }
