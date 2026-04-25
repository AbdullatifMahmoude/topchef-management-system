document.addEventListener("DOMContentLoaded", function () {
(function () {
  const page = document.getElementById("page-categories");

  // ===== FETCH ALL CATEGORIES =====
  async function loadCategories() {
    const tbody = page.querySelector(".orders_table tbody");
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:24px;opacity:.6">جاري التحميل...</td></tr>';
    try {
      const [catRes, prodRes] = await Promise.all([
        apiFetch("/menu/categories"),
        apiFetch("/menu/products"),
      ]);

      if (!catRes.ok) { console.error("categories error:", catRes.status); return; }

      const catData  = await catRes.json();
      const categories = Array.isArray(catData) ? catData : (catData.data ?? []);

      let products = [];
      if (prodRes.ok) {
        const prodData = await prodRes.json();
        products = Array.isArray(prodData) ? prodData : (prodData.data ?? []);
      }

      const countMap = {};
      products.forEach((p) => {
        countMap[p.cat_id] = (countMap[p.cat_id] || 0) + 1;
      });

      const enriched = categories.map((cat) => ({
        ...cat,
        items_count: countMap[cat.id] || 0,
      }));

      renderTable(enriched);
    } catch (err) {
      console.error("فشل تحميل التصنيفات:", err);
      page.querySelector(".orders_table tbody").innerHTML = '<tr><td colspan="4" style="text-align:center;padding:24px;color:red">خطأ في جلب البيانات</td></tr>';
    }
  }

  // ===== RENDER TABLE =====
  function renderTable(categories) {
    const tbody = page.querySelector(".orders_table tbody");
    tbody.innerHTML = "";

    categories.forEach((cat) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${cat.cat_name}</td>
        <td>${cat.items_count ?? 0}</td>
        <td class="switch_td">
          <div class="switch ${cat.is_active ? "" : "active"}" data-id="${cat.id}">
            <div class="circle"></div>
          </div>
        </td>
        <td>
          <div class="event_icons">
            <img src="/assets/delete.png" alt="حذف" data-id="${cat.id}" class="delete_icon" style="cursor:pointer"/>
            <img src="/assets/Edit_light.png" alt="تعديل" data-id="${cat.id}" data-name="${cat.cat_name}" data-active="${cat.is_active}" class="edit_icon" style="cursor:pointer"/>
          </div>
        </td>
      `;
      tbody.appendChild(tr);
    });
  }

  // ===== EVENT DELEGATION =====
  page.querySelector(".orders_table tbody").addEventListener("click", (e) => {
    const deleteBtn = e.target.closest(".delete_icon");
    if (deleteBtn) { showWarningModal(deleteBtn.dataset.id); return; }

    const editBtn = e.target.closest(".edit_icon");
    if (editBtn) { openEditModal(editBtn.dataset.id); return; }

    const sw = e.target.closest(".orders_table .switch");
    if (sw) { toggleCategory(sw.dataset.id, sw); return; }
  });

  // ===== TOGGLE CATEGORY =====
  async function toggleCategory(id, switchEl) {
    try {
      const res = await apiFetch(`/menu/categories/${id}/toggle`, { method: "PATCH", hideLoader: true });
      if (res.ok) {
        const data = await res.json();
        data.is_active ? switchEl.classList.remove("active") : switchEl.classList.add("active");
      } else {
        console.error("فشل toggle:", res.status);
      }
    } catch (err) {
      console.error("فشل تغيير الحالة:", err);
    }
  }

  // ===== ADD CATEGORY =====
  async function addCategory(name) {
    try {
      const res = await apiFetch("/menu/categories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cat_name: name }),
      });
      const responseData = await res.json();
      if (res.ok) {
        closeCategoryModal();
        loadCategories();
      } else {
        alert("فشل إضافة التصنيف: " + JSON.stringify(responseData));
      }
    } catch (err) {
      console.error("خطأ في الإضافة:", err);
    }
  }

  // ===== UPDATE CATEGORY =====
  async function updateCategory(id, name) {
    try {
      const res = await apiFetch(`/menu/categories/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cat_name: name }),
      });
      if (res.ok) {
        closeCategoryModal();
        loadCategories();
      } else {
        const err = await res.json();
        alert("فشل تعديل التصنيف: " + JSON.stringify(err));
      }
    } catch (err) {
      console.error("خطأ في التعديل:", err);
    }
  }

  // ===== DELETE CATEGORY =====
  async function deleteCategory(id) {
    try {
      const res = await apiFetch(`/menu/categories/${id}`, { method: "DELETE" });
      if (res.ok) {
        closeWarningModal();
        loadCategories();
      } else {
        const err = await res.json().catch(() => ({}));
        alert("فشل حذف التصنيف: " + JSON.stringify(err));
      }
    } catch (err) {
      console.error("خطأ في الحذف:", err);
    }
  }

  // ===== MODAL LOGIC =====
  let currentEditId = null;
  let pendingDeleteId = null;

  const categoryModal = page.querySelector(".category_modal");
  const warningModal = page.querySelector(".warning_modal");
  const modalInput = categoryModal?.querySelector(".form_category_modal input");
  const modalTitle = categoryModal?.querySelector("h1");
  const saveBtn = categoryModal?.querySelector(".add_category_btn");

  // Real-time validation على الـ input
  modalInput?.addEventListener("input", () => validateField(modalInput, "categoryName"));

  // Open modal for ADD
  page.querySelector(".title_btn .add_category_btn")?.addEventListener("click", () => {
    currentEditId = null;
    modalTitle.textContent = "أضف تصنيف جديد";
    modalInput.value = "";
    clearFieldState(modalInput);
    categoryModal.style.display = "flex";
  });

  // Open modal for EDIT
  async function openEditModal(id) {
    currentEditId = id;
    modalTitle.textContent = "تعديل التصنيف";
    modalInput.value = "";
    clearFieldState(modalInput);
    categoryModal.style.display = "flex";

    try {
      const res = await apiFetch(`/menu/categories/${id}`);
      const cat = await res.json();
      modalInput.value = cat.cat_name;
    } catch (err) {
      console.error("فشل جلب بيانات التصنيف:", err);
    }
  }

  // Save button
  saveBtn?.addEventListener("click", () => {
    const valid = validateField(modalInput, "categoryName");
    if (!valid) return;

    const name = modalInput.value.trim();
    if (currentEditId) {
      updateCategory(currentEditId, name);
    } else {
      addCategory(name);
    }
  });

  // Cancel button
  categoryModal?.querySelector(".cancel_category_btn").addEventListener("click", closeCategoryModal);

  // Exit icon
  categoryModal?.querySelector(".category_exit img").addEventListener("click", closeCategoryModal);

  function closeCategoryModal() {
    categoryModal.style.display = "none";
    currentEditId = null;
    clearFieldState(modalInput);
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

  warningModal?.querySelector(".warning_exit img").addEventListener("click", closeWarningModal);
  warningModal?.querySelector(".confirm_btn").addEventListener("click", () => {
    if (pendingDeleteId) deleteCategory(pendingDeleteId);
  });

  // ===== INIT =====
  loadCategories();
})();
}); // DOMContentLoaded