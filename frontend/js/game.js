import { api } from './api.js';
import { showScreen } from './screens.js';

let game = null, catalog = null, selectedTab = 'evidence', feed = [], submitting = false, portrayalByStatement = new Map();
const $ = id => document.getElementById(id);
const el = (tag, text, cls) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; };
const button = (text, fn, cls='secondary') => { const node = el('button', text, cls); node.type = 'button'; node.addEventListener('click', fn); return node; };

export function startGame(view, publicCatalog) { game = view; catalog = publicCatalog; selectedTab = 'evidence'; feed = []; portrayalByStatement = new Map(); render(); showScreen('game'); }
export function resumeGame(view, publicCatalog) { startGame(view, publicCatalog); addFeed('Session resumed.'); }

async function act(intent) {
  if (submitting) return;
  submitting = true;
  document.body.setAttribute('aria-busy','true');
  const controls = [...document.querySelectorAll('#screen-game button')];
  const disabledBefore = new Map(controls.map(control => [control, control.disabled]));
  controls.forEach(control => { control.disabled = true; });
  try {
    const result = await api.action(intent);
    game = result.game;
    addFeed(result.narration, result.accepted ? '' : 'rejected');
    if (result.dialogue) {
      const spoken = result.portrayal?.surface_utterance || result.dialogue.text;
      if (result.portrayal?.surface_utterance) portrayalByStatement.set(result.dialogue.id, spoken);
      addFeed(`${result.dialogue.speaker_name}: ${spoken}`, 'dialogue');
    }
    result.discoveries?.forEach(item => addFeed(`Evidence recorded: ${item.name}.`, 'found'));
    result.items?.forEach(item => addFeed(`Added to inventory: ${item.name}.`, 'found'));
    result.events?.forEach(item => addFeed(item, 'event'));
    if (game.phase === 'ended') await showResult(); else render();
    return result;
  } catch (error) { toast(error.message, 'error'); }
  finally { submitting = false; document.body.removeAttribute('aria-busy'); disabledBefore.forEach((disabled,control)=>{if(control.isConnected)control.disabled=disabled;}); }
}
function addFeed(text, type='') { feed.unshift({text,type}); renderNarration(); }
function toast(text, type='') { const msg = el('div', text, `toast ${type}`); $('toast-region').append(msg); window.setTimeout(() => msg.remove(), 5500); }

