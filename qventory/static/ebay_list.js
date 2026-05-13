(function() {
  const config = window.EBAY_LIST_CONFIG;
  let draft = null;
  let specificsSchema = null;
  let saveTimer = null;
  let images = [];
  let selectedImageIndex = null;
  let imageEditor = null;

  const qs = (sel) => document.querySelector(sel);

  const wizardStatus = qs('#wizardStatus');

  function setStatus(msg) {
    if (wizardStatus) wizardStatus.textContent = msg;
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

  function debounceSave() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(saveDraft, 800);
  }

  function serializeDraftFromInputs() {
    return {
      title: qs('#titleInput').value.trim(),
      sku: qs('#skuInput').value.trim(),
      condition_id: qs('#conditionInput').value,
      quantity: parseInt(qs('#quantityInput').value || '0', 10),
      price: parseFloat(qs('#priceInput').value || '0'),
      currency: qs('#currencyInput').value,
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
    ['#titleInput', '#skuInput', '#conditionInput', '#quantityInput', '#priceInput', '#currencyInput']
      .forEach(sel => {
        const el = qs(sel);
        el.addEventListener('input', debounceSave);
        el.addEventListener('change', debounceSave);
      });
    qs('#visualEditor').addEventListener('input', debounceSave);
    qs('#descriptionHtmlInput').addEventListener('input', debounceSave);
    ['#fulfillmentPolicySelect', '#paymentPolicySelect', '#returnPolicySelect']
      .forEach(sel => qs(sel).addEventListener('change', debounceSave));
  }

  function renderDraftToInputs() {
    if (!draft) return;
    qs('#titleInput').value = draft.title || '';
    qs('#skuInput').value = draft.sku || '';
    qs('#conditionInput').value = draft.condition_id || '';
    qs('#quantityInput').value = draft.quantity || 1;
    qs('#priceInput').value = draft.price || '';
    qs('#currencyInput').value = draft.currency || 'USD';
    setDescriptionHtml(draft.description_html || '');
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

  async function loadCategoryTree() {
    const res = await fetch(`${config.categoriesUrl}?leaf_only=0`);
    const data = await res.json();
    const categories = data.categories || [];
    renderCategoryTree(categories);
  }

  function renderCategoryTree(categories) {
    const tree = qs('#categoryTree');
    tree.innerHTML = '';
    categories.forEach(cat => {
      const div = document.createElement('div');
      div.className = `category-node ${cat.is_leaf ? 'leaf' : ''}`;
      div.style.marginLeft = `${cat.level * 10}px`;
      div.textContent = cat.full_path;
      div.addEventListener('click', () => selectCategory(cat));
      tree.appendChild(div);
    });
  }

  async function searchCategories() {
    const query = qs('#categorySearchInput').value.trim();
    if (!query) return;
    const url = `${config.categoriesUrl}?query=${encodeURIComponent(query)}&leaf_only=0&limit=20`;
    const res = await fetch(url);
    const data = await res.json();
    renderAutocomplete(data.categories || []);
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
      div.textContent = cat.full_path;
      div.addEventListener('click', () => {
        selectCategory(cat);
        box.style.display = 'none';
      });
      box.appendChild(div);
    });
    box.style.display = 'block';
  }

  async function selectCategory(cat) {
    draft.category_id = cat.category_id;
    qs('#categorySelected').textContent = `Selected: ${cat.full_path}`;
    await fetchSpecifics(cat.category_id);
    debounceSave();
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

  function dataUrlToBlob(dataUrl) {
    const parts = dataUrl.split(',');
    const mimeMatch = parts[0].match(/:(.*?);/);
    const mime = mimeMatch ? mimeMatch[1] : 'image/jpeg';
    const binary = atob(parts[1]);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    return new Blob([bytes], {type: mime});
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

  async function compressBlobToJpeg(blob, maxDimension = null) {
    const image = await blobToImage(blob);
    const ratio = maxDimension && maxDimension !== 'original'
      ? Math.min(1, Number(maxDimension) / Math.max(image.width, image.height))
      : 1;
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(image.width * ratio));
    canvas.height = Math.max(1, Math.round(image.height * ratio));
    const ctx = canvas.getContext('2d');
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    return encodeCanvasToJpeg(canvas);
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
    if (!imageEditor) return;
    try {
      imageEditor.destroy();
    } catch (e) {
      // Ignore editor cleanup failures from partially initialized instances.
    }
    imageEditor = null;
  }

  function imageEditorMenus(img) {
    const menus = ['crop', 'flip', 'rotate'];
    if (img && !img.is_main) {
      menus.push('draw', 'text');
    }
    return menus;
  }

  function ensureToastImageEditor(img) {
    const editorEl = qs('#tuiImageEditor');
    const hintEl = qs('#imageEditorHint');
    if (!editorEl || !window.tui || !window.tui.ImageEditor) {
      if (hintEl) hintEl.textContent = 'Image editor could not load.';
      return;
    }
    destroyImageEditor();
    imageEditor = new window.tui.ImageEditor(editorEl, {
      includeUI: {
        loadImage: {
          path: img.url,
          name: img.filename || 'image'
        },
        menu: imageEditorMenus(img),
        initMenu: 'crop',
        uiSize: {
          width: '100%',
          height: '560px'
        },
        menuBarPosition: 'bottom'
      },
      cssMaxWidth: 900,
      cssMaxHeight: 430,
      usageStatistics: false
    });
    if (hintEl) {
      hintEl.textContent = img.is_main
        ? 'Main image: crop, rotate, flip, brightness, contrast and resize/export.'
        : 'Secondary image: crop, rotate, flip, brightness, contrast, draw, text and resize/export.';
    }
    qs('#toastBrightnessRange').value = '0';
    qs('#toastContrastRange').value = '0';
  }

  async function processFile(file) {
    try {
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
      await uploadImage(img);
    } catch (err) {
      setStatus(`Failed to process image ${file.name}. If it's HEIC/HEIF, convert to JPG first.`);
    }
  }

  async function uploadImage(img) {
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
    img.ebay_image_url = uploadData.image.ebay_image_url;
    delete img.replace_existing;
    draft = uploadData.draft;
    setStatus('Image uploaded to eBay.');
    debounceSave();
  }

  function renderImageList() {
    const list = qs('#imageList');
    list.innerHTML = '';
    images.forEach((img, index) => {
      const card = document.createElement('div');
      card.className = `image-card ${index === selectedImageIndex ? 'selected' : ''}`;
      card.draggable = true;
      card.dataset.index = index;
      card.innerHTML = `
        <img src="${img.url}" alt="">
        <div class="muted">${img.is_main ? 'Main' : ''}</div>
        <button class="btn btn-small" data-action="main">Set Main</button>
      `;
      card.addEventListener('click', () => selectImage(index));
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
      card.querySelector('[data-action="main"]').addEventListener('click', (e) => {
        e.stopPropagation();
        images.forEach(i => i.is_main = false);
        img.is_main = true;
        renderImageList();
        if (selectedImageIndex === index) {
          ensureToastImageEditor(img);
        }
        debounceSave();
      });
      list.appendChild(card);
    });
  }

  function selectImage(index) {
    selectedImageIndex = index;
    const img = images[index];
    if (!img) return;
    renderImageList();
    ensureToastImageEditor(img);
  }

  async function applyEditsToSelected() {
    if (selectedImageIndex === null || !imageEditor) return;
    try {
      let dataUrl;
      try {
        dataUrl = imageEditor.toDataURL({format: 'jpeg', quality: 0.9});
      } catch (e) {
        dataUrl = imageEditor.toDataURL();
      }
      const rawBlob = dataUrlToBlob(dataUrl);
      const resizeValue = qs('#resizeSelect').value;
      const blob = await compressBlobToJpeg(rawBlob, resizeValue);
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
      ensureToastImageEditor(img);
      await uploadImage(img);
    } catch (err) {
      setStatus('Could not export this image. Try re-uploading the original file before editing.');
    }
  }

  async function applyToneAdjustments() {
    if (selectedImageIndex === null || !imageEditor) return;
    const brightness = Number(qs('#toastBrightnessRange').value || 0) / 100;
    const contrast = Number(qs('#toastContrastRange').value || 0) / 100;
    try {
      if (brightness !== 0) {
        await imageEditor.applyFilter('brightness', {brightness});
      }
      if (contrast !== 0) {
        await imageEditor.applyFilter('contrast', {contrast});
      }
      qs('#toastBrightnessRange').value = '0';
      qs('#toastContrastRange').value = '0';
      setStatus('Brightness and contrast applied. Export when ready.');
    } catch (err) {
      setStatus('Could not apply brightness/contrast in the editor.');
    }
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

  qs('#applyEditsBtn').addEventListener('click', applyEditsToSelected);
  qs('#applyToneBtn').addEventListener('click', applyToneAdjustments);

  qs('#saveDraftBtn').addEventListener('click', async () => {
    await saveDraft();
    qs('#publishStatus').textContent = 'Draft saved.';
  });

  qs('#publishBtn').addEventListener('click', async () => {
    qs('#publishStatus').textContent = 'Publishing...';
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
        ebay_image_url: img.ebay_image_url,
        url: img.ebay_image_url,
        is_main: img.is_main || false
      }));
      renderImageList();
      selectImage(0);
    }
    bindInputAutosave();
    setupEditorToggle();
    await loadPolicies();
    await loadLocations();
    await loadCategoryTree();
  }

  init();
})();
