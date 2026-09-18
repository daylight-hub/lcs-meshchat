// Drives the real shipped console in a headless browser and asserts that the
// LCS additions actually attach. The previous generation of these scripts
// queried selectors that existed nowhere in the bundle and shipped twice
// without anyone noticing, because nothing ever loaded the page.
//
//   node tools/console/test_console_extras.mjs
//
// The console needs a live node to render Transport Config on its own, so the
// test synthesises the exact markup the bundle produces (verified against the
// minified source: .tab-body.config-tab.no-pad > .sidenav + .sidenav-detail,
// field rows as .field > label > span plus .field > div > input) and checks
// that the MutationObserver-driven code finds it.

import { fileURLToPath } from "url";
import path from "path";
import { createRequire } from "module";

// playwright may only be installed globally on a build box
const require_ = createRequire(import.meta.url);
let chromium;
try {
  ({ chromium } = await import("playwright"));
} catch {
  const { execSync } = await import("child_process");
  const root = execSync("npm root -g", { encoding: "utf-8" }).trim();
  const mod = await import("file://" + path.join(root, "playwright", "index.js"));
  chromium = (mod.chromium || (mod.default && mod.default.chromium));
}
void require_;

const here = path.dirname(fileURLToPath(import.meta.url));
const page_url =
  "file://" + path.resolve(here, "../../src/frontend/public/transport-console/index.html");

const fail = [];
const ok = [];
function check(name, cond) {
  (cond ? ok : fail).push(name);
  console.log(`${cond ? "  ok  " : " FAIL "} ${name}`);
}

const browser = await chromium.launch();
const page = await browser.newPage();
page.on("pageerror", (e) => fail.push("page error: " + e.message));
await page.goto(page_url);
await page.waitForTimeout(400);

// ---- the console's own anchors are where the scripts expect ----------------

check("bridge URL field present",
  await page.locator('input[title="LCS MeshChat WebSocket URL"]').count() === 1);
check("transport select present",
  await page.locator(".topbar select").count() === 1);
check("Transport Config tab present",
  await page.locator('.tabbar button', { hasText: "Transport Config" }).count() === 1);
check("single .body host present",
  await page.locator(".body").count() === 1);

// ---- put the page into the state the preset row needs ----------------------

await page.evaluate(() => {
  // Transport "RNS (via LCS MeshChat)"
  const sel = document.querySelector(".topbar select");
  sel.value = "rns";
  sel.dispatchEvent(new Event("change", { bubbles: true }));

  // Make Transport Config the active tab, the way the bundle does.
  for (const b of document.querySelectorAll(".tabbar button")) {
    b.style.display = "";
    b.disabled = false;
    b.classList.toggle("active", b.textContent.trim() === "Transport Config");
  }

  // Reproduce the namespace detail pane exactly as pt()/ft()/dt() build it.
  const mk = (tag, cls, kids = []) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    for (const k of kids) n.appendChild(typeof k === "string" ? document.createTextNode(k) : k);
    return n;
  };
  const field = (label, { type = "number", unit = null, value = "" } = {}) => {
    const row = mk("div", "field");
    const lab = mk("label");
    lab.appendChild(mk("span", null, [label]));
    lab.appendChild(mk("span"));
    row.appendChild(lab);
    const holder = mk("div");
    const input = document.createElement("input");
    input.type = type;
    input.value = value;
    holder.appendChild(input);
    if (unit) holder.appendChild(mk("span", "unit", [unit]));
    row.appendChild(holder);
    row.appendChild(mk("div", "err"));
    return row;
  };

  const tab = mk("div", "tab-body config-tab no-pad");
  const nav = mk("div", "sidenav");
  for (const name of ["Reticulum", "RNode radio config", "Display"]) {
    const b = mk("button", "sidenav-btn" + (name === "RNode radio config" ? " active" : ""));
    b.appendChild(mk("span", null, [name]));
    b.appendChild(mk("span", "dot"));
    nav.appendChild(b);
  }
  const detail = mk("div", "sidenav-detail");
  const inner = mk("div");
  inner.appendChild(mk("h2", "ns-h", ["RNode radio config"]));
  inner.appendChild(mk("div", "ns-toolbar"));
  const group = mk("div", "ns-sub-fields");
  group.appendChild(field("Frequency", { unit: "Hz", value: "914875000" }));
  group.appendChild(field("Bandwidth", { unit: "Hz", value: "250000" }));
  group.appendChild(field("Spreading factor", { value: "11" }));
  group.appendChild(field("Coding rate", { value: "5" }));
  group.appendChild(field("TX power", { unit: "dBm", value: "17" }));
  inner.appendChild(group);
  detail.appendChild(inner);
  tab.appendChild(nav);
  tab.appendChild(detail);

  const body = document.querySelector(".body");
  body.innerHTML = "";
  body.appendChild(tab);
});

