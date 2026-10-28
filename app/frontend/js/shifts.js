let shiftsRefreshTimer = null;
let shiftsData = [];
let selectedShift = null;
let shiftBusinessDatePromise = null;

const shiftMoney = (value) => `${Number(value || 0).toLocaleString("ar-EG", { maximumFractionDigits: 2 })} ج.م`;
const shiftNumber = (value) => Number(value || 0).toLocaleString("ar-EG");
const shiftEscape = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
const shiftTime = (value) => value ? new Date(value).toLocaleTimeString("ar-EG", { hour: "2-digit", minute: "2-digit" }) : "—";
const shiftDuration = (minutes) => {
  const total = Number(minutes || 0), hours = Math.floor(total / 60), rest = total % 60;
  if (!hours) return `${shiftNumber(rest)} دقيقة`;
  return `${shiftNumber(hours)} س ${shiftNumber(rest)} د`;
};

document.addEventListener("DOMContentLoaded", () => {
  const dateInput = document.getElementById("shiftsDateFilter");
  if (dateInput) initializeShiftBusinessDate();
  document.getElementById("shiftsDateBtn")?.addEventListener("click", fetchShiftsReport);
  document.getElementById("shiftsStatusFilter")?.addEventListener("change", renderShiftsTable);
  document.getElementById("shiftsCashierFilter")?.addEventListener("change", renderShiftsTable);
  document.querySelectorAll('.side_btn[data-page="shifts"]').forEach((button) => button.addEventListener("click", () => {
    initializeShiftBusinessDate().then(fetchShiftsReport);
    startShiftsAutoRefresh();
  }));
  document.getElementById("closeShiftDrawer")?.addEventListener("click", closeShiftDrawer);
  document.getElementById("closeShiftDrawerBtn")?.addEventListener("click", closeShiftDrawer);
  document.getElementById("printShiftBtn")?.addEventListener("click", () => {
    document.body.classList.add("printing_shift");
    window.addEventListener("afterprint", () => document.body.classList.remove("printing_shift"), { once: true });
    window.print();
  });
  window.addEventListener("topchef:admin-live", (event) => {
    const payload = event.detail || {};
    if (["SHIFT_CREATED", "SHIFT_UPDATED"].includes(payload.type) && document.getElementById("page-shifts")?.style.display !== "none") {
      fetchShiftsReport();
    }
  });
});

function initializeShiftBusinessDate() {
  if (shiftBusinessDatePromise) return shiftBusinessDatePromise;
  shiftBusinessDatePromise = window.apiFetch("/shifts/business-date", { hideLoader: true })
    .then(async (response) => {
      if (!response.ok) throw new Error("Failed to fetch business date");
      const data = await response.json();
      const dateInput = document.getElementById("shiftsDateFilter");
      if (dateInput && data.business_date) {
        dateInput.value = data.business_date;
        window.refreshStableDateInput?.(dateInput);
      }
    })
    .catch((error) => {
      console.error("Error fetching shift business date:", error);
      const now = new Date();
      if (now.getHours() < 7) now.setDate(now.getDate() - 1);
      const dateInput = document.getElementById("shiftsDateFilter");
      if (dateInput && !dateInput.value) {
        const localDate = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
        dateInput.value = localDate;
        window.refreshStableDateInput?.(dateInput);
      }
    });
  return shiftBusinessDatePromise;
}

function startShiftsAutoRefresh() {
  if (shiftsRefreshTimer) return;
  shiftsRefreshTimer = setInterval(() => {
    const page = document.getElementById("page-shifts");
    if (page && page.style.display !== "none") fetchShiftsReport();
  }, 60000);
}

async function fetchShiftsReport() {
  const tbody = document.querySelector("#shifts_table tbody");
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="8" class="shift_empty_cell">جاري تحميل الشيفتات...</td></tr>';
  try {
    const date = document.getElementById("shiftsDateFilter").value;
    const response = await window.apiFetch(`/shifts?target_date=${date}`, { hideLoader: true });
    if (!response.ok) throw new Error("Failed to fetch shifts");
    shiftsData = await response.json();
    updateShiftDashboard();
  } catch (error) {
    console.error("Error fetching shifts:", error);
    tbody.innerHTML = '<tr><td colspan="8" class="shift_empty_cell is_error">حدث خطأ أثناء جلب بيانات الشيفتات</td></tr>';
  }
}

