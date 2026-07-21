import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';


const read = path => readFile(new URL(path, import.meta.url), 'utf8');


test('setup labels OpenRouter generation as required and demo as explicit', async () => {
  const html = await read('../index.html');
  assert.match(html, /OpenRouter then generates the canonical timeline/);
  assert.match(html, /id="offline-demo"[^>]*>Run offline demo fixture/);
  assert.doesNotMatch(html, /No provider is required to play|Optional AI settings/);
});


test('normal start sends generation inputs while demo uses its own endpoint', async () => {
  const app = await read('../js/app.js');
  const api = await read('../js/api.js');
  assert.match(app, /location_id: selectedLocation\(\)\?\.id/);
  assert.match(app, /difficulty: \$\('case-difficulty'\)\.value/);
  assert.match(app, /api\.newGame\(payload\)/);
  assert.match(app, /api\.demoGame\(\{ recipe_id: catalog\.default_recipe_id, seed \}\)/);
  assert.match(api, /demoGame: value => request\('POST','\/game\/demo',value\)/);
});


test('manual generation exposes all cards as checkboxes and requires exactly eight', async () => {
  const app = await read('../js/app.js');
  const html = await read('../index.html');
  assert.match(app, /input\.type = 'checkbox'/);
  assert.match(app, /choices\.length !== 8/);
  assert.match(html, /Choose any eight characters/);
  assert.match(html, /All 24 cards are available/);
});


test('structured provider errors surface their safe message and code', async () => {
  const api = await read('../js/api.js');
  assert.match(api, /data\.detail\.message/);
  assert.match(api, /error\.code =/);
  assert.doesNotMatch(api, /new Error\(detail \|\|[^\n]+\); \}/);
});
