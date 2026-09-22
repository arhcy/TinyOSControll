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

// --- rendering -----------------------------------------------------------
function createCard(a) {
  const el = document.createElement("section");
  el.className = "agent";
  el.innerHTML = `
    <div class="agent-head"><h2>${esc(a.name)}</h2><span class="badge"></span></div>
    <div class="meta">MAC ${esc(a.mac)}${a.ip ? " · " + esc(a.ip) : ""}</div>
    <div class="tele"></div>
    <pre class="amd" hidden></pre>
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
  if (t.amd_smi) { amd.hidden = false; amd.textContent = t.amd_smi; }
  else amd.hidden = true;
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
