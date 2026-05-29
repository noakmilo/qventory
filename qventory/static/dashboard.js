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
const bulkEditOpenBtn = document.getElementById('bulkEditOpenBtn');
let bulkRelistItems = [];
let bulkRelistDiscountPercent = 0;

function getSelectedItemIds() {
  const selectedCheckboxes = document.querySelectorAll('.item-checkbox:checked');
  return Array.from(selectedCheckboxes)
    .map(cb => cb.dataset.itemId || cb.value)
    .map(id => parseInt(id, 10))
    .filter(id => Number.isFinite(id));
}

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
    if (bulkEditOpenBtn) bulkEditOpenBtn.style.display = 'inline-flex';
  } else {
    bulkActionsContainer.style.display = 'none';
    bulkSelectedCount.textContent = '';
    if (bulkEditOpenBtn) bulkEditOpenBtn.style.display = 'none';
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

    const itemIds = getSelectedItemIds();

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
    } else if (action === 'bulk_update') {
      openBulkEditModal(itemIds);
    } else if (action === 'bulk_relist') {
      if (itemIds.length < 2) {
        alert('Select 2 or more items for bulk relist');
        return;
      }
      openBulkRelistModal(itemIds);
    } else if (action === 'bulk_schedule_auto_relist') {
      if (itemIds.length < 2) {
        alert('Select 2 or more items for bulk auto relist');
        return;
      }
      openBulkAutoRelistModal(itemIds);
    } else if (action === 'bulk_schedule_price_update') {
      if (itemIds.length < 2) {
        alert('Select 2 or more items for bulk price update');
        return;
      }
      openBulkPriceUpdateModal(itemIds);
    } else if (action === 'retire_items') {
      if (!confirm(`Copy ${itemIds.length} item(s) to Retirements?`)) {
        return;
      }

      try {
        const response = await fetch('/items/bulk_retire', {
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
        console.error('Bulk retire error:', error);
        alert('Failed to add items to Retirements');
      }
    } else if (action === 'purge_retired') {
      if (!confirm(`This will permanently end ${itemIds.length} listing(s) on eBay. This is irreversible. Continue?`)) {
        return;
      }

      try {
        const response = await fetch('/retired_items/bulk_purge', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ retired_item_ids: itemIds })
        });

        const data = await response.json();
        if (data.ok) {
          alert(data.message);
          location.reload();
        } else {
          alert('Error: ' + data.error);
        }
      } catch (error) {
        console.error('Bulk purge error:', error);
        alert('Failed to purge retired items');
      }
    } else if (action === 'archive_retired' || action === 'restore_retired') {
      const archive = action === 'archive_retired';
      const verb = archive ? 'Archive' : 'Restore';
      if (!confirm(`${verb} ${itemIds.length} retired item(s)?`)) {
        return;
      }

      try {
        const response = await fetch('/retired_items/bulk_archive', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ retired_item_ids: itemIds, archive })
        });

        const data = await response.json();
        if (data.ok) {
          alert(data.message);
          location.reload();
        } else {
          alert('Error: ' + data.error);
        }
      } catch (error) {
        console.error('Bulk archive retired error:', error);
        alert(archive ? 'Failed to archive retired items' : 'Failed to restore retired items');
      }
    } else if (action === 'delete_retired') {
      if (!confirm(`Remove ${itemIds.length} item(s) from Retirements?`)) {
        return;
      }

      try {
        const response = await fetch('/retired_items/bulk_delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ retired_item_ids: itemIds })
        });

        const data = await response.json();
        if (data.ok) {
          alert(data.message);
          location.reload();
        } else {
          alert('Error: ' + data.error);
        }
      } catch (error) {
        console.error('Bulk delete retired error:', error);
        alert('Failed to remove items');
      }
    } else if (action === 'deactivate_by_user') {
      if (!confirm(`Hide ${itemIds.length} item(s) from active inventory?`)) {
        return;
      }

      try {
        const response = await fetch('/items/bulk_deactivate_by_user', {
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
        console.error('Bulk deactivate error:', error);
        alert('Failed to hide items');
      }
    } else if (action === 'reactivate_by_user') {
      if (!confirm(`Reactivate ${itemIds.length} item(s) into active inventory?`)) {
        return;
      }

      try {
        const response = await fetch('/items/bulk_reactivate_by_user', {
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
        console.error('Bulk reactivate error:', error);
        alert('Failed to reactivate items');
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


// ==================== BULK UPDATE & RELIST ====================

function getBulkRelistItemData(itemIds) {
  return itemIds.map(id => {
    const row = document.querySelector(`tr[data-item-row="${id}"]`);
    const price = row ? parseFloat(row.dataset.itemPrice || '') : NaN;
    const titleCell = row?.querySelector('[data-col="title"]');
    return {
      id,
      title: row?.dataset.itemTitle || titleCell?.textContent?.trim() || `Item ${id}`,
      price: Number.isFinite(price) ? price : null
    };
  });
}

function calculateBulkRelistPrice(price) {
  if (!Number.isFinite(price)) return null;
  return price * (1 - bulkRelistDiscountPercent / 100);
}

function formatBulkRelistPrice(price) {
  return Number.isFinite(price) ? `$${price.toFixed(2)}` : 'Missing price';
}

function updateBulkRelistState() {
  const countEl = document.getElementById('bulkRelistCount');
  const validationEl = document.getElementById('bulkRelistValidation');
  const discountLabel = document.getElementById('bulkRelistDiscountLabel');
  const submitBtn = document.getElementById('bulkRelistSubmit');

  if (countEl) countEl.textContent = bulkRelistItems.length;
  if (discountLabel) {
    discountLabel.textContent = bulkRelistDiscountPercent > 0
      ? `Current rule: -${bulkRelistDiscountPercent}% from each current price`
      : 'Current rule: no discount';
  }

  const requiresPrice = bulkRelistDiscountPercent > 0;
  const missingPriceCount = bulkRelistItems.filter(item => item.price === null).length;
  const disabled = bulkRelistItems.length < 2 || (requiresPrice && missingPriceCount > 0);

  if (validationEl) {
    if (bulkRelistItems.length < 2) {
      validationEl.textContent = 'Keep at least 2 items to run bulk relist.';
      validationEl.style.color = '#fca5a5';
    } else if (requiresPrice && missingPriceCount > 0) {
      validationEl.textContent = `${missingPriceCount} item(s) need a current price.`;
      validationEl.style.color = '#fca5a5';
    } else {
      validationEl.textContent = `${bulkRelistItems.length} item(s) ready.`;
      validationEl.style.color = 'var(--sub)';
    }
  }

  if (submitBtn) submitBtn.disabled = disabled;
}

function renderBulkRelistItems() {
  const list = document.getElementById('bulkRelistItemsList');
  if (!list) return;

  if (bulkRelistItems.length === 0) {
    list.innerHTML = '<div style="padding:14px;color:var(--sub);font-size:13px;">No items selected.</div>';
    updateBulkRelistState();
    return;
  }

  list.innerHTML = bulkRelistItems.map(item => {
    const newPrice = item.price === null ? null : calculateBulkRelistPrice(item.price);
    return `
      <div data-bulk-relist-item="${item.id}" style="display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center;padding:10px 12px;border-bottom:1px solid var(--border);">
        <div style="min-width:0;">
          <div style="font-size:13px;color:var(--text);font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(item.title)}</div>
          <div style="font-size:12px;color:var(--sub);margin-top:4px;">
            Current: <strong>${formatBulkRelistPrice(item.price)}</strong>
            <span style="margin:0 6px;">→</span>
            New: <strong style="color:#f97316;">${formatBulkRelistPrice(newPrice)}</strong>
          </div>
        </div>
        <button type="button" class="btn" data-bulk-relist-remove="${item.id}" style="padding:6px 9px;font-size:12px;">
          <i class="fas fa-times"></i>
        </button>
      </div>
    `;
  }).join('');

  updateBulkRelistState();
}

function setBulkRelistDiscount(percent) {
  const parsed = parseFloat(percent);
  if (!Number.isFinite(parsed) || parsed < 0 || parsed > 100) {
    alert('Enter a discount between 0 and 100');
    return;
  }
  bulkRelistDiscountPercent = parsed;
  renderBulkRelistItems();
}

function openBulkRelistModal(itemIds) {
  const modal = document.getElementById('bulkRelistModal');
  if (!modal) {
    console.error('Bulk relist modal not found');
    return;
  }

  bulkRelistItems = getBulkRelistItemData(itemIds);
  bulkRelistDiscountPercent = 0;

  const customInput = document.getElementById('bulkRelistCustomDiscount');
  if (customInput) customInput.value = '';

  renderBulkRelistItems();
  modal.hidden = false;
  document.body.classList.add('modal-open');
}

function closeBulkRelistModal() {
  const modal = document.getElementById('bulkRelistModal');
  if (!modal) return;
  modal.hidden = true;
  document.body.classList.remove('modal-open');
}

document.addEventListener('click', (event) => {
  const closeBtn = event.target.closest('[data-modal-close="bulkRelist"]');
  if (closeBtn) {
    closeBulkRelistModal();
    return;
  }

  const discountBtn = event.target.closest('[data-bulk-relist-discount]');
  if (discountBtn) {
    setBulkRelistDiscount(discountBtn.dataset.bulkRelistDiscount);
    return;
  }

  const removeBtn = event.target.closest('[data-bulk-relist-remove]');
  if (removeBtn) {
    const itemId = parseInt(removeBtn.dataset.bulkRelistRemove, 10);
    bulkRelistItems = bulkRelistItems.filter(item => item.id !== itemId);
    const checkbox = document.querySelector(`.item-checkbox[data-item-id="${itemId}"]`);
    if (checkbox) {
      checkbox.checked = false;
      updateBulkActions();
    }
    renderBulkRelistItems();
  }
});

document.getElementById('bulkRelistApplyCustomDiscount')?.addEventListener('click', () => {
  const input = document.getElementById('bulkRelistCustomDiscount');
  setBulkRelistDiscount(input?.value);
});

document.getElementById('bulkRelistCustomDiscount')?.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    setBulkRelistDiscount(event.target.value);
  }
});

document.getElementById('bulkRelistForm')?.addEventListener('submit', async (event) => {
  event.preventDefault();

  const itemIds = bulkRelistItems.map(item => item.id);
  if (itemIds.length < 2) {
    alert('Keep at least 2 items for bulk relist');
    return;
  }

  const submitBtn = document.getElementById('bulkRelistSubmit');
  const originalHtml = submitBtn?.innerHTML;
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Queueing...';
  }

  try {
    const response = await fetch('/items/bulk_relist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_ids: itemIds,
        discount_percent: bulkRelistDiscountPercent
      })
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || 'Failed to queue bulk relist');
    }
    closeBulkRelistModal();
    alert(data.message || 'Bulk relist queued');
    location.reload();
  } catch (error) {
    console.error('Bulk relist error:', error);
    alert(error.message || 'Failed to queue bulk relist');
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = originalHtml;
    }
  }
});

function escapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = value ?? '';
  return div.innerHTML;
}

window.closeBulkRelistModal = closeBulkRelistModal;

// ==================== SCHEDULED AUTO RELIST ====================

let autoRelistScheduleState = {
  itemId: null,
  currentPrice: null,
  hasRule: false
};
let bulkAutoRelistItems = [];

function parseMoneyValue(value) {
  const parsed = parseFloat(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatMoneyValue(value) {
  return Number.isFinite(value) ? `$${value.toFixed(2)}` : '—';
}

function calculateDiscountedFloorPrice(currentPrice, discountPercent, floorPrice) {
  if (!Number.isFinite(currentPrice) || !Number.isFinite(discountPercent)) return null;
  const discounted = currentPrice * (1 - discountPercent / 100);
  if (Number.isFinite(floorPrice)) {
    return Math.max(discounted, floorPrice);
  }
  return discounted;
}

function toggleCustomDays(frequencyEl, wrapEl) {
  if (!frequencyEl || !wrapEl) return;
  wrapEl.style.display = frequencyEl.value === 'custom' ? 'block' : 'none';
}

function updateAutoRelistSchedulePreview() {
  const discount = parseMoneyValue(document.getElementById('autoRelistScheduleDiscount')?.value);
  const floor = parseMoneyValue(document.getElementById('autoRelistScheduleFloorPrice')?.value);
  const preview = document.getElementById('autoRelistSchedulePreview');
  if (!preview) return;

  const current = autoRelistScheduleState.currentPrice;
  if (!Number.isFinite(current) || !Number.isFinite(discount) || !Number.isFinite(floor)) {
    preview.textContent = 'Enter a discount and floor price to preview the next relist price.';
    return;
  }

  const nextPrice = calculateDiscountedFloorPrice(current, discount, floor);
  preview.innerHTML = `Next relist price: <strong style="color:#f97316;">${formatMoneyValue(nextPrice)}</strong> (floor ${formatMoneyValue(floor)})`;
}

function closeAutoRelistScheduleModal() {
  const modal = document.getElementById('autoRelistScheduleModal');
  if (!modal) return;
  modal.hidden = true;
  document.body.classList.remove('modal-open');
}

async function openAutoRelistScheduleModal(itemId, fallback = {}) {
  const modal = document.getElementById('autoRelistScheduleModal');
  if (!modal) return;

  const titleEl = document.getElementById('autoRelistScheduleItemTitle');
  const priceEl = document.getElementById('autoRelistScheduleCurrentPrice');
  const itemInput = document.getElementById('autoRelistScheduleItemId');
  const frequencyEl = document.getElementById('autoRelistScheduleFrequency');
  const customDaysEl = document.getElementById('autoRelistScheduleCustomDays');
  const discountEl = document.getElementById('autoRelistScheduleDiscount');
  const floorEl = document.getElementById('autoRelistScheduleFloorPrice');
  const runFirstEl = document.getElementById('autoRelistRunFirstImmediately');
  const stopBtn = document.getElementById('autoRelistScheduleStop');
  const submitBtn = document.getElementById('autoRelistScheduleSubmit');

  itemInput.value = itemId;
  titleEl.textContent = fallback.title || `Item ${itemId}`;
  priceEl.textContent = formatMoneyValue(parseMoneyValue(fallback.price));
  autoRelistScheduleState = {
    itemId,
    currentPrice: parseMoneyValue(fallback.price),
    hasRule: false
  };

  frequencyEl.value = 'weekly';
  customDaysEl.value = '7';
  discountEl.value = '10';
  floorEl.value = fallback.price ? (parseMoneyValue(fallback.price) * 0.6).toFixed(2) : '';
  if (runFirstEl) runFirstEl.checked = false;
  stopBtn.style.display = 'none';
  submitBtn.innerHTML = '<i class="fas fa-clock"></i> Schedule';
  toggleCustomDays(frequencyEl, document.getElementById('autoRelistScheduleCustomDaysWrap'));

  modal.hidden = false;
  document.body.classList.add('modal-open');

  try {
    const response = await fetch(`/items/${itemId}/auto_relist_rule`);
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || 'Failed to load schedule');
    }

    const item = data.item || {};
    const rule = data.rule;
    autoRelistScheduleState.currentPrice = parseMoneyValue(item.price);
    titleEl.textContent = item.title || titleEl.textContent;
    priceEl.textContent = formatMoneyValue(autoRelistScheduleState.currentPrice);

    if (rule) {
      autoRelistScheduleState.hasRule = true;
      frequencyEl.value = rule.frequency || 'weekly';
      customDaysEl.value = rule.custom_interval_days || 7;
      discountEl.value = rule.price_decrease_amount ?? 10;
      floorEl.value = Number.isFinite(parseMoneyValue(rule.min_price)) ? parseMoneyValue(rule.min_price).toFixed(2) : '';
      if (runFirstEl) runFirstEl.checked = Boolean(rule.run_first_relist_immediately);
      stopBtn.style.display = 'inline-flex';
      submitBtn.innerHTML = '<i class="fas fa-clock"></i> Update Schedule';
    } else if (Number.isFinite(autoRelistScheduleState.currentPrice)) {
      floorEl.value = (autoRelistScheduleState.currentPrice * 0.6).toFixed(2);
    }
    toggleCustomDays(frequencyEl, document.getElementById('autoRelistScheduleCustomDaysWrap'));
    updateAutoRelistSchedulePreview();
  } catch (error) {
    alert(error.message || 'Failed to load schedule');
    closeAutoRelistScheduleModal();
  }
}

function getAutoRelistSchedulePayload() {
  return {
    frequency: document.getElementById('autoRelistScheduleFrequency')?.value,
    custom_interval_days: document.getElementById('autoRelistScheduleCustomDays')?.value,
    discount_percent: document.getElementById('autoRelistScheduleDiscount')?.value,
    min_price: document.getElementById('autoRelistScheduleFloorPrice')?.value,
    run_first_relist_immediately: document.getElementById('autoRelistRunFirstImmediately')?.checked || false
  };
}

