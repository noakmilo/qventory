/**
 * Qventory Profit Calculator
 * Native profit calculation module with autocomplete and history
 */

const ProfitCalc = (function() {
  'use strict';

  // eBay fee structures
  const standardFees = {
    "Electronics": 12.9,
    "Clothing, Shoes & Accessories": 13.25,
    "Toys & Hobbies": 12.9,
    "Collectibles": 12.9,
    "Books, Movies & Music": 14.95,
    "Video Games & Consoles": 12.9,
    "Home & Garden": 12.9,
    "Tools & Equipment": 12.9,
    "Sports": 12.9,
    "Health & Beauty": 12.9,
    "Business & Industrial": 12.9,
    "Pet Supplies": 12.9
  };

  const storeFees = {
    "Electronics": 11.7,
    "Clothing, Shoes & Accessories": 11.5,
    "Toys & Hobbies": 11.5,
    "Collectibles": 11.5,
    "Books, Movies & Music": 12.0,
    "Video Games & Consoles": 11.5,
    "Home & Garden": 11.5,
    "Tools & Equipment": 11.5,
    "Sports": 11.5,
    "Health & Beauty": 11.5,
    "Business & Industrial": 11.5,
    "Pet Supplies": 11.5
  };

  // Depop fee structure
  const depopPaymentFeeRate = 3.3;
  const depopPaymentFixedFee = 0.45;
  const depopBoostFeeRate = 8;

  // DOM elements
  let elements = {};

  // Autocomplete state
  let autocompleteTimeout = null;
  let currentItemData = null;

  function initElements() {
    elements = {
      marketplace: document.getElementById('marketplace'),
      itemName: document.getElementById('itemName'),
      buyPrice: document.getElementById('buyPrice'),
      resalePrice: document.getElementById('resalePrice'),
      fees: document.getElementById('fees'),
      feesLabel: document.getElementById('feesLabel'),
      shipping: document.getElementById('shipping'),

      // eBay specific
      hasStore: document.getElementById('hasStore'),
      ebayCategory: document.getElementById('ebayCategory'),
      topRated: document.getElementById('topRated'),
      fixedFee: document.getElementById('fixedFee'),
      ebaySection: document.getElementById('ebay-section'),

      // Depop specific
      depopCategory: document.getElementById('depopCategory'),
      depopBoost: document.getElementById('depopBoost'),
      depopShipping: document.getElementById('depopShipping'),
      depopSection: document.getElementById('depop-section'),

      // Results & History
      result: document.getElementById('result'),
      history: document.getElementById('history'),

      // Autocomplete
      autocompleteList: document.getElementById('autocompleteList')
    };
  }

  function switchMarketplace() {
    const marketplace = elements.marketplace.value;
    elements.ebaySection.classList.toggle('active', marketplace === 'ebay');
    elements.depopSection.classList.toggle('active', marketplace === 'depop');

    elements.feesLabel.textContent = marketplace === 'ebay'
      ? 'eBay + PayPal Fees (%)'
      : 'Depop Fees (%)';

    updateFees();
    saveFormData();
  }

  function updateCategoryOptions() {
    const hasStore = elements.hasStore.checked;
    const fees = hasStore ? storeFees : standardFees;
    const current = elements.ebayCategory.value;

    elements.ebayCategory.innerHTML = '<option value="">Select a category</option>';
    for (let category in fees) {
      const option = document.createElement('option');
      option.value = category;
      option.textContent = category;
      elements.ebayCategory.appendChild(option);
    }

    if (current && fees[current]) {
      elements.ebayCategory.value = current;
    }

    updateFees();
  }

  function updateDepopFees() {
    const includeBoost = elements.depopBoost.checked;
    const totalFee = includeBoost ? depopPaymentFeeRate + depopBoostFeeRate : depopPaymentFeeRate;
    elements.fees.value = totalFee.toFixed(2);
  }

  function updateFees() {
    const marketplace = elements.marketplace.value;

    if (marketplace === 'ebay') {
      const hasStore = elements.hasStore.checked;
      const selectedCategory = elements.ebayCategory.value;
      const topRated = elements.topRated.checked;

      let fee = hasStore ? storeFees[selectedCategory] : standardFees[selectedCategory];
      if (fee && topRated) {
        fee *= 0.90;
      }

      elements.fees.value = fee ? fee.toFixed(2) : '15';
    } else {
      updateDepopFees();
    }
  }

  function calculateDepopFees(resalePrice, shippingCost) {
    const useBoost = elements.depopBoost.checked;
    const includeShippingInPrice = elements.depopShipping.checked;

    const feeBasis = includeShippingInPrice ? resalePrice : resalePrice + shippingCost;

    const paymentProcessingFee = (feeBasis * (depopPaymentFeeRate / 100)) + depopPaymentFixedFee;
    const boostFee = useBoost ? (resalePrice * (depopBoostFeeRate / 100)) : 0;
    const totalFees = paymentProcessingFee + boostFee;

    return {
      totalFees,
      details: `Depop Fees (${depopPaymentFeeRate}% + $${depopPaymentFixedFee.toFixed(2)}${useBoost ? ` + Boost ${depopBoostFeeRate}%` : ''})`
    };
  }

  function calculate() {
    const marketplace = elements.marketplace.value;
    const itemName = elements.itemName.value.trim();
    const buyPrice = parseFloat(elements.buyPrice.value) || 0;
    const resalePrice = parseFloat(elements.resalePrice.value) || 0;
    const shippingCost = parseFloat(elements.shipping.value) || 0;

    if (!buyPrice || !resalePrice) {
      elements.result.innerHTML = '<p style="color:var(--err)">Please fill in Item Cost and Listing Price.</p>';
      elements.result.style.display = 'block';
      return;
    }

    let totalFees, feeDetails, net, profit, totalCost, breakeven;

    if (marketplace === 'ebay') {
      const feePercent = parseFloat(elements.fees.value) || 0;
      const includeFixedFee = elements.fixedFee.checked;
      const variableFees = resalePrice * (feePercent / 100);
      const fixedFee = includeFixedFee ? 0.30 : 0;
      totalFees = variableFees + fixedFee;
      feeDetails = `eBay + PayPal Fees (${feePercent}% + $${fixedFee.toFixed(2)})`;
      net = resalePrice - totalFees - shippingCost;
      totalCost = buyPrice + shippingCost + totalFees;
      breakeven = ((buyPrice + shippingCost + fixedFee) / (1 - (feePercent / 100))).toFixed(2);
    } else {
      const depopFees = calculateDepopFees(resalePrice, shippingCost);
      totalFees = depopFees.totalFees;
      feeDetails = depopFees.details;
      const includeShippingInPrice = elements.depopShipping.checked;
      net = resalePrice - totalFees - (includeShippingInPrice ? 0 : shippingCost);
      totalCost = buyPrice + (includeShippingInPrice ? 0 : shippingCost) + totalFees;
      breakeven = ((buyPrice + (includeShippingInPrice ? 0 : shippingCost) + depopPaymentFixedFee) / (1 - (depopPaymentFeeRate / 100))).toFixed(2);
    }

    profit = net - buyPrice;
    const taxRate = 0.0875;
    const buyerPays = resalePrice * (1 + taxRate);
    const roi = ((profit / buyPrice) * 100).toFixed(2);
    const markup = (((resalePrice - buyPrice) / buyPrice) * 100).toFixed(2);
    const earningsPerDollar = (profit / buyPrice).toFixed(2);

    const output = `
🧾 Item: ${itemName || 'Unnamed'}
🏪 Marketplace: ${marketplace === 'ebay' ? 'eBay' : 'Depop'}${marketplace === 'depop' ? ` (${elements.depopCategory.value})` : ''}
💰 Profit: $${profit.toFixed(2)}
🔄 ROI: ${roi}%
📊 Markup: ${markup}%
📦 Net Sale: $${net.toFixed(2)}
💼 Total Cost: $${totalCost.toFixed(2)}
💸 ${feeDetails}: $${totalFees.toFixed(2)}
🚚 Shipping: $${marketplace === 'depop' && elements.depopShipping.checked ? 'Included in price' : shippingCost.toFixed(2)}
🧾 Buyer Pays (w/ tax): $${buyerPays.toFixed(2)}
🧮 Break-even Price: $${breakeven}
💡 Earnings per $1 Invested: $${earningsPerDollar}
`.trim();

    elements.result.innerHTML = `
      <pre>${output}</pre>
      <button class="btn submitbtn" onclick="ProfitCalc.copyResult()">
        <i class="fas fa-copy"></i> Copy Note
      </button>
    `;
    elements.result.style.display = 'block';

    saveToHistory(output);
  }

  function copyResult() {
    const text = elements.result.querySelector('pre').innerText;
    navigator.clipboard.writeText(text).then(() => {
      alert('Copied to clipboard!');
    }).catch(() => {
      alert('Failed to copy to clipboard');
    });
  }

  function saveToHistory(noteText) {
    const itemName = elements.itemName.value.trim();
    const now = new Date().toLocaleString();
    const entry = { date: now, item: itemName || "Unnamed Item", note: noteText };
    let history = JSON.parse(localStorage.getItem('qventoryProfitHistory') || '[]');
    history.unshift(entry);
    if (history.length > 50) history = history.slice(0, 50); // Keep last 50
    localStorage.setItem('qventoryProfitHistory', JSON.stringify(history));
    renderHistory();
  }

  function renderHistory() {
    const history = JSON.parse(localStorage.getItem('qventoryProfitHistory') || '[]');

    if (history.length === 0) {
      elements.history.innerHTML = '<p style="color:var(--sub);text-align:center">No saved calculations yet.</p>';
      return;
    }

    let html = '';
    history.forEach((entry, index) => {
      html += `
        <div class="history-entry">
          <strong>${entry.item}</strong>
          <small>${entry.date}</small>
          <div class="history-actions">
            <button class="btn" onclick="ProfitCalc.deleteHistory(${index})" style="background:var(--err)">
              <i class="fas fa-trash"></i> Delete
            </button>
            <button class="btn submitbtn" onclick="ProfitCalc.copyNote(${index})">
              <i class="fas fa-copy"></i> Copy
            </button>
          </div>
          <pre>${entry.note}</pre>
        </div>
      `;
    });

    elements.history.innerHTML = html;
  }

  function deleteHistory(index) {
    let history = JSON.parse(localStorage.getItem('qventoryProfitHistory') || '[]');
    history.splice(index, 1);
    localStorage.setItem('qventoryProfitHistory', JSON.stringify(history));
    renderHistory();
  }

  function copyNote(index) {
    const history = JSON.parse(localStorage.getItem('qventoryProfitHistory') || '[]');
    if (history[index]) {
      navigator.clipboard.writeText(history[index].note).then(() => {
        alert('Note copied to clipboard!');
      }).catch(() => {
        alert('Failed to copy to clipboard');
      });
    }
  }

  function toggleHistory() {
    const isHidden = elements.history.style.display === 'none';
    elements.history.style.display = isHidden ? 'block' : 'none';
  }

  function saveFormData() {
    const data = {
      marketplace: elements.marketplace.value,
      itemName: elements.itemName.value,
      buyPrice: elements.buyPrice.value,
      resalePrice: elements.resalePrice.value,
      shipping: elements.shipping.value,
      hasStore: elements.hasStore.checked,
      topRated: elements.topRated.checked,
      fixedFee: elements.fixedFee.checked,
      ebayCategory: elements.ebayCategory.value,
      depopCategory: elements.depopCategory.value,
      depopBoost: elements.depopBoost.checked,
      depopShipping: elements.depopShipping.checked
    };
    localStorage.setItem('qventoryProfitCalcData', JSON.stringify(data));
  }

  function loadFormData() {
    const data = JSON.parse(localStorage.getItem('qventoryProfitCalcData'));
    if (!data) return;

    elements.marketplace.value = data.marketplace || 'ebay';
    elements.itemName.value = data.itemName || '';
    elements.buyPrice.value = data.buyPrice || '';
    elements.resalePrice.value = data.resalePrice || '';
    elements.shipping.value = data.shipping || '';
    elements.hasStore.checked = data.hasStore || false;
    elements.topRated.checked = data.topRated || false;
    elements.fixedFee.checked = data.fixedFee || false;
    elements.depopBoost.checked = data.depopBoost || false;
    elements.depopShipping.checked = data.depopShipping || false;

    switchMarketplace();
    updateCategoryOptions();

    if (data.ebayCategory) {
      elements.ebayCategory.value = data.ebayCategory;
    }

    if (data.depopCategory) {
      elements.depopCategory.value = data.depopCategory;
    }

    updateFees();
  }

  function applyUrlPrefill() {
    const params = new URLSearchParams(window.location.search);
    let applied = false;

    const title = params.get('title');
    const cost = params.get('cost');
    const price = params.get('price');

    if (title) {
      elements.itemName.value = title;
      applied = true;
    }

    if (cost !== null && cost !== '') {
      const parsedCost = parseFloat(cost);
      if (Number.isFinite(parsedCost)) {
        elements.buyPrice.value = parsedCost.toFixed(2);
        applied = true;
      }
    }

    if (price !== null && price !== '') {
      const parsedPrice = parseFloat(price);
      if (Number.isFinite(parsedPrice)) {
        elements.resalePrice.value = parsedPrice.toFixed(2);
        applied = true;
      }
    }

    return applied;
  }

  // Autocomplete functionality
  function setupAutocomplete() {
    elements.itemName.addEventListener('input', function() {
      const query = this.value.trim();

      clearTimeout(autocompleteTimeout);

      if (query.length < 2) {
        hideAutocomplete();
        return;
      }

      autocompleteTimeout = setTimeout(() => {
        fetchAutocomplete(query);
      }, 300);
    });

    // Close autocomplete when clicking outside
    document.addEventListener('click', function(e) {
      if (!elements.itemName.contains(e.target) && !elements.autocompleteList.contains(e.target)) {
        hideAutocomplete();
      }
    });
  }

  async function fetchAutocomplete(query) {
    try {
      const response = await fetch(`/api/autocomplete-items?q=${encodeURIComponent(query)}`);
      const data = await response.json();

      if (data.ok && data.items && data.items.length > 0) {
        showAutocomplete(data.items);
      } else {
        hideAutocomplete();
      }
    } catch (error) {
      console.error('Autocomplete error:', error);
      hideAutocomplete();
    }
  }

  function showAutocomplete(items) {
    let html = '';
    items.forEach(item => {
      const costStr = item.cost !== null ? `$${item.cost.toFixed(2)}` : 'N/A';
      const priceStr = item.price !== null ? `$${item.price.toFixed(2)}` : 'N/A';

      html += `
        <div class="autocomplete-item" data-item='${JSON.stringify(item)}'>
          <strong>${item.title}</strong>
          <small>SKU: ${item.sku} | Cost: ${costStr} | Price: ${priceStr}</small>
        </div>
      `;
    });

    elements.autocompleteList.innerHTML = html;
    elements.autocompleteList.classList.add('show');

    // Add click listeners
    elements.autocompleteList.querySelectorAll('.autocomplete-item').forEach(el => {
      el.addEventListener('click', function() {
        const item = JSON.parse(this.getAttribute('data-item'));
        selectItem(item);
      });
    });
  }

  function hideAutocomplete() {
    elements.autocompleteList.classList.remove('show');
    elements.autocompleteList.innerHTML = '';
  }

  function selectItem(item) {
    currentItemData = item;
    elements.itemName.value = item.title;

    if (item.cost !== null) {
      elements.buyPrice.value = item.cost.toFixed(2);
    }

    if (item.price !== null) {
      elements.resalePrice.value = item.price.toFixed(2);
    }

    hideAutocomplete();
    saveFormData();
  }

  // Initialize when modal or page loads
  function init() {
    initElements();
    updateCategoryOptions();
    loadFormData();
    if (applyUrlPrefill()) {
      saveFormData();
    }
    renderHistory();
    setupAutocomplete();

    // Event listeners
    elements.marketplace.addEventListener('change', switchMarketplace);
    elements.hasStore.addEventListener('change', () => { updateCategoryOptions(); saveFormData(); });
    elements.ebayCategory.addEventListener('change', () => { updateFees(); saveFormData(); });
    elements.topRated.addEventListener('change', () => { updateFees(); saveFormData(); });
    elements.fixedFee.addEventListener('change', saveFormData);
    elements.depopBoost.addEventListener('change', () => { updateDepopFees(); saveFormData(); });
    elements.depopShipping.addEventListener('change', saveFormData);
    elements.depopCategory.addEventListener('change', saveFormData);

    // Save on input changes
    ['itemName', 'buyPrice', 'resalePrice', 'shipping'].forEach(field => {
      elements[field].addEventListener('input', saveFormData);
    });
  }

  // Public API
  return {
    init,
    calculate,
    copyResult,
    deleteHistory,
    copyNote,
    toggleHistory,
    selectItem  // For modal usage
  };
})();

// Initialize when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', ProfitCalc.init);
} else {
  ProfitCalc.init();
}
