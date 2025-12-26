/**
 * Qventory Dashboard JavaScript
 * Handles bulk actions, QR scanning, and image modals
 */

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
    } else if (action === 'assign_location') {
      // Open bulk location assignment modal
      openBulkLocationModal(itemIds);
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

// ==================== BULK LOCATION ASSIGNMENT ====================

function openBulkLocationModal(itemIds) {
  const modal = document.getElementById('bulkLocationModal');
  if (!modal) {
    console.error('Bulk location modal not found');
    return;
  }

  // Store selected item IDs
  modal.dataset.itemIds = JSON.stringify(itemIds);

  // Update count
  const countEl = document.getElementById('bulkLocationCount');
  if (countEl) {
    countEl.textContent = itemIds.length;
  }

  // Reset form
  const form = document.getElementById('bulkLocationForm');
  if (form) form.reset();

  // Show modal
  modal.classList.remove('hidden');
  modal.removeAttribute('aria-hidden');
}

function closeBulkLocationModal() {
  const modal = document.getElementById('bulkLocationModal');
  if (modal) {
    modal.classList.add('hidden');
    modal.setAttribute('aria-hidden', 'true');
  }
}

// Bulk location form submission
const bulkLocationForm = document.getElementById('bulkLocationForm');
if (bulkLocationForm) {
  bulkLocationForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    const modal = document.getElementById('bulkLocationModal');
    const itemIds = JSON.parse(modal.dataset.itemIds || '[]');

    if (itemIds.length === 0) {
      alert('No items selected');
      return;
    }

    const formData = new FormData(e.target);
    const locationData = {
      item_ids: itemIds,
      A: formData.get('A') || null,
      B: formData.get('B') || null,
      S: formData.get('S') || null,
      C: formData.get('C') || null,
      sync_to_ebay: formData.get('sync_to_ebay') === 'on'
    };

    // Disable submit button
    const submitBtn = e.target.querySelector('button[type="submit"]');
    const originalText = submitBtn.innerHTML;
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing...';

    try {
      const response = await fetch('/items/bulk_assign_location', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(locationData)
      });

      const data = await response.json();

      if (data.ok) {
        alert(data.message || 'Location assigned successfully');
        closeBulkLocationModal();
        location.reload();
      } else {
        alert('Error: ' + (data.error || 'Failed to assign location'));
        submitBtn.disabled = false;
        submitBtn.innerHTML = originalText;
      }
    } catch (error) {
      console.error('Bulk location assignment error:', error);
      alert('Failed to assign location');
      submitBtn.disabled = false;
      submitBtn.innerHTML = originalText;
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

  setupInlineEditors();
  setupLocationButtons();
  setupActionButtons();
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
  initializeItemEventListeners();
});

// ==================== PROFIT CALC MODAL ====================

function setupProfitCalcModal() {
  const modal = document.getElementById('profitCalcModal');
  if (!modal || modal.dataset.initialized) return;

  modal.dataset.initialized = 'true';
  const closeTargets = modal.querySelectorAll('[data-modal-close]');

  closeTargets.forEach(target => {
    target.addEventListener('click', closeProfitCalcModal);
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !modal.hidden) {
      closeProfitCalcModal();
    }
  });
}

function openProfitCalcModal(url) {
  const modal = document.getElementById('profitCalcModal');
  const frame = document.getElementById('profitCalcFrame');

  if (!modal || !frame) return false;

  frame.src = url;
  modal.hidden = false;
  document.body.classList.add('modal-open');
  return true;
}

function closeProfitCalcModal() {
  const modal = document.getElementById('profitCalcModal');
  const frame = document.getElementById('profitCalcFrame');

  if (!modal) return;

  modal.hidden = true;
  document.body.classList.remove('modal-open');
  if (frame) {
    frame.src = 'about:blank';
  }
}

// ==================== ACTION BUTTONS ====================

