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

// ==================== ACTION BUTTONS ====================

function setupActionButtons() {
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

      // Open Profit Calculator page for this item
      window.location.href = `/profit-calculator?${params.toString()}`;
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
    const response = await fetch(`/api/items/${itemId}/inline`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || 'Failed to update item');
    }

    if (data.row_html) {
      const row = container.closest('tr');
      if (row) {
        const temp = document.createElement('tbody');
        temp.innerHTML = data.row_html.trim();
        const newRow = temp.querySelector('tr');
        if (newRow) {
          row.replaceWith(newRow);
          initializeItemEventListeners();
        }
      }
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

// ==================== LOCATION MODAL ====================

const locationModal = document.getElementById('locationInlineModal');
const locationModalForm = document.getElementById('locationModalForm');
const locationModalFields = document.getElementById('locationModalFields');
const locationModalClose = document.getElementById('locationModalClose');
const locationModalCancel = document.getElementById('locationModalCancel');
let locationModalItemId = null;

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

    if (data.row_html) {
      const row = document.querySelector(`tr[data-item-row="${locationModalItemId}"]`);
      if (row) {
        const temp = document.createElement('tbody');
        temp.innerHTML = data.row_html.trim();
        const newRow = temp.querySelector('tr');
        if (newRow) {
          row.replaceWith(newRow);
          initializeItemEventListeners();
        }
      }
    }
  } catch (error) {
    alert(error.message || 'Error updating location');
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
