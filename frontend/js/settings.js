import { api } from './api.js';
import { openModal } from './modal.js';

const $ = id => document.getElementById(id);
const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
};

function field(label, input) {
  const element = node('label', label);
  element.append(input);
  return element;
}

function open() {
  const modal = openModal('OpenRouter generation settings');
  const { body, footer, close } = modal;
  body.append(node(
    'p',
    'An OpenRouter API key is required for each new generated mystery. The selected character cards and predefined location are sent to the model; the host rejects any scenario that fails schema, chronology, discovery, or solvability validation. The labelled offline demo remains provider-free.',
  ));

  const key = document.createElement('input');
  key.type = 'password';
  key.placeholder = 'OpenRouter API key';
  const model = document.createElement('input');
  model.placeholder = 'OpenRouter model ID';
  const temperature = document.createElement('input');
  temperature.type = 'number';
  temperature.min = '0';
  temperature.max = '2';
  temperature.step = '.05';
  temperature.value = '.8';
  body.append(
    field('API key', key),
    field('Model', model),
    field('Temperature', temperature),
  );

  const status = node('p', '', 'muted');
  status.setAttribute('aria-live', 'polite');
  const results = node('div', undefined, 'model-results');
  const search = node('button', 'Search available models', 'secondary');
  search.type = 'button';
  search.addEventListener('click', async () => {
    status.textContent = 'Searching...';
    status.classList.remove('error');
    try {
      const result = await api.models(model.value);
      results.replaceChildren();
      result.models.slice(0, 20).forEach(item => {
        const button = node('button', `${item.name} (${item.id})`, 'model-choice');
        button.type = 'button';
        button.addEventListener('click', () => {
          model.value = item.id;
          status.textContent = 'Model selected.';
        });
        results.append(button);
      });
      status.textContent = `${result.models.length} models returned.`;
    } catch (error) {
      status.textContent = error.message;
      status.classList.add('error');
    }
  });
  body.append(search, status, results);

  const save = node('button', 'Save settings', 'primary');
  save.type = 'button';
  save.addEventListener('click', async () => {
    try {
      const payload = { temperature: Number(temperature.value) };
      if (key.value.trim()) payload.api_key = key.value.trim();
      if (model.value.trim()) payload.model = model.value.trim();
      await api.saveSettings(payload);
      close();
    } catch (error) {
      status.textContent = error.message;
      status.classList.add('error');
    }
  });
  footer.append(save);

  api.settings().then(data => {
    key.placeholder = data.api_key_set
      ? 'Key already stored - enter only to replace'
      : 'OpenRouter API key required';
    model.value = data.model || '';
    temperature.value = data.temperature ?? .8;
  }).catch(() => {});
}

export function initSettings() {
  $('title-settings').addEventListener('click', open);
  $('setup-settings').addEventListener('click', open);
  $('game-settings').addEventListener('click', open);
}