function setupActionButtons() {
  setupProfitCalcModal();
  // AI Research buttons
  document.querySelectorAll('.ai-research-btn').forEach(btn => {
    if (btn.dataset.initialized) return;
    btn.dataset.initialized = 'true';
    btn.style.cursor = 'pointer';

    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const itemId = btn.dataset.itemId;
      const itemTitle = btn.dataset.itemTitle;

      if (!itemId) {
        alert('Item ID not found');
        return;
      }

      // Open AI Research page for this item
      window.location.href = `/ai-research?item_id=${itemId}&title=${encodeURIComponent(itemTitle)}`;
    });
  });

  // Profit Calculator buttons
  document.querySelectorAll('.profit-calc-btn').forEach(btn => {
    if (btn.dataset.initialized) return;
    btn.dataset.initialized = 'true';
    btn.style.cursor = 'pointer';

    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const itemId = btn.dataset.itemId;
      const itemTitle = btn.dataset.itemTitle;
      const itemCost = btn.dataset.itemCost;
      const itemPrice = btn.dataset.itemPrice;

      if (!itemId) {
        alert('Item ID not found');
        return;
      }

      // Build query params
      const params = new URLSearchParams({
        item_id: itemId,
        title: itemTitle || ''
      });

      if (itemCost) params.append('cost', itemCost);
      if (itemPrice) params.append('price', itemPrice);

      const url = `/profit-calculator?${params.toString()}&embed=1`;
      if (!openProfitCalcModal(url)) {
        window.location.href = url.replace('&embed=1', '');
      }
    });
  });

  // Sync to eBay buttons
  document.querySelectorAll('.sync-to-ebay-btn').forEach(btn => {
    if (btn.dataset.initialized) return;
    btn.dataset.initialized = 'true';
    btn.style.cursor = 'pointer';

    btn.addEventListener('click', async (e) => {
      e.preventDefault();
      const itemId = btn.dataset.itemId;
      const ebayListingId = btn.dataset.ebayListingId;
      const locationCode = btn.dataset.locationCode;

      if (!itemId || !ebayListingId) {
        alert('Item ID or eBay Listing ID not found');
        return;
      }

      if (!locationCode) {
        alert('No location code set for this item. Please add a location first.');
        return;
      }

      if (!confirm(`Sync location "${locationCode}" to eBay listing ${ebayListingId}?`)) {
        return;
      }

      // Disable button and show loading state
      const originalHTML = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

      try {
        const response = await fetch('/item/sync_to_ebay', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            item_id: itemId
          })
        });

        const data = await response.json();

        if (data.ok) {
          alert(data.message || 'Location synced successfully!');
        } else {
          alert('Error: ' + (data.error || 'Failed to sync location'));
        }
      } catch (error) {
        console.error('Sync to eBay error:', error);
        alert('Failed to sync location to eBay');
      } finally {
        btn.disabled = false;
        btn.innerHTML = originalHTML;
      }
    });
  });

  // Thumb buttons (image preview)
  document.querySelectorAll('.thumb-wrap').forEach(btn => {
    if (btn.dataset.initialized) return;
    btn.dataset.initialized = 'true';
    btn.style.cursor = 'pointer';

    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const fullImageUrl = btn.dataset.full;
      if (fullImageUrl) {
        openImageModal(fullImageUrl);
      }
    });
  });

  // QR links
  document.querySelectorAll('.qr-link').forEach(link => {
    if (link.dataset.initialized) return;
    link.dataset.initialized = 'true';
    link.style.cursor = 'pointer';

    link.addEventListener('click', (e) => {
      e.preventDefault();
      const qrUrl = link.href;
      const caption = link.dataset.caption || 'QR Code';
      const publicLink = link.href.replace('/qr/', '/location/');
      openQRModal(qrUrl, caption, publicLink);
    });
  });
}

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

// ==================== QR SCANNER (jsQR Implementation) ====================

const btnScanQR = document.getElementById('btnScanQR');