function render() {
  if (!game) return;
  $('case-title').textContent = game.case_title; $('room-label').textContent = game.player_room.name; $('turn-label').textContent = `Turn ${game.turn}`; $('time-label').textContent = game.time_label; $('accuse-button').disabled = game.phase !== 'investigation' || Boolean(game.active_interview_character_id);
  $('scene-name').textContent = game.player_room.name; $('scene-description').textContent = game.player_room.description;
  renderOpening(); renderMap(); renderCharacters(); renderActions(); renderNarration(); renderNotebook();
}
function renderOpening() {
  const host = $('opening-panel'); host.replaceChildren();
  if (!game.opening) return;
  const opening = game.opening;
  host.append(el('p','Discovery meeting','eyebrow'),el('h2',`${opening.victim_name} is dead.`),el('p',opening.body_condition));
  const quote = el('blockquote', opening.containment_statement); host.append(quote);
  if (opening.discoverer_observations?.length) { const list = el('ul'); opening.discoverer_observations.forEach(x=>list.append(el('li',x))); host.append(list); }
  const reactions = el('details'); reactions.append(el('summary','Witness reactions')); const list=el('ul'); opening.initial_reactions.forEach(x=>list.append(el('li',`${x.speaker_name}: ${x.text}`))); reactions.append(list); host.append(reactions);
  host.append(button('Conclude discovery meeting',()=>act({kind:'advance_opening'}),'primary'));
}
function roomData() { return catalog?.locations?.[0] || {rooms:[],doors:[]}; }
function renderMap() {
  const host = $('room-map'); host.replaceChildren(); const loc=roomData(); const exits=new Set(game.player_room.exits);
  loc.rooms.forEach(room => { const isHere = room.id === game.player_room.id, valid = exits.has(room.id); const b = button(room.short_name || room.name, ()=> valid && act({kind:'move',room_id:room.id}),`map-room${isHere?' here':''}${valid?' exit':''}`); b.title = room.name; b.setAttribute('aria-label',`${room.name}${isHere?' (current room)':valid?' (move here)':' (not connected)'}`); b.disabled = !valid || game.phase !== 'investigation' || Boolean(game.active_interview_character_id); host.append(b); });
  $('map-note').textContent = game.phase === 'discovery' ? 'Finish the discovery meeting to move through the manor.' : `${game.player_room.exits.length} unlocked route${game.player_room.exits.length===1?'':'s'} from here.`;
}
function renderCharacters() {
  const host=$('present-characters'); host.replaceChildren();
  if (!game.present_characters.length) host.append(el('p','Nobody is here.','muted'));
  game.present_characters.forEach(person => { const card=el('article',undefined,'person-card'); card.append(portrait(person),el('strong',person.name),el('p',person.description || 'A guest with a story.')); const active=game.active_interview_character_id===person.id; const control=button(active?'Continue interview':'Question',()=>active?interviewModal(person):act({kind:'begin_interview',character_id:person.id}).then(result=>{if(result?.accepted&&game.active_interview_character_id===person.id)interviewModal(person);}),active?'primary':'secondary'); control.disabled=Boolean(game.active_interview_character_id)&&!active; card.append(control); host.append(card); });
}
function renderActions() {
  const host=$('scene-actions'); host.replaceChildren();
  if (game.phase !== 'investigation') return;
  if (game.active_interview_character_id) { const person=game.present_characters.find(item=>item.id===game.active_interview_character_id); host.append(button(`Continue interview${person?`: ${person.name}`:''}`,()=>person&&interviewModal(person),'primary')); return; }
  game.player_room.searchable_objects.forEach(object => host.append(button(`Search: ${object.name}`,()=>act({kind:'search',object_id:object.id}),'action-button')));
  game.available_scenes.forEach(scene => host.append(
    button(scene.label,()=>act({kind:'examine_scene',scene_id:scene.id}),'action-button')
  ));
  game.discovered_evidence.forEach(item => host.append(button(`Examine: ${item.name}`,()=>act({kind:'examine_evidence',evidence_id:item.id}),'quiet-button')));
  host.append(button('Review notebook',()=>act({kind:'review_notebook'}),'quiet-button'));
}
function renderNarration() { const host=$('narration'); host.replaceChildren(); if(!feed.length) host.append(el('li','The case file is waiting for your first move.','muted')); feed.slice(0,24).forEach(entry=>host.append(el('li',entry.text,entry.type))); }
function renderNotebook() {
  document.querySelectorAll('.tab').forEach(tab=>{const active=tab.dataset.tab===selectedTab;tab.classList.toggle('active',active);tab.setAttribute('aria-selected',String(active));});
  const host=$('notebook-panel'); host.replaceChildren();
  if(selectedTab==='evidence') { renderEvidence(host); return; } if(selectedTab==='facts') { renderFacts(host); return; } if(selectedTab==='suspects') { renderSuspects(host); return; } renderNotes(host);
}
function renderEvidence(host) { host.append(el('p',`${game.discovered_evidence.length} item${game.discovered_evidence.length===1?'':'s'} catalogued.`,'muted')); if(!game.discovered_evidence.length) host.append(el('p','No evidence has been collected.')); game.discovered_evidence.forEach(item=>{const card=el('article',undefined,'record-card');card.append(el('strong',item.name),el('span',item.kind,'tag'),el('p',item.description));host.append(card);}); if(game.inventory.length){host.append(el('h3','Inventory'));game.inventory.forEach(item=>{const card=el('article',undefined,'record-card');card.append(el('strong',item.name),el('p',item.description));host.append(card);});} }
function renderFacts(host) { if(!game.known_facts.length) host.append(el('p','Facts will appear when evidence supports them.','muted')); game.known_facts.forEach(item=>{const card=el('article',undefined,'record-card');card.append(el('span',item.category,'tag'),el('p',item.statement));host.append(card);}); }
function renderSuspects(host) { game.suspects.forEach(person=>{const card=el('article',undefined,'person-card');card.append(portrait(person),el('strong',person.name),el('p',person.description || 'A surviving member of the house party.'));host.append(card);}); }
function renderNotes(host) {
  const noteForm=el('form',undefined,'note-form'), input=document.createElement('textarea'); input.placeholder='Private note — stored in this save.'; input.setAttribute('aria-label','Add notebook note'); const add=button('Add note', async e=>{e.preventDefault();if(input.value.trim()) await act({kind:'add_note',text:input.value.trim()});},'secondary'); noteForm.append(input,add); host.append(noteForm);
  if(game.notes.length){const h=el('h3','Notes');host.append(h);game.notes.forEach(note=>host.append(el('p',note,'note')));}
  const timeline=el('details'); timeline.append(el('summary',`Timeline (${game.timeline.length})`)); const form=el('form',undefined,'timeline-form'), minute=document.createElement('input'), text=document.createElement('input'); minute.type='number';minute.placeholder='Time (minutes)';text.placeholder='Timeline entry'; const sources=sourceSelect(true); form.append(minute,text,sources,button('Add timeline',async e=>{e.preventDefault();if(text.value.trim()) await act({kind:'add_timeline_entry',text:text.value.trim(),minute:minute.value?Number(minute.value):null,source_ids:selectedValues(sources)});},'secondary')); timeline.append(form); game.timeline.forEach(t=>timeline.append(el('p',`${t.minute===null?'Undated':formatMinute(t.minute)} — ${t.text}`,'note')));host.append(timeline);
  const comp=el('details');comp.append(el('summary',`Compare statements (${game.statements.length})`));if(game.statements.length<2)comp.append(el('p','Record two interview statements first.','muted'));else{const a=statementSelect(),b=statementSelect(),note=document.createElement('input');note.placeholder='Why do they conflict?';comp.append(a,b,note,button('Mark contradiction',()=>act({kind:'mark_contradiction',left_statement_id:a.value,right_statement_id:b.value,note:note.value}),'secondary'));} game.contradictions.forEach(c=>comp.append(el('p',`Marked: ${c.note || 'possible contradiction'}`,'note')));host.append(comp);
  if (game.statements.length) { const record=el('details'); record.append(el('summary',`Interview record (${game.statements.length})`)); game.statements.forEach(statement=>record.append(el('p',`${statement.speaker_name}: ${portrayalByStatement.get(statement.id) || statement.text}`,'note'))); host.append(record); }
}
function sourceSelect(multi=false) { const select=document.createElement('select');select.multiple=multi;select.setAttribute('aria-label','Sources'); [...game.discovered_evidence,...game.known_facts,...game.statements].forEach(x=>{const o=el('option',x.name||x.statement||`${x.speaker_name}: ${x.text}`);o.value=x.id;select.append(o);});return select; }
function evidenceSelect() { const select=document.createElement('select');select.multiple=true;select.setAttribute('aria-label','Supporting evidence');game.discovered_evidence.forEach(x=>{const o=el('option',x.name);o.value=x.id;select.append(o);});return select; }
function statementSelect(){const s=document.createElement('select');game.statements.forEach(x=>{const o=el('option',`${x.speaker_name}: ${x.text}`);o.value=x.id;s.append(o);});return s;}
function selectedValues(select){return Array.from(select.selectedOptions).map(x=>x.value);}
function formatMinute(value){return `${String(Math.floor(value/60)%24).padStart(2,'0')}:${String(value%60).padStart(2,'0')}`;}

