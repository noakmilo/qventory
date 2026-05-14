(function() {
  const config = window.EBAY_LIST_CONFIG;
  let draft = null;
  let specificsSchema = null;
  let saveTimer = null;
  let images = [];
  let selectedImageIndex = null;
  let cropper = null;
  let flipX = 1;
  let flipY = 1;
  let currentAspectMode = 'free';
  let categorySearchTimer = null;
  const MAX_IMAGES = 24;

  const qs = (sel) => document.querySelector(sel);

  const wizardStatus = qs('#wizardStatus');

  function setStatus(msg) {
    if (wizardStatus) wizardStatus.textContent = msg;
  }

  function draftUrl(base, id) {
    return `${base}/${id}`;
  }

  function generateSku() {
    const now = new Date();
    const pad = (value) => String(value).padStart(2, '0');
    const date = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`;
    const time = `${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
    return `QV-${date}-${time}`;
  }

  function defaultDraft() {
    return {
      id: null,
      title: '',
      sku: generateSku(),
      condition_id: '',
      quantity: 1,
      price: null,
      currency: 'USD',
      listing_format: 'FIXED_PRICE',
      accept_offers: false,
      auction_start_price: null,
      category_id: null,
      item_specifics: {},
      package_details: {},
      policy_ids: {},
      images: []
    };
  }

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, (char) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[char]));
  }

  async function createDraft() {
    const previousDraft = draft || {};
    const res = await fetch(config.draftCreateUrl, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({})
    });
    const data = await res.json();
    draft = {
      ...data.draft,
      category_id: previousDraft.category_id || data.draft.category_id || null,
      item_specifics: previousDraft.item_specifics || data.draft.item_specifics || {}
    };
    const url = new URL(window.location.href);
    url.searchParams.set('draft_id', draft.id);
    window.history.replaceState({}, '', url);
    setStatus(`Draft #${draft.id} created.`);
    return draft;
  }

  async function loadDraftFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const draftId = params.get('draft_id');
    if (!draftId) {
      draft = defaultDraft();
      setStatus('New unsaved draft. Click Save Draft when you are ready.');
      return;
    }
    const res = await fetch(draftUrl(config.draftBaseUrl, draftId));
    if (!res.ok) {
      draft = defaultDraft();
      setStatus('Draft not found. Started a new unsaved draft.');
      return;
    }
    const data = await res.json();
    draft = data.draft;
    setStatus(`Draft #${draft.id} loaded.`);
  }

  async function ensureDraftExists() {
    if (draft && draft.id) return draft;
    await createDraft();
    return draft;
  }

  function debounceSave() {
    if (!draft || !draft.id) return;
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => saveDraft({createIfMissing: false}), 800);
  }

  function serializeDraftFromInputs() {
    const listingType = qs('#listingTypeInput').value;
    return {
      title: qs('#titleInput').value.trim(),
      sku: qs('#skuInput').value.trim(),
      condition_id: qs('#conditionInput').value,
      condition_label: qs('#conditionInput').selectedOptions[0]?.textContent || null,
      quantity: parseInt(qs('#quantityInput').value || '0', 10),
      price: parseFloat(qs('#priceInput').value || '0'),
      currency: qs('#currencyInput').value,
      listing_format: listingType === 'AUCTION' ? 'AUCTION' : 'FIXED_PRICE',
      accept_offers: listingType === 'FIXED_PRICE_OFFERS',
      auction_start_price: readFloat('#auctionStartPriceInput'),
      package_details: serializePackageDetails(),
      description_html: getDescriptionHtml(),
      fulfillment_policy_id: qs('#fulfillmentPolicySelect').value || null,
      payment_policy_id: qs('#paymentPolicySelect').value || null,
      return_policy_id: qs('#returnPolicySelect').value || null
    };
  }

  function setDescriptionHtml(html) {
    qs('#descriptionHtmlInput').value = html || '';
    qs('#visualEditor').innerHTML = html || '';
  }

  function getDescriptionHtml() {
    if (qs('#descriptionHtmlInput').style.display === 'none') {
      return qs('#visualEditor').innerHTML;
    }
    return qs('#descriptionHtmlInput').value;
  }

  function setAiGenerating(targets, isGenerating) {
    targets.forEach((target) => {
      if (!target) return;
      target.classList.toggle('ai-generating', isGenerating);
      target.classList.toggle('ai-generating-text', isGenerating);
      if ('disabled' in target) target.disabled = isGenerating;
      if (target.isContentEditable) target.setAttribute('aria-busy', isGenerating ? 'true' : 'false');
    });
  }

  function readFloat(selector) {
    const value = parseFloat(qs(selector).value || '0');
    return Number.isFinite(value) ? value : 0;
  }

  function serializePackageDetails() {
    return {
      weight_lbs: readFloat('#packageWeightLbsInput'),
      weight_oz: readFloat('#packageWeightOzInput'),
      length_in: readFloat('#packageLengthInput'),
      width_in: readFloat('#packageWidthInput'),
      height_in: readFloat('#packageHeightInput'),
      weight_unit: 'OUNCE',
      dimension_unit: 'INCH'
    };
  }

  async function saveDraft(options = {}) {
    const {createIfMissing = false, quiet = false, includeImages = true} = options;
    if (!draft) draft = defaultDraft();
    if (!draft.id) {
      if (!createIfMissing) return;
      await createDraft();
    }
    if (includeImages) {
      await uploadPendingImages();
    }
    normalizeMainImage();
    const payload = serializeDraftFromInputs();
    payload.category_id = draft.category_id || null;
    payload.item_specifics = draft.item_specifics || {};
    if (includeImages) {
      payload.images = images.map((img, index) => ({
        order: index,
        filename: img.filename,
        sha256: img.sha256,
        width: img.width,
        height: img.height,
        cloudinary_url: img.cloudinary_url || img.image_url || null,
        cloudinary_public_id: img.cloudinary_public_id || null,
        image_url: img.cloudinary_url || img.image_url || null,
        ebay_image_url: img.ebay_image_url,
        ebay_image_location: img.ebay_image_location || null,
        is_main: img.is_main || false
      }));
    }
    const res = await fetch(draftUrl(config.draftBaseUrl, draft.id), {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    draft = data.draft;
    if (!quiet) {
      setStatus(`Draft #${draft.id} saved at ${new Date().toLocaleTimeString()}`);
    }
  }

  async function uploadPendingImages() {
    if (!draft || !draft.id) return;
    for (const img of images) {
      if (img.blob && !img.cloudinary_url && !img.image_url) {
        await uploadImage(img, {deferSave: true});
      }
    }
  }

  function bindInputAutosave() {
    [
      '#titleInput', '#skuInput', '#conditionInput', '#quantityInput', '#priceInput', '#currencyInput',
      '#listingTypeInput', '#auctionStartPriceInput',
      '#packageWeightLbsInput', '#packageWeightOzInput', '#packageLengthInput', '#packageWidthInput', '#packageHeightInput'
    ]
      .forEach(sel => {
        const el = qs(sel);
        el.addEventListener('input', debounceSave);
        el.addEventListener('change', debounceSave);
      });
    qs('#listingTypeInput').addEventListener('change', toggleListingTypeFields);
    qs('#visualEditor').addEventListener('input', debounceSave);
    qs('#descriptionHtmlInput').addEventListener('input', debounceSave);
    ['#fulfillmentPolicySelect', '#paymentPolicySelect', '#returnPolicySelect']
      .forEach(sel => qs(sel).addEventListener('change', debounceSave));
  }

  function renderDraftToInputs() {
    if (!draft) return;
    qs('#titleInput').value = draft.title || '';
    qs('#skuInput').value = draft.sku || generateSku();
    qs('#conditionInput').value = draft.condition_id || '';
    qs('#quantityInput').value = draft.quantity || 1;
    qs('#priceInput').value = draft.price || '';
    qs('#currencyInput').value = draft.currency || 'USD';
    const listingType = draft.listing_format === 'AUCTION'
      ? 'AUCTION'
      : draft.accept_offers
        ? 'FIXED_PRICE_OFFERS'
        : 'FIXED_PRICE';
    qs('#listingTypeInput').value = listingType;
    qs('#auctionStartPriceInput').value = draft.auction_start_price || '';
    toggleListingTypeFields();
    const packageDetails = draft.package_details || {};
    qs('#packageWeightLbsInput').value = packageDetails.weight_lbs || '';
    qs('#packageWeightOzInput').value = packageDetails.weight_oz || '';
    qs('#packageLengthInput').value = packageDetails.length_in || '';
    qs('#packageWidthInput').value = packageDetails.width_in || '';
    qs('#packageHeightInput').value = packageDetails.height_in || '';
    setDescriptionHtml(draft.description_html || '');
    populateConditionSelect([], draft.condition_id || '');
  }

  function toggleListingTypeFields() {
    const isAuction = qs('#listingTypeInput').value === 'AUCTION';
    qs('#auctionFields').style.display = isAuction ? 'block' : 'none';
  }

  function applyCommand(cmd) {
    document.execCommand(cmd, false, null);
  }

  function setupEditorToggle() {
    const visualBtn = qs('#visualModeBtn');
    const htmlBtn = qs('#htmlModeBtn');
    const visualEditor = qs('#visualEditor');
    const htmlEditor = qs('#descriptionHtmlInput');

    visualBtn.addEventListener('click', () => {
      visualBtn.classList.add('active');
      htmlBtn.classList.remove('active');
      htmlEditor.style.display = 'none';
      visualEditor.style.display = 'block';
      visualEditor.innerHTML = htmlEditor.value;
    });
    htmlBtn.addEventListener('click', () => {
      htmlBtn.classList.add('active');
      visualBtn.classList.remove('active');
      htmlEditor.style.display = 'block';
      visualEditor.style.display = 'none';
      htmlEditor.value = visualEditor.innerHTML;
    });

    document.querySelectorAll('.editor-toolbar [data-cmd]').forEach(btn => {
      btn.addEventListener('click', () => applyCommand(btn.dataset.cmd));
    });
  }

  async function loadPolicies() {
    const res = await fetch(config.policiesUrl);
    const data = await res.json();
    if (!data.ok) {
      setStatus('Failed to load policies.');
      return;
    }
    const policies = data.policies || {};
    populatePolicySelect('#fulfillmentPolicySelect', policies.fulfillment || []);
    populatePolicySelect('#paymentPolicySelect', policies.payment || []);
    populatePolicySelect('#returnPolicySelect', policies.return || []);
  }

  function populatePolicySelect(selector, policies) {
    const select = qs(selector);
    select.innerHTML = '';
    const empty = document.createElement('option');
    empty.value = '';
    empty.textContent = 'Select policy';
    select.appendChild(empty);
    policies.forEach(p => {
      const opt = document.createElement('option');
      opt.value = policyIdForSelector(selector, p);
      opt.textContent = `${p.name || p.description || p.id}`;
      select.appendChild(opt);
    });
    if (draft && draft.policy_ids) {
      const current = selector === '#fulfillmentPolicySelect'
        ? draft.policy_ids.fulfillment
        : selector === '#paymentPolicySelect'
          ? draft.policy_ids.payment
          : draft.policy_ids.return;
      if (current) select.value = current;
    }
  }

  function policyIdForSelector(selector, policy) {
    if (selector === '#fulfillmentPolicySelect') {
      return policy.fulfillmentPolicyId || policy.policyId || policy.id || '';
    }
    if (selector === '#paymentPolicySelect') {
      return policy.paymentPolicyId || policy.policyId || policy.id || '';
    }
    if (selector === '#returnPolicySelect') {
      return policy.returnPolicyId || policy.policyId || policy.id || '';
    }
    return policy.policyId || policy.id || '';
  }

  async function loadLocations() {
    const res = await fetch(config.locationsUrl);
    const data = await res.json();
    if (!data.ok) {
      setStatus('No merchant locations found.');
      return;
    }
    const location = (data.locations || [])[0];
    if (location) {
      setStatus(`Using location: ${location.merchantLocationKey}`);
    }
  }

  async function loadCategoryPicker() {
    if (!draft || !draft.category_id) {
      renderSelectedCategory(null);
      return;
    }
    try {
      const res = await fetch(`${config.categoriesUrl}/${draft.category_id}/path`);
      const data = await res.json();
      if (data.ok) {
        const selected = {
          category_id: draft.category_id,
          full_path: data.full_path,
          is_leaf: true
        };
        renderSelectedCategory(selected);
        qs('#categorySearchInput').value = selected.full_path || '';
      }
    } catch (err) {
      const selected = {category_id: draft.category_id, full_path: `Category ${draft.category_id}`, is_leaf: true};
      renderSelectedCategory(selected);
      qs('#categorySearchInput').value = selected.full_path;
    }
    await loadCategoryConditions(draft.category_id, draft.condition_id);
    await fetchSpecifics(draft.category_id);
  }

  function scheduleCategorySearch() {
    if (categorySearchTimer) clearTimeout(categorySearchTimer);
    categorySearchTimer = setTimeout(searchCategories, 250);
  }

  async function searchCategories() {
    const query = qs('#categorySearchInput').value.trim();
    if (query.length < 2) {
      renderAutocomplete([]);
      return;
    }
    const url = `${config.categoriesUrl}?query=${encodeURIComponent(query)}&leaf_only=1&limit=18`;
    try {
      const res = await fetch(url);
      const data = await res.json();
      renderAutocomplete(data.categories || []);
    } catch (err) {
      setStatus('Could not search eBay categories.');
      renderAutocomplete([]);
    }
  }

  function renderAutocomplete(categories) {
    const box = qs('#categoryAutocomplete');
    box.innerHTML = '';
    if (!categories.length) {
      box.style.display = 'none';
      return;
    }
    categories.forEach(cat => {
      const div = document.createElement('div');
      div.className = 'item';
      const path = cat.full_path || cat.name || cat.category_id;
      const parts = path.split(' > ');
      div.innerHTML = `
        <div class="item-title">${escapeHtml(parts[parts.length - 1])}</div>
        <div class="item-meta">${escapeHtml(path)}</div>
      `;
      div.addEventListener('click', () => {
        selectCategory(cat);
        box.style.display = 'none';
      });
      box.appendChild(div);
    });
    box.style.display = 'block';
  }

  async function selectCategory(cat) {
    if (!draft) draft = defaultDraft();
    draft.category_id = cat.category_id;
    renderSelectedCategory(cat);
    qs('#categorySearchInput').value = cat.full_path || cat.name || '';
    await loadCategoryConditions(cat.category_id, draft.condition_id);
    await fetchSpecifics(cat.category_id);
    debounceSave();
  }

  async function loadCategoryConditions(categoryId, preferredValue = '') {
    const select = qs('#conditionInput');
    populateConditionSelect([], '');
    select.disabled = true;
    select.innerHTML = '<option value="">Loading valid conditions...</option>';
    try {
      const res = await fetch(`${config.categoryConditionBaseUrl}/${categoryId}/conditions`);
      const data = await res.json();
      if (!data.ok) {
        throw new Error(data.details || data.error || 'condition lookup failed');
      }
      populateConditionSelect(data.conditions || [], preferredValue);
    } catch (err) {
      select.innerHTML = '<option value="">Could not load category conditions</option>';
      select.disabled = false;
      setStatus('Could not load valid conditions for this category.');
    }
  }

  function populateConditionSelect(conditions, preferredValue = '') {
    const select = qs('#conditionInput');
    select.innerHTML = '';
    const empty = document.createElement('option');
    empty.value = '';
    empty.textContent = conditions.length ? 'Select condition' : 'Select a category first';
    select.appendChild(empty);
    conditions.forEach((condition) => {
      const opt = document.createElement('option');
      opt.value = condition.value;
      opt.textContent = condition.label || condition.value.replaceAll('_', ' ');
      opt.dataset.conditionId = condition.condition_id || '';
      select.appendChild(opt);
    });
    select.disabled = !conditions.length;
    if (preferredValue && conditions.some((condition) => condition.value === preferredValue)) {
      select.value = preferredValue;
    } else if (preferredValue && conditions.length) {
      draft.condition_id = null;
      setStatus('Previous condition is not valid for this category. Select one of the valid conditions.');
    }
  }

  function renderSelectedCategory(cat) {
    const selected = qs('#categorySelected');
    if (!selected) return;
    if (!cat || !cat.category_id) {
      selected.innerHTML = '<span class="muted">No category selected.</span>';
      return;
    }
    selected.innerHTML = `
      <strong>${escapeHtml(cat.full_path || cat.name || 'Selected category')}</strong>
      <span class="muted">eBay category ID: ${escapeHtml(cat.category_id)}</span>
    `;
  }

  function selectedCategoryPath() {
    const selected = qs('#categorySelected strong');
    return selected ? selected.textContent.trim() : '';
  }

  function openProfitCalcFromListing() {
    const title = qs('#titleInput').value.trim();
    const price = qs('#priceInput').value.trim();
    const params = new URLSearchParams({
      embed: '1',
      title
    });
    if (price) params.set('price', price);
    if (draft && draft.category_id) {
      params.set('category_id', draft.category_id);
      const path = selectedCategoryPath();
      if (path) params.set('category_path', path);
    }

    const url = `/profit-calculator?${params.toString()}`;
    const modal = qs('#profitCalcModal');
    const frame = qs('#profitCalcFrame');
    if (!modal || !frame) {
      const standaloneParams = new URLSearchParams(params);
      standaloneParams.delete('embed');
      window.location.href = `/profit-calculator?${standaloneParams.toString()}`;
      return;
    }
    frame.src = url;
    modal.hidden = false;
    document.body.classList.add('modal-open');
  }

  async function fetchSpecifics(categoryId) {
    const url = `${config.categoriesUrl}/${categoryId}/specifics`;
    const res = await fetch(url);
    const data = await res.json();
    specificsSchema = data.specifics;
    renderSpecificsForm();
  }

  async function refreshSpecifics() {
    if (!draft || !draft.category_id) return;
    const url = `${config.categoriesUrl}/${draft.category_id}/specifics/refresh`;
    const res = await fetch(url, {method: 'POST'});
    const data = await res.json();
    specificsSchema = data.specifics;
    renderSpecificsForm();
  }

  async function runDraftAi(action, label) {
    try {
      setStatus(`${label}...`);
      await saveDraft({createIfMissing: true, quiet: true});
      const res = await fetch(`${config.draftBaseUrl}/${draft.id}/ai/${action}`, {method: 'POST'});
      const data = await res.json();
      if (!data.ok) {
        setStatus(`${label} failed: ${data.details || data.error || 'unknown error'}`);
        return null;
      }
      return data;
    } catch (err) {
      setStatus(`${label} failed.`);
      return null;
    }
  }

  async function optimizeTitleWithAi() {
    const titleInput = qs('#titleInput');
    const button = qs('#optimizeTitleBtn');
    setAiGenerating([titleInput, button], true);
    try {
      const data = await runDraftAi('title', 'Optimizing title');
      if (!data || !data.title) return;
      titleInput.value = data.title;
      setStatus('Title optimized with AI.');
      await saveDraft({createIfMissing: true});
    } finally {
      setAiGenerating([titleInput, button], false);
    }
  }

  async function generateDescriptionWithAi() {
    const visualEditor = qs('#visualEditor');
    const htmlEditor = qs('#descriptionHtmlInput');
    const button = qs('#generateDescriptionBtn');
    setAiGenerating([visualEditor, htmlEditor, button], true);
    try {
      const data = await runDraftAi('description', 'Generating description');
      if (!data || !data.description_html) return;
      setDescriptionHtml(data.description_html);
      setStatus('Description generated with AI.');
      await saveDraft({createIfMissing: true});
    } finally {
      setAiGenerating([visualEditor, htmlEditor, button], false);
    }
  }

  async function fillSpecificsWithAi() {
    const data = await runDraftAi('specifics', 'Filling item specifics');
    if (!data || !data.item_specifics) return;
    draft.item_specifics = data.item_specifics;
    renderSpecificsForm();
    setStatus('Item specifics filled with AI.');
    await saveDraft({createIfMissing: true});
  }

  function renderSpecificsForm() {
    const container = qs('#specificsContainer');
    container.innerHTML = '';
    if (!specificsSchema) return;
    const required = specificsSchema.required_fields || [];
    const optional = specificsSchema.optional_fields || [];
    const makeField = (spec, requiredFlag) => {
      const wrapper = document.createElement('div');
      const label = document.createElement('label');
      label.className = 'label';
      label.textContent = `${spec.name}${requiredFlag ? ' *' : ''}`;
      const input = document.createElement('input');
      input.className = 'input';
      input.value = (draft.item_specifics && draft.item_specifics[spec.name]) ? draft.item_specifics[spec.name][0] : '';
      input.addEventListener('input', () => {
        const val = input.value.trim();
        if (!draft.item_specifics) draft.item_specifics = {};
        if (val) {
          draft.item_specifics[spec.name] = [val];
        } else {
          delete draft.item_specifics[spec.name];
        }
        debounceSave();
      });
      wrapper.appendChild(label);
      wrapper.appendChild(input);
      return wrapper;
    };
    required.forEach(spec => container.appendChild(makeField(spec, true)));
    optional.forEach(spec => container.appendChild(makeField(spec, false)));
  }

  async function hashFile(file) {
    const buf = await file.arrayBuffer();
    const hash = await crypto.subtle.digest('SHA-256', buf);
    return Array.from(new Uint8Array(hash)).map(b => b.toString(16).padStart(2, '0')).join('');
  }

  async function blobToImage(blob) {
    const url = URL.createObjectURL(blob);
    try {
      const img = await new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = reject;
        image.src = url;
      });
      return img;
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  async function compressBlobToJpeg(blob, maxDimension = null, tone = null) {
    const image = await blobToImage(blob);
    const ratio = maxDimension && maxDimension !== 'original'
      ? Math.min(1, Number(maxDimension) / Math.max(image.width, image.height))
      : 1;
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(image.width * ratio));
    canvas.height = Math.max(1, Math.round(image.height * ratio));
    const ctx = canvas.getContext('2d');
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    if (tone && (tone.brightness || tone.contrast)) {
      const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const data = imgData.data;
      const brightness = Number(tone.brightness || 0) * 2.55;
      const contrastValue = Number(tone.contrast || 0);
      const contrast = (259 * (contrastValue + 255)) / (255 * (259 - contrastValue));
      for (let i = 0; i < data.length; i += 4) {
        data[i] = clampChannel(contrast * (data[i] - 128) + 128 + brightness);
        data[i + 1] = clampChannel(contrast * (data[i + 1] - 128) + 128 + brightness);
        data[i + 2] = clampChannel(contrast * (data[i + 2] - 128) + 128 + brightness);
      }
      ctx.putImageData(imgData, 0, 0);
    }
    return encodeCanvasToJpeg(canvas);
  }

  function clampChannel(value) {
    return Math.max(0, Math.min(255, value));
  }

  async function encodeCanvasToJpeg(canvas) {
    let quality = 0.9;
    let blob = await new Promise(res => canvas.toBlob(res, 'image/jpeg', quality));
    while (blob.size > 900000 && quality > 0.6) {
      quality -= 0.1;
      blob = await new Promise(res => canvas.toBlob(res, 'image/jpeg', quality));
    }
    return blob;
  }

  function destroyImageEditor() {
    if (!cropper) return;
    try {
      cropper.destroy();
    } catch (e) {
      // Ignore editor cleanup failures from partially initialized instances.
    }
    cropper = null;
  }

  function ensureOpenImageEditor(img) {
    const imageEl = qs('#cropperImage');
    const emptyEl = qs('#imageEmptyState');
    const hintEl = qs('#imageEditorHint');
    if (!imageEl || !window.Cropper) {
      if (hintEl) hintEl.textContent = 'Open source image editor could not load.';
      return;
    }
    destroyImageEditor();
    flipX = 1;
    flipY = 1;
    imageEl.style.display = 'block';
    if (emptyEl) emptyEl.style.display = 'none';
    imageEl.removeAttribute('crossorigin');
    imageEl.src = img.url;
    cropper = new window.Cropper(imageEl, {
      viewMode: 1,
      autoCropArea: 1,
      aspectRatio: aspectRatioForMode(currentAspectMode),
      background: false,
      responsive: false,
      checkOrientation: true,
      movable: true,
      zoomable: true,
      rotatable: true,
      scalable: true,
      ready() {
        fitCropBoxToCanvas();
      }
    });
    if (hintEl) {
      hintEl.textContent = img.blob
        ? 'Crop, rotate, flip, adjust brightness/contrast, resize and export to eBay.'
        : 'Saved eBay image loaded. If export fails, re-add the original image and edit it locally.';
    }
    qs('#imageBrightnessRange').value = '0';
    qs('#imageContrastRange').value = '0';
    updateTonePreview();
  }

  function aspectRatioForMode(mode) {
    if (mode === 'square') return 1;
    if (mode === 'landscape') return 4 / 3;
    return NaN;
  }

  function fitCropBoxToCanvas() {
    if (!cropper) return;
    const canvas = cropper.getCanvasData();
    if (!canvas || !canvas.width || !canvas.height) return;
    const aspectRatio = aspectRatioForMode(currentAspectMode);
    if (Number.isFinite(aspectRatio)) {
      let width = canvas.width;
      let height = width / aspectRatio;
      if (height > canvas.height) {
        height = canvas.height;
        width = height * aspectRatio;
      }
      cropper.setCropBoxData({
        left: canvas.left + ((canvas.width - width) / 2),
        top: canvas.top + ((canvas.height - height) / 2),
        width,
        height
      });
      return;
    }
    cropper.setCropBoxData({
      left: canvas.left,
      top: canvas.top,
      width: canvas.width,
      height: canvas.height
    });
  }

  function setAspectMode(mode) {
    currentAspectMode = mode;
    document.querySelectorAll('[data-aspect]').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.aspect === mode);
    });
    if (!cropper) return;
    cropper.setAspectRatio(aspectRatioForMode(mode));
    fitCropBoxToCanvas();
  }

  function updateTonePreview() {
    const brightness = 100 + Number(qs('#imageBrightnessRange').value || 0);
    const contrast = 100 + Number(qs('#imageContrastRange').value || 0);
    const filter = `brightness(${brightness}%) contrast(${contrast}%)`;
    document.querySelectorAll('.open-image-editor-shell img').forEach((imgEl) => {
      imgEl.style.filter = filter;
    });
  }

  async function processFile(file) {
    try {
      if (images.length >= MAX_IMAGES) {
        setStatus(`You can add up to ${MAX_IMAGES} images.`);
        return;
      }
      const sha256 = await hashFile(file);
      if (images.some(img => img.sha256 === sha256)) {
        return;
      }
      const blob = await compressBlobToJpeg(file);
      if (blob.size > 2 * 1024 * 1024) {
        setStatus('Image exceeds 2MB after compression. Try smaller dimensions.');
        return;
      }
      const previewImage = await blobToImage(blob);
      const url = URL.createObjectURL(blob);
      const img = {
        filename: file.name,
        sha256,
        blob,
        url,
        width: previewImage.width,
        height: previewImage.height,
        ebay_image_url: null,
        is_main: images.length === 0
      };
      images.push(img);
      renderImageList();
      selectImage(images.length - 1);
      if (draft && draft.id) {
        await uploadImage(img);
      } else {
        setStatus('Image ready locally. Click Save Draft to upload it.');
      }
    } catch (err) {
      setStatus(`Failed to process image ${file.name}. If it's HEIC/HEIF, convert to JPG first.`);
    }
  }

  async function uploadImage(img, options = {}) {
    const {deferSave = false} = options;
    await ensureDraftExists();
    const previousDraft = draft || {};
    const formData = new FormData();
    formData.append('draft_id', draft.id);
    formData.append('filename', img.filename);
    formData.append('sha256', img.sha256);
    formData.append('width', img.width);
    formData.append('height', img.height);
    if (img.replace_existing && selectedImageIndex !== null) {
      formData.append('replace_index', selectedImageIndex);
    }
    formData.append('image', img.blob, img.filename || 'image.jpg');

    const uploadResp = await fetch(config.imageUploadUrl, {
      method: 'POST',
      body: formData
    });
    const uploadData = await uploadResp.json();
    if (!uploadData.ok) {
      setStatus(`Image upload failed: ${uploadData.details || uploadData.error || 'unknown error'}`);
      return;
    }
    img.cloudinary_url = uploadData.image.cloudinary_url || uploadData.image.image_url;
    img.cloudinary_public_id = uploadData.image.cloudinary_public_id;
    img.image_url = uploadData.image.image_url || img.cloudinary_url;
    img.ebay_image_url = uploadData.image.ebay_image_url || null;
    img.url = img.cloudinary_url || img.url;
    delete img.replace_existing;
    draft = {
      ...uploadData.draft,
      category_id: previousDraft.category_id || uploadData.draft.category_id || null,
      item_specifics: previousDraft.item_specifics || uploadData.draft.item_specifics || {}
    };
    renderImageList();
    setStatus('Image saved to Cloudinary. It will upload to eBay when you publish.');
    if (!deferSave) {
      debounceSave();
    }
  }

  function renderImageList() {
    const list = qs('#imageList');
    list.innerHTML = '';
    images.forEach((img, index) => {
      const card = document.createElement('div');
      card.className = `image-card ${index === selectedImageIndex ? 'selected' : ''}`;
      card.draggable = true;
      card.dataset.index = index;
      const label = index === 0 || img.is_main ? 'Main image' : `Image ${index + 1}`;
      card.innerHTML = `
        <img src="${escapeHtml(img.url)}" alt="">
        <div class="image-card-info">
          <div class="image-card-title">${escapeHtml(img.filename || label)}</div>
          <div class="image-card-meta">
            <span class="${index === 0 ? 'image-main-badge' : ''}">${escapeHtml(label)}</span>
            <span>${img.cloudinary_url || img.image_url ? 'Saved' : 'Pending'}</span>
          </div>
          <div class="image-card-actions">
            <button class="btn btn-small" data-action="main" title="Set as main image"><i class="${index === 0 ? 'fas' : 'far'} fa-star"></i></button>
            <button class="btn btn-small" data-action="up" title="Move up"><i class="fas fa-arrow-up"></i></button>
            <button class="btn btn-small" data-action="down" title="Move down"><i class="fas fa-arrow-down"></i></button>
            <button class="btn btn-small danger" data-action="delete" title="Delete image"><i class="fas fa-trash"></i></button>
          </div>
        </div>
      `;
      card.addEventListener('click', (e) => {
        e.stopPropagation();
        selectImage(index);
      });
      card.addEventListener('dragstart', (e) => {
        e.stopPropagation();
        e.dataTransfer.setData('text/plain', index.toString());
      });
      card.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.stopPropagation();
      });
      card.addEventListener('drop', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const from = parseInt(e.dataTransfer.getData('text/plain'), 10);
        const to = parseInt(card.dataset.index, 10);
        if (Number.isNaN(from) || Number.isNaN(to) || from === to) return;
        const moved = images.splice(from, 1)[0];
        images.splice(to, 0, moved);
        normalizeMainImage();
        selectedImageIndex = to;
        renderImageList();
        if (images[selectedImageIndex]) ensureOpenImageEditor(images[selectedImageIndex]);
        debounceSave();
      });
      card.querySelector('[data-action="main"]').addEventListener('click', (e) => {
        e.stopPropagation();
        images.forEach(i => i.is_main = false);
        img.is_main = true;
        moveImage(index, 0);
      });
      card.querySelector('[data-action="up"]').addEventListener('click', (e) => {
        e.stopPropagation();
        moveImage(index, index - 1);
      });
      card.querySelector('[data-action="down"]').addEventListener('click', (e) => {
        e.stopPropagation();
        moveImage(index, index + 1);
      });
      card.querySelector('[data-action="delete"]').addEventListener('click', (e) => {
        e.stopPropagation();
        deleteImageAt(index);
      });
      list.appendChild(card);
    });
    if (images.length < MAX_IMAGES) {
      const addTile = document.createElement('button');
      addTile.type = 'button';
      addTile.className = 'image-add-tile';
      addTile.id = 'imageAddTile';
      addTile.innerHTML = `
        <i class="far fa-images"></i>
        <strong>${images.length ? 'Add more images' : 'Add listing images'}</strong>
        <span>${images.length}/${MAX_IMAGES} used. Click or drop here.</span>
      `;
      addTile.addEventListener('click', (e) => {
        e.stopPropagation();
        qs('#imageInput').click();
      });
      list.appendChild(addTile);
    }
  }

  function normalizeMainImage() {
    images.forEach((image, idx) => {
      image.is_main = idx === 0;
    });
  }

  function moveImage(from, to) {
    if (to < 0 || to >= images.length || from === to) return;
    const moved = images.splice(from, 1)[0];
    images.splice(to, 0, moved);
    normalizeMainImage();
    selectedImageIndex = to;
    renderImageList();
    const img = images[selectedImageIndex];
    if (img) ensureOpenImageEditor(img);
    debounceSave();
  }

  function deleteImageAt(index) {
    const removed = images.splice(index, 1)[0];
    if (removed && removed.url && removed.url.startsWith('blob:')) {
      URL.revokeObjectURL(removed.url);
    }
    normalizeMainImage();
    if (!images.length) {
      selectedImageIndex = null;
      destroyImageEditor();
      const imageEl = qs('#cropperImage');
      const emptyEl = qs('#imageEmptyState');
      if (imageEl) {
        imageEl.removeAttribute('src');
        imageEl.style.display = 'none';
      }
      if (emptyEl) emptyEl.style.display = 'flex';
    } else {
      selectedImageIndex = Math.min(index, images.length - 1);
      ensureOpenImageEditor(images[selectedImageIndex]);
    }
    renderImageList();
    debounceSave();
  }

  function deleteSelectedImage() {
    if (selectedImageIndex === null) return;
    deleteImageAt(selectedImageIndex);
  }

  function selectImage(index) {
    selectedImageIndex = index;
    const img = images[index];
    if (!img) return;
    renderImageList();
    ensureOpenImageEditor(img);
  }

  async function applyEditsToSelected() {
    if (selectedImageIndex === null || !cropper) return;
    try {
      const canvas = cropper.getCroppedCanvas({
        fillColor: '#ffffff',
        imageSmoothingEnabled: true,
        imageSmoothingQuality: 'high'
      });
      if (!canvas) {
        setStatus('Could not export this image from the editor.');
        return;
      }
      const rawBlob = await encodeCanvasToJpeg(canvas);
      const resizeValue = qs('#resizeSelect').value;
      const tone = {
        brightness: Number(qs('#imageBrightnessRange').value || 0),
        contrast: Number(qs('#imageContrastRange').value || 0)
      };
      const blob = await compressBlobToJpeg(rawBlob, resizeValue, tone);
      if (blob.size > 2 * 1024 * 1024) {
        setStatus('Image exceeds 2MB after export. Try a smaller resize option.');
        return;
      }
      const previewImage = await blobToImage(blob);
      const url = URL.createObjectURL(blob);
      const img = images[selectedImageIndex];
      img.blob = blob;
      img.url = url;
      img.width = previewImage.width;
      img.height = previewImage.height;
      img.sha256 = await hashFile(blob);
      img.ebay_image_url = null;
      img.replace_existing = true;
      renderImageList();
      ensureOpenImageEditor(img);
      if (draft && draft.id) {
        await uploadImage(img);
      } else {
        delete img.replace_existing;
        setStatus('Image edits are ready locally. Click Save Draft to upload them.');
      }
    } catch (err) {
      setStatus('Could not export this image. If it was loaded from a saved eBay URL, re-add the original file and edit it locally.');
    }
  }

  qs('#categorySearchBtn').addEventListener('click', searchCategories);
  qs('#categorySearchInput').addEventListener('input', scheduleCategorySearch);
  qs('#categorySearchInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      searchCategories();
    }
  });
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.category-picker')) {
      renderAutocomplete([]);
    }
  });
  qs('#refreshSpecificsBtn').addEventListener('click', refreshSpecifics);
  qs('#optimizeTitleBtn').addEventListener('click', optimizeTitleWithAi);
  qs('#listingProfitCalcBtn').addEventListener('click', openProfitCalcFromListing);
  qs('#generateDescriptionBtn').addEventListener('click', generateDescriptionWithAi);
  qs('#fillSpecificsAiBtn').addEventListener('click', fillSpecificsWithAi);
  qs('#generateSkuBtn').addEventListener('click', () => {
    qs('#skuInput').value = generateSku();
    debounceSave();
  });

  const imageDropzone = qs('#imageDropzone');
  imageDropzone.addEventListener('click', (e) => {
    if (e.target && e.target.id === 'imageInput') return;
    if (e.target.closest('.image-card') || e.target.closest('.image-add-tile')) return;
    qs('#imageInput').click();
  });
  imageDropzone.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      qs('#imageInput').click();
    }
  });
  imageDropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    imageDropzone.classList.add('dragging');
  });
  imageDropzone.addEventListener('dragleave', () => {
    imageDropzone.classList.remove('dragging');
  });
  imageDropzone.addEventListener('drop', async (e) => {
    e.preventDefault();
    imageDropzone.classList.remove('dragging');
    const files = Array.from(e.dataTransfer.files || []).filter(file => file.type.startsWith('image/'));
    for (const file of files) {
      await processFile(file);
    }
  });

  qs('#imageInput').addEventListener('change', async (e) => {
    const files = Array.from(e.target.files || []);
    for (const file of files) {
      await processFile(file);
    }
    e.target.value = '';
  });

  qs('#applyEditsBtn').addEventListener('click', applyEditsToSelected);
  qs('#deleteImageBtn').addEventListener('click', deleteSelectedImage);
  qs('#imageBrightnessRange').addEventListener('input', updateTonePreview);
  qs('#imageContrastRange').addEventListener('input', updateTonePreview);
  qs('#cropResetBtn').addEventListener('click', () => {
    if (!cropper) return;
    cropper.reset();
    flipX = 1;
    flipY = 1;
    qs('#imageBrightnessRange').value = '0';
    qs('#imageContrastRange').value = '0';
    updateTonePreview();
    setAspectMode(currentAspectMode);
  });
  document.querySelectorAll('[data-aspect]').forEach((btn) => {
    btn.addEventListener('click', () => setAspectMode(btn.dataset.aspect));
  });
  qs('#rotateLeftBtn').addEventListener('click', () => {
    if (cropper) cropper.rotate(-90);
  });
  qs('#rotateRightBtn').addEventListener('click', () => {
    if (cropper) cropper.rotate(90);
  });
  qs('#flipHorizontalBtn').addEventListener('click', () => {
    if (!cropper) return;
    flipX *= -1;
    cropper.scaleX(flipX);
  });
  qs('#flipVerticalBtn').addEventListener('click', () => {
    if (!cropper) return;
    flipY *= -1;
    cropper.scaleY(flipY);
  });

  qs('#saveDraftBtn').addEventListener('click', async () => {
    await saveDraft({createIfMissing: true});
    qs('#publishStatus').textContent = 'Draft saved.';
  });

  qs('#publishBtn').addEventListener('click', async () => {
    qs('#publishStatus').textContent = 'Publishing...';
    await saveDraft({createIfMissing: true});
    const res = await fetch(`${config.draftBaseUrl}/${draft.id}/publish`, {method: 'POST'});
    const data = await res.json();
    if (data.ok) {
      qs('#publishStatus').textContent = `Published! Listing ID: ${data.draft.ebay_listing_id || 'N/A'}`;
    } else {
      qs('#publishStatus').textContent = `Publish failed: ${JSON.stringify(data.errors || data.error)}`;
    }
  });

  async function init() {
    await loadDraftFromUrl();
    renderDraftToInputs();
    if (draft && draft.images && draft.images.length) {
      images = draft.images.map((img) => ({
        filename: img.filename,
        sha256: img.sha256,
        width: img.width,
        height: img.height,
        cloudinary_url: img.cloudinary_url || img.image_url,
        cloudinary_public_id: img.cloudinary_public_id,
        image_url: img.image_url || img.cloudinary_url || img.ebay_image_url,
        ebay_image_url: img.ebay_image_url,
        ebay_image_location: img.ebay_image_location,
        url: img.cloudinary_url || img.image_url || img.ebay_image_url,
        is_main: img.is_main || false
      }));
      renderImageList();
      selectImage(0);
    } else {
      renderImageList();
    }
    bindInputAutosave();
    setupEditorToggle();
    await loadPolicies();
    await loadLocations();
    await loadCategoryPicker();
  }

  init();
})();