if (btnScanQR) {
  btnScanQR.addEventListener('click', async () => {
    // Check if getUserMedia is supported
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      alert('Camera access not supported in this browser.');
      return;
    }

    // Check if jsQR is loaded
    if (typeof jsQR === 'undefined') {
      alert('QR scanner library not loaded. Please refresh the page.');
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' }
      });

      // Create modal with video and canvas
      const scanModal = document.createElement('div');
      scanModal.className = 'qr-modal';
      scanModal.innerHTML = `
        <div class="qr-sheet">
          <div class="qr-header">
            <strong>Scan QR Code</strong>
            <button type="button" id="closeScan" class="qr-icon"><i class="fas fa-times"></i></button>
          </div>
          <div class="qr-body">
            <video id="scanVideo" playsinline style="width:100%;max-width:400px;border-radius:8px;"></video>
            <canvas id="scanCanvas" style="display:none;"></canvas>
            <p style="margin-top:12px;font-size:13px;color:var(--text-secondary);text-align:center;">
              Point your camera at a QR code
            </p>
          </div>
        </div>
      `;
      document.body.appendChild(scanModal);

      const video = scanModal.querySelector('#scanVideo');
      const canvas = scanModal.querySelector('#scanCanvas');
      const context = canvas.getContext('2d');

      video.srcObject = stream;
      video.setAttribute('playsinline', true); // Required for iOS
      video.play();

      const closeScan = scanModal.querySelector('#closeScan');
      let scanning = true;

      closeScan.addEventListener('click', () => {
        scanning = false;
        stream.getTracks().forEach(track => track.stop());
        scanModal.remove();
      });

      // Start scanning when video is ready
      video.addEventListener('loadedmetadata', () => {
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        requestAnimationFrame(tick);
      });

      function tick() {
        if (!scanning) return;

        if (video.readyState === video.HAVE_ENOUGH_DATA) {
          canvas.width = video.videoWidth;
          canvas.height = video.videoHeight;
          context.drawImage(video, 0, 0, canvas.width, canvas.height);

          const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
          const code = jsQR(imageData.data, imageData.width, imageData.height, {
            inversionAttempts: "dontInvert",
          });

          if (code) {
            // QR code detected!
            scanning = false;
            stream.getTracks().forEach(track => track.stop());
            scanModal.remove();

            const qrData = code.data;

            // Navigate to the scanned URL or fill search box
            if (qrData.startsWith('http')) {
              window.location.href = qrData;
            } else {
              const searchInput = document.getElementById('q');
              if (searchInput) {
                searchInput.value = qrData;
                searchInput.form.submit();
              }
            }
            return;
          }
        }

        requestAnimationFrame(tick);
      }

    } catch (error) {
      console.error('Camera error:', error);
      let errorMsg = 'Failed to access camera.';

      if (error.name === 'NotAllowedError') {
        errorMsg = 'Camera access denied. Please allow camera access in your browser settings.';
      } else if (error.name === 'NotFoundError') {
        errorMsg = 'No camera found on this device.';
      } else if (error.name === 'NotReadableError') {
        errorMsg = 'Camera is already in use by another app.';
      }

      alert(errorMsg);
    }
  });
}

// ==================== INLINE EDITORS ====================

function setupInlineEditors() {
  document.querySelectorAll('.inline-edit').forEach(container => {
    if (container.dataset.inlineInitialized === '1') {
      return;
    }
    container.dataset.inlineInitialized = '1';

    const display = container.querySelector('.inline-edit__display');
    const form = container.querySelector('.inline-edit__form');
    const cancelBtn = form ? form.querySelector('.inline-edit__cancel') : null;

    if (!form) {
      return;
    }

    const openEditor = () => {
      if (display) {
        display.hidden = true;
      }
      form.hidden = false;
      const firstInput = form.querySelector('input, textarea, select');
      if (firstInput) {
        firstInput.focus();
        if (typeof firstInput.select === 'function') {
          firstInput.select();
        }
      }
    };

    if (display) {
      display.addEventListener('click', (event) => {
        if (event.target.closest('[data-inline-ignore]')) {
          return;
        }
        openEditor();
      });
      display.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          openEditor();
        }
      });
    }

    if (cancelBtn) {
      cancelBtn.addEventListener('click', () => {
        form.reset();
        form.hidden = true;
        if (display) {
          display.hidden = false;
        }
      });
    }

    form.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        form.reset();
        form.hidden = true;
        if (display) {
          display.hidden = false;
        }
      }
    });

    if (container.dataset.field === 'supplier') {
      const supplierInput = form.querySelector('input[name="value"]');
      const list = form.querySelector('.supplier-inline-autocomplete');
      if (supplierInput && list) {
        setupSupplierInlineAutocomplete(supplierInput, list, form, container);
      }
    }

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      submitInlineForm(container, form, display);
    });
  });
}

