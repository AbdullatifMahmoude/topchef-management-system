(function () {
  // ===== ELEMENTS =====
  const modal = document.querySelector("#page-items .modal");
  const modalTitle = document.querySelector("#page-items .logo_title_modal h1");
  const productForm = document.getElementById("productForm");
  const productNameInput = productForm.querySelector("input[placeholder='اسم الصنف']");
  const descInput = document.getElementById("desc_input");
  const catSelect = document.getElementById("cat_select");
  const sizeTypeSelect = document.getElementById("size_type");
  const singlePriceInput = document.getElementById("single_price");
  const singlePriceField = document.querySelector("#page-items .product_single_price");
  const sizesSectionHeading = document.getElementById("sizes_section_heading");
  const multiSizesContainer = document.getElementById("multi_sizes_container");
  const addSizeBtn = document.getElementById("add_size_btn");
  const warningModal = document.querySelector("#page-items .warning_modal");

  let allProducts = [];
  let allCategories = [];
  let productSales = new Map();
  let productChanges = [];
  let currentEditId = null;
  let pendingDeleteId = null;

  // ===== INIT HIDE =====
  singlePriceField.style.display = "none";
  sizesSectionHeading.style.display = "none";
  addSizeBtn.style.display = "none";
  multiSizesContainer.style.display = "none";

  // ===== REAL-TIME VALIDATION =====
  productNameInput.addEventListener("input", () => validateField(productNameInput, "productName"));
  singlePriceInput.addEventListener("input", () => validateField(singlePriceInput, "price"));

  // ===== API FUNCTIONS =====
  async function loadProducts() {
    const tbody = document.querySelector(".orders_table_items tbody");
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:24px;opacity:.6">جاري التحميل...</td></tr>';
    try {
      const res = await apiFetch("/menu/products");
      if (!res.ok) { console.error("products error:", res.status); return; }
      const data = await res.json();
      allProducts = Array.isArray(data) ? data : (data.data ?? []);
      updateItemsSummary();
      applyItemsFilters();
    } catch (err) {
      console.error("فشل تحميل الاصناف:", err);
      document.querySelector(".orders_table_items tbody").innerHTML = '<tr><td colspan="6" style="text-align:center;padding:24px;color:red">خطأ في جلب البيانات</td></tr>';
    }
  }

  async function loadCategories() {
    try {
      const res = await apiFetch("/menu/categories");
      if (!res.ok) { console.error("categories error:", res.status); return; }
      const data = await res.json();
      const cats = Array.isArray(data) ? data : (data.data ?? []);
      allCategories = cats;
      catSelect.innerHTML = '<option value="">اختر التصنيف</option>';
      cats.forEach((cat) => {
        const opt = document.createElement("option");
        opt.value = cat.id;
        opt.textContent = cat.cat_name;
        catSelect.appendChild(opt);
      });
      const filter = document.getElementById("itemsCategoryFilter");
      if (filter) filter.innerHTML = '<option value="all">كل التصنيفات</option>' + cats.map((cat) => `<option value="${cat.id}">${escapeItemsText(cat.cat_name)}</option>`).join("");
    } catch (err) {
      console.error("فشل تحميل التصنيفات:", err);
    }
  }

  async function addProduct(body) {
    try {
      const res = await apiFetch("/menu/products", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        closeModal();
        loadProducts();
      } else {
        const err = await res.json();
        alert("فشل اضافة الصنف: " + JSON.stringify(err));
      }
    } catch (err) {
      console.error("خطا في الاضافة:", err);
    }
  }

  async function updateProduct(id, body) {
    try {
      const res = await apiFetch("/menu/products/" + id, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        closeModal();
        loadProducts();
      } else {
        const err = await res.json();
        alert("فشل تعديل الصنف: " + JSON.stringify(err));
      }
    } catch (err) {
      console.error("خطا في التعديل:", err);
    }
  }

  async function deleteProduct(id) {
    try {
      const res = await apiFetch("/menu/products/" + id, { method: "DELETE" });
      if (res.ok || res.status === 204) {
        closeWarningModal();
        loadProducts();
      } else {
        alert("فشل الحذف");
      }
    } catch (err) {
      console.error("خطا في الحذف:", err);
    }
  }

  async function toggleProduct(id, switchEl) {
    try {
      const res = await apiFetch("/menu/products/" + id + "/toggle", { method: "PATCH", hideLoader: true });
      if (res.ok) {
        const data = await res.json();
        data.is_available ? switchEl.classList.remove("active") : switchEl.classList.add("active");
        const product = allProducts.find((item) => Number(item.id) === Number(id));
        if (product) product.is_available = data.is_available;
        updateItemsSummary();
        applyItemsFilters();
      }
    } catch (err) {
      console.error("خطا في toggle:", err);
    }
  }

  // ===== RENDER TABLE =====
  function renderTable(products) {
    const tbody = document.querySelector(".orders_table_items tbody");
    tbody.innerHTML = "";

    const caption = document.getElementById("itemsTableCaption");
    if (caption) caption.textContent = `عرض ${products.length.toLocaleString("ar-EG")} من ${allProducts.length.toLocaleString("ar-EG")} صنف`;
    if (!products.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="items_empty_cell">لا توجد أصناف مطابقة للفلاتر الحالية</td></tr>';
      return;
    }

    products.forEach((p) => {
      const catOption = catSelect.querySelector('option[value="' + p.cat_id + '"]');
      const catName = catOption ? catOption.textContent : p.cat_id;

      let priceCell = "";
      if (p.variants && p.variants.length === 1) {
        priceCell = parseFloat(p.variants[0].price).toFixed(0) + " ج.م";
      } else if (p.variants && p.variants.length > 1) {
        priceCell = p.variants.map((v) =>
          `<span class="item_price_tag">${escapeItemsText(v.name)}: ${parseFloat(v.price).toFixed(0)} ج.م</span>`
        ).join("");
      } else {
        priceCell = "-";
      }

      const tr = document.createElement("tr");
      tr.classList.add("no_borer_bottom");
      tr.innerHTML =
        '<td><div class="item_identity"><strong>' + escapeItemsText(p.product_name) + '</strong><small>' + escapeItemsText(p.description || "بدون وصف") + '</small></div></td>' +
        '<td><span class="item_category_badge">' + escapeItemsText(catName) + "</span></td>" +
        '<td><span class="item_type_badge">' + ((p.variants || []).length > 1 ? `${p.variants.length} أحجام` : "حجم واحد") + "</span></td>" +
        "<td>" + priceCell + "</td>" +
        '<td class="switch_td">' +
          '<span class="item_availability ' + (p.is_available ? "available" : "paused") + '">' + (p.is_available ? "متاح" : "موقوف") + '</span>' +
          '<div class="switch ' + (p.is_available ? "" : "active") + '" data-id="' + p.id + '">' +
            '<div class="circle"></div>' +
          '</div>' +
        '</td>' +
        '<td><div class="event_icons">' +
          '<img src="/assets/delete.png" alt="حذف" data-id="' + p.id + '" class="delete_icon" style="cursor:pointer"/>' +
          '<img src="/assets/Edit_light.png" alt="تعديل" data-id="' + p.id + '" class="edit_icon" style="cursor:pointer"/>' +
        '</div></td>';
      tbody.appendChild(tr);
    });
  }

  async function loadProductOperations() {
    try {
      const response = await apiFetch("/menu/products/operations", { hideLoader: true });
      if (!response.ok) throw new Error(`operations ${response.status}`);
      const data = await response.json();
      productSales = new Map((data.sales || []).map((entry) => [Number(entry.product_id), entry]));
      productChanges = data.changes || [];
      renderItemsInsights();
    } catch (error) {
      console.error("فشل تحميل أداء الأصناف:", error);
      document.getElementById("itemsTopSelling").innerHTML = '<div class="items_empty_cell">تعذر تحميل الأداء</div>';
      document.getElementById("itemsChangeLog").innerHTML = '<div class="items_empty_cell">تعذر تحميل السجل</div>';
    }
  }

  function escapeItemsText(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  }

  function renderItemsInsights() {
    const ranked = allProducts.map((product) => ({ product, ...(productSales.get(Number(product.id)) || { units_sold: 0, sales: 0 }) })).filter((entry) => Number(entry.units_sold) > 0).sort((a, b) => Number(b.units_sold) - Number(a.units_sold)).slice(0, 5);
    const max = Math.max(...ranked.map((entry) => Number(entry.units_sold)), 1);
    document.getElementById("itemsTopSelling").innerHTML = ranked.length ? ranked.map((entry, index) => `<div class="items_top_row"><p><span><b>${index + 1}</b>${escapeItemsText(entry.product.product_name)}</span><strong>${Number(entry.units_sold).toLocaleString("ar-EG")} وحدة</strong></p><i><b style="width:${Number(entry.units_sold) / max * 100}%"></b></i><small>${Number(entry.sales || 0).toLocaleString("ar-EG", { maximumFractionDigits: 0 })} ج.م مبيعات</small></div>`).join("") : '<div class="items_empty_cell">لا توجد مبيعات خلال آخر 30 يوم</div>';
    document.getElementById("itemsChangeLog").innerHTML = productChanges.length ? productChanges.slice(0, 8).map((change) => {
      const availability = change.change_type === "availability";
      const action = availability ? (change.new_value === "true" ? "فعّل الصنف" : "أوقف الصنف") : "عدّل الأسعار";
      return `<div class="items_change_row"><i class="${availability ? "availability" : "price"}"></i><div><strong>${escapeItemsText(action)} — ${escapeItemsText(change.product_name)}</strong><span>${escapeItemsText(change.changed_by)} • ${new Date(change.created_at).toLocaleString("ar-EG", { dateStyle: "short", timeStyle: "short" })}</span></div></div>`;
    }).join("") : '<div class="items_empty_cell">لا توجد تغييرات مسجلة بعد</div>';
  }

  function productMinimumPrice(product) {
    const prices = (product.variants || []).map((variant) => Number(variant.price)).filter(Number.isFinite);
    return prices.length ? Math.min(...prices) : 0;
  }

  function updateItemsSummary() {
    const available = allProducts.filter((product) => product.is_available).length;
    const variants = allProducts.reduce((sum, product) => sum + (product.variants || []).length, 0);
    const multi = allProducts.filter((product) => (product.variants || []).length > 1).length;
    const set = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };
    set("itemsTotalCount", allProducts.length.toLocaleString("ar-EG"));
    set("itemsCategoryCount", `${allCategories.length.toLocaleString("ar-EG")} تصنيف`);
    set("itemsAvailableCount", available.toLocaleString("ar-EG"));
    set("itemsPausedCount", (allProducts.length - available).toLocaleString("ar-EG"));
    set("itemsAvailabilityRate", `${(allProducts.length ? available / allProducts.length * 100 : 0).toLocaleString("ar-EG", { maximumFractionDigits: 0 })}% من المنيو`);
    set("itemsVariantsCount", variants.toLocaleString("ar-EG"));
    set("itemsMultiSizeCount", `${multi.toLocaleString("ar-EG")} صنف متعدد الأحجام`);
  }

  function applyItemsFilters() {
    const query = document.querySelector("#page-items .search-bar")?.value.trim().toLowerCase() || "";
    const category = document.getElementById("itemsCategoryFilter")?.value || "all";
    const status = document.getElementById("itemsStatusFilter")?.value || "all";
    const type = document.getElementById("itemsTypeFilter")?.value || "all";
    const sort = document.getElementById("itemsSortFilter")?.value || "name";
    const categoryName = (product) => allCategories.find((cat) => Number(cat.id) === Number(product.cat_id))?.cat_name || "";
    const filtered = allProducts.filter((product) => {
      const matchesQuery = !query || product.product_name.toLowerCase().includes(query) || String(product.description || "").toLowerCase().includes(query);
      const matchesCategory = category === "all" || Number(product.cat_id) === Number(category);
      const matchesStatus = status === "all" || (status === "available" ? product.is_available : !product.is_available);
      const isVariant = (product.variants || []).length > 1;
      const matchesType = type === "all" || (type === "variant" ? isVariant : !isVariant);
      return matchesQuery && matchesCategory && matchesStatus && matchesType;
    });
    filtered.sort((a, b) => {
      if (sort === "price_asc") return productMinimumPrice(a) - productMinimumPrice(b);
      if (sort === "price_desc") return productMinimumPrice(b) - productMinimumPrice(a);
      if (sort === "category") return categoryName(a).localeCompare(categoryName(b), "ar");
      return a.product_name.localeCompare(b.product_name, "ar");
    });
    renderTable(filtered);
  }

  // ===== EVENT DELEGATION =====
  document.querySelector(".orders_table_items tbody").addEventListener("click", (e) => {
    const deleteBtn = e.target.closest(".delete_icon");
    if (deleteBtn) { showWarningModal(deleteBtn.dataset.id); return; }

    const editBtn = e.target.closest(".edit_icon");
    if (editBtn) { openEditModal(editBtn.dataset.id); return; }

    const sw = e.target.closest(".orders_table_items .switch");
    if (sw) { toggleProduct(sw.dataset.id, sw); return; }
  });

  // ===== SIZE TYPE LOGIC =====
  sizeTypeSelect.addEventListener("change", () => {
    const val = sizeTypeSelect.value;
    if (val === "one") {
      singlePriceField.style.display = "flex";
      sizesSectionHeading.style.display = "none";
      multiSizesContainer.style.display = "none";
      addSizeBtn.style.display = "none";
      multiSizesContainer.innerHTML = "";
      clearFieldState(singlePriceInput);
    } else if (val === "many") {
      singlePriceField.style.display = "none";
      sizesSectionHeading.style.display = "flex";
      multiSizesContainer.style.display = "block";
      addSizeBtn.style.display = "block";
      clearFieldState(singlePriceInput);
      if (multiSizesContainer.children.length === 0) addSizeRow();
    } else {
      singlePriceField.style.display = "none";
      sizesSectionHeading.style.display = "none";
      multiSizesContainer.style.display = "none";
      addSizeBtn.style.display = "none";
    }
  });

  function addSizeRow(name, price) {
    name = name || "";
    price = price || "";
    const div = document.createElement("div");
    div.classList.add("size_row");
    div.innerHTML =
      '<input type="text" placeholder="السعر" value="' + price + '" class="size_price" />' +
      '<input type="text" placeholder="الحجم" value="' + name + '" class="size_name" />' +
      '<button type="button" class="remove_size_btn" style="margin:0;background:#e74c3c;color:white;border:none;border-radius:6px;width:26px;height:26px;font-size:12px;cursor:pointer;line-height:1;flex-shrink:0;">✕</button>';

    // Real-time validation على الـ size rows
    div.querySelector(".size_price").addEventListener("input", (e) => validateField(e.target, "price"));
    div.querySelector(".size_name").addEventListener("input", (e) => validateField(e.target, "sizeName"));

    div.querySelector(".remove_size_btn").addEventListener("click", () => div.remove());
    multiSizesContainer.appendChild(div);
  }

  addSizeBtn.addEventListener("click", () => addSizeRow());

  // ===== OPEN MODAL ADD =====
  document.querySelector("#page-items .add_btn").addEventListener("click", () => {
    currentEditId = null;
    modalTitle.textContent = "اضف صنف جديد";
    productForm.reset();
    multiSizesContainer.innerHTML = "";
    singlePriceField.style.display = "none";
    sizesSectionHeading.style.display = "none";
    multiSizesContainer.style.display = "none";
    addSizeBtn.style.display = "none";
    [productNameInput, singlePriceInput].forEach(clearFieldState);
    loadCategories();
    modal.style.display = "flex";
  });

  // ===== OPEN MODAL EDIT =====
  async function openEditModal(id) {
    currentEditId = id;
    modalTitle.textContent = "تعديل الصنف";
    productForm.reset();
    multiSizesContainer.innerHTML = "";
    singlePriceField.style.display = "none";
    sizesSectionHeading.style.display = "none";
    multiSizesContainer.style.display = "none";
    addSizeBtn.style.display = "none";
    [productNameInput, singlePriceInput].forEach(clearFieldState);
    await loadCategories();
    modal.style.display = "flex";

    try {
      const res = await apiFetch("/menu/products/" + id);
      const p = await res.json();

      productNameInput.value = p.product_name;
      descInput.value = p.description || "";
      catSelect.value = p.cat_id;

      if (p.variants.length === 1) {
        sizeTypeSelect.value = "one";
        singlePriceField.style.display = "flex";
        sizesSectionHeading.style.display = "none";
        singlePriceInput.value = parseFloat(p.variants[0].price).toFixed(0);
        singlePriceInput.dataset.variantId = p.variants[0].id;
      } else {
        sizeTypeSelect.value = "many";
        multiSizesContainer.style.display = "block";
        sizesSectionHeading.style.display = "flex";
        addSizeBtn.style.display = "block";
        p.variants.forEach((v) => addSizeRow(v.name, parseFloat(v.price).toFixed(0)));
        multiSizesContainer.querySelectorAll(".size_row").forEach((row, i) => {
          row.dataset.variantId = p.variants[i] ? p.variants[i].id : "";
        });
      }
    } catch (err) {
      console.error("فشل جلب بيانات الصنف:", err);
    }
  }

  // ===== FORM SUBMIT =====
  productForm.addEventListener("submit", (e) => {
    e.preventDefault();

    const product_name = productNameInput.value.trim();
    const cat_id = parseInt(catSelect.value);
    const description = descInput.value.trim();
    const sizeType = sizeTypeSelect.value;

    // Validate اسم الصنف
    if (!validateField(productNameInput, "productName")) return;
    if (!cat_id) return alert("يرجى اختيار التصنيف");
    if (!sizeType) return alert("يرجى اختيار نسخة البيع");

    let variants = [];
    let product_type = "simple";

    if (sizeType === "one") {
      // Validate السعر
      if (!validateField(singlePriceInput, "price")) return;
      const price = parseFloat(singlePriceInput.value);
      const variant = { name: product_name, price: price };
      if (currentEditId && singlePriceInput.dataset.variantId) {
        variant.id = parseInt(singlePriceInput.dataset.variantId);
      }
      variants = [variant];
      product_type = "simple";
    } else {
      const rows = multiSizesContainer.querySelectorAll(".size_row");
      if (rows.length === 0) return alert("يرجى اضافة حجم واحد على الاقل");

      let hasError = false;
      rows.forEach((row) => {
        const priceInput = row.querySelector(".size_price");
        const nameInput  = row.querySelector(".size_name");
        const priceValid = validateField(priceInput, "price");
        const nameValid  = validateField(nameInput, "sizeName");
        if (!priceValid || !nameValid) hasError = true;

        const name  = nameInput.value.trim();
        const price = parseFloat(priceInput.value);
        if (name && price) {
          const variant = { name, price };
          if (currentEditId && row.dataset.variantId) {
            variant.id = parseInt(row.dataset.variantId);
          }
          variants.push(variant);
        }
      });

      if (hasError) return;
      if (variants.length === 0) return alert("يرجى ادخال بيانات الاحجام");
      product_type = "variant";
    }

    const body = { cat_id, product_name, product_type, description, variants };
    if (!currentEditId) body.is_available = true;

    if (currentEditId) {
      updateProduct(currentEditId, body);
    } else {
      addProduct(body);
    }
  });

  // ===== CLOSE MODAL =====
  modal.querySelector(".exit img").addEventListener("click", closeModal);

  function closeModal() {
    modal.style.display = "none";
    currentEditId = null;
    productForm.reset();
    multiSizesContainer.innerHTML = "";
    singlePriceField.style.display = "none";
    sizesSectionHeading.style.display = "none";
    multiSizesContainer.style.display = "none";
    addSizeBtn.style.display = "none";
    [productNameInput, singlePriceInput].forEach(clearFieldState);
  }

  // ===== WARNING MODAL =====
  function showWarningModal(id) {
    pendingDeleteId = id;
    warningModal.style.display = "flex";
  }

  function closeWarningModal() {
    warningModal.style.display = "none";
    pendingDeleteId = null;
  }

  warningModal.querySelector(".warning_exit img").addEventListener("click", closeWarningModal);
  warningModal.querySelector(".confirm_btn").addEventListener("click", () => {
    if (pendingDeleteId) deleteProduct(pendingDeleteId);
  });

  // ===== SEARCH =====
  document.querySelector("#page-items .search-bar").addEventListener("input", applyItemsFilters);
  ["itemsCategoryFilter", "itemsStatusFilter", "itemsTypeFilter", "itemsSortFilter"].forEach((id) => document.getElementById(id)?.addEventListener("change", applyItemsFilters));
  document.getElementById("itemsResetFilters")?.addEventListener("click", () => {
    document.querySelector("#page-items .search-bar").value = "";
    ["itemsCategoryFilter", "itemsStatusFilter", "itemsTypeFilter"].forEach((id) => { document.getElementById(id).value = "all"; });
    document.getElementById("itemsSortFilter").value = "name";
    applyItemsFilters();
  });

  // ===== EXPOSE GLOBAL =====
  window.refreshProducts = loadProducts;
  window.refreshCategories = loadCategories;

  // ===== INIT =====
  loadCategories().then(async () => { await loadProducts(); await loadProductOperations(); });
})();
