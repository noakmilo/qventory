/**
 * Receipt Item Association JavaScript
 *
 * Features:
 * - Autocomplete for inventory item selection
 * - Associate receipt items with inventory or expenses
 * - Remove associations
 * - Real-time UI updates
 */

// Parse inventory items from hidden JSON data
const inventoryItemsData = JSON.parse(
    document.getElementById('inventory-items-data')?.textContent || '[]'
);

// Global state for selected items
const selectedItems = new Map(); // receiptItemId -> inventoryItemId

/**
 * Initialize autocomplete for all inventory search inputs
 */
function initializeAutocomplete() {
    const autocompleteInputs = document.querySelectorAll('.inventory-autocomplete');

    autocompleteInputs.forEach(input => {
        const receiptItemId = input.dataset.receiptItemId;
        const associateBtn = document.querySelector(
            `.associate-inventory-btn[data-receipt-item-id="${receiptItemId}"]`
        );

        // Create autocomplete dropdown container
        const dropdown = document.createElement('div');
        dropdown.className = 'autocomplete-dropdown';
        dropdown.style.cssText = `
            position: absolute;
            z-index: 1000;
            background: white;
            border: 1px solid #ddd;
            border-radius: 4px;
            max-height: 300px;
            overflow-y: auto;
            display: none;
            width: 100%;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        `;
        input.parentElement.style.position = 'relative';
        input.parentElement.appendChild(dropdown);

        // Input event handler
        input.addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase().trim();

            if (query.length < 2) {
                dropdown.style.display = 'none';
                dropdown.innerHTML = '';
                associateBtn.disabled = true;
                selectedItems.delete(receiptItemId);
                return;
            }

            // Filter inventory items
            const matches = inventoryItemsData.filter(item => {
                return (
                    item.title.toLowerCase().includes(query) ||
                    item.sku.toLowerCase().includes(query) ||
                    (item.location_code && item.location_code.toLowerCase().includes(query))
                );
            });

            // Render dropdown
            if (matches.length > 0) {
                dropdown.innerHTML = matches.slice(0, 10).map(item => `
                    <div class="autocomplete-item" data-item-id="${item.id}" style="
                        padding: 8px 12px;
                        cursor: pointer;
                        border-bottom: 1px solid #eee;
                    ">
                        <div style="font-weight: 500;">${escapeHtml(item.title)}</div>
                        <div style="font-size: 0.85em; color: #666;">
                            SKU: ${escapeHtml(item.sku)}
                            ${item.location_code ? ` • Location: ${escapeHtml(item.location_code)}` : ''}
                            ${item.item_cost ? ` • Cost: $${parseFloat(item.item_cost).toFixed(2)}` : ''}
                        </div>
                    </div>
                `).join('');

                dropdown.style.display = 'block';

                // Add click handlers to items
                dropdown.querySelectorAll('.autocomplete-item').forEach(itemEl => {
                    itemEl.addEventListener('mouseenter', function() {
                        this.style.backgroundColor = '#f0f0f0';
                    });
                    itemEl.addEventListener('mouseleave', function() {
                        this.style.backgroundColor = 'white';
                    });
                    itemEl.addEventListener('click', function() {
                        const selectedItemId = parseInt(this.dataset.itemId);
                        const selectedItem = inventoryItemsData.find(i => i.id === selectedItemId);

                        if (selectedItem) {
                            input.value = selectedItem.title;
                            selectedItems.set(receiptItemId, selectedItemId);
                            associateBtn.disabled = false;
                            dropdown.style.display = 'none';
                        }
                    });
                });
            } else {
                dropdown.innerHTML = '<div style="padding: 12px; color: #999; text-align: center;">No items found</div>';
                dropdown.style.display = 'block';
                associateBtn.disabled = true;
                selectedItems.delete(receiptItemId);
            }
        });

        // Close dropdown on outside click
        document.addEventListener('click', (e) => {
            if (!input.contains(e.target) && !dropdown.contains(e.target)) {
                dropdown.style.display = 'none';
            }
        });
    });
}

/**
 * Initialize association button handlers
 */
function initializeAssociationButtons() {
    // Associate with inventory
    document.querySelectorAll('.associate-inventory-btn').forEach(btn => {
        btn.addEventListener('click', async function() {
            const receiptItemId = this.dataset.receiptItemId;
            const inventoryItemId = selectedItems.get(receiptItemId);

            if (!inventoryItemId) {
                alert('Please select an inventory item first');
                return;
            }

            const updateCostCheckbox = document.getElementById(`update-cost-${receiptItemId}`);
            const updateCost = updateCostCheckbox ? updateCostCheckbox.checked : false;

            this.disabled = true;
            this.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Linking...';

            try {
                const response = await fetch(`/receipts/${getReceiptId()}/associate`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                    },
                    body: new URLSearchParams({
                        receipt_item_id: parseInt(receiptItemId),
                        association_type: 'inventory',
                        inventory_item_id: inventoryItemId,
                        update_cost: updateCost
                    })
                });

                const data = await response.json();

                if (data.success) {
                    // Reload page to show updated associations
                    window.location.reload();
                } else {
                    alert('Association failed: ' + (data.error || 'Unknown error'));
                    this.disabled = false;
                    this.innerHTML = 'Link';
                }
            } catch (error) {
                console.error('Error:', error);
                alert('Association failed. Please try again.');
                this.disabled = false;
                this.innerHTML = 'Link';
            }
        });
    });

    // Record as expense - open modal instead of prompts
    document.querySelectorAll('.record-expense-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const receiptItemId = this.dataset.receiptItemId;
            const description = this.dataset.description;
            const amount = parseFloat(this.dataset.amount);

            // Open the expense modal (defined in view.html)
            if (typeof openExpenseModal === 'function') {
                openExpenseModal(receiptItemId, description, amount);
            } else {
                console.error('openExpenseModal function not found');
                alert('Error: Expense modal not available');
            }
        });
    });

    // Remove association
    document.querySelectorAll('.remove-association-btn').forEach(btn => {
        btn.addEventListener('click', async function() {
            const receiptItemId = parseInt(this.dataset.receiptItemId);
            const hasExpense = this.dataset.hasExpense === 'true';

            let deleteExpense = false;
            if (hasExpense) {
                deleteExpense = confirm(
                    'This item is linked to an expense. Do you want to delete the expense as well?\n\n' +
                    'Click OK to delete the expense, or Cancel to keep it.'
                );
            }

            if (!confirm('Remove this association?')) {
                return;
            }

            this.disabled = true;
            this.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Removing...';

            try {
                const response = await fetch(`/receipts/${getReceiptId()}/disassociate`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                    },
                    body: new URLSearchParams({
                        receipt_item_id: receiptItemId,
                        delete_expense: deleteExpense
                    })
                });

                const data = await response.json();

                if (data.success) {
                    window.location.reload();
                } else {
                    alert('Remove failed: ' + (data.error || 'Unknown error'));
                    this.disabled = false;
                    this.innerHTML = 'Remove Association';
                }
            } catch (error) {
                console.error('Error:', error);
                alert('Remove failed. Please try again.');
                this.disabled = false;
                this.innerHTML = 'Remove Association';
            }
        });
    });
}

/**
 * Get receipt ID from URL
 */
function getReceiptId() {
    const pathParts = window.location.pathname.split('/');
    return pathParts[pathParts.length - 1];
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(unsafe) {
    return unsafe
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

/**
 * Initialize all functionality
 */
document.addEventListener('DOMContentLoaded', function() {
    initializeAutocomplete();
    initializeAssociationButtons();
});
