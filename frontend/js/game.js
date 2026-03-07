/**
 * game.js — Game screen controller
 * Manages: map rendering, character list, dialogue/event feed,
 *          investigate, accusation modal, results screen.
 */
import { api } from './api.js';
import { showScreen } from './screens.js';

// ── State ─────────────────────────────────────────────────────────────────────
let _state = null;         // World state from /api/game/state
let _scenario = null;      // From /api/game/new response
let _selectedNpc = null;   // NPC name the player is talking to
let _selectedAccusee = null;
let _gameData = null;      // From /api/game/new response (locations, cast, etc.)
let _clues = [];
let _timerInterval = null;
let _startTime = null;
let _abortCtrl = null;     // AbortController for event listener cleanup

// ── Feed helpers ──────────────────────────────────────────────────────────────
function addToFeed(type, content, speaker = '') {
  const feed = document.getElementById('chat-feed');
  const empty = feed.querySelector('.chat-empty-state');
  if (empty) empty.remove();

  const msg = document.createElement('div');
  msg.className = `chat-msg ${type}`;

  if (speaker) {
    const spk = document.createElement('div');
    spk.className = 'chat-speaker';
    spk.textContent = speaker;
    msg.appendChild(spk);
  }

  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble';
  bubble.textContent = content;
  msg.appendChild(bubble);
  feed.appendChild(msg);
  feed.scrollTop = feed.scrollHeight;
}

function addClueFlash(clue) {
  const feed = document.getElementById('chat-feed');
  const el = document.createElement('div');
  el.className = 'clue-flash';
  el.innerHTML = `<span class="clue-flash-icon">🔍</span><span><strong>${clue.clue_type.toUpperCase()}</strong> — ${clue.description}</span>`;
  feed.appendChild(el);
  feed.scrollTop = feed.scrollHeight;
}

function addEventLog(description) {
  const log = document.getElementById('event-log');
  const elapsed = _startTime ? Math.floor((Date.now() - _startTime) / 1000) : 0;
  const mins = String(Math.floor(elapsed / 60)).padStart(2, '0');
  const secs = String(elapsed % 60).padStart(2, '0');
  const entry = document.createElement('div');
  entry.className = 'event-log-entry';
  entry.innerHTML = `<span class="time">${mins}:${secs}</span>${description}`;
  log.appendChild(entry);
  log.scrollTop = log.scrollHeight;
}

// ── Map ───────────────────────────────────────────────────────────────────────
function buildMap(locations, characterStates, playerLocation) {
  const svg = document.getElementById('map-svg');
  if (!svg || !locations?.length) return;
  svg.innerHTML = '';

  const W = 230, H = 160;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);

  // Simple force-directed layout with fixed positions based on index
  const count = locations.length;
  const positions = {};

  locations.forEach((loc, i) => {
    const angle = (i / count) * 2 * Math.PI - Math.PI / 2;
    const r = count <= 4 ? 50 : count <= 6 ? 55 : 60;
    positions[loc.id] = {
      x: W / 2 + r * Math.cos(angle),
      y: H / 2 + r * Math.sin(angle),
    };
  });

  // Draw edges
  const drawnEdges = new Set();
  locations.forEach(loc => {
    (loc.connected_to || []).forEach(targetId => {
      const key = [loc.id, targetId].sort().join('|');
      if (drawnEdges.has(key)) return;
      drawnEdges.add(key);
      const a = positions[loc.id], b = positions[targetId];
      if (!a || !b) return;
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('x1', a.x); line.setAttribute('y1', a.y);
      line.setAttribute('x2', b.x); line.setAttribute('y2', b.y);
      line.setAttribute('class', 'map-edge');
      svg.appendChild(line);
    });
  });

  // Draw location nodes
  locations.forEach(loc => {
    const pos = positions[loc.id];
    if (!pos) return;
    const isCurrent = loc.id === playerLocation;
    const charCount = (characterStates || []).filter(c => c.location === loc.id && c.name !== '[player]').length;

    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.setAttribute('class', `map-node${isCurrent ? ' current' : ''}`);
    g.setAttribute('data-loc-id', loc.id);

    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('cx', pos.x); circle.setAttribute('cy', pos.y); circle.setAttribute('r', 11);
    g.appendChild(circle);

    const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    label.setAttribute('x', pos.x); label.setAttribute('y', pos.y + 20);
    label.setAttribute('text-anchor', 'middle');
    label.textContent = loc.name.length > 12 ? loc.name.substring(0, 11) + '…' : loc.name;
    g.appendChild(label);

    if (charCount > 0) {
      const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      dot.setAttribute('cx', pos.x + 8); dot.setAttribute('cy', pos.y - 8); dot.setAttribute('r', 3.5);
      dot.setAttribute('class', 'map-char-dot');
      const cnt = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      cnt.setAttribute('x', pos.x + 8); cnt.setAttribute('y', pos.y - 5);
      cnt.setAttribute('text-anchor', 'middle');
      cnt.setAttribute('font-size', '5');
      cnt.setAttribute('fill', '#07070c');
      cnt.textContent = charCount;
      g.appendChild(dot); g.appendChild(cnt);
    }

    g.addEventListener('click', () => moveToLocation(loc.id, loc.name));
    svg.appendChild(g);
  });
}

