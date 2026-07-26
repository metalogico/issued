(() => {
  const storageKey = 'issued-theme';
  const root = document.documentElement;
  const toggle = document.getElementById('theme-toggle');
  const themeColor = document.querySelector('meta[name="theme-color"]');
  const colorScheme = window.matchMedia('(prefers-color-scheme: dark)');

  if (!toggle) return;

  const applyTheme = (theme, persist = false) => {
    const isDark = theme === 'dark';
    root.dataset.theme = isDark ? 'dark' : 'light';
    toggle.setAttribute('aria-pressed', String(isDark));
    toggle.setAttribute('aria-label', `Switch to ${isDark ? 'light' : 'dark'} mode`);
    toggle.title = toggle.getAttribute('aria-label');
    themeColor?.setAttribute('content', isDark ? '#111827' : '#7c3aed');

    if (persist) {
      try {
        localStorage.setItem(storageKey, root.dataset.theme);
      } catch (_) {
        // The selected theme still applies when storage is unavailable.
      }
    }
  };

  applyTheme(root.dataset.theme === 'dark' ? 'dark' : 'light');

  toggle.addEventListener('click', () => {
    applyTheme(root.dataset.theme === 'dark' ? 'light' : 'dark', true);
  });

  colorScheme.addEventListener('change', (event) => {
    try {
      if (localStorage.getItem(storageKey)) return;
    } catch (_) {
      // Follow the system setting when storage is unavailable.
    }
    applyTheme(event.matches ? 'dark' : 'light');
  });
})();
