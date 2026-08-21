function displayOrderNumber(orderNumber, fallback = "---") {
  const text = String(orderNumber ?? fallback);
  return text.includes("-") ? text.split("-").pop() : text;
}

document.addEventListener("DOMContentLoaded", () => {
  const page = document.getElementById("page-reports");
  if (!page) return;
  const money = (value, compact = false) => `${Number(value || 0).toLocaleString("ar-EG", { maximumFractionDigits: compact ? 0 : 2, notation: compact ? "compact" : "standard" })} ج.م`;
  const number = (value) => Number(value || 0).toLocaleString("ar-EG");
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
  const filterBtns = [...page.querySelectorAll(".filter-btn")];
  const title = page.querySelector(".title_report");
  const loading = document.getElementById("reportsLoading");
  const errorBox = document.getElementById("reportsError");
  const startInput = document.getElementById("customStartDate");
  const endInput = document.getElementById("customEndDate");
  let hasLoaded = false;
  const pageSize = 50;
  let currentBaseUrl = "/reports/daily";
  let currentType = "daily";
  let currentOffset = 0;
  let currentSummary = { total_orders: 0 };
  let currentRange = { start: "", end: "" };
  let currentPageOrders = [];

  const dateLabel = (value, options = { day: "numeric", month: "short" }) => value ? new Date(`${value}T12:00:00`).toLocaleDateString("ar-EG", options) : "—";
  function reportTitle(type, data = {}) {
    if (type === "daily") return `تقرير يوم ${dateLabel(data.report_date, { weekday: "long", day: "numeric", month: "long", year: "numeric" })}`;
    if (type === "weekly" || type === "custom") return `من ${dateLabel(data.start_date, { day: "numeric", month: "long", year: "numeric" })} إلى ${dateLabel(data.end_date, { day: "numeric", month: "long", year: "numeric" })}`;
    if (type === "monthly") return new Date(data.year, Number(data.month) - 1, 1).toLocaleDateString("ar-EG", { month: "long", year: "numeric" });
    return `تقرير سنة ${data.year || new Date().getFullYear()}`;
  }

  function renderTrend(trend) {
    const target = document.getElementById("revenueTrendChart");
    const points = (trend || []).map((point) => ({ label: dateLabel(point.period_date), value: Number(point.revenue || 0) }));
    if (!points.length) { target.innerHTML = '<div class="report_chart_empty">لا توجد مبيعات في هذه الفترة</div>'; return; }
    const width = 760, height = 250, pad = { top: 24, right: 20, bottom: 46, left: 62 };
    const max = Math.max(...points.map((point) => point.value), 1);
    const x = (index) => pad.left + (points.length === 1 ? (width - pad.left - pad.right) / 2 : index * (width - pad.left - pad.right) / (points.length - 1));
    const y = (value) => pad.top + (height - pad.top - pad.bottom) * (1 - value / max);
    const line = points.map((point, index) => `${x(index)},${y(point.value)}`).join(" ");
    const area = `${pad.left},${height - pad.bottom} ${line} ${x(points.length - 1)},${height - pad.bottom}`;
    const grid = [0, .25, .5, .75, 1].map((ratio) => { const gy = y(max * ratio); return `<line x1="${pad.left}" y1="${gy}" x2="${width - pad.right}" y2="${gy}"/><text x="${pad.left - 10}" y="${gy + 4}">${escapeHtml(money(max * ratio, true).replace(" ج.م", ""))}</text>`; }).join("");
    const labelStep = Math.max(1, Math.ceil(points.length / 8));
    const labels = points.map((point, index) => (index % labelStep === 0 || index === points.length - 1) ? `<text x="${x(index)}" y="${height - 16}" class="chart_axis_label">${escapeHtml(point.label)}</text>` : "").join("");
    const dots = points.map((point, index) => `<circle cx="${x(index)}" cy="${y(point.value)}" r="5"><title>${escapeHtml(point.label)}: ${escapeHtml(money(point.value))}</title></circle>`).join("");
    target.innerHTML = `<svg class="report_line_chart" viewBox="0 0 ${width} ${height}" role="img"><g class="chart_grid">${grid}</g><polygon class="chart_area" points="${area}"/><polyline class="chart_line" points="${line}"/><g class="chart_dots">${dots}</g><g class="chart_labels">${labels}</g></svg>`;
  }

  function renderStatus(summary) {
    const total = Number(summary.total_orders || 0), completed = Number(summary.successful_orders || 0);
    const rate = total ? Math.round(completed / total * 100) : 0;
    document.getElementById("ordersStatusChart").style.setProperty("--completion", `${rate * 3.6}deg`);
    document.getElementById("donut_rate").textContent = `${number(rate)}%`;
    document.getElementById("completion_rate_value").textContent = `${number(rate)}%`;
  }

  function renderBars(targetId, rows, formatValue = number) {
    const target = document.getElementById(targetId), max = Math.max(...rows.map((row) => row.value), 1);
    target.innerHTML = rows.map((row) => `<div class="report_bar_row"><div class="report_bar_label"><span>${escapeHtml(row.label)}</span><strong>${escapeHtml(formatValue(row.value))}</strong></div><div class="report_bar_track"><i style="width:${Math.max(row.value / max * 100, row.value ? 4 : 0)}%;--bar-color:${row.color || "var(--color-primary)"}"></i></div></div>`).join("");
  }

  function renderTypes(activity) {
    const types = { "صالة": 0, "تيك اوي": 0, "دليفري": 0 };
    (activity || []).forEach((item) => { const key = item.order_type || "غير محدد"; types[key] = (types[key] || 0) + Number(item.count || 0); });
    renderBars("orderTypesChart", Object.entries(types).map(([label, value], index) => ({ label, value, color: ["#f1c75b", "#4fb3bf", "#9b7de3", "#eb8f62"][index % 4] })));
  }

  function renderPeakHours(activity) {
    const buckets = [
      { label: "5 - 9 صباحًا", value: 0, test: (hour) => hour >= 5 && hour < 9 },
      { label: "9 ص - 1 ظهرًا", value: 0, test: (hour) => hour >= 9 && hour < 13 },
      { label: "1 - 5 عصرًا", value: 0, test: (hour) => hour >= 13 && hour < 17 },
      { label: "5 - 9 مساءً", value: 0, test: (hour) => hour >= 17 && hour < 21 },
      { label: "9 مساءً - 5 صباحًا", value: 0, test: (hour) => hour >= 21 || hour < 5 },
    ];
    (activity || []).forEach((item) => {
      const hour = Number(item.hour);
      const bucket = buckets.find((entry) => entry.test(hour));
      if (bucket) bucket.value += Number(item.count || 0);
    });
    const peak = buckets.reduce((best, item) => item.value > best.value ? item : best, buckets[0]);
    document.getElementById("peakHourLabel").textContent = peak.value ? peak.label : "—";
    renderBars("peakHoursChart", buckets.map((item, index) => ({ ...item, color: ["#4fb3bf", "#67c58b", "#f1c75b", "#eb8f62", "#9b7de3"][index] })), (value) => `${number(value)} طلب`);
  }

  function renderTopItems(items) {
    const rows = (items || []).map((item, index) => ({
      label: `${index + 1}. ${item.name}`,
      value: Number(item.quantity || 0),
      color: ["#f1c75b", "#4fb3bf", "#9b7de3", "#eb8f62", "#67c58b"][index],
    }));
    const target = document.getElementById("topItemsChart");
    if (!rows.length) {
      target.innerHTML = '<div class="report_chart_empty">لا توجد أصناف مباعة في هذه الفترة</div>';
      return;
    }
    renderBars("topItemsChart", rows, (value) => `${number(value)} قطعة`);
  }

  function renderTable(orders, summary, offset, limit) {
    const tbody = page.querySelector(".orders_table_reports tbody");
    const total = Number(summary.total_orders || 0);
    const first = total ? offset + 1 : 0;
    const last = Math.min(offset + orders.length, total);
    document.getElementById("reports_orders_count").textContent = `عرض ${number(first)}–${number(last)} من ${number(total)} طلب`;
    const totalPages = Math.max(1, Math.ceil(total / limit));
    const currentPage = Math.floor(offset / limit) + 1;
    document.getElementById("reportsPageInfo").textContent = `صفحة ${number(currentPage)} من ${number(totalPages)}`;
    document.getElementById("reportsPrevPage").disabled = offset <= 0;
    document.getElementById("reportsNextPage").disabled = offset + limit >= total;
    if (!orders.length) { tbody.innerHTML = '<tr><td colspan="6" class="reports_empty">لا توجد طلبات في هذه الفترة</td></tr>'; return; }
    tbody.innerHTML = orders.map((order) => {
      const cancelled = order.status === "cancelled" || String(order.order_type).includes("ملغي");
      const type = String(order.order_type || "—").replace(" (ملغي)", "");
      return `<tr><td>#${escapeHtml(displayOrderNumber(order.order_number))}</td><td>${escapeHtml(type)}</td><td><span class="report_status ${cancelled ? "is_cancelled" : "is_completed"}">${cancelled ? "ملغي" : "مكتمل"}</span></td><td>${escapeHtml(money(order.total_amount))}</td><td>${escapeHtml(dateLabel(order.order_date))}</td><td dir="ltr">${escapeHtml(order.created_at_time || "—")}</td></tr>`;
    }).join("");
  }

  function renderExpenses(expenses, summary) {
    const rows = expenses || [];
    const tbody = page.querySelector(".reports_expenses_table tbody");
    document.getElementById("reports_expenses_count").textContent = `${number(rows.length)} مصروف في الفترة المحددة`;
    document.getElementById("reports_expenses_sum").textContent = money(summary.total_expenses);
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="reports_empty">لا توجد مصروفات في هذه الفترة</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map((expense) => {
      const createdAt = expense.created_at ? new Date(expense.created_at) : null;
      const time = createdAt && !Number.isNaN(createdAt.getTime())
        ? createdAt.toLocaleTimeString("ar-EG", { hour: "2-digit", minute: "2-digit" })
        : "—";
      return `<tr><td><strong class="report_expense_title">${escapeHtml(expense.title || "—")}</strong></td><td><strong class="report_expense_amount">${escapeHtml(money(expense.amount))}</strong></td><td>${escapeHtml(expense.cashier_name || "كاشير")}</td><td class="report_expense_note">${escapeHtml(expense.note || "بدون ملاحظة")}</td><td>${escapeHtml(dateLabel(expense.target_date))}</td><td dir="ltr">${escapeHtml(time)}</td></tr>`;
    }).join("");
  }

  function updateReport(data, type) {
    const summary = data.summary || {}, orders = data.orders || [];
    currentPageOrders = orders;
    currentSummary = summary;
    if (data.report_date) currentRange = { start: data.report_date, end: data.report_date };
    else if (data.start_date && data.end_date) currentRange = { start: data.start_date, end: data.end_date };
    else if (data.year && data.month) {
      const month = String(data.month).padStart(2, "0");
      const lastDay = new Date(Number(data.year), Number(data.month), 0).getDate();
      currentRange = { start: `${data.year}-${month}-01`, end: `${data.year}-${month}-${String(lastDay).padStart(2, "0")}` };
    } else if (data.year) currentRange = { start: `${data.year}-01-01`, end: `${data.year}-12-31` };
    title.textContent = reportTitle(type, data);
    document.getElementById("total_revenue_value").textContent = money(summary.total_revenue);
    document.getElementById("total_expenses_value").textContent = money(summary.total_expenses);
    document.getElementById("net_profit_value").textContent = money(summary.net_profit);
    document.getElementById("chart_revenue_total").textContent = money(summary.total_revenue);
    document.getElementById("total_orders_value").textContent = number(summary.total_orders);
    document.getElementById("average_order_value").textContent = money(summary.average_order_value);
    document.getElementById("successful_orders_value").textContent = number(summary.successful_orders);
    document.getElementById("cancelled_orders_value").textContent = number(summary.cancelled_orders);
    renderStatus(summary); renderTrend(data.revenue_trend); renderTypes(data.activity_breakdown); renderPeakHours(data.activity_breakdown); renderTopItems(data.top_items);
    renderBars("financialBreakdownChart", [
      { label: "صافي المبيعات", value: Number(summary.total_revenue || 0), color: "#f1c75b" },
      { label: "قبل الخصم", value: Number(summary.total_subtotal || 0), color: "#4fb3bf" },
      { label: "الخصومات", value: Number(summary.total_discount || 0), color: "#eb6a67" },
      { label: "رسوم التوصيل", value: Number(summary.total_delivery_fee || 0), color: "#9b7de3" },
      { label: "المصروفات", value: Number(summary.total_expenses || 0), color: "#ef8a75" },
      { label: "صافي الربح", value: Number(summary.net_profit || 0), color: "#58cf91" },
    ], money);
    renderTable(orders, summary, Number(data.orders_offset || 0), Number(data.orders_limit || pageSize));
    renderExpenses(data.expenses, summary);
  }

  async function loadReport(baseUrl, type, offset = 0) {
    currentBaseUrl = baseUrl; currentType = type; currentOffset = offset;
    const separator = baseUrl.includes("?") ? "&" : "?";
    const url = `${baseUrl}${separator}limit=${pageSize}&offset=${offset}`;
    loading.hidden = false; errorBox.hidden = true;
    try {
      const response = await window.apiFetch(url);
      if (!response.ok) throw new Error(`تعذر تحميل التقرير (${response.status})`);
      updateReport(await response.json(), type); hasLoaded = true;
    } catch (error) { errorBox.textContent = error.message || "حدث خطأ أثناء تحميل التقرير"; errorBox.hidden = false; }
    finally { loading.hidden = true; }
  }

  async function loadOrdersPage(offset) {
    if (!currentRange.start || !currentRange.end) return;
    loading.hidden = false; errorBox.hidden = true;
    try {
      const url = `/reports/orders?start_date=${currentRange.start}&end_date=${currentRange.end}&limit=${pageSize}&offset=${offset}`;
      const response = await window.apiFetch(url);
      if (!response.ok) throw new Error(`تعذر تحميل صفحة الطلبات (${response.status})`);
      const data = await response.json();
      currentOffset = Number(data.offset || 0);
      currentPageOrders = data.orders || [];
      renderTable(currentPageOrders, currentSummary, currentOffset, Number(data.limit || pageSize));
    } catch (error) { errorBox.textContent = error.message || "حدث خطأ أثناء تحميل الطلبات"; errorBox.hidden = false; }
    finally { loading.hidden = true; }
  }

  function periodUrl(type) {
    const today = new Date();
    if (type === "daily") return "/reports/daily";
    if (type === "weekly") return "/reports/weekly";
    if (type === "monthly") return `/reports/monthly?year=${today.getFullYear()}&month=${today.getMonth() + 1}`;
    return `/reports/yearly?year=${today.getFullYear()}`;
  }

  const buttonTypes = { dailyBtn: "daily", weeklyBtn: "weekly", monthlyBtn: "monthly", yearlyBtn: "yearly" };
  filterBtns.forEach((button) => button.addEventListener("click", () => {
    filterBtns.forEach((item) => item.classList.remove("active_report")); button.classList.add("active_report");
    const type = buttonTypes[button.id]; loadReport(periodUrl(type), type, 0);
  }));
  const today = new Date().toISOString().split("T")[0]; startInput.value = today; endInput.value = today;
  document.getElementById("customDateBtn").addEventListener("click", () => {
    if (!startInput.value || !endInput.value) { errorBox.textContent = "اختر تاريخ البداية والنهاية"; errorBox.hidden = false; return; }
    filterBtns.forEach((item) => item.classList.remove("active_report"));
    loadReport(`/reports/custom?start_date=${startInput.value}&end_date=${endInput.value}`, "custom", 0);
  });
  document.getElementById("reportsPrevPage").addEventListener("click", () => loadOrdersPage(Math.max(0, currentOffset - pageSize)));
  document.getElementById("reportsNextPage").addEventListener("click", () => loadOrdersPage(currentOffset + pageSize));
  document.getElementById("printBtn").addEventListener("click", async () => {
    const button = document.getElementById("printBtn");
    const originalText = button.textContent;
    const savedOrders = currentPageOrders;
    const savedOffset = currentOffset;
    let printPrepared = false;
    const restorePrintState = () => {
      currentPageOrders = savedOrders;
      currentOffset = savedOffset;
      renderTable(savedOrders, currentSummary, savedOffset, pageSize);
      button.disabled = false;
      button.textContent = originalText;
    };
    button.disabled = true;
    button.textContent = "جاري تجهيز الطباعة...";
    errorBox.hidden = true;
    try {
      const allOrders = [];
      const total = Number(currentSummary.total_orders || 0);
      const printBatchSize = 200;
      for (let offset = 0; offset < total; offset += printBatchSize) {
        const url = `/reports/orders?start_date=${currentRange.start}&end_date=${currentRange.end}&limit=${printBatchSize}&offset=${offset}`;
        const response = await window.apiFetch(url);
        if (!response.ok) throw new Error(`تعذر تجهيز طلبات الطباعة (${response.status})`);
        const data = await response.json();
        allOrders.push(...(data.orders || []));
      }
      renderTable(allOrders, currentSummary, 0, Math.max(total, 1));
      printPrepared = true;
      window.addEventListener("afterprint", restorePrintState, { once: true });
      window.print();
    } catch (error) {
      errorBox.textContent = error.message || "حدث خطأ أثناء تجهيز التقرير للطباعة";
      errorBox.hidden = false;
    } finally { if (!printPrepared) restorePrintState(); }
  });
  new MutationObserver(() => { if (page.style.display !== "none" && !hasLoaded) loadReport("/reports/daily", "daily", 0); }).observe(page, { attributes: true, attributeFilter: ["style"] });
  if (page.style.display !== "none") loadReport("/reports/daily", "daily", 0);
});
