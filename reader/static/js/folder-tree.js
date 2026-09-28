(() => {
  const panel = document.getElementById('folder-tree-panel');
  if (!panel) return;
  const root = document.documentElement;
  const toggle = document.getElementById('show-tree-toggle');
  const scroll = document.getElementById('folder-tree-scroll');
  const desktop = window.matchMedia('(min-width: 1024px)');
  const branches = [...panel.querySelectorAll('[data-folder-toggle]')];
  const read = (key, fallback) => {
    try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch (_) { return fallback; }
  };
  const save = (key, value) => {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) {}
  };
  const stored = read('issued-tree-expanded', []);
  const expanded = new Set(Array.isArray(stored) ? stored.map(String) : []);
  JSON.parse(panel.dataset.ancestors).forEach(id => expanded.add(String(id)));
  const valid = new Set(branches.map(button => button.dataset.folderToggle));
  for (const id of expanded) if (!valid.has(id)) expanded.delete(id);
  let rememberedScroll = Number(read('issued-tree-scroll', 0)) || 0;
  const location = window.location.pathname;
  let revealSelection = read('issued-tree-scroll-location', null) !== location;
  const saveScroll = () => {
    save('issued-tree-scroll', rememberedScroll);
    save('issued-tree-scroll-location', location);
  };
  const setBranch = button => {
    const open = expanded.has(button.dataset.folderToggle);
    button.setAttribute('aria-expanded', String(open));
    document.getElementById(button.getAttribute('aria-controls')).hidden = !open;
  };
  branches.forEach(button => {
    setBranch(button);
    button.addEventListener('click', () => {
      const id = button.dataset.folderToggle;
      if (expanded.has(id)) expanded.delete(id); else expanded.add(id);
      setBranch(button);
      save('issued-tree-expanded', [...expanded]);
    });
  });
  save('issued-tree-expanded', [...expanded]);

  const restoreScroll = () => requestAnimationFrame(() => {
    if (!desktop.matches || root.dataset.showTree !== 'true') return;
    scroll.scrollTop = rememberedScroll;
    const current = scroll.querySelector('[aria-current="page"]');
    if (current && revealSelection && current.hasAttribute('data-tree-folder')) {
      const box = current.getBoundingClientRect();
      const viewport = scroll.getBoundingClientRect();
      if (box.top < viewport.top || box.bottom > viewport.bottom) {
        scroll.scrollTop += box.top - viewport.top - viewport.height / 2;
      }
    }
    if (panel.getClientRects().length) revealSelection = false;
  });
  const render = () => {
    toggle.setAttribute('aria-checked', root.dataset.showTree);
  };
  toggle.addEventListener('click', () => {
    const enabled = root.dataset.showTree !== 'true';
    root.dataset.showTree = String(enabled);
    save('issued-show-tree', enabled);
    render();
    if (enabled) restoreScroll();
  });
  scroll.addEventListener('scroll', () => {
    if (!desktop.matches || root.dataset.showTree !== 'true') return;
    rememberedScroll = scroll.scrollTop;
    saveScroll();
  }, { passive: true });
  panel.querySelectorAll('a').forEach(link => link.addEventListener('click', () => {
    rememberedScroll = scroll.scrollTop;
    saveScroll();
  }));
  desktop.addEventListener('change', () => {
    if (!desktop.matches && panel.contains(document.activeElement)) {
      document.getElementById('display-settings-toggle').focus();
    }
    restoreScroll();
  });
  window.addEventListener('pageshow', restoreScroll);
  render();
  restoreScroll();
})();
