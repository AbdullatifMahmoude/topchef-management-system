(() => {
  const page = document.getElementById("page-expenses");
  if (!page) return;

  const $ = (id) => document.getElementById(id);
  const tbody = $("adminExpensesTable").querySelector("tbody");
  let expenses = [];

  const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[char]);
  const money = (value) => `${Number(value || 0).toLocaleString("ar-EG", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ج.م`;

  function refreshDate(input) {
    window.refreshStableDateInput?.(input);
  }

  function resetForm() {
    $("adminExpenseForm").reset();
    $("adminExpenseId").value = "";
    $("adminExpenseFormTitle").textContent = "تسجيل مصروف جديد";
    $("adminExpenseSubmit").textContent = "حفظ المصروف";
    $("adminExpenseCancelEdit").hidden = true;
    $("adminExpenseDate").disabled = false;
    $("adminExpenseDate").value = $("adminExpensesEnd").value;
    refreshDate($("adminExpenseDate"));
  }

  function render() {
    const query = $("adminExpensesSearch").value.trim().toLowerCase();
    const rows = expenses.filter((item) => !query || `${item.title} ${item.note || ""} ${item.recorded_by || ""}`.toLowerCase().includes(query));
    $("adminExpensesCount").textContent = rows.length.toLocaleString("ar-EG");
    $("adminExpensesTotal").textContent = money(rows.reduce((sum, item) => sum + Number(item.amount || 0), 0));
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="admin_expenses_empty">لا توجد مصاريف مطابقة</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map((item) => `<tr>
      <td>${escapeHtml(item.target_date)}</td>
      <td><strong>${escapeHtml(item.title)}</strong></td>
      <td class="admin_expense_amount">${escapeHtml(money(item.amount))}</td>
      <td>${escapeHtml(item.note || "—")}</td>
      <td>${escapeHtml(item.recorded_by || "—")}</td>
      <td><span class="admin_expense_source ${item.source}">${item.source === "admin" ? "الإدارة" : "الكاشير"}</span></td>
      <td><div class="admin_expense_actions"><button type="button" data-edit-expense="${item.id}">تعديل</button><button type="button" data-delete-expense="${item.id}">حذف</button></div></td>
    </tr>`).join("");
  }

  async function loadExpenses() {
    const start = $("adminExpensesStart").value;
    const end = $("adminExpensesEnd").value;
    if (!start || !end) return;
    tbody.innerHTML = '<tr><td colspan="7" class="admin_expenses_empty">جاري التحميل...</td></tr>';
    try {
      const response = await window.apiFetch(`/shifts/admin/expenses?start_date=${encodeURIComponent(start)}&end_date=${encodeURIComponent(end)}`, { hideLoader: true });
      if (!response.ok) throw new Error("تعذر تحميل المصاريف");
      const data = await response.json();
      expenses = Array.isArray(data.items) ? data.items : [];
      render();
    } catch (error) {
      tbody.innerHTML = `<tr><td colspan="7" class="admin_expenses_empty is_error">${escapeHtml(error.message)}</td></tr>`;
    }
  }

  async function initialise() {
    if ($("adminExpensesStart").value) return loadExpenses();
    let businessDate = new Date().toISOString().slice(0, 10);
    try {
      const response = await window.apiFetch("/shifts/business-date", { hideLoader: true });
      if (response.ok) businessDate = (await response.json()).business_date || businessDate;
    } catch (_) {}
    $("adminExpensesStart").value = businessDate;
    $("adminExpensesEnd").value = businessDate;
    $("adminExpenseDate").value = businessDate;
    [$("adminExpensesStart"), $("adminExpensesEnd"), $("adminExpenseDate")].forEach(refreshDate);
    await loadExpenses();
  }

  $("adminExpenseForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const id = $("adminExpenseId").value;
    const payload = {
      title: $("adminExpenseTitle").value.trim(),
      amount: Number($("adminExpenseAmount").value),
      note: $("adminExpenseNote").value.trim() || null,
      target_date: $("adminExpenseDate").value,
    };
    const submit = $("adminExpenseSubmit");
    submit.disabled = true;
    try {
      const response = await window.apiFetch(id ? `/shifts/admin/expenses/${id}` : "/shifts/admin/expenses", {
        method: id ? "PATCH" : "POST",
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === "string" ? data.detail : "تعذر حفظ المصروف");
      }
      resetForm();
      await loadExpenses();
    } catch (error) {
      alert(error.message);
    } finally {
      submit.disabled = false;
    }
  });

  tbody.addEventListener("click", async (event) => {
    const editButton = event.target.closest("[data-edit-expense]");
    const deleteButton = event.target.closest("[data-delete-expense]");
    const id = Number(editButton?.dataset.editExpense || deleteButton?.dataset.deleteExpense);
    const item = expenses.find((row) => Number(row.id) === id);
    if (!item) return;
    if (editButton) {
      $("adminExpenseId").value = item.id;
      $("adminExpenseTitle").value = item.title;
      $("adminExpenseAmount").value = item.amount;
      $("adminExpenseNote").value = item.note || "";
      $("adminExpenseDate").value = item.target_date;
      $("adminExpenseDate").disabled = !item.editable_date;
      $("adminExpenseFormTitle").textContent = "تعديل المصروف";
      $("adminExpenseSubmit").textContent = "حفظ التعديل";
      $("adminExpenseCancelEdit").hidden = false;
      refreshDate($("adminExpenseDate"));
      $("adminExpenseTitle").focus();
      return;
    }
    if (!confirm(`حذف مصروف «${item.title}»؟`)) return;
    const response = await window.apiFetch(`/shifts/admin/expenses/${id}`, { method: "DELETE" });
    if (response.ok) await loadExpenses();
    else alert("تعذر حذف المصروف");
  });

  $("adminExpenseCancelEdit").addEventListener("click", resetForm);
  $("adminExpensesApply").addEventListener("click", loadExpenses);
  $("adminExpensesSearch").addEventListener("input", render);
  window.refreshAdminExpenses = initialise;
  document.querySelector('[data-page="expenses"]')?.addEventListener("click", initialise);
})();
