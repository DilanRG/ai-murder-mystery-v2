import assert from 'node:assert/strict';
import test from 'node:test';

import {
  formatAccusationResult,
  submitAccusation
} from '../js/game.js';


test('final accusation submits the exact selected support and contradictions', async () => {
  const calls = [];
  const response = { accepted: true };
  const action = async intent => {
    calls.push(intent);
    return response;
  };

  const result = await submitAccusation(action, {
    characterId: 'gabriel_cross',
    evidenceIds: ['poker', 'accounts', 'clock'],
    method: 'The poker delivered the fatal blow.',
    motive: 'The accounts exposed the theft.',
    timeline: 'The clock stopped at the murder minute.',
    timelineFactId: 'timeline_clock',
    confirmedContradictionIds: ['contradiction_1']
  });

  assert.equal(result, response);
  assert.deepEqual(calls, [{
    kind: 'accuse',
    character_id: 'gabriel_cross',
    selected_supporting_evidence_ids: ['poker', 'accounts', 'clock'],
    method: 'The poker delivered the fatal blow.',
    motive: 'The accounts exposed the theft.',
    timeline: 'The clock stopped at the murder minute.',
    timeline_fact_ids: ['timeline_clock'],
    confirmed_contradiction_ids: ['contradiction_1']
  }]);
});


test('final result renders all six supported dimensions', () => {
  const text = formatAccusationResult({
    end_reason: 'accusation',
    summary: 'Your accusation is sufficiently supported.',
    correct_culprit: true,
    method_supported: true,
    motive_supported: true,
    timeline_supported: true,
    evidence_supported: true,
    contradictions_supported: true,
    evaluation_score: 6
  });

  assert.equal(
    text,
    'Your accusation is sufficiently supported. Evaluation (6/6): culprit: supported; method: supported; motive: supported; timeline: supported; evidence route: supported; contradictions: supported.'
  );
});


test('final result exposes an incomplete route and unsupported contradiction', () => {
  const text = formatAccusationResult({
    end_reason: 'accusation',
    summary: 'Your accusation lacks sufficient support.',
    correct_culprit: true,
    method_supported: true,
    motive_supported: true,
    timeline_supported: true,
    evidence_supported: false,
    contradictions_supported: false,
    evaluation_score: 4
  });

  assert.equal(
    text,
    'Your accusation lacks sufficient support. Evaluation (4/6): culprit: supported; method: supported; motive: supported; timeline: supported; evidence route: unsupported; contradictions: unsupported.'
  );
});
