document.addEventListener("DOMContentLoaded", () => {
  const filterBtns     = document.querySelectorAll(".filter-btn");
  const reports_modal  = document.querySelector(".reports_modal");
  const exit_reports   = document.querySelector(".exit_reports_modal");
  const title_report   = document.querySelector(".title_report");
  const printBtn       = document.getElementById("printBtn");
  const dailyBtn       = document.getElementById("dailyBtn");
  const weeklyBtn      = document.getElementById("weeklyBtn");
  const monthlyBtn     = document.getElementById("monthlyBtn");
  const yearlyBtn      = document.getElementById("yearlyBtn");

  // فتح/غلق المودال
  if (reports_modal) reports_modal.style.display = "none";

  filterBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      if (reports_modal) reports_modal.style.display = "flex";
      filterBtns.forEach((b) => b.classList.remove("active_report"));
      btn.classList.add("active_report");
    });
  });

  if (exit_reports) {
    exit_reports.addEventListener("click", () => {
      reports_modal.style.display = "none";
    });
  }

  window.addEventListener("click", (e) => {
    if (e.target === reports_modal) reports_modal.style.display = "none";
  });

  // الطباعة
  if (printBtn) {
    printBtn.addEventListener("click", () => window.print());
  }

  // عنوان التقرير
  function setReportTitle(type) {
    const today = new Date();
    if (type === "daily") {
      title_report.textContent = "تقرير يوم " + today.toLocaleDateString("ar-EG", {
        weekday: "long", day: "numeric", month: "long", year: "numeric",
      });
    } else if (type === "weekly") {
      const firstDay = new Date(today);
      firstDay.setDate(today.getDate() - ((today.getDay() + 1) % 7));
      const lastDay = new Date(firstDay);
      lastDay.setDate(firstDay.getDate() + 6);
      title_report.textContent = "تقرير الأسبوع من " +
        firstDay.toLocaleDateString("ar-EG", { day: "numeric", month: "long", year: "numeric" }) +
        " إلى " +
        lastDay.toLocaleDateString("ar-EG", { day: "numeric", month: "long", year: "numeric" });
    } else if (type === "monthly") {
      title_report.textContent = "تقرير شهر " + today.toLocaleDateString("ar-EG", {
        month: "long", year: "numeric",
      });
    } else if (type === "yearly") {
      title_report.textContent = "تقرير سنة " + today.toLocaleDateString("ar-EG", {
        year: "numeric",
      });
    }
  }

  // تحديث الكروت والجدول من بيانات الـ API
  function updateReportUI(data) {
    const summary = data.summary;

    if (document.getElementById("total_revenue_value")) {
      document.getElementById("total_revenue_value").textContent = Number(summary.total_revenue).toLocaleString("ar-EG") + " ج.م";
    }
    if (document.getElementById("total_orders_value")) {
      document.getElementById("total_orders_value").textContent = summary.total_orders + " طلب";
    }
    if (document.getElementById("average_order_value")) {
      document.getElementById("average_order_value").textContent = Number(summary.average_order_value).toLocaleString("ar-EG", { maximumFractionDigits: 2 }) + " ج.م";
    }
    if (document.getElementById("cancelled_orders_value")) {
      document.getElementById("cancelled_orders_value").textContent = summary.cancelled_orders + " طلب";
    }
    if (document.getElementById("successful_orders_value")) {
      document.getElementById("successful_orders_value").textContent = summary.successful_orders + " طلب";
    }

    // تحديث جدول الطلبات في المودال
    const tbody = document.querySelector(".orders_table_reports tbody");
    if (tbody && data.orders) {
      tbody.innerHTML = "";
      if (data.orders.length === 0) {
        tbody.innerHTML = "<tr><td colspan='5' style='text-align:center;padding:24px;opacity:.6'>لا توجد طلبات في هذه الفترة</td></tr>";
        return;
      }
      data.orders.forEach((order, index) => {
        const tr = document.createElement("tr");
        if (index === data.orders.length - 1) {
          tr.classList.add("final_row");
        }
        tr.innerHTML = `
          <td>#${order.order_number}</td>
          <td>${order.order_type}</td>
          <td>${order.items_summary}</td>
          <td>${Number(order.total_amount).toLocaleString("ar-EG")} ج.م</td>
          <td>${order.created_at_time}</td>
        `;
        tbody.appendChild(tr);
      });
    }
  }

  // جلب البيانات من الـ API باستخدام apiFetch المشتركة
  async function fetchReportData(type) {
    const today = new Date();
    let url = "";
    if (type === "daily") {
      url = "/reports/daily";
    } else if (type === "weekly") {
      url = "/reports/weekly";
    } else if (type === "monthly") {
      url = `/reports/monthly?year=${today.getFullYear()}&month=${today.getMonth() + 1}`;
    } else if (type === "yearly") {
      url = `/reports/yearly?year=${today.getFullYear()}`;
    }

    try {
      const response = await window.apiFetch(url);

      if (response.ok) {
        const data = await response.json();
        updateReportUI(data);
      } else {
        console.error("Report API error:", response.status);
      }
    } catch (error) {
      console.error("Error fetching report data:", error);
    }
  }

  if (dailyBtn) {
    dailyBtn.addEventListener("click", () => {
      setReportTitle("daily");
      fetchReportData("daily");
    });
  }
  if (weeklyBtn) {
    weeklyBtn.addEventListener("click", () => {
      setReportTitle("weekly");
      fetchReportData("weekly");
    });
  }
  if (monthlyBtn) {
    monthlyBtn.addEventListener("click", () => {
      setReportTitle("monthly");
      fetchReportData("monthly");
    });
  }
  if (yearlyBtn) {
    yearlyBtn.addEventListener("click", () => {
      setReportTitle("yearly");
      fetchReportData("yearly");
    });
  }

  // فلتر مخصص بالتواريخ
  const customStartDate = document.getElementById("customStartDate");
  const customEndDate = document.getElementById("customEndDate");
  const customDateBtn = document.getElementById("customDateBtn");

  if (customDateBtn && customStartDate && customEndDate) {
    // تعيين تواريخ افتراضية (اليوم)
    const todayStr = new Date().toISOString().split('T')[0];
    customStartDate.value = todayStr;
    customEndDate.value = todayStr;

    customDateBtn.addEventListener("click", async () => {
      const start = customStartDate.value;
      const end = customEndDate.value;
      
      if (!start || !end) {
        alert("برجاء اختيار تاريخ البداية والنهاية");
        return;
      }

      if (reports_modal) reports_modal.style.display = "flex";
      filterBtns.forEach((b) => b.classList.remove("active_report"));

      const sDate = new Date(start);
      const eDate = new Date(end);
      title_report.textContent = "تقرير من " + 
        sDate.toLocaleDateString("ar-EG", { day: "numeric", month: "long", year: "numeric" }) +
        " إلى " +
        eDate.toLocaleDateString("ar-EG", { day: "numeric", month: "long", year: "numeric" });

      try {
        const url = `/reports/custom?start_date=${start}&end_date=${end}`;
        const response = await window.apiFetch(url);

        if (response.ok) {
          const data = await response.json();
          updateReportUI(data);
        } else {
          console.error("Custom Report API error:", response.status);
        }
      } catch (error) {
        console.error("Error fetching custom report data:", error);
      }
    });
  }

  // عنوان افتراضي - بدون fetch تلقائي عشان ميبطئش الصفحة
  setReportTitle("daily");
});