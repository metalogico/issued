const FIT_MODES = ['width', 'height'];

export function calculatePageSizing(viewportWidth, viewportHeight, pages, mode = 'height', gap = 0) {
  if (
    !Number.isFinite(viewportWidth) || viewportWidth <= 0
    || !Number.isFinite(viewportHeight) || viewportHeight <= 0
    || !pages.length
    || pages.some(page => !Number.isFinite(page.width) || page.width <= 0
      || !Number.isFinite(page.height) || page.height <= 0)
  ) return [];

  const ratios = pages.map(page => page.width / page.height);
  const availableWidth = Math.max(0, viewportWidth - Math.max(0, gap) * (pages.length - 1));
  const widthHeight = availableWidth / ratios.reduce((sum, ratio) => sum + ratio, 0);
  const height = mode === 'width' ? widthHeight : viewportHeight;

  return ratios.map(ratio => ({ width: height * ratio, height }));
}

export function createReaderSizing({ reader, viewport, content, images, buttons, interactions }) {
  let mode = 'height';
  let frame = null;
  let resetScroll = false;
  let fullscreen = false;
  const pixels = value => parseFloat(value) || 0;

  const updateButtons = () => {
    buttons.forEach(button => {
      const active = button.dataset.readerFit === mode;
      button.setAttribute('aria-pressed', String(active));
      button.classList.toggle('btn-view-active', active);
    });
  };

  const layout = () => {
    frame = null;
    const active = document.fullscreenElement === reader;
    const changed = active !== fullscreen;
    fullscreen = active;
    reader.classList.toggle('fullscreen-sizing', active);
    if (changed) interactions.setFullscreenSizing(active);

    if (!active) {
      images.forEach(image => {
        image.style.removeProperty('width');
        image.style.removeProperty('height');
      });
      viewport.scrollLeft = 0;
      viewport.scrollTop = 0;
      resetScroll = false;
      return;
    }
    // Hiding scrollbars during zoom can resize the scrollport. Keep the base
    // page dimensions stable until zoom resets or the window actually resizes.
    if (interactions.isZoomed()) return;

    const visible = images.filter(image => !image.classList.contains('hidden'));
    if (visible.some(image => !image.complete || !image.naturalWidth || !image.naturalHeight)) return;
    const style = window.getComputedStyle(viewport);
    const pages = visible.map(image => ({ width: image.naturalWidth, height: image.naturalHeight }));
    const gap = pixels(window.getComputedStyle(content).columnGap);
    const fullWidth = viewport.offsetWidth - pixels(style.borderLeftWidth) - pixels(style.borderRightWidth)
      - pixels(style.paddingLeft) - pixels(style.paddingRight);
    const fullHeight = viewport.offsetHeight - pixels(style.borderTopWidth) - pixels(style.borderBottomWidth)
      - pixels(style.paddingTop) - pixels(style.paddingBottom);
    const unconstrained = calculatePageSizing(fullWidth, fullHeight, pages, mode, gap);
    // Decide overflow without a scrollbar first, then keep that axis stable.
    // Otherwise a scrollbar near the fit threshold can repeatedly add/remove itself.
    const overflow = mode === 'width' && unconstrained[0]?.height > fullHeight + 0.5
      ? 'hidden scroll'
      : mode === 'height' && unconstrained.reduce((sum, size) => sum + size.width, 0)
        + gap * (visible.length - 1) > fullWidth + 0.5 ? 'scroll hidden' : 'hidden';
    interactions.setFullscreenOverflow(overflow);
    const width = viewport.clientWidth - pixels(style.paddingLeft) - pixels(style.paddingRight);
    const height = viewport.clientHeight - pixels(style.paddingTop) - pixels(style.paddingBottom);
    const sizes = calculatePageSizing(width, height, pages, mode, gap);
    const resized = visible.some((image, index) => sizes[index]
      && (Math.abs(pixels(image.style.width) - sizes[index].width) > 0.01
        || Math.abs(pixels(image.style.height) - sizes[index].height) > 0.01));
    if (resized) interactions.resetZoom({ animate: false });
    sizes.forEach((size, index) => {
      visible[index].style.width = `${size.width}px`;
      visible[index].style.height = `${size.height}px`;
    });
    if (resetScroll || changed) {
      viewport.scrollLeft = 0;
      viewport.scrollTop = 0;
    }
    resetScroll = false;
  };

  const refresh = ({ reset = false } = {}) => {
    resetScroll = resetScroll || reset;
    if (frame === null) frame = window.requestAnimationFrame(layout);
  };
  const imageLoaded = () => refresh();
  const fullscreenChanged = () => refresh({ reset: true });
  const resized = () => refresh();
  const select = event => {
    if (document.fullscreenElement !== reader) return;
    const nextMode = event.currentTarget.dataset.readerFit;
    if (!FIT_MODES.includes(nextMode)) return;
    mode = nextMode;
    interactions.resetZoom({ animate: false });
    updateButtons();
    refresh({ reset: true });
  };

  const observer = new ResizeObserver(resized);
  observer.observe(viewport);
  images.forEach(image => image.addEventListener('load', imageLoaded));
  buttons.forEach(button => button.addEventListener('click', select));
  document.addEventListener('fullscreenchange', fullscreenChanged);
  window.addEventListener('resize', resized);
  updateButtons();
  refresh();

  return {
    refresh,
    destroy() {
      observer.disconnect();
      if (frame !== null) window.cancelAnimationFrame(frame);
      images.forEach(image => image.removeEventListener('load', imageLoaded));
      buttons.forEach(button => button.removeEventListener('click', select));
      document.removeEventListener('fullscreenchange', fullscreenChanged);
      window.removeEventListener('resize', resized);
    },
  };
}
