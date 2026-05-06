// ============================================================
//  offer.js  –  صفحة العروض (مرتبطة بالـ API)
// ============================================================

(function () {

  /* ================================================================
     عناصر الصفحة
  ================================================================ */
  const page            = document.getElementById("page-offers");
  const tbody           = page.querySelector(".orders_table_offers tbody");
  const searchBar       = page.querySelector(".search-bar-offers");
  const addBtn          = page.querySelector(".add_btn_offers");
  const modal           = page.querySelector(".offers_modal");
  const exitBtn         = page.querySelector(".offers_exit img");
  const offerForm       = page.querySelector(".offer-form");

  /* ---- حقول الفورم ---- */
  const inpCode         = offerForm.querySelector('input[placeholder="مثال: SAVE20"]');
  const selType         = offerForm.querySelector(".form-group-select");
  const inpDiscount     = offerForm.querySelector(".form-group-price input");
  const inputs_amount   = offerForm.querySelectorAll(".form-group-amoun input");
  const inpMinOrder     = inputs_amount[0];
  const inpMaxDiscount  = inputs_amount[1];
  const inputs_num      = offerForm.querySelectorAll(".form-group-num input");
  const inpUsageLimit   = inputs_num[0];
  const inpUsagePerUser = inputs_num[1];
  const switchEl        = offerForm.querySelector(".status_offers .switch");
  const inputs_date     = offerForm.querySelectorAll(".form-group-from input");
  const inpFrom         = inputs_date[0];
  const inpTo           = inputs_date[1];
  const submitBtn       = offerForm.querySelector(".form-group-submit-btn");

  /* ---- حالة ---- */
  let allOffers = [];
  let editId    = null;
  let isActive  = true;

  /* ================================================================
     خريطة تحويل: عربي ↔ API
  ================================================================ */
  const typeMap = {
    "نسبة مئوية"          : "percentage",
    "خصم ثابت"            : "fixed",
    "اشترِ واحد وخذ واحد" : "buy_one_get_one",
    "خصم موسمي"           : "seasonal_discount",
    "كود ترويجي"          : "promo_code",
    "خصم كميات"           : "bulk_discount",
  };
  const typeMapReverse = Object.fromEntries(
    Object.entries(typeMap).map(([ar, en]) => [en, ar])
  );

  /* ================================================================
     Switch في الفورم
  ================================================================ */
  switchEl.addEventListener("click", () => {
    isActive = !isActive;
    switchEl.classList.toggle("active", isActive);
  });

  /* عناوين الجدول مكتوبة في الـ HTML مباشرة */

  /* ================================================================
     رسم صفوف الجدول
  ================================================================ */
  function buildTable(offers) {
    tbody.innerHTML = "";

    if (!offers.length) {
      tbody.innerHTML = `
        <tr>
          <td colspan="11" style="text-align:center;padding:24px;opacity:.6">
            لا توجد عروض
          </td>
        </tr>`;
      return;
    }

    offers.forEach((offer) => {
      const tr = document.createElement("tr");
      tr.className = "offers_body_row";

      const fromDate = offer.valid_from ? offer.valid_from.slice(0, 10) : "—";
      const toDate   = offer.valid_to   ? offer.valid_to.slice(0, 10)   : "—";
      const typeAr   = typeMapReverse[offer.discount_type] || offer.discount_type;
      const isOn     = offer.is_active;

      tr.innerHTML = `
        <td>${offer.code}</td>
        <td>${typeAr}</td>
        <td>${offer.discount_value}</td>
        <td>${offer.min_order_amount}</td>
        <td>${offer.max_discount_amount}</td>
        <td>${offer.usage_limit}</td>
        <td>${offer.usage_per_user}</td>
        <td>${fromDate}</td>
        <td>${toDate}</td>
        <td class="switch_td">
          <div class="switch ${isOn ? "active" : ""}">
            <div class="circle"></div>
          </div>
        </td>
        <td>
          <div class="event_icons">
            <img src="/assets/delete.png"     alt="حذف"   class="del-btn"  style="cursor:pointer" />
            <img src="/assets/Edit_light.png" alt="تعديل" class="edit-btn" style="cursor:pointer" />
          </div>
        </td>
      `;

      /* أحداث الصف */
      const swEl = tr.querySelector(".switch");
      swEl.addEventListener("click", () => toggleOffer(offer, swEl));
      tr.querySelector(".del-btn").addEventListener("click", () => deleteOffer(offer.offer_id));
      tr.querySelector(".edit-btn").addEventListener("click", () => openModal(offer));

      tbody.appendChild(tr);
    });
  }

  /* ================================================================
     جلب العروض من الـ API
  ================================================================ */
  async function fetchOffers() {
    tbody.innerHTML = `
      <tr>
        <td colspan="11" style="text-align:center;padding:24px;opacity:.6">
          جاري التحميل...
        </td>
      </tr>`;
    try {
      const res = await window.apiFetch("/offers/");
      if (!res.ok) throw new Error();
      allOffers = await res.json();
      buildTable(allOffers);
    } catch {
      tbody.innerHTML = `
        <tr>
          <td colspan="11" style="text-align:center;padding:24px;color:red">
            خطأ في جلب البيانات
          </td>
        </tr>`;
    }
  }

  /* ================================================================
     فتح / إغلاق المودال
  ================================================================ */
  function openModal(offer = null) {
    editId = offer ? offer.offer_id : null;

    /* عنوان المودال */
    page.querySelector(".logo_title_modal_offers h1").textContent =
      offer ? "تعديل العرض" : "أضف عرض جديد";
    submitBtn.textContent = offer ? "تحديث العرض" : "حفظ العرض";

    if (offer) {
      inpCode.value         = offer.code                || "";
      selType.value         = typeMapReverse[offer.discount_type] || "";
      inpDiscount.value     = offer.discount_value      || "";
      inpMinOrder.value     = offer.min_order_amount    || "";
      inpMaxDiscount.value  = offer.max_discount_amount || "";
      inpUsageLimit.value   = offer.usage_limit         || "";
      inpUsagePerUser.value = offer.usage_per_user      || "";
      inpFrom.value         = offer.valid_from ? offer.valid_from.slice(0, 10) : "";
      inpTo.value           = offer.valid_to   ? offer.valid_to.slice(0, 10)   : "";
      isActive              = offer.is_active;
    } else {
      offerForm.reset();
      isActive = true;
    }

    switchEl.classList.toggle("active", isActive);
    modal.style.display = "flex";
  }

  function closeModal() {
    modal.style.display = "none";
    editId = null;
  }

  addBtn.addEventListener("click", () => openModal());
  exitBtn.addEventListener("click", closeModal);
  modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });

  /* ================================================================
     حفظ (إضافة أو تعديل)
  ================================================================ */
  offerForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const discountTypeEn = typeMap[selType.value];
    if (!discountTypeEn) {
      alert("من فضلك اختر نوع العرض");
      return;
    }

    const payload = {
      code               : inpCode.value.trim(),
      discount_type      : discountTypeEn,
      discount_value     : parseFloat(inpDiscount.value)    || 0,
      min_order_amount   : parseFloat(inpMinOrder.value)    || 0,
      max_discount_amount: parseFloat(inpMaxDiscount.value) || 0,
      usage_limit        : parseInt(inpUsageLimit.value)    || 0,
      usage_per_user     : parseInt(inpUsagePerUser.value)  || 0,
      is_active          : isActive,
      valid_from         : inpFrom.value ? new Date(inpFrom.value).toISOString() : null,
      valid_to           : inpTo.value   ? new Date(inpTo.value).toISOString()   : null,
    };

    try {
      const res = await window.apiFetch(
        editId ? `/offers/${editId}` : "/offers/",
        { method: editId ? "PATCH" : "POST", body: JSON.stringify(payload) }
      );

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert("خطأ: " + (err.detail?.[0]?.msg || "حدث خطأ"));
        return;
      }

      closeModal();
      fetchOffers();
    } catch {
      alert("حدث خطأ أثناء الحفظ");
    }
  });

  /* ================================================================
     warning modal للحذف
  ================================================================ */
  const warningModal   = page.querySelector(".offers_warning_modal");
  const warningExit    = page.querySelector(".offers_warning_exit img");
  const confirmDelBtn  = page.querySelector(".offers_confirm_delete_btn");
  let pendingDeleteId  = null;

  function openWarning(id) {
    pendingDeleteId = id;
    warningModal.style.display = "flex";
  }

  function closeWarning() {
    warningModal.style.display = "none";
    pendingDeleteId = null;
  }

  warningExit.addEventListener("click", closeWarning);
  warningModal.addEventListener("click", (e) => { if (e.target === warningModal) closeWarning(); });

  confirmDelBtn.addEventListener("click", async () => {
    if (!pendingDeleteId) return;
    const id = pendingDeleteId;
    closeWarning();
    try {
      const res = await window.apiFetch(`/offers/${id}`, { method: "DELETE" });
      if (res.status === 204 || res.ok) {
        fetchOffers();
      } else {
        alert("فشل الحذف");
      }
    } catch {
      alert("حدث خطأ أثناء الحذف");
    }
  });

  /* ================================================================
     حذف عرض
  ================================================================ */
  function deleteOffer(id) {
    openWarning(id);
  }

  /* ================================================================
     تفعيل / تعطيل من الجدول
  ================================================================ */
  async function toggleOffer(offer, swEl) {
    try {
      const res = await window.apiFetch(`/offers/${offer.offer_id}`, {
        method : "PATCH",
        hideLoader: true,
        body   : JSON.stringify({ is_active: !offer.is_active }),
      });
      if (res.ok) {
        offer.is_active = !offer.is_active;
        swEl.classList.toggle("active", offer.is_active);
      }
    } catch {
      alert("حدث خطأ أثناء تغيير الحالة");
    }
  }

  /* ================================================================
     بحث
  ================================================================ */
  searchBar.addEventListener("input", () => {
    const q = searchBar.value.trim().toLowerCase();
    if (!q) { buildTable(allOffers); return; }
    buildTable(
      allOffers.filter(
        (o) =>
          o.code.toLowerCase().includes(q) ||
          (typeMapReverse[o.discount_type] || "").includes(q)
      )
    );
  });

  /* ================================================================
     تشغيل تلقائي لما الصفحة تتفتح
  ================================================================ */
  const offerSideBtn = document.querySelector('[data-page="offers"]');
  if (offerSideBtn) {
    offerSideBtn.addEventListener("click", fetchOffers);
  }

  /* لو الصفحة مفتوحة بالفعل */
  if (page.style.display !== "none") fetchOffers();

})();
(function () {
  const offersModal = document.querySelector(".offers_modal");
  const offersExit  = document.querySelector(".offers_exit");
  const addOffersBtn = document.querySelector(".add_btn_offers");
  const offerForm   = document.querySelector(".offer-form");

  if (!offerForm) return;

  // ===== ELEMENTS =====
  const codeInput      = offerForm.querySelector('input[placeholder="مثال: SAVE20"]');
  const discountInput  = offerForm.querySelector(".form-group-price input");
  const minQtyInput    = offerForm.querySelectorAll(".form-group-amoun input")[0];
  const maxQtyInput    = offerForm.querySelectorAll(".form-group-amoun input")[1];
  const dateFrom       = offerForm.querySelectorAll('input[type="date"]')[0];
  const dateTo         = offerForm.querySelectorAll('input[type="date"]')[1];
  const offerTypeSelect = offerForm.querySelector(".form-group-select");

  // ===== REAL-TIME VALIDATION =====
  codeInput?.addEventListener("input",     () => validateField(codeInput, "offerCode"));
  discountInput?.addEventListener("input", () => validateField(discountInput, "discountValue"));
  minQtyInput?.addEventListener("input",   () => validateField(minQtyInput, "quantity"));
  maxQtyInput?.addEventListener("input",   () => validateQtyRange());
  dateFrom?.addEventListener("change",     () => validateField(dateFrom, "date"));
  dateTo?.addEventListener("change",       () => validateDateRange());

  // ===== VALIDATE MAX >= MIN =====
  function validateQtyRange() {
    const min = parseInt(minQtyInput?.value);
    const max = parseInt(maxQtyInput?.value);
    if (!validateField(maxQtyInput, "quantity")) return false;
    if (min && max && max < min) {
      setFieldState(maxQtyInput, "error", "أقصى كمية يجب أن تكون أكبر من أو تساوي أقل كمية");
      return false;
    }
    setFieldState(maxQtyInput, "success", "");
    return true;
  }

  // ===== VALIDATE DATE RANGE =====
  function validateDateRange() {
    if (!validateField(dateTo, "date")) return false;
    const from = new Date(dateFrom?.value);
    const to   = new Date(dateTo?.value);
    if (dateFrom?.value && dateTo?.value && to < from) {
      setFieldState(dateTo, "error", "تاريخ الانتهاء يجب أن يكون بعد تاريخ البداية");
      return false;
    }
    setFieldState(dateTo, "success", "");
    return true;
  }

  // ===== FORM SUBMIT =====
  offerForm.addEventListener("submit", (e) => {
    e.preventDefault();

    // validate نوع العرض
    if (!offerTypeSelect?.value || offerTypeSelect.value === "نوع العرض") {
      offerTypeSelect.style.border = "2px solid #e74c3c";
      
      return;
    } else {
      offerTypeSelect.style.border = "";
    }

    const codeValid    = validateField(codeInput, "offerCode");
    const discountValid = validateField(discountInput, "discountValue");
    const minValid     = validateField(minQtyInput, "quantity");
    const maxValid     = validateQtyRange();
    const dateFromValid = validateField(dateFrom, "date");
    const dateToValid  = validateDateRange();

    if (!codeValid || !discountValid || !minValid || !maxValid || !dateFromValid || !dateToValid) return;

    // ✅ كل الـ validation عدى — ابعت للـ API
    const body = {
      code:          codeInput.value.trim().toUpperCase(),
      type:          offerTypeSelect.value,
      discount:      parseFloat(discountInput.value),
      min_qty:       parseInt(minQtyInput.value),
      max_qty:       parseInt(maxQtyInput.value),
      date_from:     dateFrom.value,
      date_to:       dateTo.value,
    };

    console.log("✅ offer body:", body);
    // TODO: apiFetch("/offers", { method: "POST", body: JSON.stringify(body) })

    alert("تم حفظ العرض بنجاح ✅");
    closeOffersModal();
  });

  // ===== MODAL =====
  function openOffersModal() {
    offerForm.reset();
    [codeInput, discountInput, minQtyInput, maxQtyInput, dateFrom, dateTo].forEach(
      (el) => el && clearFieldState(el)
    );
    if (offersModal) offersModal.style.display = "flex";
  }

  function closeOffersModal() {
    if (offersModal) offersModal.style.display = "none";
  }

  addOffersBtn?.addEventListener("click", openOffersModal);
  offersExit?.addEventListener("click", closeOffersModal);
  window.addEventListener("click", (e) => {
    if (e.target === offersModal) closeOffersModal();
  });

})();