async function submitInlineForm(container, form, display) {
  const itemId = container.dataset.itemId;
  const field = container.dataset.field;
  const type = container.dataset.type || 'text';

  if (!itemId || !field) {
    return;
  }

  const payload = { field };

  if (type === 'location') {
    const components = {};
    form.querySelectorAll('[data-component]').forEach(input => {
      const key = input.dataset.component;
      if (!key) {
        return;
      }
      components[key] = input.value != null ? input.value.trim() : '';
    });
    payload.components = components;
  } else {
    const input = form.querySelector('input, textarea, select');
    if (!input) {
      return;
    }
    payload.value = input.value != null ? input.value.trim() : '';
  }

  const submitButton = form.querySelector('.inline-edit__action:not(.inline-edit__cancel)');
  if (submitButton) {
    submitButton.disabled = true;
    submitButton.dataset.originalText = submitButton.textContent;
    submitButton.textContent = 'Saving…';
  }

  try {
    // SPECIAL CASE: If we're in sold view and editing item_cost, use sale update endpoint
    // In sold view, the itemId is actually the sale_id (because sold view shows sales, not items)
    const isSoldView = window.location.pathname.includes('/sold') || document.querySelector('[data-view-type="sold"]');
    const isItemCostField = field === 'item_cost';

    let response, data;

    if (isSoldView && isItemCostField) {
      // Update sale's item_cost via new endpoint
      response = await fetch(`/sale/${itemId}/update_cost`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ item_cost: payload.value })
      });
      data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(data.error || 'Failed to update item cost');
      }
      // Transform response to match expected format
      data.field = 'item_cost';
      data.item_cost = data.item_cost;
    } else {
      // Normal item inline edit
      response = await fetch(`/api/items/${itemId}/inline`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      });
      data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(data.error || 'Failed to update item');
      }
    }

    // Update only the specific field instead of replacing entire row
    // This prevents losing unsaved edits in other fields
    if (data.field === 'supplier') {
      updateSupplierDisplay(container, data.supplier);
    } else if (data.field === 'item_cost') {
      updateCostDisplay(container, data.item_cost);
    } else if (data.field === 'location') {
      updateLocationDisplay(container, data.location_code, data.A, data.B, data.S, data.C);
    }
  } catch (error) {
    alert(error.message || 'Error updating item');
  } finally {
    if (submitButton) {
      submitButton.disabled = false;
      submitButton.textContent = submitButton.dataset.originalText || 'Save';
    }
    form.hidden = true;
    if (display) {
      display.hidden = false;
    }
  }
}

// Helper functions to update field displays without replacing entire row
function updateSupplierDisplay(container, supplierValue) {
  const display = container.querySelector('.inline-edit__display');
  const valueSpan = display ? display.querySelector('.inline-edit__value') : null;
  const placeholder = display ? display.querySelector('.inline-edit__placeholder') : null;

  if (supplierValue) {
    if (valueSpan) {
      valueSpan.textContent = supplierValue;
      valueSpan.style.display = '';
    } else if (placeholder) {
      const newValueSpan = document.createElement('span');
      newValueSpan.className = 'inline-edit__value tag';
      newValueSpan.textContent = supplierValue;
      placeholder.replaceWith(newValueSpan);
    }
  } else {
    if (valueSpan) {
      const newPlaceholder = document.createElement('span');
      newPlaceholder.className = 'inline-edit__placeholder';
      newPlaceholder.textContent = 'Add supplier';
      valueSpan.replaceWith(newPlaceholder);
    }
  }
}

function updateCostDisplay(container, costValue) {
  const display = container.querySelector('.inline-edit__display');
  const valueSpan = display ? display.querySelector('.inline-edit__value') : null;
  const placeholder = display ? display.querySelector('.inline-edit__placeholder') : null;

  if (costValue !== null && costValue !== undefined) {
    const formattedCost = `$${parseFloat(costValue).toFixed(2)}`;
    if (valueSpan) {
      valueSpan.innerHTML = `<i class="fas fa-receipt"></i> ${formattedCost}`;
      valueSpan.style.display = '';
    } else if (placeholder) {
      const newValueSpan = document.createElement('span');
      newValueSpan.className = 'inline-edit__value tag';
      newValueSpan.innerHTML = `<i class="fas fa-receipt"></i> ${formattedCost}`;
      placeholder.replaceWith(newValueSpan);
    }
  } else {
    if (valueSpan) {
      const newPlaceholder = document.createElement('span');
      newPlaceholder.className = 'inline-edit__placeholder';
      newPlaceholder.textContent = 'Add cost';
      valueSpan.replaceWith(newPlaceholder);
    }
  }
}

