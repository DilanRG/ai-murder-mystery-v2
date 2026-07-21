import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';


test('timeout outcome receives a distinct player-facing result title', async () => {
  const game = await readFile(new URL('../js/game.js', import.meta.url), 'utf8');

  assert.match(game, /result\?\.end_reason==='timeout'\?'Time expired'/);
  assert.match(game, /result\?\.summary\|\|'The investigation has ended\.'/);
});
