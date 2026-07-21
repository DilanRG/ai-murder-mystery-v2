const BASE = '/api';
async function request(method, path, body) {
  let response;
  try { response = await fetch(`${BASE}${path}`, { method, headers: body === undefined ? {} : {'Content-Type':'application/json'}, body: body === undefined ? undefined : JSON.stringify(body) }); }
  catch { throw new Error('The local game server cannot be reached. Start the backend and try again.'); }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) { const detail = Array.isArray(data.detail) ? data.detail.map(x => x.msg).join(', ') : data.detail; throw new Error(detail || `Request failed (${response.status}).`); }
  return data;
}
export const api = {
  health: () => request('GET','/health'), settings: () => request('GET','/settings'), saveSettings: value => request('POST','/settings',value), models: q => request('GET',`/models?q=${encodeURIComponent(q)}`),
  bootstrap: () => request('GET','/game/bootstrap'), catalog: () => request('GET','/game/catalog'), newGame: value => request('POST','/game/new',value), state: () => request('GET','/game/state'), action: intent => request('POST','/game/action',intent),
  saves: () => request('GET','/game/saves/v1'), save: filename => request('POST','/game/saves/v1',{filename}), load: filename => request('POST',`/game/saves/v1/${encodeURIComponent(filename)}/load`), debrief: () => request('GET','/game/debrief'),
  validateCard: value => request('POST','/cards/validate',value), saveCardDraft: value => request('POST','/cards/drafts',value), cardDrafts: () => request('GET','/cards/drafts'), authoredCard: id => request('GET',`/cards/authored/${encodeURIComponent(id)}/export`), draftCard: id => request('GET',`/cards/drafts/${encodeURIComponent(id)}/export`)
};
