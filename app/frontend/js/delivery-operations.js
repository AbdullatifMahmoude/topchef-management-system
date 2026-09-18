(function () {
  const page = document.getElementById("page-delivery-ops");
  if (!page) return;

  let snapshot = { stats: [], orders: [], summary: {} };
  let loading = false;

  const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[char]);
  const money = (value) => `${Number(value || 0).toLocaleString("ar-EG", { maximumFractionDigits: 2 })} ج.م`;
  const statusLabel = (status) => status === "out_for_delivery" ? "خرج للتوصيل" : "مؤكد";
  const paymentLabel = (method) => ({ cash: "نقدي", instapay: "إنستا باي", wallet: "محفظة" }[method] || method);

  function setText(id, value) {
    const target = document.getElementById(id);
    if (target) target.textContent = value;
  }

  function renderSummary() {
    const summary = snapshot.summary || {};
    setText("deliveryUnassignedCount", Number(summary.unassigned_orders || 0).toLocaleString("ar-EG"));
    setText("deliveryOnRoadCount", Number(summary.out_for_delivery || 0).toLocaleString("ar-EG"));
    setText("deliveryDeliveredCount", Number(summary.delivered_orders || 0).toLocaleString("ar-EG"));
    setText("deliveryAvailableRiders", Number(summary.available_riders || 0).toLocaleString("ar-EG"));
    setText("deliveryBusyRiders", `${Number(summary.active_riders || 0).toLocaleString("ar-EG")} مشغول`);
    setText("deliveryCashExpected", money(summary.cash_to_collect));
  }

  function riderOptions(selectedId) {
    const options = snapshot.stats.map((rider) =>
      `<option value="${rider.id}" ${Number(selectedId) === Number(rider.id) ? "selected" : ""}>${esc(rider.name)} — ${rider.availability === "busy" ? "مشغول" : "متاح"}</option>`
    ).join("");
    return `<option value="">اختر المندوب</option>${options}`;
  }

  function renderOrders() {
    const target = document.getElementById("deliveryOrdersList");
    const filter = document.getElementById("deliveryOrdersFilter").value;
    let orders = snapshot.orders || [];
    if (filter === "unassigned") orders = orders.filter((order) => !order.rider_id);
    if (filter === "out_for_delivery") orders = orders.filter((order) => order.status === "out_for_delivery");
    orders = [...orders].sort((a, b) => Number(!a.rider_id) - Number(!b.rider_id) || b.age_minutes - a.age_minutes).reverse();

    if (!orders.length) {
      target.innerHTML = '<div class="delivery_empty is_success">لا توجد طلبات في هذه الحالة</div>';
      return;
    }

    target.innerHTML = orders.map((order) => {
      const late = order.age_minutes >= 35;
      const onRoad = order.status === "out_for_delivery";
      return `<div class="delivery_order_card ${late ? "is_late" : ""}">
        <div class="delivery_order_top"><div><strong>#${esc(order.order_number)}</strong><span>${esc(order.customer_name)} • ${esc(order.customer_phone || "بدون هاتف")}</span></div><b class="delivery_status ${onRoad ? "on_road" : "confirmed"}">${statusLabel(order.status)}</b></div>
        <p class="delivery_address">${esc(order.customer_address || "العنوان غير مسجل")}</p>
        <div class="delivery_order_meta"><span>${money(order.total_amount)}</span><span>${paymentLabel(order.payment_method)}</span><span class="${late ? "late" : ""}">منذ ${Number(order.age_minutes).toLocaleString("ar-EG")} دقيقة</span></div>
        <div class="delivery_order_actions">
          <select class="delivery_rider_select" data-order-id="${order.id}">${riderOptions(order.rider_id)}</select>
          ${onRoad
            ? `<button class="delivery_complete_btn" data-action="deliver" data-order-id="${order.id}">تم التسليم</button>`
            : `<button class="delivery_dispatch_btn" data-action="dispatch" data-order-id="${order.id}" ${order.rider_id ? "" : "disabled"}>خرج للتوصيل</button>`}
        </div>
      </div>`;
    }).join("");
  }

  function renderRiders() {
    const target = document.getElementById("deliveryRidersList");
    const riders = snapshot.stats || [];
    if (!riders.length) {
      target.innerHTML = '<div class="delivery_empty">لا يوجد مندوبون نشطون. أضفهم من صفحة المستخدمين.</div>';
      return;
    }
    target.innerHTML = riders.map((rider) => `<div class="delivery_rider_card">
      <div class="delivery_rider_identity"><i>${esc((rider.name || "م").trim().charAt(0))}</i><div><strong>${esc(rider.name)}</strong><span>${esc(rider.phone || rider.username)}</span></div><b class="${rider.availability}">${rider.availability === "busy" ? "مشغول" : "متاح"}</b></div>
      <div class="delivery_rider_metrics"><span><small>نشط</small><strong>${rider.active_orders}</strong></span><span><small>تم التسليم</small><strong>${rider.delivered_orders}</strong></span><span><small>نقدي</small><strong>${money(rider.cash_amount)}</strong></span><span><small>تحويل</small><strong>${money(rider.digital_amount)}</strong></span></div>
    </div>`).join("");
  }

  async function updateOrder(orderId, body, successMessage) {
    const response = await window.apiFetch(`/orders/${orderId}/status`, {
      method: "PATCH",
      body: JSON.stringify(body),
      hideLoader: true,
    });
    if (!response.ok) {
      let detail = "تعذر تحديث الطلب";
      try { detail = (await response.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    if (typeof window.showToast === "function") window.showToast(successMessage, "success");
    await refresh();
  }

  async function refresh() {
    if (loading) return;
    loading = true;
    try {
      const response = await window.apiFetch("/orders/riders/stats", { hideLoader: true });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      snapshot = await response.json();
      renderSummary();
      renderOrders();
      renderRiders();
    } catch (error) {
      console.error("Delivery operations load failed:", error);
      document.getElementById("deliveryOrdersList").innerHTML = '<div class="delivery_empty is_error">تعذر تحميل حركة التوصيل</div>';
      document.getElementById("deliveryRidersList").innerHTML = '<div class="delivery_empty is_error">تعذر تحميل المناديب</div>';
    } finally {
      loading = false;
    }
  }

  page.addEventListener("change", async (event) => {
    const select = event.target.closest(".delivery_rider_select");
    if (!select) return;
    const orderId = Number(select.dataset.orderId);
    const riderId = Number(select.value) || null;
    try {
      await updateOrder(orderId, { delivery_person_id: riderId }, riderId ? "تم إسناد الطلب" : "تم إلغاء الإسناد");
    } catch (error) {
      alert(error.message);
      await refresh();
    }
  });

  page.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    button.disabled = true;
    try {
      const status = button.dataset.action === "dispatch" ? "out_for_delivery" : "delivered";
      await updateOrder(Number(button.dataset.orderId), { order_status: status }, status === "delivered" ? "تم تسجيل تسليم الطلب" : "تم خروج الطلب للتوصيل");
    } catch (error) {
      alert(error.message);
      button.disabled = false;
    }
  });

  document.getElementById("deliveryOrdersFilter").addEventListener("change", renderOrders);
  document.getElementById("deliveryOpsRefresh").addEventListener("click", refresh);
  window.refreshDeliveryOperations = refresh;
  setInterval(() => {
    if (page.style.display !== "none" && !document.hidden) refresh();
  }, 30000);
})();