async function moveToLocation(locationId, locationName) {
  if (!_state) return;
  try {
    const result = await api.move(locationId);
    _state = result.state;
    refreshCharacterList();
    refreshMap();
    document.getElementById('current-location-name').textContent = locationName;
    const loc = _gameData?.locations?.find(l => l.id === locationId);
    document.getElementById('current-location-desc').textContent = loc?.description || '';
    addEventLog(`Moved to ${locationName}`);

    // Update available NPCs for talking
    if (_selectedNpc) {
      const npcInRoom = _state.characters?.some(c => c.name === _selectedNpc && c.location === locationId);
      if (!npcInRoom) clearSelectedNpc();
    }
  } catch (e) {
    addToFeed('event', `(Cannot move there: ${e.message})`);
  }
}

function refreshMap() {
  if (!_gameData || !_state) return;
  const playerChar = _state.characters?.find(c => c.is_player);
  buildMap(_gameData.locations, _state.characters, _state.player_location);
}

// ── Character List ────────────────────────────────────────────────────────────
function refreshCharacterList() {
  const list = document.getElementById('character-list');
  if (!list || !_state) return;

  const playerLoc = _state.player_location;
  list.innerHTML = '';

  (_state.characters || []).forEach(char => {
    if (char.is_player) return;
    const card = document.createElement('div');
    card.className = `character-card${!char.alive ? ' dead' : ''}${_selectedNpc === char.name ? ' selected' : ''}`;
    const sameRoom = char.location === playerLoc;
    const initials = char.name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();

    card.innerHTML = `
      <div class="char-avatar">${initials}</div>
      <div class="char-info">
        <div class="char-name">${char.name}</div>
        <div class="char-location">${char.location || '?'}</div>
      </div>
      ${sameRoom && char.alive ? '<span class="char-badge same-room">here</span>' : ''}
    `;
    if (char.alive && sameRoom) {
      card.addEventListener('click', () => selectNpc(char.name));
    }
    list.appendChild(card);
  });
}

// ── NPC Selection ─────────────────────────────────────────────────────────────
function selectNpc(name) {
  _selectedNpc = name;
  document.getElementById('chat-npc-name').textContent = `Speaking with ${name}`;
  document.getElementById('btn-clear-npc').classList.remove('hidden');
  document.getElementById('chat-input').disabled = false;
  document.getElementById('btn-send').disabled = false;
  document.getElementById('chat-input').focus();
  refreshCharacterList();
  addToFeed('event', `You approach ${name}.`);
}

function clearSelectedNpc() {
  _selectedNpc = null;
  document.getElementById('chat-npc-name').textContent = 'Select a suspect to question';
  document.getElementById('btn-clear-npc').classList.add('hidden');
  document.getElementById('chat-input').disabled = true;
  document.getElementById('btn-send').disabled = true;
  refreshCharacterList();
}

