/**
 * Qventory Profit Calculator
 * Native profit calculation module with autocomplete and history
 */

const ProfitCalc = (function() {
  'use strict';

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
      fixedAdsFee: document.getElementById('fixedAdsFee'),
      shipping: document.getElementById('shipping'),

      // eBay specific
      hasStore: document.getElementById('hasStore'),
      topRated: document.getElementById('topRated'),
      fixedFee: document.getElementById('fixedFee'),
      ebaySection: document.getElementById('ebay-section'),
      ebayCategorySearch: document.getElementById('ebayCategorySearch'),
      ebayCategoryId: document.getElementById('ebayCategoryId'),
      ebayCategoryList: document.getElementById('ebayCategoryList'),
      ebayCategoryPath: document.getElementById('ebayCategoryPath'),

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
      ? 'Estimated Fee Rate (%)'
      : 'Depop Fees (%)';

    if (marketplace === 'ebay') {
      elements.fees.value = '0';
    } else {
      updateDepopFees();
    }
    saveFormData();
  }

  function updateDepopFees() {
    const includeBoost = elements.depopBoost.checked;
    const totalFee = includeBoost ? depopPaymentFeeRate + depopBoostFeeRate : depopPaymentFeeRate;
    elements.fees.value = totalFee.toFixed(2);
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

  async function calculate() {
    const marketplace = elements.marketplace.value;
    const itemName = elements.itemName.value.trim();
    const buyPrice = parseFloat(elements.buyPrice.value) || 0;
    const resalePrice = parseFloat(elements.resalePrice.value) || 0;
    const shippingCost = parseFloat(elements.shipping.value) || 0;
    const adsFeeRate = parseFloat(elements.fixedAdsFee.value) || 0;

    if (!buyPrice || !resalePrice) {
      elements.result.innerHTML = '<p style="color:var(--err)">Please fill in Item Cost and Listing Price.</p>';
      elements.result.style.display = 'block';
      return;
    }

    if (marketplace === 'ebay') {
      try {
        const payload = {
          marketplace,
          item_name: itemName,
          buy_price: buyPrice,
          resale_price: resalePrice,
          shipping_cost: shippingCost,
          ads_fee_rate: adsFeeRate,
          has_store: elements.hasStore.checked,
          top_rated: elements.topRated.checked,
          include_fixed_fee: elements.fixedFee.checked,
          category_id: elements.ebayCategoryId.value || null,
          category_path: elements.ebayCategoryPath.textContent || null
        };

        const response = await fetch('/api/profit-calculator/calc', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!data.ok) {
          elements.result.innerHTML = `<p style="color:var(--err)">${data.error || 'Calculation failed.'}</p>`;
          elements.result.style.display = 'block';
          return;
        }

        const feeRate = data.fee_breakdown ? data.fee_breakdown.fee_rate_percent : 0;
        elements.fees.value = feeRate ? feeRate.toFixed(2) : '0';

        elements.result.innerHTML = `
          <pre>${data.output_text}</pre>
          <button class="btn submitbtn" onclick="ProfitCalc.copyResult()">
            <i class="fas fa-copy"></i> Copy Note
          </button>
        `;
        elements.result.style.display = 'block';
        await renderHistory();
        return;
      } catch (error) {
        elements.result.innerHTML = `<p style="color:var(--err)">Calculation error: ${error.message}</p>`;
        elements.result.style.display = 'block';
        return;
      }
    }

    let totalFees, marketplaceFees, feeDetails, net, profit, totalCost, breakeven;
    if (marketplace === 'depop') {
      const depopFees = calculateDepopFees(resalePrice, shippingCost);
      marketplaceFees = depopFees.totalFees;
      totalFees = marketplaceFees + (resalePrice * (adsFeeRate / 100));
      feeDetails = depopFees.details;
      const includeShippingInPrice = elements.depopShipping.checked;
      net = resalePrice - totalFees - (includeShippingInPrice ? 0 : shippingCost);
      totalCost = buyPrice + (includeShippingInPrice ? 0 : shippingCost) + totalFees;
      const depopPercentTotal = depopPaymentFeeRate + (elements.depopBoost.checked ? depopBoostFeeRate : 0) + adsFeeRate;
      breakeven = ((buyPrice + (includeShippingInPrice ? 0 : shippingCost) + depopPaymentFixedFee) / (1 - (depopPercentTotal / 100))).toFixed(2);
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
💸 ${feeDetails}: $${marketplaceFees.toFixed(2)}
📣 Ads Fee (${adsFeeRate.toFixed(2)}%): $${(resalePrice * (adsFeeRate / 100)).toFixed(2)}
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

  async function saveToHistory(noteText) {
    try {
      await renderHistory();
    } catch (error) {
      console.error('History sync error:', error);
    }
  }

  async function renderHistory() {
    try {
      const response = await fetch('/api/profit-calculator/reports');
      const data = await response.json();
      const history = data.reports || [];

      if (!history.length) {
        elements.history.innerHTML = '<p style="color:var(--sub);text-align:center">No saved calculations yet.</p>';
        return;
      }

      let html = '';
      history.forEach((entry) => {
        const when = entry.created_at ? new Date(entry.created_at).toLocaleString() : '';
        html += `
          <div class="history-entry">
            <strong>${entry.item_name || 'Unnamed Item'}</strong>
            <small>${when}</small>
            <div class="history-actions">
              <button class="btn" onclick="ProfitCalc.deleteHistory(${entry.id})" style="background:var(--err)">
                <i class="fas fa-trash"></i> Delete
              </button>
              <button class="btn submitbtn" onclick="ProfitCalc.copyNote(${entry.id})">
                <i class="fas fa-copy"></i> Copy
              </button>
            </div>
            <pre>${entry.output_text || ''}</pre>
          </div>
        `;
      });

      elements.history.innerHTML = html;
    } catch (error) {
      elements.history.innerHTML = '<p style="color:var(--err);text-align:center">Failed to load history.</p>';
    }
  }

  async function deleteHistory(reportId) {
    await fetch(`/api/profit-calculator/reports/${reportId}`, { method: 'DELETE' });
    renderHistory();
  }

  async function copyNote(reportId) {
    const response = await fetch('/api/profit-calculator/reports');
    const data = await response.json();
    const entry = (data.reports || []).find(r => r.id === reportId);
    if (entry && entry.output_text) {
      navigator.clipboard.writeText(entry.output_text).then(() => {
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
      fixedAdsFee: elements.fixedAdsFee.value,
      shipping: elements.shipping.value,
      hasStore: elements.hasStore.checked,
      topRated: elements.topRated.checked,
      fixedFee: elements.fixedFee.checked,
      ebayCategoryId: elements.ebayCategoryId.value,
      ebayCategoryPath: elements.ebayCategoryPath.textContent,
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
    elements.fixedAdsFee.value = data.fixedAdsFee || '';
    elements.shipping.value = data.shipping || '';
    elements.hasStore.checked = data.hasStore || false;
    elements.topRated.checked = data.topRated || false;
    elements.fixedFee.checked = data.fixedFee || false;
    elements.ebayCategoryId.value = data.ebayCategoryId || '';
    elements.ebayCategoryPath.textContent = data.ebayCategoryPath || '';
    if (data.ebayCategoryPath) {
      elements.ebayCategorySearch.value = data.ebayCategoryPath;
    }
    elements.depopBoost.checked = data.depopBoost || false;
    elements.depopShipping.checked = data.depopShipping || false;

    switchMarketplace();
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

  function setupCategorySearch() {
    elements.ebayCategorySearch.addEventListener('input', function() {
      const query = this.value.trim();
      clearTimeout(autocompleteTimeout);
      if (query.length < 2) {
        hideCategoryAutocomplete();
        return;
      }
      autocompleteTimeout = setTimeout(() => {
        fetchCategoryAutocomplete(query);
      }, 300);
    });

    document.addEventListener('click', function(e) {
      if (!elements.ebayCategorySearch.contains(e.target) && !elements.ebayCategoryList.contains(e.target)) {
        hideCategoryAutocomplete();
      }
    });
  }

  async function fetchCategoryAutocomplete(query) {
    try {
      const response = await fetch(`/api/ebay/categories/search?q=${encodeURIComponent(query)}`);
      const data = await response.json();
      if (data.ok && data.categories && data.categories.length) {
        showCategoryAutocomplete(data.categories);
      } else {
        hideCategoryAutocomplete();
      }
    } catch (error) {
      console.error('Category autocomplete error:', error);
      hideCategoryAutocomplete();
    }
  }

  function showCategoryAutocomplete(categories) {
    let html = '';
    categories.forEach(cat => {
      html += `
        <div class="autocomplete-item" data-category='${JSON.stringify(cat)}'>
          <strong>${cat.name}</strong>
          <small>${cat.full_path}</small>
        </div>
      `;
    });
    elements.ebayCategoryList.innerHTML = html;
    elements.ebayCategoryList.classList.add('show');

    elements.ebayCategoryList.querySelectorAll('.autocomplete-item').forEach(el => {
      el.addEventListener('click', function() {
        const cat = JSON.parse(this.getAttribute('data-category'));
        selectCategory(cat);
      });
    });
  }

  function hideCategoryAutocomplete() {
    elements.ebayCategoryList.classList.remove('show');
    elements.ebayCategoryList.innerHTML = '';
  }

  function selectCategory(cat) {
    elements.ebayCategoryId.value = cat.category_id;
    elements.ebayCategorySearch.value = cat.name;
    elements.ebayCategoryPath.textContent = cat.full_path;
    hideCategoryAutocomplete();
    saveFormData();
  }

  // Initialize when modal or page loads
  function init() {
    initElements();
    loadFormData();
    if (applyUrlPrefill()) {
      saveFormData();
    }
    renderHistory();
    setupAutocomplete();
    setupCategorySearch();

    // Event listeners
    elements.marketplace.addEventListener('change', switchMarketplace);
    elements.hasStore.addEventListener('change', saveFormData);
    elements.topRated.addEventListener('change', saveFormData);
    elements.fixedFee.addEventListener('change', saveFormData);
    elements.depopBoost.addEventListener('change', () => { updateDepopFees(); saveFormData(); });
    elements.depopShipping.addEventListener('change', saveFormData);
    elements.depopCategory.addEventListener('change', saveFormData);

    // Save on input changes
    ['itemName', 'buyPrice', 'resalePrice', 'fixedAdsFee', 'shipping'].forEach(field => {
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
