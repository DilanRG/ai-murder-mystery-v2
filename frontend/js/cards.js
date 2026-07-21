import { api } from './api.js';

const node=(tag,text,cls)=>{const item=document.createElement(tag);if(text!==undefined)item.textContent=text;if(cls)item.className=cls;return item;};
const field=(title,input)=>{const label=node('label',title);label.append(input);return label;};

function downloadValidated(raw,id){const parsed=JSON.parse(raw),payload=JSON.stringify(parsed,null,2)+'\n',url=URL.createObjectURL(new Blob([payload],{type:'application/json'})),anchor=document.createElement('a');anchor.href=url;anchor.download=`${id}.json`;anchor.click();URL.revokeObjectURL(url);}

function editorModal(catalog){
  const root=document.getElementById('modal-root'),opener=document.activeElement;root.replaceChildren();
  const overlay=node('div',undefined,'modal-overlay'),panel=node('section',undefined,'modal-panel card-editor'),head=node('header'),body=node('div',undefined,'modal-body'),footer=node('footer',undefined,'modal-footer');
  const close=()=>{root.replaceChildren();if(opener instanceof HTMLElement)opener.focus();};
  panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','true');panel.setAttribute('aria-label','Character card editor');panel.tabIndex=-1;
  const closeButton=node('button','Close','text-button');closeButton.type='button';closeButton.addEventListener('click',close);head.append(node('h2','Character card editor'),closeButton);
  body.append(node('p','Import, inspect, edit, validate, and export JSON Character Card V3 data. Imported prompts remain inert data and drafts do not alter the active case.','muted'));

  const source=document.createElement('select');source.setAttribute('aria-label','Starter card');
  const authoredGroup=document.createElement('optgroup'),draftGroup=document.createElement('optgroup');authoredGroup.label='Authored cards';draftGroup.label='Local drafts';
  (catalog?.characters||[]).forEach(character=>{const option=node('option',character.name);option.value=`authored:${character.id}`;authoredGroup.append(option);});source.append(authoredGroup,draftGroup);
  const addDraftOption=preview=>{if(Array.from(source.options).some(option=>option.value===`draft:${preview.character_id}`))return;const option=node('option',`${preview.name} — ${preview.character_id}`);option.value=`draft:${preview.character_id}`;draftGroup.append(option);};
  api.cardDrafts().then(result=>result.drafts.forEach(addDraftOption)).catch(()=>{});
  const load=node('button','Load selected card','secondary');load.type='button';
  const file=document.createElement('input');file.type='file';file.accept='.json,application/json';file.setAttribute('aria-label','Import JSON card file');
  const characterId=document.createElement('input');characterId.placeholder='canonical_character_id';characterId.setAttribute('aria-label','Character ID');
  const textarea=document.createElement('textarea');textarea.className='card-json';textarea.placeholder='Paste a complete CCv3 JSON object here.';textarea.setAttribute('aria-label','CCv3 JSON');
  const replace=document.createElement('input');replace.type='checkbox';const replaceLabel=node('label',undefined,'check-field');replaceLabel.append(replace,node('span','Replace an existing draft with this ID'));
  const status=node('div','Load an authored card or import JSON to begin.','editor-status muted');
  body.append(field('Start from an authored card',source),load,field('Import JSON file',file),field('Draft character ID',characterId),field('Card JSON',textarea),replaceLabel,status);

  let validatedRaw='';let validatedId='';
  const setStatus=(text,error=false)=>{status.textContent=text;status.className=`editor-status ${error?'error':'found'}`;};
  const loadCard=async(kind,id)=>{try{const data=kind==='draft'?await api.draftCard(id):await api.authoredCard(id);textarea.value=JSON.stringify(data,null,2);characterId.value=kind==='draft'?id:'';validatedRaw='';setStatus('Card loaded. Validate it before saving or exporting.');}catch(error){setStatus(error.message,true);}};
  load.addEventListener('click',()=>{if(!source.value)return;const [kind,id]=source.value.split(':',2);loadCard(kind,id);});
  file.addEventListener('change',async()=>{const selected=file.files?.[0];if(!selected)return;if(selected.size>524288){setStatus('Card file exceeds the 512 KiB limit.',true);return;}try{textarea.value=await selected.text();validatedRaw='';setStatus('File imported. Validate it before saving.');}catch{setStatus('The selected file could not be read.',true);}});
  textarea.addEventListener('input',()=>{validatedRaw='';validatedId='';});characterId.addEventListener('input',()=>{validatedRaw='';validatedId='';});

  const validate=node('button','Validate','secondary'),save=node('button','Save local draft','primary'),exportButton=node('button','Export validated JSON','secondary');
  validate.type=save.type=exportButton.type='button';exportButton.disabled=true;
  validate.addEventListener('click',async()=>{try{const result=await api.validateCard({raw_json:textarea.value,character_id:characterId.value.trim()||null});if(!result.ok){validatedRaw='';exportButton.disabled=true;setStatus(result.issues.map(issue=>issue.message).join(' ')||'Card is invalid.',true);return;}validatedRaw=textarea.value;validatedId=result.preview.character_id;characterId.value=validatedId;exportButton.disabled=false;setStatus(`Valid playable CCv3 card: ${result.preview.name}.`);}catch(error){setStatus(error.message,true);}});
  save.addEventListener('click',async()=>{try{const result=await api.saveCardDraft({raw_json:textarea.value,character_id:characterId.value.trim()||null,replace:replace.checked});validatedRaw=textarea.value;validatedId=result.preview.character_id;characterId.value=validatedId;addDraftOption(result.preview);source.value=`draft:${validatedId}`;exportButton.disabled=false;setStatus(`Saved ${result.filename}.`);}catch(error){setStatus(error.message,true);}});
  exportButton.addEventListener('click',()=>{try{downloadValidated(validatedRaw,validatedId);}catch{setStatus('Validate the JSON again before exporting.',true);}});
  footer.append(validate,exportButton,save);panel.append(head,body,footer);overlay.append(panel);overlay.addEventListener('click',event=>{if(event.target===overlay)close();});panel.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();close();}});root.append(overlay);panel.focus();
}

export function initCardEditor(getCatalog){document.getElementById('card-editor').addEventListener('click',()=>editorModal(getCatalog()));}
