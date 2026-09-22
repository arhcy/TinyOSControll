"use strict";

const $ = (s) => document.querySelector(s);
const tokenInput = $("#token");
const saveBtn = $("#save");
const connEl = $("#conn");
const agentsEl = $("#agents");
const statusLine = $("#status-line");

const cards = new Map(); // agent name -> card element

// --- token ---------------------------------------------------------------
tokenInput.value = localStorage.getItem("tinyos_token") || "";
saveBtn.addEventListener("click", () => {
  localStorage.setItem("tinyos_token", tokenInput.value.trim());
  connectSSE();
  refresh();
});

function getToken() {
  return localStorage.getItem("tinyos_token") || tokenInput.value.trim() || "";
}

// --- api -----------------------------------------------------------------
async function api(path, method = "GET", body) {
  const headers = { "X-API-Key": getToken() };
  if (body) headers["Content-Type"] = "application/json";
  const res = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`${res.status} ${t}`);
  }
  return res.json();
}

// --- formatting ----------------------------------------------------------
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
const pct = (v) => (v == null ? "—" : v + "%");
const mb = (v) => (v == null ? "—" : v + " MB");
const num = (s) => { const v = parseFloat(s); return Number.isFinite(v) ? v : null; };

// Parse the fixed `amd-smi monitor` table into per-GPU objects. Returns null
// when the layout is not recognized so the caller can fall back to raw text.
function parseAmdSmi(text) {
  const lines = String(text).trim().split(/\r?\n/).filter((l) => l.trim());
  if (lines.length < 2) return null;
  const expected = ["GPU", "XCP", "POWER", "GPU_T", "MEM_T", "GFX_CLK",
                    "GFX%", "MEM%", "ENC%", "DEC%", "VRAM_USAGE"];
  const header = lines[0].trim().split(/\s+/);
  if (header.length !== expected.length ||
      header.some((h, i) => h !== expected[i])) return null;
  const gpus = [];
  for (const line of lines.slice(1)) {
    const t = line.trim().split(/\s+/);
    if (t[3] !== "W" || t[5] !== "°C" || t[7] !== "°C" || t[9] !== "MHz" ||
        t[11] !== "%" || t[13] !== "%") return null;
    let enc, dec, vramUsed, vramTotal;
    if (t[14] === "N/A") {
      if (t.length !== 20 || t[16] !== "%" || t[19] !== "GB") return null;
      enc = null; dec = num(t[15]);
      vramUsed = num(t[17]); vramTotal = num(t[18]);
    } else {
      if (t.length !== 21 || t[15] !== "%" || t[17] !== "%" || t[20] !== "GB") return null;
      enc = num(t[14]); dec = num(t[16]);
      vramUsed = num(t[18]); vramTotal = num(t[19]);
    }
    gpus.push({
      gpu: parseInt(t[0], 10), xcp: parseInt(t[1], 10),
      power_w: num(t[2]), gpu_temp_c: num(t[4]), mem_temp_c: num(t[6]),
      gfx_clk_mhz: num(t[8]), gfx_pct: num(t[10]), mem_pct: num(t[12]),
      enc_pct: enc, dec_pct: dec,
      vram_used_gb: vramUsed, vram_total_gb: vramTotal,
    });
  }
  return gpus.length ? gpus : null;
}

const statBlock = (label, value) =>
  `<div class="stat"><span class="stat-label">${esc(label)}</span>` +
  `<span class="stat-val">${esc(value)}</span></div>`;

function gpuBlock(g) {
  const vram = (g.vram_used_gb == null || g.vram_total_gb == null)
    ? "—" : `${g.vram_used_gb} / ${g.vram_total_gb} GB`;
  const stats = [
    statBlock("Power", g.power_w == null ? "—" : g.power_w + " W"),
    statBlock("GPU Temp", g.gpu_temp_c == null ? "—" : g.gpu_temp_c + " °C"),
    statBlock("Mem Temp", g.mem_temp_c == null ? "—" : g.mem_temp_c + " °C"),
    statBlock("GFX Clock", g.gfx_clk_mhz == null ? "—" : g.gfx_clk_mhz + " MHz"),
    statBlock("GFX", pct(g.gfx_pct)),
    statBlock("Mem", pct(g.mem_pct)),
    statBlock("Enc", g.enc_pct == null ? "N/A" : pct(g.enc_pct)),
    statBlock("Dec", pct(g.dec_pct)),
    statBlock("VRAM", vram),
    statBlock("XCP", g.xcp == null ? "—" : String(g.xcp)),
  ].join("");
  return `<div class="gpu"><div class="gpu-head">GPU ${esc(g.gpu)}</div>` +
         `<div class="gpu-stats">${stats}</div></div>`;
}

// --- rendering -----------------------------------------------------------
function createCard(a) {
  const el = document.createElement("section");
  el.className = "agent";
  el.innerHTML = `
    <div class="agent-head"><h2>${esc(a.name)}</h2><span class="badge"></span></div>
    <div class="meta">MAC ${esc(a.mac)}${a.ip ? " · " + esc(a.ip) : ""}</div>
    <div class="tele"></div>
    <div class="amd" hidden></div>
    <div class="actions">
      <button data-act="wake">Wake</button>
      <button data-act="poweroff">Power off</button>
      <button data-act="reboot">Reboot</button>
    </div>
    <div class="containers"></div>`;
  el.querySelectorAll("button[data-act]").forEach((b) =>
    b.addEventListener("click", () => doAction(a.name, b.dataset.act)));
  return el;
}