// ── Dialogue ──────────────────────────────────────────────────────────────────
async function sendMessage() {
  const input = document.getElementById('chat-input');
  const message = input.value.trim();
  if (!message || !_selectedNpc) return;

  input.value = '';
  input.disabled = true;
  document.getElementById('btn-send').disabled = true;

  addToFeed('player', message, 'You');

  try {
    const result = await api.talk(_selectedNpc, message);
    addToFeed('npc', result.response, _selectedNpc);
    addEventLog(`Questioned ${_selectedNpc}`);
  } catch (e) {
    addToFeed('event', `(Error: ${e.message})`);
  } finally {
    input.disabled = false;
    document.getElementById('btn-send').disabled = false;
    input.focus();
  }
}

// ── Investigate ───────────────────────────────────────────────────────────────
async function investigate() {
  const btn = document.getElementById('btn-investigate');
  btn.disabled = true;
  btn.textContent = '🔍 Searching...';
  addToFeed('event', 'You search the area carefully...');

  try {
    const result = await api.investigate();
    _state = result.state;

    if (result.clues_found?.length) {
      result.clues_found.forEach(clue => {
        addClueFlash(clue);
        addClue(clue);
        addEventLog(`Found clue: ${clue.clue_type}`);
      });
    } else {
      addToFeed('event', 'Nothing new turns up.');
    }
  } catch (e) {
    addToFeed('event', `(${e.message})`);
  } finally {
    btn.disabled = false;
    btn.textContent = '🔍 Search Area';
  }
}

function addClue(clue) {
  _clues.push(clue);
  const list = document.getElementById('clue-list');
  const empty = list.querySelector('.empty-state');
  if (empty) empty.remove();

  const item = document.createElement('div');
  item.className = `clue-item${clue.is_red_herring ? ' red-herring' : ''}`;
  item.innerHTML = `
    <div class="clue-type">${clue.clue_type}</div>
    <div class="clue-desc">${clue.description}</div>
    ${clue.points_to ? `<div class="clue-points-to">→ ${clue.points_to}</div>` : ''}
  `;
  list.appendChild(item);

  const count = document.getElementById('clue-count');
  count.textContent = _clues.length;
}

// ── Accusation ────────────────────────────────────────────────────────────────
function openAccusationModal() {
  const modal = document.getElementById('modal-accuse');
  const list = document.getElementById('accuse-suspect-list');
  list.innerHTML = '';
  _selectedAccusee = null;
  document.getElementById('btn-confirm-accuse').disabled = true;
  document.getElementById('selected-accusee').classList.add('hidden');
  document.getElementById('accuse-reasoning').value = '';

  (_state?.characters || []).filter(c => c.alive && !c.is_player).forEach(char => {
    const el = document.createElement('div');
    el.className = 'accuse-suspect-item';
    el.innerHTML = `<strong>${char.name}</strong>`;
    el.addEventListener('click', () => {
      list.querySelectorAll('.accuse-suspect-item').forEach(i => i.classList.remove('selected'));
      el.classList.add('selected');
      _selectedAccusee = char.name;
      document.getElementById('accusee-name').textContent = char.name;
      document.getElementById('selected-accusee').classList.remove('hidden');
      document.getElementById('btn-confirm-accuse').disabled = false;
    });
    list.appendChild(el);
  });

  modal.classList.remove('hidden');
}

async function confirmAccuse() {
  if (!_selectedAccusee) return;
  const reasoning = document.getElementById('accuse-reasoning').value.trim();
  document.getElementById('modal-accuse').classList.add('hidden');

  try {
    const result = await api.accuse(_selectedAccusee, reasoning);
    stopTimer();
    await showResults(result);
  } catch (e) {
    addToFeed('event', `(Accusation failed: ${e.message})`);
  }
}

