import assert from 'node:assert/strict';
import test from 'node:test';

import {
  formatAccusationResult,
  formatResultTitle
} from '../js/game.js';


test('timeout outcome receives a distinct player-facing result', () => {
  const result = {
    end_reason: 'timeout',
    solved: false,
    summary: 'Time expired before you filed a final accusation.'
  };

  assert.equal(formatResultTitle(result), 'Time expired');
  assert.equal(
    formatAccusationResult(result),
    'Time expired before you filed a final accusation.'
  );
});