function updateCard(el, a) {
  const t = a.telemetry || {};
  const ram = t.ram || {};
  const sw = t.swap || {};
  el.className = "agent " + (a.online ? "online" : "offline");
  const badge = el.querySelector(".badge");
  badge.textContent = a.online ? "online" : "offline";
  badge.className = "badge " + (a.online ? "on" : "off");
  el.querySelector(".tele").innerHTML =
    `<div>CPU <b>${t.cpu_temp_c == null ? "—" : t.cpu_temp_c + "°C"}</b></div>` +
    `<div>RAM <b>${pct(ram.percent)}</b> <small>${mb(ram.used_mb)}/${mb(ram.total_mb)}</small></div>` +
    `<div>SWAP <b>${pct(sw.percent)}</b> <small>${mb(sw.used_mb)}/${mb(sw.total_mb)}</small></div>`;
  const amd = el.querySelector(".amd");
  const parsed = Array.isArray(t.amd_smi) ? t.amd_smi
                 : (typeof t.amd_smi === "string" ? parseAmdSmi(t.amd_smi) : null);
  if (parsed) {
    amd.hidden = false;
    amd.className = "amd amd-blocks";
    amd.innerHTML = parsed.map(gpuBlock).join("");
  } else if (t.amd_smi) {
    amd.hidden = false;
    amd.className = "amd amd-raw";
    amd.textContent = t.amd_smi;
  } else {
    amd.hidden = true;
    amd.className = "amd";
  }
}

async function refresh() {
  try {
    const agents = await api("/api/agents");
    for (const a of agents) {
      let card = cards.get(a.name);
      if (!card) {
        card = createCard(a);
        cards.set(a.name, card);
        agentsEl.appendChild(card);
      }
      updateCard(card, a);
    }
    connEl.textContent = "connected";
    statusLine.textContent = `updated ${new Date().toLocaleTimeString()}`;
  } catch (e) {
    connEl.textContent = "error";
    statusLine.textContent = e.message;
  }
}

function refreshContainers(name) {
  return api(`/api/agents/${encodeURIComponent(name)}/containers`)
    .then((map) => {
      const el = cards.get(name)?.querySelector(".containers");
      if (!el) return;
      el.innerHTML = "";
      const names = Object.keys(map);
      if (!names.length) {
        el.innerHTML = "<div class='muted'>no containers configured</div>";
        return;
      }
      for (const n of names) {
        const st = (map[n] && map[n].state) || "unknown";
        const row = document.createElement("div");
        row.className = "crow";
        row.innerHTML =
          `<span class="cname">${esc(n)}</span>` +
          `<span class="cstate ${esc(st)}">${esc(st)}</span>` +
          `<button data-c="start">Start</button>` +
          `<button data-c="stop">Stop</button>` +
          `<button data-c="restart">Restart</button>`;
        row.querySelectorAll("button[data-c]").forEach((b) =>
          b.addEventListener("click", () => containerAction(name, n, b.dataset.c)));
        el.appendChild(row);
      }
    })
    .catch(() => {});
}

// --- actions -------------------------------------------------------------
async function doAction(name, act) {
  try {
    const r = await api(`/api/agents/${encodeURIComponent(name)}/${act}`, "POST");
    flash(`${name}: ${act} ${r.ok ? "ok" : "failed" + (r.error ? " (" + r.error + ")" : "")}`);
  } catch (e) {
    flash(`${name}: ${act} error: ${e.message}`);
  }
}

async function containerAction(agent, container, action) {
  try {
    const r = await api(
      `/api/agents/${encodeURIComponent(agent)}/containers/${encodeURIComponent(container)}/${action}`,
      "POST");
    flash(`${agent}/${container}: ${action} ${r.ok ? "ok" : "failed" + (r.error ? " (" + r.error + ")" : "")}`);
    refreshContainers(agent);
  } catch (e) {
    flash(`${agent}/${container}: ${action} error: ${e.message}`);
  }
}

function flash(msg) {
  statusLine.textContent = msg;
  console.log(msg);
}

// --- live updates --------------------------------------------------------
let sse = null;
function connectSSE() {
  const token = getToken();
  if (!token) return;
  if (sse) sse.close();
  sse = new EventSource(`/api/stream?token=${encodeURIComponent(token)}`);
  sse.onmessage = (ev) => {
    let data;
    try { data = JSON.parse(ev.data); } catch { return; }
    const d = data.data || {};
    if (data.event === "telemetry") {
      refresh();
    } else if (data.event === "status" || data.event === "action") {
      refresh();
      // Skip the containers refresh when the agent is (or just became)
      // offline: the request would 503 in main and only log console noise.
      // After "wake" the agent is offline by definition; it will be
      // refreshed again when the "status" online event arrives.
      if (d.agent && d.online !== false && d.action !== "wake") {
        refreshContainers(d.agent);
      }
    }
  };
  sse.onerror = () => { connEl.textContent = "reconnecting…"; };
}

// --- init ----------------------------------------------------------------
refresh();
connectSSE();
setInterval(refresh, 5000);
api("/api/agents")
  .then((agents) => agents.forEach((a) => { if (a.online) refreshContainers(a.name); }))
  .catch(() => {});
