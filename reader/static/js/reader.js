import {
  createReaderInteractions,
  MOBILE_READER_MEDIA_QUERY,
} from './reader-interactions.js';

/**
 * Issued web reader – page navigation, fullscreen, progress tracking, spread view
 */
(() => {
  const reader = document.querySelector('.reader');
  if (!reader) return;

  // --- DOM refs ---
  const $ = (sel) => document.querySelector(sel);
  const img = $('#reader-image');
  const imgRight = $('#reader-image-right');
  const pagesEl = $('#reader-pages');
  const spinner = $('#reader-spinner');
  const pageNumEl = $('#reader-page-num');
  const progressBar = $('#reader-progress');
  const prevBtn = $('#reader-prev');
  const nextBtn = $('#reader-next');
  const fsBtn = $('#fullscreen-toggle');
  const fsIconEnter = $('#fullscreen-icon-enter');
  const fsIconExit = $('#fullscreen-icon-exit');
  const imageWrap = $('.reader-image-wrap');
  const progressWrap = $('#reader-progress-wrap');
  const pageInput = $('#reader-page-input');
  const btnSpread = $('#btn-spread');
  const iconSpreadOff = $('#icon-spread-off');
  const iconSpreadOn = $('#icon-spread-on');
  const btnCoverSep = $('#btn-cover-sep');
  const readerControls = $('.reader-controls');
  const actionsToggle = $('#reader-actions-toggle');
  const actionsPanel = $('#reader-actions-panel');
  const actionsBackdrop = $('#reader-actions-backdrop');
  const controlEls = ['.reader-controls', '.reader-navigation', '.reader-hints'].map($);
  const mobileReaderQuery = window.matchMedia(MOBILE_READER_MEDIA_QUERY);

  const comicUuid = reader.dataset.comicUuid;
  const pageCount = parseInt(reader.dataset.pageCount, 10) || 1;
  const initialPage = parseInt(reader.dataset.initialPage, 10) || 1;

  let currentPage = initialPage;
  let loading = false;
  let progressTimer = null;
  let hideTimer = null;
  let twoPageMode = false;
  let coverSeparate = true;
  let interactions = null;
  let mobileActionsOpen = false;

  // --- Helpers ---

  const setMobileActionsOpen = (open, { restoreFocus = false } = {}) => {
    const isMobile = mobileReaderQuery.matches;
    mobileActionsOpen = Boolean(open && isMobile);
    readerControls?.classList.toggle('mobile-actions-open', mobileActionsOpen);
    actionsToggle?.setAttribute('aria-expanded', String(mobileActionsOpen));

    if (actionsPanel) {
      if (isMobile) {
        actionsPanel.setAttribute('aria-hidden', String(!mobileActionsOpen));
        actionsPanel.inert = !mobileActionsOpen;
      } else {
        actionsPanel.removeAttribute('aria-hidden');
        actionsPanel.inert = false;
      }
    }

    if (restoreFocus && isMobile) actionsToggle?.focus();
  };

  const closeMobileActions = (restoreFocus = false) => {
    setMobileActionsOpen(false, { restoreFocus });
  };

  const syncMobileActionsLayout = () => closeMobileActions();

  const pageUrl = (p) =>
    `/reader/api/comic/${encodeURIComponent(comicUuid)}/page/${p}`;

  const setSpinner = (on) => spinner?.classList.toggle('visible', on);

  const setControlsVisible = (visible) => {
    controlEls.forEach(el => el?.classList.toggle('hidden', !visible));
    reader.classList.toggle('cursor-hidden', !visible);
  };

  // --- Spread helpers ---

  const getRightPage = (page) => {
    if (!twoPageMode) return null;
    if (coverSeparate && page === 1) return null;
    if (page >= pageCount) return null;
    return page + 1;
  };

  const getNextPage = () => {
    if (!twoPageMode) return currentPage + 1;
    if (coverSeparate && currentPage === 1) return 2;
    return currentPage + 2;
  };

  const getPrevPage = () => {
    if (!twoPageMode) return currentPage - 1;
    if (coverSeparate && currentPage === 2) return 1;
    return currentPage - 2;
  };

  // Snap to nearest valid left-page for the current spread mode
  const snapPage = (page) => {
    if (!twoPageMode) return page;
    if (coverSeparate) {
      if (page === 1) return 1;
      return page % 2 === 0 ? page : page - 1;
    } else {
      return page % 2 === 1 ? page : page - 1;
    }
  };

  const updateBtnStates = () => {
    iconSpreadOff.classList.toggle('hidden', twoPageMode);
    iconSpreadOn.classList.toggle('hidden', !twoPageMode);
    btnCoverSep.disabled = !twoPageMode;
    btnCoverSep.classList.toggle('btn-view-active', twoPageMode && coverSeparate);
  };

  // --- Page navigation ---

  const updatePage = (page) => {
    if (page < 1 || page > pageCount || loading) return;
    interactions?.resetZoom({ animate: false });
    loading = true;
    currentPage = page;

    setSpinner(true);
    img.style.opacity = '0.5';
    if (imgRight) imgRight.style.opacity = '0.5';

    const rightPage = getRightPage(page);
    let leftLoaded = false;
    let rightLoaded = !rightPage;

    const done = () => {
      if (!leftLoaded || !rightLoaded) return;
      img.style.opacity = '1';
      if (imgRight) imgRight.style.opacity = '1';
      setSpinner(false);
      loading = false;
      if (pagesEl) pagesEl.classList.toggle('spread-mode', !!rightPage);
    };

    // Load left page
    const preloadL = new Image();
    preloadL.onload = () => { img.src = pageUrl(page); img.alt = `Page ${page}`; leftLoaded = true; done(); };
    preloadL.onerror = () => { leftLoaded = true; done(); };
    preloadL.src = pageUrl(page);

    // Load right page
    if (rightPage && imgRight) {
      imgRight.classList.remove('hidden');
      const preloadR = new Image();
      preloadR.onload = () => {
        imgRight.src = pageUrl(rightPage);
        imgRight.alt = `Page ${rightPage}`;
        rightLoaded = true;
        done();
      };
      preloadR.onerror = () => { rightLoaded = true; done(); };
      preloadR.src = pageUrl(rightPage);
    } else if (imgRight) {
      imgRight.classList.add('hidden');
    }

    // Update UI
    pageNumEl.textContent = rightPage ? `${page}–${rightPage}` : `${page}`;
    progressBar.style.width = `${(page / pageCount) * 100}%`;
    prevBtn.disabled = getPrevPage() < 1;
    nextBtn.disabled = getNextPage() > pageCount;

    saveProgress(page, rightPage);
  };

  const navigate = (delta) => updatePage(delta > 0 ? getNextPage() : getPrevPage());

  // --- Progress save (debounced) ---

  const saveProgress = (page, rightPage) => {
    const lastVisible = rightPage ?? page;
    clearTimeout(progressTimer);
    progressTimer = setTimeout(() => {
      fetch(`/reader/api/comic/${encodeURIComponent(comicUuid)}/progress`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_page: lastVisible, is_completed: lastVisible >= pageCount }),
      }).catch(() => { });
    }, 500);
  };

  // --- Progress bar scrubbing ---

  const pageFromBarEvent = (e) => {
    const rect = progressWrap.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    return snapPage(Math.max(1, Math.min(pageCount, Math.round(ratio * (pageCount - 1)) + 1)));
  };

  let barDragging = false;

  progressWrap.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    barDragging = true;
    progressWrap.setPointerCapture(e.pointerId);
    updatePage(pageFromBarEvent(e));
  });

  progressWrap.addEventListener('pointermove', (e) => {
    if (!barDragging) return;
    updatePage(pageFromBarEvent(e));
  });

  progressWrap.addEventListener('pointerup', () => { barDragging = false; });
  progressWrap.addEventListener('pointercancel', () => { barDragging = false; });

  // --- Inline page-number jump ---

  const openPageInput = () => {
    pageNumEl.classList.add('hidden');
    pageInput.classList.remove('hidden');
    pageInput.value = currentPage;
    pageInput.select();
  };

  const commitPageInput = () => {
    const val = parseInt(pageInput.value, 10);
    pageInput.classList.add('hidden');
    pageNumEl.classList.remove('hidden');
    if (!isNaN(val) && val >= 1 && val <= pageCount) {
      updatePage(snapPage(val));
    }
  };

  const cancelPageInput = () => {
    pageInput.classList.add('hidden');
    pageNumEl.classList.remove('hidden');
  };

  pageNumEl.addEventListener('click', openPageInput);

  pageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); commitPageInput(); }
    if (e.key === 'Escape') { e.preventDefault(); cancelPageInput(); }
    e.stopPropagation();
  });

  pageInput.addEventListener('blur', commitPageInput);

  // --- Spread / cover-sep toggles ---

  const toggleSpread = () => {
    interactions?.resetZoom({ animate: false });
    twoPageMode = !twoPageMode;
    updateBtnStates();
    updatePage(snapPage(currentPage));
    closeMobileActions(true);
  };

  const toggleCoverSep = () => {
    interactions?.resetZoom({ animate: false });
    coverSeparate = !coverSeparate;
    updateBtnStates();
    updatePage(snapPage(currentPage));
    closeMobileActions(true);
  };

  // --- Pointer navigation, double-tap zoom, and pan ---

  interactions = createReaderInteractions({
    viewport: imageWrap,
    content: pagesEl,
    onPrevious: () => navigate(-1),
    onNext: () => navigate(1),
    isDisabled: () => loading,
  });

  // --- Fullscreen ---

  const toggleFullscreen = () => {
    interactions?.resetZoom({ animate: false });
    closeMobileActions();
    if (!document.fullscreenElement) {
      reader.requestFullscreen().catch(() => { });
    } else {
      document.exitFullscreen();
    }
  };

  const showControls = () => {
    if (!document.fullscreenElement) return;
    setControlsVisible(true);
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      if (document.fullscreenElement) setControlsVisible(false);
    }, 3000);
  };

  fsBtn.addEventListener('click', toggleFullscreen);
  actionsToggle?.addEventListener('click', (event) => {
    const opening = !mobileActionsOpen;
    setMobileActionsOpen(opening);
    if (opening && event.detail === 0) {
      actionsPanel?.querySelector('input, button:not(:disabled), a[href]')?.focus();
    }
  });
  actionsBackdrop?.addEventListener('click', () => closeMobileActions(true));
  mobileReaderQuery.addEventListener('change', syncMobileActionsLayout);

  document.addEventListener('fullscreenchange', () => {
    interactions?.resetZoom({ animate: false });
    closeMobileActions();
    fsIconEnter.classList.toggle('hidden', !!document.fullscreenElement);
    fsIconExit.classList.toggle('hidden', !document.fullscreenElement);
    if (document.fullscreenElement) {
      showControls();
    } else {
      setControlsVisible(true);
      clearTimeout(hideTimer);
    }
  });

  reader.addEventListener('mousemove', showControls);

  // --- Button events ---

  prevBtn.addEventListener('click', () => { navigate(-1); showControls(); });
  nextBtn.addEventListener('click', () => { navigate(1); showControls(); });
  btnSpread.addEventListener('click', () => { toggleSpread(); showControls(); });
  btnCoverSep.addEventListener('click', () => { toggleCoverSep(); showControls(); });

  // --- Keyboard ---

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && mobileActionsOpen) {
      e.preventDefault();
      closeMobileActions(true);
      return;
    }

    const target = e.target;
    if (target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) {
      return;
    }
    const actions = {
      ArrowLeft: () => navigate(-1),
      ArrowRight: () => navigate(1),
      f: toggleFullscreen,
      F: toggleFullscreen,
      z: () => interactions?.toggleZoomAtCenter(),
      Z: () => interactions?.toggleZoomAtCenter(),
    };
    if (actions[e.key]) { e.preventDefault(); actions[e.key](); }
  });

  // --- Init ---

  syncMobileActionsLayout();
  updateBtnStates();

  if (img && spinner) {
    setSpinner(true);
    img.addEventListener('load', () => setSpinner(false), { once: true });
    setTimeout(() => setSpinner(false), 3000);
  }

  updatePage(initialPage);
  window.addEventListener('pagehide', () => {
    interactions?.destroy();
    mobileReaderQuery.removeEventListener('change', syncMobileActionsLayout);
  }, { once: true });
})();