document.addEventListener('click', (event) => {
  const scheduleBtn = event.target.closest('.schedule-auto-relist-btn');
  if (scheduleBtn) {
    const itemId = parseInt(scheduleBtn.dataset.itemId, 10);
    if (Number.isFinite(itemId)) {
      openAutoRelistScheduleModal(itemId, {
        title: scheduleBtn.dataset.itemTitle || '',
        price: scheduleBtn.dataset.itemPrice || ''
      });
    }
    return;
  }

  const closeBtn = event.target.closest('[data-modal-close="autoRelistSchedule"]');
  if (closeBtn) {
    closeAutoRelistScheduleModal();
    return;
  }

  const discountBtn = event.target.closest('[data-auto-relist-discount]');
  if (discountBtn) {
    const discountEl = document.getElementById('autoRelistScheduleDiscount');
    if (discountEl) discountEl.value = discountBtn.dataset.autoRelistDiscount;
    updateAutoRelistSchedulePreview();
  }
});

document.getElementById('autoRelistScheduleFrequency')?.addEventListener('change', (event) => {
  toggleCustomDays(event.target, document.getElementById('autoRelistScheduleCustomDaysWrap'));
});
document.getElementById('autoRelistScheduleDiscount')?.addEventListener('input', updateAutoRelistSchedulePreview);
document.getElementById('autoRelistScheduleFloorPrice')?.addEventListener('input', updateAutoRelistSchedulePreview);

document.getElementById('autoRelistScheduleForm')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const itemId = document.getElementById('autoRelistScheduleItemId')?.value;
  const submitBtn = document.getElementById('autoRelistScheduleSubmit');
  const originalHtml = submitBtn?.innerHTML;

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
  }

  try {
    const response = await fetch(`/items/${itemId}/auto_relist_rule`, {
      method: autoRelistScheduleState.hasRule ? 'PATCH' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(getAutoRelistSchedulePayload())
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || 'Failed to save schedule');
    }
    alert(data.message || 'Schedule saved');
    location.reload();
  } catch (error) {
    alert(error.message || 'Failed to save schedule');
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = originalHtml;
    }
  }
});

document.getElementById('autoRelistScheduleStop')?.addEventListener('click', async () => {
  const itemId = document.getElementById('autoRelistScheduleItemId')?.value;
  if (!itemId || !confirm('Stop this auto relist schedule?')) return;

  try {
    const response = await fetch(`/items/${itemId}/auto_relist_rule/stop`, { method: 'POST' });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || 'Failed to stop schedule');
    }
    alert(data.message || 'Schedule stopped');
    location.reload();
  } catch (error) {
    alert(error.message || 'Failed to stop schedule');
  }
});

// ==================== SCHEDULED PRICE UPDATE ====================

let priceUpdateState = {
  itemId: null,
  currentPrice: null,
  hasRule: false
};
let bulkPriceUpdateItems = [];

function closePriceUpdateModal() {
  const modal = document.getElementById('priceUpdateModal');
  if (!modal) return;
  modal.hidden = true;
  document.body.classList.remove('modal-open');
}

function updatePriceUpdatePreview() {
  const discount = parseMoneyValue(document.getElementById('priceUpdateDiscount')?.value);
  const floor = parseMoneyValue(document.getElementById('priceUpdateFloorPrice')?.value);
  const preview = document.getElementById('priceUpdatePreview');
  if (!preview) return;

  const current = priceUpdateState.currentPrice;
  if (!Number.isFinite(current) || !Number.isFinite(discount) || !Number.isFinite(floor)) {
    preview.textContent = 'Enter a discount and floor price to preview the next price update.';
    return;
  }
  const nextPrice = calculateDiscountedFloorPrice(current, discount, floor);
  preview.innerHTML = `Next price update: <strong style="color:#eab308;">${formatMoneyValue(nextPrice)}</strong> (floor ${formatMoneyValue(floor)})`;
}

function applyPriceUpdateDiscountToNowPrice() {
  const current = priceUpdateState.currentPrice;
  const discount = parseMoneyValue(document.getElementById('priceUpdateDiscount')?.value);
  const floor = parseMoneyValue(document.getElementById('priceUpdateFloorPrice')?.value);
  const nowPriceEl = document.getElementById('priceUpdateNowPrice');
  if (!nowPriceEl || !Number.isFinite(current) || !Number.isFinite(discount)) return;
  const nextPrice = calculateDiscountedFloorPrice(current, discount, floor);
  if (Number.isFinite(nextPrice)) {
    nowPriceEl.value = nextPrice.toFixed(2);
  }
}

function updatePriceScheduleWarning({ hasPriceRule = false, hasAutoRule = false } = {}) {
  const warningEl = document.getElementById('priceUpdateConflictWarning');
  if (!warningEl) return;

  const messages = [];
  if (hasPriceRule) {
    messages.push('This item already has an active Update Price schedule. Saving will update that schedule.');
  }
  if (hasAutoRule) {
    messages.push('This item has an active Update & Relist schedule. Saving a price update schedule will stop and overwrite that schedule.');
  }

  if (!messages.length) {
    warningEl.style.display = 'none';
    warningEl.innerHTML = '';
    return;
  }

  warningEl.innerHTML = `<i class="fas fa-exclamation-triangle" style="color:#eab308;"></i> ${messages.join(' ')}`;
  warningEl.style.display = 'block';
}

async function openPriceUpdateModal(itemId, fallback = {}) {
  const modal = document.getElementById('priceUpdateModal');
  if (!modal) return;

  const titleEl = document.getElementById('priceUpdateItemTitle');
  const priceEl = document.getElementById('priceUpdateCurrentPrice');
  const itemInput = document.getElementById('priceUpdateItemId');
  const nowPriceEl = document.getElementById('priceUpdateNowPrice');
  const frequencyEl = document.getElementById('priceUpdateFrequency');
  const customDaysEl = document.getElementById('priceUpdateCustomDays');
  const discountEl = document.getElementById('priceUpdateDiscount');
  const floorEl = document.getElementById('priceUpdateFloorPrice');
  const runFirstEl = document.getElementById('priceUpdateRunFirstImmediately');
  const stopBtn = document.getElementById('priceUpdateScheduleStop');
  const submitBtn = document.getElementById('priceUpdateScheduleSubmit');

  itemInput.value = itemId;
  titleEl.textContent = fallback.title || `Item ${itemId}`;
  const fallbackPrice = parseMoneyValue(fallback.price);
  priceEl.textContent = formatMoneyValue(fallbackPrice);
  if (nowPriceEl) nowPriceEl.value = Number.isFinite(fallbackPrice) ? fallbackPrice.toFixed(2) : '';
  priceUpdateState = { itemId, currentPrice: fallbackPrice, hasRule: false };

  frequencyEl.value = 'weekly';
  customDaysEl.value = '7';
  discountEl.value = '10';
  floorEl.value = Number.isFinite(fallbackPrice) ? (fallbackPrice * 0.6).toFixed(2) : '';
  if (runFirstEl) runFirstEl.checked = false;
  stopBtn.style.display = 'none';
  submitBtn.innerHTML = '<i class="fas fa-clock"></i> Schedule';
  updatePriceScheduleWarning();
  toggleCustomDays(frequencyEl, document.getElementById('priceUpdateCustomDaysWrap'));

  modal.hidden = false;
  document.body.classList.add('modal-open');

  try {
    const response = await fetch(`/items/${itemId}/price_update_rule`);
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || 'Failed to load price update');
    }

    const item = data.item || {};
    const rule = data.rule;
    priceUpdateState.currentPrice = parseMoneyValue(item.price);
    titleEl.textContent = item.title || titleEl.textContent;
    priceEl.textContent = formatMoneyValue(priceUpdateState.currentPrice);
    if (nowPriceEl) nowPriceEl.value = Number.isFinite(priceUpdateState.currentPrice) ? priceUpdateState.currentPrice.toFixed(2) : '';
    if (rule) {
      priceUpdateState.hasRule = true;
      frequencyEl.value = rule.frequency || 'weekly';
      customDaysEl.value = rule.custom_interval_days || 7;
      discountEl.value = rule.price_decrease_amount ?? 10;
      floorEl.value = Number.isFinite(parseMoneyValue(rule.min_price)) ? parseMoneyValue(rule.min_price).toFixed(2) : '';
      if (runFirstEl) runFirstEl.checked = Boolean(rule.run_first_relist_immediately);
      stopBtn.style.display = 'inline-flex';
      submitBtn.innerHTML = '<i class="fas fa-clock"></i> Update Schedule';
    } else if (Number.isFinite(priceUpdateState.currentPrice)) {
      floorEl.value = (priceUpdateState.currentPrice * 0.6).toFixed(2);
    }
    updatePriceScheduleWarning({
      hasPriceRule: Boolean(rule),
      hasAutoRule: Boolean(data.conflicting_auto_relist_rule)
    });
    toggleCustomDays(frequencyEl, document.getElementById('priceUpdateCustomDaysWrap'));
    applyPriceUpdateDiscountToNowPrice();
    updatePriceUpdatePreview();
  } catch (error) {
    alert(error.message || 'Failed to load price update');
    closePriceUpdateModal();
  }
}

