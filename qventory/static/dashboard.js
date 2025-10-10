/**
 * Qventory Dashboard JavaScript
 * Handles infinite scroll, bulk actions, QR scanning, and image modals
 */

// ==================== INFINITE SCROLL ====================

let isLoading = false;
let hasMore = true;
let currentOffset = 20; // Initial load is 20 items

const loadingSpinner = document.getElementById('loadingSpinner');
const scrollSentinel = document.getElementById('scrollSentinel');
const itemsTableBody = document.getElementById('itemsTableBody');

// Intersection Observer for infinite scroll
const observerOptions = {
  root: null,
  rootMargin: '200px', // Trigger 200px before reaching the sentinel
  threshold: 0.1
};

const observer = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting && !isLoading && hasMore) {
      loadMoreItems();
    }
  });
}, observerOptions);

// Start observing the sentinel
if (scrollSentinel) {
  observer.observe(scrollSentinel);
}

async function loadMoreItems() {
  if (isLoading || !hasMore) return;

  isLoading = true;
  if (loadingSpinner) loadingSpinner.style.display = 'block';

  try {
    // Get current URL params (filters)
    const params = new URLSearchParams(window.location.search);
    params.set('offset', currentOffset);
    params.set('limit', 20);

    // Add view_type if on inventory pages
    if (window.QVENTORY_VIEW_TYPE) {
      params.set('view_type', window.QVENTORY_VIEW_TYPE);
    }

    const response = await fetch(`/api/load-more-items?${params.toString()}`);
    const data = await response.json();

    if (data.ok && data.items && data.items.length > 0) {
      // Append new items to table
      data.items.forEach(itemHtml => {
        const row = document.createElement('tr');
        row.innerHTML = itemHtml;
        itemsTableBody.appendChild(row.firstElementChild || row);
      });

      currentOffset += data.items.length;
      hasMore = data.has_more;

      // Re-initialize event listeners for new items
      initializeItemEventListeners();
    } else {
      hasMore = false;
    }
  } catch (error) {
    console.error('Error loading more items:', error);
    hasMore = false;
  } finally {
    isLoading = false;
    if (loadingSpinner) loadingSpinner.style.display = 'none';
  }
}

// ==================== BULK ACTIONS ====================

const selectAllCheckbox = document.getElementById('selectAllCheckbox');
const bulkActionsContainer = document.getElementById('bulkActionsContainer');
const bulkActionSelect = document.getElementById('bulkActionSelect');
const bulkActionApply = document.getElementById('bulkActionApply');
const bulkSelectedCount = document.getElementById('bulkSelectedCount');

// Select all checkbox
if (selectAllCheckbox) {
  selectAllCheckbox.addEventListener('change', (e) => {
    const checkboxes = document.querySelectorAll('.item-checkbox');
    checkboxes.forEach(cb => {
      cb.checked = e.target.checked;
    });
    updateBulkActions();
  });
}

// Update bulk actions visibility and count
function updateBulkActions() {
  const selectedCheckboxes = document.querySelectorAll('.item-checkbox:checked');
  const count = selectedCheckboxes.length;

  if (count > 0) {
    bulkActionsContainer.style.display = 'block';
    bulkSelectedCount.textContent = `${count} item(s) selected`;
  } else {
    bulkActionsContainer.style.display = 'none';
    bulkSelectedCount.textContent = '';
  }
}

// Apply bulk action
if (bulkActionApply) {
  bulkActionApply.addEventListener('click', async () => {
    const action = bulkActionSelect.value;
    if (!action) {
      alert('Please select an action');
      return;
    }

    const selectedCheckboxes = document.querySelectorAll('.item-checkbox:checked');
    const itemIds = Array.from(selectedCheckboxes).map(cb => parseInt(cb.dataset.itemId));

    if (itemIds.length === 0) {
      alert('No items selected');
      return;
    }

    if (action === 'delete') {
      if (!confirm(`Are you sure you want to delete ${itemIds.length} item(s)?`)) {
        return;
      }

      try {
        const response = await fetch('/items/bulk_delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ item_ids: itemIds })
        });

        const data = await response.json();
        if (data.ok) {
          alert(data.message);
          location.reload();
        } else {
          alert('Error: ' + data.error);
        }
      } catch (error) {
        console.error('Bulk delete error:', error);
        alert('Failed to delete items');
      }
    } else if (action === 'sync_to_ebay') {
      if (!confirm(`Sync ${itemIds.length} item(s) to eBay?`)) {
        return;
      }

      try {
        const response = await fetch('/items/bulk_sync_to_ebay', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ item_ids: itemIds })
        });

        const data = await response.json();
        if (data.ok) {
          alert(data.message);
          location.reload();
        } else {
          alert('Error: ' + data.error);
        }
      } catch (error) {
        console.error('Bulk sync error:', error);
        alert('Failed to sync items');
      }
    }
  });
}

// ==================== QR MODAL ====================

const qrModal = document.getElementById('qrModal');
const qrImage = document.getElementById('qrImage');
const qrCaption = document.getElementById('qrCaption');
const qrOpenNew = document.getElementById('qrOpenNew');
const qrClose = document.getElementById('qrClose');

