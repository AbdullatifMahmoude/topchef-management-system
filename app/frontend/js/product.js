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
  const multiSizesContainer = document.getElementById("multi_sizes_container");
  const addSizeBtn = document.getElementById("add_size_btn");
  const warningModal = document.querySelector("#page-items .warning_modal");

  let allProducts = [];
  let currentEditId = null;
  let pendingDeleteId = null;

  // ===== INIT HIDE =====
  singlePriceInput.style.display = "none";
  addSizeBtn.style.display = "none";
  multiSizesContainer.style.display = "none";

  // ===== REAL-TIME VALIDATION =====
  productNameInput.addEventListener("input", () => validateField(productNameInput, "productName"));
  singlePriceInput.addEventListener("input", () => validateField(singlePriceInput, "price"));

  // ===== API FUNCTIONS =====
  async function loadProducts() {
    const tbody = document.querySelector(".orders_table_items tbody");
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:24px;opacity:.6">جاري التحميل...</td></tr>';
    try {
      const res = await apiFetch("/menu/products");
      if (!res.ok) { console.error("products error:", res.status); return; }
      const data = await res.json();
      allProducts = Array.isArray(data) ? data : (data.data ?? []);
      renderTable(allProducts);
    } catch (err) {
      console.error("فشل تحميل الاصناف:", err);
      document.querySelector(".orders_table_items tbody").innerHTML = '<tr><td colspan="5" style="text-align:center;padding:24px;color:red">خطأ في جلب البيانات</td></tr>';
    }
  }

  async function loadCategories() {
    try {
      const res = await apiFetch("/menu/categories");
      if (!res.ok) { console.error("categories error:", res.status); return; }
      const data = await res.json();
      const cats = Array.isArray(data) ? data : (data.data ?? []);
      catSelect.innerHTML = '<option value="">اختر التصنيف</option>';
      cats.forEach((cat) => {
        const opt = document.createElement("option");
        opt.value = cat.id;
        opt.textContent = cat.cat_name;
        catSelect.appendChild(opt);
      });
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
      }
    } catch (err) {
      console.error("خطا في toggle:", err);
    }
  }

  // ===== RENDER TABLE =====
  function renderTable(products) {
    const tbody = document.querySelector(".orders_table_items tbody");
    tbody.innerHTML = "";

    products.forEach((p) => {
      const catOption = catSelect.querySelector('option[value="' + p.cat_id + '"]');
      const catName = catOption ? catOption.textContent : p.cat_id;

      let priceCell = "";
      if (p.variants && p.variants.length === 1) {
        priceCell = parseFloat(p.variants[0].price).toFixed(0) + " ج.م";
      } else if (p.variants && p.variants.length > 1) {
        priceCell = p.variants.map((v) =>
          '<span style="display:inline-block; background:#C9A84C ;color:#000000; border-radius:6px; padding:2px 8px; margin:2px; font-size:16px;">' +
          v.name + ": " + parseFloat(v.price).toFixed(0) + " ج.م" +
          '</span>'
        ).join("");
      } else {
        priceCell = "-";
      }

      const tr = document.createElement("tr");
      tr.classList.add("no_borer_bottom");
      tr.innerHTML =
        "<td>" + p.product_name + "</td>" +
        "<td>" + catName + "</td>" +
        "<td>" + priceCell + "</td>" +
        '<td class="switch_td">' +
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
      singlePriceInput.style.display = "block";
      multiSizesContainer.style.display = "none";
      addSizeBtn.style.display = "none";
      multiSizesContainer.innerHTML = "";
      clearFieldState(singlePriceInput);
    } else if (val === "many") {
      singlePriceInput.style.display = "none";
      multiSizesContainer.style.display = "block";
      addSizeBtn.style.display = "block";
      clearFieldState(singlePriceInput);
      if (multiSizesContainer.children.length === 0) addSizeRow();
    } else {
      singlePriceInput.style.display = "none";
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
  document.querySelector(".add_btn").addEventListener("click", () => {
    currentEditId = null;
    modalTitle.textContent = "اضف صنف جديد";
    productForm.reset();
    multiSizesContainer.innerHTML = "";
    singlePriceInput.style.display = "none";
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
    singlePriceInput.style.display = "none";
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
        singlePriceInput.style.display = "block";
        singlePriceInput.value = parseFloat(p.variants[0].price).toFixed(0);
        singlePriceInput.dataset.variantId = p.variants[0].id;
      } else {
        sizeTypeSelect.value = "many";
        multiSizesContainer.style.display = "block";
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
    singlePriceInput.style.display = "none";
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
  document.querySelector(".search-bar").addEventListener("input", (e) => {
    const q = e.target.value.trim().toLowerCase();
    const filtered = allProducts.filter((p) =>
      p.product_name.toLowerCase().includes(q)
    );
    renderTable(filtered);
  });

  // ===== INIT =====
  loadCategories().then(() => loadProducts());
})();