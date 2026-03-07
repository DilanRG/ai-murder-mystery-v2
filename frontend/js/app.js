/**
 * app.js — Entry point
 * Wires all modules together, handles screen flow, particle system, and global events.
 */
import { api, connectWs, onWsEvent } from './api.js';
import { showScreen } from './screens.js';
import { initSettings } from './settings.js';
import { initGame, handleWsEvent, showResults } from './game.js';

// ── Toast Notifications ───────────────────────────────────────────────────────

export function showToast(message, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container') || (() => {
    const el = document.createElement('div');
    el.id = 'toast-container';
    el.style.cssText = 'position:fixed;bottom:2rem;right:2rem;z-index:9999;display:flex;flex-direction:column;gap:0.5rem;';
    document.body.appendChild(el);
    return el;
  })();

  const toast = document.createElement('div');
  const colors = { info: '#c9aa71', error: '#8b0000', success: '#2d6a2d', warning: '#7a5c00' };
  toast.style.cssText = `
    background: rgba(10,10,10,0.92);
    border-left: 3px solid ${colors[type] || colors.info};
    color: #e8dcc8;
    padding: 0.75rem 1.25rem;
    border-radius: 6px;
    font-size: 0.85rem;
    font-family: Inter, sans-serif;
    max-width: 320px;
    backdrop-filter: blur(12px);
    animation: fadeIn 0.2s ease;
  `;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), duration);
}

// ── Background Particle System ────────────────────────────────────────────────