function updateLocationDisplay(container, locationCode, A, B, S, C) {
  const locationDisplay = container.querySelector('.location-display');
  if (!locationDisplay) return;

  // Update data attributes
  if (A !== undefined) locationDisplay.dataset.locationA = A || '';
  if (B !== undefined) locationDisplay.dataset.locationB = B || '';
  if (S !== undefined) locationDisplay.dataset.locationS = S || '';
  if (C !== undefined) locationDisplay.dataset.locationC = C || '';
  locationDisplay.dataset.locationCode = locationCode || '';

  // CRITICAL: Update the sync-to-ebay button's data-location-code attribute
  const row = container.closest('tr[data-item-row]');
  if (row) {
    const syncBtn = row.querySelector('.sync-to-ebay-btn');
    if (syncBtn) {
      syncBtn.dataset.locationCode = locationCode || '';
      console.log('[Location Update] Updated sync button locationCode to:', locationCode || '(empty)');
    }
  }

  // Find or create elements for display
  const linkContainer = locationDisplay.querySelector('a[data-inline-ignore]');
  const qrLink = locationDisplay.querySelector('.qr-link');
  const placeholder = locationDisplay.querySelector('.inline-edit__placeholder');

  if (locationCode) {
    const username = document.querySelector('[data-username]')?.dataset.username || '';

    if (linkContainer) {
      linkContainer.textContent = locationCode;
      linkContainer.href = `/inventory/${username}/location/${locationCode}`;
    } else if (placeholder) {
      // Create new link elements
      const newLink = document.createElement('a');
      newLink.href = `/inventory/${username}/location/${locationCode}`;
      newLink.dataset.inlineIgnore = 'true';
      newLink.textContent = locationCode;

      const newQRLink = document.createElement('a');
      newQRLink.className = 'tag qr-link';
      newQRLink.href = `/inventory/${username}/qr-location?code=${encodeURIComponent(locationCode)}`;
      newQRLink.dataset.caption = `QR for ${locationCode}`;
      newQRLink.dataset.inlineIgnore = 'true';
      newQRLink.innerHTML = '<i class="fas fa-qrcode"></i> QR';

      placeholder.replaceWith(newLink);
      newLink.after(document.createTextNode(' '));
      newLink.nextSibling.after(newQRLink);
    }

    if (qrLink) {
      qrLink.href = `/inventory/${username}/qr-location?code=${encodeURIComponent(locationCode)}`;
      qrLink.dataset.caption = `QR for ${locationCode}`;
    }
  } else {
    // No location - show placeholder
    if (linkContainer) {
      const newPlaceholder = document.createElement('span');
      newPlaceholder.className = 'inline-edit__placeholder';
      newPlaceholder.textContent = 'No location';
      linkContainer.replaceWith(newPlaceholder);
      if (qrLink) qrLink.remove();
    }
  }
}

function setupSupplierInlineAutocomplete(input, list, form, container) {
  if (input.dataset.autocompleteInitialized === '1') {
    return;
  }
  input.dataset.autocompleteInitialized = '1';

  let activeIndex = -1;
  let debounceTimer = null;

  const closeList = () => {
    list.classList.remove('show');
    list.innerHTML = '';
    activeIndex = -1;
  };

  const commitValue = (value) => {
    input.value = value;
    closeList();
  };

  input.addEventListener('input', (event) => {
    const query = event.target.value.trim();
    clearTimeout(debounceTimer);

    if (query.length === 0) {
      closeList();
      return;
    }

    debounceTimer = setTimeout(async () => {
      try {
        const response = await fetch(`/api/suppliers/search?q=${encodeURIComponent(query)}`);
        if (!response.ok) {
          throw new Error('Failed to fetch suppliers');
        }

        const suppliers = await response.json();
        if (!Array.isArray(suppliers) || suppliers.length === 0) {
          closeList();
          return;
        }

        list.innerHTML = '';
        suppliers.forEach((supplier, index) => {
          const item = document.createElement('div');
          item.className = 'autocomplete-item';
          item.innerHTML = highlightSupplierMatch(supplier, query);
          item.dataset.index = index;
          item.dataset.value = supplier;
          item.addEventListener('mousedown', (e) => {
            e.preventDefault();
            commitValue(supplier);
          });
          list.appendChild(item);
        });

        list.classList.add('show');
        activeIndex = -1;
      } catch (error) {
        console.error('Supplier autocomplete error:', error);
        closeList();
      }
    }, 200);
  });

  input.addEventListener('keydown', (event) => {
    const items = list.querySelectorAll('.autocomplete-item');
    if (!items.length) {
      return;
    }

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      activeIndex = (activeIndex + 1) % items.length;
      updateSupplierActiveItem(items, activeIndex);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      activeIndex = activeIndex <= 0 ? items.length - 1 : activeIndex - 1;
      updateSupplierActiveItem(items, activeIndex);
    } else if (event.key === 'Enter' && activeIndex >= 0) {
      event.preventDefault();
      const value = items[activeIndex].dataset.value;
      commitValue(value);
    } else if (event.key === 'Escape') {
      closeList();
    }
  });

  const outsideHandler = (event) => {
    if (!container.contains(event.target)) {
      closeList();
    }
  };

  document.addEventListener('click', outsideHandler);
  form.addEventListener('reset', closeList);
  form.addEventListener('submit', closeList);
}

