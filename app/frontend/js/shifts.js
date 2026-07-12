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
      }
    });
  });
});

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
      <td>${shift.total_sales.toFixed(2)} ج.م</td>
      <td>${shift.target_date}</td>
    `;
    tbody.appendChild(tr);
  });
}