function getPriceUpdateSchedulePayload() {
  return {
    frequency: document.getElementById('priceUpdateFrequency')?.value,
    custom_interval_days: document.getElementById('priceUpdateCustomDays')?.value,
    discount_percent: document.getElementById('priceUpdateDiscount')?.value,
    min_price: document.getElementById('priceUpdateFloorPrice')?.value,
    run_first_relist_immediately: document.getElementById('priceUpdateRunFirstImmediately')?.checked || false
  };
}

document.addEventListener('click', (event) => {
  const updatePriceBtn = event.target.closest('.update-price-btn');
  if (updatePriceBtn) {
    const itemId = parseInt(updatePriceBtn.dataset.itemId, 10);
    if (Number.isFinite(itemId)) {
      openPriceUpdateModal(itemId, {
        title: updatePriceBtn.dataset.itemTitle || '',
        price: updatePriceBtn.dataset.itemPrice || ''
      });
    }
    return;
  }

  const closeBtn = event.target.closest('[data-modal-close="priceUpdate"]');
  if (closeBtn) {
    closePriceUpdateModal();
    return;
  }

  const discountBtn = event.target.closest('[data-price-update-discount]');
  if (discountBtn) {
    const discountEl = document.getElementById('priceUpdateDiscount');
    if (discountEl) discountEl.value = discountBtn.dataset.priceUpdateDiscount;
    applyPriceUpdateDiscountToNowPrice();
    updatePriceUpdatePreview();
  }
});

document.getElementById('priceUpdateFrequency')?.addEventListener('change', (event) => {
  toggleCustomDays(event.target, document.getElementById('priceUpdateCustomDaysWrap'));
});
document.getElementById('priceUpdateDiscount')?.addEventListener('input', () => {
  applyPriceUpdateDiscountToNowPrice();
  updatePriceUpdatePreview();
});
document.getElementById('priceUpdateFloorPrice')?.addEventListener('input', () => {
  applyPriceUpdateDiscountToNowPrice();
  updatePriceUpdatePreview();
});

document.getElementById('priceUpdateNowSubmit')?.addEventListener('click', async () => {
  const itemId = document.getElementById('priceUpdateItemId')?.value;
  const price = document.getElementById('priceUpdateNowPrice')?.value;
  const button = document.getElementById('priceUpdateNowSubmit');
  const originalHtml = button?.innerHTML;
  if (button) {
    button.disabled = true;
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Updating...';
  }
  try {
    const response = await fetch(`/items/${itemId}/update_price`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ price })
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || 'Failed to update price');
    }
    alert(data.message || 'Price updated');
    location.reload();
  } catch (error) {
    alert(error.message || 'Failed to update price');
  } finally {
    if (button) {
      button.disabled = false;
      button.innerHTML = originalHtml;
    }
  }
});

document.getElementById('priceUpdateForm')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const itemId = document.getElementById('priceUpdateItemId')?.value;
  const submitBtn = document.getElementById('priceUpdateScheduleSubmit');
  const originalHtml = submitBtn?.innerHTML;
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
  }
  try {
    const response = await fetch(`/items/${itemId}/price_update_rule`, {
      method: priceUpdateState.hasRule ? 'PATCH' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(getPriceUpdateSchedulePayload())
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || 'Failed to save schedule');
    }
    alert(data.message || 'Price update schedule saved');
    location.reload();
  } catch (error) {
    alert(error.message || 'Failed to save schedule');
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = originalHtml;
    }
  }
});

document.getElementById('priceUpdateScheduleStop')?.addEventListener('click', async () => {
  const itemId = document.getElementById('priceUpdateItemId')?.value;
  if (!itemId || !confirm('Stop this price update schedule?')) return;
  try {
    const response = await fetch(`/items/${itemId}/price_update_rule/stop`, { method: 'POST' });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || 'Failed to stop schedule');
    }
    alert(data.message || 'Schedule stopped');
    location.reload();
  } catch (error) {
    alert(error.message || 'Failed to stop schedule');
  }
});

function closeBulkAutoRelistModal() {
  const modal = document.getElementById('bulkAutoRelistModal');
  if (!modal) return;
  modal.hidden = true;
  document.body.classList.remove('modal-open');
}

function getBulkAutoRelistItemData(itemIds) {
  return itemIds.map(id => {
    const row = document.querySelector(`tr[data-item-row="${id}"]`);
    const price = row ? parseMoneyValue(row.dataset.itemPrice || '') : null;
    const titleCell = row?.querySelector('[data-col="title"]');
    return {
      id,
      title: row?.dataset.itemTitle || titleCell?.textContent?.trim() || `Item ${id}`,
      price,
      hasAutoRelistRule: Boolean(row?.dataset.autoRelistRuleId),
      hasPriceUpdateRule: Boolean(row?.dataset.priceUpdateRuleId),
      floorOverride: ''
    };
  });
}

function updateBulkAutoRelistState() {
  const countEl = document.getElementById('bulkAutoRelistCount');
  const validationEl = document.getElementById('bulkAutoRelistValidation');
  const submitBtn = document.getElementById('bulkAutoRelistSubmit');
  const missingPrice = bulkAutoRelistItems.filter(item => !Number.isFinite(item.price)).length;

  if (countEl) countEl.textContent = bulkAutoRelistItems.length;
  if (validationEl) {
    if (bulkAutoRelistItems.length < 2) {
      validationEl.textContent = 'Keep at least 2 items to schedule.';
      validationEl.style.color = '#fca5a5';
    } else if (missingPrice > 0) {
      validationEl.textContent = `${missingPrice} item(s) need a current price.`;
      validationEl.style.color = '#fca5a5';
    } else {
      validationEl.textContent = `${bulkAutoRelistItems.length} item(s) ready.`;
      validationEl.style.color = 'var(--sub)';
    }
  }
  if (submitBtn) submitBtn.disabled = bulkAutoRelistItems.length < 2 || missingPrice > 0;
}

function renderBulkAutoRelistItems() {
  const list = document.getElementById('bulkAutoRelistItemsList');
  if (!list) return;

  const floorPercent = parseMoneyValue(document.getElementById('bulkAutoRelistFloorPercent')?.value) ?? 60;
  const discountPercent = parseMoneyValue(document.getElementById('bulkAutoRelistDiscount')?.value) ?? 10;

  list.innerHTML = bulkAutoRelistItems.map(item => {
    const defaultFloor = Number.isFinite(item.price) ? item.price * (floorPercent / 100) : null;
    const floor = item.floorOverride !== '' ? parseMoneyValue(item.floorOverride) : defaultFloor;
    const nextPrice = calculateDiscountedFloorPrice(item.price, discountPercent, floor);
    return `
      <div data-bulk-auto-item="${item.id}" style="display:grid;grid-template-columns:1fr 130px auto;gap:12px;align-items:center;padding:10px 12px;border-bottom:1px solid var(--border);">
        <div style="min-width:0;">
          <div style="font-size:13px;color:var(--text);font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(item.title)}</div>
          <div style="font-size:12px;color:var(--sub);margin-top:4px;">
            ${formatMoneyValue(item.price)} → <strong style="color:#f97316;">${formatMoneyValue(nextPrice)}</strong>
            · Floor ${formatMoneyValue(floor)}
          </div>
        </div>
        <input class="input" type="number" data-bulk-auto-floor="${item.id}" step="0.01" min="0" placeholder="Floor override" value="${escapeHtml(item.floorOverride)}" style="padding:6px 8px;font-size:12px;">
        <button type="button" class="btn" data-bulk-auto-remove="${item.id}" style="padding:6px 9px;font-size:12px;">
          <i class="fas fa-times"></i>
        </button>
      </div>
    `;
  }).join('');

  updateBulkAutoRelistState();
}