function updateSupplierActiveItem(items, activeIndex) {
  items.forEach((item, index) => {
    if (index === activeIndex) {
      item.classList.add('active');
      item.scrollIntoView({ block: 'nearest' });
    } else {
      item.classList.remove('active');
    }
  });
}

function highlightSupplierMatch(text, query) {
  if (!text || !query) return text || '';
  const regex = new RegExp(`(${escapeSupplierRegex(query)})`, 'gi');
  return text.replace(regex, '<span class="match">$1</span>');
}

function escapeSupplierRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// ==================== LOCATION MODAL ====================

const locationModal = document.getElementById('locationInlineModal');
const locationModalForm = document.getElementById('locationModalForm');
const locationModalFields = document.getElementById('locationModalFields');
const locationModalClose = document.getElementById('locationModalClose');
const locationModalCancel = document.getElementById('locationModalCancel');
let locationModalItemId = null;
let locationModalContext = null; // Store modal context when opening QR scanner
const LOCATION_SAVE_TEXT = 'Save & Sync';
const LOCATION_UPDATE_TEXT = 'Update & Sync';

function showFlashMessage(message, category = 'ok') {
  const mainContent = document.querySelector('.main-content');
  if (!mainContent) {
    alert(message);
    return;
  }

  let container = mainContent.querySelector('.flash-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'flash-container';
    mainContent.insertBefore(container, mainContent.querySelector('.content-wrapper') || mainContent.firstChild);
  }

  const flash = document.createElement('div');
  flash.className = `flash ${category === 'ok' ? 'ok' : category === 'error' ? 'error' : ''}`;
  flash.textContent = message;

  const close = document.createElement('button');
  close.className = 'flash-close';
  close.textContent = '×';
  close.addEventListener('click', () => flash.remove());

  flash.appendChild(close);
  container.appendChild(flash);

  setTimeout(() => {
    flash.remove();
  }, 6000);
}

function setupLocationButtons() {
  document.querySelectorAll('.location-inline-button').forEach(button => {
    if (button.dataset.inlineInitialized === '1') {
      return;
    }
    button.dataset.inlineInitialized = '1';
    button.addEventListener('click', (event) => {
      event.preventDefault();
      openLocationModal(button);
    });
  });
}