function updateShiftDashboard() {
  const totalSales = shiftsData.reduce((sum, shift) => sum + Number(shift.total_sales || 0), 0);
  const totalOrders = shiftsData.reduce((sum, shift) => sum + Number(shift.total_orders || 0), 0);
  const active = shiftsData.filter((shift) => shift.status === "active" || !shift.end_time);
  const closed = shiftsData.length - active.length;
  const set = (id, value) => { const element = document.getElementById(id); if (element) element.textContent = value; };
  set("shiftsTotalCount", shiftNumber(shiftsData.length));
  set("shiftsClosedCount", `${shiftNumber(closed)} شيفت مغلق`);
  set("shiftsActiveCount", shiftNumber(active.length));
  set("shiftsActiveCashiers", active.length ? active.map((shift) => shift.cashier_name).join("، ") : "لا يوجد كاشير نشط");
  set("shiftsTotalSales", shiftMoney(totalSales));
  set("shiftsTotalOrders", shiftNumber(totalOrders));
  set("shiftsAverageOrder", `متوسط الطلب ${shiftMoney(totalOrders ? totalSales / totalOrders : 0)}`);
  renderActiveShift(active);
  renderShiftPerformance();
  updateCashierFilter();
  renderShiftsTable();
}

function renderActiveShift(activeShifts) {
  const target = document.getElementById("activeShiftContent");
  const badge = document.getElementById("activeShiftBadge");
  if (!activeShifts.length) {
    badge.textContent = "غير نشط"; badge.className = "";
    target.className = "active_shift_empty"; target.textContent = "لا يوجد شيفت مفتوح حاليًا"; return;
  }
  const shift = activeShifts.slice().sort((a, b) => new Date(b.start_time) - new Date(a.start_time))[0];
  const needsReview = Number(shift.duration_minutes || 0) >= 720;
  badge.textContent = needsReview ? "يحتاج مراجعة" : "نشط الآن";
  badge.className = needsReview ? "needs_review" : "active";
  target.className = "active_shift_content";
  target.innerHTML = `<div class="active_cashier"><span>الكاشير الحالي</span><strong>${shiftEscape(shift.cashier_name)}</strong><small>بدأ ${shiftTime(shift.start_time)} • ${shiftDuration(shift.duration_minutes)}</small></div><div class="active_shift_metrics"><div><span>الطلبات</span><strong>${shiftNumber(shift.total_orders)}</strong></div><div><span>المبيعات</span><strong>${shiftMoney(shift.total_sales)}</strong></div><div><span>متوسط الطلب</span><strong>${shiftMoney(shift.average_order)}</strong></div></div>`;
}

function renderShiftPerformance() {
  const grouped = new Map();
  shiftsData.forEach((shift) => {
    const current = grouped.get(shift.cashier_name) || { sales: 0, orders: 0 };
    current.sales += Number(shift.total_sales || 0); current.orders += Number(shift.total_orders || 0);
    grouped.set(shift.cashier_name, current);
  });
  const rows = [...grouped.entries()].sort((a, b) => b[1].sales - a[1].sales);
  const max = Math.max(...rows.map(([, value]) => value.sales), 1);
  const target = document.getElementById("shiftPerformanceList");
  target.innerHTML = rows.length ? rows.map(([name, value], index) => `<div class="shift_performance_row"><p><span>${index + 1}. ${shiftEscape(name)}</span><strong>${shiftMoney(value.sales)}</strong></p><i><b style="width:${value.sales / max * 100}%"></b></i><small>${shiftNumber(value.orders)} طلب</small></div>`).join("") : '<div class="active_shift_empty">لا توجد بيانات مقارنة</div>';
}

function updateCashierFilter() {
  const select = document.getElementById("shiftsCashierFilter");
  const current = select.value;
  const names = [...new Set(shiftsData.map((shift) => shift.cashier_name))];
  select.innerHTML = '<option value="all">كل الكاشيرين</option>' + names.map((name) => `<option value="${shiftEscape(name)}">${shiftEscape(name)}</option>`).join("");
  if (names.includes(current)) select.value = current;
}

