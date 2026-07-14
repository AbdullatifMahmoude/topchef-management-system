document.addEventListener("DOMContentLoaded", () => {
  const shiftsDateBtn = document.getElementById("shiftsDateBtn");
  const shiftsDateFilter = document.getElementById("shiftsDateFilter");

  if (shiftsDateFilter) {
    // Set default date to today
    const today = new Date();
    shiftsDateFilter.value = today.toISOString().split("T")[0];
  }

  if (shiftsDateBtn) {
    shiftsDateBtn.addEventListener("click", fetchShiftsReport);
  }

  // Load initially if page is visible, but we can also just listen to the sidebar button
  document.querySelectorAll(".side_btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.getAttribute("data-page") === "shifts") {
        fetchShiftsReport();
        startShiftsAutoRefresh();
      }
    });
  });

  startShiftsWebSocket();
});

let shiftsRefreshTimer = null;

function startShiftsAutoRefresh() {
  if (shiftsRefreshTimer) return;
  shiftsRefreshTimer = setInterval(() => {
    const page = document.getElementById("page-shifts");
    if (page && page.style.display !== "none") {
      fetchShiftsReport();
    }
  }, 15000);
}

function startShiftsWebSocket() {
  if (!window.WebSocket) return;

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/orders/ws/admin`;
  let socket = null;
  let reconnectTimer = null;

  const connect = () => {
    if (socket) return;
    socket = new WebSocket(wsUrl);

    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (
          payload.type === "SHIFT_CREATED" ||
          payload.type === "SHIFT_UPDATED"
        ) {
          const page = document.getElementById("page-shifts");
          if (page && page.style.display !== "none") {
            fetchShiftsReport();
          }
        }
      } catch (err) {
        console.error("Shifts WS message error:", err);
      }
    };

    socket.onclose = () => {
      socket = null;
      if (!reconnectTimer) {
        reconnectTimer = setInterval(connect, 10000);
      }
    };

    socket.onopen = () => {
      if (reconnectTimer) {
        clearInterval(reconnectTimer);
        reconnectTimer = null;
      }
    };
  };

  connect();
}

async function fetchShiftsReport() {
  const tbody = document.querySelector("#shifts_table tbody");
  if (!tbody) return;

  tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:20px; opacity:0.5;">جاري التحميل...</td></tr>`;

  try {
    const dateFilter = document.getElementById("shiftsDateFilter").value;
    const res = await window.apiFetch(`/shifts?target_date=${dateFilter}`);
    if (!res.ok) throw new Error("Failed to fetch shifts");
    
    const data = await res.json();
    renderShifts(data);
  } catch (error) {
    console.error("Error fetching shifts:", error);
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:20px; color:var(--color-danger, #e74c3c);">حدث خطأ أثناء جلب البيانات</td></tr>`;
  }
}

function renderShifts(shifts) {
  const tbody = document.querySelector("#shifts_table tbody");
  if (!tbody) return;

  if (!shifts || shifts.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:20px; opacity:0.5;">لا توجد شيفتات مسجلة في هذا اليوم</td></tr>`;
    return;
  }

  tbody.innerHTML = "";
  shifts.forEach(shift => {
    const start = shift.start_time ? new Date(shift.start_time).toLocaleTimeString('ar-EG', { hour: '2-digit', minute: '2-digit' }) : "غير محدد";
    const end = shift.end_time ? new Date(shift.end_time).toLocaleTimeString('ar-EG', { hour: '2-digit', minute: '2-digit' }) : "<span style='color:var(--color-primary);'>نشط الآن</span>";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${shift.cashier_name}</td>
      <td>${start}</td>
      <td>${end}</td>
      <td>${shift.total_orders}</td>
      <td>${Number(shift.total_sales || 0).toFixed(2)} ج.م</td>
      <td>${shift.target_date}</td>
    `;
    tbody.appendChild(tr);
  });
}