// ── Results ───────────────────────────────────────────────────────────────────
export async function showResults(accuseResult) {
  showScreen('results');
  stopTimer();

  const icon    = accuseResult.correct ? '🎯' : '💀';
  const heading = accuseResult.correct ? 'Case Solved' : 'The Killer Walks Free';

  let sub = '';
  if (accuseResult.reason === 'timeout') {
    sub = `Time expired. The killer escaped justice.`;
  } else if (accuseResult.correct) {
    sub = `Your accusation against ${accuseResult.actual_killer || accuseResult.accused} was correct.`;
  } else {
    sub = `You accused ${accuseResult.accused || '?'}, but the killer was ${accuseResult.actual_killer || '?'}.`;
  }

  document.getElementById('verdict-icon').textContent = icon;
  document.getElementById('verdict-heading').textContent = heading;
  document.getElementById('verdict-heading').className = `verdict-heading ${accuseResult.correct ? 'correct' : 'wrong'}`;
  document.getElementById('verdict-sub').textContent = sub;

  // Narrative paragraph
  if (accuseResult.narrative) {
    const narEl = document.getElementById('verdict-narrative');
    if (narEl) {
      narEl.textContent = accuseResult.narrative;
      narEl.classList.remove('hidden');
    }
  }

  // Use injected debrief if available, otherwise fetch
  try {
    const debrief = accuseResult.debrief || await api.debrief();
    renderDebrief(debrief, accuseResult);
  } catch (e) {
    console.error('Debrief failed:', e);
  }
}

function renderDebrief(debrief, accuseResult) {
  // Murder tab
  const m = debrief.murder;
  document.getElementById('tab-murder').innerHTML = `
    <div class="debrief-card">
      <div class="debrief-row"><span class="debrief-label">Killer</span><span class="debrief-value killer">${m.killer}</span></div>
      <div class="debrief-row"><span class="debrief-label">Victim</span><span class="debrief-value">${m.victim}</span></div>
      <div class="debrief-row"><span class="debrief-label">Method</span><span class="debrief-value">${m.method}</span></div>
      <div class="debrief-row"><span class="debrief-label">Motive</span><span class="debrief-value">${m.motive}</span></div>
      <div class="debrief-row"><span class="debrief-label">Time of Death</span><span class="debrief-value">${m.time_of_death}</span></div>
      <div class="debrief-row"><span class="debrief-label">Location</span><span class="debrief-value">${m.location}</span></div>
      <div class="debrief-row"><span class="debrief-label">Cover Story</span><span class="debrief-value">${m.cover_story}</span></div>
    </div>
    <br/>
    <div class="debrief-card">
      <div class="debrief-row"><span class="debrief-label">Backstory</span><span class="debrief-value">${debrief.backstory || ''}</span></div>
    </div>
    <br/>
    <div style="font-family:var(--font-mono);font-size:10px;color:var(--text-muted);text-align:center">
      Clues found: ${debrief.stats.clues_found}/${debrief.stats.total_clues}
      ${debrief.stats.planted_clues_exist ? ' · (Includes planted evidence)' : ''}
      &nbsp;·&nbsp; Time: ${Math.floor(debrief.stats.elapsed_seconds/60)}m ${debrief.stats.elapsed_seconds%60}s
    </div>
  `;

  // Suspects tab — full reveal
  document.getElementById('tab-suspects').innerHTML = `
    <div class="debrief-card">
      ${(debrief.npc_briefings || []).map(b => `
        <div class="debrief-suspect-block">
          <div class="debrief-row">
            <span class="debrief-label">${b.name}</span>
            <span class="debrief-value${b.role === 'killer' ? ' killer' : ''}">${b.role.toUpperCase()}</span>
          </div>
          <div class="debrief-row"><span class="debrief-label">Alibi</span><span class="debrief-value">${b.alibi}</span></div>
          <div class="debrief-row"><span class="debrief-label">True Whereabouts</span><span class="debrief-value">${b.true_whereabouts}</span></div>
          <div class="debrief-row"><span class="debrief-label">Suspicions</span><span class="debrief-value">${b.suspicions || '—'}</span></div>
          ${b.secrets?.length ? `<div class="debrief-row"><span class="debrief-label">Secrets</span><span class="debrief-value">${b.secrets.join('; ')}</span></div>` : ''}
        </div>
      `).join('<hr style="border-color:rgba(255,255,255,0.05);margin:0.5rem 0">')}
    </div>
  `;

  // Evidence tab
  const realClues = (debrief.clues || []).filter(c => !c.is_red_herring && !c.planted);
  const redH = (debrief.clues || []).filter(c => c.is_red_herring);
  const planted = (debrief.clues || []).filter(c => c.planted);
  document.getElementById('tab-evidence').innerHTML = `
    <div class="debrief-card">
      <div style="font-family:var(--font-mono);font-size:9px;letter-spacing:.15em;color:var(--text-muted);margin-bottom:.75rem;text-transform:uppercase">Real Clues</div>
      ${realClues.map(c => `<div class="debrief-row">
        <span class="debrief-label">${c.clue_type}</span>
        <span class="debrief-value${c.discovered ? '' : ' text-muted'}">${c.description} <em>${c.discovered ? '✓ found' : '✗ missed'}</em></span>
      </div>`).join('')}
    </div>
    ${redH.length ? `<br/><div class="debrief-card">
      <div style="font-family:var(--font-mono);font-size:9px;letter-spacing:.15em;color:var(--accent-dim);margin-bottom:.75rem;text-transform:uppercase">Red Herrings</div>
      ${redH.map(c => `<div class="debrief-row">
        <span class="debrief-label">${c.clue_type}</span>
        <span class="debrief-value">${c.description}</span>
      </div>`).join('')}
    </div>` : ''}
    ${planted.length ? `<br/><div class="debrief-card">
      <div style="font-family:var(--font-mono);font-size:9px;letter-spacing:.15em;color:#8b0000;margin-bottom:.75rem;text-transform:uppercase">⚠ Planted Evidence (Killer)</div>
      ${planted.map(c => `<div class="debrief-row">
        <span class="debrief-label">planted</span>
        <span class="debrief-value">${c.description}</span>
      </div>`).join('')}
    </div>` : ''}
  `;

  // Timeline tab
  const timeline = debrief.timeline || [];
  const timelineHtml = timeline.length
    ? timeline.map(e => {
        const mins = String(Math.floor(e.time / 60)).padStart(2, '0');
        const secs = String(e.time % 60).padStart(2, '0');
        const typeColors = { movement: '#c9aa71', speech: '#7ecad4', discovery: '#6dba6d', examine: '#888' };
        return `<div class="timeline-entry">
          <span class="timeline-time">${mins}:${secs}</span>
          <span class="timeline-dot" style="background:${typeColors[e.type] || '#555'}"></span>
          <span class="timeline-text"><em>${e.actor}</em> — ${e.description}</span>
        </div>`;
      }).join('')
    : '<div style="color:var(--text-muted);font-size:0.85rem;text-align:center;padding:2rem">No events recorded.</div>';
  const timelineTab = document.getElementById('tab-timeline');
  if (timelineTab) timelineTab.innerHTML = `<div class="debrief-card" style="max-height:400px;overflow-y:auto">${timelineHtml}</div>`;

  // Tab switching
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
      btn.classList.add('active');
      document.getElementById(`tab-${btn.dataset.tab}`)?.classList.remove('hidden');
    });
  });
}

