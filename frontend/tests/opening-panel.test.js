import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';


test('opening panel hides after discovery and reappears when opening content exists', async () => {
  const game = await readFile(new URL('../js/game.js', import.meta.url), 'utf8');

  assert.match(game, /host\.hidden = !game\.opening/);
  assert.match(game, /if \(!game\.opening\) return/);
});
