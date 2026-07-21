import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { MAX_RECIPE_SEED, parseRecipeSeed } from '../js/seed.js';


test('blank seed delegates to the random seed source', () => {
  assert.equal(parseRecipeSeed('   ', () => 84), 84);
});


test('manual seed accepts the full JavaScript-safe deterministic range', () => {
  assert.equal(parseRecipeSeed('2147483648'), 2_147_483_648);
  assert.equal(parseRecipeSeed(String(MAX_RECIPE_SEED)), Number.MAX_SAFE_INTEGER);
});


test('manual seed rejects minus, fractional, enormous, and malformed values', () => {
  for (const raw of ['-1', '1.5', '9007199254740992', '1e309', 'a-million']) {
    assert.throws(
      () => parseRecipeSeed(raw),
      /whole number from 0 to 9007199254740991/,
      raw,
    );
  }
});


test('a broken random source cannot bypass the seed contract', () => {
  for (const generated of [-1, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
    assert.throws(
      () => parseRecipeSeed('', () => generated),
      /whole number from 0 to 9007199254740991/,
      String(generated),
    );
  }
});


test('new-story seed input advertises the same exact range', async () => {
  const html = await readFile(new URL('../index.html', import.meta.url), 'utf8');
  const input = html.match(/<input id="case-seed"[^>]+>/)?.[0] ?? '';
  assert.match(input, /min="0"/);
  assert.match(input, new RegExp(`max="${MAX_RECIPE_SEED}"`));
  assert.match(input, /step="1"/);
});


test('new-story submission uses the shared seed parser', async () => {
  const app = await readFile(new URL('../js/app.js', import.meta.url), 'utf8');
  assert.match(app, /import \{ parseRecipeSeed \} from '\.\/seed\.js'/);
  assert.match(app, /parseRecipeSeed\(\$\('case-seed'\)\.value,randomSeed\)/);
  assert.doesNotMatch(app, /seed>2147483647/);
});
