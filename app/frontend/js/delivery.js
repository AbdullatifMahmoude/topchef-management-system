(function () {
  const page = document.getElementById("page-delivery");

  // ===== ELEMENTS =====
  const modal         = page.querySelector(".delivery_modal");
  const modalTitle    = page.querySelector(".logo_title_modal_delivery h1");
  const deliveryForm  = page.querySelector(".delivery_form");
  const fullNameInput = deliveryForm.querySelector("#full_name_input");
  const nameInput     = deliveryForm.querySelector("#username_input");
  const phoneInput    = deliveryForm.querySelector("input[placeholder='رقم التليفون']");
  const passwordInput = deliveryForm.querySelector("input[placeholder='كلمه السر']");
  const roleSelect    = page.querySelector("#role");
  const warningModal  = page.querySelector(".warning_modal");

  let allUsers      = [];
  let currentEditId = null;
  let pendingDeleteId = null;
  const currentUserId = Number(localStorage.getItem("user_id"));
  const escapeUserText = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" })[char]);

  // ===== REAL-TIME VALIDATION =====
  fullNameInput.addEventListener("input", () => validateField(fullNameInput, "username"));
  nameInput.addEventListener("input",     () => validateField(nameInput, "username"));
  phoneInput.addEventListener("input",    () => validateField(phoneInput, "phone"));
  passwordInput.addEventListener("input", () => {
    if (currentEditId) {
      validateOptionalField(passwordInput, "password");
    } else {
      validateField(passwordInput, "password");
    }
  });

  // ===== API FUNCTIONS =====
  async function loadUsers() {
    const tbody = page.querySelector(".orders_table_delivery tbody");
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:24px;opacity:.6">جاري التحميل...</td></tr>';
    try {
      const res = await apiFetch("/user/users");
      if (!res.ok) { console.error("users error:", res.status); return; }
      const data = await res.json();
      allUsers = Array.isArray(data) ? data : (data.data ?? []);
      updateUsersSummary();
      applyUsersFilters();
      // تحديث قائمة الدليفري عبر السيرفر يتم مباشرة عند الحاجة في لوحة الكاشير
    } catch (err) {
      console.error("فشل تحميل المستخدمين:", err);
      page.querySelector(".orders_table_delivery tbody").innerHTML = '<tr><td colspan="6" style="text-align:center;padding:24px;color:red">خطأ في جلب البيانات</td></tr>';
    }
  }

  async function addUser(body) {
    try {
      const res = await apiFetch("/user/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) { closeModal(); loadUsers(); }
      else {
        const err = await res.json();
        alert("فشل إضافة المستخدم: " + JSON.stringify(err));
      }
    } catch (err) { console.error("خطأ في الإضافة:", err); }
  }

  async function updateUser(id, body) {
    try {
      const res = await apiFetch("/user/users/" + id, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) { closeModal(); loadUsers(); }
      else {
        const err = await res.json();
        alert("فشل تعديل المستخدم: " + JSON.stringify(err));
      }
    } catch (err) { console.error("خطأ في التعديل:", err); }
  }

  async function deleteUser(id) {
    try {
      const res = await apiFetch("/user/users/" + id, { method: "DELETE" });
      if (res.ok || res.status === 204) { closeWarningModal(); loadUsers(); }
      else alert("فشل الحذف");
    } catch (err) { console.error("خطأ في الحذف:", err); }
  }

  // ===== RENDER TABLE =====
  const roleNames = { admin: "ادمن", delivery: "دليفري", cashier: "كاشير", user: "كاشير" };

  function updateUsersSummary() {
    const roleCount = (role) => allUsers.filter((user) => user.role === role || (role === "cashier" && user.role === "user")).length;
    const active = allUsers.filter((user) => user.is_active).length;
    const set = (id, value) => { const element = document.getElementById(id); if (element) element.textContent = value; };
    set("usersTotalCount", allUsers.length.toLocaleString("ar-EG"));
    set("usersActiveSummary", `${active.toLocaleString("ar-EG")} حساب نشط`);
    set("usersAdminCount", roleCount("admin").toLocaleString("ar-EG"));
    set("usersCashierCount", roleCount("cashier").toLocaleString("ar-EG"));
    set("usersDeliveryCount", roleCount("delivery").toLocaleString("ar-EG"));
    set("usersPausedCount", (allUsers.length - active).toLocaleString("ar-EG"));
  }

  function applyUsersFilters() {
    const query = document.getElementById("usersSearch")?.value.trim().toLowerCase() || "";
    const role = document.getElementById("usersRoleFilter")?.value || "all";
    const status = document.getElementById("usersStatusFilter")?.value || "all";
    const filtered = allUsers.filter((user) => {
      const text = `${user.full_name || ""} ${user.username || ""} ${user.phone || ""}`.toLowerCase();
      const normalizedRole = user.role === "user" ? "cashier" : user.role;
      return (!query || text.includes(query)) && (role === "all" || normalizedRole === role) && (status === "all" || (status === "active" ? user.is_active : !user.is_active));
    });
    renderTable(filtered);
  }

  function renderTable(users) {
    const tbody = page.querySelector(".orders_table_delivery tbody");
    tbody.innerHTML = "";
    document.getElementById("usersTableCaption").textContent = `عرض ${users.length.toLocaleString("ar-EG")} من ${allUsers.length.toLocaleString("ar-EG")} مستخدم`;
    if (!users.length) { tbody.innerHTML = '<tr><td colspan="6" class="users_empty_cell">لا توجد حسابات مطابقة للفلاتر</td></tr>'; return; }
    users.forEach((u) => {
      const isCurrent = Number(u.id) === currentUserId;
      const initial = (u.full_name || u.username || "م").trim().charAt(0);
      const tr = document.createElement("tr");
      tr.innerHTML =
        '<td><div class="user_identity"><i>' + escapeUserText(initial) + '</i><div><strong>' + escapeUserText(u.full_name || u.username) + '</strong><small>' + (isCurrent ? "حسابك الحالي" : escapeUserText("@" + u.username)) + '</small></div></div></td>' +
        "<td>" + escapeUserText(u.username) + "</td>" +
        "<td dir=" + '"ltr"' + ">" + escapeUserText(u.phone) + "</td>" +
        '<td><span class="user_role ' + u.role + '">' + escapeUserText(roleNames[u.role] || u.role) + "</span></td>" +
        '<td><div class="switch_td"><span class="user_status ' + (u.is_active ? "is_active" : "is_paused") + '">' + (u.is_active ? "نشط" : "موقوف") + '</span><div class="switch ' + (u.is_active ? "" : "active") + ' ' + (isCurrent ? "is_locked" : "") + '" data-id="' + u.id + '"><div class="circle"></div></div></div></td>' +
        '<td><div class="event_icons">' +
          (isCurrent ? '<span class="user_protected">محمي</span>' : '<img src="/assets/delete.png" alt="حذف" data-id="' + u.id + '" class="delete_icon" style="cursor:pointer"/>') +
          '<img src="/assets/Edit_light.png" alt="تعديل" data-id="' + u.id + '" class="edit_icon" style="cursor:pointer"/>' +
        '</div></td>';
      tbody.appendChild(tr);
    });
  }

  // ===== EVENT DELEGATION =====
  page.querySelector(".orders_table_delivery tbody").addEventListener("click", async (e) => {
    const deleteBtn = e.target.closest(".delete_icon");
    if (deleteBtn) { showWarningModal(deleteBtn.dataset.id); return; }

    const editBtn = e.target.closest(".edit_icon");
    if (editBtn) { openEditModal(editBtn.dataset.id); return; }

    const sw = e.target.closest(".switch[data-id]");
    if (sw) {
      const id = sw.dataset.id;
      if (Number(id) === currentUserId) { alert("لا يمكن إيقاف حسابك الحالي"); return; }
      const isActive = !sw.classList.contains("active");
      try {
        const res = await apiFetch(`/user/users/${id}/toggle`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_active: isActive }),
        });
        if (res.ok) {
          const user = allUsers.find((item) => Number(item.id) === Number(id));
          if (user) user.is_active = !user.is_active;
          updateUsersSummary(); applyUsersFilters();
        } else {
          alert("فشل تغيير الحالة");
        }
      } catch (err) {
        console.error("خطأ في تغيير الحالة:", err);
      }
      return;
    }
  });

  // ===== OPEN MODAL ADD =====
  page.querySelector(".add_btn_delivery").addEventListener("click", () => {
    currentEditId = null;
    modalTitle.textContent = "أضف مستخدم جديد";
    deliveryForm.reset();
    [fullNameInput, nameInput, phoneInput, passwordInput].forEach(clearFieldState);
    // كلمة السر مطلوبة في الإضافة
    passwordInput.placeholder = "كلمه السر";
    modal.style.display = "flex";
  });

  // ===== OPEN MODAL EDIT =====
  async function openEditModal(id) {
    currentEditId = id;
    modalTitle.textContent = "تعديل المستخدم";
    deliveryForm.reset();
    [fullNameInput, nameInput, phoneInput, passwordInput].forEach(clearFieldState);
    // كلمة السر اختيارية في التعديل
    passwordInput.placeholder = "كلمه السر (اتركها فارغة إن لم تريد تغييرها)";
    modal.style.display = "flex";

    try {
      const res = await apiFetch("/user/users/" + id);
      const u = await res.json();
      fullNameInput.value = u.full_name || '';
      nameInput.value  = u.username;
      phoneInput.value = u.phone;
      roleSelect.value = u.role;
    } catch (err) {
      console.error("فشل جلب بيانات المستخدم:", err);
    }
  }

  // ===== FORM SUBMIT =====
  deliveryForm.addEventListener("submit", (e) => {
    e.preventDefault();
    e.stopPropagation();

    // validate كل الفيلدز — كلها required
    const fullNameValid = validateField(fullNameInput, "username");
    const nameValid     = validateField(nameInput, "username");
    const phoneValid    = validateField(phoneInput, "phone");
    // كلمة السر: required في الإضافة، optional في التعديل
    const passwordValid = currentEditId
      ? validateOptionalField(passwordInput, "password")
      : validateField(passwordInput, "password");

    // الـ API بيطلب 8 حروف على الأقل
    if (passwordInput.value.trim() && passwordInput.value.trim().length < 8) {
      setFieldState(passwordInput, "error", "كلمة المرور: 8 أحرف على الأقل");
      return;
    }

    if (!fullNameValid || !nameValid || !phoneValid || !passwordValid) return;

    const full_name = fullNameInput.value.trim();
    const username  = nameInput.value.trim();
    const phone     = phoneInput.value.trim();
    const password  = passwordInput.value.trim();
    const role      = roleSelect.value;

    const body = { full_name, username, phone, role };
    if (password) body.password = password;

    currentEditId ? updateUser(currentEditId, body) : addUser(body);
  });

  // ===== CLOSE MODAL =====
  modal.querySelector(".exit img").addEventListener("click", closeModal);
  page.querySelector(".cancel_category_btn").addEventListener("click", closeModal);

  function closeModal() {
    modal.style.display = "none";
    currentEditId = null;
    deliveryForm.reset();
    [fullNameInput, nameInput, phoneInput, passwordInput].forEach(clearFieldState);
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
    if (Number(pendingDeleteId) === currentUserId) return alert("لا يمكن حذف حسابك الحالي");
    if (pendingDeleteId) deleteUser(pendingDeleteId);
  });

  // ===== PASSWORD TOGGLE =====
  const pwWrapper    = page.querySelector(".password_wrapper");
  const toggleBtn    = page.querySelector(".toggle_password");
  const eyeIcon      = page.querySelector(".eye_icon");
  const eyeOffIcon   = page.querySelector(".eye_off_icon");

  toggleBtn.addEventListener("click", () => {
    const isHidden = passwordInput.type === "password";
    passwordInput.type      = isHidden ? "text" : "password";
    eyeIcon.style.display    = isHidden ? "none"  : "block";
    eyeOffIcon.style.display = isHidden ? "block" : "none";
  });

  // ===== EXPOSE GLOBAL =====
  window.refreshUsers = loadUsers;

  document.getElementById("usersSearch")?.addEventListener("input", applyUsersFilters);
  document.getElementById("usersRoleFilter")?.addEventListener("change", applyUsersFilters);
  document.getElementById("usersStatusFilter")?.addEventListener("change", applyUsersFilters);
  document.getElementById("usersResetFilters")?.addEventListener("click", () => {
    document.getElementById("usersSearch").value = "";
    document.getElementById("usersRoleFilter").value = "all";
    document.getElementById("usersStatusFilter").value = "all";
    applyUsersFilters();
  });

  // ===== INIT =====
  loadUsers();
})();
