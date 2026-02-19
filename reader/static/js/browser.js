/**
 * Issued web reader – browser: comic info modal, htmx events, toasts, view toggle
 */
(() => {
  // --- View toggle (grid / table) ---

  const comicsSection = document.getElementById('comics-section');
  const gridBtn = document.getElementById('view-grid-btn');
  const tableBtn = document.getElementById('view-table-btn');

  if (comicsSection && gridBtn && tableBtn) {
    const isSearch = comicsSection.dataset.isSearch === 'true';
    const STORAGE_KEY = 'comics-view';

    const applyView = (view) => {
      const gridLists = comicsSection.querySelectorAll('.comics-grid-list');
      const tableLists = comicsSection.querySelectorAll('.comics-table-list');
      if (view === 'table') {
        gridLists.forEach(el => el.classList.add('hidden'));
        tableLists.forEach(el => el.classList.remove('hidden'));
        tableBtn.classList.add('bg-violet-100', 'text-violet-700');
        gridBtn.classList.remove('bg-violet-100', 'text-violet-700');
      } else {
        tableLists.forEach(el => el.classList.add('hidden'));
        gridLists.forEach(el => el.classList.remove('hidden'));
        gridBtn.classList.add('bg-violet-100', 'text-violet-700');
        tableBtn.classList.remove('bg-violet-100', 'text-violet-700');
      }
    };

    const savedView = localStorage.getItem(STORAGE_KEY);
    applyView(savedView || 'grid');

    gridBtn.addEventListener('click', () => {
      localStorage.setItem(STORAGE_KEY, 'grid');
      applyView('grid');
    });
    tableBtn.addEventListener('click', () => {
      localStorage.setItem(STORAGE_KEY, 'table');
      applyView('table');
    });
  }

  // --- Comic info modal ---

  const modal = document.getElementById('comic-info-modal');
  const form = document.getElementById('comic-info-form');
  const filenameEl = document.getElementById('comic-info-filename');

  if (!modal || !form) return;

  let currentUuid = null;

  const META_FIELDS = [
    'title', 'series', 'issue_number', 'publisher', 'year', 'month',
    'writer', 'penciller', 'artist', 'summary', 'score', 'genre',
    'notes', 'web', 'language_iso',
  ];

  // --- Helpers ---

  const toast = (icon, title, text, timer = 3000) =>
    Swal.fire({ icon, title, text, toast: true, position: 'top-end', showConfirmButton: false, timer, timerProgressBar: true });

  const setModalOpen = (open) => {
    modal.classList.toggle('hidden', !open);
    modal.classList.toggle('flex', open);
    modal.setAttribute('aria-hidden', String(!open));
    if (!open) currentUuid = null;
  };

  // --- Form population ---

  const populateForm = (data) => {
    filenameEl.textContent = data.filename || '';
    currentUuid = data.uuid || null;
    if (currentUuid) {
      form.dataset.uuid = currentUuid;
    }
    META_FIELDS.forEach((name) => {
      const el = form.elements[name];
      if (el) el.value = data[name] ?? '';
    });
  };

  // --- htmx events (GET metadata load) ---

  document.body.addEventListener('htmx:afterRequest', (evt) => {
    const { target, successful, xhr } = evt.detail;

    if (target?.id === 'comic-info-form' && successful && xhr?.status === 200) {
      try {
        populateForm(JSON.parse(xhr.responseText));
        setModalOpen(true);
      } catch {
        toast('error', 'Could not load comic info', 'The comic may have been moved or deleted.');
      }
    }
  });

  // --- Form submit → JSON PATCH ---

  form.addEventListener('submit', async (evt) => {
    evt.preventDefault();
    const uuid = form.dataset.uuid;
    if (!uuid) return;
    const data = {};
    META_FIELDS.forEach((name) => {
      const el = form.elements[name];
      if (!el) return;
      const val = el.value.trim();
      data[name] = val === '' ? null : val;
    });
    try {
      const res = await fetch(`/reader/api/comic/${uuid}/metadata`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error(res.status);
      setModalOpen(false);
      toast('success', 'Saved!', null, 2000);
    } catch {
      toast('error', 'An error occurred', 'Please try again.');
    }
  });

  // --- Continue reading counter ---

  document.addEventListener('htmx:afterRequest', (evt) => {
    if (!evt.detail.elt?.classList?.contains('continue-reading-remove')) return;
    setTimeout(() => {
      const countEl = document.getElementById('continue-reading-count');
      if (!countEl) return;
      const remaining = document.querySelectorAll('.continue-reading-item').length;
      countEl.textContent = remaining;
      if (remaining === 0) countEl.closest('details')?.remove();
    }, 350);
  });

  // --- Modal close ---

  const close = () => setModalOpen(false);
  document.getElementById('comic-info-close')?.addEventListener('click', close);
  document.getElementById('comic-info-cancel')?.addEventListener('click', close);
  modal.addEventListener('click', (e) => { if (e.target === modal) close(); });
})();
