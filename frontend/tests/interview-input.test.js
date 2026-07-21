import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';


test('Ask permits only a trimmed 1-1200 character interview question', async () => {
  const game = await readFile(new URL('../js/game.js', import.meta.url), 'utf8');

  assert.match(game, /const ask = button\('Ask'/);
  assert.match(game, /input\.maxLength\s*=\s*1200/);
  assert.match(game, /input\.disabled = count <= 0/);
  assert.match(game, /ask\.disabled = count <= 0 \|\| question\.length === 0 \|\| question\.length > 1200/);
  assert.match(game, /chip\.disabled = count <= 0/);
  assert.match(game, /input\.addEventListener\('input', updateAskAvailability\)/);
  assert.match(game, /input\.value\s*=\s*s;\s*updateAskAvailability\(\);\s*input\.focus\(\)/);
  assert.match(game, /count===1\?'remains':'remain'/);
});