function openLocationModal(button) {
  if (!locationModal || !locationModalForm || !locationModalFields) {
    return;
  }

  const locationContainer = button.closest('.inline-edit--location');
  const locationDisplay = button.closest('.location-display');
  if (!locationContainer || !locationDisplay) {
    return;
  }

  locationModalItemId = locationContainer.dataset.itemId;
  locationModalFields.innerHTML = '';

  const components = [
    { key: 'A', enabled: locationDisplay.dataset.enableA === '1', label: locationDisplay.dataset.labelA || 'A', value: locationDisplay.dataset.locationA || '' },
    { key: 'B', enabled: locationDisplay.dataset.enableB === '1', label: locationDisplay.dataset.labelB || 'B', value: locationDisplay.dataset.locationB || '' },
    { key: 'S', enabled: locationDisplay.dataset.enableS === '1', label: locationDisplay.dataset.labelS || 'S', value: locationDisplay.dataset.locationS || '' },
    { key: 'C', enabled: locationDisplay.dataset.enableC === '1', label: locationDisplay.dataset.labelC || 'C', value: locationDisplay.dataset.locationC || '' },
  ];

  let firstInput = null;
  components.forEach(component => {
    if (!component.enabled) {
      return;
    }
    const wrapper = document.createElement('label');
    wrapper.textContent = component.label;
    wrapper.className = 'location-modal__label';

    const input = document.createElement('input');
    input.type = 'text';
    input.name = component.key;
    input.value = component.value;
    input.autocomplete = 'off';
    input.dataset.component = component.key;
    input.setAttribute('data-component', component.key);
    wrapper.appendChild(input);
    locationModalFields.appendChild(wrapper);
    if (!firstInput) {
      firstInput = input;
    }
  });

  const submitButton = locationModalForm.querySelector('button[type="submit"]');
  const hasLocation = (locationDisplay.dataset.locationCode || '').trim().length > 0;
  if (submitButton) {
    submitButton.textContent = hasLocation ? LOCATION_UPDATE_TEXT : LOCATION_SAVE_TEXT;
  }

  locationModal.classList.remove('hidden');
  locationModal.removeAttribute('hidden');
  locationModal.removeAttribute('aria-hidden');

  if (firstInput) {
    firstInput.focus();
    firstInput.select();
  }
}

function closeLocationModal() {
  if (!locationModal) {
    return;
  }
  locationModal.classList.add('hidden');
  locationModal.setAttribute('hidden', '');
  locationModal.setAttribute('aria-hidden', 'true');
  locationModalItemId = null;
  if (locationModalFields) {
    locationModalFields.innerHTML = '';
  }
}

async function submitLocationModal(event) {
  event.preventDefault();
  if (!locationModalItemId) {
    return;
  }

  const payload = {
    field: 'location',
    components: {}
  };

  locationModalForm.querySelectorAll('[data-component]').forEach(input => {
    const key = input.dataset.component;
    payload.components[key] = input.value != null ? input.value.trim() : '';
  });

  const submitButton = locationModalForm.querySelector('button[type="submit"]');
  if (submitButton) {
    submitButton.disabled = true;
    submitButton.dataset.originalText = submitButton.textContent;
    submitButton.textContent = 'Saving…';
  }

  try {
    const response = await fetch(`/api/items/${locationModalItemId}/inline`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || 'Failed to update location');
    }

    // Update location display without replacing entire row
    const row = document.querySelector(`tr[data-item-row="${locationModalItemId}"]`);
    if (row) {
      const locationContainer = row.querySelector('.inline-edit--location');
      if (locationContainer) {
        updateLocationDisplay(locationContainer, data.location_code, data.A, data.B, data.S, data.C);
      }
    }

    if (data.location_code) {
      const syncResponse = await fetch('/item/sync_to_ebay', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_id: locationModalItemId })
      });
      const syncData = await syncResponse.json();
      if (!syncResponse.ok || !syncData.ok) {
        throw new Error(syncData.error || 'eBay sync failed');
      }
      showFlashMessage(`eBay Custom SKU updated on item ${locationModalItemId}`, 'ok');
    }
  } catch (error) {
    showFlashMessage(error.message || 'Error updating location', 'error');
  } finally {
    if (submitButton) {
      submitButton.disabled = false;
      submitButton.textContent = submitButton.dataset.originalText || 'Save';
    }
    closeLocationModal();
  }
}

if (locationModalForm) {
  locationModalForm.addEventListener('submit', submitLocationModal);
}
if (locationModalClose) {
  locationModalClose.addEventListener('click', closeLocationModal);
}
if (locationModalCancel) {
  locationModalCancel.addEventListener('click', closeLocationModal);
}
if (locationModal) {
  locationModal.addEventListener('click', (event) => {
    if (event.target === locationModal) {
      closeLocationModal();
    }
  });
}

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && locationModal && !locationModal.classList.contains('hidden')) {
    closeLocationModal();
  }
});

// QR Scanner callback for location parsing
// This will be called by the QR scanner script when scanning from location modal
window.qrScannerLocationCallback = null;

