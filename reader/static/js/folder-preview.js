/**
 * Issued web reader – folder thumbnail preview loader (2x2 mosaic)
 */
(() => {
  document.querySelectorAll('[data-folder-id]').forEach((card) => {
    const folderId = card.dataset.folderId;
    if (!folderId) return;

    const placeholder = card.querySelector('.folder-preview-placeholder');
    const container = card.querySelector('.folder-preview-images');
    const thumbs = [1, 2, 3, 4].map(n => card.querySelector(`.folder-thumb-${n}`));

    const thumbUrl = (uuid) => `/opds/comic/${uuid}/thumbnail`;

    const reveal = () => {
      const hasAny = thumbs.some(t => t?.style.backgroundImage);
      if (hasAny) {
        placeholder?.classList.add('hidden');
        container?.classList.remove('hidden');
      }
    };

    fetch(`/reader/api/folder/${folderId}/preview?limit=4`)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(({ uuids = [] }) => {
        if (!uuids.length) return;
        if (uuids.length === 1) container?.classList.add('folder-preview-single');

        let loaded = 0;
        const target = Math.min(uuids.length, 4);

        uuids.slice(0, 4).forEach((uuid, i) => {
          if (!thumbs[i]) return;
          const img = new Image();
          img.onload = () => {
            thumbs[i].style.backgroundImage = `url("${thumbUrl(uuid)}")`;
            if (++loaded === target) reveal();
          };
          img.onerror = () => { if (++loaded === target) reveal(); };
          img.src = thumbUrl(uuid);
        });
      })
      .catch(() => { });
  });
})();
