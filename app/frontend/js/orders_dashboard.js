/**
 * Orders Dashboard — Real-time Orders & Stats for Admin
 */
(function () {
  let ordersList = [];
  let socket = null;
  let reconnectTimer = null;
  let heartbeatTimer = null;
  let fallbackRefreshTimer = null;
  let latestStats = {};
  let currentOrderFilter = "all";

  function displayOrderNumber(orderNumber, fallback = "---") {
    const value = orderNumber ?? fallback;
    const text = String(value);
    return text.includes("-") ? text.split("-").pop() : text;
  }

  let productCache = {};

  async function loadDashboardStats() {
    const statsRes = await apiFetch("/orders/dashboard/stats", { hideLoader: true });
    if (statsRes.ok) updateStatsUI(await statsRes.json());
  }

  // ===== INITIAL LOAD =====
  async function loadDashboardData() {
    try {
      // 1. Fetch Stats
      await loadDashboardStats();

      // 2. Ensure Products are loaded for naming
      if (Object.keys(productCache).length === 0) {
        const prodRes = await apiFetch("/menu/products", { hideLoader: true });
        if (prodRes.ok) {
          const prods = await prodRes.json();
          prods.forEach(p => productCache[p.id] = p.product_name);
        }
      }

      // 3. Fetch all orders for the current business day for the admin dashboard only
      const ordersRes = await apiFetch("/orders/dashboard/today", { hideLoader: true });
      if (ordersRes.ok) {
        const data = await ordersRes.json();
        ordersList = data.orders || [];
        renderOrdersTable();
        updateOperationalUI();
      }
    } catch (err) {
      console.error("Dashboard load failed:", err);
    }
  }

  // ===== RENDER TABLE =====
  function renderOrdersTable() {
    const tbody = document.querySelector("#home_orders_table tbody");
    if (!tbody) return;

    const filteredOrders = ordersList.filter((order) => {
      if (currentOrderFilter === "active") return ["new", "confirmed"].includes(order.order_status);
      if (currentOrderFilter === "completed") return ["completed", "delivered"].includes(order.order_status);
      if (currentOrderFilter === "cancelled") return order.order_status === "cancelled";
      return true;
    }).slice(0, 15);

    const caption = document.getElementById("ops_orders_caption");
    if (caption) caption.textContent = `عرض ${filteredOrders.length} من ${ordersList.length} طلب في يوم العمل`;

    if (filteredOrders.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding:40px; opacity:0.5;">لا توجد طلبات لهذا اليوم حتى الآن</td></tr>';
      return;
    }

    tbody.innerHTML = filteredOrders.map(order => {
      const statusObj = getStatusInfo(order.order_status);
      const timeStr = formatOrderTime(order.created_at);
      let updatedTimeStr = "";
      if (order.updated_at && order.created_at && Math.abs(new Date(order.updated_at).getTime() - new Date(order.created_at).getTime()) > 2000) {
         updatedTimeStr = `<br><span style="color:#f39c12; font-size:10px;">عدل في: ${formatOrderTime(order.updated_at)}</span>`;
      }
      const itemsSummary = summarizeItems(order.items);
      const totalAmount = parseFloat(order.total_amount || 0).toFixed(2);

      return `
        <tr>
          <td style="font-weight:bold; color:var(--color-primary);">#${displayOrderNumber(order.order_number, order.id)}</td>
          <td>${order.customer_name || "عميل نقدي"}</td>
          <td style="font-size:12px; max-width:300px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${itemsSummary}</td>
          <td style="font-weight:bold;">${totalAmount} ج.م</td>
          <td><span class="${statusObj.cls}">${statusObj.label}</span></td>
          <td style="opacity:0.7; font-size:11px;">${timeStr}${updatedTimeStr}</td>
        </tr>
      `;
    }).join("");
  }

  // ===== UPDATE STATS =====
  function updateStatsUI(stats) {
    latestStats = stats || {};
    const els = {
      total_orders: document.getElementById("stat_total_orders"),
      total_sales: document.getElementById("stat_total_sales"),
      completed: document.getElementById("stat_completed_orders"),
      cancelled: document.getElementById("stat_cancelled_orders"),
      active: document.getElementById("stat_active_orders")
    };

    if (els.total_orders) els.total_orders.textContent = stats.total_count;
    if (els.total_sales)  els.total_sales.textContent = stats.total_sales.toFixed(2) + " ج.م";
    const expensesEl = document.getElementById("ops_total_expenses");
    const profitEl = document.getElementById("ops_net_profit");
    if (expensesEl) expensesEl.textContent = Number(stats.total_expenses || 0).toLocaleString("ar-EG", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " ج.م";
    if (profitEl) {
      const netProfit = Number(stats.net_profit || 0);
      profitEl.textContent = netProfit.toLocaleString("ar-EG", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " ج.م";
      profitEl.classList.toggle("is_negative", netProfit < 0);
    }
    if (els.completed)    els.completed.textContent = stats.completed_count;
    if (els.cancelled)    els.cancelled.textContent = stats.cancelled_count;
    if (els.active)       els.active.textContent = stats.active_count;
    const successful = Number(stats.total_count || 0) - Number(stats.cancelled_count || 0);
    const average = successful ? Number(stats.total_sales || 0) / successful : 0;
    const successRate = stats.total_count ? successful / Number(stats.total_count) * 100 : 0;
    const averageEl = document.getElementById("ops_average_order");
    const successEl = document.getElementById("ops_success_rate");
    const cancelEl = document.getElementById("ops_cancel_summary");
    const salesCompareEl = document.getElementById("ops_sales_vs_yesterday");
    if (averageEl) averageEl.textContent = average.toLocaleString("ar-EG", { maximumFractionDigits: 2 }) + " ج.م";
    if (successEl) successEl.textContent = successRate.toLocaleString("ar-EG", { maximumFractionDigits: 1 }) + "%";
    if (cancelEl) cancelEl.textContent = `${Number(stats.cancelled_count || 0).toLocaleString("ar-EG")} طلب ملغي`;
    if (salesCompareEl) {
      if (stats.is_holiday) {
        salesCompareEl.className = "ops_sales_compare is_holiday";
        salesCompareEl.textContent = stats.holiday_name || "اليوم إجازة أسبوعية";
        updateOperationalUI();
        return;
      }
      const change = stats.sales_change_percent;
      const comparisonLabel = stats.comparison_label || "أمس";
      salesCompareEl.className = "ops_sales_compare";
      if (change == null) {
        salesCompareEl.textContent = Number(stats.total_sales || 0) > 0 ? `لا توجد مبيعات للمقارنة مع ${comparisonLabel}` : `مقارنة بنفس التوقيت مع ${comparisonLabel}`;
      } else {
        const numericChange = Number(change);
        const direction = numericChange > 0 ? "up" : numericChange < 0 ? "down" : "flat";
        salesCompareEl.classList.add(`is_${direction}`);
        const arrow = direction === "up" ? "↑" : direction === "down" ? "↓" : "—";
        salesCompareEl.textContent = `${arrow} ${Math.abs(numericChange).toLocaleString("ar-EG", { maximumFractionDigits: 1 })}% عن نفس التوقيت مع ${comparisonLabel}`;
      }
    }
    updateOperationalUI();
  }

  function normalizeOrderType(value) {
    const type = String(value || "").toUpperCase();
    if (type.includes("HALL") || type.includes("DINE_IN")) return "صالة";
    if (type.includes("TAKEAWAY") || type.includes("TAKE_AWAY")) return "تيك أواي";
    if (type.includes("DELIVERY")) return "دليفري";
    if (type.includes("ONLINE")) return "أون لاين";
    return "أخرى";
  }

  function updateOperationalUI() {
    const active = ordersList.filter((order) => ["new", "confirmed"].includes(order.order_status));
    const newOrders = active.filter((order) => order.order_status === "new");
    const confirmed = active.filter((order) => order.order_status === "confirmed");
    const now = Date.now();
    const delayed = active.map((order) => ({
      order,
      minutes: order.created_at ? Math.max(0, Math.floor((now - new Date(order.created_at).getTime()) / 60000)) : 0,
    })).filter((entry) => entry.minutes >= 20).sort((a, b) => b.minutes - a.minutes);

    const setText = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };
    setText("ops_new_orders", newOrders.length.toLocaleString("ar-EG"));
    setText("ops_confirmed_orders", confirmed.length.toLocaleString("ar-EG"));
    setText("ops_orders_mix", `${Number(latestStats.completed_count || 0).toLocaleString("ar-EG")} مكتمل • ${active.length.toLocaleString("ar-EG")} نشط`);

    const attention = document.getElementById("ops_attention");
    if (attention) {
      if (delayed.length) {
        attention.className = "ops_attention is_warning";
        attention.innerHTML = `<strong>${delayed.length.toLocaleString("ar-EG")} طلب متأخر</strong><span>أقدم طلب منتظر منذ ${delayed[0].minutes.toLocaleString("ar-EG")} دقيقة</span>`;
      } else {
        attention.className = "ops_attention is_clear";
        attention.innerHTML = "<strong>التشغيل مستقر</strong><span>لا توجد طلبات متأخرة حاليًا</span>";
      }
    }

    const channelCounts = {};
    ordersList.forEach((order) => { const key = normalizeOrderType(order.order_type); channelCounts[key] = (channelCounts[key] || 0) + 1; });
    const channels = ["صالة", "تيك أواي", "دليفري", "أون لاين"];
    const maxChannel = Math.max(...channels.map((key) => channelCounts[key] || 0), 1);
    const channelsEl = document.getElementById("ops_channels");
    if (channelsEl) channelsEl.innerHTML = channels.map((label, index) => `<div><p><span>${label}</span><strong>${(channelCounts[label] || 0).toLocaleString("ar-EG")}</strong></p><i><b style="width:${(channelCounts[label] || 0) / maxChannel * 100}%;--channel-color:${["#f1c75b", "#4fb3bf", "#9b7de3", "#eb8f62"][index]}"></b></i></div>`).join("");

    const cancelled = ordersList.filter((order) => order.order_status === "cancelled").slice(0, 3);
    const alerts = [
      ...delayed.slice(0, 4).map((entry) => ({ type: "warning", title: `طلب #${displayOrderNumber(entry.order.order_number, entry.order.id)} متأخر`, detail: `${entry.minutes} دقيقة انتظار` })),
      ...cancelled.map((order) => ({ type: "danger", title: `تم إلغاء الطلب #${displayOrderNumber(order.order_number, order.id)}`, detail: formatOrderTime(order.updated_at || order.created_at) })),
    ];
    setText("ops_alerts_count", alerts.length.toLocaleString("ar-EG"));
    const alertsEl = document.getElementById("ops_alerts");
    if (alertsEl) alertsEl.innerHTML = alerts.length ? alerts.map((alert) => `<div class="ops_alert ${alert.type}"><i></i><div><strong>${alert.title}</strong><span>${alert.detail}</span></div></div>`).join("") : '<div class="ops_empty_state">لا توجد تنبيهات تحتاج تدخلك</div>';
  }

  function updateConnectionStatus(status) {
    const dot = document.getElementById("ws_status_dot");
    const text = document.getElementById("ws_status_text");
    if (!dot || !text) return;

    if (status === "connected") {
      dot.style.background = "#2ecc71";
      dot.style.boxShadow = "0 0 8px #2ecc71";
      text.textContent = "متصل مباشر";
    } else if (status === "disconnected") {
      dot.style.background = "#e74c3c";
      dot.style.boxShadow = "none";
      text.textContent = "غير متصل (إعادة محاولة)";
    } else {
      dot.style.background = "#f1c40f";
      dot.style.boxShadow = "none";
      text.textContent = "جاري الاتصال...";
    }
  }

  // ===== WEBSOCKET =====
  function setupWebSocket() {
    if (socket) return;
    updateConnectionStatus("connecting");

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/orders/ws/admin`;
    
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      console.log("WebSocket connected successfully (Admin Dashboard)");
      updateConnectionStatus("connected");
      if (reconnectTimer) {
        clearInterval(reconnectTimer);
        reconnectTimer = null;
      }
      loadDashboardData();
      clearInterval(heartbeatTimer);
      heartbeatTimer = setInterval(() => {
        if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "HEARTBEAT" }));
      }, 20000);
    };

    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === "HEARTBEAT") {
          if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "HEARTBEAT" }));
          return;
        }
        if (payload.type === "HEARTBEAT_ACK") return;
        handleSocketEvent(payload);
      } catch (err) {
        console.error("WS Message Error:", err);
      }
    };

    socket.onclose = () => {
      updateConnectionStatus("disconnected");
      clearInterval(heartbeatTimer);
      heartbeatTimer = null;
      socket = null;
      if (!reconnectTimer) {
        reconnectTimer = setInterval(setupWebSocket, 5000);
      }
    };

    socket.onerror = (err) => {
      socket.close();
    };
  }

  function handleSocketEvent(payload) {
    const { type, data } = payload;

    if (type === "ORDER_SNAPSHOT") {
        ordersList = data.orders || [];
        renderOrdersTable();
        updateOperationalUI();
        setTimeout(loadDashboardStats, 300);
        return;
    }

    // Refresh Orders/Dashboard
    if (type === "NEW_ORDER" || type === "ORDER_UPDATED") {
      if (type === "NEW_ORDER") {
        if (!ordersList.find(o => o.id === data.id)) {
          ordersList.unshift(data);
          renderOrdersTable();
          updateOperationalUI();
          highlightRow(data.id);
        }
      } else {
        const idx = ordersList.findIndex(o => o.id === data.id);
        if (idx !== -1) {
          ordersList[idx] = { ...ordersList[idx], ...data };
          renderOrdersTable();
          updateOperationalUI();
          highlightRow(data.id);
        } else {
          setTimeout(loadDashboardData, 500);
        }
      }
      // Always refresh stats if something changed
      if (document.getElementById("page-home")) setTimeout(loadDashboardStats, 300);
    }

    if (type === "EXPENSE_UPDATED") {
      const liveDayTotal = Number(data?.day_total);
      if (Number.isFinite(liveDayTotal)) {
        latestStats = { ...latestStats, total_expenses: liveDayTotal, net_profit: Number(latestStats.total_sales || 0) - liveDayTotal };
        updateStatsUI(latestStats);
      }
      setTimeout(loadDashboardStats, 250);
      if (typeof window.refreshShifts === "function") window.refreshShifts();
    }

    // Refresh Products Page
    if (type === "PRODUCT_UPDATED") {
       if (typeof window.refreshProducts === "function") {
         window.refreshProducts();
       }
       // Also refresh dashboard cache to keep names updated
       if (data && data.id) productCache[data.id] = data.product_name;
    }

    // Refresh Categories Page
    if (type === "CATEGORY_UPDATED") {
       if (typeof window.refreshCategoriesPage === "function") {
         window.refreshCategoriesPage();
       }
       // Products page also uses category names
       if (typeof window.refreshCategories === "function") {
         window.refreshCategories();
       }
    }

    // Refresh Users Page
    if (type === "USER_UPDATED") {
       if (typeof window.refreshUsers === "function") {
         window.refreshUsers();
       }
    }
    
    // Global order refresh completed.
    if (type === "SYNC_COMPLETE") {
       console.log("Master sync complete, refreshing all...");
       loadDashboardData();
       if (typeof window.refreshProducts === "function") window.refreshProducts();
       if (typeof window.refreshCategoriesPage === "function") window.refreshCategoriesPage();
       if (typeof window.refreshUsers === "function") window.refreshUsers();
    }
  }

  function highlightRow(orderId) {
    setTimeout(() => {
        const rows = document.querySelectorAll("#home_orders_table tbody tr");
        rows.forEach(row => {
            if (row.innerHTML.includes(`#${orderId}`)) {
                row.style.transition = "background 0.5s";
                row.style.background = "rgba(241, 196, 15, 0.2)";
                setTimeout(() => {
                    row.style.background = "";
                }, 2000);
            }
        });
    }, 100);
  }

  // ===== HELPERS =====
  function getStatusInfo(status) {
    const map = {
      "new": { label: "جديد", cls: "status_new" },
      "confirmed": { label: "مؤكد", cls: "status_new" }, // Using same style as new for now
      "completed": { label: "مكتمل", cls: "status_completed" },
      "delivered": { label: "تم التوصيل", cls: "status_completed" },
      "cancelled": { label: "ملغي", cls: "status_cancelled" }
    };
    return map[status] || { label: status, cls: "" };
  }

  function formatOrderTime(dateStr) {
    if (!dateStr) return "---";
    const d = new Date(dateStr);
    if (isNaN(d)) return dateStr;
    return d.toLocaleTimeString("ar-EG", { hour: "2-digit", minute: "2-digit" });
  }

  function summarizeItems(items) {
    if (!items || items.length === 0) return "لا توجد أصناف";
    return items.map(it => {
      const name = productCache[it.product_id] || `#${it.product_id}`;
      return `${it.quantity}x ${name}`;
    }).join(", ");
  }

  // ===== EXPOSE GLOBAL =====
  window.refreshDashboard = loadDashboardData;

  // ===== INIT =====
  document.addEventListener("DOMContentLoaded", () => {
    const clock = () => {
      const now = new Date();
      const timeEl = document.getElementById("ops_current_time");
      const dateEl = document.getElementById("ops_business_date");
      if (timeEl) timeEl.textContent = now.toLocaleTimeString("ar-EG", { hour: "2-digit", minute: "2-digit" });
      if (dateEl) dateEl.textContent = now.toLocaleDateString("ar-EG", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    };
    clock();
    setInterval(clock, 30000);
    document.querySelectorAll("[data-order-filter]").forEach((button) => button.addEventListener("click", () => {
      document.querySelectorAll("[data-order-filter]").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      currentOrderFilter = button.dataset.orderFilter;
      renderOrdersTable();
    }));
    document.querySelectorAll("[data-ops-page]").forEach((button) => button.addEventListener("click", () => {
      if (typeof window.showPage === "function") window.showPage(button.dataset.opsPage);
      else if (typeof showPage === "function") showPage(button.dataset.opsPage);
    }));
    // Connect WebSocket globally
    setupWebSocket();
    clearInterval(fallbackRefreshTimer);
    fallbackRefreshTimer = setInterval(() => {
      const home = document.getElementById("page-home");
      if (document.visibilityState === "visible" && home && getComputedStyle(home).display !== "none") {
        loadDashboardData();
      }
    }, 30000);

    // Only load initial dashboard data if on home page
    if (document.getElementById("page-home")) {
      loadDashboardData();
    }
  });

})();
