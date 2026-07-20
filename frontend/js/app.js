import { api } from './api.js';
import { showScreen } from './screens.js';
import { startGame, resumeGame, bindGameControls, openSaveLoad } from './game.js';
import { initSettings } from './settings.js';

let catalog = null;
const $ = id => document.getElementById(id);
const message = (text, error=false) => { $('connection').textContent=text; $('connection').classList.toggle('error',error); };
async function bootstrap() {
  try { const data=await api.bootstrap(), saved=await api.saves(); catalog=data.catalog; const canResume=Boolean(data.game)||saved.saves.length>0; message(data.game ? 'A local session is ready to resume.' : saved.saves.length ? `${saved.saves.length} saved investigation${saved.saves.length===1?'':'s'} available.` : 'Local case file connected.'); $('resume-game').disabled=!canResume; if(data.game)$('resume-game').onclick=()=>resumeGame(data.game,catalog);else if(saved.saves.length)$('resume-game').onclick=()=>openSaveLoad(true,catalog); updateSetup(data.catalog); }
  catch(error){message(error.message,true);$('new-game').disabled=true;$('resume-game').disabled=true;}
}
function updateSetup(data){ const location=data.locations?.[0], host=$('case-summary');host.replaceChildren();if(!location)return;[['Location',location.name],['Conditions',location.isolation_premise],['Cast',`${data.characters?.length||0} public character records`]].forEach(([term,value])=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=term;dd.textContent=value;host.append(dt,dd);}); }
async function begin(){try{$('start-case').disabled=true;const response=await api.newGame({case_id:catalog.default_case_id,location_id:catalog.default_location_id});startGame(response.game,response.catalog);}catch(e){message(e.message,true);}finally{$('start-case').disabled=false;}}
function setup(){ $('new-game').addEventListener('click',()=>showScreen('setup'));$('start-case').addEventListener('click',begin);document.querySelectorAll('[data-screen]').forEach(x=>x.addEventListener('click',()=>showScreen(x.dataset.screen)));$('again-button').addEventListener('click',()=>showScreen('setup'));bindGameControls();initSettings();bootstrap(); }
setup();
