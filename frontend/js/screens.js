/**
 * screens.js — Screen navigation with crossfade transitions
 */

const SCREENS = ['title', 'setup', 'loading', 'game', 'results'];

export function showScreen(name) {
  SCREENS.forEach(id => {
    const el = document.getElementById(`screen-${id}`);
    if (!el) return;
    if (id === name) {
      el.style.display = 'flex';
      // Force reflow before adding active class for transition
      void el.offsetWidth;
      el.classList.add('active');
    } else {
      el.classList.remove('active');
      // Hide after transition
      el.addEventListener('transitionend', () => {
        if (!el.classList.contains('active')) el.style.display = 'none';
      }, { once: true });
    }
  });
}

export function currentScreen() {
  return SCREENS.find(id => {
    const el = document.getElementById(`screen-${id}`);
    return el?.classList.contains('active');
  });
}
