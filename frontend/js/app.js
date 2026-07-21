import { api } from './api.js';
import { showScreen } from './screens.js';
import { startGame, resumeGame, bindGameControls, openSaveLoad } from './game.js';
import { initSettings } from './settings.js';
import { initCardEditor } from './cards.js';

let catalog = null;
const $ = id => document.getElementById(id);
const message = (text, error=false) => { $('connection').textContent=text; $('connection').classList.toggle('error',error); };
async function bootstrap() {
  try { const data=await api.bootstrap(), saved=await api.saves(); catalog=data.catalog; const canResume=Boolean(data.game)||saved.saves.length>0; message(data.game ? 'A local session is ready to resume.' : saved.saves.length ? `${saved.saves.length} saved investigation${saved.saves.length===1?'':'s'} available.` : 'Local case file connected.'); $('resume-game').disabled=!canResume; if(data.game)$('resume-game').onclick=()=>resumeGame(data.game,catalog);else if(saved.saves.length)$('resume-game').onclick=()=>openSaveLoad(true,catalog); updateSetup(data.catalog); }
  catch(error){message(error.message,true);$('new-game').disabled=true;$('resume-game').disabled=true;}
}
function updateSeedVisibility(){ const seeded=$('case-mode').value.startsWith('recipe:');$('case-seed').disabled=!seeded;$('case-seed-note').hidden=!seeded; }
function updateSetup(data){
  const location=data.locations?.[0], host=$('case-summary'), select=$('case-mode');host.replaceChildren();select.replaceChildren();if(!location)return;
  [['Location',location.name],['Conditions',location.isolation_premise],['Cast',`${data.characters?.length||0} public character records`],['Variations',`${data.recipes?.[0]?.variation_count||1} complete authored crime spines`]].forEach(([term,value])=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=term;dd.textContent=value;host.append(dt,dd);});
  (data.recipes||[]).forEach(recipe=>{const option=document.createElement('option');option.value=`recipe:${recipe.id}`;option.textContent=`${recipe.name} (${recipe.variation_count} possibilities)`;option.selected=recipe.id===data.default_recipe_id;select.append(option);});
  const fixed=document.createElement('option');fixed.value=`case:${data.default_case_id}`;fixed.textContent='Original Ashwick case (fixed)';select.append(fixed);updateSeedVisibility();
}
function randomSeed(){const values=new Uint32Array(1);crypto.getRandomValues(values);return values[0] & 0x7fffffff;}
async function begin(){
  try{
    $('start-case').disabled=true;
    const [mode,id]=$('case-mode').value.split(':',2);let payload;
    if(mode==='recipe'){
      const raw=$('case-seed').value.trim(),seed=raw===''?randomSeed():Number(raw);
      if(!Number.isSafeInteger(seed)||seed<0||seed>2147483647)throw new Error('Case seed must be a whole number from 0 to 2147483647.');
      $('case-seed').value=String(seed);payload={recipe_id:id,seed};
    }else payload={case_id:id,location_id:catalog.default_location_id};
    const response=await api.newGame(payload);startGame(response.game,response.catalog);
  }catch(e){message(e.message,true);}finally{$('start-case').disabled=false;}
}
function setup(){ $('new-game').addEventListener('click',()=>showScreen('setup'));$('start-case').addEventListener('click',begin);$('case-mode').addEventListener('change',updateSeedVisibility);document.querySelectorAll('[data-screen]').forEach(x=>x.addEventListener('click',()=>showScreen(x.dataset.screen)));$('again-button').addEventListener('click',()=>showScreen('setup'));bindGameControls();initSettings();initCardEditor(() => catalog);bootstrap(); }
setup();
