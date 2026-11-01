(function () {
  const form = document.getElementById("whatsappSettingsForm");
  if (!form || form.hidden) return;

  const apiKeyInput = document.getElementById("whatsappApiKey");
  const apiKeyStatus = document.getElementById("whatsappApiKeyStatus");
  const messageInput = document.getElementById("whatsappBulkMessage");
  const phoneNumberIdInput = document.getElementById("whatsappPhoneNumberId");
  const graphVersionInput = document.getElementById("whatsappGraphVersion");
  const languageCodeInput = document.getElementById("whatsappLanguageCode");
  const enabledInput = document.getElementById("whatsappEnabled");
  const bulkTemplateInput = document.getElementById("whatsappBulkTemplateName");
  const businessPhoneInput = document.getElementById("whatsappBusinessPhone");
  const customerServicePhoneInput = document.getElementById("whatsappCustomerServicePhone");
  const menuUrlInput = document.getElementById("whatsappMenuUrl");
  const webhookTokenInput = document.getElementById("whatsappWebhookToken");
  const appSecretInput = document.getElementById("whatsappAppSecret");
  const bulkLimitInput = document.getElementById("whatsappBulkLimit");
  const bulkSendButton = document.getElementById("sendWhatsAppBulk");
  const messageCount = document.getElementById("whatsappMessageCount");
  const notice = document.getElementById("whatsappSettingsNotice");
  const saveButton = document.getElementById("saveWhatsAppSettings");
  const toggleButton = document.getElementById("toggleWhatsAppApiKey");
  let currentSettings = {};

  function showNotice(message, type) {
    notice.hidden = false;
    notice.className = `settings_notice ${type}`;
    notice.textContent = message;
  }

  function errorMessage(data, fallback) {
    if (typeof data?.detail === "string") return data.detail;
    if (Array.isArray(data?.detail)) return data.detail.map((item) => item.msg).filter(Boolean).join("، ") || fallback;
    return fallback;
  }

  function updateCount() {
    messageCount.textContent = messageInput.value.length.toLocaleString("ar-EG");
  }

  async function loadSettings() {
    try {
      const response = await window.apiFetch("/settings/whatsapp");
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(errorMessage(data, "تعذر تحميل إعدادات واتساب"));
      currentSettings = data;
      messageInput.value = data.bulk_message || "";
      phoneNumberIdInput.value = data.phone_number_id || "";
      graphVersionInput.value = data.graph_api_version || "v23.0";
      languageCodeInput.value = data.language_code || "ar";
      enabledInput.checked = Boolean(data.enabled);
      bulkTemplateInput.value = data.bulk_template_name || "topchef_bulk_message";
      businessPhoneInput.value = data.business_phone_number || "201129820007";
      customerServicePhoneInput.value = data.customer_service_phone || "";
      menuUrlInput.value = data.menu_url || "https://topchefeg.com/";
      webhookTokenInput.placeholder = data.webhook_verify_token_configured ? "محفوظ — اتركه فارغًا للاحتفاظ به" : "أدخل Verify Token";
      appSecretInput.placeholder = data.app_secret_configured ? "محفوظ — اتركه فارغًا للاحتفاظ به" : "أدخل Meta App Secret";
      bulkLimitInput.value = data.bulk_send_limit || 500;
      apiKeyStatus.textContent = data.api_key_configured
        ? "يوجد مفتاح محفوظ — اترك الخانة فارغة للاحتفاظ به"
        : "لا يوجد مفتاح API محفوظ";
      apiKeyStatus.classList.toggle("configured", Boolean(data.api_key_configured));
      updateCount();
    } catch (error) {
      showNotice(error.message || "تعذر تحميل إعدادات واتساب", "error");
    }
  }

  messageInput.addEventListener("input", updateCount);
  toggleButton.addEventListener("click", () => {
    const visible = apiKeyInput.type === "text";
    apiKeyInput.type = visible ? "password" : "text";
    toggleButton.textContent = visible ? "إظهار" : "إخفاء";
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    saveButton.disabled = true;
    saveButton.textContent = "جاري الحفظ...";
    notice.hidden = true;
    const payload = {
      bulk_message: messageInput.value.trim(),
      phone_number_id: phoneNumberIdInput.value.trim(),
      graph_api_version: graphVersionInput.value.trim(),
      first_order_template_name: currentSettings.first_order_template_name || "topchef_first_order_details",
      order_details_template_name: currentSettings.order_details_template_name || "topchef_order_details",
      order_status_template_name: currentSettings.order_status_template_name || "topchef_order_status",
      language_code: languageCodeInput.value.trim(),
      enabled: enabledInput.checked,
      bulk_template_name: bulkTemplateInput.value.trim(),
      password_reset_template_name: currentSettings.password_reset_template_name || "topchef_password_reset",
      reset_code_expiry_minutes: currentSettings.reset_code_expiry_minutes || 10,
      bulk_send_limit: Number(bulkLimitInput.value),
      business_phone_number: businessPhoneInput.value.trim(),
      customer_service_phone: customerServicePhoneInput.value.trim(),
      menu_url: menuUrlInput.value.trim(),
    };
    if (apiKeyInput.value.trim()) payload.api_key = apiKeyInput.value.trim();
    if (webhookTokenInput.value.trim()) payload.webhook_verify_token = webhookTokenInput.value.trim();
    if (appSecretInput.value.trim()) payload.app_secret = appSecretInput.value.trim();

    try {
      const response = await window.apiFetch("/settings/whatsapp", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(errorMessage(data, "فشل حفظ إعدادات واتساب"));
      apiKeyInput.value = "";
      webhookTokenInput.value = "";
      appSecretInput.value = "";
      apiKeyStatus.textContent = data.api_key_configured
        ? "يوجد مفتاح محفوظ — اترك الخانة فارغة للاحتفاظ به"
        : "لا يوجد مفتاح API محفوظ";
      apiKeyStatus.classList.toggle("configured", Boolean(data.api_key_configured));
      showNotice("تم حفظ إعدادات واتساب بنجاح", "success");
    } catch (error) {
      showNotice(error.message || "تعذر الاتصال بالخادم", "error");
    } finally {
      saveButton.disabled = false;
      saveButton.textContent = "حفظ الإعدادات";
    }
  });

  bulkSendButton.addEventListener("click", async () => {
    if (!messageInput.value.trim()) return showNotice("اكتب الرسالة الجماعية واحفظها أولًا", "error");
    if (!window.confirm("سيتم إرسال الرسالة لكل العملاء المسجلين ضمن الحد المحدد. هل تريد المتابعة؟")) return;
    bulkSendButton.disabled = true;
    bulkSendButton.textContent = "جاري إضافة الرسائل...";
    try {
      const response = await window.apiFetch("/settings/whatsapp/bulk-send", { method: "POST" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(errorMessage(data, "فشل بدء الإرسال الجماعي"));
      showNotice(`تمت إضافة ${Number(data.queued_count || 0).toLocaleString("ar-EG")} رسالة للإرسال`, "success");
    } catch (error) {
      showNotice(error.message || "فشل بدء الإرسال الجماعي", "error");
    } finally {
      bulkSendButton.disabled = false;
      bulkSendButton.textContent = "إرسال الرسالة الجماعية";
    }
  });

  loadSettings();
})();

(function () {
  const form = document.getElementById("loyaltySettingsForm");
  if (!form) return;
  const tiers = document.getElementById("loyaltyTiers");
  const redemptionRules = document.getElementById("redemptionRules");
  let rewardProducts = [];
  const notice = document.getElementById("loyaltySettingsNotice");
  const save = document.getElementById("saveLoyaltySettings");
  const show = (message, type) => {
    notice.hidden = false;
    notice.className = `settings_notice ${type}`;
    notice.textContent = message;
  };
  const errorMessage = (data, fallback) => typeof data?.detail === "string"
    ? data.detail
    : Array.isArray(data?.detail)
      ? data.detail.map(item => item.msg).filter(Boolean).join("، ") || fallback
      : fallback;

  function addTier(value = {}) {
    if (tiers.children.length >= 20) return show("الحد الأقصى 20 شريحة", "error");
    const previous = tiers.lastElementChild;
    const previousStart = Number(previous?.querySelector('[data-field="from_amount"]')?.value || 0);
    const previousStep = Number(previous?.querySelector('[data-field="step_amount"]')?.value || 100);
    const row = document.createElement("div");
    row.className = "loyalty_tier";
    row.innerHTML = `<label class="settings_field"><span>تبدأ من مبلغ (ج.م)</span><input data-field="from_amount" type="number" min="0" step="0.01" required></label>
      <label class="settings_field"><span>كل مبلغ كامل (ج.م)</span><input data-field="step_amount" type="number" min="0.01" step="0.01" required></label>
      <label class="settings_field"><span>نقاط لكل مبلغ كامل</span><input data-field="points_per_step" type="number" min="1" max="100000" step="1" required></label>
      <button type="button" aria-label="حذف الشريحة">حذف</button>`;
    row.querySelector('[data-field="from_amount"]').value = value.from_amount ?? (previous ? previousStart + previousStep : 0);
    row.querySelector('[data-field="step_amount"]').value = value.step_amount ?? 100;
    row.querySelector('[data-field="points_per_step"]').value = value.points_per_step ?? 10;
    row.querySelector("button").onclick = () => row.remove();
    tiers.appendChild(row);
  }

  function addRedemptionRule(value = {}) {
    if (redemptionRules.children.length >= 20) return show("الحد الأقصى 20 قاعدة استبدال", "error");
    const row = document.createElement("div");
    row.className = "loyalty_tier redemption_rule";
    row.dataset.ruleId = value.id || crypto.randomUUID();
    row.innerHTML = `<label class="settings_field"><span>نوع المكافأة</span><select data-field="reward_type"><option value="fixed_discount">خصم ثابت</option><option value="free_product">صنف مجاني</option></select></label>
      <label class="settings_field"><span>النقاط المطلوبة</span><input data-field="points_required" type="number" min="1" max="1000000" step="1" required></label>
      <label class="settings_field" data-fixed><span>قيمة الخصم (ج.م)</span><input data-field="discount_amount" type="number" min="0.01" step="0.01"></label>
      <label class="settings_field" data-free><span>الصنف المجاني</span><select data-field="product_id"></select></label>
      <label class="settings_field" data-free><span>الحجم أو السعر</span><select data-field="variant_id"></select></label>
      <button type="button" aria-label="حذف قاعدة الاستبدال">حذف</button>`;
    const type = row.querySelector('[data-field="reward_type"]');
    const product = row.querySelector('[data-field="product_id"]');
    const variant = row.querySelector('[data-field="variant_id"]');
    type.value = value.reward_type || "fixed_discount";
    rewardProducts.filter(item => item.is_available).forEach(item => product.add(new Option(item.product_name, item.id)));
    if (value.product_id) product.value = String(value.product_id);
    const updateVariants = () => {
      variant.replaceChildren();
      const selected = rewardProducts.find(item => String(item.id) === product.value);
      (selected?.variants || []).forEach(item => variant.add(new Option(`${item.name} — ${Number(item.price).toFixed(2)} ج.م`, item.id)));
      if (value.variant_id && String(value.product_id) === product.value) variant.value = String(value.variant_id);
    };
    const updateType = () => {
      const free = type.value === "free_product";
      row.querySelectorAll("[data-free]").forEach(field => { field.hidden = !free; field.querySelector("select").required = free; });
      row.querySelector("[data-fixed]").hidden = free;
      row.querySelector('[data-field="discount_amount"]').required = !free;
    };
    product.onchange = updateVariants;
    type.onchange = updateType;
    row.querySelector('[data-field="points_required"]').value = value.points_required ?? 100;
    row.querySelector('[data-field="discount_amount"]').value = value.discount_amount ?? 10;
    row.querySelector("button").onclick = () => row.remove();
    updateVariants(); updateType();
    redemptionRules.appendChild(row);
  }

  document.getElementById("addLoyaltyTier").onclick = () => addTier();
  document.getElementById("addRedemptionRule").onclick = () => addRedemptionRule();
  async function load() {
    try {
      const [response, productsResponse] = await Promise.all([
        window.apiFetch("/settings/loyalty"), window.apiFetch("/menu/products"),
      ]);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(errorMessage(data, "تعذر تحميل قواعد النقاط"));
      if (!productsResponse.ok) throw new Error("تعذر تحميل الأصناف لقواعد المكافآت");
      rewardProducts = await productsResponse.json();
      document.getElementById("loyaltyEnabled").checked = Boolean(data.enabled);
      document.getElementById("redemptionEnabled").checked = Boolean(data.redemption_enabled);
      document.getElementById("loyaltyMinimumOrder").value = data.minimum_order_amount ?? 0;
      document.getElementById("loyaltyMaxPoints").value = data.max_points_per_order ?? 10000;
      tiers.replaceChildren();
      (data.tiers || []).forEach(addTier);
      redemptionRules.replaceChildren();
      (data.redemption_rules || []).forEach(addRedemptionRule);
      if (!data.configured) show("البرنامج متوقف. أضف الشرائح واحفظها لتبدأ النقاط بعد التفعيل.", "success");
    } catch (error) { show(error.message || "تعذر تحميل قواعد النقاط", "error"); }
  }
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const payload = {
      enabled: document.getElementById("loyaltyEnabled").checked,
      redemption_enabled: document.getElementById("redemptionEnabled").checked,
      minimum_order_amount: document.getElementById("loyaltyMinimumOrder").value,
      max_points_per_order: Number(document.getElementById("loyaltyMaxPoints").value),
      tiers: [...tiers.children].map(row => Object.fromEntries(
        [...row.querySelectorAll("[data-field]")].map(input => [input.dataset.field,
          input.dataset.field === "points_per_step" ? Number(input.value) : input.value])
      )),
      redemption_rules: [...redemptionRules.children].map(row => ({
        id: row.dataset.ruleId,
        reward_type: row.querySelector('[data-field="reward_type"]').value,
        points_required: Number(row.querySelector('[data-field="points_required"]').value),
        ...(row.querySelector('[data-field="reward_type"]').value === "free_product"
          ? {product_id: Number(row.querySelector('[data-field="product_id"]').value), variant_id: Number(row.querySelector('[data-field="variant_id"]').value)}
          : {discount_amount: row.querySelector('[data-field="discount_amount"]').value}),
      })),
    };
    save.disabled = true;
    notice.hidden = true;
    try {
      const response = await window.apiFetch("/settings/loyalty", {
        method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(errorMessage(data, "تعذر حفظ قواعد النقاط"));
      const earningState = data.active ? "احتساب النقاط مفعّل للطلبات المؤكدة القادمة" : "احتساب النقاط متوقف";
      const redemptionState = data.redemption_active ? "استبدال النقاط متاح للعميل" : "الاستبدال متوقف ومخفي عن العميل";
      show(`تم حفظ القواعد. ${earningState}، و${redemptionState}.`, "success");
    } catch (error) { show(error.message || "تعذر الاتصال بالخادم", "error"); }
    finally { save.disabled = false; }
  });
  load();
})();

(function () {
  const form = document.getElementById("paymentSettingsForm");
  if (!form) return;
  const fields = {
    instapay_enabled: document.getElementById("instapayEnabled"),
    instapay_account: document.getElementById("instapayAccount"),
    wallet_enabled: document.getElementById("walletEnabled"),
    wallet_number: document.getElementById("walletNumber"),
    payment_account_name: document.getElementById("paymentAccountName"),
  };
  const notice = document.getElementById("paymentSettingsNotice");
  const save = document.getElementById("savePaymentSettings");
  const show = (message, type) => { notice.hidden = false; notice.className = `settings_notice ${type}`; notice.textContent = message; };
  async function load() {
    try {
      const response = await window.apiFetch("/settings/payments");
      const data = await response.json();
      if (!response.ok) throw new Error("تعذر تحميل بيانات الدفع");
      Object.entries(fields).forEach(([key, input]) => { if (input.type === "checkbox") input.checked = Boolean(data[key]); else input.value = data[key] || ""; });
    } catch (error) { show(error.message, "error"); }
  }
  form.addEventListener("submit", async event => {
    event.preventDefault(); save.disabled = true; save.textContent = "جاري الحفظ...";
    const payload = Object.fromEntries(Object.entries(fields).map(([key, input]) => [key, input.type === "checkbox" ? input.checked : input.value.trim()]));
    try {
      const response = await window.apiFetch("/settings/payments", {method:"PATCH", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "تعذر حفظ بيانات الدفع");
      show("تم حفظ بيانات الدفع", "success");
    } catch (error) { show(error.message, "error"); }
    finally { save.disabled = false; save.textContent = "حفظ بيانات الدفع"; }
  });
  load();
})();