function openQRModal(url, caption, link) {
  if (qrImage) qrImage.src = url;
  if (qrCaption) qrCaption.textContent = caption || '';
  if (qrOpenNew) qrOpenNew.href = link || '#';
  if (qrModal) {
    qrModal.classList.remove('hidden');
    qrModal.removeAttribute('aria-hidden');
  }
}

function closeQRModal() {
  if (qrModal) {
    qrModal.classList.add('hidden');
    qrModal.setAttribute('aria-hidden', 'true');
  }
}

if (qrClose) {
  qrClose.addEventListener('click', closeQRModal);
}

if (qrModal) {
  qrModal.addEventListener('click', (e) => {
    if (e.target === qrModal) closeQRModal();
  });
}

// ==================== IMAGE MODAL ====================

const imgModal = document.getElementById('imgModal');
const imgModalImg = document.getElementById('imgModalImg');
const imgClose = document.getElementById('imgClose');

function openImageModal(src) {
  if (imgModalImg) imgModalImg.src = src;
  if (imgModal) {
    imgModal.classList.remove('hidden');
    imgModal.removeAttribute('hidden');
    imgModal.removeAttribute('aria-hidden');
  }
}

function closeImageModal() {
  if (imgModal) {
    imgModal.classList.add('hidden');
    imgModal.setAttribute('hidden', '');
    imgModal.setAttribute('aria-hidden', 'true');
  }
}

if (imgClose) {
  imgClose.addEventListener('click', closeImageModal);
}

if (imgModal) {
  imgModal.addEventListener('click', (e) => {
    if (e.target === imgModal) closeImageModal();
  });
}

// ==================== EVENT LISTENERS ====================

function initializeItemEventListeners() {
  // Item checkboxes
  document.querySelectorAll('.item-checkbox').forEach(checkbox => {
    if (!checkbox.dataset.initialized) {
      checkbox.addEventListener('change', updateBulkActions);
      checkbox.dataset.initialized = 'true';
    }
  });

  // QR buttons
  document.querySelectorAll('.btn-qr').forEach(btn => {
    if (!btn.dataset.initialized) {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const url = btn.dataset.qrUrl;
        const caption = btn.dataset.qrCaption;
        const link = btn.dataset.qrLink;
        openQRModal(url, caption, link);
      });
      btn.dataset.initialized = 'true';
    }
  });

  // Image thumbnails
  document.querySelectorAll('.item-thumb-img').forEach(img => {
    if (!img.dataset.initialized) {
      img.addEventListener('click', (e) => {
        e.preventDefault();
        openImageModal(img.src);
      });
      img.style.cursor = 'pointer';
      img.dataset.initialized = 'true';
    }
  });
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
  initializeItemEventListeners();
});

// ==================== FILTERS TOGGLE ====================

const filtersToggle = document.getElementById('filtersToggle');
const filtersContent = document.getElementById('filtersContent');

if (filtersToggle && filtersContent) {
  filtersToggle.addEventListener('click', () => {
    const isExpanded = filtersToggle.getAttribute('aria-expanded') === 'true';
    filtersToggle.setAttribute('aria-expanded', !isExpanded);
    filtersContent.style.display = isExpanded ? 'none' : 'block';
  });
}

// ==================== QR SCANNER ====================

const btnScanQR = document.getElementById('btnScanQR');

if (btnScanQR) {
  btnScanQR.addEventListener('click', async () => {
    if (!('BarcodeDetector' in window)) {
      alert('QR scanning not supported in this browser. Use Chrome on Android/Desktop or Safari 14+ on iOS.');
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
      const video = document.createElement('video');
      video.srcObject = stream;
      video.play();

      const barcodeDetector = new BarcodeDetector({ formats: ['qr_code'] });

      // Create a simple modal for the camera feed
      const scanModal = document.createElement('div');
      scanModal.className = 'qr-modal';
      scanModal.innerHTML = `
        <div class="qr-sheet">
          <div class="qr-header">
            <strong>Scan QR Code</strong>
            <button type="button" id="closeScan" class="qr-icon"><i class="fas fa-times"></i></button>
          </div>
          <div class="qr-body">
            <video id="scanVideo" style="width:100%;max-width:400px;border-radius:8px;"></video>
          </div>
        </div>
      `;
      document.body.appendChild(scanModal);

      const scanVideo = scanModal.querySelector('#scanVideo');
      scanVideo.srcObject = stream;
      scanVideo.play();

      const closeScan = scanModal.querySelector('#closeScan');
      closeScan.addEventListener('click', () => {
        stream.getTracks().forEach(track => track.stop());
        scanModal.remove();
      });

      // Scan for QR codes
      const scanInterval = setInterval(async () => {
        try {
          const barcodes = await barcodeDetector.detect(scanVideo);
          if (barcodes.length > 0) {
            const code = barcodes[0].rawValue;
            clearInterval(scanInterval);
            stream.getTracks().forEach(track => track.stop());
            scanModal.remove();

            // Navigate to the scanned URL or fill search box
            if (code.startsWith('http')) {
              window.location.href = code;
            } else {
              const searchInput = document.getElementById('q');
              if (searchInput) {
                searchInput.value = code;
                searchInput.form.submit();
              }
            }
          }
        } catch (err) {
          console.error('Barcode detection error:', err);
        }
      }, 100);

    } catch (error) {
      console.error('Camera error:', error);
      alert('Failed to access camera: ' + error.message);
    }
  });
}
