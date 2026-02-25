(function() {
  const config = window.EBAY_LIST_CONFIG;
  let draft = null;
  let specificsSchema = null;
  let saveTimer = null;
  let currentImage = null;
  let images = [];

  const qs = (sel) => document.querySelector(sel);
  const qsa = (sel) => Array.from(document.querySelectorAll(sel));

  const wizardStatus = qs('#wizardStatus');
  const steps = qsa('.wizard-step');
  const sections = qsa('.wizard-section');

  function setStatus(msg) {
    if (wizardStatus) wizardStatus.textContent = msg;
  }

  function setActiveStep(step) {
    steps.forEach(btn => btn.classList.toggle('active', btn.dataset.step === step));
    sections.forEach(sec => sec.classList.toggle('active', sec.id === `step-${step}`));
  }

  steps.forEach(btn => {
    btn.addEventListener('click', () => setActiveStep(btn.dataset.step));
  });

  function debounceSave() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(saveDraft, 800);
  }

  function draftUrl(base, id) {
    return `${base}/${id}`;
  }

  async function createDraft() {
    const res = await fetch(config.draftCreateUrl, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({})
    });
    const data = await res.json();
    draft = data.draft;
    setStatus(`Draft #${draft.id} loaded.`);
  }

  async function loadDraftFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const draftId = params.get('draft_id');
    if (!draftId) {
      await createDraft();
      return;
    }
    const res = await fetch(draftUrl(config.draftBaseUrl, draftId));
    if (!res.ok) {
      await createDraft();
      return;
    }
    const data = await res.json();
    draft = data.draft;
    setStatus(`Draft #${draft.id} loaded.`);
  }

  function serializeDraftFromInputs() {
    return {
      title: qs('#titleInput').value.trim(),
      sku: qs('#skuInput').value.trim(),
      condition_id: qs('#conditionInput').value,
      quantity: parseInt(qs('#quantityInput').value || '0', 10),
      price: parseFloat(qs('#priceInput').value || '0'),
      currency: qs('#currencyInput').value,
      description_html: qs('#descriptionHtmlInput').value,
      description_text: qs('#descriptionTextInput').value,
      location: {
        postal_code: qs('#postalInput').value.trim(),
        city: qs('#cityInput').value.trim(),
        state: qs('#stateInput').value.trim(),
        country: qs('#countryInput').value.trim() || 'US',
        merchant_location_key: qs('#merchantLocationKeyInput').value.trim()
      },
      fulfillment_policy_id: qs('#fulfillmentPolicyInput').value.trim(),
      payment_policy_id: qs('#paymentPolicyInput').value.trim(),
      return_policy_id: qs('#returnPolicyInput').value.trim()
    };
  }

  async function saveDraft() {
    if (!draft) return;
    const payload = serializeDraftFromInputs();
    payload.category_id = draft.category_id || null;
    payload.item_specifics = draft.item_specifics || {};
    payload.images = images.map((img, index) => ({
      order: index,
      filename: img.filename,
      sha256: img.sha256,
      width: img.width,
      height: img.height,
      ebay_image_url: img.ebay_image_url,
      is_main: img.is_main || false
    }));
    const res = await fetch(draftUrl(config.draftBaseUrl, draft.id), {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    draft = data.draft;
    setStatus(`Draft #${draft.id} saved at ${new Date().toLocaleTimeString()}`);
  }

  function bindInputAutosave() {
    qsa('#step-basic input, #step-basic textarea, #step-basic select').forEach(el => {
      el.addEventListener('input', debounceSave);
      el.addEventListener('change', debounceSave);
    });
  }

  function renderDraftToInputs() {
    if (!draft) return;
    qs('#titleInput').value = draft.title || '';
    qs('#skuInput').value = draft.sku || '';
    qs('#conditionInput').value = draft.condition_id || '';
    qs('#quantityInput').value = draft.quantity || 1;
    qs('#priceInput').value = draft.price || '';
    qs('#currencyInput').value = draft.currency || 'USD';
    qs('#descriptionHtmlInput').value = draft.description_html || '';
    qs('#descriptionTextInput').value = draft.description_text || '';
    const loc = draft.location || {};
    qs('#postalInput').value = loc.postal_code || '';
    qs('#cityInput').value = loc.city || '';
    qs('#stateInput').value = loc.state || '';
    qs('#countryInput').value = loc.country || 'US';
    qs('#merchantLocationKeyInput').value = loc.merchant_location_key || '';
    const policies = draft.policy_ids || {};
    qs('#fulfillmentPolicyInput').value = policies.fulfillment || '';
    qs('#paymentPolicyInput').value = policies.payment || '';
    qs('#returnPolicyInput').value = policies.return || '';
  }

  async function searchCategories() {
    const query = qs('#categorySearchInput').value.trim();
    if (!query) return;
    const url = `${config.categoriesUrl}?query=${encodeURIComponent(query)}&leaf_only=1&limit=20`;
    const res = await fetch(url);
    const data = await res.json();
    renderCategoryResults(data.categories || []);
  }

  function renderCategoryResults(categories) {
    const container = qs('#categoryResults');
    container.innerHTML = '';
    categories.forEach(cat => {
      const div = document.createElement('div');
      div.className = 'category-item';
      div.textContent = cat.full_path;
      div.addEventListener('click', () => selectCategory(cat));
      container.appendChild(div);
    });
  }

  async function selectCategory(cat) {
    draft.category_id = cat.category_id;
    qs('#categorySelected').textContent = `Selected: ${cat.full_path}`;
    await fetchSpecifics(cat.category_id);
    debounceSave();
  }

  async function fetchSpecifics(categoryId) {
    const url = `${config.specificsUrl}/${categoryId}`;
    const res = await fetch(url);
    const data = await res.json();
    specificsSchema = data.specifics;
    renderSpecificsForm();
  }

  async function refreshSpecifics() {
    if (!draft || !draft.category_id) return;
    const url = `${config.specificsRefreshUrl}/${draft.category_id}`;
    const res = await fetch(url, {method: 'POST'});
    const data = await res.json();
    specificsSchema = data.specifics;
    renderSpecificsForm();
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
      input.setAttribute('data-spec-name', spec.name);
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

  async function loadImageToCanvas(file) {
    const bitmap = await createImageBitmap(file);
    const canvas = qs('#editorCanvas');
    const ctx = canvas.getContext('2d');
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    ctx.drawImage(bitmap, 0, 0);
    return {canvas, ctx, width: bitmap.width, height: bitmap.height};
  }

  function applyAdjustments(canvas, ctx, brightness, contrast, aspect) {
    const width = canvas.width;
    const height = canvas.height;
    let sx = 0, sy = 0, sw = width, sh = height;
    if (aspect && aspect !== 'original') {
      const [aw, ah] = aspect.split(':').map(Number);
      const targetRatio = aw / ah;
      const currentRatio = width / height;
      if (currentRatio > targetRatio) {
        sw = height * targetRatio;
        sx = (width - sw) / 2;
      } else {
        sh = width / targetRatio;
        sy = (height - sh) / 2;
      }
    }
    const tmp = document.createElement('canvas');
    tmp.width = sw;
    tmp.height = sh;
    const tctx = tmp.getContext('2d');
    tctx.drawImage(canvas, sx, sy, sw, sh, 0, 0, sw, sh);
    const imgData = tctx.getImageData(0, 0, sw, sh);
    const data = imgData.data;
    const b = brightness / 100;
    const c = (contrast / 100) + 1;
    const intercept = 128 * (1 - c);
    for (let i = 0; i < data.length; i += 4) {
      data[i] = data[i] * c + intercept + 255 * b;
      data[i + 1] = data[i + 1] * c + intercept + 255 * b;
      data[i + 2] = data[i + 2] * c + intercept + 255 * b;
    }
    tctx.putImageData(imgData, 0, 0);
    return tmp;
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

  async function processFile(file) {
    try {
      const sha256 = await hashFile(file);
      if (images.some(img => img.sha256 === sha256)) {
        return;
      }
      const {canvas} = await loadImageToCanvas(file);
      const aspect = qs('#aspectSelect').value;
      const brightness = parseInt(qs('#brightnessRange').value, 10);
      const contrast = parseInt(qs('#contrastRange').value, 10);
      const processedCanvas = applyAdjustments(canvas, canvas.getContext('2d'), brightness, contrast, aspect);
      const blob = await encodeCanvasToJpeg(processedCanvas);
      if (blob.size > 2 * 1024 * 1024) {
        setStatus('Image exceeds 2MB after compression. Try smaller dimensions.');
        return;
      }
      const url = URL.createObjectURL(blob);
      const img = {
        filename: file.name,
        sha256,
        blob,
        url,
        width: processedCanvas.width,
        height: processedCanvas.height,
        ebay_image_url: null,
        is_main: images.length === 0
      };
      images.push(img);
      renderImageList();
      await uploadImage(img);
    } catch (err) {
      setStatus(`Failed to process image ${file.name}. If it's HEIC/HEIF, convert to JPG first.`);
    }
  }

  async function uploadImage(img) {
    const tokenResp = await fetch(config.uploadTokenUrl, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        draft_id: draft.id,
        filename: img.filename,
        content_type: 'image/jpeg',
        size: img.blob.size,
        sha256: img.sha256
      })
    });
    const tokenData = await tokenResp.json();
    if (!tokenData.ok) return;
    const upload = tokenData.upload;
    const uploadHeaders = upload.headers || {};
    const putResp = await fetch(upload.upload_url, {
      method: 'PUT',
      headers: uploadHeaders,
      body: img.blob
    });
    let imageUrl = null;
    try {
      const json = await putResp.json();
      imageUrl = json.imageUrl || json.image_url || json.url || null;
    } catch (e) {
      imageUrl = putResp.headers.get('Location');
    }
    img.ebay_image_url = imageUrl;
    await fetch(config.imageConfirmUrl, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        draft_id: draft.id,
        image: {
          filename: img.filename,
          sha256: img.sha256,
          width: img.width,
          height: img.height,
          ebay_image_url: img.ebay_image_url,
          upload_session_id: upload.upload_session_id
        }
      })
    });
    debounceSave();
  }

  function renderImageList() {
    const list = qs('#imageList');
    list.innerHTML = '';
    images.forEach((img, index) => {
      const card = document.createElement('div');
      card.className = 'image-card';
      card.draggable = true;
      card.dataset.index = index;
      card.innerHTML = `
        <img src="${img.url}" alt="">
        <div class="muted">${img.is_main ? 'Main' : ''}</div>
        <button class="btn btn-small" data-action="main">Set Main</button>
      `;
      card.addEventListener('dragstart', (e) => {
        e.dataTransfer.setData('text/plain', index.toString());
      });
      card.addEventListener('dragover', (e) => e.preventDefault());
      card.addEventListener('drop', (e) => {
        e.preventDefault();
        const from = parseInt(e.dataTransfer.getData('text/plain'), 10);
        const to = parseInt(card.dataset.index, 10);
        const moved = images.splice(from, 1)[0];
        images.splice(to, 0, moved);
        renderImageList();
        debounceSave();
      });
      card.querySelector('[data-action="main"]').addEventListener('click', () => {
        images.forEach(i => i.is_main = false);
        img.is_main = true;
        renderImageList();
        debounceSave();
      });
      list.appendChild(card);
    });
  }

  qs('#categorySearchBtn').addEventListener('click', searchCategories);
  qs('#categorySearchInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') searchCategories();
  });

  qs('#refreshSpecificsBtn').addEventListener('click', refreshSpecifics);

  qs('#imageInput').addEventListener('change', async (e) => {
    const files = Array.from(e.target.files || []);
    for (const file of files) {
      await processFile(file);
    }
    e.target.value = '';
  });

  qs('#applyEditsBtn').addEventListener('click', () => {
    setStatus('Adjustments apply to newly added images.');
  });

  qs('#validateBtn').addEventListener('click', async () => {
    const res = await fetch(draftUrl(config.draftValidateUrl, draft.id), {method: 'POST'});
    const data = await res.json();
    qs('#publishStatus').textContent = data.ok ? 'Draft valid.' : `Validation errors: ${JSON.stringify(data.errors)}`;
  });

  qs('#publishBtn').addEventListener('click', async () => {
    qs('#publishStatus').textContent = 'Publishing...';
    const res = await fetch(draftUrl(config.draftPublishUrl, draft.id), {method: 'POST'});
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
        ebay_image_url: img.ebay_image_url,
        url: img.ebay_image_url,
        is_main: img.is_main || false
      }));
      renderImageList();
    }
    bindInputAutosave();
  }

  init();
})();