// ── Timer ─────────────────────────────────────────────────────────────────────
let _timerConfig = { timerMode: 'none', timerMinutes: 30 };
let _timerLimitMs = 0;

function startTimer() {
  _startTime = Date.now();
  _timerLimitMs = _timerConfig.timerMode === 'realtime' ? _timerConfig.timerMinutes * 60 * 1000 : 0;

  if (_timerLimitMs > 0) {
    // Countdown timer
    _timerInterval = setInterval(() => {
      const elapsed = Date.now() - _startTime;
      const remaining = Math.max(0, _timerLimitMs - elapsed);
      const m = String(Math.floor(remaining / 60000)).padStart(2, '0');
      const s = String(Math.floor((remaining % 60000) / 1000)).padStart(2, '0');
      const el = document.getElementById('game-timer');
      if (el) {
        el.textContent = `${m}:${s}`;
        el.style.color = remaining < 120000 ? '#8b0000' : '';
      }
      if (remaining === 0) {
        stopTimer();
        api.endGame().catch(() => {});
      }
    }, 1000);
  } else {
    // Count-up timer (elapsed)
    _timerInterval = setInterval(() => {
      const elapsed = Math.floor((Date.now() - _startTime) / 1000);
      const m = String(Math.floor(elapsed / 60)).padStart(2, '0');
      const s = String(elapsed % 60).padStart(2, '0');
      const el = document.getElementById('game-timer');
      if (el) el.textContent = `${m}:${s}`;
    }, 1000);
  }
}

