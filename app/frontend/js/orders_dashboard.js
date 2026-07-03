/**
 * Orders Dashboard — Real-time Orders & Stats for Admin
 */
(function () {
  let ordersList = [];
  let socket = null;
  let reconnectTimer = null;

  let productCache = {};

  // ===== INITIAL LOAD =====
  async function loadDashboardData() {
    try {
      // 1. Fetch Stats
      const statsRes = await apiFetch("/orders/dashboard/stats", { hideLoader: true });
      if (statsRes.ok) {
        const stats = await statsRes.json();
        updateStatsUI(stats);
      }

      // 2. Ensure Products are loaded for naming
      if (Object.keys(productCache).length === 0) {
        const prodRes = await apiFetch("/menu/products", { hideLoader: true });
        if (prodRes.ok) {
          const prods = await prodRes.json();
          prods.forEach(p => productCache[p.id] = p.product_name);
        }
      }

      // 3. Fetch Orders (today's shift)
      const ordersRes = await apiFetch("/orders/?page=1&page_size=50", { hideLoader: true });
      if (ordersRes.ok) {
        const data = await ordersRes.json();
        ordersList = data.orders || [];
        renderOrdersTable();
      }
    } catch (err) {
      console.error("Dashboard load failed:", err);
    }
  }

  // ===== RENDER TABLE =====
  function renderOrdersTable() {
    const tbody = document.querySelector("#home_orders_table tbody");
    if (!tbody) return;

    if (ordersList.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding:40px; opacity:0.5;">لا توجد طلبات لهذا اليوم حتى الآن</td></tr>';
      return;
    }

    tbody.innerHTML = ordersList.map(order => {
      const statusObj = getStatusInfo(order.order_status);
      const timeStr = formatOrderTime(order.created_at);
      let updatedTimeStr = "";
      if (order.updated_at && order.updated_at !== order.created_at) {
         updatedTimeStr = `<br><span style="color:#f39c12; font-size:10px;">عدل في: ${formatOrderTime(order.updated_at)}</span>`;
      }
      const itemsSummary = summarizeItems(order.items);
      const totalAmount = parseFloat(order.total_amount || 0).toFixed(2);

      return `
        <tr>
          <td style="font-weight:bold; color:var(--color-primary);">#${order.order_number || order.id}</td>
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
    const els = {
      total_orders: document.getElementById("stat_total_orders"),
      total_sales: document.getElementById("stat_total_sales"),
      completed: document.getElementById("stat_completed_orders"),
      cancelled: document.getElementById("stat_cancelled_orders"),
      active: document.getElementById("stat_active_orders")
    };

    if (els.total_orders) els.total_orders.textContent = stats.total_count;
    if (els.total_sales)  els.total_sales.textContent = stats.total_sales.toFixed(2) + " ج.م";
    if (els.completed)    els.completed.textContent = stats.completed_count;
    if (els.cancelled)    els.cancelled.textContent = stats.cancelled_count;
    if (els.active)       els.active.textContent = stats.active_count;
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
    };

    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        handleSocketEvent(payload);
      } catch (err) {
        console.error("WS Message Error:", err);
      }
    };

    socket.onclose = () => {
      updateConnectionStatus("disconnected");
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
        setTimeout(loadDashboardData, 500); 
        return;
    }

    // Refresh Orders/Dashboard
    if (type === "NEW_ORDER" || type === "ORDER_UPDATED") {
      if (type === "NEW_ORDER") {
        if (!ordersList.find(o => o.id === data.id)) {
          ordersList.unshift(data);
          renderOrdersTable();
          highlightRow(data.id);
        }
      } else {
        const idx = ordersList.findIndex(o => o.id === data.id);
        if (idx !== -1) {
          ordersList[idx] = { ...ordersList[idx], ...data };
          renderOrdersTable();
          highlightRow(data.id);
        } else {
          setTimeout(loadDashboardData, 500);
        }
      }
      // Always refresh stats if something changed
      if (document.getElementById("page-home")) {
        setTimeout(loadDashboardData, 500);
      }
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
    
    // Global sync complete from desktop
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
    // Connect WebSocket globally
    setupWebSocket();

    // Only load initial dashboard data if on home page
    if (document.getElementById("page-home")) {
      loadDashboardData();
    }
  });

})();