function initParticles() {
  const canvas = document.getElementById('particles-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  let W, H, particles;

  function resize() {
    W = canvas.width = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }

  function makeParticle() {
    return {
      x: Math.random() * W,
      y: Math.random() * H,
      vx: (Math.random() - 0.5) * 0.15,
      vy: -Math.random() * 0.2 - 0.05,
      life: Math.random(),
      maxLife: 0.4 + Math.random() * 0.6,
      size: Math.random() * 1.2 + 0.3,
    };
  }

  function init() {
    resize();
    particles = Array.from({ length: 80 }, makeParticle);
    particles.forEach(p => { p.life = Math.random() * p.maxLife; });
  }

  function tick() {
    ctx.clearRect(0, 0, W, H);
    particles.forEach((p, i) => {
      p.x += p.vx;
      p.y += p.vy;
      p.life += 0.002;
      if (p.life > p.maxLife || p.y < -5) {
        particles[i] = makeParticle();
        particles[i].y = H + 5;
      }
      const prog = p.life / p.maxLife;
      const alpha = prog < 0.3 ? prog / 0.3 : 1 - (prog - 0.3) / 0.7;
      ctx.globalAlpha = alpha * 0.55;
      ctx.fillStyle = '#c9aa71';
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
      ctx.fill();
    });
    ctx.globalAlpha = 1;
    requestAnimationFrame(tick);
  }

  window.addEventListener('resize', () => { resize(); });
  init();
  tick();
}

// ── Title Screen ──────────────────────────────────────────────────────────────

async function checkBackend() {
  const dot = document.getElementById('backend-status');
  const label = document.getElementById('backend-status-label');
  const apiWarn = document.getElementById('api-key-warning');
  try {
    const health = await api.health();
    dot.className = 'status-dot connected';
    label.textContent = health.model ? `Connected · ${health.model}` : 'Connected';
    if (!health.llm_connected) apiWarn?.classList.remove('hidden');
    else apiWarn?.classList.add('hidden');
  } catch {
    dot.className = 'status-dot disconnected';
    label.textContent = 'Backend offline';
    if (apiWarn) {
      apiWarn.classList.remove('hidden');
      apiWarn.textContent = '⚠ Cannot reach backend — is it running?';
    }
  }
}

// ── Setup Screen ──────────────────────────────────────────────────────────────

function initSetup() {
  const timerMinRow = document.getElementById('timer-minutes-row');
  const sliderTimer = document.getElementById('slider-timer');
  const sliderLabel = document.getElementById('slider-timer-label');

  document.getElementById('timer-group')?.addEventListener('change', e => {
    if (e.target.name === 'timer_mode') {
      timerMinRow?.classList.toggle('hidden', e.target.value !== 'realtime');
    }
  });

  sliderTimer?.addEventListener('input', () => {
    if (sliderLabel) sliderLabel.textContent = `${sliderTimer.value} min`;
  });
}

// ── Game End Handling ─────────────────────────────────────────────────────────

function handleGamePhaseChange(data) {
  if (data?.phase !== 'ended') return;

  const correct = data.correct;
  const reason = data.reason || '';
  const narrative = data.narrative || '';

  if (reason === 'timeout') {
    showToast('⏰ Time expired — the killer escapes!', 'error', 6000);
  }

  // Build fake accusation result for results screen
  const fakeResult = {
    correct: correct ?? false,
    reason,
    narrative,
    accused: data.accused || '',
    actual_killer: data.actual_killer || '',
    verdict: correct ? 'Case solved.' : (reason === 'timeout' ? 'Time expired.' : 'The killer walks free.'),
  };

  // Slight delay so the user can read a toast, then show results
  setTimeout(() => {
    api.debrief().then(debrief => {
      showResults({ ...fakeResult, debrief });
    }).catch(() => {
      showResults({ ...fakeResult, debrief: null });
    });
    showScreen('results');
  }, reason === 'timeout' ? 2000 : 500);
}

// ── Game Flow ─────────────────────────────────────────────────────────────────

async function startGame() {
  const btnStart = document.getElementById('btn-start-game');
  btnStart.disabled = true;
  btnStart.textContent = '⟳ Starting...';

  const playerName = document.getElementById('input-player-name')?.value.trim() || 'Detective';
  const playerDesc = document.getElementById('input-player-desc')?.value.trim() || '';
  const difficulty = document.querySelector('input[name="difficulty"]:checked')?.value || 'normal';
  const timerMode = document.querySelector('input[name="timer_mode"]:checked')?.value || 'none';
  const timerMinutes = parseInt(document.getElementById('slider-timer')?.value || '30', 10);

  showScreen('loading');

  // Reset loading steps
  const steps = ['lstep-cast', 'lstep-scenario', 'lstep-world', 'lstep-agents'];
  steps.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.className = 'loading-step';
  });

  let stepIndex = 0;
  function advanceStep() {
    if (stepIndex > 0 && stepIndex - 1 < steps.length) {
      document.getElementById(steps[stepIndex - 1])?.classList.replace('active', 'done');
    }
    if (stepIndex < steps.length) {
      document.getElementById(steps[stepIndex])?.classList.add('active');
    }
    stepIndex++;
  }

  advanceStep(); // Step 1 active immediately

  onWsEvent('loading_status', data => {
    const statusEl = document.getElementById('loading-status');
    if (statusEl) statusEl.textContent = data?.message || '';
    advanceStep();
  });

  // Register game-phase WS handler early
  onWsEvent('game_phase', handleGamePhaseChange);

  try {
    const gameResp = await api.newGame({
      player_name: playerName,
      player_description: playerDesc,
      difficulty,
      timer_mode: timerMode,
      timer_minutes: timerMinutes,
    });

    // Mark all steps done
    steps.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.className = 'loading-step done';
    });

    let state;
    try { state = await api.getState(); } catch { state = gameResp; }

    await new Promise(r => setTimeout(r, 600));

    showScreen('game');
    initGame(gameResp, state, { timerMode, timerMinutes });

    // Route all WS events to game module
    onWsEvent('*', (msg) => handleWsEvent(msg));

  } catch (e) {
    showScreen('setup');
    showToast(`Failed to start game: ${e.message}`, 'error', 8000);
  } finally {
    btnStart.disabled = false;
    btnStart.textContent = '▶ Start Investigation';
  }
}

// ── Play Again ────────────────────────────────────────────────────────────────

function resetToTitle() {
  // Reload the page for a clean state (simplest full reset)
  window.location.reload();
}

// ── Boot ──────────────────────────────────────────────────────────────────────

async function boot() {
  initParticles();
  initSettings();
  initSetup();
  connectWs();

  showScreen('title');
  checkBackend();
  setInterval(checkBackend, 10000);

  // Title → Setup
  document.getElementById('btn-new-game')?.addEventListener('click', () => {
    showScreen('setup');
  });

  // Setup → Title (back)
  document.getElementById('btn-setup-back')?.addEventListener('click', () => {
    showScreen('title');
  });

  // Setup → Game
  document.getElementById('btn-start-game')?.addEventListener('click', startGame);

  // Results → Play Again
  document.getElementById('btn-play-again')?.addEventListener('click', resetToTitle);
}

boot();
