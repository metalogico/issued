/**
 * Issued web reader – browser: comic info modal, htmx events, toasts, view toggle
 */
(() => {
  const seriesMenu = document.querySelector('.series-more');
  document.addEventListener('click', (event) => {
    if (seriesMenu && !seriesMenu.contains(event.target)) seriesMenu.open = false;
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && seriesMenu?.open) {
      seriesMenu.open = false;
      seriesMenu.querySelector('summary').focus();
    }
  });
  document.addEventListener('htmx:beforeRequest', (event) => {
    if (event.detail.elt?.classList.contains('complete-all-btn') && seriesMenu) {
      seriesMenu.open = false;
    }
  });
  // --- View toggle (grid / table) ---

  const viewStorageKey = 'comics-view';
  const desktopView = window.matchMedia('(min-width: 1024px)');
  let preferredView = 'grid';
  try {
    preferredView = localStorage.getItem(viewStorageKey) === 'table' ? 'table' : 'grid';
  } catch (_) {}

  const applyView = () => {
    const section = document.getElementById('comics-section');
    if (!section) return;
    const table = desktopView.matches && preferredView === 'table';
    section.querySelectorAll('.comics-grid-list').forEach(el => el.classList.toggle('hidden', table));
    section.querySelectorAll('.comics-table-list').forEach(el => el.classList.toggle('hidden', !table));
    for (const [id, active] of [['view-grid-btn', !table], ['view-table-btn', table]]) {
      const button = document.getElementById(id);
      button?.setAttribute('aria-pressed', String(active));
    }
  };
  document.addEventListener('click', event => {
    const button = event.target.closest('#view-grid-btn, #view-table-btn');
    if (!button || !desktopView.matches) return;
    preferredView = button.id === 'view-table-btn' ? 'table' : 'grid';
    try { localStorage.setItem(viewStorageKey, preferredView); } catch (_) {}
    applyView();
  });
  desktopView.addEventListener('change', applyView);
  document.addEventListener('htmx:afterSwap', applyView);
  applyView();

  // --- Ongoing series (folder bookmark) ---

  const toastOngoing = (icon, title, text, timer = 3000) =>
    Swal.fire({ icon, title, text, toast: true, position: 'top-end', showConfirmButton: false, timer, timerProgressBar: true });

  const applyOngoingBtn = (btn, ongoing) => {
    btn.dataset.ongoing = ongoing ? 'true' : 'false';
    btn.setAttribute('aria-pressed', String(ongoing));
    btn.classList.toggle('bg-violet-100', ongoing);
    btn.querySelector('.ongoing-check')?.classList.toggle('hidden', !ongoing);
  };

  document.addEventListener('click', async (evt) => {
    const btn = evt.target.closest('.folder-ongoing-toggle');
    if (!btn) return;
    evt.preventDefault();
    if (btn.dataset.loading === 'true') return;
    const folderId = btn.dataset.folderId;
    if (!folderId) return;
    const next = btn.dataset.ongoing !== 'true';
    btn.dataset.loading = 'true';
    try {
      const res = await fetch(`/reader/api/folder/${folderId}/ongoing`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ongoing: next }),
      });
      if (!res.ok) {
        let msg = 'Could not update';
        try {
          const j = await res.json();
          if (j.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
        } catch { /* ignore */ }
        toastOngoing('error', msg, null, 4000);
        return;
      }
      const payload = await res.json();
      const ongoing = Boolean(payload?.ongoing);
      document.querySelectorAll('.folder-ongoing-toggle').forEach((b) => {
        if (b.dataset.folderId === folderId) applyOngoingBtn(b, ongoing);
      });
      toastOngoing('success', ongoing ? 'Added to Ongoing' : 'Removed from Ongoing', null, 2000);
    } catch {
      toastOngoing('error', 'Network error', 'Please try again.');
    } finally {
      btn.dataset.loading = 'false';
    }
  });

  // --- Manual library scan ---

  const scanBtn = document.getElementById('scan-library-btn');
  const scanToast = (icon, title, text, timer = 3000) =>
    Swal.fire({ icon, title, text, toast: true, position: 'top-end', showConfirmButton: false, timer, timerProgressBar: true });

  if (scanBtn) {
    scanBtn.addEventListener('click', async () => {
      if (scanBtn.dataset.loading === 'true') return;

      scanBtn.dataset.loading = 'true';
      scanBtn.disabled = true;
      scanBtn.classList.add('animate-pulse');

      try {
        const res = await fetch('/reader/api/library/scan', { method: 'POST' });
        if (!res.ok) {
          let detail = 'Please try again.';
          try {
            const payload = await res.json();
            if (payload?.detail && typeof payload.detail === 'string') {
              detail = payload.detail;
            }
          } catch { /* ignore JSON parse errors */ }
          throw new Error(detail);
        }

        const payload = await res.json();
        const stats = payload?.stats || {};
        scanToast(
          'success',
          'Scan completed',
          `Added ${stats.added || 0}, updated ${stats.updated || 0}, deleted ${stats.deleted || 0}.`,
          2200,
        );

        setTimeout(() => {
          window.location.reload();
        }, 500);
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Please try again.';
        scanToast('error', 'Scan failed', message, 4500);
      } finally {
        scanBtn.dataset.loading = 'false';
        scanBtn.disabled = false;
        scanBtn.classList.remove('animate-pulse');
      }
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
    if (typeof window._tagsLoadForComic === 'function') {
      window._tagsLoadForComic(currentUuid, data.tags || []);
    }
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