function openBulkAutoRelistModal(itemIds) {
  const modal = document.getElementById('bulkAutoRelistModal');
  if (!modal) return;
  bulkAutoRelistItems = getBulkAutoRelistItemData(itemIds);
  document.getElementById('bulkAutoRelistFrequency').value = 'weekly';
  document.getElementById('bulkAutoRelistCustomDays').value = '7';
  document.getElementById('bulkAutoRelistDiscount').value = '10';
  document.getElementById('bulkAutoRelistFloorPercent').value = '60';
  document.getElementById('bulkAutoRelistRunFirstImmediately').checked = false;
  toggleCustomDays(document.getElementById('bulkAutoRelistFrequency'), document.getElementById('bulkAutoRelistCustomDaysWrap'));
  renderBulkAutoRelistItems();
  modal.hidden = false;
  document.body.classList.add('modal-open');
}

document.addEventListener('click', (event) => {
  const closeBtn = event.target.closest('[data-modal-close="bulkAutoRelist"]');
  if (closeBtn) {
    closeBulkAutoRelistModal();
    return;
  }

  const discountBtn = event.target.closest('[data-bulk-auto-discount]');
  if (discountBtn) {
    const input = document.getElementById('bulkAutoRelistDiscount');
    if (input) input.value = discountBtn.dataset.bulkAutoDiscount;
    renderBulkAutoRelistItems();
    return;
  }

  const removeBtn = event.target.closest('[data-bulk-auto-remove]');
  if (removeBtn) {
    const itemId = parseInt(removeBtn.dataset.bulkAutoRemove, 10);
    bulkAutoRelistItems = bulkAutoRelistItems.filter(item => item.id !== itemId);
    const checkbox = document.querySelector(`.item-checkbox[data-item-id="${itemId}"]`);
    if (checkbox) {
      checkbox.checked = false;
      updateBulkActions();
    }
    renderBulkAutoRelistItems();
  }
});

document.addEventListener('change', (event) => {
  const floorInput = event.target.closest('[data-bulk-auto-floor]');
  if (floorInput) {
    const itemId = parseInt(floorInput.dataset.bulkAutoFloor, 10);
    const item = bulkAutoRelistItems.find(entry => entry.id === itemId);
    if (item) item.floorOverride = floorInput.value;
    renderBulkAutoRelistItems();
  }
});

document.getElementById('bulkAutoRelistFrequency')?.addEventListener('change', (event) => {
  toggleCustomDays(event.target, document.getElementById('bulkAutoRelistCustomDaysWrap'));
});
document.getElementById('bulkAutoRelistDiscount')?.addEventListener('input', renderBulkAutoRelistItems);
document.getElementById('bulkAutoRelistFloorPercent')?.addEventListener('input', renderBulkAutoRelistItems);

document.getElementById('bulkAutoRelistForm')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const floorOverrides = {};
  bulkAutoRelistItems.forEach(item => {
    if (item.floorOverride !== '') floorOverrides[String(item.id)] = item.floorOverride;
  });

  const submitBtn = document.getElementById('bulkAutoRelistSubmit');
  const originalHtml = submitBtn?.innerHTML;
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
  }

  try {
    const response = await fetch('/items/bulk_auto_relist_rules', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_ids: bulkAutoRelistItems.map(item => item.id),
        frequency: document.getElementById('bulkAutoRelistFrequency')?.value,
        custom_interval_days: document.getElementById('bulkAutoRelistCustomDays')?.value,
        discount_percent: document.getElementById('bulkAutoRelistDiscount')?.value,
        floor_percent: document.getElementById('bulkAutoRelistFloorPercent')?.value,
        run_first_relist_immediately: document.getElementById('bulkAutoRelistRunFirstImmediately')?.checked || false,
        floor_overrides: floorOverrides
      })
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || 'Failed to schedule items');
    }
    alert(data.message || 'Items scheduled');
    location.reload();
  } catch (error) {
    alert(error.message || 'Failed to schedule items');
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = originalHtml;
    }
  }
});

function closeBulkPriceUpdateModal() {
  const modal = document.getElementById('bulkPriceUpdateModal');
  if (!modal) return;
  modal.hidden = true;
  document.body.classList.remove('modal-open');
}

function getBulkPriceUpdateItemData(itemIds) {
  return itemIds.map(id => {
    const row = document.querySelector(`tr[data-item-row="${id}"]`);
    const price = row ? parseMoneyValue(row.dataset.itemPrice || '') : null;
    const titleCell = row?.querySelector('[data-col="title"]');
    return {
      id,
      title: row?.dataset.itemTitle || titleCell?.textContent?.trim() || `Item ${id}`,
      price,
      hasAutoRelistRule: Boolean(row?.dataset.autoRelistRuleId),
      hasPriceUpdateRule: Boolean(row?.dataset.priceUpdateRuleId),
      floorOverride: ''
    };
  });
}

function updateBulkPriceUpdateState() {
  const countEl = document.getElementById('bulkPriceUpdateCount');
  const validationEl = document.getElementById('bulkPriceUpdateValidation');
  const submitBtn = document.getElementById('bulkPriceUpdateSubmit');
  const missingPrice = bulkPriceUpdateItems.filter(item => !Number.isFinite(item.price)).length;
  const existingPriceRules = bulkPriceUpdateItems.filter(item => item.hasPriceUpdateRule).length;
  const conflictingAutoRules = bulkPriceUpdateItems.filter(item => item.hasAutoRelistRule).length;

  if (countEl) countEl.textContent = bulkPriceUpdateItems.length;
  if (validationEl) {
    if (bulkPriceUpdateItems.length < 2) {
      validationEl.textContent = 'Keep at least 2 items to schedule.';
      validationEl.style.color = '#fca5a5';
    } else if (missingPrice > 0) {
      validationEl.textContent = `${missingPrice} item(s) need a current price.`;
      validationEl.style.color = '#fca5a5';
    } else if (existingPriceRules || conflictingAutoRules) {
      const parts = [];
      if (existingPriceRules) parts.push(`${existingPriceRules} existing price schedule(s) will be updated`);
      if (conflictingAutoRules) parts.push(`${conflictingAutoRules} relist schedule(s) will be stopped`);
      validationEl.textContent = parts.join('; ') + '.';
      validationEl.style.color = '#eab308';
    } else {
      validationEl.textContent = `${bulkPriceUpdateItems.length} item(s) ready.`;
      validationEl.style.color = 'var(--sub)';
    }
  }
  if (submitBtn) submitBtn.disabled = bulkPriceUpdateItems.length < 2 || missingPrice > 0;
}

function renderBulkPriceUpdateItems() {
  const list = document.getElementById('bulkPriceUpdateItemsList');
  if (!list) return;

  const floorPercent = parseMoneyValue(document.getElementById('bulkPriceUpdateFloorPercent')?.value) ?? 60;
  const discountPercent = parseMoneyValue(document.getElementById('bulkPriceUpdateDiscount')?.value) ?? 10;

  list.innerHTML = bulkPriceUpdateItems.map(item => {
    const defaultFloor = Number.isFinite(item.price) ? item.price * (floorPercent / 100) : null;
    const floor = item.floorOverride !== '' ? parseMoneyValue(item.floorOverride) : defaultFloor;
    const nextPrice = calculateDiscountedFloorPrice(item.price, discountPercent, floor);
    const scheduleNotes = [
      item.hasPriceUpdateRule ? 'Existing price schedule will be updated' : '',
      item.hasAutoRelistRule ? 'Update & Relist schedule will be stopped' : ''
    ].filter(Boolean).join(' · ');
    return `
      <div data-bulk-price-item="${item.id}" style="display:grid;grid-template-columns:1fr 130px auto;gap:12px;align-items:center;padding:10px 12px;border-bottom:1px solid var(--border);">
        <div style="min-width:0;">
          <div style="font-size:13px;color:var(--text);font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(item.title)}</div>
          <div style="font-size:12px;color:var(--sub);margin-top:4px;">
            ${formatMoneyValue(item.price)} → <strong style="color:#eab308;">${formatMoneyValue(nextPrice)}</strong>
            · Floor ${formatMoneyValue(floor)}
          </div>
          ${scheduleNotes ? `<div style="font-size:11px;color:#eab308;margin-top:3px;">${escapeHtml(scheduleNotes)}</div>` : ''}
        </div>
        <input class="input" type="number" data-bulk-price-floor="${item.id}" step="0.01" min="0" placeholder="Floor override" value="${escapeHtml(item.floorOverride)}" style="padding:6px 8px;font-size:12px;">
        <button type="button" class="btn" data-bulk-price-remove="${item.id}" style="padding:6px 9px;font-size:12px;">
          <i class="fas fa-times"></i>
        </button>
      </div>
    `;
  }).join('');

  updateBulkPriceUpdateState();
}

