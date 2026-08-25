// ============================================
// Toggle switch functionality
// ============================================
document.querySelectorAll(".switch").forEach((t) => {
  t.addEventListener("click", () => t.classList.toggle("active"));
});

// ============================================
// دالة تطبيع النص العربي
// ============================================
function normalizeArabic(text) {
  return text
    .toLowerCase()
    .replace(/[أإآ]/g, "ا")
    .replace(/ة/g, "ه")
    .replace(/ى/g, "ي")
    .replace(/[ًٌٍَُِّْ]/g, "")
    .trim();
}
// ============================================
// نظام التنقل بين الصفحات - SPA Navigation
// ============================================
function showPage(pageId) {
  document.querySelectorAll(".page-content").forEach((page) => {
    page.style.display = "none";
  });

  const targetPage = document.getElementById("page-" + pageId);
  if (targetPage) targetPage.style.display = "block";

  document.querySelectorAll(".side_btn[data-page]").forEach((btn) => {
    btn.classList.toggle("active", btn.getAttribute("data-page") === pageId);
  });

  if (pageId === "home") {
    if (typeof refreshDashboard === "function") refreshDashboard();
  }
  if (pageId === "delivery-ops" && typeof window.refreshDeliveryOperations === "function") {
    window.refreshDeliveryOperations();
  }

  history.pushState({ page: pageId }, "", "#" + pageId);
}

// ============================================
// DOMContentLoaded - كل الأحداث في بلوك واحد
// ============================================
document.addEventListener("DOMContentLoaded", function () {

  // --- تفعيل القائمة الجانبية في مقاس التابلت ---
  const sidebar = document.querySelector(".sidemenu");
  const toggleBtn = document.getElementById("sidebar_toggle_btn");
  const overlay = document.getElementById("sidemenu_overlay");

  if (sidebar && toggleBtn && overlay) {
    const tabletQuery = window.matchMedia("(max-width: 1280px)");

    const closeSidebar = () => {
      sidebar.classList.remove("open");
      overlay.classList.remove("active");
      toggleBtn.setAttribute("aria-expanded", "false");
    };

    const openSidebar = () => {
      if (!tabletQuery.matches) return;
      sidebar.classList.add("open");
      overlay.classList.add("active");
      toggleBtn.setAttribute("aria-expanded", "true");
    };

    const toggleSidebar = () => {
      if (sidebar.classList.contains("open")) {
        closeSidebar();
      } else {
        openSidebar();
      }
    };

    toggleBtn.setAttribute("aria-controls", "admin_sidemenu");
    toggleBtn.setAttribute("aria-expanded", "false");
    sidebar.id = sidebar.id || "admin_sidemenu";

    toggleBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      toggleSidebar();
    });

    overlay.addEventListener("click", closeSidebar);

    sidebar.querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", closeSidebar);
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeSidebar();
    });

    const handleTabletChange = () => {
      if (!tabletQuery.matches) closeSidebar();
    };

    if (typeof tabletQuery.addEventListener === "function") {
      tabletQuery.addEventListener("change", handleTabletChange);
    } else if (typeof tabletQuery.addListener === "function") {
      tabletQuery.addListener(handleTabletChange);
    }
  }

  // --- أزرار السايد منيو ---
  document.querySelectorAll(".side_btn[data-page]").forEach((btn) => {
    btn.addEventListener("click", function () {
      showPage(this.getAttribute("data-page"));
    });
  });

  // --- موديل الأصناف ---
  const itemModal = document.querySelector(".modal");
  const addItemBtn = document.querySelector(".add_btn");
  const itemExit = itemModal?.querySelector(".exit");

  if (addItemBtn && itemModal && itemExit) {
    addItemBtn.addEventListener("click", () => (itemModal.style.display = "flex"));
    itemExit.addEventListener("click", () => (itemModal.style.display = "none"));
    window.addEventListener("click", (e) => { if (e.target === itemModal) itemModal.style.display = "none"; });
  }

  // --- موديل الدليفري --- ✅ مصلح: بنبحث جوا الـ modal مش في كل الصفحة
  const deliveryModal = document.querySelector(".delivery_modal");
  const addDeliveryBtn = document.querySelector(".add_btn_delivery");
  const deliveryExit = deliveryModal?.querySelector(".exit"); // ✅ مصلح

  if (deliveryModal) deliveryModal.style.display = "none";
  if (addDeliveryBtn && deliveryModal && deliveryExit) {
    addDeliveryBtn.addEventListener("click", () => (deliveryModal.style.display = "flex"));
    deliveryExit.addEventListener("click", () => (deliveryModal.style.display = "none"));
    window.addEventListener("click", (e) => { if (e.target === deliveryModal) deliveryModal.style.display = "none"; });
  }

  // --- موديل العروض ---
  const offersModal = document.querySelector(".offers_modal");
  const addOffersBtn = document.querySelector(".add_btn_offers");
  const offersExit = document.querySelector(".offers_exit");

  if (addOffersBtn && offersModal && offersExit) {
    addOffersBtn.addEventListener("click", () => (offersModal.style.display = "flex"));
    offersExit.addEventListener("click", () => (offersModal.style.display = "none"));
    window.addEventListener("click", (e) => { if (e.target === offersModal) offersModal.style.display = "none"; });
  }

  // --- البحث في الأصناف --- (متعمل في product.js)

  // --- البحث في العروض ---
  document.querySelectorAll(".search-bar-offers").forEach((input) => {
    input.addEventListener("input", function () {
      filterTable(this.value, ".orders_table_offers tbody", "لا يوجد عروض");
    });
  });

  // --- تحديد الصفحة الأولى ---
  const hash = window.location.hash.replace("#", "");
  const validPages = ["home", "items", "categories", "delivery", "delivery-ops", "shifts", "reports", "offers", "settings", "events"];
  showPage(validPages.includes(hash) ? hash : "home");

  // --- Back/Forward ---
  window.addEventListener("popstate", (e) => {
    showPage(e.state?.page || "home");
  });
});

// ============================================
// دالة البحث المشتركة
// ============================================
function filterTable(value, tbodySelector, emptyMessage) {
  const searchValue = normalizeArabic(value);
  const rows = document.querySelectorAll(tbodySelector + " tr:not(.no-results-message)");
  let found = false;

  rows.forEach((row) => {
    const match = normalizeArabic(row.textContent).includes(searchValue);
    row.style.display = match ? "" : "none";
    if (match) found = true;
  });

  const tbody = document.querySelector(tbodySelector);
  let message = tbody?.querySelector(".no-results-message");
  if (!message && tbody) {
    message = document.createElement("tr");
    message.className = "no-results-message";
    message.innerHTML = `<td colspan="100%" style="text-align:center; color:red;">${emptyMessage}</td>`;
    tbody.appendChild(message);
  }
  if (message) message.style.display = found ? "none" : "";
}
