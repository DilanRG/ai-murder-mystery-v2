import { api } from './api.js';
import { showScreen } from './screens.js';
import { startGame, resumeGame, bindGameControls, openSaveLoad } from './game.js';
import { initSettings } from './settings.js';
import { initCardEditor } from './cards.js';
import { parseRecipeSeed } from './seed.js';

let catalog = null;
const $ = id => document.getElementById(id);
const message = (text, error = false) => {
  $('connection').textContent = text;
  $('connection').classList.toggle('error', error);
};

async function bootstrap() {
  try {
    const data = await api.bootstrap();
    const saved = await api.saves();
    catalog = data.catalog;
    const canResume = Boolean(data.game) || saved.saves.length > 0;
    message(
      data.game
        ? 'A local session is ready to resume.'
        : saved.saves.length
          ? `${saved.saves.length} saved investigation${saved.saves.length === 1 ? '' : 's'} available.`
          : 'Local case file connected.',
    );
    $('resume-game').disabled = !canResume;
    if (data.game) $('resume-game').onclick = () => resumeGame(data.game, catalog);
    else if (saved.saves.length) $('resume-game').onclick = () => openSaveLoad(true, catalog);
    updateSetup(data.catalog);
  } catch (error) {
    message(error.message, true);
    $('new-game').disabled = true;
    $('resume-game').disabled = true;
  }
}

function selectedLocation() {
  return (catalog?.locations || []).find(item => item.id === $('location-mode').value);
}

function updateCastVisibility() {
  $('manual-cast').hidden = $('cast-mode').value !== 'manual';
}

function renderCastPicker() {
  const host = $('cast-picker');
  host.replaceChildren();
  (catalog?.characters || []).forEach(character => {
    const label = document.createElement('label');
    const input = document.createElement('input');
    const portrait = document.createElement('img');
    const name = document.createElement('span');
    label.className = 'cast-choice';
    input.type = 'checkbox';
    input.name = 'selected-character';
    input.value = character.id;
    portrait.src = character.portrait_url || '';
    portrait.alt = '';
    name.textContent = character.name || character.id;
    label.append(input, portrait, name);
    host.append(label);
  });
}

function updateSetup(data) {
  const location = data.locations?.[0];
  const host = $('case-summary');
  const select = $('location-mode');
  host.replaceChildren();
  select.replaceChildren();
  if (!location) return;
  [
    ['Location pool', `${data.locations.length} predefined location`],
    ['Current setting', location.name],
    ['Conditions', location.isolation_premise],
    ['Character pool', `${data.characters?.length || 0} editable character cards`],
    ['Story engine', 'OpenRouter generates and validates a new canonical mystery'],
  ].forEach(([term, value]) => {
    const dt = document.createElement('dt');
    const dd = document.createElement('dd');
    dt.textContent = term;
    dd.textContent = value;
    host.append(dt, dd);
  });
  data.locations.forEach(item => {
    const option = document.createElement('option');
    option.value = item.id;
    option.textContent = item.name;
    option.selected = item.id === data.default_location_id;
    select.append(option);
  });
  renderCastPicker();
  updateCastVisibility();
}

function randomSeed() {
  const values = new Uint32Array(1);
  crypto.getRandomValues(values);
  return values[0] & 0x7fffffff;
}

async function begin() {
  const start = $('start-case');
  try {
    start.disabled = true;
    start.textContent = 'Generating and validating story...';
    message('OpenRouter is building the timeline, roles, clues, private briefings, and solution...');
    const seed = parseRecipeSeed($('case-seed').value,randomSeed);
    $('case-seed').value = String(seed);
    const payload = {
      seed,
      location_id: selectedLocation()?.id || catalog.default_location_id,
      difficulty: $('case-difficulty').value,
    };
    if ($('cast-mode').value === 'manual') {
      const choices = Array.from(
        document.querySelectorAll('#cast-picker input:checked'),
      ).map(input => input.value);
      if (choices.length !== 8) throw new Error('Choose exactly eight characters from the full pool.');
      payload.character_ids = choices;
    }
    const response = await api.newGame(payload);
    startGame(response.game, response.catalog);
  } catch (error) {
    message(error.message, true);
  } finally {
    start.disabled = false;
    start.textContent = 'Generate new mystery';
  }
}

async function beginDemo() {
  const button = $('offline-demo');
  try {
    button.disabled = true;
    message('Loading the explicit provider-free demo fixture...');
    const seed = parseRecipeSeed($('case-seed').value,randomSeed);
    $('case-seed').value = String(seed);
    const response = await api.demoGame({ recipe_id: catalog.default_recipe_id, seed });
    startGame(response.game, response.catalog);
  } catch (error) {
    message(error.message, true);
  } finally {
    button.disabled = false;
  }
}

function setup() {
  $('new-game').addEventListener('click', () => showScreen('setup'));
  $('start-case').addEventListener('click', begin);
  $('offline-demo').addEventListener('click', beginDemo);
  $('cast-mode').addEventListener('change', updateCastVisibility);
  document.querySelectorAll('[data-screen]').forEach(element =>
    element.addEventListener('click', () => showScreen(element.dataset.screen)),
  );
  $('again-button').addEventListener('click', () => showScreen('setup'));
  bindGameControls();
  initSettings();
  initCardEditor(() => catalog);
  bootstrap();
}

setup();