function renderShiftsTable() {
  const tbody = document.querySelector("#shifts_table tbody");
  if (!tbody) return;
  const status = document.getElementById("shiftsStatusFilter")?.value || "all";
  const cashier = document.getElementById("shiftsCashierFilter")?.value || "all";
  const filtered = shiftsData.filter((shift) => (status === "all" || shift.status === status) && (cashier === "all" || shift.cashier_name === cashier));
  document.getElementById("shiftsTableCaption").textContent = `عرض ${shiftNumber(filtered.length)} من ${shiftNumber(shiftsData.length)} شيفت`;
  if (!filtered.length) { tbody.innerHTML = '<tr><td colspan="8" class="shift_empty_cell">لا توجد شيفتات مطابقة للفلاتر</td></tr>'; return; }
  tbody.innerHTML = filtered.map((shift) => {
    const active = shift.status === "active" || !shift.end_time;
    return `<tr><td><span class="shift_status ${active ? "active" : "closed"}">${active ? "نشط" : "مغلق"}</span></td><td><strong>${shiftEscape(shift.cashier_name)}</strong></td><td>${shiftDuration(shift.duration_minutes)}</td><td><span class="shift_times">${shiftTime(shift.start_time)}<i>←</i>${active ? "الآن" : shiftTime(shift.end_time)}</span></td><td>${shiftNumber(shift.total_orders)}</td><td>${shiftMoney(shift.average_order)}</td><td><strong>${shiftMoney(shift.total_sales)}</strong></td><td><button class="shift_details_btn" type="button" data-shift-id="${shift.id}">عرض</button></td></tr>`;
  }).join("");
  tbody.querySelectorAll("[data-shift-id]").forEach((button) => button.addEventListener("click", () => openShiftDrawer(Number(button.dataset.shiftId))));
}

