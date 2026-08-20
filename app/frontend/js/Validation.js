// ============================================
// validation.js
// ============================================

(function injectValidationStyles() {
  const style = document.createElement("style");
  style.textContent = `
    /* ── الـ hint يتحط أسفل الـ input بدون ما يكسر الـ layout ── */

    /* كل container بيحتوي input لازم يبقى flex-column */
    .form-group,
    .form-group-price,
    .form-group-amoun,
    .form-group-num,
    .form-group-from,
    .form_category_modal,
    .form_modal_delivery .delivery_form {
      align-items: center;
    }

    /* الـ hint نفسه */
    .field_hint {
      font-size: 11px;
      margin-top: 3px;
      display: block;
      width: 100%;
      text-align: right;
      font-family: "Cairo", sans-serif;
      line-height: 1.3;
      max-width: 400px;
    }
    .hint_error  { color: #e74c3c; text-align: center; }
    .hint_success { color: #2ecc71; }

    /* border على الـ input نفسه */
    .input_error {
      border: 1.5px solid #e74c3c !important;
      box-shadow: 0 0 0 2px rgba(231,76,60,0.15) !important;
      outline: none !important;
    }
    .input_success {
      border: 1.5px solid #2ecc71 !important;
      box-shadow: 0 0 0 2px rgba(46,204,113,0.1) !important;
      outline: none !important;
    }
  `;
  document.head.appendChild(style);
})();

// ===== RULES =====
const VALIDATION_RULES = {
  username: {
    regex: /^[\u0600-\u06FF a-zA-Z0-9_]{3,30}$/,
    message: "الاسم: 3-30 حرف، حروف عربية أو إنجليزية وأرقام فقط",
  },
  productName: {
    regex: /^[\u0600-\u06FF a-zA-Z0-9\-_().،,]{2,50}$/,
    message: "اسم الصنف: 2-50 حرف، حروف وأرقام فقط",
  },
  categoryName: {
    regex: /^[\u0600-\u06FF a-zA-Z0-9\-_]{2,30}$/,
    message: "اسم التصنيف: 2-30 حرف، حروف وأرقام فقط",
  },
  sizeName: {
    regex: /^[\u0600-\u06FF a-zA-Z0-9\-_/.()]{1,20}$/,
    message: "اسم الحجم: 1-20 حرف (أرقام وحروف)",
  },
  price: {
    regex: /^\d+(\.\d{1,2})?$/,
    message: "أرقام فقط، مثال: 10 أو 10.50",
    extra: (val) => parseFloat(val) > 0 || "يجب أن يكون أكبر من صفر",
  },
  phone: {
    regex: /^01[0125][0-9]{8}$/,
    message: "11 رقم يبدأ بـ 010 أو 011 أو 012 أو 015",
  },
  password: {
    regex: /^[a-zA-Z0-9]{6,}$/,
    message: "6 أحرف على الأقل، أرقام أو أرقام وحروف",
  },
  offerCode: {
    regex: /^[a-zA-Z0-9]{3,20}$/,
    message: "حروف إنجليزية وأرقام فقط، 3-20 حرف",
  },
  discountValue: {
    regex: /^\d+(\.\d{1,2})?$/,
    message: "أرقام فقط، مثال: 10 أو 10.50",
    extra: (val) => parseFloat(val) > 0 || "يجب أن تكون أكبر من صفر",
  },
  quantity: {
    regex: /^[1-9][0-9]*$/,
    message: "أرقام صحيحة موجبة فقط",
  },
  date: {
    regex: /^\d{4}-\d{2}-\d{2}$/,
    message: "يرجى اختيار تاريخ صحيح",
  },
};

// ============================================
// getHintContainer
// بيدور على أقرب container مناسب للـ hint
// الأولوية: .form-group أو .form-group-* أو parentElement
// ============================================
function getHintContainer(input) {
  return (
    input.closest(".form-group-price") ||
    input.closest(".form-group-amoun") ||
    input.closest(".form-group-num")   ||
    input.closest(".form-group-from")  ||
    input.closest(".form-group")       ||
    input.parentElement
  );
}

// ============================================
// setFieldState
// ============================================
function setFieldState(input, state, message) {
  input.classList.remove("input_error", "input_success");

  const container = getHintContainer(input);

  // شيل الـ hint القديم المرتبط بالـ input ده بس
  const oldHint = container.querySelector(".field_hint[data-for]");
  if (oldHint && oldHint.dataset.for === input.placeholder) oldHint.remove();

  // شيل أي hint قديم خالص
  const allOld = container.querySelectorAll(".field_hint");
  allOld.forEach(h => h.remove());

  if (state === "error") {
    input.classList.add("input_error");
    if (message) {
      const hint = document.createElement("span");
      hint.className = "field_hint hint_error";
      hint.dataset.for = input.placeholder || "";
      hint.textContent = "⚠ " + message;
      // حطه بعد الـ input مباشرةً جوه الـ container
      input.insertAdjacentElement("afterend", hint);
    }
  } else if (state === "success") {
    input.classList.add("input_success");
    // The green border is the success indicator. Keeping the checkmark out of
    // the layout prevents fields in horizontal rows from being pushed aside.
  }
}

function clearFieldState(input) {
  input.classList.remove("input_error", "input_success");
  const container = getHintContainer(input);
  container.querySelectorAll(".field_hint").forEach(h => h.remove());
}

// ============================================
// validateField
// ============================================
function validateField(input, ruleKey) {
  const value = input.value.trim();
  const rule = VALIDATION_RULES[ruleKey];
  if (!rule) return true;

  if (!value) {
    setFieldState(input, "error", "هذا الحقل مطلوب");
    return false;
  }
  if (!rule.regex.test(value)) {
    setFieldState(input, "error", rule.message);
    return false;
  }
  if (rule.extra) {
    const extraResult = rule.extra(value);
    if (extraResult !== true) {
      setFieldState(input, "error", extraResult);
      return false;
    }
  }

  setFieldState(input, "success", "");
  return true;
}

// ============================================
// validateOptionalField — مش مطلوب (كلمة السر في التعديل)
// ============================================
function validateOptionalField(input, ruleKey) {
  if (!input.value.trim()) {
    clearFieldState(input);
    return true;
  }
  return validateField(input, ruleKey);
}
