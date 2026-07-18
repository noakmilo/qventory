document.addEventListener('DOMContentLoaded', () => {
  const tableWraps = document.querySelectorAll(
    '.inventory-table-wrap, .fulfillment-table-wrap'
  );

  tableWraps.forEach((tableWrap) => {
    const floatingScroll = document.createElement('div');
    const floatingScrollContent = document.createElement('div');

    floatingScroll.className = 'floating-table-scroll';
    floatingScroll.setAttribute('role', 'region');
    floatingScroll.setAttribute('aria-label', 'Horizontal table scroll');
    floatingScroll.tabIndex = 0;
    floatingScrollContent.className = 'floating-table-scroll__content';
    floatingScroll.appendChild(floatingScrollContent);
    // Keep the fixed scrollbar outside cards/backdrop-filter containers, which can
    // otherwise make `position: fixed` relative to the card instead of the viewport.
    document.body.appendChild(floatingScroll);

    let syncing = false;

    const syncWidthsAndVisibility = () => {
      const tableRect = tableWrap.getBoundingClientRect();
      const hasHorizontalOverflow = tableWrap.scrollWidth > tableWrap.clientWidth + 1;
      const tableIsVisible = tableRect.top < window.innerHeight && tableRect.bottom > 0;

      floatingScrollContent.style.width = `${tableWrap.scrollWidth}px`;
      floatingScroll.style.left = `${Math.max(0, tableRect.left)}px`;
      floatingScroll.style.width = `${Math.min(tableRect.width, window.innerWidth - Math.max(0, tableRect.left))}px`;
      floatingScroll.classList.toggle(
        'is-visible',
        hasHorizontalOverflow && tableIsVisible
      );
    };

    tableWrap.addEventListener('scroll', () => {
      if (syncing) return;
      syncing = true;
      floatingScroll.scrollLeft = tableWrap.scrollLeft;
      syncing = false;
    }, { passive: true });

    floatingScroll.addEventListener('scroll', () => {
      if (syncing) return;
      syncing = true;
      tableWrap.scrollLeft = floatingScroll.scrollLeft;
      syncing = false;
    }, { passive: true });

    window.addEventListener('scroll', syncWidthsAndVisibility, { passive: true });
    window.addEventListener('resize', syncWidthsAndVisibility, { passive: true });

    if ('ResizeObserver' in window) {
      new ResizeObserver(syncWidthsAndVisibility).observe(tableWrap);
    }

    syncWidthsAndVisibility();
  });
});
