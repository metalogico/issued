(() => {
  const widthStorageKey = 'issued-layout-width';
  const sizeStorageKey = 'issued-thumbnail-size';
  const borderlessStorageKey = 'issued-borderless-collage';
  const hideFileTypesStorageKey = 'issued-hide-file-types';
  const sortStorageKey = 'issued-sort-order';
  const validWidths = ['fixed', 'full'];
  const validSorts = ['az', 'za', 'newest', 'oldest'];
  const validSizes = ['tiny', 'extra-small', 'small', 'medium', 'large', 'extra-large', 'huge'];
  const sizeLabels = {
    tiny: 'Tiny',
    'extra-small': 'Extra small',
    small: 'Small',
    medium: 'Medium',
    large: 'Large',
    'extra-large': 'Extra large',
    huge: 'Huge',
  };
  const root = document.documentElement;
  const toggle = document.getElementById('display-settings-toggle');
  const panel = document.getElementById('display-settings-panel');
  const sizeLabel = document.getElementById('thumbnail-size-label');
  const decreaseButton = document.getElementById('thumbnail-size-decrease');
  const increaseButton = document.getElementById('thumbnail-size-increase');
  const borderlessToggle = document.getElementById('borderless-collage-toggle');
  const hideFileTypesToggle = document.getElementById('hide-file-types-toggle');

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
    if (sizeLabel) sizeLabel.textContent = sizeLabels[normalizedSize];
    if (decreaseButton) decreaseButton.disabled = sizeIndex === 0;
    if (increaseButton) increaseButton.disabled = sizeIndex === validSizes.length - 1;
    if (shouldPersist) persist(sizeStorageKey, normalizedSize);
  };

  const applyBorderless = (enabled, shouldPersist = false) => {
    const isEnabled = enabled === true || enabled === 'true';
    root.dataset.borderless = String(isEnabled);
    borderlessToggle?.setAttribute('aria-checked', String(isEnabled));
    if (shouldPersist) persist(borderlessStorageKey, String(isEnabled));
  };

  const applyHideFileTypes = (enabled, shouldPersist = false) => {
    const isEnabled = enabled === true || enabled === 'true';
    root.dataset.hideFileTypes = String(isEnabled);
    hideFileTypesToggle?.setAttribute('aria-checked', String(isEnabled));
    if (shouldPersist) persist(hideFileTypesStorageKey, String(isEnabled));
  };

  applyWidth(root.dataset.layoutWidth);
  applySize(root.dataset.thumbnailSize);
  applyBorderless(root.dataset.borderless);
  applyHideFileTypes(root.dataset.hideFileTypes);

  // --- Comic sorting (grid and table of the comics section only) ---

  const titleOf = (element) => element.dataset.title || '';
  const addedOf = (element) => element.dataset.added || '';
  const compareText = (a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
  const compareAdded = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  const sortComparators = {
    az: (a, b) => compareText(titleOf(a), titleOf(b)) || compareAdded(addedOf(a), addedOf(b)),
    za: (a, b) => compareText(titleOf(b), titleOf(a)) || compareAdded(addedOf(b), addedOf(a)),
    newest: (a, b) => compareAdded(addedOf(b), addedOf(a)) || compareText(titleOf(a), titleOf(b)),
    oldest: (a, b) => compareAdded(addedOf(a), addedOf(b)) || compareText(titleOf(a), titleOf(b)),
  };

  const sortChildren = (container, childSelector, compare) => {
    const children = Array.from(container.querySelectorAll(`:scope > ${childSelector}`));
    children.sort(compare).forEach((child) => container.appendChild(child));
  };

  const applySortToDom = (order) => {
    const compare = sortComparators[order];
    const section = document.getElementById('comics-section');
    if (!compare || !section || section.dataset.isSearch === 'true') return;
    section.querySelectorAll('.comics-grid-list').forEach((list) => sortChildren(list, 'li[data-title]', compare));
    section.querySelectorAll('.comics-table-list tbody').forEach((tbody) => sortChildren(tbody, 'tr[data-title]', compare));
  };

  const applySort = (order, shouldPersist = false) => {
    const normalizedOrder = validSorts.includes(order) ? order : 'az';
    root.dataset.sortOrder = normalizedOrder;
    document.querySelectorAll('[data-sort-order]').forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.sortOrder === normalizedOrder));
    });
    applySortToDom(normalizedOrder);
    if (shouldPersist) persist(sortStorageKey, normalizedOrder);
  };

  let savedSort = null;
  try {
    savedSort = localStorage.getItem(sortStorageKey);
  } catch (_) {}
  applySort(savedSort);

  document.querySelectorAll('[data-sort-order]').forEach((button) => {
    button.addEventListener('click', () => applySort(button.dataset.sortOrder, true));
  });

  // The comics section is replaced by htmx (e.g. "Complete all"): re-apply the order.
  document.addEventListener('htmx:afterSwap', () => applySort(root.dataset.sortOrder));

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

  borderlessToggle?.addEventListener('click', () => {
    applyBorderless(root.dataset.borderless !== 'true', true);
  });

  hideFileTypesToggle?.addEventListener('click', () => {
    applyHideFileTypes(root.dataset.hideFileTypes !== 'true', true);
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
