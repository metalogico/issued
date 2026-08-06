(() => {
  const widthStorageKey = 'issued-layout-width';
  const sizeStorageKey = 'issued-thumbnail-size';
  const validWidths = ['fixed', 'full'];
  const validSizes = ['small', 'medium', 'large'];
  const root = document.documentElement;
  const toggle = document.getElementById('display-settings-toggle');
  const panel = document.getElementById('display-settings-panel');
  const sizeLabel = document.getElementById('thumbnail-size-label');
  const decreaseButton = document.getElementById('thumbnail-size-decrease');
  const increaseButton = document.getElementById('thumbnail-size-increase');

  const persist = (key, value) => {
    try {
      localStorage.setItem(key, value);
    } catch (_) {}
  };

  const applyWidth = (width, shouldPersist = false) => {
    const normalizedWidth = validWidths.includes(width) ? width : 'fixed';
    root.dataset.layoutWidth = normalizedWidth;
    document.querySelectorAll('[data-layout-width]').forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.layoutWidth === normalizedWidth));
    });
    if (shouldPersist) persist(widthStorageKey, normalizedWidth);
  };

  const applySize = (size, shouldPersist = false) => {
    const normalizedSize = validSizes.includes(size) ? size : 'medium';
    const sizeIndex = validSizes.indexOf(normalizedSize);
    root.dataset.thumbnailSize = normalizedSize;
    if (sizeLabel) sizeLabel.textContent = normalizedSize[0].toUpperCase() + normalizedSize.slice(1);
    if (decreaseButton) decreaseButton.disabled = sizeIndex === 0;
    if (increaseButton) increaseButton.disabled = sizeIndex === validSizes.length - 1;
    if (shouldPersist) persist(sizeStorageKey, normalizedSize);
  };

  applyWidth(root.dataset.layoutWidth);
  applySize(root.dataset.thumbnailSize);

  if (!toggle || !panel) return;

  const closePanel = () => {
    panel.classList.add('hidden');
    toggle.setAttribute('aria-expanded', 'false');
  };

  toggle.addEventListener('click', () => {
    const shouldOpen = panel.classList.contains('hidden');
    panel.classList.toggle('hidden', !shouldOpen);
    toggle.setAttribute('aria-expanded', String(shouldOpen));
  });

  document.querySelectorAll('[data-layout-width]').forEach((button) => {
    button.addEventListener('click', () => applyWidth(button.dataset.layoutWidth, true));
  });

  decreaseButton?.addEventListener('click', () => {
    const currentIndex = validSizes.indexOf(root.dataset.thumbnailSize);
    applySize(validSizes[Math.max(0, currentIndex - 1)], true);
  });

  increaseButton?.addEventListener('click', () => {
    const currentIndex = validSizes.indexOf(root.dataset.thumbnailSize);
    applySize(validSizes[Math.min(validSizes.length - 1, currentIndex + 1)], true);
  });

  document.addEventListener('click', (event) => {
    if (!panel.contains(event.target) && !toggle.contains(event.target)) closePanel();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      closePanel();
      toggle.focus();
    }
  });
})();
