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
  const additions = selectedShift.cash_additions || [];
  const additionHistory = additions.length ? additions.map((item) => `<li><div><strong>${shiftMoney(item.amount)}</strong><span>${shiftEscape(item.reason)}</span></div><small>${shiftEscape(item.admin_name)} • ${shiftTime(item.created_at)}</small></li>`).join("") : '<li class="is_empty">لا توجد إضافات مسجلة</li>';
  const additionForm = selectedShift.status === "active"
    ? '<p class="shift_addition_hint">يمكن إضافة مبلغ بعد إغلاق الشيفت فقط.</p>'
    : selectedShift.actual_closing_cash == null
      ? '<p class="shift_addition_hint">يجب أن يسجل الكاشير النقد الفعلي أولًا.</p>'
      : `<form id="shiftCashAdditionForm"><label>المبلغ الموجود<input name="amount" type="number" min="0.01" step="0.01" required></label><label>سبب الإضافة<textarea name="reason" minlength="2" maxlength="500" required placeholder="مثال: تم العثور على المبلغ داخل درج جانبي"></textarea></label><button type="submit">إضافة المبلغ للشيفت</button></form>`;
  document.getElementById("shiftDrawerContent").innerHTML = `<div class="drawer_shift_status"><span class="shift_status ${selectedShift.status}">${selectedShift.status === "active" ? "نشط الآن" : "شيفت مغلق"}</span><small>${selectedShift.target_date}</small></div><div class="drawer_metrics"><div><span>بداية الشيفت</span><strong>${shiftTime(selectedShift.start_time)}</strong></div><div><span>نهاية الشيفت</span><strong>${selectedShift.end_time ? shiftTime(selectedShift.end_time) : "مفتوح"}</strong></div><div><span>مدة الشيفت</span><strong>${shiftDuration(selectedShift.duration_minutes)}</strong></div><div><span>إجمالي الطلبات</span><strong>${shiftNumber(selectedShift.total_orders)}</strong></div><div><span>نقدي — حصة المطعم</span><strong>${shiftMoney(selectedShift.cash_sales)}</strong></div><div><span>InstaPay — حصة المطعم</span><strong>${shiftMoney(selectedShift.instapay_sales)}</strong></div><div><span>محفظة — حصة المطعم</span><strong>${shiftMoney(selectedShift.wallet_sales)}</strong></div><div><span>رصيد البداية</span><strong>${shiftMoney(selectedShift.opening_cash)}</strong></div><div><span>مصروفات/سحب</span><strong>${shiftMoney(selectedShift.cash_expenses)}</strong></div><div><span>النقدي المتوقع بعد تسليم الدليفري</span><strong>${shiftMoney(selectedShift.expected_cash)}</strong></div><div><span>النقدي الفعلي عند التسليم</span><strong>${selectedShift.actual_closing_cash == null ? "لم يُسلّم" : shiftMoney(selectedShift.actual_closing_cash)}</strong></div><div><span>إضافات الأدمن</span><strong>${shiftMoney(selectedShift.cash_additions_total)}</strong></div><div><span>النقدي بعد الإضافات</span><strong>${selectedShift.adjusted_closing_cash == null ? "—" : shiftMoney(selectedShift.adjusted_closing_cash)}</strong></div><div><span>فرق العهدة</span><strong class="${difference == null ? "" : Number(difference) === 0 ? "is_ok" : "is_warning"}">${difference == null ? "—" : shiftMoney(difference)}</strong></div></div><div class="drawer_shift_total"><span>صافي مبيعات المطعم بالشيفت</span><strong>${shiftMoney(selectedShift.total_sales)}</strong></div>${selectedShift.closing_note ? `<p class="shift_closing_note">ملاحظة التسليم: ${shiftEscape(selectedShift.closing_note)}</p>` : ""}<section class="shift_additions"><h3>إضافات العهدة بواسطة الأدمن</h3><ul>${additionHistory}</ul>${additionForm}</section>`;
  document.getElementById("shiftCashAdditionForm")?.addEventListener("submit", submitShiftCashAddition);
  const drawer = document.getElementById("shiftDetailsDrawer");
  drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false");
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
  if (!(payload.amount > 0) || payload.reason.length < 2) return;
  button.disabled = true;
  try {
    const response = await window.apiFetch(`/shifts/${selectedShift.id}/cash-additions`, {
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
