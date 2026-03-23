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

  // --- Complete all comics ---

  document.addEventListener('htmx:afterSwap', (evt) => {
    const triggerEl = evt.detail?.requestConfig?.elt;
    const swapTarget = evt.detail?.target;
    if (!triggerEl?.classList?.contains('complete-all-btn')) return;
    if (swapTarget?.id !== 'comics-section') return;

    if (window.lucide) {
      window.lucide.createIcons();
    }

    toast('success', 'All comics marked as completed!', null, 3000);
  });

  const applyCompletedState = (btn, isCompleted) => {
    btn.dataset.isCompleted = isCompleted ? 'true' : 'false';
    btn.title = isCompleted ? 'Mark as not completed' : 'Mark as completed';
    btn.setAttribute('aria-label', btn.title);

    btn.innerHTML = '<i data-lucide="check" class="h-4 w-4"></i>';

    if (btn.classList.contains('comic-completed-toggle-grid')) {
      btn.className = `comic-completed-toggle comic-completed-toggle-grid absolute left-2 top-2 z-20 flex h-7 w-7 items-center justify-center rounded-full shadow-md transition ${isCompleted
        ? 'bg-violet-600 text-white opacity-100'
        : 'bg-gray-100 text-gray-400 opacity-0 group-hover:opacity-100 hover:bg-violet-100 hover:text-violet-700'
        }`;
      return;
    }

    btn.className = `comic-completed-toggle comic-completed-toggle-table mx-auto inline-flex h-7 w-7 items-center justify-center rounded-full transition ${isCompleted
      ? 'bg-violet-600 text-white'
      : 'bg-gray-100 text-gray-400 hover:bg-violet-100 hover:text-violet-700'
      }`;
    if (window.lucide) {
      window.lucide.createIcons();
    }
  };

  document.addEventListener('click', async (evt) => {
    const toggleBtn = evt.target.closest('.comic-completed-toggle');
    if (!toggleBtn) return;

    evt.preventDefault();
    evt.stopPropagation();

    if (toggleBtn.dataset.loading === 'true') return;
    const comicUuid = toggleBtn.dataset.comicUuid;
    if (!comicUuid) return;

    toggleBtn.dataset.loading = 'true';

    try {
      let isCompleted;
      const res = await fetch(`/reader/api/comic/${comicUuid}/completed/toggle`, {
        method: 'POST',
      });

      if (res.status === 404) {
        const progressRes = await fetch(`/reader/api/comic/${comicUuid}/progress`);
        if (!progressRes.ok) throw new Error(progressRes.status);
        const progressPayload = await progressRes.json();
        const nextCompleted = !Boolean(progressPayload?.is_completed);
        const nextPage = Number(progressPayload?.current_page) || 1;

        const patchRes = await fetch(`/reader/api/comic/${comicUuid}/progress`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ current_page: nextPage, is_completed: nextCompleted }),
        });
        if (!patchRes.ok) throw new Error(patchRes.status);
        isCompleted = nextCompleted;
      } else {
        if (!res.ok) throw new Error(res.status);
        const payload = await res.json();
        isCompleted = Boolean(payload?.is_completed);
      }

      document.querySelectorAll('.comic-completed-toggle').forEach((btn) => {
        if (btn.dataset.comicUuid === comicUuid) {
          applyCompletedState(btn, isCompleted);
        }
      });

      if (window.lucide) {
        window.lucide.createIcons();
      }
    } catch {
      toast('error', 'An error occurred', 'Please try again.');
    } finally {
      toggleBtn.dataset.loading = 'false';
    }
  });

  // --- Modal close ---

  const close = () => setModalOpen(false);
  document.getElementById('comic-info-close')?.addEventListener('click', close);
  document.getElementById('comic-info-cancel')?.addEventListener('click', close);
  modal.addEventListener('click', (e) => { if (e.target === modal) close(); });
})();