function openShiftDrawer(id) {
  selectedShift = shiftsData.find((shift) => Number(shift.id) === id);
  if (!selectedShift) return;
  document.getElementById("drawerCashierName").textContent = selectedShift.cashier_name;
  const difference = selectedShift.cash_difference;
  const differenceClass = difference == null ? "" : Number(difference) > 0 ? "cash_difference_positive" : Number(difference) < 0 ? "cash_difference_negative" : "";
  const differenceLabel = difference == null ? "فرق النقدية" : Number(difference) < 0 ? "عجز نقدية بالدرج" : Number(difference) > 0 ? "زيادة نقدية بالدرج" : "نقدية مطابقة تماماً";
  const settledDifference = selectedShift.difference_after_adjustments;
  const settledDifferenceClass = settledDifference == null ? "" : Number(settledDifference) > 0 ? "cash_difference_positive" : Number(settledDifference) < 0 ? "cash_difference_negative" : "";
  const settledDifferenceMetric = selectedShift.cash_tracking_enabled && (selectedShift.post_close_adjustments || []).length && settledDifference != null
    ? `<div class="${settledDifferenceClass}"><span>الفرق بعد تسويات الإدارة المسجلة</span><strong>${shiftMoney(settledDifference)}</strong></div>`
    : "";
  const additions = selectedShift.cash_additions || [];
  const adjustmentRows = selectedShift.cash_tracking_enabled ? (selectedShift.post_close_adjustments || []) : additions;
  const additionHistory = adjustmentRows.length ? adjustmentRows.map((item) => `<li><div><strong>${shiftMoney(item.amount)}</strong><span>${shiftEscape(item.reason)}</span></div><small>${shiftTime(item.created_at)}</small></li>`).join("") : '<li class="is_empty">لا توجد تسويات لاحقة</li>';
  const additionForm = selectedShift.status === "active"
    ? ''
    : selectedShift.actual_closing_cash == null
      ? '<p class="shift_addition_hint">يجب تسجيل النقد الفعلي للشيفت أولاً.</p>'
      : selectedShift.cash_tracking_enabled
        ? `<form id="shiftCashAdditionForm"><label>مبلغ التسوية (+ إضافة / − رد أو تصحيح)<input name="amount" type="number" step="0.01" required></label><label>سبب التسوية<textarea name="reason" minlength="3" maxlength="500" required></textarea></label><button type="submit">تسجيل تسوية لاحقة</button></form>`
        : `<form id="shiftCashAdditionForm"><label>المبلغ الموجود<input name="amount" type="number" min="0.01" step="0.01" required></label><label>سبب الإضافة<textarea name="reason" minlength="2" maxlength="500" required placeholder="مثال: تم العثور على المبلغ داخل درج جانبي"></textarea></label><button type="submit">إضافة المبلغ للشيفت</button></form>`;

  const adminForceCloseSection = selectedShift.status === "active"
    ? `<form class="shift_close_confirmation" id="adminForceCloseForm">
        <header>
          <span class="shift_close_badge" style="border-color:rgba(239,111,108,.3);background:rgba(239,111,108,.12);color:#ef928d;">شيفت معلق / نشط</span>
          <h3>إغلاق الشيفت بواسطة الإدارة</h3>
        </header>
        <p class="shift_close_intro">لو الكاشير غادر أو ترك الوردية مفتوحة، يمكنك إدخال النقد الفعلي وإغلاق الشيفت الآن لمنع تعليق النظام.</p>
        <div class="shift_close_counts">
          <label class="shift_close_admin_count" style="grid-column:1/-1;">
            النقد الفعلي الموجود بالدرج
            <input name="actual_closing_cash" type="number" min="0" step="0.01" inputmode="decimal" placeholder="المبلغ الفعلي بعد العد" required>
          </label>
        </div>
        <label class="shift_close_note">ملاحظة الإغلاق (اختياري)
          <textarea name="closing_note" maxlength="500" rows="2" placeholder="اكتب سبب الإغلاق الإداري"></textarea>
        </label>
        <button type="submit" style="background:#ef8a75;color:#300;">إغلاق الشيفت واعتماد النقد</button>
      </form>`
    : "";

  const confirmation = selectedShift.status !== "active" && selectedShift.close_snapshot_at
    ? selectedShift.admin_confirmed_at
      ? `<section class="shift_close_approved" role="status"><div><span>حالة التسليم</span><strong>تم اعتماد استلام الشيفت من الإدارة</strong><small>${shiftTime(selectedShift.admin_confirmed_at)}</small></div><div class="shift_close_approved_counts"><p><span>عدّ الكاشير</span><strong>${shiftMoney(selectedShift.actual_closing_cash)}</strong></p><p><span>عدّ الإدارة</span><strong>${shiftMoney(selectedShift.admin_count)}</strong></p></div></section>`
      : selectedShift.actual_closing_cash == null
        ? `<p class="shift_close_pending">الإقفال غير مكتمل: الكاشير لم يسجل عدّ النقد بعد.</p>`
        : `<form class="shift_close_confirmation" id="shiftCloseConfirmationForm"><header><span class="shift_close_badge">مطلوب مراجعة الإدارة</span><h3>اعتماد استلام الشيفت</h3></header><p class="shift_close_intro">أعدّ النقد بنفسك، ثم سجّل نتيجة العدّ هنا. الرقم المسجل من الكاشير ظاهر للمقارنة فقط.</p><div class="shift_close_counts"><div class="shift_close_cashier_count"><span>عدّ الكاشير</span><strong>${shiftMoney(selectedShift.actual_closing_cash)}</strong><small>المبلغ الذي سجله عند الإقفال</small></div><label class="shift_close_admin_count">عدّ الإدارة<input name="admin_count" type="number" min="0" step="0.01" inputmode="decimal" placeholder="اكتب المبلغ بعد العدّ" required></label></div><label class="shift_close_note">سبب اختلاف العدّ <small>مطلوب فقط لو عدّ الإدارة مختلف عن عدّ الكاشير</small><textarea name="note" maxlength="500" rows="2" placeholder="اكتب سبب الفرق باختصار"></textarea></label><p class="shift_close_help">لو العدّين متطابقين، اكتب نفس المبلغ في خانة الإدارة واترك الملاحظة فارغة.</p><button type="submit">اعتماد بعد المراجعة</button></form>`
    : "";

  document.getElementById("shiftDrawerContent").innerHTML = `
    <div class="drawer_shift_status">
      <span class="shift_status ${selectedShift.status}">${selectedShift.status === "active" ? "نشط الآن" : "شيفت مغلق"}</span>
      <small>${selectedShift.target_date}</small>
    </div>

    <h3 class="drawer_metrics_heading">وقت الوردية والطلبات</h3>
    <div class="drawer_metrics">
      <div><span>بداية الشيفت</span><strong>${shiftTime(selectedShift.start_time)}</strong></div>
      <div><span>نهاية الشيفت</span><strong>${selectedShift.end_time ? shiftTime(selectedShift.end_time) : "مفتوح"}</strong></div>
      <div><span>مدة الوردية</span><strong>${shiftDuration(selectedShift.duration_minutes)}</strong></div>
      <div><span>إجمالي الطلبات</span><strong>${shiftNumber(selectedShift.total_orders)}</strong></div>
    </div>

    <h3 class="drawer_metrics_heading">حساب نقدية الدرج (الخزينة)</h3>
    <div class="drawer_metrics">
      <div><span>رصيد بداية الشيفت (العهدة)</span><strong>${shiftMoney(selectedShift.opening_cash)}</strong></div>
      <div><span>(+) مبيعات نقدية بالدرج (كاش)</span><strong>${shiftMoney(selectedShift.cash_sales)}</strong></div>
      <div><span>(−) مصروفات نقدية من الدرج</span><strong>${shiftMoney(selectedShift.cash_expenses)}</strong></div>
      <div><span>(=) النقد المتوقع في الدرج</span><strong>${shiftMoney(selectedShift.expected_cash)}</strong></div>
      <div><span>عدّ الكاشير الفعلي عند الإقفال</span><strong>${selectedShift.actual_closing_cash == null ? "غير مسجل بعد" : shiftMoney(selectedShift.actual_closing_cash)}</strong></div>
      <div class="${differenceClass}"><span>${differenceLabel}</span><strong>${difference == null ? "—" : shiftMoney(difference)}</strong></div>
      ${settledDifferenceMetric}
    </div>
    ${Number(selectedShift.unconfirmed_delivery_cash || 0) > 0 ? `<p class="shift_addition_hint">منها ${shiftMoney(selectedShift.unconfirmed_delivery_cash)} نقد دليفري لم يُسجَّل توريده من المندوب وقت الإقفال — راجعه قبل نسبة أي عجز للكاشير.</p>` : ""}
    ${Number(selectedShift.late_cash_expenses || 0) > 0 ? `<p class="shift_addition_hint">مصروفات من الدرج سُجلت بعد الإقفال: ${shiftMoney(selectedShift.late_cash_expenses)} — غير مخصومة من المتوقع؛ لو اتصرفت فعلاً من الدرج سجّلها كتسوية لاحقة.</p>` : ""}

    <h3 class="drawer_metrics_heading" style="margin-top:16px;">المبيعات الإلكترونية (لا تدخل في نقد الدرج)</h3>
    <div class="drawer_metrics">
      <div><span>مبيعات InstaPay</span><strong>${shiftMoney(selectedShift.instapay_sales)}</strong></div>
      <div><span>مبيعات المحفظة الإلكترونية</span><strong>${shiftMoney(selectedShift.wallet_sales)}</strong></div>
    </div>

    <div class="drawer_shift_total" style="margin-top:16px;">
      <span>صافي مبيعات المطعم بالشيفت</span>
      <strong>${shiftMoney(selectedShift.total_sales)}</strong>
    </div>

    ${selectedShift.closing_note ? `<p class="shift_closing_note">ملاحظة التسليم: ${shiftEscape(selectedShift.closing_note)}</p>` : ""}
    ${adminForceCloseSection}
    ${confirmation}
    ${selectedShift.status !== "active" ? `<section class="shift_additions"><h3>تسويات ما بعد الإقفال</h3><ul>${additionHistory}</ul>${additionForm}</section>` : ""}`;

  document.getElementById("shiftCashAdditionForm")?.addEventListener("submit", submitShiftCashAddition);
  document.getElementById("shiftCloseConfirmationForm")?.addEventListener("submit", submitShiftCloseConfirmation);
  document.getElementById("adminForceCloseForm")?.addEventListener("submit", submitAdminForceClose);
  const drawer = document.getElementById("shiftDetailsDrawer");
  drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false");
}