function openBulkPriceUpdateModal(itemIds) {
  const modal = document.getElementById('bulkPriceUpdateModal');
  if (!modal) return;
  bulkPriceUpdateItems = getBulkPriceUpdateItemData(itemIds);
  document.getElementById('bulkPriceUpdateFrequency').value = 'weekly';
  document.getElementById('bulkPriceUpdateCustomDays').value = '7';
  document.getElementById('bulkPriceUpdateDiscount').value = '10';
  document.getElementById('bulkPriceUpdateFloorPercent').value = '60';
  document.getElementById('bulkPriceUpdateRunFirstImmediately').checked = false;
  toggleCustomDays(document.getElementById('bulkPriceUpdateFrequency'), document.getElementById('bulkPriceUpdateCustomDaysWrap'));
  renderBulkPriceUpdateItems();
  modal.hidden = false;
  document.body.classList.add('modal-open');
}

document.addEventListener('click', (event) => {
  const closeBtn = event.target.closest('[data-modal-close="bulkPriceUpdate"]');
  if (closeBtn) {
    closeBulkPriceUpdateModal();
    return;
  }

  const discountBtn = event.target.closest('[data-bulk-price-discount]');
  if (discountBtn) {
    const input = document.getElementById('bulkPriceUpdateDiscount');
    if (input) input.value = discountBtn.dataset.bulkPriceDiscount;
    renderBulkPriceUpdateItems();
    return;
  }

  const removeBtn = event.target.closest('[data-bulk-price-remove]');
  if (removeBtn) {
    const itemId = parseInt(removeBtn.dataset.bulkPriceRemove, 10);
    bulkPriceUpdateItems = bulkPriceUpdateItems.filter(item => item.id !== itemId);
    const checkbox = document.querySelector(`.item-checkbox[data-item-id="${itemId}"]`);
    if (checkbox) {
      checkbox.checked = false;
      updateBulkActions();
    }
    renderBulkPriceUpdateItems();
  }
});

document.addEventListener('change', (event) => {
  const floorInput = event.target.closest('[data-bulk-price-floor]');
  if (floorInput) {
    const itemId = parseInt(floorInput.dataset.bulkPriceFloor, 10);
    const item = bulkPriceUpdateItems.find(entry => entry.id === itemId);
    if (item) item.floorOverride = floorInput.value;
    renderBulkPriceUpdateItems();
  }
});

document.getElementById('bulkPriceUpdateFrequency')?.addEventListener('change', (event) => {
  toggleCustomDays(event.target, document.getElementById('bulkPriceUpdateCustomDaysWrap'));
});
document.getElementById('bulkPriceUpdateDiscount')?.addEventListener('input', renderBulkPriceUpdateItems);
document.getElementById('bulkPriceUpdateFloorPercent')?.addEventListener('input', renderBulkPriceUpdateItems);

document.getElementById('bulkPriceUpdateForm')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const floorOverrides = {};
  bulkPriceUpdateItems.forEach(item => {
    if (item.floorOverride !== '') floorOverrides[String(item.id)] = item.floorOverride;
  });

  const submitBtn = document.getElementById('bulkPriceUpdateSubmit');
  const originalHtml = submitBtn?.innerHTML;
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
  }

  try {
    const response = await fetch('/items/bulk_price_update_rules', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_ids: bulkPriceUpdateItems.map(item => item.id),
        frequency: document.getElementById('bulkPriceUpdateFrequency')?.value,
        custom_interval_days: document.getElementById('bulkPriceUpdateCustomDays')?.value,
        discount_percent: document.getElementById('bulkPriceUpdateDiscount')?.value,
        floor_percent: document.getElementById('bulkPriceUpdateFloorPercent')?.value,
        run_first_relist_immediately: document.getElementById('bulkPriceUpdateRunFirstImmediately')?.checked || false,
        floor_overrides: floorOverrides
      })
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || 'Failed to schedule price updates');
    }
    alert(data.message || 'Price updates scheduled');
    location.reload();
  } catch (error) {
    alert(error.message || 'Failed to schedule price updates');
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = originalHtml;
    }
  }
});

window.closeAutoRelistScheduleModal = closeAutoRelistScheduleModal;
window.closeBulkAutoRelistModal = closeBulkAutoRelistModal;
window.closePriceUpdateModal = closePriceUpdateModal;
window.closeBulkPriceUpdateModal = closeBulkPriceUpdateModal;

if (bulkEditOpenBtn) {
  bulkEditOpenBtn.addEventListener('click', () => {
    const itemIds = getSelectedItemIds();
    if (itemIds.length === 0) {
      alert('No items selected');
      return;
    }
    openBulkEditModal(itemIds);
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
    let itemIds = JSON.parse(modal.dataset.itemIds || '[]');
    if (!itemIds.length) {
      itemIds = getSelectedItemIds();
    }

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

// ==================== BULK EDIT ====================

function openBulkEditModal(itemIds) {
  const modal = document.getElementById('bulkEditModal');
  if (!modal) {
    console.error('Bulk edit modal not found');
    return;
  }

  modal.dataset.itemIds = JSON.stringify(itemIds);
  modal.dataset.submitMode = 'custom';

  const countEl = document.getElementById('bulkEditCount');
  if (countEl) {
    countEl.textContent = itemIds.length;
  }

  const form = document.getElementById('bulkEditForm');
  if (form) form.reset();

  setBulkEditEnabled(false);
  updateBulkEditLocationPreview();
  setupBulkEditSupplierAutocomplete();
  updateBulkEditSelectedList(itemIds);

  modal.hidden = false;
  document.body.classList.add('modal-open');
}

function closeBulkEditModal() {
  const modal = document.getElementById('bulkEditModal');
  if (modal) {
    modal.hidden = true;
    document.body.classList.remove('modal-open');
  }
}

function setBulkEditEnabled(enabled) {
  const supplierInput = document.getElementById('bulkEditSupplier');
  const costInput = document.getElementById('bulkEditCost');
  const locationInputs = document.querySelectorAll('.bulk-edit-location');
  const syncToggle = document.getElementById('bulkEditSyncToEbay');

  if (supplierInput) supplierInput.disabled = !enabled;
  if (costInput) costInput.disabled = !enabled;
  locationInputs.forEach(input => {
    input.disabled = !enabled;
  });
  if (syncToggle) syncToggle.disabled = !enabled;
}

function updateBulkEditLocationPreview() {
  const preview = document.getElementById('bulkEditLocationPreview');
  if (!preview) return;

  const A = document.querySelector('.bulk-edit-location[name="A"]')?.value || '';
  const B = document.querySelector('.bulk-edit-location[name="B"]')?.value || '';
  const S = document.querySelector('.bulk-edit-location[name="S"]')?.value || '';
  const C = document.querySelector('.bulk-edit-location[name="C"]')?.value || '';

  const parts = [];
  if (A) parts.push(`A${A}`);
  if (B) parts.push(`B${B}`);
  if (S) parts.push(`S${S}`);
  if (C) parts.push(`C${C}`);

  preview.textContent = parts.length ? parts.join('') : '—';
}

function applyBulkEditPreset(preset) {
  const supplierToggle = document.getElementById('bulkEditApplySupplier');
  const costToggle = document.getElementById('bulkEditApplyCost');
  const locationToggle = document.getElementById('bulkEditApplyLocation');
  const syncToggle = document.getElementById('bulkEditSyncToEbay');

  if (!supplierToggle || !costToggle || !locationToggle) return;

  supplierToggle.checked = preset === 'supplier_cost' || preset === 'all';
  costToggle.checked = preset === 'supplier_cost' || preset === 'all';
  locationToggle.checked = preset === 'location_sync' || preset === 'all';

  if (syncToggle) {
    syncToggle.checked = preset === 'location_sync' || preset === 'all';
    syncToggle.disabled = !locationToggle.checked;
  }

  const supplierInput = document.getElementById('bulkEditSupplier');
  const costInput = document.getElementById('bulkEditCost');
  const locationInputs = document.querySelectorAll('.bulk-edit-location');

  if (supplierInput) supplierInput.disabled = !supplierToggle.checked;
  if (costInput) costInput.disabled = !costToggle.checked;
  locationInputs.forEach(input => {
    input.disabled = !locationToggle.checked;
  });

  updateBulkEditLocationPreview();
}

function setupBulkEditToggles() {
  const supplierToggle = document.getElementById('bulkEditApplySupplier');
  const costToggle = document.getElementById('bulkEditApplyCost');
  const locationToggle = document.getElementById('bulkEditApplyLocation');
  const supplierInput = document.getElementById('bulkEditSupplier');
  const costInput = document.getElementById('bulkEditCost');
  const locationInputs = document.querySelectorAll('.bulk-edit-location');
  const syncToggle = document.getElementById('bulkEditSyncToEbay');

  if (supplierToggle && supplierInput) {
    supplierToggle.addEventListener('change', () => {
      supplierInput.disabled = !supplierToggle.checked;
    });
  }

  if (costToggle && costInput) {
    costToggle.addEventListener('change', () => {
      costInput.disabled = !costToggle.checked;
    });
  }

  if (locationToggle) {
    locationToggle.addEventListener('change', () => {
      const enabled = locationToggle.checked;
      locationInputs.forEach(input => {
        input.disabled = !enabled;
      });
      if (syncToggle) {
        syncToggle.disabled = !enabled;
        if (!enabled) syncToggle.checked = false;
      }
      updateBulkEditLocationPreview();
    });
  }

  locationInputs.forEach(input => {
    input.addEventListener('change', updateBulkEditLocationPreview);
  });
}

function setupBulkEditSupplierAutocomplete() {
  const supplierInput = document.getElementById('bulkEditSupplier');
  const list = document.getElementById('bulkEditSupplierList');
  const form = document.getElementById('bulkEditForm');
  const container = document.querySelector('.bulk-edit-supplier');

  if (supplierInput && list && form && container) {
    setupSupplierInlineAutocomplete(supplierInput, list, form, container);
  }
}

function updateBulkEditSelectedList(itemIds) {
  const listWrap = document.getElementById('bulkEditSelectedList');
  const listContainer = listWrap ? listWrap.querySelector('div') : null;
  const toggleBtn = document.getElementById('bulkEditToggleItems');

  if (!listWrap || !listContainer || !toggleBtn) return;

  const titles = itemIds.map(id => {
    const row = document.querySelector(`tr[data-item-row="${id}"]`);
    const titleCell = row ? row.querySelector('td:nth-child(3)') : null;
    return titleCell ? titleCell.textContent.trim() : `Item ${id}`;
  });

  listContainer.innerHTML = titles.map(title => `<div style="padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.04);">${title}</div>`).join('');

  listWrap.style.display = 'none';
  toggleBtn.textContent = 'Show items';
}

const bulkEditModal = document.getElementById('bulkEditModal');
if (bulkEditModal) {
  bulkEditModal.querySelectorAll('[data-modal-close="bulkEdit"]').forEach(btn => {
    btn.addEventListener('click', closeBulkEditModal);
  });

  bulkEditModal.querySelectorAll('[data-bulk-preset]').forEach(btn => {
    btn.addEventListener('click', () => {
      applyBulkEditPreset(btn.getAttribute('data-bulk-preset'));
    });
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !bulkEditModal.hidden) {
      closeBulkEditModal();
    }
  });
}

const bulkEditToggleBtn = document.getElementById('bulkEditToggleItems');
if (bulkEditToggleBtn) {
  bulkEditToggleBtn.addEventListener('click', () => {
    const listWrap = document.getElementById('bulkEditSelectedList');
    if (!listWrap) return;
    const isHidden = listWrap.style.display === 'none' || listWrap.style.display === '';
    listWrap.style.display = isHidden ? 'block' : 'none';
    bulkEditToggleBtn.textContent = isHidden ? 'Hide items' : 'Show items';
  });
}

const bulkEditForm = document.getElementById('bulkEditForm');
if (bulkEditForm) {
  setupBulkEditToggles();

  bulkEditForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    await submitBulkEdit('custom');
  });
}

