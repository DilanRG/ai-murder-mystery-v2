let activeModal = null;
let modalNumber = 0;

const focusableSelector = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])'
].join(',');

function focusableElements(panel) {
  return [...panel.querySelectorAll(focusableSelector)].filter(node =>
    !node.hidden && node.getAttribute('aria-hidden') !== 'true'
  );
}

export function openModal(title, { className = '' } = {}) {
  activeModal?.close(false);
  const root = document.getElementById('modal-root');
  const opener = document.activeElement;
  const app = document.querySelector('main');
  const overlay = document.createElement('div');
  const panel = document.createElement('section');
  const header = document.createElement('header');
  const heading = document.createElement('h2');
  const body = document.createElement('div');
  const footer = document.createElement('footer');
  const closeButton = document.createElement('button');
  const headingId = `modal-title-${++modalNumber}`;

  overlay.className = 'modal-overlay';
  panel.className = `modal-panel${className ? ` ${className}` : ''}`;
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-modal', 'true');
  panel.setAttribute('aria-labelledby', headingId);
  panel.tabIndex = -1;
  heading.id = headingId;
  heading.textContent = title;
  closeButton.type = 'button';
  closeButton.className = 'text-button';
  closeButton.textContent = 'Close';
  body.className = 'modal-body';
  footer.className = 'modal-footer';

  let closed = false;
  const close = (restoreFocus = true) => {
    if (closed) return;
    closed = true;
    root.replaceChildren();
    if (app) app.inert = false;
    if (activeModal?.panel === panel) activeModal = null;
    if (restoreFocus && opener instanceof HTMLElement && opener.isConnected) {
      opener.focus();
    }
  };

  closeButton.addEventListener('click', () => close());
  overlay.addEventListener('click', event => {
    if (event.target === overlay) close();
  });
  panel.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== 'Tab') return;
    const controls = focusableElements(panel);
    if (!controls.length) {
      event.preventDefault();
      panel.focus();
      return;
    }
    const first = controls[0], last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  header.append(heading, closeButton);
  panel.append(header, body, footer);
  overlay.append(panel);
  root.replaceChildren(overlay);
  if (app) app.inert = true;
  activeModal = { panel, close };
  panel.focus();
  return { panel, body, footer, close };
}

export function closeActiveModal() {
  activeModal?.close();
}
