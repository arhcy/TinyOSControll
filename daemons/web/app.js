const $ = (id) => document.getElementById(id);
const token = () => localStorage.getItem('osagent_token') || '';
let es = null;

function setToken(v) {
  localStorage.setItem('osagent_token', v);
  connect();
}

async function api(path, body) {
  const res = await fetch(path, {
    method: body ? 'POST' : 'GET',
    headers: { 'X-API-Key': token(), 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error((await res.text()) || String(res.status));
  return res.json();
}

function connect() {
  if (es) es.close();
  if (!token()) return;
  es = new EventSource('/api/events?key=' + encodeURIComponent(token()));
  es.addEventListener('status', (e) => renderStatus(JSON.parse(e.data)));
  es.addEventListener('telemetry', (e) => renderTelemetry(JSON.parse(e.data)));
  es.addEventListener('containers', (e) => renderContainers(JSON.parse(e.data)));
  es.onerror = () => setAgentStatus(false);
}

async function refresh() {
  if (!token()) return;
  try {
    const s = await api('/api/status');
    renderStatus(s);
    if (s.telemetry) renderTelemetry(s.telemetry);
    renderContainers({ containers: s.containers || [] });
  } catch (err) {
    setActionMsg('помилка: ' + err.message, true);
  }
}

function setAgentStatus(online) {
  const el = $('agent-status');
  el.className = 'status ' + (online ? 'online' : 'offline');
  $('agent-status-text').textContent = online ? 'агент онлайн' : 'агент офлайн';
}

function renderStatus(s) {
  setAgentStatus(!!s.agent_online);
  $('wol-mac').textContent = s.wol_mac || '—';
}

function renderContainers(cl) {
  const tb = $('containers-table').querySelector('tbody');
  tb.innerHTML = '';
  for (const c of cl.containers || []) {
    const tr = document.createElement('tr');
    const running = c.state === 'running';
    const td1 = document.createElement('td');
    td1.textContent = c.name;
    const td2 = document.createElement('td');
    const badge = document.createElement('span');
    badge.className = 'badge ' + (running ? 'ok' : 'bad');
    badge.textContent = c.state;
    td2.appendChild(badge);
    const td3 = document.createElement('td');
    td3.className = 'buttons';
    tr.append(td1, td2, td3);
    for (const op of running ? ['stop', 'restart'] : ['start']) {
      const b = document.createElement('button');
      b.textContent = op === 'start' ? 'запустити' : op === 'stop' ? 'зупинити' : 'перезапустити';
      if (op === 'stop') b.className = 'danger';
      b.onclick = () => doContainer(c.name, op);
      td3.appendChild(b);
    }
    tb.appendChild(tr);
  }
}

async function doContainer(name, op) {
  setActionMsg(name + ': ' + op + '…');
  try {
    await api('/api/actions', { action: 'container', name, op });
    setActionMsg(name + ': ' + op + ' виконано');
  } catch (err) {
    setActionMsg('помилка: ' + err.message, true);
  }
}

function renderTelemetry(t) {
  $('updated-at').textContent = 'оновлено: ' + (t.ts || '');
  const temps = (t.cpu || []).map((z) => (z.type || 'zone') + ': ' + z.temp_c.toFixed(1) + '°C').join(' · ');
  $('cpu-temps').textContent = temps || 'CPU температури: немає даних';
  if (t.ram) {
    const gb = (kb) => (kb / 1048576).toFixed(1);
    $('ram').innerHTML = 'RAM: <span class="bar"><span class="bar-fill" style="width:' +
      t.ram.used_pct.toFixed(0) + '%"></span></span> ' +
      gb(t.ram.used_kb) + ' / ' + gb(t.ram.total_kb) + ' ГБ (' + t.ram.used_pct.toFixed(0) + '%)';
  }
  if (t.gpu) {
    const parts = [];
    if (t.gpu.temp_c != null) parts.push('GPU ' + t.gpu.temp_c + '°C');
    if (t.gpu.use_pct != null) parts.push('load ' + t.gpu.use_pct + '%');
    if (t.gpu.mem_use_pct != null) parts.push('vram ' + t.gpu.mem_use_pct + '%');
    $('gpu').textContent = parts.join(' · ') || 'GPU: немає даних';
  }
  if (t.load) $('load').textContent = 'load: ' + t.load.l1 + ' ' + t.load.l5 + ' ' + t.load.l15;
  $('amdsmi').textContent = (t.gpu && t.gpu.raw) || '—';
}

function setActionMsg(msg, isError) {
  const el = $('action-msg');
  el.textContent = msg || '';
  el.className = 'muted' + (isError ? ' error' : '');
}

$('btn-wol').onclick = async () => {
  setActionMsg('WoL: надсилаю магічний пакет…');
  try { await api('/api/actions', { action: 'wol' }); setActionMsg('WoL: пакет надіслано'); }
  catch (err) { setActionMsg('помилка: ' + err.message, true); }
};

$('btn-shutdown').onclick = async () => {
  if (!confirm('Вимкнути цільовий сервер?')) return;
  setActionMsg('Shutdown: виконую…');
  try { await api('/api/actions', { action: 'shutdown' }); setActionMsg('Shutdown: команду надіслано, сервер вимикається'); }
  catch (err) { setActionMsg('помилка: ' + err.message, true); }
};

$('btn-save-token').onclick = () => { setToken($('token').value.trim()); refresh(); };

window.addEventListener('load', () => { $('token').value = token(); refresh(); connect(); });
