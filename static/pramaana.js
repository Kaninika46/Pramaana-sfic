/* Pramaana client script: guided form steps, GPS capture, browser-side file
 * fingerprints, device-local drafts, deadline countdowns, double-submit guard.
 * Every form also works without JavaScript (all steps are shown at once). */
(function () {
  "use strict";
  document.documentElement.classList.add("js");

  // ---------------------------------------------------------------- SHA-256
  // Pure-JS fallback for phones on plain-HTTP LAN addresses, where
  // window.crypto.subtle is unavailable. (Kept from the original app.)
  function sha256PureJS(bytes) {
    const K = [
      0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
      0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
      0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
      0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
      0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
      0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
      0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
      0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
    ];
    const rotr = (n, x) => (x >>> n) | (x << (32 - n));
    const l = bytes.length;
    const padLen = ((l + 9 + 63) & ~63);
    const buf = new Uint8Array(padLen);
    buf.set(bytes);
    buf[l] = 0x80;
    const view = new DataView(buf.buffer);
    view.setUint32(padLen - 8, Math.floor((l * 8) / 0x100000000), false);
    view.setUint32(padLen - 4, (l * 8) >>> 0, false);
    let H = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
    const W = new Uint32Array(64);
    for (let i = 0; i < padLen; i += 64) {
      for (let t = 0; t < 16; t++) W[t] = view.getUint32(i + t * 4, false);
      for (let t = 16; t < 64; t++) {
        const s0 = rotr(7, W[t - 15]) ^ rotr(18, W[t - 15]) ^ (W[t - 15] >>> 3);
        const s1 = rotr(17, W[t - 2]) ^ rotr(19, W[t - 2]) ^ (W[t - 2] >>> 10);
        W[t] = (W[t - 16] + s0 + W[t - 7] + s1) >>> 0;
      }
      let [a, b, c, d, e, f, g, h] = H;
      for (let t = 0; t < 64; t++) {
        const S1 = rotr(6, e) ^ rotr(11, e) ^ rotr(25, e);
        const ch = (e & f) ^ (~e & g);
        const t1 = (h + S1 + ch + K[t] + W[t]) >>> 0;
        const S0 = rotr(2, a) ^ rotr(13, a) ^ rotr(22, a);
        const t2 = (S0 + ((a & b) ^ (a & c) ^ (b & c))) >>> 0;
        h = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
      }
      H = H.map((v, idx) => (v + [a, b, c, d, e, f, g, h][idx]) >>> 0);
    }
    return H.map(v => v.toString(16).padStart(8, "0")).join("");
  }

  async function sha256File(file) {
    const buffer = await file.arrayBuffer();
    if (window.crypto && window.crypto.subtle) {
      const digest = await window.crypto.subtle.digest("SHA-256", buffer);
      return Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, "0")).join("");
    }
    return sha256PureJS(new Uint8Array(buffer));
  }

  function formatSize(n) {
    return n < 1048576 ? Math.round(n / 1024) + " KB" : (n / 1048576).toFixed(1) + " MB";
  }

  // Browser-side fingerprints: lets the server confirm the file arrived unchanged.
  document.querySelectorAll("form[data-hash-files]").forEach(function (form) {
    const hidden = form.querySelector("input[name=client_hashes]");
    const inputs = form.querySelectorAll("input[type=file]");
    const maxBytes = parseInt(form.dataset.maxBytes || "0", 10);
    async function refresh() {
      const all = [];
      for (const input of inputs) {
        const list = document.getElementById(input.id + "-list");
        if (list) list.textContent = "";
        for (const file of input.files) {
          const li = document.createElement("li");
          if (maxBytes && file.size > maxBytes) {
            li.textContent = file.name + " — too large (" + formatSize(file.size) + "), it will be rejected";
            li.className = "field-error";
          } else {
            li.textContent = file.name + " (" + formatSize(file.size) + ") — fingerprinting…";
            const hex = await sha256File(file);
            all.push({ name: file.name, size: file.size, sha256: hex });
            li.textContent = file.name + " (" + formatSize(file.size) + ") — SHA-256 " + hex.slice(0, 16) + "…";
          }
          if (list) list.appendChild(li);
        }
      }
      if (hidden) hidden.value = JSON.stringify(all);
    }
    inputs.forEach(i => i.addEventListener("change", refresh));
  });

  // ---------------------------------------------------------------- GPS
  document.querySelectorAll("[data-gps-button]").forEach(function (btn) {
    const status = document.getElementById("gps-status");
    const lat = document.getElementById("latitude");
    const lon = document.getElementById("longitude");
    const acc = document.getElementById("location_accuracy_m");
    const src = document.getElementById("location_source");
    btn.hidden = false;
    btn.addEventListener("click", function () {
      if (!navigator.geolocation) {
        status.textContent = "This phone or browser cannot share its location. Type the numbers instead.";
        return;
      }
      status.textContent = "Finding location… stand in or next to the field.";
      btn.setAttribute("aria-busy", "true");
      navigator.geolocation.getCurrentPosition(function (pos) {
        lat.value = pos.coords.latitude.toFixed(6);
        lon.value = pos.coords.longitude.toFixed(6);
        acc.value = Math.round(pos.coords.accuracy);
        src.value = "device_gps";
        btn.removeAttribute("aria-busy");
        status.textContent = "Location recorded from the phone (accuracy about ±" + Math.round(pos.coords.accuracy) +
          " m). Check it is the affected field, not your home.";
      }, function (err) {
        btn.removeAttribute("aria-busy");
        status.textContent = "Could not get location (" + err.message + "). You can type it, or leave it empty.";
      }, { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 });
    });
    [lat, lon].forEach(el => el.addEventListener("input", function () { src.value = "manual"; acc.value = ""; }));
  });

  // ---------------------------------------------------------------- stepper
  document.querySelectorAll("form[data-stepper]").forEach(function (form) {
    const steps = Array.from(form.querySelectorAll(".step"));
    const marks = Array.from(document.querySelectorAll(".stepper li"));
    const firstError = form.querySelector(".has-error");
    let current = firstError ? Math.max(0, steps.indexOf(firstError.closest(".step"))) : 0;

    function show(idx, moveFocus) {
      current = idx;
      steps.forEach((s, i) => { s.hidden = i !== idx; });
      marks.forEach((m, i) => {
        m.className = i < idx ? "done" : (i === idx ? "current" : "");
        if (i === idx) m.setAttribute("aria-current", "step"); else m.removeAttribute("aria-current");
      });
      if (steps[idx].dataset.summary !== undefined) buildSummary();
      const heading = steps[idx].querySelector("legend");
      if (heading && moveFocus) { heading.setAttribute("tabindex", "-1"); heading.focus(); }
    }
    function valid(step) {
      const fields = Array.from(step.querySelectorAll("input, select, textarea"));
      for (const f of fields) {
        if (!f.checkValidity()) { f.reportValidity(); return false; }
      }
      return true;
    }
    function buildSummary() {
      const box = document.getElementById("review-summary");
      if (!box) return;
      box.textContent = "";
      const dl = document.createElement("dl");
      dl.className = "kv";
      form.querySelectorAll("[data-summary-label]").forEach(function (f) {
        let value = "";
        if (f.type === "file") value = Array.from(f.files).map(x => x.name).join(", ");
        else if (f.tagName === "SELECT") value = f.options[f.selectedIndex] ? f.options[f.selectedIndex].text : "";
        else if (f.type === "radio") { if (!f.checked) return; value = f.closest("label").textContent.trim(); }
        else value = f.value;
        const dt = document.createElement("dt"); dt.textContent = f.dataset.summaryLabel;
        const dd = document.createElement("dd"); dd.textContent = value || "—";
        dl.appendChild(dt); dl.appendChild(dd);
      });
      box.appendChild(dl);
    }
    form.addEventListener("click", function (e) {
      const t = e.target.closest("[data-step-next], [data-step-back], [data-step-goto]");
      if (!t) return;
      e.preventDefault();
      if (t.hasAttribute("data-step-next")) { if (valid(steps[current])) show(Math.min(current + 1, steps.length - 1), true); }
      else if (t.hasAttribute("data-step-back")) show(Math.max(current - 1, 0), true);
      else show(parseInt(t.dataset.stepGoto, 10), true);
    });
    show(current, Boolean(firstError));
  });

  // ---------------------------------------------------------------- drafts
  // Text fields only (never files or consent), saved on this device so a lost
  // connection or closed tab does not lose the work.
  document.querySelectorAll("form[data-draft-key]").forEach(function (form) {
    const key = "pramaana-draft:" + form.dataset.draftKey;
    const note = document.getElementById("draft-status");
    const fields = Array.from(form.elements).filter(el =>
      el.name && !["file", "hidden", "checkbox", "password", "submit"].includes(el.type));
    let store = null;
    try { store = window.localStorage; } catch (e) { store = null; }
    if (!store) return;
    const hasServerValues = form.dataset.hasValues === "1";
    try {
      const saved = JSON.parse(store.getItem(key) || "null");
      if (saved && !hasServerValues) {
        fields.forEach(el => {
          if (!(el.name in saved)) return;
          if (el.type === "radio") el.checked = saved[el.name] === el.value;
          else el.value = saved[el.name];
        });
        if (note) note.textContent = "Restored a draft saved on this device. Photos must be chosen again.";
      }
    } catch (e) { /* ignore corrupt drafts */ }
    let timer = null;
    form.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        const data = {};
        fields.forEach(el => { if (el.type !== "radio" || el.checked) data[el.name] = el.value; });
        try { store.setItem(key, JSON.stringify(data)); if (note) note.textContent = "Draft saved on this device."; } catch (e) { }
      }, 600);
    });
    const clear = document.getElementById("draft-clear");
    if (clear) clear.addEventListener("click", function () {
      try { store.removeItem(key); } catch (e) { }
      form.reset();
      if (note) note.textContent = "Draft cleared.";
    });
    form.addEventListener("submit", function () { try { store.removeItem(key); } catch (e) { } });
  });

  // ---------------------------------------------------------------- countdowns
  // The deadline comes from the server (persisted case timestamps); the page
  // only corrects for the difference between server and phone clocks.
  document.querySelectorAll("[data-deadline-ms]").forEach(function (el) {
    const deadline = parseInt(el.dataset.deadlineMs, 10);
    const offset = parseInt(el.dataset.serverNowMs, 10) - Date.now();
    const prefix = el.dataset.prefix || "";
    function tick() {
      const left = Math.floor((deadline - (Date.now() + offset)) / 1000);
      if (left <= 0) { el.textContent = prefix + "window ended"; return; }
      const h = Math.floor(left / 3600), m = Math.floor((left % 3600) / 60), s = left % 60;
      el.textContent = prefix + h + "h " + String(m).padStart(2, "0") + "m " + String(s).padStart(2, "0") + "s left";
    }
    tick();
    setInterval(tick, 1000);
  });

  // ---------------------------------------------------------------- forms
  document.querySelectorAll("form").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      const confirmMsg = form.dataset.confirm;
      if (confirmMsg && !window.confirm(confirmMsg)) { e.preventDefault(); return; }
      const btn = e.submitter || form.querySelector("[type=submit]");
      if (btn && form.dataset.busyText) {
        setTimeout(function () { btn.setAttribute("aria-busy", "true"); btn.disabled = true; btn.textContent = form.dataset.busyText; }, 0);
      }
    });
  });
})();