function stopTimer() {
  clearInterval(_timerInterval);
  _timerInterval = null;
}

// ── WebSocket event handling ──────────────────────────────────────────────────
export function handleWsEvent(data) {
  if (!data) return;
  const { type, actor, description, location } = data;

  switch (type) {
    case 'speech':
      if (actor !== '[player]') addToFeed('npc', description, actor);
      break;
    case 'movement':
      addEventLog(description);
      refreshCharacterList();
      refreshMap();
      break;
    case 'discovery':
      addEventLog(description);
      break;
    case 'atmosphere':
      addToFeed('narration', description);
      break;
    default:
      if (description) addEventLog(description);
  }
}

// ── Loading state ─────────────────────────────────────────────────────────────
function setLoading(isLoading) {
  const btnSend = document.getElementById('btn-send');
  const btnInv  = document.getElementById('btn-investigate');
  if (btnSend) {
    btnSend.disabled = isLoading;
    btnSend.textContent = isLoading ? '...' : 'Send';
  }
  if (btnInv) {
    btnInv.disabled = isLoading;
    btnInv.textContent = isLoading ? '...' : 'Investigate';
  }
}

// ── Initialise game screen ────────────────────────────────────────────────────
export function initGame(gameResponse, state, timerConfig = {}) {
  _gameData = gameResponse;
  _state = state;
  _clues = [];
  _selectedNpc = null;
  _selectedAccusee = null;
  _timerConfig = { timerMode: timerConfig.timerMode || 'none', timerMinutes: timerConfig.timerMinutes || 30 };
  clearInterval(_timerInterval);

  // Tear down previous game's event listeners
  if (_abortCtrl) _abortCtrl.abort();
  _abortCtrl = new AbortController();
  const { signal } = _abortCtrl;

  // Populate header
  document.getElementById('game-scenario-title').textContent = gameResponse.title || 'The Mystery';

  // Opening narration
  const feed = document.getElementById('chat-feed');
  feed.innerHTML = '';
  if (gameResponse.opening_narration) {
    addToFeed('narration', gameResponse.opening_narration);
  }
  addToFeed('event', `The victim: ${gameResponse.victim}. The investigation begins.`);

  // Initial location
  const startLoc = gameResponse.locations?.find(l => l.id === gameResponse.player_start);
  if (startLoc) {
    document.getElementById('current-location-name').textContent = startLoc.name;
    document.getElementById('current-location-desc').textContent = startLoc.description;
  }

  // Build map and character list
  buildMap(gameResponse.locations, state.characters, state.player_location);
  refreshCharacterList();

  // Chat controls — all registered on the signal so they auto-remove on next initGame
  document.getElementById('btn-clear-npc')?.addEventListener('click', clearSelectedNpc, { signal });
  document.getElementById('btn-send')?.addEventListener('click', sendMessage, { signal });
  document.getElementById('chat-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  }, { signal });
  document.getElementById('btn-investigate')?.addEventListener('click', investigate, { signal });
  document.getElementById('btn-accuse')?.addEventListener('click', openAccusationModal, { signal });
  document.getElementById('btn-close-accuse')?.addEventListener('click', () =>
    document.getElementById('modal-accuse').classList.add('hidden'), { signal });
  document.getElementById('btn-clear-accusee')?.addEventListener('click', () => {
    _selectedAccusee = null;
    document.getElementById('selected-accusee').classList.add('hidden');
    document.getElementById('btn-confirm-accuse').disabled = true;
    document.querySelectorAll('.accuse-suspect-item').forEach(i => i.classList.remove('selected'));
  }, { signal });
  document.getElementById('btn-confirm-accuse')?.addEventListener('click', confirmAccuse, { signal });
  // play-again handled by app.js

  startTimer();
}