function interviewModal(person) {
  const modal=modalShell(`Question ${person.name}`), count=game.active_interview_exchanges_remaining ?? 0; modal.body.append(el('p',`${count} exchange${count===1?'':'s'} remain in this interview.`)); const suggestions=['Where were you when it happened?','What did you see near the victim?','Who can confirm your account?']; const suggest=el('div',undefined,'suggestions'), input=document.createElement('textarea');input.placeholder='Ask a focused question…';input.setAttribute('aria-label','Question');suggestions.forEach(s=>suggest.append(button(s,()=>{input.value=s;input.focus();},'chip')));modal.body.append(suggest,input);modal.footer.append(button('Ask',async()=>{if(input.value.trim()){closeModal();await act({kind:'interview_exchange',message:input.value.trim()}); if(game.active_interview_character_id) interviewModal(person);}},'primary'),button('Conclude interview',async()=>{closeModal();await act({kind:'end_interview'});},'secondary'));
}
export function openAccusation() {
  const modal=modalShell('Make a final accusation'); modal.body.append(el('p','Choose a living suspect and support every part of the case with knowledge you have actually learned.'));
  const suspect=document.createElement('select');suspect.setAttribute('aria-label','Suspect');game.suspects.forEach(x=>{const o=el('option',x.name);o.value=x.id;suspect.append(o);});
  const method=factSelect(['means','forensics'],'Method'),motive=factSelect(['motive'],'Motive'),timeline=factSelect(['timeline','opportunity'],'Timeline fact'),evidence=evidenceSelect();modal.body.append(labelled('Suspect',suspect),labelled('Method fact',method),labelled('Motive fact',motive),labelled('Timeline fact',timeline),labelled('Supporting evidence',evidence));modal.footer.append(button('Submit final accusation',async()=>{closeModal();await act({kind:'accuse',character_id:suspect.value,evidence_ids:selectedValues(evidence),method:method.selectedOptions[0]?.textContent||'',motive:motive.selectedOptions[0]?.textContent||'',timeline:timeline.selectedOptions[0]?.textContent||'',timeline_fact_ids:timeline.value?[timeline.value]:[]});},'danger'));
}
function factSelect(categories, placeholder){const s=document.createElement('select');s.setAttribute('aria-label',placeholder);s.append(el('option',`Select ${placeholder}`));s.options[0].value='';game.known_facts.filter(x=>categories.includes(x.category)).forEach(x=>{const o=el('option',x.statement);o.value=x.id;s.append(o);});return s;}
function initials(name){return name.split(/\s+/).map(part=>part[0]).join('').slice(0,2).toUpperCase();}
function portrait(person) {
  const fallback=()=>el('span',initials(person.name),'person-avatar');
  if (!person.portrait_url) return fallback();
  const image=document.createElement('img'); image.className='person-portrait'; image.src=person.portrait_url; image.alt=`Portrait placeholder for ${person.name}`;
  image.addEventListener('error',()=>image.replaceWith(fallback()),{once:true});
  return image;
}
function labelled(title,input){const l=el('label',title);l.append(input);return l;}
function modalShell(title){const root=$('modal-root'),opener=document.activeElement;root.replaceChildren();const overlay=el('div',undefined,'modal-overlay'),panel=el('section',undefined,'modal-panel'),head=el('header'),close=()=>{root.replaceChildren();if(opener instanceof HTMLElement)opener.focus();};panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','true');panel.setAttribute('aria-label',title);panel.tabIndex=-1;head.append(el('h2',title),button('Close',close,'text-button'));const body=el('div',undefined,'modal-body'),footer=el('footer',undefined,'modal-footer');panel.append(head,body,footer);overlay.append(panel);overlay.addEventListener('click',e=>{if(e.target===overlay)close();});panel.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();close();}});root.append(overlay);panel.focus();return{body,footer};}
function closeModal(){$('modal-root').replaceChildren();}
async function showResult(){ showScreen('result'); const result=game.result; $('result-title').textContent=result?.solved?'Case solved':'Case concluded';$('result-summary').textContent=result?.summary||'The investigation has ended.';$('debrief-content').replaceChildren();$('debrief-button').hidden=false; }
export async function revealDebrief(){try{const data=await api.debrief(),solution=data.solution,host=$('debrief-content');host.replaceChildren();host.append(el('h3',`The truth: ${solution.culprit_name}`),el('p',`Method: ${solution.method}`),el('p',`Motive: ${solution.motive}`),el('p',`Opportunity: ${solution.opportunity}`),el('p',solution.cover_story));const list=el('ul');solution.supporting_evidence.forEach(x=>list.append(el('li',`${x.name} — ${x.description}`)));host.append(el('h3','Supporting evidence'),list);$('debrief-button').hidden=true;}catch(error){toast(error.message,'error');}}
export function openSaveLoad(loadOnly=false, publicCatalog=catalog){const modal=modalShell(loadOnly?'Load investigation':'Save or load investigation');const name=document.createElement('input');name.placeholder='Save name';if(!loadOnly)modal.body.append(labelled('Save current case',name));modal.body.append(el('p','Loading replaces the current local session.','muted'));const saves=el('div',undefined,'stack');modal.body.append(saves);api.saves().then(data=>{if(!data.saves.length)saves.append(el('p','No saves found.','muted'));data.saves.forEach(file=>saves.append(button(`Load ${file}`,async()=>{const result=await api.load(file);closeModal();resumeGame(result.game,publicCatalog);toast(`Loaded ${file}.`,'found');},'secondary')));}).catch(e=>saves.append(el('p',e.message,'rejected')));if(!loadOnly)modal.footer.append(button('Save',async()=>{try{const result=await api.save(name.value.trim()||'ashwick-save');toast(`Saved as ${result.filename}.`,'found');closeModal();}catch(e){toast(e.message,'error');}},'primary'));}
export function bindGameControls(){document.querySelectorAll('.tab').forEach(tab=>tab.addEventListener('click',()=>{selectedTab=tab.dataset.tab;renderNotebook();}));$('accuse-button').addEventListener('click',openAccusation);$('save-button').addEventListener('click',()=>openSaveLoad());$('debrief-button').addEventListener('click',revealDebrief);}
