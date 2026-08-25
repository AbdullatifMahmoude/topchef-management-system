(function () {
  const form = document.getElementById("whatsappSettingsForm");
  if (!form) return;

  const apiKeyInput = document.getElementById("whatsappApiKey");
  const apiKeyStatus = document.getElementById("whatsappApiKeyStatus");
  const messageInput = document.getElementById("whatsappBulkMessage");
  const phoneNumberIdInput = document.getElementById("whatsappPhoneNumberId");
  const graphVersionInput = document.getElementById("whatsappGraphVersion");
  const templateNameInput = document.getElementById("whatsappTemplateName");
  const languageCodeInput = document.getElementById("whatsappLanguageCode");
  const enabledInput = document.getElementById("whatsappEnabled");
  const bulkTemplateInput = document.getElementById("whatsappBulkTemplateName");
  const resetTemplateInput = document.getElementById("whatsappResetTemplateName");
  const resetExpiryInput = document.getElementById("whatsappResetExpiry");
  const bulkLimitInput = document.getElementById("whatsappBulkLimit");
  const bulkSendButton = document.getElementById("sendWhatsAppBulk");
  const messageCount = document.getElementById("whatsappMessageCount");
  const notice = document.getElementById("whatsappSettingsNotice");
  const saveButton = document.getElementById("saveWhatsAppSettings");
  const toggleButton = document.getElementById("toggleWhatsAppApiKey");

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
      messageInput.value = data.bulk_message || "";
      phoneNumberIdInput.value = data.phone_number_id || "";
      graphVersionInput.value = data.graph_api_version || "v23.0";
      templateNameInput.value = data.template_name || "topchef_order_update";
      languageCodeInput.value = data.language_code || "ar";
      enabledInput.checked = Boolean(data.enabled);
      bulkTemplateInput.value = data.bulk_template_name || "topchef_bulk_message";
      resetTemplateInput.value = data.password_reset_template_name || "topchef_password_reset";
      resetExpiryInput.value = data.reset_code_expiry_minutes || 10;
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
      template_name: templateNameInput.value.trim(),
      language_code: languageCodeInput.value.trim(),
      enabled: enabledInput.checked,
      bulk_template_name: bulkTemplateInput.value.trim(),
      password_reset_template_name: resetTemplateInput.value.trim(),
      reset_code_expiry_minutes: Number(resetExpiryInput.value),
      bulk_send_limit: Number(bulkLimitInput.value),
    };
    if (apiKeyInput.value.trim()) payload.api_key = apiKeyInput.value.trim();

    try {
      const response = await window.apiFetch("/settings/whatsapp", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(errorMessage(data, "فشل حفظ إعدادات واتساب"));
      apiKeyInput.value = "";
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
