(function () {
  const form = document.getElementById("whatsappSettingsForm");
  if (!form) return;

  const apiKeyInput = document.getElementById("whatsappApiKey");
  const apiKeyStatus = document.getElementById("whatsappApiKeyStatus");
  const messageInput = document.getElementById("whatsappBulkMessage");
  const phoneNumberIdInput = document.getElementById("whatsappPhoneNumberId");
  const graphVersionInput = document.getElementById("whatsappGraphVersion");
  const firstOrderTemplateInput = document.getElementById("whatsappFirstOrderTemplateName");
  const orderDetailsTemplateInput = document.getElementById("whatsappOrderDetailsTemplateName");
  const orderStatusTemplateInput = document.getElementById("whatsappOrderStatusTemplateName");
  const languageCodeInput = document.getElementById("whatsappLanguageCode");
  const enabledInput = document.getElementById("whatsappEnabled");
  const bulkTemplateInput = document.getElementById("whatsappBulkTemplateName");
  const businessPhoneInput = document.getElementById("whatsappBusinessPhone");
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
      firstOrderTemplateInput.value = data.first_order_template_name || "topchef_first_order_details";
      orderDetailsTemplateInput.value = data.order_details_template_name || "topchef_order_details";
      orderStatusTemplateInput.value = data.order_status_template_name || "topchef_order_status";
      languageCodeInput.value = data.language_code || "ar";
      enabledInput.checked = Boolean(data.enabled);
      bulkTemplateInput.value = data.bulk_template_name || "topchef_bulk_message";
      businessPhoneInput.value = data.business_phone_number || "";
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
      first_order_template_name: firstOrderTemplateInput.value.trim(),
      order_details_template_name: orderDetailsTemplateInput.value.trim(),
      order_status_template_name: orderStatusTemplateInput.value.trim(),
      language_code: languageCodeInput.value.trim(),
      enabled: enabledInput.checked,
      bulk_template_name: bulkTemplateInput.value.trim(),
      password_reset_template_name: currentSettings.password_reset_template_name || "topchef_password_reset",
      reset_code_expiry_minutes: currentSettings.reset_code_expiry_minutes || 10,
      bulk_send_limit: Number(bulkLimitInput.value),
      business_phone_number: businessPhoneInput.value.trim(),
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
