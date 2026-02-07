/**
 * Issued web reader – browser: comic info modal, htmx events, toasts
 */
(() => {
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
      form.setAttribute('hx-patch', `/reader/api/comic/${currentUuid}/metadata`);
    }
    META_FIELDS.forEach((name) => {
      const el = form.elements[name];
      if (el) el.value = data[name] ?? '';
    });
  };

  // --- htmx events ---

  document.body.addEventListener('htmx:afterRequest', (evt) => {
    const { target, successful, xhr, verb, failed } = evt.detail;

    if (target.id === 'comic-info-form' && successful && xhr?.status === 200 && verb !== 'patch') {
      try {
        populateForm(JSON.parse(xhr.responseText));
        setModalOpen(true);
      } catch {
        toast('error', 'Could not load comic info', 'The comic may have been moved or deleted.');
      }
    }

    if (target.id === 'comic-info-form' && successful && verb === 'patch') {
      setModalOpen(false);
      toast('success', 'Saved!', null, 2000);
    }

    if (failed && xhr) {
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
