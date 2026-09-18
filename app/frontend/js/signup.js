(function () {
  const form = document.querySelector(".signup_form");
  if (!form) return; // مش صفحة اللوجن، اخرج بهدوء

  const API_BASE = window.location.origin;

  const usernameInput = form.querySelector('input[type="text"]');
  const passwordInput = document.getElementById('password_input') || form.querySelector('input[type="password"]');
  const submitBtn     = form.querySelector("button[type='submit']");
  const resetForm = document.getElementById("passwordResetForm");
  const forgotButton = document.getElementById("forgotPasswordButton");

  // ===== Regex Rules =====
  const RULES = {
    username: {
      regex: /^[a-zA-Z0-9_\u0600-\u06FF]{3,20}$/,
      message: "اسم المستخدم: 3-20 حرف، حروف وأرقام وـ فقط",
    },
    password: {
      regex: /^.{6,}$/,
      message: "كلمة المرور: 6 أحرف على الأقل",
    },
  };

  // ===== Real-time validation =====
  usernameInput.addEventListener("input", () => validateField(usernameInput, "username"));
  passwordInput.addEventListener("input", () => validateField(passwordInput, "password"));

  // ===== Submit =====
  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const usernameValid = validateField(usernameInput, "username");
    const passwordValid = validateField(passwordInput, "password");
    if (!usernameValid || !passwordValid) return;

    setLoading(true);
    clearFormError();

    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: usernameInput.value.trim(),
          password: passwordInput.value,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        const msg = typeof data?.detail === "string"
          ? data.detail
          : data?.detail?.[0]?.msg || "اسم المستخدم أو كلمة المرور غلط";
        showFormError(msg);
        return;
      }

      // ✅ حفظ البيانات
      localStorage.setItem("token",      data.access_token);
      localStorage.setItem("token_type", data.token_type);
      localStorage.setItem("user_id",    data.user_id);
      localStorage.setItem("username",   data.username);
      localStorage.setItem("role",       data.role);

      // ✅ محاولة جلب الاسم الكامل من الاستجابة أو استخدام اسم المستخدم كاسم افتراضي
      let fullName = data.full_name || data.name;

      if (fullName) {
        localStorage.setItem("full_name", fullName);
      } else {
        localStorage.setItem("full_name", data.username); // Fallback
      }

      // ✅ توجيه حسب الرول
      if (data.role === "cashier") {
        window.location.href = "/cashier/cashier.html";
      } else {
        window.location.href = "dashboard.html";
      }

    } catch (err) {
      console.error("Login error:", err);
      showFormError("حدث خطأ في الاتصال، تحقق من الإنترنت وحاول مرة تانية");
    } finally {
      setLoading(false);
    }
  });

  // ===== Validate field =====
  function validateField(input, fieldName) {
    const value = input.value.trim();
    const rule  = RULES[fieldName];

    if (!value) {
      setFieldState(input, "error", "هذا الحقل مطلوب");
      return false;
    }
    if (!rule.regex.test(value)) {
      setFieldState(input, "error", rule.message);
      return false;
    }
    setFieldState(input, "success", "");
    return true;
  }

  // ===== Field state =====
  function setFieldState(input, state, message) {
    input.classList.remove("input_error", "input_success");

    const anchor    = input.closest(".input_wrapper") || input;
    const container = anchor.parentElement;
    const old = container.querySelector(".field_hint");
    if (old) old.remove();

    if (state === "error") {
      input.classList.add("input_error");
      if (message) {
        const hint = document.createElement("span");
        hint.className   = "field_hint hint_error";
        hint.textContent = "⚠ " + message;
        anchor.insertAdjacentElement("afterend", hint);
      }
    } else if (state === "success") {
      input.classList.add("input_success");
    }
  }

  // ===== Form error =====
  function showFormError(msg) {
    clearFormError();
    const err = document.createElement("p");
    err.className   = "form_error";
    err.textContent = "⚠ " + msg;
    form.insertBefore(err, submitBtn);
  }

  function clearFormError() {
    const old = form.querySelector(".form_error");
    if (old) old.remove();
  }

  // ===== Loading =====
  function setLoading(isLoading) {
    submitBtn.disabled    = isLoading;
    submitBtn.textContent = isLoading ? "جاري الدخول..." : "دخول";
  }

  if (resetForm && forgotButton) {
    const resetUsername = document.getElementById("resetUsername");
    const resetPassword = document.getElementById("resetNewPassword");
    const resetFields = document.getElementById("resetCodeFields");
    const resetNotice = document.getElementById("passwordResetNotice");
    const sendCodeButton = document.getElementById("sendResetCode");
    let resetChallengeId = "";
    let resetPollTimer = null;

    const showResetNotice = (message, type) => {
      resetNotice.hidden = false;
      resetNotice.className = `reset_notice ${type}`;
      resetNotice.textContent = message;
    };
    forgotButton.addEventListener("click", () => {
      resetUsername.value = usernameInput.value.trim();
      form.hidden = true;
      resetForm.hidden = false;
    });
    document.getElementById("backToLogin").addEventListener("click", () => {
      if (resetPollTimer) clearTimeout(resetPollTimer);
      resetPollTimer = null;
      resetChallengeId = "";
      resetForm.hidden = true;
      form.hidden = false;
      resetNotice.hidden = true;
    });
    sendCodeButton.addEventListener("click", async () => {
      const username = resetUsername.value.trim();
      if (!RULES.username.regex.test(username)) return showResetNotice(RULES.username.message, "error");
      sendCodeButton.disabled = true;
      try {
        const response = await fetch(`${API_BASE}/auth/forgot-password`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "تعذر بدء التحقق");
        resetChallengeId = data.challenge_id;
        const whatsappWindow = window.open(data.whatsapp_url, "_blank", "noopener,noreferrer");
        if (!whatsappWindow) showResetNotice("اسمح بفتح النوافذ ثم اضغط الزر مرة أخرى", "error");
        else showResetNotice("أرسل الرسالة الجاهزة من واتساب. ننتظر التأكيد...", "success");
        const poll = async () => {
          if (!resetChallengeId) return;
          try {
            const statusResponse = await fetch(`${API_BASE}/auth/password-reset-status/${encodeURIComponent(resetChallengeId)}`);
            const status = await statusResponse.json().catch(() => ({}));
            if (statusResponse.ok && status.verified) {
              resetFields.hidden = false;
              showResetNotice("تم تأكيد واتساب. اختر كلمة المرور الجديدة.", "success");
              return;
            }
          } catch (_) {}
          resetPollTimer = setTimeout(poll, 2000);
        };
        poll();
      } catch (error) {
        showResetNotice(error.message || "تعذر الاتصال بالخادم", "error");
      } finally {
        sendCodeButton.disabled = false;
      }
    });
    resetForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const newPassword = resetPassword.value.trim();
      if (!resetChallengeId) return showResetNotice("ابدأ تأكيد واتساب أولاً", "error");
      if (!/^[A-Za-z0-9]{6,}$/.test(newPassword)) return showResetNotice("كلمة المرور 6 خانات على الأقل، حروف إنجليزية أو أرقام فقط", "error");
      const button = resetForm.querySelector("button[type='submit']");
      button.disabled = true;
      try {
        const response = await fetch(`${API_BASE}/auth/reset-password`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: resetUsername.value.trim(), challenge_id: resetChallengeId, new_password: newPassword }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "تعذر تغيير كلمة المرور");
        showResetNotice(data.message, "success");
        setTimeout(() => document.getElementById("backToLogin").click(), 1200);
      } catch (error) {
        showResetNotice(error.message || "تعذر الاتصال بالخادم", "error");
      } finally {
        button.disabled = false;
      }
    });
  }

})();
