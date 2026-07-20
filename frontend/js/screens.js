const screens = ['title','setup','game','result'];
export function showScreen(name) { screens.forEach(key => document.getElementById(`screen-${key}`)?.classList.toggle('active', key === name)); window.scrollTo({top:0,behavior:'instant'}); }
