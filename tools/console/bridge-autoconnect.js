(function () {
  "use strict";

  // ---------------------------------------------------------------------
  // LCS MeshChat RNS bridge auto-discovery
  //
  // Replaces the hard-coded wss://127.0.0.1:9337/ws default with a probe of
  // the endpoints MeshChat can actually be listening on, in the order most
  // likely to work in the browser the console is currently running in.
  //
  // Three tiers, tried in order:
  //   1. explicit / remembered / same-origin   (serial, fast)
  //   2. loopback                              (serial, fast)
  //   3. LAN + mDNS .local sweep               (parallel, bounded)
  //
  // Probe handshake is the same one the RNS transport itself uses: open the
  // socket, send {"type":"ping"}, expect {"type":"pong"}.
  // ---------------------------------------------------------------------

  var LS_KEY = "meshchat_rns_bridge_url";      // last known-good endpoint
  var LS_HOSTS = "meshchat_rns_known_hosts";   // hosts that have worked before
  var PROBE_TIMEOUT_LOCAL = 1500;
  var PROBE_TIMEOUT_LAN = 3000;
  var SWEEP_CONCURRENCY = 8;

  var MESHCHAT_PORTS = [9337, 8000, 8080, 4000];
  var BRIDGE_PORTS = [9337];
  var PROXY_PORTS = [8443];            // the HTTPS reverse proxy in front of Docker
  var MESHCHAT_PATH = "/rns/ws";
  var BRIDGE_PATH = "/ws";
  var HEALTH_PATH = "/rns/health";

  // Browsers cannot enumerate mDNS, so a .local sweep has to guess names. These
  // are the ones the LCS documentation tells people to use, plus the usual
  // appliance hostnames a MeshChat container tends to live behind.
  var LOCAL_NAMES = [
    "liberty.local",
    "meshchat.local",
    "lcs.local",
    "reticulum-meshchat.local",
    "rns.local",
    "openwrt.local",
    "raspberrypi.local",
    "nas.local"
  ];

  var params = new URLSearchParams(location.search);
  var isHttps = location.protocol === "https:";
  var isFile = location.protocol === "file:";
  var ua = navigator.userAgent;
  var isSafari = /^((?!chrome|chromium|android|crios|fxios).)*safari/i.test(ua);
  var isFirefox = /firefox|fxios/i.test(ua);
  var isChromium = !isSafari && !isFirefox;

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      if (k === "style") { for (var s in attrs.style) n.style[s] = attrs.style[s]; }
      else if (k === "html") { n.innerHTML = attrs[k]; }
      else n.setAttribute(k, attrs[k]);
    }
    (kids || []).forEach(function (c) {
      n.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return n;
  }

  function lsGet(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }
  function lsSet(key, val) {
    try { localStorage.setItem(key, val); } catch (e) {}
  }
  function knownHosts() {
    var raw = lsGet(LS_HOSTS);
    if (!raw) return [];
    try {
      var a = JSON.parse(raw);
      return Array.isArray(a) ? a.filter(function (x) { return typeof x === "string"; }) : [];
    } catch (e) { return []; }
  }
  function rememberHost(url) {
    var host;
    try { host = new URL(url).host; } catch (e) { return; }
    if (!host) return;
    var list = knownHosts().filter(function (h) { return h !== host; });
    list.unshift(host);
    lsSet(LS_HOSTS, JSON.stringify(list.slice(0, 12)));
  }

  function isLoopbackHost(host) {
    var h = String(host || "").replace(/:\d+$/, "").toLowerCase();
    return h === "localhost" || h === "127.0.0.1" || h === "::1" || h === "[::1]";
  }

  function withToken(url) {
    var token = params.get("token");
    if (!token || url.indexOf("token=") >= 0) return url;
    return url + (url.indexOf("?") >= 0 ? "&" : "?") + "token=" + encodeURIComponent(token);
  }

  // ---------------------------------------------------------------------
  // candidate tiers
  // ---------------------------------------------------------------------

  function tierExplicit() {
    var out = [];
    if (params.get("ws")) out.push(params.get("ws"));
    var cached = lsGet(LS_KEY);
    if (cached) out.push(cached);
    // Same origin. This is MeshChat serving the console itself, directly or
    // through the HTTPS reverse proxy, and it is the only arrangement that
    // works in every browser: no mixed content, no separate TLS prompt, no
    // local-network-access permission.
    if (!isFile && location.host) {
      out.push((isHttps ? "wss://" : "ws://") + location.host + MESHCHAT_PATH);
    }
    if (params.get("port")) {
      out.push("ws://localhost:" + params.get("port") + MESHCHAT_PATH);
      out.push("ws://localhost:" + params.get("port") + BRIDGE_PATH);
    }
    return out;
  }

  function tierLoopback() {
    var out = [];
    // Hostname "localhost" before the 127.0.0.1 literal: Firefox exempts the
    // localhost *hostname* from mixed-content blocking and is less consistent
    // about the raw loopback IP.
    var schemes = isHttps ? ["ws", "wss"] : ["ws"];
    schemes.forEach(function (scheme) {
      MESHCHAT_PORTS.forEach(function (p) {
        out.push(scheme + "://localhost:" + p + MESHCHAT_PATH);
        out.push(scheme + "://127.0.0.1:" + p + MESHCHAT_PATH);
      });
      BRIDGE_PORTS.forEach(function (p) {
        out.push(scheme + "://localhost:" + p + BRIDGE_PATH);
        out.push(scheme + "://127.0.0.1:" + p + BRIDGE_PATH);
      });
    });
    return out;
  }

  // Tier 3: the Docker case. MeshChat is on another box on the LAN, behind the
  // HTTPS reverse proxy on 8443, reached by an mDNS .local name.
  function tierSweep() {
    var out = [];
    var hosts = [];

    function addHost(h) {
      if (h && hosts.indexOf(h) < 0) hosts.push(h);
    }

    // Names the user supplied on the query string win.
    (params.get("hosts") || "").split(",").forEach(function (h) {
      addHost(h.trim().toLowerCase());
    });

    // Hosts that have answered before, on this browser.
    knownHosts().forEach(function (h) { addHost(h.toLowerCase()); });

    // The page's own hostname, on the proxy port as well as its own. Covers
    // "console served from somewhere else on the same appliance".
    if (!isFile && location.hostname) addHost(location.hostname.toLowerCase());

    // The documented names.
    LOCAL_NAMES.forEach(addHost);

    // If the page itself is on a .local name, try the short form and the other
    // documented names under the same suffix.
    if (/\.local$/i.test(location.hostname || "")) {
      var stem = location.hostname.replace(/\.local$/i, "");
      addHost(stem + ".local");
    }

    hosts.forEach(function (h) {
      if (!h || isLoopbackHost(h)) return;

      // Reverse proxy: always wss, because the proxy exists to terminate TLS.
      PROXY_PORTS.forEach(function (p) {
        out.push("wss://" + h + ":" + p + MESHCHAT_PATH);
      });

      // Plain HTTP publish of the container port. An https page cannot reach
      // these at all (mixed content), so only offer them from an http page.
      if (!isHttps) {
        [8000, 8082, 8080, 9337].forEach(function (p) {
          out.push("ws://" + h + ":" + p + MESHCHAT_PATH);
        });
      }

      // Standard 443 behind a real domain name.
      out.push("wss://" + h + MESHCHAT_PATH);
    });

    return out;
  }

  function dedupe(list) {
    var seen = {}, out = [];
    list.forEach(function (u) {
      if (u && !seen[u]) { seen[u] = 1; out.push(withToken(u)); }
    });
    return out;
  }

  function allCandidates() {
    return dedupe(tierExplicit().concat(tierLoopback(), tierSweep()));
  }

  // ---------------------------------------------------------------------
  // probe
  //
  // Resolves { ok, url, reason }. `reason` separates "nothing there" from
  // "something there that would not talk", which is what makes the failure
  // banner able to say anything useful.
  // ---------------------------------------------------------------------

  function probe(url) {
    var host = "";
    try { host = new URL(url).host; } catch (e) {}
    var timeout = isLoopbackHost(host) ? PROBE_TIMEOUT_LOCAL : PROBE_TIMEOUT_LAN;

    return new Promise(function (resolve) {
      var ws, done = false, timer, opened = false;
      function finish(ok, reason) {
        if (done) return;
        done = true;
        clearTimeout(timer);
        try {
          if (ws) {
            ws.onopen = ws.onmessage = ws.onerror = ws.onclose = null;
            ws.close();
          }
        } catch (e) {}
        resolve({ ok: ok, url: url, reason: reason || "" });
      }
      try { ws = new WebSocket(url); }
      catch (e) { return resolve({ ok: false, url: url, reason: "blocked" }); }

      timer = setTimeout(function () {
        finish(false, opened ? "no-pong" : "timeout");
      }, timeout);

      ws.onopen = function () {
        opened = true;
        try { ws.send(JSON.stringify({ type: "ping" })); }
        catch (e) { finish(false, "send-failed"); }
      };
      ws.onmessage = function (ev) {
        var m = null;
        try { m = JSON.parse(typeof ev.data === "string" ? ev.data : ""); } catch (e) {}
        if (m && m.type === "pong") finish(true, "");
      };
      ws.onerror = function () {
        finish(false, opened ? "dropped" : "refused");
      };
      ws.onclose = function (ev) {
        if (opened) return finish(false, "closed-" + (ev && ev.code));
        // 1006 before open on a wss:// URL is what an untrusted certificate,
        // a refused connection and a blocked port all look like from script.
        finish(false, "refused");
      };
    });
  }

  // Bounded-concurrency sweep. Resolves the first success, or null.
  function probeParallel(list, limit) {
    return new Promise(function (resolve) {
      var i = 0, active = 0, settled = false, failures = [];
      function next() {
        if (settled) return;
        if (i >= list.length && active === 0) {
          settled = true;
          return resolve({ found: null, failures: failures });
        }
        while (active < limit && i < list.length) {
          var url = list[i++];
          active++;
          probe(url).then(function (r) {
            active--;
            if (settled) return;
            if (r.ok) {
              settled = true;
              return resolve({ found: r.url, failures: failures });
            }
            failures.push(r);
            next();
          });
        }
      }
      next();
    });
  }

  async function probeSerial(list) {
    var failures = [];
    for (var i = 0; i < list.length; i++) {
      var r = await probe(list[i]);
      if (r.ok) return { found: r.url, failures: failures };
      failures.push(r);
    }
    return { found: null, failures: failures };
  }

  async function discover(onProgress) {
    var failures = [];

    if (onProgress) onProgress("Checking this page's own address…");
    var r = await probeSerial(dedupe(tierExplicit()));
    failures = failures.concat(r.failures);
    if (r.found) return { found: r.found, failures: failures };

    if (onProgress) onProgress("Checking this computer…");
    r = await probeSerial(dedupe(tierLoopback()));
    failures = failures.concat(r.failures);
    if (r.found) return { found: r.found, failures: failures };

    var sweep = dedupe(tierSweep());
    if (sweep.length) {
      if (onProgress) onProgress("Scanning the local network for .local names…");
      r = await probeParallel(sweep, SWEEP_CONCURRENCY);
      failures = failures.concat(r.failures);
      if (r.found) return { found: r.found, failures: failures };
    }

    return { found: null, failures: failures };
  }

  // ---------------------------------------------------------------------
  // applying the result to the console's own state
  //
  // The console keeps its state in a closure we cannot reach, but every field
  // it renders is bound with an oninput/onchange handler. Setting .value and
  // dispatching the matching event updates the store exactly as a keystroke
  // would, so nothing here depends on the console's internals.
  // ---------------------------------------------------------------------

  function setInput(node, value) {
    if (!node) return;
    node.value = value;
    node.dispatchEvent(new Event("input", { bubbles: true }));
  }
  function setSelect(node, value) {
    if (!node || node.value === value) return;
    node.value = value;
    node.dispatchEvent(new Event("change", { bubbles: true }));
  }
  function setCheckbox(node, value) {
    if (!node || node.checked === value) return;
    node.checked = value;
    node.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function fields() {
    return {
      url: document.querySelector('input[title="LCS MeshChat WebSocket URL"]'),
      dest: document.querySelector('input[title="Remote node destination hash (32 hex chars)"]'),
      aspect: document.querySelector('input[title="RNS destination aspect (dot-separated)"]'),
      ident: document.querySelector('label[title^="Send local identity"] input[type=checkbox]'),
      transport: document.querySelector(".topbar select")
    };
  }

  // ---------------------------------------------------------------------
  // diagnostics
  // ---------------------------------------------------------------------

  function banner(cls, title, lines, links, extra) {
    var app = document.getElementById("app");
    if (!app) return null;
    var old = document.getElementById("bridge-banner");
    if (old && old.parentNode) old.parentNode.removeChild(old);

    var d = el("div", {
      id: "bridge-banner",
      class: "notice",
      style: { margin: "12px", lineHeight: "1.55" }
    }, [el("strong", null, [title])]);

    (lines || []).forEach(function (t) {
      d.appendChild(el("div", { style: { marginTop: "6px" } }, [t]));
    });

    if (links && links.length) {
      var ul = el("ul", { style: { margin: "8px 0 0 18px" } });
      links.forEach(function (l) {
        var li = el("li");
        if (l.href) {
          li.appendChild(el("a", {
            href: l.href, target: "_blank", rel: "noopener",
            style: { color: "inherit" }
          }, [l.text]));
        } else {
          li.appendChild(document.createTextNode(l.text));
        }
        ul.appendChild(li);
      });
      d.appendChild(ul);
    }

    if (extra) d.appendChild(extra);

    if (cls === "ok") {
      d.style.background = "rgba(21,128,61,.12)";
      d.style.color = "var(--ok)";
    }

    app.insertBefore(d, app.firstChild);
    return d;
  }

  async function lnaState() {
    try {
      if (!navigator.permissions || !navigator.permissions.query) return null;
      var p = await navigator.permissions.query({ name: "local-network-access" });
      return p && p.state;
    } catch (e) { return null; }
  }

  // Does the bridge answer over plain HTTP on this origin? If it does but the
  // WebSocket did not, the bridge, Docker and the proxy are all fine and the
  // problem is the browser refusing the upgrade -- almost always an untrusted
  // certificate, since a cert exception accepted for the page does not always
  // carry over to a wss:// handshake.
  async function sameOriginHealth() {
    if (isFile || !location.host) return null;
    try {
      var res = await fetch(HEALTH_PATH, { cache: "no-store" });
      return res.ok;
    } catch (e) { return false; }
  }

  function manualEntry() {
    var wrap = el("div", {
      style: { marginTop: "10px", display: "flex", gap: "8px",
               alignItems: "center", flexWrap: "wrap" }
    });
    var input = el("input", {
      type: "text",
      placeholder: "wss://liberty.local:8443/rns/ws",
      style: { flex: "1 1 320px", minWidth: "260px", padding: "5px 8px",
               border: "1px solid var(--border)", borderRadius: "4px",
               background: "var(--panel)", color: "var(--ink)", font: "inherit" }
    });
    var btn = el("button", { class: "primary", style: { font: "inherit", padding: "5px 12px",
                              borderRadius: "4px", cursor: "pointer" } }, ["Use this address"]);
    var note = el("span", { style: { fontSize: "12px", opacity: ".85" } });

    async function apply() {
      var url = String(input.value || "").trim();
      if (!url) return;
      if (!/^wss?:\/\//i.test(url)) {
        note.textContent = "Address must start with ws:// or wss://";
        return;
      }
      btn.disabled = true;
      note.textContent = "Checking…";
      var r = await probe(url);
      btn.disabled = false;
      if (!r.ok) {
        note.textContent = "No answer (" + (r.reason || "failed") + "). Saved anyway — press Connect to try it.";
      } else {
        note.textContent = "Answered. Select a destination hash and click Connect.";
      }
      lsSet(LS_KEY, url);
      rememberHost(url);
      var f = fields();
      setInput(f.url, url);
      setSelect(f.transport, "rns");
    }

    btn.onclick = apply;
    input.addEventListener("keydown", function (e) { if (e.key === "Enter") apply(); });

    wrap.appendChild(el("span", { style: { fontSize: "12px", opacity: ".85" } },
                        ["Or type the address:"]));
    wrap.appendChild(input);
    wrap.appendChild(btn);
    wrap.appendChild(note);
    return wrap;
  }

  async function explainFailure(tried, failures) {
    var lines = [];
    var links = [];

    var health = await sameOriginHealth();
    var origin = location.protocol === "https:" ? "wss://" : "ws://";
    origin += location.host + MESHCHAT_PATH;

    if (health === true) {
      // The decisive case: HTTP reached the bridge on this very origin, so the
      // container, the proxy and the bridge are all healthy.
      lines.push("MeshChat answered on this address over HTTPS, but the browser would " +
        "not open a WebSocket to the same place. The container, the reverse proxy " +
        "and the bridge are all working — the browser is refusing the upgrade.");
      lines.push("The usual cause is the self-signed certificate. Accepting the warning " +
        "for a page does not always carry over to a wss:// connection. Open the link " +
        "below in a new tab, accept the certificate there, then reload this page.");
      links.push({ text: "Trust the certificate: " + location.origin + HEALTH_PATH,
                   href: location.origin + HEALTH_PATH });
      links.push({ text: "If it still fails, install the certificate as trusted on this " +
                         "device, or put a real domain name and a Let's Encrypt " +
                         "certificate in front of the proxy." });
      links.push({ text: "Address to use manually: " + origin });
    } else if (isHttps && isSafari) {
      lines.push("This page is served over https://, and Safari blocks every " +
        "mixed-content request — including ones aimed at localhost. Safari can " +
        "never reach a local bridge from an https page, no matter which port or " +
        "certificate is used.");
      links.push({ text: "Open the console from MeshChat instead: http://127.0.0.1:8000/console",
                   href: "http://127.0.0.1:8000/console" });
      links.push({ text: "Or save this page to disk and open it as a file:// page." });
    } else if (isHttps && isChromium) {
      var state = await lnaState();
      lines.push("This page is served over https://. Since Chrome 141 / Edge 142, a " +
        "public page reaching localhost needs the Local Network Access permission " +
        "(shown as “Access other apps and services on this device”)." +
        (state ? " Current permission state: " + state + "." : ""));
      links.push({ text: "Allow that permission when prompted, then reload." });
      links.push({ text: "Or open the console from MeshChat: http://127.0.0.1:8000/console",
                   href: "http://127.0.0.1:8000/console" });
    } else if (isHttps && isFirefox) {
      lines.push("This page is served over https://. Firefox exempts the localhost " +
        "hostname from mixed-content blocking but is inconsistent about the raw " +
        "127.0.0.1 literal, and now enforces its own local-network restrictions.");
      links.push({ text: "Open the console from MeshChat: http://127.0.0.1:8000/console",
                   href: "http://127.0.0.1:8000/console" });
    } else {
      lines.push("Nothing answered a ping on any of the endpoints tried, including a " +
        "sweep of the usual .local names on port 8443. MeshChat is probably not " +
        "running, is on a hostname not in the list, or was built without the RNS " +
        "bridge enabled.");
      links.push({ text: "Check the bridge is alive: http://127.0.0.1:8000/rns/health",
                   href: "http://127.0.0.1:8000/rns/health" });
      links.push({ text: "Add ?hosts=myhost.local to this URL to have the sweep include " +
                         "a name of your own, or ?ws=wss://host:port/rns/ws to skip " +
                         "discovery entirely." });
    }

    // A short, useful trace rather than the whole candidate list.
    var opened = failures.filter(function (f) {
      return f.reason === "no-pong" || f.reason === "dropped" ||
             (f.reason || "").indexOf("closed-") === 0;
    });
    if (opened.length) {
      lines.push("Opened but did not answer a ping: " +
        opened.slice(0, 4).map(function (f) { return f.url; }).join("  ·  ") +
        " — that address is a WebSocket server, but not this bridge.");
    }
    lines.push("Tried " + tried.length + " addresses, starting with " +
               tried.slice(0, 3).join("  ·  ") + (tried.length > 3 ? "  ·  …" : ""));

    banner("warn", "RNS bridge not found", lines, links, manualEntry());
  }

  // ---------------------------------------------------------------------
  // go
  // ---------------------------------------------------------------------

  async function start() {
    var f = fields();
    if (!f.url) return;   // console markup changed; leave everything alone

    // Seed anything supplied on the query string first, so a bookmarked link
    // lands on a fully configured console.
    if (params.get("dest")) setInput(f.dest, params.get("dest").trim());
    if (params.get("aspect")) setInput(f.aspect, params.get("aspect"));
    if (params.get("identify") === "0") setCheckbox(f.ident, false);

    var tried = allCandidates();

    // Support hook: open the browser console and read __lcsBridgeDiscovery to
    // see exactly what was tried and how each address failed.
    window.__lcsBridgeDiscovery = { candidates: tried, failures: null, found: null };

    var progress = banner("info", "Looking for LCS MeshChat…",
                          ["Checking this page's own address…"]);
    function note(text) {
      if (!progress || !progress.parentNode) return;
      var line = progress.querySelector("div");
      if (line) line.textContent = text;
    }

    var result = await discover(note);
    window.__lcsBridgeDiscovery.failures = result.failures;
    window.__lcsBridgeDiscovery.found = result.found;

    if (!result.found) {
      try { localStorage.removeItem(LS_KEY); } catch (e) {}
      await explainFailure(tried, result.failures);
      return;
    }

    lsSet(LS_KEY, result.found);
    rememberHost(result.found);
    setInput(f.url, result.found);

    var wanted = params.get("transport");
    if (wanted) setSelect(f.transport, wanted);
    else setSelect(f.transport, "rns");

    var b = banner("ok", "RNS bridge found", [
      "Using " + result.found + " — select a destination hash and click Connect."
    ]);
    if (b) setTimeout(function () {
      if (b.parentNode) b.parentNode.removeChild(b);
    }, 6000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { setTimeout(start, 0); });
  } else {
    setTimeout(start, 0);
  }
})();
