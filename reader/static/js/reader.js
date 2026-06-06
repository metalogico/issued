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
  const btnSpread = $('#btn-spread');
  const iconSpreadOff = $('#icon-spread-off');
  const iconSpreadOn = $('#icon-spread-on');
  const btnCoverSep = $('#btn-cover-sep');
  const controlEls = ['.reader-controls', '.reader-navigation', '.reader-hints'].map($);

  const comicUuid = reader.dataset.comicUuid;
  const pageCount = parseInt(reader.dataset.pageCount, 10) || 1;
  const initialPage = parseInt(reader.dataset.initialPage, 10) || 1;

  let currentPage = initialPage;
  let loading = false;
  let progressTimer = null;
  let hideTimer = null;
  let lastTouchEnd = 0;
  let twoPageMode = false;
  let coverSeparate = true;

  // --- Helpers ---

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
      if (pagesEl) pagesEl.classList.remove('spread-mode');
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
        body: JSON.stringify({ current_page: page, is_completed: lastVisible >= pageCount }),
      }).catch(() => { });
    }, 500);
  };

  // --- Spread / cover-sep toggles ---

  const toggleSpread = () => {
    twoPageMode = !twoPageMode;
    updateBtnStates();
    updatePage(snapPage(currentPage));
  };

  const toggleCoverSep = () => {
    coverSeparate = !coverSeparate;
    updateBtnStates();
    updatePage(snapPage(currentPage));
  };

  // --- Tap navigation (mobile + desktop) ---

  const handleTap = (clientX) => {
    if (!imageWrap || loading) return;
    const rect = imageWrap.getBoundingClientRect();
    navigate((clientX - rect.left) < rect.width / 2 ? -1 : 1);
  };

  imageWrap?.addEventListener('click', (e) => {
    if (Date.now() - lastTouchEnd < 400) return;
    handleTap(e.clientX);
  });

  imageWrap?.addEventListener('touchend', (e) => {
    if (e.cancelable && e.changedTouches?.length) {
      e.preventDefault();
      lastTouchEnd = Date.now();
      handleTap(e.changedTouches[0].clientX);
    }
  }, { passive: false });

  // --- Fullscreen ---

  const toggleFullscreen = () => {
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

  document.addEventListener('fullscreenchange', () => {
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
  btnCoverSep.addEventListener('click', () => { if (!btnCoverSep.disabled) { toggleCoverSep(); showControls(); } });

  // --- Keyboard ---

  document.addEventListener('keydown', (e) => {
    const actions = {
      ArrowLeft: () => navigate(-1),
      ArrowRight: () => navigate(1),
      f: toggleFullscreen,
      F: toggleFullscreen,
    };
    if (actions[e.key]) { e.preventDefault(); actions[e.key](); }
  });

  // --- Init ---

  updateBtnStates();

  if (img && spinner) {
    setSpinner(true);
    img.addEventListener('load', () => setSpinner(false), { once: true });
    setTimeout(() => setSpinner(false), 3000);
  }

  updatePage(initialPage);
})();