// QR Scanner button in location modal
const locationModalScanQRBtn = document.getElementById('locationModalScanQR');
if (locationModalScanQRBtn) {
  locationModalScanQRBtn.addEventListener('click', () => {
    // Save current modal context before closing
    locationModalContext = {
      itemId: locationModalItemId,
      fields: []
    };

    // Save current field configuration
    locationModalFields.querySelectorAll('[data-component]').forEach(input => {
      const label = input.parentElement.textContent.replace(input.value, '').trim();
      locationModalContext.fields.push({
        key: input.dataset.component,
        label: label,
        value: input.value
      });
    });

    console.log('[QR Location] Saved modal context:', locationModalContext);

    // Set the callback for when QR is scanned
    window.qrScannerLocationCallback = parseAndPopulateLocation;

    // Close location modal temporarily (hide but don't clear fields yet)
    locationModal.classList.add('hidden');
    locationModal.setAttribute('hidden', '');

    // Open the QR scanner (exposed globally from dashboard.html)
    if (typeof window.openQRScanner === 'function') {
      window.openQRScanner();
    } else {
      console.error('QR Scanner not available');
      alert('QR Scanner not available on this page');
      // Reopen location modal
      locationModal.classList.remove('hidden');
      locationModal.removeAttribute('hidden');
      window.qrScannerLocationCallback = null;
      locationModalContext = null;
    }
  });
}

function parseLocationCode(rawCode) {
  // Extract location code from URL if needed
  // Example: "https://qventory.com/user/location/B3S2" -> "B3S2"
  let code = rawCode;

  // If it's a URL, extract the location code part
  if (code.includes('/location/')) {
    const parts = code.split('/location/');
    code = parts[1] || code;
    // Remove any trailing slashes or query params
    code = code.split('?')[0].split('#')[0].replace(/\/$/, '');
  }

  // Parse location code like "A1B2S3CT1" into components
  // Handles multi-char values: A1, B2, S3, C=T1
  // Returns {A: '1', B: '2', S: '3', C: 'T1'}
  const components = {};

  // Pattern: A letter (A, B, S, or C) followed by alphanumeric chars until next marker
  // Use non-greedy +? and lookahead to stop before the next A/B/S/C or end of string
  const pattern = /([ABSC])([A-Z0-9]+?)(?=[ABSC]|$)/gi;
  let match;

  while ((match = pattern.exec(code)) !== null) {
    const key = match[1].toUpperCase();
    const value = match[2];
    components[key] = value;
  }

  return components;
}

function parseAndPopulateLocation(qrValue) {
  // Callback when QR is scanned
  console.log('[QR Location] Raw QR value:', qrValue);
  const components = parseLocationCode(qrValue);
  console.log('[QR Location] Parsed components:', components);

  if (!locationModalContext) {
    console.error('[QR Location] No modal context saved!');
    window.qrScannerLocationCallback = null;
    return;
  }

  // Restore item ID
  locationModalItemId = locationModalContext.itemId;

  // Recreate fields with scanned values
  locationModalFields.innerHTML = '';
  let firstInput = null;

  locationModalContext.fields.forEach(field => {
    const wrapper = document.createElement('label');
    wrapper.textContent = field.label;
    wrapper.className = 'location-modal__label';

    const input = document.createElement('input');
    input.type = 'text';
    input.name = field.key;
    input.autocomplete = 'off';
    input.dataset.component = field.key;
    input.setAttribute('data-component', field.key);

    // Use scanned value if available, otherwise use previous value
    input.value = components[field.key] || field.value;
    console.log(`[QR Location] Field ${field.key} = ${input.value} (scanned: ${components[field.key] || 'N/A'})`);

    wrapper.appendChild(input);
    locationModalFields.appendChild(wrapper);

    if (!firstInput) {
      firstInput = input;
    }
  });

  // Reopen location modal
  locationModal.classList.remove('hidden');
  locationModal.removeAttribute('hidden');
  locationModal.removeAttribute('aria-hidden');

  if (firstInput) {
    firstInput.focus();
    firstInput.select();
  }

  // Clear the callback and context
  window.qrScannerLocationCallback = null;
  locationModalContext = null;
}

// ==================== EXPOSE FOR AUTO-REFRESH ====================
// Expose setupInlineEditors globally so it can be called after dynamic row insertion
window.dashboardScripts = {
  initInlineEdit: setupInlineEditors,
  setupLocationButtons: setupLocationButtons,
  setupActionButtons: setupActionButtons
};
