import { api } from './api.js';
import { showScreen } from './screens.js';
import { startGame, resumeGame, bindGameControls, openSaveLoad } from './game.js';
import { initSettings } from './settings.js';
import { initCardEditor } from './cards.js';
import { parseRecipeSeed } from './seed.js';

let catalog = null;
const $ = id => document.getElementById(id);
const message = (text, error=false) => { $('connection').textContent=text; $('connection').classList.toggle('error',error); };
async function bootstrap() {
  try { const data=await api.bootstrap(), saved=await api.saves(); catalog=data.catalog; const canResume=Boolean(data.game)||saved.saves.length>0; message(data.game ? 'A local session is ready to resume.' : saved.saves.length ? `${saved.saves.length} saved investigation${saved.saves.length===1?'':'s'} available.` : 'Local case file connected.'); $('resume-game').disabled=!canResume; if(data.game)$('resume-game').onclick=()=>resumeGame(data.game,catalog);else if(saved.saves.length)$('resume-game').onclick=()=>openSaveLoad(true,catalog); updateSetup(data.catalog); }
  catch(error){message(error.message,true);$('new-game').disabled=true;$('resume-game').disabled=true;}
}
function selectedRecipe(){const [mode,id]=$('case-mode').value.split(':',2);return mode==='recipe'?(catalog?.recipes||[]).find(item=>item.id===id):null;}
function updateCastVisibility(){const recipe=selectedRecipe(),manual=Boolean(recipe)&&$('cast-mode').value==='manual';$('cast-mode').disabled=!recipe;$('manual-cast').hidden=!manual;}
function renderCastPicker(){
  const host=$('cast-picker'),recipe=selectedRecipe(),characters=new Map((catalog?.characters||[]).map(item=>[item.id,item]));host.replaceChildren();
  (recipe?.cast_groups||[]).forEach((group,index)=>{const section=document.createElement('section');section.className='cast-group';const heading=document.createElement('h3');heading.textContent=`Ensemble choice ${index+1}`;section.append(heading);group.candidate_character_ids.forEach(id=>{const character=characters.get(id),label=document.createElement('label'),input=document.createElement('input'),portrait=document.createElement('img'),name=document.createElement('span');label.className='cast-choice';input.type='radio';input.name=`cast-group-${index}`;input.value=id;portrait.src=character?.portrait_url||'';portrait.alt='';name.textContent=character?.name||id;label.append(input,portrait,name);section.append(label);});host.append(section);});
}
function updateSeedVisibility(){ const seeded=$('case-mode').value.startsWith('recipe:');$('case-seed').disabled=!seeded;$('case-seed-note').hidden=!seeded;renderCastPicker();updateCastVisibility(); }
function updateSetup(data){
  const location=data.locations?.[0], host=$('case-summary'), select=$('case-mode');host.replaceChildren();select.replaceChildren();if(!location)return;
  [['Location',location.name],['Conditions',location.isolation_premise],['Character pool',`${data.characters?.length||0} editable character cards`],['Story combinations',`${data.recipes?.[0]?.variation_count||1} validated cast and mystery combinations`]].forEach(([term,value])=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=term;dd.textContent=value;host.append(dt,dd);});
  (data.recipes||[]).forEach(recipe=>{const option=document.createElement('option');option.value=`recipe:${recipe.id}`;option.textContent=`${recipe.name} (${recipe.variation_count} possibilities)`;option.selected=recipe.id===data.default_recipe_id;select.append(option);});
  const fixed=document.createElement('option');fixed.value=`case:${data.default_case_id}`;fixed.textContent='Original Ashwick case (fixed)';select.append(fixed);updateSeedVisibility();
}
function randomSeed(){const values=new Uint32Array(1);crypto.getRandomValues(values);return values[0] & 0x7fffffff;}
async function begin(){
  try{
    const start=$('start-case');start.disabled=true;start.textContent='Casting and directing story…';message('Selecting the ensemble, directing the evening, and validating the case…');
    const [mode,id]=$('case-mode').value.split(':',2);let payload;
    if(mode==='recipe'){
      const seed=parseRecipeSeed($('case-seed').value,randomSeed);
      $('case-seed').value=String(seed);payload={recipe_id:id,seed};
      if($('cast-mode').value==='manual'){const choices=Array.from(document.querySelectorAll('#cast-picker input:checked')).map(input=>input.value);if(choices.length!==8)throw new Error('Choose one character from each of the eight ensemble groups.');payload.character_ids=choices;}
    }else payload={case_id:id,location_id:catalog.default_location_id};
    const response=await api.newGame(payload);startGame(response.game,response.catalog);
  }catch(e){message(e.message,true);}finally{$('start-case').disabled=false;$('start-case').textContent='Open the case';}
}
function setup(){ $('new-game').addEventListener('click',()=>showScreen('setup'));$('start-case').addEventListener('click',begin);$('case-mode').addEventListener('change',updateSeedVisibility);$('cast-mode').addEventListener('change',updateCastVisibility);document.querySelectorAll('[data-screen]').forEach(x=>x.addEventListener('click',()=>showScreen(x.dataset.screen)));$('again-button').addEventListener('click',()=>showScreen('setup'));bindGameControls();initSettings();initCardEditor(() => catalog);bootstrap(); }
setup();
