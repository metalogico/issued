/** Shared, keyboard-accessible tooltips for Issued's icon controls. */
(() => {
  const tip = document.createElement('div');
  tip.id = 'issued-control-tooltip';
  tip.className = 'issued-tooltip';
  tip.setAttribute('role', 'tooltip');
  tip.hidden = true;
  document.body.append(tip);
  let active = null;
  let timer;
  const hover = window.matchMedia('(hover: hover)');

  const hide = () => {
    clearTimeout(timer);
    if (active) {
      const ids = (active.getAttribute('aria-describedby') || '').split(/\s+/)
        .filter(id => id && id !== tip.id);
      if (ids.length) active.setAttribute('aria-describedby', ids.join(' '));
      else active.removeAttribute('aria-describedby');
    }
    active = null;
    tip.hidden = true;
  };
  const show = (control) => {
    if (!control?.isConnected || control.disabled || control.getAttribute('aria-expanded') === 'true'
      || (control.tagName === 'SUMMARY' && control.parentElement.open)) return;
    hide();
    active = control;
    tip.textContent = control.dataset.uiTooltip;
    const ids = (control.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
    control.setAttribute('aria-describedby', [...new Set([...ids, tip.id])].join(' '));
    tip.hidden = false;
    const rect = control.getBoundingClientRect();
    const bounds = tip.getBoundingClientRect();
    const above = rect.top >= bounds.height + 12;
    tip.style.left = `${Math.max(8, Math.min(innerWidth - bounds.width - 8,
      rect.left + (rect.width - bounds.width) / 2))}px`;
    tip.style.top = `${Math.max(8, Math.min(innerHeight - bounds.height - 8,
      above ? rect.top - bounds.height - 8 : rect.bottom + 8))}px`;
  };
  document.addEventListener('pointerover', event => {
    if (!hover.matches || event.pointerType === 'touch') return;
    if (tip.contains(event.target)) { clearTimeout(timer); return; }
    const control = event.target.closest('[data-ui-tooltip]');
    if (!control || control.contains(event.relatedTarget)) return;
    hide();
    timer = setTimeout(() => show(control), 300);
  });
  document.addEventListener('pointerout', event => {
    const control = event.target.closest('[data-ui-tooltip]');
    if (control?.contains(event.relatedTarget) || tip.contains(event.relatedTarget)) return;
    if (control || tip.contains(event.target)) {
      clearTimeout(timer);
      timer = setTimeout(hide, 120);
    }
  });
  document.addEventListener('focusin', event => {
    const control = event.target.closest('[data-ui-tooltip]');
    if (control?.matches(':focus-visible')) show(control);
  });
  document.addEventListener('focusout', event => {
    if (event.target === active) hide();
  });
  document.addEventListener('pointerdown', hide);
  document.addEventListener('click', hide);
  document.addEventListener('keydown', event => { if (event.key === 'Escape') hide(); });
  document.addEventListener('scroll', hide, true);
  window.addEventListener('resize', hide);
  document.addEventListener('htmx:beforeSwap', hide);
})();
