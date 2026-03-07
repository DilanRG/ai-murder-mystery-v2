/**
 * api.js — REST client + WebSocket connection manager
 * All backend communication goes through this module.
 */

const BASE = '/api';
let _ws = null;
let _wsHandlers = {};
let _wsReconnectTimer = null;

// ── REST helpers ─────────────────────────────────────────────────────────────

async function request(method, path, body = null) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body !== null) opts.body = JSON.stringify(body);
  const resp = await fetch(`${BASE}${path}`, opts);
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
  return data;
}

export const api = {
  health:          () => request('GET', '/health'),
  getSettings:     () => request('GET', '/settings'),
  saveSettings:    (s) => request('POST', '/settings', s),
  fetchModels:     (q = '', provider = '') => request('GET', `/models?q=${encodeURIComponent(q)}&provider=${encodeURIComponent(provider)}`),
  listCharacters:  () => request('GET', '/characters'),
  newGame:         (opts) => request('POST', '/game/new', opts),
  getState:        () => request('GET', '/game/state'),
  move:            (location_id) => request('POST', '/game/move', { location_id }),
  talk:            (npc_name, message) => request('POST', '/game/talk', { npc_name, message }),
  investigate:     () => request('POST', '/game/investigate'),
  accuse:          (suspect_name, reasoning) => request('POST', '/game/accuse', { suspect_name, reasoning }),
  debrief:         () => request('GET', '/game/debrief'),
  endGame:         () => request('POST', '/game/end'),
};

// ── WebSocket ─────────────────────────────────────────────────────────────────

export function onWsEvent(type, handler) {
  _wsHandlers[type] = handler;
}

export function offWsEvent(type) {
  delete _wsHandlers[type];
}

export function connectWs() {
  if (_ws && _ws.readyState === WebSocket.OPEN) return;
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  const host = location.host || '127.0.0.1:8765';
  _ws = new WebSocket(`${protocol}://${host}/ws/events`);

  _ws.onopen = () => {
    console.log('[WS] Connected');
    clearTimeout(_wsReconnectTimer);
    _ws._pingInterval = setInterval(() => {
      if (_ws.readyState === WebSocket.OPEN) _ws.send('ping');
    }, 20000);
  };

  _ws.onmessage = (e) => {
    if (e.data === 'pong') return;
    try {
      const msg = JSON.parse(e.data);
      const handler = _wsHandlers[msg.type];
      if (handler) handler(msg.data);
      const catchAll = _wsHandlers['*'];
      if (catchAll) catchAll(msg);
    } catch (_) {}
  };

  _ws.onclose = () => {
    console.log('[WS] Disconnected — reconnecting in 3s');
    clearInterval(_ws?._pingInterval);
    _wsReconnectTimer = setTimeout(connectWs, 3000);
  };

  _ws.onerror = () => _ws.close();
}
