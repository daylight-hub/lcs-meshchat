(function () {
  "use strict";

  // -------------------------------------------------------------------
  // LCS MeshChat console extras
  //   1. One-time setup instructions while the LCS MeshChat transport is picked
  //   2. A standing warning on Transport Config against changing modem
  //      parameters on a node reached over the air
  //   3. A frequency/modem preset dropdown on the RNode radio namespace
  //
  // All three are pure DOM additions driven by the console's own controls, so
  // none of them depend on the console's internal state.
  //
  // Anchoring notes -- the console's real markup, confirmed against the
  // shipped bundle rather than assumed:
  //
  //   #app > .tabbar > button.tab[.active]        tab buttons
  //   #app > .body                                exactly one tab body at a time
  //     > .tab-body.config-tab.no-pad             Transport Config *and* Node Config
  //       > .sidenav > button.sidenav-btn[.active]
  //       > .sidenav-detail                       rebuilt on every namespace switch
  //         > div
  //           > h2.ns-h                           namespace name
  //           > .ns-toolbar                       Save / Revert / Refresh
  //           > .ns-sub-fields
  //             > .field > label > span           field label text
  //             > .field > div > input|select     the control
  //
  // Both Transport Config and Node Config render .config-tab .sidenav-detail,
  // so the active tab label is what tells them apart. Only one .body child
  // exists at a time, so there is never more than one to choose between.
  // -------------------------------------------------------------------

  var LCG1 = [{l:"Short Turbo — SF7 / 500 kHz / CR 4:5  (fastest, very short range)",f:914875000,bw:500000,sf:7,cr:5},{l:"Short Fast — SF7 / 250 kHz / CR 4:5  (★ LC: best for voice over LoRa)",f:914875000,bw:250000,sf:7,cr:5},{l:"Average - Recommended for Speed — SF8 / 250 kHz / CR 4:5  (moderate speed, short range)",f:914875000,bw:250000,sf:8,cr:5},{l:"Medium Fast — SF9 / 250 kHz / CR 4:5  (balanced speed and range)",f:914875000,bw:250000,sf:9,cr:5},{l:"Medium Slow — SF10 / 250 kHz / CR 4:5  (slower speed, medium range)",f:914875000,bw:250000,sf:10,cr:5},{l:"Long Fast — SF11 / 250 kHz / CR 4:5  (★ LCS Recommended / LC default)",f:914875000,bw:250000,sf:11,cr:5},{l:"Long Moderate — SF11 / 125 kHz / CR 4:8  (better range, slower)",f:914875000,bw:125000,sf:11,cr:8},{l:"Long Slow — SF12 / 125 kHz / CR 4:8  (maximum range, slowest)",f:914875000,bw:125000,sf:12,cr:8}];
  var LCG2 = [{l:"SF7 / 62.5 kHz / CR 4:5  — Norway narrowband",f:914875000,bw:62500,sf:7,cr:5},{l:"SF7 / 125 kHz / CR 4:5  — Italy: Brescia, Treviso",f:914875000,bw:125000,sf:7,cr:5},{l:"SF8 / 125 kHz / CR 4:5  — ★ LC US default — also 15 city presets",f:914875000,bw:125000,sf:8,cr:5},{l:"SF9 / 125 kHz / CR 4:5  — EU country default (DE, NL, IT, SE, CH, FI, BE, GB)",f:914875000,bw:125000,sf:9,cr:5},{l:"SF12 / 125 kHz / CR 4:5  — Italy Genova (max range, 125 kHz)",f:914875000,bw:125000,sf:12,cr:5}];

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      if (k === "style") { for (var p in attrs.style) n.style[p] = attrs.style[p]; }
      else if (k === "html") n.innerHTML = attrs[k];
      else n.setAttribute(k, attrs[k]);
    }
    (kids || []).forEach(function (c) {
      n.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return n;
  }

  function transportSelect() { return document.querySelector(".topbar select"); }

  function isRemote() {
    var sel = transportSelect();
    return !!sel && sel.value === "rns";
  }

  function activeTabLabel() {
    var b = document.querySelector(".tabbar button.active, .tabbar .active");
    return b ? (b.textContent || "").trim() : "";
  }

  function onTransportConfig() {
    return /transport config/i.test(activeTabLabel());
  }

  // The Transport Config detail pane. Returns null unless Transport Config is
  // the tab actually showing, which is what keeps these additions off Node
  // Config -- it renders the same classes.
  function configDetail() {
    if (!onTransportConfig()) return null;
    var body = document.querySelector(".body") || document;
    var detail = body.querySelector(".config-tab .sidenav-detail");
    if (!detail) detail = document.querySelector(".config-tab .sidenav-detail");
    if (!detail || detail.offsetParent === null) return null;
    return detail;
  }

  // ---- 1. setup instructions -----------------------------------------

  var SETUP_ID = "lcs-rns-setup";

  function renderSetupNotice() {
    var app = document.getElementById("app");
    if (!app || !transportSelect()) return;

    var existing = document.getElementById(SETUP_ID);
    if (!isRemote()) {
      if (existing && existing.parentNode) existing.parentNode.removeChild(existing);
      return;
    }
    if (existing) return;

    var box = el("div", {
      id: SETUP_ID, class: "notice",
      style: { margin: "12px", lineHeight: "1.55" }
    }, [el("strong", null, ["Before a node will accept you over Reticulum"])]);

    box.appendChild(el("div", { style: { marginTop: "6px" } }, [
      "A node only answers remote management requests from identities it has been " +
      "told to trust, and that list can only be set over a wired connection. " +
      "This is a one-time step per node."
    ]));

    var ol = el("ol", { style: { margin: "8px 0 0 20px" } });
    [
      "Copy your Identity Hash from LCS MeshChat (Settings → Identity). It is 32 hex characters.",
      "Connect the node over USB-C and switch this console's Transport to Serial, then Connect.",
      "Open Transport Config → Reticulum, tick Remote management enabled, and add your " +
        "Identity Hash to Remote management allowed.",
      "Save, then unplug. From now on the node is reachable from LCS MeshChat over the mesh."
    ].forEach(function (t) { ol.appendChild(el("li", { style: { marginTop: "3px" } }, [t])); });
    box.appendChild(ol);

    box.appendChild(el("div", { style: { marginTop: "8px", opacity: ".85" } }, [
      "Skipping this gives a link that reaches Connected and then fails every request."
    ]));

    var banner = document.getElementById("bridge-banner");
    if (banner && banner.parentNode === app) app.insertBefore(box, banner.nextSibling);
    else app.insertBefore(box, app.firstChild);
  }

  // ---- 2. modem parameter warning on Transport Config ------------------

  var RADIO_WARN_ID = "lcs-radio-warning";

  function renderRadioWarning() {
    var detail = configDetail();
    var existing = document.getElementById(RADIO_WARN_ID);
    var wanted = isRemote() && !!detail;

    if (!wanted) {
      if (existing && existing.parentNode) existing.parentNode.removeChild(existing);
      return;
    }
    if (existing && existing.parentNode === detail) return;
    if (existing && existing.parentNode) existing.parentNode.removeChild(existing);

    var w = el("div", {
      id: RADIO_WARN_ID, class: "notice",
      style: { margin: "0 0 12px 0", lineHeight: "1.55" }
    }, [el("strong", null, ["Do not change radio parameters over Reticulum"])]);

    w.appendChild(el("div", { style: { marginTop: "6px" } }, [
      "Frequency, bandwidth, spreading factor and coding rate are how this node " +
      "reaches the mesh you are talking to it through. Change one and the node " +
      "applies it, stops matching everything around it, and goes silent — with " +
      "no path left to undo it. Recovering means physically reaching the node " +
      "with a USB-C cable."
    ]));
    w.appendChild(el("div", { style: { marginTop: "6px" } }, [
      "Everything else on this tab is safe to change remotely. For modem " +
      "parameters, connect over Serial instead."
    ]));

    detail.insertBefore(w, detail.firstChild);
  }

  // ---- 3. frequency presets on the RNode radio namespace ---------------

  var PRESET_ID = "lcs-preset-row";

  // Transport Config is rendered from a schema the node supplies, so field
  // names are not known ahead of time. Match on the visible label instead.
  var MATCHERS = [
    { key: "f",  re: /frequenc|(^|[^a-z])freq([^a-z]|$)/i },
    { key: "bw", re: /bandwidth|(^|[^a-z])bw([^a-z]|$)/i },
    { key: "sf", re: /spread|(^|[^a-z])sf([^a-z]|$)/i },
    { key: "cr", re: /coding|(^|[^a-z])cr([^a-z]|$)/i }
  ];

  // A .field row is `<div class="field"><label><span>Label</span>…</label>…`.
  // Read only the first span so badge text ("read-only", "secret") cannot
  // pollute the match.
  function rowLabel(row) {
    var label = row.querySelector("label");
    if (!label) return "";
    var span = label.querySelector("span");
    return ((span ? span.textContent : label.textContent) || "").trim();
  }

  function rowUnit(row) {
    var u = row.querySelector(".unit");
    return u ? (u.textContent || "").trim().toLowerCase() : "";
  }

  function findFields(root) {
    var found = {};
    if (!root) return found;
    var rows = root.querySelectorAll(".field");
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].id === PRESET_ID) continue;
      var input = rows[i].querySelector("input, select");
      if (!input || input.type === "checkbox") continue;
      if (rows[i].classList.contains("ro-info")) continue;   // read-only display
      var text = rowLabel(rows[i]);
      if (!text) continue;
      for (var m = 0; m < MATCHERS.length; m++) {
        var key = MATCHERS[m].key;
        if (!found[key] && MATCHERS[m].re.test(text)) {
          found[key] = { input: input, row: rows[i], unit: rowUnit(rows[i]) };
        }
      }
    }
    return found;
  }

  // The preset row belongs on the radio namespace only, not on Reticulum or
  // any other namespace that happens to mention a frequency. Require the
  // frequency field plus at least one other modem parameter.
  function isRadioNamespace(found) {
    return !!found.f && !!(found.bw || found.sf || found.cr);
  }

  function setField(node, value) {
    if (!node) return false;
    node.value = String(value);
    node.dispatchEvent(new Event("input", { bubbles: true }));
    node.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  // A node may express these in Hz, kHz or MHz depending on its schema. Prefer
  // the unit the schema declares; fall back to matching the magnitude already
  // in the box; fall back again to raw Hz.
  function scaleFor(field, hz, ceilingForDivided, divisor) {
    var unit = field.unit;
    if (unit) {
      if (/^m/.test(unit)) return hz / 1e6;        // MHz
      if (/^k/.test(unit)) return hz / 1e3;        // kHz
      if (/hz$/.test(unit)) return hz;             // Hz
    }
    var current = parseFloat(field.input.value);
    if (isFinite(current) && current > 0 && current < ceilingForDivided) {
      return hz / divisor;
    }
    return hz;
  }

  function applyPreset(preset, root) {
    var f = findFields(root);
    var applied = [], missing = [];
    if (f.f)  { setField(f.f.input,  scaleFor(f.f,  preset.f,  100000, 1e6)); applied.push("frequency"); }
    else missing.push("frequency");
    if (f.bw) { setField(f.bw.input, scaleFor(f.bw, preset.bw, 10000,  1e3)); applied.push("bandwidth"); }
    else missing.push("bandwidth");
    if (f.sf) { setField(f.sf.input, preset.sf); applied.push("SF"); } else missing.push("SF");
    if (f.cr) { setField(f.cr.input, preset.cr); applied.push("CR"); } else missing.push("CR");
    return { applied: applied, missing: missing };
  }

  var REMOTE_CONFIRM = [
    "You are connected to this node over Reticulum.",
    "",
    "Frequency, bandwidth, spreading factor and coding rate are how this node",
    "reaches the mesh you are talking to it through. If you save a change to any",
    "of them, the node applies it, stops matching everything around it, and goes",
    "silent. There is no path left to undo it, and recovering means physically",
    "reaching the node with a USB-C cable.",
    "",
    "Fill the fields in anyway?"
  ].join("\n");

  function buildPresetRow(root) {
    var sel = el("select", { style: { maxWidth: "470px", font: "inherit",
                                      padding: "4px 8px", borderRadius: "4px",
                                      border: "1px solid var(--border)",
                                      background: "var(--panel)", color: "var(--ink)" } });
    sel.appendChild(el("option", { value: "" }, ["— select a preset —"]));

    var g1 = el("optgroup", { label: "Liberty Chat modem presets @ 914.875 MHz" });
    LCG1.forEach(function (p, i) { g1.appendChild(el("option", { value: "a" + i }, [p.l])); });
    sel.appendChild(g1);

    var g2 = el("optgroup", { label: "Liberty Chat country presets @ 914.875 MHz (modem params)" });
    LCG2.forEach(function (p, i) { g2.appendChild(el("option", { value: "b" + i }, [p.l])); });
    sel.appendChild(g2);

    var note = el("span", { style: { fontSize: "12px", opacity: ".85" } });

    sel.addEventListener("change", function () {
      var v = sel.value;
      if (!v) { note.textContent = ""; return; }
      var preset = v.charAt(0) === "a" ? LCG1[+v.slice(1)] : LCG2[+v.slice(1)];
      if (!preset) return;

      if (isRemote() && !window.confirm(REMOTE_CONFIRM)) {
        sel.value = "";
        note.textContent = "Cancelled. Nothing was changed.";
        return;
      }

      var r = applyPreset(preset, root);
      if (!r.applied.length) {
        note.textContent = "No matching radio fields on this node's Transport Config.";
      } else {
        note.textContent = "Set " + r.applied.join(", ")
          + (r.missing.length ? " — no field found for " + r.missing.join(", ") : "")
          + ". Nothing has reached the node until you Save."
          + (isRemote() ? " Saving will take this node off the mesh." : "");
      }
    });

    var row = el("div", { class: "field", id: PRESET_ID });
    row.appendChild(el("label", null, [el("span", null, ["Frequency preset"])]));
    row.appendChild(el("div", {
      style: { display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap" }
    }, [sel, note]));
    return row;
  }

  function ensurePresetRow() {
    var detail = configDetail();
    if (!detail) return;
    if (detail.querySelector("#" + PRESET_ID)) return;

    var found = findFields(detail);
    if (!isRadioNamespace(found)) return;

    // Sit directly above the frequency field, inside whatever container holds
    // it, so the dropdown lands with the radio settings rather than at the top
    // of the pane.
    var anchor = found.f.row;
    if (anchor && anchor.parentNode) {
      anchor.parentNode.insertBefore(buildPresetRow(detail), anchor);
    } else {
      detail.insertBefore(buildPresetRow(detail), detail.firstChild);
    }
  }

  // ---- wire up --------------------------------------------------------

  function tick() {
    try { renderSetupNotice(); } catch (e) {}
    try { renderRadioWarning(); } catch (e) {}
    try { ensurePresetRow(); } catch (e) {}
  }

  function start() {
    var sel = transportSelect();
    if (sel) sel.addEventListener("change", tick);
    document.addEventListener("click", function (e) {
      // tab switches and namespace switches are both plain buttons
      if (e.target && e.target.closest &&
          e.target.closest(".tabbar button, .sidenav-btn")) {
        setTimeout(tick, 0);
        setTimeout(tick, 250);
      }
    }, true);
    tick();
    // the console rebuilds the detail pane on every namespace switch and on
    // every schema refresh, so re-assert rather than trying to hook its
    // render cycle
    // Namespace and schema changes replace whole subtrees (childList), but a
    // tab switch only toggles .active on a button (attributes), so watch both.
    new MutationObserver(function () {
      clearTimeout(start._t);
      start._t = setTimeout(tick, 120);
    }).observe(document.getElementById("app") || document.body,
               { childList: true, subtree: true,
                 attributes: true, attributeFilter: ["class"] });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { setTimeout(start, 0); });
  } else {
    setTimeout(start, 0);
  }
})();