async function submitAdminForceClose(event) {
  event.preventDefault();
  if (!selectedShift) return;
  const form = event.currentTarget;
  const button = form.querySelector("button[type='submit']");
  const actualCash = Number(form.elements.actual_closing_cash.value);
  const note = String(form.elements.closing_note.value || "").trim();
  if (!Number.isFinite(actualCash) || actualCash < 0) {
    window.showToast?.("اكتب المبلغ الفعلي الموجود في الدرج", "error");
    return;
  }
  button.disabled = true;
  try {
    const response = await window.apiFetch(`/shifts/${selectedShift.id}/admin-close`, {
      method: "POST",
      body: JSON.stringify({ actual_closing_cash: actualCash, closing_note: note || null }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === "string" ? data.detail : "تعذر إغلاق الشيفت");
    }
    const id = selectedShift.id;
    await fetchShiftsReport();
    openShiftDrawer(id);
    window.showToast?.("تم إغلاق الشيفت إدارياً وتجميد حساباته", "success");
  } catch (error) {
    window.showToast?.(error.message, "error");
    button.disabled = false;
  }
}

async function submitShiftCloseConfirmation(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type='submit']");
  const adminCountValue = String(form.elements.admin_count.value || "").trim();
  const adminCount = Number(adminCountValue);
  const note = String(form.elements.note.value || "").trim();
  if (!adminCountValue || !Number.isFinite(adminCount) || adminCount < 0) {
    window.showToast?.("اكتب المبلغ الذي عدّته الإدارة", "error");
    return;
  }
  if (adminCount !== Number(selectedShift.actual_closing_cash) && !note) {
    window.showToast?.("اكتب سبب اختلاف عدّ الإدارة عن عدّ الكاشير", "error");
    form.elements.note.focus();
    return;
  }
  button.disabled = true;
  try {
    const response = await window.apiFetch(`/shifts/${selectedShift.id}/confirm-close`, {
      method: "POST",
      body: JSON.stringify({ admin_count: adminCount, note: note || null }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === "string" ? data.detail : "تعذر اعتماد التسليم");
    }
    const id = selectedShift.id;
    await fetchShiftsReport();
    openShiftDrawer(id);
    window.showToast?.("تم اعتماد تسليم الشيفت", "success");
  } catch (error) {
    window.showToast?.(error.message, "error");
    button.disabled = false;
  }
}

async function submitShiftCashAddition(event) {
  event.preventDefault();
  if (!selectedShift) return;
  const form = event.currentTarget;
  const button = form.querySelector("button[type='submit']");
  const payload = {
    amount: Number(form.elements.amount.value),
    reason: form.elements.reason.value.trim(),
  };
  if (!Number.isFinite(payload.amount) || (selectedShift.cash_tracking_enabled ? payload.amount === 0 : payload.amount <= 0) || payload.reason.length < 2) return;
  if (selectedShift.cash_tracking_enabled) payload.idempotency_key = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  button.disabled = true;
  try {
    const response = await window.apiFetch(`/shifts/${selectedShift.id}/${selectedShift.cash_tracking_enabled ? "post-close-adjustments" : "cash-additions"}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error("Failed to add recovered cash");
    await fetchShiftsReport();
    openShiftDrawer(selectedShift.id);
    window.showToast?.("تمت إضافة المبلغ وتحديث فرق العهدة", "success");
  } catch (error) {
    console.error("Error adding shift cash:", error);
    window.showToast?.("تعذر إضافة المبلغ للشيفت", "error");
    button.disabled = false;
  }
}

function closeShiftDrawer() {
  const drawer = document.getElementById("shiftDetailsDrawer");
  drawer.classList.remove("open"); drawer.setAttribute("aria-hidden", "true");
}