await page.waitForTimeout(700);

// ---- the additions attached ------------------------------------------------

check("preset row inserted", await page.locator("#lcs-preset-row").count() === 1);
check("radio warning inserted", await page.locator("#lcs-radio-warning").count() === 1);
check("setup notice inserted", await page.locator("#lcs-rns-setup").count() === 1);

check("preset row sits directly above the frequency field",
  await page.evaluate(() => {
    const row = document.querySelector("#lcs-preset-row");
    const next = row && row.nextElementSibling;
    return !!next && /frequenc/i.test(next.querySelector("label span").textContent);
  }));

check("preset row is inside the radio field group",
  await page.evaluate(() =>
    !!document.querySelector(".ns-sub-fields #lcs-preset-row")));

const presetCount = await page.locator("#lcs-preset-row select option").count();
check(`preset dropdown has all 13 presets (+placeholder) [${presetCount}]`, presetCount === 14);

check("'Average - Recommended for Speed' present",
  await page.locator('#lcs-preset-row select option', {
    hasText: "Average - Recommended for Speed" }).count() === 1);

// ---- selecting a preset writes the fields ---------------------------------

await page.evaluate(() => { window.confirm = () => true; });
const longSlow = await page.evaluate(() => {
  const o = [...document.querySelectorAll("#lcs-preset-row select option")]
    .find((x) => /Long Slow/.test(x.textContent));
  return o ? o.value : null;
});
check("Long Slow preset exists", longSlow !== null);
await page.selectOption("#lcs-preset-row select", longSlow);
await page.waitForTimeout(150);

const values = await page.evaluate(() => {
  const out = {};
  for (const row of document.querySelectorAll(".ns-sub-fields .field")) {
    if (row.id === "lcs-preset-row") continue;
    const label = row.querySelector("label span").textContent.trim();
    out[label] = row.querySelector("input").value;
  }
  return out;
});
console.log("    field values after preset:", JSON.stringify(values));

check("frequency written in Hz (unit-aware)", values["Frequency"] === "914875000");
check("bandwidth written in Hz (unit-aware)", values["Bandwidth"] === "125000");
check("spreading factor written", values["Spreading factor"] === "12");
check("coding rate written", values["Coding rate"] === "8");
check("unrelated field untouched", values["TX power"] === "17");

// ---- the preset row does NOT appear on a non-radio namespace ---------------

await page.evaluate(() => {
  const group = document.querySelector(".ns-sub-fields");
  group.innerHTML = "";
  const row = document.createElement("div");
  row.className = "field";
  const lab = document.createElement("label");
  const sp = document.createElement("span");
  sp.textContent = "Announce frequency";
  lab.appendChild(sp);
  row.appendChild(lab);
  const d = document.createElement("div");
  const i = document.createElement("input");
  i.type = "number";
  d.appendChild(i);
  row.appendChild(d);
  group.appendChild(row);
  document.querySelector("#lcs-preset-row")?.remove();
  document.querySelector(".sidenav-detail h2").textContent = "Reticulum";
});
await page.waitForTimeout(500);
check("no preset row on a namespace with only 'Announce frequency'",
  await page.locator("#lcs-preset-row").count() === 0);

// ---- and not on Node Config, which renders the same classes ----------------

await page.evaluate(() => {
  for (const b of document.querySelectorAll(".tabbar button")) {
    b.classList.toggle("active", b.textContent.trim() === "Node Config");
  }
});
await page.waitForTimeout(400);
check("radio warning removed when Transport Config is not the active tab",
  await page.locator("#lcs-radio-warning").count() === 0);

await browser.close();

console.log(`\n${ok.length} passed, ${fail.length} failed`);
if (fail.length) {
  for (const f of fail) console.log("  FAILED: " + f);
  process.exit(1);
}
