/**
 * settings.js — Settings modal: API key, model search (with pricing), samplers
 */
import { api } from './api.js';

let _currentModel = '';
let _models = [];

export function initSettings() {
  // Slider live display
  const sliders = [
    ['s-temperature', 's-temperature-val', v => v],
    ['s-top-p', 's-top-p-val', v => v],
    ['s-max-tokens', 's-max-tokens-val', v => parseInt(v).toLocaleString()],
  ];
  sliders.forEach(([sliderId, valId, fmt]) => {
    const s = document.getElementById(sliderId);
    const v = document.getElementById(valId);
    if (s && v) s.addEventListener('input', () => { v.textContent = fmt(s.value); });
  });

  // Test connection
  document.getElementById('btn-test-connection')?.addEventListener('click', testConnection);

  // Model search
  document.getElementById('btn-model-search')?.addEventListener('click', searchModels);
  document.getElementById('settings-model-search')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') searchModels();
  });

  // Open/close
  document.getElementById('btn-settings')?.addEventListener('click', openSettings);
  document.getElementById('btn-game-settings')?.addEventListener('click', openSettings);
  document.getElementById('btn-close-settings')?.addEventListener('click', closeSettings);
  document.getElementById('btn-save-settings')?.addEventListener('click', saveSettings);

  // Click-outside to close
  document.getElementById('modal-settings')?.addEventListener('click', e => {
    if (e.target === document.getElementById('modal-settings')) closeSettings();
  });
}

async function openSettings() {
  document.getElementById('modal-settings').classList.remove('hidden');
  // Load current settings
  try {
    const data = await api.getSettings();
    const el = id => document.getElementById(id);
    if (data.api_key_set) el('settings-api-key').placeholder = '(set — enter new key to change)';
    _currentModel = data.model || '';
    el('selected-model-display').textContent = _currentModel || 'No model selected';
    el('s-temperature').value = data.temperature ?? 0.8;
    el('s-temperature-val').textContent = (data.temperature ?? 0.8).toFixed(2);
    el('s-top-p').value = data.top_p ?? 0.95;
    el('s-top-p-val').textContent = (data.top_p ?? 0.95).toFixed(2);
    el('s-max-tokens').value = data.max_tokens ?? 1024;
    el('s-max-tokens-val').textContent = (data.max_tokens ?? 1024).toLocaleString();
  } catch (e) {
    console.warn('Could not load settings:', e);
  }
}

function closeSettings() {
  document.getElementById('modal-settings').classList.add('hidden');
}

async function testConnection() {
  const apiKey = document.getElementById('settings-api-key').value.trim();
  const statusEl = document.getElementById('connection-status');
  const btn = document.getElementById('btn-test-connection');

  if (!apiKey && !document.getElementById('settings-api-key').placeholder.includes('(set')) {
    statusEl.textContent = '⚠ Enter an API key first';
    statusEl.className = 'connection-status error';
    return;
  }

  btn.disabled = true;
  statusEl.textContent = 'Testing...';
  statusEl.className = 'connection-status';

  try {
    // Save key temporarily and test by hitting models endpoint
    if (apiKey) await api.saveSettings({ api_key: apiKey });
    const resp = await api.fetchModels();
    const count = resp.models?.length ?? 0;
    statusEl.textContent = `✓ Connected — ${count} models available`;
    statusEl.className = 'connection-status ok';
  } catch (e) {
    statusEl.textContent = `✗ ${e.message}`;
    statusEl.className = 'connection-status error';
  } finally {
    btn.disabled = false;
  }
}

async function searchModels() {
  const query = document.getElementById('settings-model-search').value.trim();
  const resultsEl = document.getElementById('model-results');

  resultsEl.innerHTML = '<div style="padding:0.75rem; color:var(--text-muted); font-size:11px">Searching...</div>';
  resultsEl.classList.remove('hidden');

  try {
    const resp = await api.fetchModels(query);
    _models = resp.models || [];
    renderModelResults(_models.slice(0, 60));
  } catch (e) {
    resultsEl.innerHTML = `<div style="padding:0.75rem; color:var(--text-red); font-size:11px">Error: ${e.message}</div>`;
  }
}

function renderModelResults(models) {
  const resultsEl = document.getElementById('model-results');
  if (!models.length) {
    resultsEl.innerHTML = '<div style="padding:0.75rem; color:var(--text-muted); font-size:11px">No models found.</div>';
    return;
  }
  resultsEl.innerHTML = models.map(m => {
    const priceStr = m.is_free
      ? '🟢 FREE'
      : `$${m.prompt_price_per_1m.toFixed(2)}/$${m.completion_price_per_1m.toFixed(2)} per 1M`;
    const ctx = m.context_length ? `${(m.context_length / 1000).toFixed(0)}k ctx` : '';
    return `
      <div class="model-result-item${m.is_free ? ' free' : ''}" data-id="${m.id}">
        <span class="model-result-name">${m.name}</span>
        <span class="model-result-meta">${priceStr}${ctx ? ' · ' + ctx : ''}</span>
      </div>
    `;
  }).join('');

  resultsEl.querySelectorAll('.model-result-item').forEach(item => {
    item.addEventListener('click', () => selectModel(item.dataset.id, item.querySelector('.model-result-name').textContent));
  });
}

function selectModel(id, name) {
  _currentModel = id;
  document.getElementById('selected-model-display').textContent = `${name} (${id})`;
  document.getElementById('model-results').classList.add('hidden');
}

async function saveSettings() {
  const apiKey = document.getElementById('settings-api-key').value.trim();
  const updates = {};
  if (apiKey) updates.api_key = apiKey;
  if (_currentModel) updates.model = _currentModel;
  updates.temperature = parseFloat(document.getElementById('s-temperature').value);
  updates.top_p = parseFloat(document.getElementById('s-top-p').value);
  updates.max_tokens = parseInt(document.getElementById('s-max-tokens').value);

  try {
    const result = await api.saveSettings(updates);
    const statusEl = document.getElementById('connection-status');
    statusEl.textContent = result.llm_connected ? `✓ Saved — connected (${result.model})` : '✓ Saved';
    statusEl.className = 'connection-status ok';
    setTimeout(closeSettings, 1200);
  } catch (e) {
    alert(`Failed to save: ${e.message}`);
  }
}

export function getCurrentModel() { return _currentModel; }
