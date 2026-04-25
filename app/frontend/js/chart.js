document.addEventListener("DOMContentLoaded", () => {
  const filterBtns     = document.querySelectorAll(".filter-btn");
  const reports_modal  = document.querySelector(".reports_modal");
  const exit_reports   = document.querySelector(".exit_reports_modal");
  const title_report   = document.querySelector(".title_report");
  const printBtn       = document.getElementById("printBtn");
  const dailyBtn       = document.getElementById("dailyBtn");
  const weeklyBtn      = document.getElementById("weeklyBtn");
  const monthlyBtn     = document.getElementById("monthlyBtn");

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
    }
  }

  if (dailyBtn)   dailyBtn.addEventListener("click",   () => setReportTitle("daily"));
  if (weeklyBtn)  weeklyBtn.addEventListener("click",  () => setReportTitle("weekly"));
  if (monthlyBtn) monthlyBtn.addEventListener("click", () => setReportTitle("monthly"));

  // عنوان افتراضي
  setReportTitle("monthly");
});