async function submitBulkEdit(mode) {
  const modal = document.getElementById('bulkEditModal');
  let itemIds = JSON.parse(modal?.dataset.itemIds || '[]');
  if (!itemIds.length) {
    itemIds = getSelectedItemIds();
  }

  if (itemIds.length === 0) {
    alert('No items selected');
    return;
  }

  const applySupplierToggle = document.getElementById('bulkEditApplySupplier')?.checked;
  const applyCostToggle = document.getElementById('bulkEditApplyCost')?.checked;
  const applyLocationToggle = document.getElementById('bulkEditApplyLocation')?.checked;

  let applySupplier = applySupplierToggle;
  let applyCost = applyCostToggle;
  let applyLocation = applyLocationToggle;

  if (mode === 'supplier_cost') {
    applySupplier = true;
    applyCost = true;
    applyLocation = false;
  }

  if (mode === 'location_sync') {
    applySupplier = false;
    applyCost = false;
    applyLocation = true;
  }

  if (!applySupplier && !applyCost && !applyLocation) {
    alert('Select at least one field to update.');
    return;
  }

  const formData = new FormData(document.getElementById('bulkEditForm'));
  const payload = {
    item_ids: itemIds,
    apply_supplier: !!applySupplier,
    apply_cost: !!applyCost,
    apply_location: !!applyLocation,
    supplier: applySupplier ? (formData.get('supplier') || '').trim() : null,
    item_cost: applyCost ? formData.get('item_cost') : null,
    A: applyLocation ? (formData.get('A') || null) : null,
    B: applyLocation ? (formData.get('B') || null) : null,
    S: applyLocation ? (formData.get('S') || null) : null,
    C: applyLocation ? (formData.get('C') || null) : null,
    sync_to_ebay: applyLocation && (mode === 'location_sync' || formData.get('sync_to_ebay') === 'on')
  };

  const submitBtn = document.querySelector('button[form="bulkEditForm"]');
  const originalText = submitBtn ? submitBtn.innerHTML : '';
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing...';
  }

  try {
    const response = await fetch('/items/bulk_update_fields', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const data = await response.json();

    if (data.ok) {
      alert(data.message || 'Items updated successfully');
      closeBulkEditModal();
      location.reload();
    } else {
      alert('Error: ' + (data.error || 'Failed to update items'));
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = originalText;
      }
    }
  } catch (error) {
    console.error('Bulk update error:', error);
    alert('Failed to update items');
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = originalText;
    }
  }
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

  // Retired items purge buttons
  document.querySelectorAll('.retired-purge-btn').forEach(btn => {
    if (!btn.dataset.initialized) {
      btn.addEventListener('click', async () => {
        const retiredId = parseInt(btn.dataset.retiredId, 10);
        if (!Number.isFinite(retiredId)) {
          alert('Invalid item');
          return;
        }
        if (!confirm('This will permanently end the eBay listing. This is irreversible. Continue?')) {
          return;
        }

        try {
          const response = await fetch('/retired_items/bulk_purge', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ retired_item_ids: [retiredId] })
          });
          const data = await response.json();
          if (data.ok) {
            alert(data.message);
            location.reload();
          } else {
            alert('Error: ' + data.error);
          }
        } catch (error) {
          console.error('Retired purge error:', error);
          alert('Failed to purge item');
        }
      });
      btn.dataset.initialized = 'true';
    }
  });

  // Retired items archive/restore buttons
  document.querySelectorAll('.retired-archive-btn').forEach(btn => {
    if (!btn.dataset.initialized) {
      btn.addEventListener('click', async () => {
        const retiredId = parseInt(btn.dataset.retiredId, 10);
        const archive = btn.dataset.archive !== 'false';
        if (!Number.isFinite(retiredId)) {
          alert('Invalid item');
          return;
        }
        if (!confirm(archive ? 'Archive this retired item?' : 'Restore this retired item?')) {
          return;
        }

        try {
          const response = await fetch('/retired_items/bulk_archive', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ retired_item_ids: [retiredId], archive })
          });
          const data = await response.json();
          if (data.ok) {
            alert(data.message || (archive ? 'Archived' : 'Restored'));
            location.reload();
          } else {
            alert('Error: ' + (data.error || 'Failed to update item'));
          }
        } catch (error) {
          console.error('Retired archive error:', error);
          alert(archive ? 'Failed to archive item' : 'Failed to restore item');
        }
      });
      btn.dataset.initialized = 'true';
    }
  });

  // Retired items delete buttons
  document.querySelectorAll('.retired-delete-btn').forEach(btn => {
    if (!btn.dataset.initialized) {
      btn.addEventListener('click', async () => {
        const retiredId = parseInt(btn.dataset.retiredId, 10);
        if (!Number.isFinite(retiredId)) {
          alert('Invalid item');
          return;
        }
        if (!confirm('Remove this item from Retirements?')) {
          return;
        }

        try {
          const response = await fetch('/retired_items/bulk_delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ retired_item_ids: [retiredId] })
          });
          const data = await response.json();
          if (data.ok) {
            alert(data.message || 'Removed');
            location.reload();
          } else {
            alert('Error: ' + (data.error || 'Failed to remove'));
          }
        } catch (error) {
          console.error('Retired delete error:', error);
          alert('Failed to remove item');
        }
      });
      btn.dataset.initialized = 'true';
    }
  });

  // Send single item to Retirements
  document.querySelectorAll('.retire-btn').forEach(btn => {
    if (!btn.dataset.initialized) {
      btn.addEventListener('click', async () => {
        const itemId = parseInt(btn.dataset.itemId, 10);
        if (!Number.isFinite(itemId)) {
          alert('Invalid item');
          return;
        }
        if (!confirm('Copy this item to Retirements?')) {
          return;
        }
        try {
          const response = await fetch('/items/bulk_retire', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ item_ids: [itemId] })
          });
          const data = await response.json();
          if (data.ok) {
            alert(data.message || 'Added to Retirements');
            location.reload();
          } else {
            alert('Error: ' + (data.error || 'Failed to add to Retirements'));
          }
        } catch (error) {
          console.error('Retirements error:', error);
          alert('Failed to add to Retirements');
        }
      });
      btn.dataset.initialized = 'true';
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
  const customEndpoint = container.dataset.endpoint;

  if ((!itemId && !customEndpoint) || !field) {
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

    if (customEndpoint) {
      response = await fetch(customEndpoint, {
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
    } else if (isSoldView && isItemCostField) {
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
      updateCostDisplay(container, data.item_cost, data.cost_history_added);
      if (isSoldView && typeof data.net_profit !== 'undefined') {
        updateNetProfitDisplay(container, data.net_profit);
      }
    } else if (data.field === 'location') {
      updateLocationDisplay(container, data.location_code, data.A, data.B, data.S, data.C);
    } else if (data.field === 'note') {
      updateNoteDisplay(container, data.note);
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

function updateCostDisplay(container, costValue, costHistoryAdded = false) {
  const display = container.querySelector('.inline-edit__display');
  const valueSpan = display ? display.querySelector('.inline-edit__value') : null;
  const placeholder = display ? display.querySelector('.inline-edit__placeholder') : null;
  const row = container.closest('tr[data-item-row]');
  const existingHistoryBtn = display ? display.querySelector('.cost-history-btn') : null;

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
    const currentValueSpan = display ? display.querySelector('.inline-edit__value') : null;
    if (currentValueSpan && (costHistoryAdded || existingHistoryBtn)) {
      const btn = existingHistoryBtn || document.createElement('button');
      btn.type = 'button';
      btn.className = 'cost-history-btn';
      btn.dataset.itemId = row ? row.dataset.itemId : '';
      btn.setAttribute('title', 'Cost history');
      btn.setAttribute('data-inline-ignore', '');
      btn.style.marginLeft = '6px';
      btn.style.border = 'none';
      btn.style.background = 'none';
      btn.style.color = 'var(--sub)';
      btn.style.cursor = 'pointer';
      if (!btn.innerHTML) {
        btn.innerHTML = '<i class="fas fa-clock"></i>';
      }
      currentValueSpan.appendChild(btn);
    }
    if (row) {
      row.dataset.itemCost = parseFloat(costValue).toFixed(2);
    }
  } else {
    if (valueSpan) {
      const newPlaceholder = document.createElement('span');
      newPlaceholder.className = 'inline-edit__placeholder';
      newPlaceholder.textContent = 'Add cost';
      valueSpan.replaceWith(newPlaceholder);
    }
    if (row) {
      row.dataset.itemCost = '';
    }
  }

  if (row) {
    updateRoiDisplay(row);
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

function updateNoteDisplay(container, noteValue) {
  const display = container.querySelector('.inline-edit__display');
  if (!display) return;

  const valueSpan = display.querySelector('.inline-edit__value');
  const placeholder = display.querySelector('.inline-edit__placeholder');
  const trimmed = (noteValue || '').trim();

  if (trimmed) {
    if (valueSpan) {
      valueSpan.textContent = trimmed;
      valueSpan.style.display = '';
    } else if (placeholder) {
      const newValueSpan = document.createElement('span');
      newValueSpan.className = 'inline-edit__value tag';
      newValueSpan.textContent = trimmed;
      placeholder.replaceWith(newValueSpan);
    }
  } else {
    if (valueSpan) {
      const newPlaceholder = document.createElement('span');
      newPlaceholder.className = 'inline-edit__placeholder';
      newPlaceholder.textContent = 'Add note';
      valueSpan.replaceWith(newPlaceholder);
    }
  }
}

function updateNetProfitDisplay(container, netProfitValue) {
  const row = container.closest('tr[data-item-row]');
  if (!row) return;
  const netCell = row.querySelector('td[data-col="net_profit"]');
  if (!netCell) return;
  const value = parseFloat(netProfitValue);
  if (!isFinite(value)) return;
  netCell.textContent = `$${value.toFixed(2)}`;
  netCell.classList.remove('positive', 'negative');
  netCell.classList.add(value >= 0 ? 'positive' : 'negative');
}

function updateRoiDisplay(row) {
  const roiCell = row.querySelector('.roi-cell');
  if (!roiCell) {
    return;
  }
  const roiValue = roiCell.querySelector('.roi-value') || roiCell;
  const priceRaw = row.dataset.itemPrice;
  const costRaw = row.dataset.itemCost;
  const price = priceRaw ? parseFloat(priceRaw) : NaN;
  const cost = costRaw ? parseFloat(costRaw) : NaN;

  if (!isFinite(price) || !isFinite(cost) || cost <= 0) {
    roiValue.textContent = '—';
    roiValue.className = 'roi-value';
    return;
  }

  const roi = Math.round(((price - cost) / cost) * 100);
  roiValue.textContent = `ROI ${roi}%`;
  roiValue.className = 'tag roi-value';
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
  const componentState = {
    A: { enabled: locationDisplay.dataset.enableA === '1', label: locationDisplay.dataset.labelA || 'A', value: locationDisplay.dataset.locationA || '' },
    B: { enabled: locationDisplay.dataset.enableB === '1', label: locationDisplay.dataset.labelB || 'B', value: locationDisplay.dataset.locationB || '' },
    S: { enabled: locationDisplay.dataset.enableS === '1', label: locationDisplay.dataset.labelS || 'S', value: locationDisplay.dataset.locationS || '' },
    C: { enabled: locationDisplay.dataset.enableC === '1', label: locationDisplay.dataset.labelC || 'C', value: locationDisplay.dataset.locationC || '' },
  };

  let firstInput = null;
  const existingInputs = locationModalFields.querySelectorAll('[data-component]');
  if (existingInputs.length > 0) {
    existingInputs.forEach(input => {
      const key = input.dataset.component;
      const state = componentState[key];
      if (!state) {
        return;
      }
      input.value = state.value;
      if (!firstInput) {
        firstInput = input;
      }
    });
  } else {
    locationModalFields.innerHTML = '';
    Object.keys(componentState).forEach(key => {
      const component = componentState[key];
      if (!component.enabled) {
        return;
      }
      const wrapper = document.createElement('label');
      wrapper.textContent = component.label;
      wrapper.className = 'location-modal__label';

      const input = document.createElement('input');
      input.type = 'text';
      input.name = key;
      input.value = component.value;
      input.autocomplete = 'off';
      input.className = 'input';
      input.dataset.component = key;
      input.setAttribute('data-component', key);
      wrapper.appendChild(input);
      locationModalFields.appendChild(wrapper);
      if (!firstInput) {
        firstInput = input;
      }
    });
  }

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

  let firstInput = null;
  const existingInputs = locationModalFields.querySelectorAll('[data-component]');
  if (existingInputs.length > 0) {
    existingInputs.forEach(input => {
      const key = input.dataset.component;
      if (!key) {
        return;
      }
      const nextValue = components[key] || input.value;
      input.value = nextValue;
      if (!firstInput) {
        firstInput = input;
      }
      console.log(`[QR Location] Field ${key} = ${nextValue} (scanned: ${components[key] || 'N/A'})`);
    });
  } else {
    // Recreate fields with scanned values
    locationModalFields.innerHTML = '';
    locationModalContext.fields.forEach(field => {
      const wrapper = document.createElement('label');
      wrapper.textContent = field.label;
      wrapper.className = 'location-modal__label';

      const input = document.createElement('input');
      input.type = 'text';
      input.name = field.key;
      input.autocomplete = 'off';
      input.className = 'input';
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
  }

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
