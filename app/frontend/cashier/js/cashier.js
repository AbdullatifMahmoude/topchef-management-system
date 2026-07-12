const API_BASE = window.location.origin;
const IS_DESKTOP_RUNTIME = ["127.0.0.1", "localhost"].includes(
  window.location.hostname,
);

// ===================================================
//  Global API Fetch Wrapper
// ===================================================
async function apiFetch(path, options = {}) {
  const token = localStorage.getItem("token");
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;

  const headers = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: "Bearer " + token } : {}),
    ...(options.headers || {}),
  };

  try {
    const response = await fetch(url, { ...options, headers });

    // إذا انتهت الجلسة أو الـ Token غير صالح (401)
    // ومسموح لنا بالتحويل التلقائي (الوضع الافتراضي)
    if (response.status === 401 && !options.suppress401) {
      console.warn(
        "Session expired or unauthorized (401). Redirecting to login...",
      );
      localStorage.clear();
      window.location.replace("../index.html");
      return new Promise(() => {}); // إيقاف التنفيذ الحالي
    }

    return response;
  } catch (error) {
    console.error(`Fetch error for ${url}:`, error);
    throw error;
  }
}

// ===================================================
//  State
// ===================================================
let categories = [];
let products = [];
let activeCatId = null;
let cart = [];

// Online Orders State
let onlineOrdersList = [];
let onlineOrdersFilter = "all"; // 'all', 'new', 'ready', 'cancelled'
let onlineOrdersSearchTerm = "";
let onlineOrdersCurrentPage = 1;
let onlineOrdersTotal = 0;
let totalNewOrdersGlobalCount = 0; // New orders only
const ordersPageSize = 30;
let lastNewOrdersCount = 0;
let isNotificationSoundEnabled = true;
let socket = null;
let reconnectTimerId = null;
let ordersSnapshotLoaded = false;
let lastSocketOrderUpdate = Date.now();

// نوع الطلب: null | 'dine_in' | 'takeaway' | 'delivery'
let orderType = null;
// بيانات الديليفري المختار
let selectedDelivery = null; // { id, name }
let selectedDeliveryFee = null; // number
let selectedDineInFee = null; // number (رسوم الصالة)

// بيانات عميل الديليفري
let deliveryCustomerInfo = {
  phone: "",
  name: "",
  customerId: null,
  addresses: [],
  selectedAddressId: null,
  newAddress: "",
};
let _phoneSearchTimeout = null;

function normalizePhoneDigits(phone) {
  return String(phone || "").replace(/\D/g, "").slice(0, 11);
}

function hasFeeValue(value) {
  return value !== null && value !== undefined && value !== "";
}

function formatFeeValue(value) {
  const numericValue = Number(value);
  return Number.isFinite(numericValue) ? `${numericValue.toFixed(0)} ج.م` : "0 ج.م";
}

function isValidEgyptianPhone(phone) {
  return /^\d{11}$/.test(normalizePhoneDigits(phone));
}


function getOrderAddressText(order) {
  if (!order) return "";
  const raw = order.customer_address || order.address || "";
  if (raw && typeof raw === "object") {
    return raw.address || raw.address_line || raw.full_address || raw.street || raw.name || "";
  }
  return raw || "";
}

// ===================================================
//  Init
// ===================================================
async function init() {
  // Start WebSocket connection early
  setupWebSocket();

  showGlobalLoader(true);

  try {
    const [catsRes, prodsRes] = await Promise.all([
      apiFetch("/menu/categories"),
      apiFetch("/menu/products"),
    ]);

    if (!catsRes.ok || !prodsRes.ok) throw new Error("API error loading menu");

    categories = await catsRes.json();
    products = await prodsRes.json();

    categories = Array.isArray(categories)
      ? categories.filter((c) => c.is_active)
      : [];

    if (categories.length > 0) {
      activeCatId = categories[0].id;
    }

    renderTabs();
    renderItems();
    initWebOrdersToggle();

    // Initial badge refresh
    refreshNewOrdersBadge();
  } catch (err) {
    console.error("API error:", err);
    document.getElementById("items_grid").innerHTML =
      `<p style="color:#e40411;text-align:center;grid-column:1/-1">حدث خطأ في تحميل البيانات</p>`;
  } finally {
    showGlobalLoader(false);
  }
}

// ===================================================
//  Tabs
// ===================================================
function renderTabs() {
  const container = document.getElementById("category_tabs");
  container.innerHTML = "";

  categories.forEach((cat) => {
    const btn = document.createElement("button");
    btn.className = "tab_btn" + (cat.id === activeCatId ? " active" : "");
    btn.textContent = cat.cat_name;
    btn.onclick = () => {
      activeCatId = cat.id;
      renderTabs();
      renderItems();
    };
    container.appendChild(btn);
  });
}

// ===================================================
//  Items Grid
// ===================================================
function renderItems() {
  const grid = document.getElementById("items_grid");
  grid.innerHTML = "";

  const catProducts = products.filter(
    (p) => p.cat_id === activeCatId && p.is_available,
  );

  if (catProducts.length === 0) {
    grid.innerHTML = `<p style="color:var(--color-subtext);grid-column:1/-1;text-align:center;padding:30px">لا توجد أصناف في هذا التصنيف</p>`;
    return;
  }

  catProducts.forEach((product) => {
    const variants = product.variants || [];
    const prices = variants
      .map((v) => parseFloat(v.price))
      .filter((p) => !isNaN(p) && p > 0);

    const price = prices.length > 0 ? Math.min(...prices) : 0;

    const priceLabel =
      variants.length > 1
        ? ` ${price} ج.م`
        : price > 0
          ? `${price} ج.م`
          : "السعر غير محدد";

    const description =
      product.description || product.desc || product.product_desc || "";
    const descriptionHtml = description
      ? `<p style="font-size: 11px; color: var(--color-subtext);  line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis;margin:0">${description}</p>`
      : "";

    const card = document.createElement("div");
    card.className = "item_card";
    card.innerHTML = `
      <h1>${product.product_name}</h1>
      ${descriptionHtml}
      <h2>${priceLabel}</h2>
    `;
    card.onclick = () => handleProductClick(product, price);
    grid.appendChild(card);
  });
}

// ===================================================
//  Variant Picker
// ===================================================
function handleProductClick(product, defaultPrice) {
  const variants = product.variants || [];
  if (variants.length <= 1) {
    addToCart({
      id: product.id,
      name: product.product_name,
      price: defaultPrice,
    });
    return;
  }
  showVariantPicker(product);
}

function showVariantPicker(product) {
  const old = document.getElementById("variant_picker");
  if (old) old.remove();

  const overlay = document.createElement("div");
  overlay.id = "variant_picker";
  overlay.style.cssText = `
    position:fixed;inset:0;background:rgba(0,0,0,0.75);
    display:flex;align-items:center;justify-content:center;z-index:9999;
  `;

  const box = document.createElement("div");
  box.style.cssText = `
    background:rgba(15,12,6,0.97);border:1px solid var(--color-primary-border);
    border-radius:16px;padding:24px;min-width:280px;display:flex;
    flex-direction:column;gap:12px;direction:rtl;
  `;

  box.innerHTML = `
    <h2 style="color:var(--color-primary);font-size:16px;margin:0;text-align:center">${product.product_name}</h2>
    <p style="color:var(--color-subtext);font-size:13px;text-align:center;margin:0">اختر الحجم</p>
  `;

  product.variants.forEach((v) => {
    const btn = document.createElement("button");
    btn.style.cssText = `
      background:var(--color-primary-light);border:1px solid var(--color-primary-border);
      border-radius:10px;padding:10px 16px;color:var(--color-text);font-family:Cairo,sans-serif;
      font-size:14px;font-weight:700;cursor:pointer;display:flex;
      justify-content:space-between;align-items:center;
    `;
    btn.innerHTML = `<span>${v.name}</span><span style="color:var(--color-primary)">${parseFloat(v.price)} ج.م</span>`;
    btn.onclick = () => {
      addToCart({
        id: `${product.id}_${v.id}`,
        name: `${product.product_name} (${v.name})`,
        price: parseFloat(v.price),
      });
      overlay.remove();
    };
    box.appendChild(btn);
  });

  const cancelBtn = document.createElement("button");
  cancelBtn.textContent = "إلغاء";
  cancelBtn.style.cssText = `
    background:transparent;border:1px solid var(--color-subtext);border-radius:10px;
    padding:8px;color:var(--color-subtext);font-family:Cairo,sans-serif;
    font-size:14px;cursor:pointer;margin-top:4px;
  `;
  cancelBtn.onclick = () => overlay.remove();
  box.appendChild(cancelBtn);

  overlay.appendChild(box);
  overlay.onclick = (e) => {
    if (e.target === overlay) overlay.remove();
  };
  document.body.appendChild(overlay);
}

// ===================================================
//  Cart Logic
// ===================================================
function addToCart(item) {
  const existing = cart.find((c) => String(c.item.id) === String(item.id));
  if (existing) {
    existing.qty++;
  } else {
    cart.push({ item, qty: 1 });
  }
  renderCart();
}

function removeFromCart(itemId) {
  cart = cart.filter((c) => String(c.item.id) !== String(itemId));
  renderCart();
}

function changeQty(itemId, delta) {
  const entry = cart.find((c) => String(c.item.id) === String(itemId));
  if (!entry) return;
  entry.qty += delta;
  if (entry.qty <= 0) {
    cart = cart.filter((c) => String(c.item.id) !== String(itemId));
  }
  renderCart();
}

function renderCart() {
  const list = document.getElementById("cart_list");
  const empty = document.getElementById("cart_empty");
  const totalEl = document.getElementById("total_price");

  const itemsTotal = cart.reduce((sum, c) => sum + c.item.price * c.qty, 0);
  let fee = 0;
  if (orderType === "delivery" && hasFeeValue(selectedDeliveryFee))
    fee = selectedDeliveryFee;
  else if (orderType === "dine_in" && hasFeeValue(selectedDineInFee))
    fee = selectedDineInFee;

  const grandTotal = itemsTotal + fee;
  totalEl.textContent = grandTotal.toFixed(2) + " ج.م";

  // استدعاء معاينة الأسعار من الباك إند
  updatePricingPreview();

  if (cart.length === 0) {
    list.innerHTML = "";
    list.appendChild(empty);
    empty.style.display = "flex";
    return;
  }

  if (empty) empty.style.display = "none";

  const existingCards = {};
  list.querySelectorAll(".total_card[data-id]").forEach((el) => {
    existingCards[el.dataset.id] = el;
  });

  const newIds = new Set(cart.map((c) => String(c.item.id)));

  Object.keys(existingCards).forEach((id) => {
    if (!newIds.has(id)) existingCards[id].remove();
  });

  cart.forEach(({ item, qty }) => {
    const idStr = String(item.id);

    if (existingCards[idStr]) {
      existingCards[idStr].querySelector(".qty_num").textContent = qty;
      existingCards[idStr].querySelector(".card_price").textContent =
        (item.price * qty).toFixed(2) + " ج.م";
    } else {
      const card = document.createElement("div");
      card.className = "total_card";
      card.dataset.id = idStr;
      card.innerHTML = `
        <div class="card_info">
          <h1>${item.name}</h1>
          <h2 class="card_price">${(item.price * qty).toFixed(2)} ج.م</h2>
        </div>
        <div class="card_controls">
          <div class="qty_controls">
            <button class="btn_qty" onclick="changeQty('${idStr}', -1)">−</button>
            <span class="qty_num">${qty}</span>
            <button class="btn_qty" onclick="changeQty('${idStr}', 1)">+</button>
          </div>
          <button class="btn_delete" onclick="removeFromCart('${idStr}')">
            <svg fill="none" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>
      `;
      list.appendChild(card);
    }
  });
}

function confirmOrder() {
  if (cart.length === 0) return;

  if (!orderType) {
    showToast("يرجى اختيار نوع الطلب أولاً", "error");
    return;
  }

  const phoneDigits = normalizePhoneDigits(deliveryCustomerInfo.phone);
  deliveryCustomerInfo.phone = phoneDigits;

  // التحقق من بيانات العميل في حالة الديليفري
  if (orderType === "delivery" && !phoneDigits) {
    showToast("يرجى إدخال رقم تليفون العميل أولاً", "error");
    return;
  }

  if (phoneDigits && !isValidEgyptianPhone(phoneDigits)) {
    showToast("رقم التليفون يجب أن يكون 11 رقم", "error");
    return;
  }

  const itemsTotal = cart.reduce((sum, c) => sum + c.item.price * c.qty, 0);
  let fee = 0;
  if (orderType === "delivery" && hasFeeValue(selectedDeliveryFee))
    fee = selectedDeliveryFee;
  else if (orderType === "dine_in" && hasFeeValue(selectedDineInFee))
    fee = selectedDineInFee;

  const grandTotal = itemsTotal + fee;

  const orderData = {
    cart,
    orderType,
    selectedDelivery,
    selectedDeliveryFee,
    itemsTotal,
    grandTotal,
    customerPhone: deliveryCustomerInfo.phone || null,
    customerName: deliveryCustomerInfo.name || null,
    customerAddress:
      deliveryCustomerInfo.addresses.length > 0 &&
      deliveryCustomerInfo.selectedAddressId
        ? getAddressText(
            deliveryCustomerInfo.addresses.find(
              (a) => a.id === deliveryCustomerInfo.selectedAddressId,
            ) || {},
          )
        : deliveryCustomerInfo.newAddress || null,
  };

  showConfirmModal(orderData);
}

function showConfirmModal(orderData) {
  const old = document.getElementById("confirm_modal");
  if (old) old.remove();

  const overlay = document.createElement("div");
  overlay.id = "confirm_modal";
  overlay.style.cssText = `
    position:fixed;inset:0;background:rgba(0,0,0,0.75);
    display:flex;align-items:center;justify-content:center;z-index:9999;
  `;

  const box = document.createElement("div");
  box.style.cssText = `
    background:rgba(15,12,6,0.97);border:1px solid var(--color-primary-border);
    border-radius:16px;padding:24px;min-width:320px;display:flex;
    flex-direction:column;gap:16px;direction:rtl;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,0.5);
  `;

  box.innerHTML = `
    <h2 style="color:var(--color-primary);font-size:18px;margin:0;">تأكيد وطباعة الطلب</h2>
    <p style="color:var(--color-text);font-size:14px;margin:0;">هل أنت متأكد من تأكيد الطلب بقيمة الإجمالي أدناه؟</p>
    <div style="font-size:24px;font-weight:900;color:var(--color-primary);padding:10px 0;border-top:1px dashed var(--color-primary-border);border-bottom:1px dashed var(--color-primary-border);">
      ${orderData.grandTotal.toFixed(2)} ج.م
    </div>
    <div style="display:flex;gap:12px;margin-top:8px;">
      <button id="btn_confirm_yes" style="
        flex:1;background:var(--color-primary);color:#000;border:none;border-radius:10px;
        padding:12px;font-family:Cairo,sans-serif;font-size:14px;font-weight:900;cursor:pointer;
        transition:opacity 0.2s;
      " onmouseover="this.style.opacity='0.8'" onmouseout="this.style.opacity='1'">طباعة وتأكيد</button>
      
      <button id="btn_confirm_no" style="
        flex:1;background:transparent;border:1px solid rgba(255,255,255,0.2);color:var(--color-subtext);
        border-radius:10px;padding:12px;font-family:Cairo,sans-serif;font-size:14px;font-weight:600;cursor:pointer;
        transition:background 0.2s;
      " onmouseover="this.style.background='rgba(255,255,255,0.05)'" onmouseout="this.style.background='transparent'">إلغاء</button>
    </div>
  `;

  overlay.appendChild(box);
  document.body.appendChild(overlay);

  document.getElementById("btn_confirm_yes").onclick = async () => {
    const btn = document.getElementById("btn_confirm_yes");
    const originalText = btn.textContent;
    btn.textContent = "جاري التأكيد...";
    btn.disabled = true;
    btn.style.opacity = "0.7";
    btn.style.cursor = "not-allowed";

    try {
      const items = cart.map((c) => {
        let prodId = c.item.id;
        if (typeof prodId === "string" && prodId.includes("_")) {
          prodId = parseInt(prodId.split("_")[0], 10);
        } else {
          prodId = parseInt(prodId, 10);
        }
        return {
          product_id: prodId,
          quantity: c.qty,
          unit_price: c.item.price,
        };
      });

      let mappedOrderType = "hall";
      if (orderType === "takeaway") mappedOrderType = "takeaway";
      else if (orderType === "delivery") mappedOrderType = "delivery";

      // معالجة بيانات العميل لجميع أنواع الطلبات
      const dcfNameInput = document.getElementById("dcf_name");
      const dcfAddrInput = document.getElementById("dcf_address_input");
      if (dcfNameInput) deliveryCustomerInfo.name = dcfNameInput.value;
      if (dcfAddrInput) deliveryCustomerInfo.newAddress = dcfAddrInput.value;

      let resolvedCustomerId = deliveryCustomerInfo.customerId;

      if (deliveryCustomerInfo.phone) {
        // 1. لو العميل جديد تماماً، نقوم بإنشائه أولاً
        if (!resolvedCustomerId) {
          try {
            const custRes = await apiFetch("/customers/", {
              method: "POST",
              body: JSON.stringify({
                name: deliveryCustomerInfo.name || "عميل",
                phone_number: deliveryCustomerInfo.phone,
              }),
            });
            if (custRes.ok) {
              const newCust = await custRes.json();
              resolvedCustomerId = newCust.id;
              deliveryCustomerInfo.customerId = resolvedCustomerId;
              // تحديث بيانات الطباعة أيضاً
              orderData.customerName = newCust.name;
            }
          } catch (custErr) {
            console.warn("لم يتم إنشاء العميل:", custErr);
          }
        }

        // 2. لو في عنوان جديد مكتوب يدوياً، نحفظه في قاعدة البيانات
        if (resolvedCustomerId && deliveryCustomerInfo.newAddress) {
          try {
            const addrRes = await apiFetch(
              `/customers/${resolvedCustomerId}/addresses`,
              {
                method: "POST",
                body: JSON.stringify({
                  address: deliveryCustomerInfo.newAddress,
                }),
              },
            );
            if (addrRes.ok) {
              const addrData = await addrRes.json();
              // نحدث الـ ID بتاع العنوان المختار عشان يتبعت مع الطلب
              deliveryCustomerInfo.selectedAddressId = addrData.id;
              // تحديث بيانات الطباعة لتظهر العنوان الصحيح في الفاتورة
              orderData.customerAddress = getAddressText(addrData);
            }
          } catch (addrErr) {
            console.warn("لم يتم حفظ العنوان:", addrErr);
          }
        }
      }

      const customerNotes =
        orderType === "delivery" &&
        !deliveryCustomerInfo.selectedAddressId &&
        deliveryCustomerInfo.newAddress
          ? deliveryCustomerInfo.newAddress
          : null;

      const discountType = document.getElementById("discount_type")?.value || null;
      const discountValue = parseFloat(document.getElementById("discount_value")?.value) || null;
      const discountReason = document.getElementById("discount_reason")?.value || null;

      const payload = {
        customer_id: resolvedCustomerId || null,
        customer_phone: deliveryCustomerInfo.phone || null,
        customer_name: deliveryCustomerInfo.name || null,
        order_type: mappedOrderType,
        source: "cashier",
        customer_notes: customerNotes,
        internal_notes: null,
        items: items,
        idempotency_key:
          Date.now().toString() + Math.random().toString(36).substr(2, 9),
        address_id: deliveryCustomerInfo.selectedAddressId || null,
        customer_address: deliveryCustomerInfo.newAddress || null, // ✅ Fix: Send address string so backend can create a record
        delivery_person_id: selectedDelivery ? selectedDelivery.id : null,
        delivery_fee:
          (orderType === "delivery"
            ? selectedDeliveryFee
            : selectedDineInFee) || 0,
        offer_code: null,
        manual_discount_type: discountType,
        manual_discount_value: discountValue,
        discount_reason: discountReason,
      };

      const res = await apiFetch("/orders/", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        console.error("API Error:", errData);
        let errMsg = "حدث خطأ أثناء إرسال الطلب";
        if (Array.isArray(errData.detail)) {
          errMsg = errData.detail
            .map((d) => `${d.loc ? d.loc.join(".") : "Error"}: ${d.msg}`)
            .join(", ");
        } else if (errData.detail) {
          errMsg =
            typeof errData.detail === "string"
              ? errData.detail
              : JSON.stringify(errData.detail);
        }
        throw new Error(errMsg);
      }

      const createdOrder = await res.json();

      overlay.remove();

      // الطباعة باستخدام بيانات السيرفر لضمان مطابقة رقم الطلب والوقت
      if (typeof printReceipt === "function") {
        // نقوم بتجهيز قائمة الأصناف بالأسماء بناءً على الـ IDS قبل الطباعة
        const cartMapped = (createdOrder.items || []).map((item) => {
          let prod = products.find((p) => p.id === item.product_id);
          let variantName = "";
          if (prod && prod.variants) {
            let v = prod.variants.find(
              (v) => parseFloat(v.price) === parseFloat(item.unit_price),
            );
            if (v && v.name !== prod.product_name)
              variantName = v.name + " - ";
          }
          let name = prod
            ? variantName + prod.product_name
            : `صنف #${item.product_id}`;

          return {
            qty: item.quantity,
            item: {
              name: name,
              price: parseFloat(item.unit_price),
            },
          };
        });

        // ندمج البيانات الأصلية من السيرفر مع قائمة الأصناف المجهزة بالأسماء
        // نضيف بيانات العميل يدوياً كاحتياط لو السيرفر لم يعيدها
        const printData = {
          ...createdOrder,
          cart: cartMapped,
          customerPhone:
            createdOrder.customer_phone || deliveryCustomerInfo.phone || null,
          customerName:
            createdOrder.customer_name || deliveryCustomerInfo.name || null,
          customerAddress:
            createdOrder.customer_address ||
            orderData.customerAddress ||
            deliveryCustomerInfo.newAddress ||
            null,
        };

        printReceipt(printData);
      } else {
        console.error(
          "Function printReceipt not found. ensure print.js is loaded.",
        );
      }

      // تصفية السلة وعودة الحالة للصفر
      cart = [];
      orderType = null;
      selectedDelivery = null;
      selectedDeliveryFee = null;
      selectedDineInFee = null;
      resetDeliveryCustomerInfo();
      const dcFormOk = document.getElementById("delivery_customer_form");
      if (dcFormOk) {
        dcFormOk.style.display = "none";
        dcFormOk.innerHTML = "";
      }
      
      const discType = document.getElementById("discount_type");
      const discValue = document.getElementById("discount_value");
      const discReason = document.getElementById("discount_reason");
      if (discType) discType.value = "";
      if (discValue) discValue.value = "";
      if (discReason) discReason.value = "";
      renderCart();
      renderOrderTypeBadge();
      renderOrderTypeButtons();

      showToast("تم تأكيد الطلب بنجاح", "success");

      // ✅ NEW: Update local memory lists immediately so the order appears without refresh
      if (isOnlineOrder(createdOrder)) {
        if (typeof onlineOrdersList !== "undefined") {
          const exists = onlineOrdersList.find(
            (o) => String(o.id) === String(createdOrder.id),
          );
          if (!exists) onlineOrdersList.unshift(createdOrder);
        }
      } else {
        if (typeof allOrdersList !== "undefined") {
          const exists = allOrdersList.find(
            (o) => String(o.id) === String(createdOrder.id),
          );
          if (!exists) allOrdersList.unshift(createdOrder);
        }
      }

      // Always re-render order tabs so the new order shows up
      renderAllOrders();
      renderOnlineOrders();
      updateOnlineStats();

      // Delayed server fetch to get the synced version from cloud
      setTimeout(() => {
        fetchAllOrdersServer(1, true);
        fetchOnlineOrdersServer(1, true);
      }, 2000);
    } catch (err) {
      console.error(err);
      showToast(err.message, "error");
      btn.textContent = originalText;
      btn.disabled = false;
      btn.style.opacity = "1";
      btn.style.cursor = "pointer";
    }
  };

  document.getElementById("btn_confirm_no").onclick = () => {
    overlay.remove();
  };

  overlay.onclick = (e) => {
    if (e.target === overlay) overlay.remove();
  };
}

function cancelOrder() {
  if (cart.length === 0) return;
  showCancelModal();
}

function showCancelModal() {
  const old = document.getElementById("cancel_modal");
  if (old) old.remove();

  const overlay = document.createElement("div");
  overlay.id = "cancel_modal";
  overlay.style.cssText = `
    position:fixed;inset:0;background:rgba(0,0,0,0.75);
    display:flex;align-items:center;justify-content:center;z-index:9999;
  `;

  const box = document.createElement("div");
  box.style.cssText = `
    background:rgba(15,12,6,0.97);border:1px solid var(--color-primary-border);
    border-radius:16px;padding:24px;min-width:320px;display:flex;
    flex-direction:column;gap:16px;direction:rtl;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,0.5);
  `;

  box.innerHTML = `
    <h2 style="color:#e40411;font-size:18px;margin:0;">إلغاء الطلب</h2>
    <p style="color:var(--color-text);font-size:14px;margin:0;">هل أنت متأكد من إلغاء الطلب الحالي ومسح السلة؟</p>
    <div style="display:flex;gap:12px;margin-top:8px;">
      <button id="btn_cancel_yes" style="
        flex:1;background:#e40411;color:#fff;border:none;border-radius:10px;
        padding:12px;font-family:Cairo,sans-serif;font-size:14px;font-weight:900;cursor:pointer;
        transition:opacity 0.2s;
      " onmouseover="this.style.opacity='0.8'" onmouseout="this.style.opacity='1'">نعم، إلغاء</button>
      
      <button id="btn_cancel_no" style="
        flex:1;background:transparent;border:1px solid rgba(255,255,255,0.2);color:var(--color-subtext);
        border-radius:10px;padding:12px;font-family:Cairo,sans-serif;font-size:14px;font-weight:600;cursor:pointer;
        transition:background 0.2s;
      " onmouseover="this.style.background='rgba(255,255,255,0.05)'" onmouseout="this.style.background='transparent'">تراجع</button>
    </div>
  `;

  overlay.appendChild(box);
  document.body.appendChild(overlay);

  document.getElementById("btn_cancel_yes").onclick = () => {
    overlay.remove();
    cart = [];
    orderType = null;
    selectedDelivery = null;
    selectedDeliveryFee = null;
    selectedDineInFee = null;
    resetDeliveryCustomerInfo();
    const dcFormCancel = document.getElementById("delivery_customer_form");
    if (dcFormCancel) {
      dcFormCancel.style.display = "none";
      dcFormCancel.innerHTML = "";
    }
    renderCart();
    renderOrderTypeBadge();
    renderOrderTypeButtons();
    showToast("تم إلغاء الطلب", "error");
  };

  document.getElementById("btn_cancel_no").onclick = () => {
    overlay.remove();
  };

  overlay.onclick = (e) => {
    if (e.target === overlay) overlay.remove();
  };
}

function showToast(message, type) {
  const container =
    document.querySelector(".total_cards") ||
    document.getElementById("cart_list");
  if (!container) return;

  const existing = document.querySelector(".toast_msg");
  if (existing) existing.remove();

  const toast = document.createElement("div");
  toast.className = "toast_msg toast_" + type;
  toast.textContent = message;

  toast.style.cssText = `
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    color: #fff;
    padding: 12px 30px;
    border-radius: 16px;
    font-family: Cairo, sans-serif;
    font-size: 16px;
    font-weight: 700;
    text-align: center;
    z-index: 100;
    white-space: nowrap;
    animation: fadeInOutToast 2.5s ease-in-out forwards;
  `;

  if (type === "success") {
    toast.style.backgroundColor = "#1d5c2b";
    toast.style.border = "2px solid #238038";
    toast.style.boxShadow = "0 0 40px rgba(35, 128, 56, 0.6)";
    toast.style.textShadow = "0 0 10px rgba(0,0,0,0.5)";
  } else {
    toast.style.backgroundColor = "#b00b16";
    toast.style.border = "2px solid #e40411";
    toast.style.boxShadow = "0 0 40px rgba(228, 4, 17, 0.6)";
    toast.style.textShadow = "0 0 10px rgba(0,0,0,0.5)";
  }

  if (!document.getElementById("toast_keyframes")) {
    const style = document.createElement("style");
    style.id = "toast_keyframes";
    style.innerHTML =
      "@keyframes fadeInOutToast { 0% { opacity: 0; transform: translate(-50%, -30%); } 15% { opacity: 1; transform: translate(-50%, -50%); } 85% { opacity: 1; transform: translate(-50%, -50%); } 100% { opacity: 0; transform: translate(-50%, -70%); } }";
    document.head.appendChild(style);
  }

  container.style.position = "relative";
  container.appendChild(toast);

  setTimeout(() => {
    if (toast.parentElement) toast.remove();
  }, 2500);
}

// ===================================================
//  Order Type - الزراير 3 وال badge
// ===================================================
const ORDER_TYPES = [
  { key: "delivery", label: "دليفري" },
  { key: "takeaway", label: "تيك اواي" },
  { key: "dine_in", label: "صالة" },
];

function renderOrderTypeButtons() {
  const container = document.getElementById("order_type_btns");
  if (!container) return;
  container.innerHTML = "";

  ORDER_TYPES.forEach((t) => {
    const btn = document.createElement("button");
    const isActive = orderType === t.key;
    btn.className = "order_type_btn" + (isActive ? " active" : "");
    btn.textContent = t.label;
    btn.onclick = () => selectOrderType(t.key);
    container.appendChild(btn);
  });
}

function renderOrderTypeBadge() {
  const badge = document.getElementById("order_type_badge");
  if (!badge) return;

  if (!orderType) {
    badge.style.display = "none";
    badge.innerHTML = "";
    return;
  }

  badge.style.display = "flex";

  if (
    orderType === "delivery" &&
    selectedDelivery &&
    hasFeeValue(selectedDeliveryFee)
  ) {
    badge.innerHTML = `
      <span class="badge_icon"></span>
      <span class="badge_name" style="cursor:pointer" onclick="renderDeliveryCustomerForm()">${selectedDelivery.name}</span>
      <span class="badge_fee">رسوم توصيل: ${formatFeeValue(selectedDeliveryFee)}</span>
      <button class="badge_clear" onclick="clearOrderType()">✕</button>
    `;
  } else if (orderType === "takeaway") {
    badge.innerHTML = `
      <span class="badge_icon"></span>
      <span class="badge_name" style="cursor:pointer" onclick="renderDeliveryCustomerForm()">تيك اواي</span>
      <button class="badge_clear" onclick="clearOrderType()">✕</button>
    `;
  } else if (orderType === "dine_in") {
    badge.innerHTML = `
      <span class="badge_icon"></span>
      <span class="badge_name" style="cursor:pointer" onclick="renderDeliveryCustomerForm()">صالة</span>
      ${hasFeeValue(selectedDineInFee) ? `<span class="badge_fee">رسوم خدمة: ${formatFeeValue(selectedDineInFee)}</span>` : ""}
      <button class="badge_clear" onclick="clearOrderType()">✕</button>
    `;
  } else if (orderType === "delivery") {
    badge.innerHTML = `
      <span class="badge_icon"></span>
      <span class="badge_name" style="color:var(--color-subtext);font-size:12px;cursor:pointer" onclick="renderDeliveryCustomerForm()">لم يتم اختيار الدليفري بعد (اضغط للإكمال)</span>
      <button class="badge_clear" onclick="clearOrderType()">✕</button>
    `;
  }
}

function clearOrderType() {
  selectedDelivery = null;
  selectedDeliveryFee = null;
  selectedDineInFee = null;
  orderType = null;
  resetDeliveryCustomerInfo();
  const dcFormClear = document.getElementById("delivery_customer_form");
  if (dcFormClear) {
    dcFormClear.style.display = "none";
    dcFormClear.innerHTML = "";
  }
  renderOrderTypeBadge();
  renderOrderTypeButtons();
  renderCart();
}

function selectOrderType(type) {
  if (type === "delivery") {
    showDeliveryModal();
  } else if (type === "dine_in") {
    showDineInFeeSelector();
  } else {
    orderType = type;
    selectedDelivery = null;
    selectedDeliveryFee = null;
    selectedDineInFee = null;
    renderOrderTypeBadge();
    renderOrderTypeButtons();
    renderCart(); // سيستدعي updatePricingPreview داخلياً
    renderDeliveryCustomerForm();
  }
}

// ===================================================
//  Pricing Preview API
// ===================================================
let _pricingTimeout = null;

async function updatePricingPreview() {
  if (cart.length === 0) return;

  // Debounce لمنع كثرة الطلبات أثناء تعديل الكميات
  if (_pricingTimeout) clearTimeout(_pricingTimeout);

  _pricingTimeout = setTimeout(async () => {
    try {
      const items = cart.map((c) => {
        let prodId = c.item.id;
        if (typeof prodId === "string" && prodId.includes("_")) {
          prodId = parseInt(prodId.split("_")[0], 10);
        } else {
          prodId = parseInt(prodId, 10);
        }
        return {
          product_id: prodId,
          quantity: c.qty,
          unit_price: c.item.price,
        };
      });

      let mappedOrderType = "hall";
      if (orderType === "takeaway") mappedOrderType = "takeaway";
      else if (orderType === "delivery") mappedOrderType = "delivery";

      const currentFee =
        (orderType === "delivery" ? selectedDeliveryFee : selectedDineInFee) ||
        0;

      const discountType = document.getElementById("discount_type")?.value || null;
      const discountValue = parseFloat(document.getElementById("discount_value")?.value) || null;

      const payload = {
        items: items,
        order_type: mappedOrderType,
        source: "cashier",
        delivery_fee: currentFee,
        offer_code: null,
        customer_phone:
          orderType === "delivery" ? deliveryCustomerInfo.phone : null,
        cashier_id: parseInt(localStorage.getItem("user_id"), 10) || null,
        manual_discount_type: discountType,
        manual_discount_value: discountValue,
      };

      const res = await apiFetch("/pricing/preview", {
        method: "POST",
        body: JSON.stringify(payload),
        hideLoader: true, // لا نريد إيقاف الواجهة في المعاينة
      });

      if (res.ok) {
        const data = await res.json();
        const totalEl = document.getElementById("total_price");
        if (totalEl && data.total_amount) {
          totalEl.textContent =
            parseFloat(data.total_amount).toFixed(2) + " ج.م";
          // يمكننا مستقبلاً عرض الخصم والـ subtotal هنا
        }
      }
    } catch (err) {
      console.warn("Pricing preview failed:", err);
    }
  }, 400);
}

// ===================================================
//  Dine-in Fee Selector
// ===================================================
function showDineInFeeSelector() {
  const container = document.getElementById("delivery_modal_container");
  if (!container) return;

  const fees = [
    5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95,
    100,
  ];

  container.style.display = "flex";
  container.innerHTML = `
    <div class="delivery_modal">
      <div class="delivery_modal_header">
        <h2>رسوم الصالة</h2>
        <button class="delivery_modal_close" onclick="closeDeliveryModal()">✕</button>
      </div>
      <div class="delivery_modal_body">
        <p style="color:var(--color-subtext);font-size:13px;text-align:center;margin-bottom:16px">اختر قيمة رسوم الخدمة</p>
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;">
          ${fees
            .map(
              (fee) => `
            <button class="delivery_fee_btn" onclick="selectDineInFee(${fee})">${fee} ج.م</button>
          `,
            )
            .join("")}
          <button class="delivery_fee_btn" onclick="selectDineInFee(0)" style="background:rgba(255,255,255,0.05);color:var(--color-subtext)">بدون</button>
        </div>
      </div>
    </div>
  `;
}

function selectDineInFee(fee) {
  selectedDineInFee = Number(fee);
  selectedDeliveryFee = null;
  selectedDelivery = null;
  orderType = "dine_in";
  closeDeliveryModal();
  renderOrderTypeBadge();
  renderOrderTypeButtons();
  renderCart();
  renderDeliveryCustomerForm();
}

// ===================================================
//  Delivery Modal - داخل الكارت مش على الصفحة
// ===================================================
async function showDeliveryModal() {
  const container = document.getElementById("delivery_modal_container");
  if (!container) return;

  container.style.display = "flex";
  container.innerHTML = `
    <div class="delivery_modal">
      <div class="delivery_modal_header">
        <h2>اختر الدليفري</h2>
        <button class="delivery_modal_close" onclick="closeDeliveryModal()">✕</button>
      </div>
      <div class="delivery_modal_body" id="delivery_names_list">
        <p style="color:var(--color-subtext);text-align:center;font-size:13px">جاري التحميل...</p>
      </div>
    </div>
  `;

  // جلب الدليفري من API
  try {
    const res = await apiFetch("/user/users/delivery", { suppress401: true });
    if (!res.ok) throw new Error(`HTTP error: ${res.status}`);
    const users = await res.json();
    const riders = Array.isArray(users)
      ? users.filter((u) => u.role === "delivery" && u.is_active)
      : [];
    _deliveryRidersCache = riders;
    renderDeliveryNames(riders);
  } catch (err) {
    if (err.message.includes("401")) {
      const list = document.getElementById("delivery_names_list");
      if (list)
        list.innerHTML = `<p style="color:#e40411;text-align:center;font-size:12px;padding:10px">عفواً، لا يملك حسابك صلاحية الوصول لقائمة المناديب</p>`;
    } else {
      console.error("خطأ في جلب الدليفري:", err);
      renderDeliveryNames([]);
    }
  }
}

function renderDeliveryNames(riders) {
  const list = document.getElementById("delivery_names_list");
  if (!list) return;

  if (!riders || riders.length === 0) {
    list.innerHTML = `<p style="color:var(--color-subtext);text-align:center;font-size:13px">لا يوجد دليفري متاح</p>`;
    return;
  }

  list.innerHTML = "";
  riders.forEach((r) => {
    const btn = document.createElement("button");
    btn.className = "delivery_name_btn";
    btn.textContent = r.full_name || r.username;
    btn.onclick = () =>
      showDeliveryFeeSelector({ id: r.id, name: r.full_name || r.username });
    list.appendChild(btn);
  });
}

function showDeliveryFeeSelector(rider) {
  const list = document.getElementById("delivery_names_list");
  if (!list) return;

  const fees = [
    0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95,
    100,
  ];

  list.innerHTML = `
    <button onclick="backToDeliveryNames()" style="
      background:transparent;border:none;color:var(--color-subtext);
      font-family:Cairo,sans-serif;font-size:13px;cursor:pointer;
      display:flex;align-items:center;gap:4px;margin-bottom:8px;padding:0;
    ">← رجوع</button>
    <p style="color:var(--color-primary);font-size:14px;font-weight:700;text-align:center;margin-bottom:12px">${rider.name}</p>
    <p style="color:var(--color-subtext);font-size:12px;text-align:center;margin-bottom:10px">اختر رسوم التوصيل</p>
  `;

  const grid = document.createElement("div");
  grid.style.cssText =
    "display:grid;grid-template-columns:repeat(4,1fr);gap:8px;";

  fees.forEach((fee) => {
    const btn = document.createElement("button");
    btn.className = "delivery_fee_btn";
    btn.textContent = `${fee} ج.م`;
    btn.onclick = () => {
      selectedDelivery = { id: rider.id, name: rider.name };
      selectedDeliveryFee = Number(fee);
      orderType = "delivery";
      resetDeliveryCustomerInfo();
      closeDeliveryModal();
      renderOrderTypeBadge();
      renderOrderTypeButtons();
      renderCart();
      renderDeliveryCustomerForm();
    };
    grid.appendChild(btn);
  });

  list.appendChild(grid);
}

let _deliveryRidersCache = null;

async function backToDeliveryNames() {
  const list = document.getElementById("delivery_names_list");
  if (!list) return;
  list.innerHTML = `<p style="color:var(--color-subtext);text-align:center;font-size:13px">جاري التحميل...</p>`;

  if (_deliveryRidersCache) {
    renderDeliveryNames(_deliveryRidersCache);
    return;
  }

  try {
    const res = await apiFetch("/user/users", { suppress401: true });
    if (!res.ok) throw new Error(`HTTP error: ${res.status}`);
    const users = await res.json();
    const riders = Array.isArray(users)
      ? users.filter((u) => u.role === "delivery" && u.is_active)
      : [];
    _deliveryRidersCache = riders;
    renderDeliveryNames(riders);
  } catch (err) {
    if (err.message.includes("401")) {
      list.innerHTML = `<p style="color:#e40411;text-align:center;font-size:12px;padding:10px">عفواً، لا يملك حسابك صلاحية الوصول لقائمة المناديب</p>`;
    } else {
      renderDeliveryNames([]);
    }
  }
}

function closeDeliveryModal() {
  const container = document.getElementById("delivery_modal_container");
  if (container) {
    container.style.display = "none";
    container.innerHTML = "";
  }
}

// ===================================================
//  Delivery Customer Form
// ===================================================
function resetDeliveryCustomerInfo() {
  deliveryCustomerInfo = {
    phone: "",
    name: "",
    customerId: null,
    addresses: [],
    selectedAddressId: null,
    newAddress: "",
    manualAddressMode: false, // لحفظ هل بنكتب عنوان جديد لعميل موجود؟
  };
}

function getAddressText(addr) {
  return (
    addr.address ||
    addr.address_line ||
    addr.full_address ||
    addr.street ||
    "عنوان محفوظ"
  );
}

function renderAddressFieldHTML() {
  const label = `<span class="dcf_label">📍 العنوان</span>`;

  // لو العميل موجود (عنده ID)
  if (deliveryCustomerInfo.customerId) {
    const addresses = deliveryCustomerInfo.addresses || [];

    // لو وضع الكتابة اليدوية مفعل (اختير "إضافة جديد")
    if (deliveryCustomerInfo.manualAddressMode) {
      return `
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px">
          ${label}
          <button class="dcf_link_btn" onclick="deliveryCustomerInfo.manualAddressMode=false; renderDeliveryCustomerForm()">الرجوع للعناوين المحفوظة</button>
        </div>
        <input type="text" id="dcf_address_input" class="dcf_input"
          placeholder="أدخل العنوان الجديد"
          value="${deliveryCustomerInfo.newAddress}"
          oninput="deliveryCustomerInfo.newAddress = this.value" />
      `;
    }

    // عرض القائمة المنسدلة
    const options = addresses
      .map((a) => {
        const text = getAddressText(a);
        const sel =
          deliveryCustomerInfo.selectedAddressId === a.id ? "selected" : "";
        return `<option value="${a.id}" ${sel}>${text}</option>`;
      })
      .join("");

    return `
      ${label}
      <select id="dcf_address_select" class="dcf_select"
        onchange="handleAddressSelect(this.value)">
        ${addresses.length === 0 ? '<option value="">-- لا توجد عناوين محفوظة --</option>' : '<option value="">-- اختر العنوان --</option>'}
        ${options}
        <option value="NEW_ADDRESS" ${deliveryCustomerInfo.manualAddressMode ? "selected" : ""}>➕ إضافة عنوان جديد...</option>
      </select>
    `;
  } else {
    // عميل جديد تماماً → text input فقط
    return `
      ${label}
      <input type="text" id="dcf_address_input" class="dcf_input"
        placeholder="أدخل العنوان"
        value="${deliveryCustomerInfo.newAddress}"
        oninput="deliveryCustomerInfo.newAddress = this.value" />
    `;
  }
}

function handleAddressSelect(val) {
  if (val === "NEW_ADDRESS") {
    deliveryCustomerInfo.manualAddressMode = true;
    deliveryCustomerInfo.selectedAddressId = null;
    deliveryCustomerInfo.newAddress = "";
  } else {
    deliveryCustomerInfo.manualAddressMode = false;
    deliveryCustomerInfo.selectedAddressId = parseInt(val) || null;
    deliveryCustomerInfo.newAddress = "";
  }
  renderDeliveryCustomerForm();
}

function renderDeliveryCustomerForm() {
  const container = document.getElementById("delivery_customer_form");
  if (!container) return;

  if (!orderType) {
    container.style.display = "none";
    container.innerHTML = "";
    return;
  }

  container.style.display = "block";
  container.innerHTML = `
    <div class="delivery_customer_card">
      <div class="dcf_title">
        <div style="display:flex; align-items:center; gap:6px;">
          <svg width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
          </svg>
          ${orderType === "delivery" ? "بيانات عميل الديليفري" : "بيانات العميل (اختياري)"}
        </div>
        <button class="dcf_close_btn" onclick="hideDeliveryCustomerForm()" title="إغلاق البيانات مؤقتاً">✕</button>
      </div>

      <div class="dcf_field">
        <span class="dcf_label">📞 رقم التليفون</span>
        <div class="dcf_phone_row">
          <input type="tel" id="dcf_phone" class="dcf_input"
            placeholder="01xxxxxxxxx" maxlength="11"
            value="${deliveryCustomerInfo.phone}"
            oninput="this.value = normalizePhoneDigits(this.value); handlePhoneInput(this.value)" />
          <span class="dcf_status" id="dcf_phone_status"></span>
        </div>
      </div>

      <div class="dcf_field">
        <span class="dcf_label">👤 اسم العميل</span>
        <input type="text" id="dcf_name" class="dcf_input"
          placeholder="اسم العميل"
          value="${deliveryCustomerInfo.name}"
          oninput="deliveryCustomerInfo.name = this.value" />
      </div>

      <div class="dcf_field" id="dcf_address_field">
        ${renderAddressFieldHTML()}
      </div>
    </div>
  `;

  // إذا كان في بيانات محفوظة، اعمل restore للحالة
  if (deliveryCustomerInfo.customerId) {
    const nameInput = document.getElementById("dcf_name");
    if (nameInput) {
      nameInput.readOnly = true;
      nameInput.style.opacity = "0.75";
      nameInput.classList.add("filled");
    }
  }
}

function hideDeliveryCustomerForm() {
  const container = document.getElementById("delivery_customer_form");
  if (container) container.style.display = "none";
}

function handlePhoneInput(phone) {
  deliveryCustomerInfo.phone = normalizePhoneDigits(phone);
  deliveryCustomerInfo.name = "";
  deliveryCustomerInfo.customerId = null;
  deliveryCustomerInfo.addresses = [];
  deliveryCustomerInfo.selectedAddressId = null;
  deliveryCustomerInfo.newAddress = "";
  deliveryCustomerInfo.manualAddressMode = false;

  const nameInput = document.getElementById("dcf_name");
  if (nameInput) {
    nameInput.value = "";
    nameInput.readOnly = false;
    nameInput.style.opacity = "1";
    nameInput.classList.remove("filled");
  }

  const addrField = document.getElementById("dcf_address_field");
  if (addrField) addrField.innerHTML = renderAddressFieldHTML();

  clearTimeout(_phoneSearchTimeout);
  const status = document.getElementById("dcf_phone_status");

  const digits = normalizePhoneDigits(phone);
  if (digits.length >= 11) {
    if (status)
      status.innerHTML =
        '<span style="color:var(--color-subtext)">جاري البحث...</span>';
    _phoneSearchTimeout = setTimeout(() => lookupCustomerByPhone(phone), 700);
  } else {
    if (status) status.innerHTML = "";
  }
}

async function lookupCustomerByPhone(phone) {
  const status = document.getElementById("dcf_phone_status");

  const applyFound = (found) => {
    deliveryCustomerInfo.customerId = found.id;
    deliveryCustomerInfo.name = found.name || "";
    deliveryCustomerInfo.addresses = Array.isArray(found.addresses)
      ? found.addresses
      : [];

    if (deliveryCustomerInfo.addresses.length === 1) {
      deliveryCustomerInfo.selectedAddressId =
        deliveryCustomerInfo.addresses[0].id;
    } else {
      deliveryCustomerInfo.selectedAddressId = null;
    }

    if (deliveryCustomerInfo.addresses.length === 1) {
      deliveryCustomerInfo.selectedAddressId =
        deliveryCustomerInfo.addresses[0].id;
    } else {
      deliveryCustomerInfo.selectedAddressId = null;
    }

    const nameInput = document.getElementById("dcf_name");
    if (nameInput) {
      nameInput.value = deliveryCustomerInfo.name;
      nameInput.readOnly = true;
      nameInput.style.opacity = "0.75";
      nameInput.classList.add("filled");
    }
    if (status) status.innerHTML = '<span style="color:#3d9e6b">✓ موجود</span>';
    const addrField = document.getElementById("dcf_address_field");
    if (addrField) addrField.innerHTML = renderAddressFieldHTML();
  };

  const applyNew = () => {
    deliveryCustomerInfo.customerId = null;
    deliveryCustomerInfo.addresses = [];
    deliveryCustomerInfo.selectedAddressId = null;

    const nameInput = document.getElementById("dcf_name");
    if (nameInput) {
      nameInput.value = "";
      nameInput.readOnly = false;
      nameInput.style.opacity = "1";
      nameInput.classList.remove("filled");
    }
    if (status)
      status.innerHTML =
        '<span style="color:var(--color-primary)">✦ جديد</span>';
    const addrField = document.getElementById("dcf_address_field");
    if (addrField) addrField.innerHTML = renderAddressFieldHTML();
  };

  const token = localStorage.getItem("token");
  const headers = token ? { Authorization: "Bearer " + token } : {};

  // ── المحاولة الأولى: by-phone (أسرع وأدق) ──
  try {
    const r1 = await apiFetch(
      `/customers/by-phone/${encodeURIComponent(phone)}`,
    );
    if (r1.ok) {
      const data = await r1.json();
      applyFound(data);
      return;
    }
  } catch (_) {
    /* تجاهل وانتقل للخطوة التالية */
  }

  // ── المحاولة الثانية: قايمة كل العملاء + فلتر ──
  try {
    const r2 = await apiFetch("/customers/");
    if (r2.ok) {
      const list = await r2.json();
      const found = Array.isArray(list)
        ? list.find((c) => c.phone_number === phone)
        : null;
      if (found) {
        applyFound(found);
        return;
      }
    }
  } catch (_) {
    /* تجاهل */
  }

  // ── كلاهما فشل → عميل جديد ──
  applyNew();
}

// ===================================================
//  Loaders
// ===================================================
function showGlobalLoader(show) {
  let loader = document.getElementById("global_page_loader");
  if (!show) {
    if (loader) loader.remove();
    return;
  }

  if (!loader) {
    loader = document.createElement("div");
    loader.id = "global_page_loader";
    loader.style.cssText = `
      position: fixed; inset: 0; background: rgba(15,12,6,0.95);
      display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 100000;
    `;
    loader.innerHTML = `
      <div style="position: relative; display: flex; align-items: center; justify-content: center;">
        <div style="width: 100px; height: 100px; border: 4px solid var(--color-primary-border); border-top-color: var(--color-primary); border-radius: 50%; animation: spinLoader 1s linear infinite;"></div>
        <img src="../assets/توب شيف 1@2x.png" style="position: absolute; width: 60px; max-height: 60px; object-fit: contain;" alt="loader">
      </div>
      <p style="color: var(--color-primary); font-family: Cairo, sans-serif; font-size: 16px; font-weight: 700; margin-top: 16px;">جاري التحميل...</p>
    `;

    if (!document.getElementById("loader_spin_style")) {
      const style = document.createElement("style");
      style.id = "loader_spin_style";
      style.innerHTML =
        "@keyframes spinLoader { to { transform: rotate(360deg); } }";
      document.head.appendChild(style);
    }

    document.body.appendChild(loader);
  }
}

// ===================================================
//  Start
// ===================================================
init();
renderOrderTypeButtons();
renderOrderTypeBadge();

// ===================================================
//  Delivery Riders Tab Logic
// ===================================================
function renderRidersTab() {
  const body = document.getElementById("riders_table_body");
  if (!body) return;

  if (
    allOrdersList.length === 0 &&
    onlineOrdersList.length === 0 &&
    !ordersSnapshotLoaded
  ) {
    body.innerHTML = `<tr><td colspan="3" style="padding:40px; text-align:center; color:var(--color-primary);">جاري تحميل البيانات...</td></tr>`;
    return;
  }

  // حساب بداية يوم العمل (الساعة 5 صباحاً)
  const now = new Date();
  const businessDayStart = new Date(now);
  businessDayStart.setHours(5, 0, 0, 0);
  if (now.getHours() < 5)
    businessDayStart.setDate(businessDayStart.getDate() - 1);

  // تجميع كل الطلبات
  const combinedOrders = [...allOrdersList, ...onlineOrdersList];

  // فلترة طلبات الدليفري ضمن يوم العمل الحالي (من الساعة 5 صباحاً)
  const deliveryOrders = combinedOrders.filter((o) => {
    if (!o.delivery_person_id || o.order_status === "cancelled") return false;
    const t = o.created_at ? new Date(o.created_at) : null;
    return t && t >= businessDayStart;
  });

  // تجميع البيانات لكل مندوب
  const riderStats = {};

  deliveryOrders.forEach((order) => {
    const rid = order.delivery_person_id;
    const rname = order.delivery_person_name || "مندوب غير معروف";

    if (!riderStats[rid]) {
      riderStats[rid] = {
        id: rid,
        name: rname,
        count: 0,
        total: 0,
        orderNumbers: [],
      };
    }

    riderStats[rid].count++;
    riderStats[rid].total += parseFloat(order.total_amount || 0);
    riderStats[rid].orderNumbers.push(order.order_number || order.id);
  });

  const ridersArr = Object.values(riderStats);

  if (ridersArr.length === 0) {
    body.innerHTML = `<tr><td colspan="3" style="padding:40px; text-align:center; color:var(--color-subtext);">لا توجد بيانات دليفري متاحة حالياً</td></tr>`;
    return;
  }

  // ترتيب حسب عدد الطلبات تنازلياً
  ridersArr.sort((a, b) => b.count - a.count);

  body.innerHTML = ridersArr
    .map(
      (r) => `
    <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); transition: background 0.2s;" onmouseover="this.style.background='rgba(255,255,255,0.02)'" onmouseout="this.style.background='transparent'">
      <td style="padding: 15px; font-weight: 700; color: #fff;">${r.name}</td>
      <td style="padding: 15px;">
        <button onclick='showRiderOrdersPopup("${r.name.replace(/'/g, "\\'")}", ${JSON.stringify(r.orderNumbers)})' 
          style="background: rgba(61, 158, 107, 0.15); color: #3d9e6b; border: 1px solid rgba(61, 158, 107, 0.3); padding: 4px 12px; border-radius: 6px; cursor: pointer; font-family: Cairo, sans-serif; font-weight: 700;">
          ${r.count} طلبات
        </button>
      </td>
      <td style="padding: 15px; font-weight: 900; color: var(--color-primary);">${r.total.toFixed(2)} ج.م</td>
    </tr>
  `,
    )
    .join("");
}

function showRiderOrdersPopup(riderName, orderNumbers) {
  const old = document.getElementById("rider_orders_popup");
  if (old) old.remove();

  const overlay = document.createElement("div");
  overlay.id = "rider_orders_popup";
  overlay.style.cssText = `
    position:fixed; inset:0; background:rgba(0,0,0,0.8);
    display:flex; align-items:center; justify-content:center; z-index:20000; direction:rtl;
  `;

  overlay.innerHTML = `
    <div style="background: var(--color-bg); border: 1px solid var(--color-primary); border-radius: 16px; padding: 24px; width: 400px; max-width: 90vw; max-height: 80vh; display: flex; flex-direction: column; gap: 16px; box-shadow: 0 20px 60px rgba(0,0,0,0.5);">
      <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(201, 168, 76, 0.2); padding-bottom: 12px;">
        <h3 style="margin: 0; color: var(--color-primary); font-size: 18px;">طلبات المندوب: ${riderName}</h3>
        <button onclick="document.getElementById('rider_orders_popup').remove()" style="background: none; border: none; color: var(--color-subtext); font-size: 24px; cursor: pointer;">&times;</button>
      </div>
      
      <div style="flex: 1; overflow-y: auto; padding-left: 8px;">
        <p style="color: var(--color-subtext); font-size: 13px; margin-bottom: 12px;">قائمة بأرقام الطلبات التي قام بتوصيلها:</p>
        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px;">
          ${orderNumbers
            .map(
              (num) => `
            <div style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 8px; text-align: center; color: #fff; font-weight: 700;">#${num}</div>
          `,
            )
            .join("")}
        </div>
      </div>
      
      <button onclick="document.getElementById('rider_orders_popup').remove()" style="background: var(--color-primary); color: #000; border: none; border-radius: 8px; padding: 10px; font-family: Cairo, sans-serif; font-weight: 900; cursor: pointer;">إغلاق</button>
    </div>
  `;

  document.body.appendChild(overlay);
  overlay.onclick = (e) => {
    if (e.target === overlay) overlay.remove();
  };
}

// ===================================================
//  Tabs Navigation (Local vs Online)
// ===================================================
function switchMainTab(tab) {
  const tabLocal = document.getElementById("tab_local");
  const tabOnline = document.getElementById("tab_online");
  const tabAllOrders = document.getElementById("tab_all_orders");
  const tabRiders = document.getElementById("tab_riders");
  const layoutLocal = document.getElementById("local_orders_layout");
  const layoutOnline = document.getElementById("online_orders_layout");
  const layoutAllOrders = document.getElementById("all_orders_layout");
  const layoutRiders = document.getElementById("riders_layout");

  if (!tabLocal || !tabOnline) return;

  // Reset tabs
  tabLocal.classList.remove("active");
  tabOnline.classList.remove("active");
  if (tabAllOrders) tabAllOrders.classList.remove("active");
  if (tabRiders) tabRiders.classList.remove("active");

  // Reset layouts
  if (layoutLocal) layoutLocal.style.display = "none";
  if (layoutOnline) layoutOnline.style.display = "none";
  if (layoutAllOrders) layoutAllOrders.style.display = "none";
  if (layoutRiders) layoutRiders.style.display = "none";

  if (tab === "local") {
    tabLocal.classList.add("active");
    if (layoutLocal) layoutLocal.style.display = ""; // Returns to CSS defined layout (grid)
  } else if (tab === "online") {
    tabOnline.classList.add("active");
    if (layoutOnline) layoutOnline.style.display = "block";
    updateOnlineStats();
    renderOnlineOrders();
  } else if (tab === "all_orders") {
    if (tabAllOrders) tabAllOrders.classList.add("active");
    if (layoutAllOrders) layoutAllOrders.style.display = "block";
    renderAllOrders();
  } else if (tab === "riders") {
    const tabRiders = document.getElementById("tab_riders");
    const layoutRiders = document.getElementById("riders_layout");
    if (tabRiders) tabRiders.classList.add("active");
    if (layoutRiders) layoutRiders.style.display = "block";
    renderRidersTab();
  }
}

// ===================================================
//  Online Orders (Website Orders)
// ===================================================
function renderOnlineOrdersState() {
  updateOnlineStats();
  renderOnlineOrders();
}

/**
 * Manually fetch all orders from the API (used by Refresh buttons)
 */
async function fetchOnlineOrdersServer(page = 1, silent = false) {
  onlineOrdersCurrentPage = page;
  if (!silent) showGlobalLoader(true);
  try {
    let url = `/orders/?page=${page}&page_size=${ordersPageSize}&source=online`;
    if (onlineOrdersFilter !== "all") {
      url += `&status=${onlineOrdersFilter}`;
    }
    const res = await apiFetch(url);
    if (!res.ok) throw new Error("Failed to fetch online orders");
    const data = await res.json();
    onlineOrdersList = data.orders || [];
    onlineOrdersTotal = data.total || 0;

    if (!silent) {
      const container =
        document.getElementById("online_orders_grid")?.parentElement;
      if (container) container.scrollTop = 0;
    }

    renderOnlineOrders();
  } catch (err) {
    console.error(err);
    if (!silent) showToast("فشل تحميل طلبات الأونلاين", "error");
  } finally {
    if (!silent) showGlobalLoader(false);
  }
}

async function fetchAllOrdersServer(page = 1, silent = false) {
  allOrdersCurrentPage = page;
  if (!silent) showGlobalLoader(true);
  try {
    let url = `/orders/?page=${page}&page_size=${ordersPageSize}&source=cashier`;
    if (allOrdersFilter !== "all") {
      url += `&order_type=${allOrdersFilter}`;
    }
    const res = await apiFetch(url);
    if (!res.ok) throw new Error("Failed to fetch all orders");
    const data = await res.json();
    allOrdersList = data.orders || [];
    allOrdersTotal = data.total || 0;

    if (!silent) {
      const container =
        document.getElementById("all_orders_grid")?.parentElement;
      if (container) container.scrollTop = 0;
    }

    renderAllOrders();
  } catch (err) {
    console.error(err);
    if (!silent) showToast("فشل تحميل طلبات الكاشير", "error");
  } finally {
    if (!silent) showGlobalLoader(false);
  }
}

async function fetchAllOrders(skipSync = false) {
  showGlobalLoader(true);
  try {
    if (IS_DESKTOP_RUNTIME && !skipSync) {
      try {
        await apiFetch("/desktop-updates/trigger-pull", {
          method: "POST",
          suppress401: true,
        });
        await new Promise((resolve) => setTimeout(resolve, 800));
      } catch (e) {
        console.warn("Could not trigger background sync:", e);
      }
    }

    // Fetch first page of both and the badge count
    await Promise.all([
      fetchOnlineOrdersServer(1),
      fetchAllOrdersServer(1),
      refreshNewOrdersBadge(),
    ]);

    ordersSnapshotLoaded = true;
    updateOnlineStats();
    renderRidersTab();

    showToast("تم تحديث البيانات بنجاح", "success");
  } catch (err) {
    console.error("Error refreshing orders:", err);
    showToast("فشل تحديث البيانات", "error");
  } finally {
    showGlobalLoader(false);
  }
}

/**
 * Alias for fetchAllOrders to satisfy the online orders refresh button
 */
async function fetchOnlineOrders() {
  await fetchAllOrders();
}

function updateOnlineStats() {
  const newCount = onlineOrdersList.filter(
    (o) => o.order_status === "new",
  ).length;
  //جاهز = confirmed, مكتمل = completed. For stats, let's show confirmed as ready in progress?
  // User asked: "Ready" (جاهزة) stat box. Let's use confirmed + completed for now or just confirmed.
  const readyCount = onlineOrdersList.filter(
    (o) => o.order_status === "confirmed" || o.order_status === "completed",
  ).length;
  const cancelledCount = onlineOrdersList.filter(
    (o) => o.order_status === "cancelled",
  ).length;

  const statBoxes = document.querySelectorAll(".stat_box h2");
  if (statBoxes.length >= 3) {
    statBoxes[0].textContent = newCount;
    statBoxes[1].textContent = cancelledCount;
    statBoxes[2].textContent = readyCount;
  }
}

async function refreshNewOrdersBadge() {
  try {
    // Fetch count of new online orders specifically
    const res = await apiFetch(
      "/orders/?status=new&page=1&page_size=1&source=online",
    );
    if (res.ok) {
      const data = await res.json();
      totalNewOrdersGlobalCount = data.total || 0;
      updateOnlineTabBadge(totalNewOrdersGlobalCount);
    }
  } catch (e) {
    console.error("Error refreshing badge count:", e);
  }
}

// Sound reminder loop: if there are new orders, play sound every 2 minutes
setInterval(
  () => {
    if (totalNewOrdersGlobalCount > 0 && isNotificationSoundEnabled) {
      console.log(
        "Sound reminder: Still have",
        totalNewOrdersGlobalCount,
        "new orders.",
      );
      playNotificationSound();
    }
  },
  2 * 60 * 1000,
);

function setOnlineOrdersFilter(filter, btn) {
  onlineOrdersFilter = filter;
  const btns = document.querySelectorAll("#online_orders_layout .filter_btn");
  btns.forEach((b) => b.classList.remove("active"));
  if (btn) btn.classList.add("active");
  onlineOrdersCurrentPage = 1;
  fetchOnlineOrdersServer(1);
}

function handleOnlineSearch(term) {
  onlineOrdersSearchTerm = term.trim().toLowerCase();
  onlineOrdersCurrentPage = 1;
  renderOnlineOrders();
}

function renderOnlineOrders() {
  const grid = document.getElementById("online_orders_grid");
  if (!grid) return;

  if (!ordersSnapshotLoaded) {
    grid.innerHTML = `<p style="color:var(--color-primary);text-align:center;grid-column:1/-1;padding:40px;">جاري الاتصال بالتحديثات المباشرة...</p>`;
    return;
  }

  const term = (onlineOrdersSearchTerm || "").toLowerCase();
  const filteredList = onlineOrdersList.filter(o => {
    if (!term) return true;
    const oNum = String(o.order_number || o.id || "").toLowerCase();
    const phone = String(o.customer_phone || "").toLowerCase();
    const name = String(o.customer_name || "").toLowerCase();
    return oNum.includes(term) || phone.includes(term) || name.includes(term);
  });

  if (filteredList.length === 0) {
    grid.innerHTML = `<p style="color:var(--color-subtext);text-align:center;grid-column:1/-1;padding:40px;">لا توجد طلبات أون لاين</p>`;
    return;
  }

  grid.innerHTML = "";

  const statusMap = {
    new: { label: "جديد", cls: "badge_new" },
    confirmed: { label: "مؤكد", cls: "badge_ready" },
    completed: { label: "مكتمل", cls: "badge_ready" },
    cancelled: { label: "ملغي", cls: "badge_canceled" },
    delivered: { label: "تم التوصيل", cls: "badge_ready" },
  };

  window.createOnlineOrderCardElement = function(order) {
    let statusObj = statusMap[order.order_status] || {
      label: order.order_status,
      cls: "",
    };

    let timeStr = "";
    const orderTime = order.created_at || order.order_date;
    if (orderTime) {
      const d = new Date(orderTime);
      if (!isNaN(d)) {
        if (String(orderTime).length > 10) {
          timeStr = d.toLocaleTimeString("ar-EG", {
            hour: "2-digit",
            minute: "2-digit",
          });
        } else {
          timeStr = d.toLocaleDateString("ar-EG");
        }
      } else {
        timeStr = orderTime;
      }
    }

    let updatedTimeStr = "";
    if (order.updated_at && order.created_at && Math.abs(new Date(order.updated_at).getTime() - new Date(order.created_at).getTime()) > 2000) {
        let du = new Date(order.updated_at);
        if (!isNaN(du)) {
            updatedTimeStr = `<span style="font-size:10px; color:#f39c12; margin-top:2px;">عدل في: ${du.toLocaleTimeString("ar-EG", {hour: "2-digit", minute: "2-digit"})} - ${du.toLocaleDateString("ar-EG")}</span>`;
        }
    }

    const card = document.createElement("div");
    card.className = "online_order_card";
    card.id = `online_order_card_${order.id}`;
    card.onclick = () => openOrderDetails(order.id, "online");
    card.innerHTML = `
      <div class="card_header">
        <span class="order_status ${statusObj.cls}">${statusObj.label}</span>
        <div style="display:flex; flex-direction:column; align-items:flex-end;">
          <span class="order_id" style="margin-bottom:2px;">طلب #${order.order_number || order.id}</span>
          <span style="font-size:11px; opacity:0.7;">${timeStr}</span>
          ${updatedTimeStr}
        </div>
      </div>
      <div class="card_details">
        <div class="detail_row">
          <span>${order.customer_phone || "بدون رقم"}</span>
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path></svg>
        </div>
        <div class="detail_row">
          <span>${order.customer_name || "عميل أونلاين"}</span>
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
        </div>
        <div class="detail_row">
          <span style="font-size:12px">
            ${
              typeof order.address === "object" && order.address !== null
                ? order.address.address
                : order.customer_address ||
                  order.address ||
                  "لا يوجد عنوان"
            }
          </span>
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><polyline points="9 22 9 12 15 12 15 22"></polyline></svg>
        </div>
        ${
          order.customer_notes
            ? `
        <div class="detail_row">
          <span style="font-size:12px">ملاحظات: ${order.customer_notes}</span>
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle></svg>
        </div>`
            : ""
        }
        ${
          order.order_type === "delivery" &&
          (order.delivery_person_id || order.delivery_person_name)
            ? `
        <div class="detail_row" style="color:var(--color-primary); font-weight:bold;">
          <span>المندوب: ${order.delivery_person_name || "..."}</span>
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--color-primary)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="3" width="15" height="13" rx="2"/><path d="M16 8h4l3 3v5h-7V8z"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/></svg>
        </div>`
            : ""
        }
        </div>
      </div>
      
      <div style="margin-top:auto; padding-top:12px; border-top:1px solid rgba(255,255,255,0.05); display:flex; flex-wrap:wrap; gap:8px; justify-content:center;">
        ${
          order.order_status === "new"
            ? `
          <button onclick="event.stopPropagation(); updateOnlineStatus(${order.id}, 'confirmed')" style="background:var(--color-primary); color:#000; border:none; padding:6px 12px; border-radius:6px; font-weight:bold; font-size:12px; cursor:pointer;">مؤكد</button>
        `
            : ""
        }
        ${
          order.order_status === "confirmed"
            ? `
          ${
            order.order_type === "delivery"
              ? `
            <button onclick="event.stopPropagation(); updateOnlineStatus(${order.id}, 'delivered')" style="background:#1d5c2b; color:#fff; border:none; padding:6px 12px; border-radius:6px; font-weight:bold; font-size:12px; cursor:pointer;">تم التوصيل</button>
          `
              : `
            <button onclick="event.stopPropagation(); updateOnlineStatus(${order.id}, 'completed')" style="background:#1d5c2b; color:#fff; border:none; padding:6px 12px; border-radius:6px; font-weight:bold; font-size:12px; cursor:pointer;">تم التجهيز</button>
          `
          }
        `
            : ""
        }
        ${
          order.order_status === "new" || order.order_status === "confirmed"
            ? `
          <button onclick="event.stopPropagation(); updateOnlineStatus(${order.id}, 'cancelled')" style="background:#e40411; color:#fff; border:none; padding:6px 12px; border-radius:6px; font-weight:bold; font-size:12px; cursor:pointer;">إلغاء</button>
          <button onclick="event.stopPropagation(); openEditOrderModal(${order.id}, 'online')" style="background:var(--color-secondary, #2980b9); color:#fff; border:none; padding:6px 12px; border-radius:6px; font-weight:bold; font-size:12px; cursor:pointer;">تعديل</button>
        `
            : ""
        }
        ${
          order.order_status !== "cancelled"
            ? `
          <button onclick="event.stopPropagation(); printOrderFromOnline(${order.id})" style="background:#5c5c5c; color:#fff; border:none; padding:6px 12px; border-radius:6px; font-weight:bold; font-size:12px; cursor:pointer;">طباعة</button>
        `
            : ""
        }
      </div>
    `;
    return card;
  };

  window.updateOrAddOnlineOrderDOM = function(order) {
    const grid = document.getElementById("online_orders_grid");
    if (!grid) return;

    // Check if empty message is present and remove it
    if (grid.innerHTML.includes("لا توجد طلبات أون لاين") || grid.innerHTML.includes("جاري الاتصال")) {
        grid.innerHTML = "";
    }

    const newCard = createOnlineOrderCardElement(order);
    const existingCard = document.getElementById(`online_order_card_${order.id}`);

    if (existingCard) {
      existingCard.replaceWith(newCard);
    } else {
      // Prepend before pagination if exists
      const firstCard = grid.querySelector('.online_order_card');
      if (firstCard) {
        grid.insertBefore(newCard, firstCard);
      } else {
        grid.prepend(newCard);
      }
    }
  };

  filteredList.forEach((order) => {
    grid.appendChild(createOnlineOrderCardElement(order));
  });

  const pagination = renderPagination(
    onlineOrdersTotal,
    onlineOrdersCurrentPage,
    ordersPageSize,
    "changeOnlinePage",
  );
  if (pagination) grid.appendChild(pagination);
}

async function updateOnlineStatus(orderId, newStatus) {
  const order = onlineOrdersList.find((o) => o.id === orderId);
  let msg = "هل أنت متأكد؟";
  if (newStatus === "confirmed") msg = "تأكيد واستلام الطلب؟";
  else if (newStatus === "completed") msg = "هل تم تجهيز الطلب؟";
  else if (newStatus === "delivered") msg = "هل تم توصيل الطلب؟";
  else if (newStatus === "cancelled") msg = "إلغاء هذا الطلب؟";

  const confirmed = await showCustomActionConfirm(msg);
  if (!confirmed) return;

  try {
    const res = await apiFetch(`/orders/${orderId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ order_status: newStatus }),
    });

    if (res.ok) {
      // ✅ Update local memory state
      const updateInList = (list) => {
        const idx = list.findIndex((o) => String(o.id) === String(orderId));
        if (idx !== -1) {
          list[idx] = { ...list[idx], order_status: newStatus };
        }
      };
      updateInList(onlineOrdersList);
      if (typeof allOrdersList !== "undefined") updateInList(allOrdersList);

      updateOnlineStats();
      refreshNewOrdersBadge();
      
      const oIdx = onlineOrdersList.findIndex((o) => o.id === orderId);
      if (oIdx !== -1) {
        window.updateOrAddOnlineOrderDOM(onlineOrdersList[oIdx]);
      }
      
      if (typeof allOrdersList !== "undefined") {
        const aIdx = allOrdersList.findIndex((o) => o.id === orderId);
        if (aIdx !== -1) {
          window.updateOrAddAllOrderDOM(allOrdersList[aIdx]);
        }
      }

      showToast("تم تحديث الحالة بنجاح", "success");
    } else {
      showToast("فشل تحديث الحالة", "error");
    }
  } catch (err) {
    console.error(err);
    showToast("خطأ في الاتصال", "error");
  }
}

// ===================================================
//  Toggle Web Orders Availability
// ===================================================
let webOrdersEnabled = true;

async function initWebOrdersToggle() {
  try {
    const res = await apiFetch("/settings/web-orders");
    if (res.ok) {
      const data = await res.json();
      // Robust parsing: handle raw boolean or object with value_bool/value
      webOrdersEnabled =
        typeof data === "boolean"
          ? data
          : data.value_bool === true || data.value === true;
      updateWebOrdersToggleUI();
    }
  } catch (err) {
    console.warn(
      "Failed to fetch web-orders setting, defaulting to enabled",
      err,
    );
    updateWebOrdersToggleUI();
  }
}

async function toggleWebOrders() {
  const btn = document.getElementById("toggle_online_btn");
  if (!btn) return;

  const newValue = !webOrdersEnabled;
  const span = btn.querySelector("span");
  const originalText = span ? span.textContent : "تشغيل الطلبات";

  btn.style.opacity = "0.7";
  btn.style.pointerEvents = "none";
  if (span) span.textContent = "جاري الحفظ...";

  try {
    const res = await apiFetch("/settings/web-orders", {
      method: "PATCH",
      body: JSON.stringify({ value_bool: newValue }),
    });

    if (res.ok) {
      const data = await res.json();
      webOrdersEnabled =
        typeof data === "boolean"
          ? data
          : data.value_bool === true || data.value === true;
      showToast(
        webOrdersEnabled ? "تم تشغيل الطلبات بنجاح" : "تم إيقاف الطلبات بنجاح",
        "success",
      );
    } else {
      throw new Error("Failed to update setting");
    }
  } catch (err) {
    console.error("toggleWebOrders error", err);
    showToast("حدث خطأ أثناء الاتصال بالسيرفر", "error");
  } finally {
    btn.style.opacity = "1";
    btn.style.pointerEvents = "auto";
    if (span) span.textContent = originalText;
    updateWebOrdersToggleUI();
  }
}

function updateWebOrdersToggleUI() {
  const btn = document.getElementById("toggle_online_btn");
  if (!btn) return;

  const span = btn.querySelector("span");

  if (webOrdersEnabled) {
    btn.classList.add("active");
    if (span) span.textContent = "تشغيل الطلبات";
  } else {
    btn.classList.remove("active");
    if (span) span.textContent = "إيقاف الطلبات";
  }
}

// ===================================================
//  Online Orders Notifications
// ===================================================
// ===================================================
//  WebSocket - Real-time updates
// ===================================================

function updateConnectionStatus(status) {
  console.log("🔄 UI Connection Status Change:", status);
  const dot = document.getElementById("ws_status_dot");
  const text = document.getElementById("ws_status_text");
  if (!dot || !text) {
    console.warn("⚠️ Connection status elements not found in DOM");
    return;
  }

  if (status === "connected") {
    dot.style.background = "#2ecc71"; // Green
    text.textContent = "متصل مباشر";
  } else if (status === "disconnected") {
    dot.style.background = "#e74c3c"; // Red
    text.textContent = "غير متصل (إعادة محاولة)";
  } else {
    dot.style.background = "#f1c40f"; // Yellow
    text.textContent = "جاري الاتصال...";
  }
}
function setupWebSocket() {
  if (reconnectTimerId) {
    clearTimeout(reconnectTimerId);
    reconnectTimerId = null;
  }

  updateConnectionStatus("connecting");

  if (
    socket &&
    [WebSocket.OPEN, WebSocket.CONNECTING].includes(socket.readyState)
  ) {
    return;
  }

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/orders/ws/cashier`;

  console.log("📡 Attempting WebSocket connection:", wsUrl);
  const ws = new WebSocket(wsUrl);
  socket = ws;

  // Safety Timeout: if it doesn't open in 5s, close and retry
  const connectTimeoutId = setTimeout(() => {
    if (ws.readyState === WebSocket.CONNECTING) {
      console.warn("⚠️ WebSocket connection timed out (5s). Retrying...");
      ws.close();
    }
  }, 5000);

  ws.onopen = () => {
    clearTimeout(connectTimeoutId);
    console.log("✅ WebSocket connected successfully (Cashier)");
    updateConnectionStatus("connected");
  };

  ws.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.type !== "HEARTBEAT" && payload.type !== "HEARTBEAT_ACK") {
        console.debug("📥 Received WS message:", payload.type);
      }
      handleSocketEvent(payload);
    } catch (err) {
      console.error("❌ Error parsing WebSocket message:", err);
    }
  };

  ws.onclose = (e) => {
    clearTimeout(connectTimeoutId);
    if (socket !== ws) return;
    console.warn(
      `🔴 WebSocket disconnected. Code: ${e.code}, Reason: ${e.reason || "None"}`,
    );
    socket = null;
    updateConnectionStatus("disconnected");

    // Exponential backoff or simple delay
    if (!reconnectTimerId) {
      reconnectTimerId = setTimeout(() => {
        reconnectTimerId = null;
        setupWebSocket();
      }, 3000);
    }
  };

  ws.onerror = (err) => {
    clearTimeout(connectTimeoutId);
    console.error("❌ WebSocket error details:", err);
    updateConnectionStatus("disconnected");
  };
}

function handleSocketEvent(payload) {
  if (
    !payload ||
    payload.type === "HEARTBEAT" ||
    payload.type === "HEARTBEAT_ACK" ||
    payload.type === "heartbeat_ack"
  ) {
    return;
  }

  if (payload.type === "SETTING_UPDATED") {
    if (payload.data?.key === "web_orders_enabled") {
      webOrdersEnabled = payload.data.value_bool === true;
      updateWebOrdersToggleUI();
      showToast(
        webOrdersEnabled
          ? "تم تفعيل الطلبات من الإدارة"
          : "تم إيقاف الطلبات من الإدارة",
        "info",
      );
    }
    return;
  }

  if (payload.type === "ORDER_SNAPSHOT") {
    const orders = Array.isArray(payload.data?.orders)
      ? payload.data.orders
      : [];
    ordersSnapshotLoaded = true;
    // Local (cashier) orders from snapshot are authoritative on desktop
    const allFromSnapshot = orders.filter((o) => !isOnlineOrder(o));
    const onlineFromSnapshot = orders.filter(isOnlineOrder);
    // Respect pagination: only keep first page and set totals
    allOrdersTotal = allFromSnapshot.length;
    onlineOrdersTotal = onlineFromSnapshot.length;
    allOrdersList = allFromSnapshot.slice(0, ordersPageSize);
    onlineOrdersList = onlineFromSnapshot.slice(0, ordersPageSize);
    allOrdersCurrentPage = 1;
    onlineOrdersCurrentPage = 1;
    lastSocketOrderUpdate = Date.now();
    updateOnlineStats();
    renderOnlineOrders();
    renderAllOrders();
    refreshNewOrdersBadge();
    updateConnectionStatus("connected");

    // Always fetch from server for accurate pagination and data
    setTimeout(() => {
      fetchOnlineOrdersServer(1, true);
      fetchAllOrdersServer(1, true);
    }, 300);
    return;
  }

  if (payload.type === "SYNC_COMPLETE") {
    console.log("Desktop master data sync complete, refreshing data safely...");
    // Safe targeted refresh: reload menu and orders without resetting UI state (cart, modals, etc.)
    _safeSyncRefresh();
    return;
  }

  // Customer/Address real-time sync from cloud/other device
  if (
    payload.type === "CUSTOMER_CREATED" ||
    payload.type === "ADDRESS_CREATED"
  ) {
    console.log("Customer data synced:", payload.type, payload.data);
    // No UI action needed - customer data will be fetched fresh when next order is placed
    // But if delivery customer form is open with same phone, we could refresh it
    if (
      payload.type === "ADDRESS_CREATED" &&
      deliveryCustomerInfo.phone &&
      payload.data
    ) {
      const eventPhone = payload.data.customer_phone;
      if (eventPhone && eventPhone === deliveryCustomerInfo.phone) {
        // Refresh the customer addresses in memory
        _refreshCustomerAddresses(deliveryCustomerInfo.phone);
      }
    }
    return;
  }

  const { event, data } = payload;
  if (!data || !data.id) return;

  ordersSnapshotLoaded = true;
  const eventName = normalizeOrderEventName(payload.type || event);
  console.log("Real-time event:", eventName, data.id);

  // 1. Update internal state
  let hasChanged = false;

  // Handle Order Created
  if (eventName === "NEW_ORDER") {
    // Deduplication by Order Number + Date (Essential for Hybrid mode)
    const isDuplicateNumber = (list, newItem) => {
      return list.find(
        (o) =>
          o.id === newItem.id ||
          (o.order_number === newItem.order_number &&
            o.order_date === newItem.order_date),
      );
    };

    if (isOnlineOrder(data)) {
      if (!isDuplicateNumber(onlineOrdersList, data)) {
        onlineOrdersList.unshift(data);
        // Trim to page size to keep pagination consistent
        if (onlineOrdersList.length > ordersPageSize) {
          onlineOrdersList = onlineOrdersList.slice(0, ordersPageSize);
        }
        onlineOrdersTotal++;
        hasChanged = true;
        playNotificationSound();
        showToast(
          "طلب أونلاين جديد! #" + (data.order_number || data.id),
          "success",
        );
      }
    }
    // Also track in all orders if loaded
    if (typeof allOrdersList !== "undefined") {
      if (!isDuplicateNumber(allOrdersList, data)) {
        if (!isOnlineOrder(data)) {
          allOrdersList.unshift(data);
          // Trim to page size to keep pagination consistent
          if (allOrdersList.length > ordersPageSize) {
            allOrdersList = allOrdersList.slice(0, ordersPageSize);
          }
          allOrdersTotal++;
          hasChanged = true;
        }
      }
    }
  }
  // Handle Order Updated / Status Changed
  else if (eventName === "ORDER_UPDATED") {
    console.log(
      "Processing update for order:",
      data.order_number,
      "Status:",
      data.order_status,
    );

    const findIdx = (list) =>
      list.findIndex(
        (o) =>
          String(o.id) === String(data.id) ||
          (o.order_number === data.order_number &&
            o.order_date === data.order_date),
      );

    const oIdx = findIdx(onlineOrdersList);
    if (oIdx !== -1) {
      const localId = onlineOrdersList[oIdx].id;
      // Merge but preserve local ID to avoid 404s on local actions
      onlineOrdersList[oIdx] = {
        ...onlineOrdersList[oIdx],
        ...data,
        id: localId,
      };
      hasChanged = true;
      console.log("Updated onlineOrdersList at index", oIdx);
    }

    if (typeof allOrdersList !== "undefined") {
      const aIdx = findIdx(allOrdersList);
      if (aIdx !== -1) {
        const localId = allOrdersList[aIdx].id;
        allOrdersList[aIdx] = { ...allOrdersList[aIdx], ...data, id: localId };
        hasChanged = true;
        console.log("Updated allOrdersList at index", aIdx);
      }
    }

    if (hasChanged) {
      showToast(
        `تحديث طلب #${data.order_number || data.id}: ${data.order_status}`,
        "success",
      );
    } else {
      console.warn(
        "Order update received but could not find order in local lists. Triggering full refresh...",
      );
      setTimeout(fetchAllOrders, 500); // Fallback for safety, delayed to allow DB commit
    }
  }

  // Real-time Menu Updates
  if (payload.type === "PRODUCT_UPDATED") {
    apiFetch("/menu/products")
      .then((res) => res.json())
      .then((prods) => {
        products = Array.isArray(prods) ? prods : prods.data || [];
        renderItems();
      });
  } else if (payload.type === "CATEGORY_UPDATED") {
    apiFetch("/menu/categories")
      .then((res) => res.json())
      .then((cats) => {
        categories = Array.isArray(cats) ? cats.filter((c) => c.is_active) : [];
        renderTabs();
        renderItems();
      });
  }

  // 2. Trigger UI Refresh if we are on a relevant tab
  if (hasChanged) {
    const onlineLayout = document.getElementById("online_orders_layout");
    const allLayout = document.getElementById("all_orders_layout");
    const ridersLayout = document.getElementById("riders_layout");

    if (onlineLayout && onlineLayout.style.display !== "none") {
      updateOnlineStats();
      const oIdx = onlineOrdersList.findIndex(o => String(o.id) === String(data.id) || (o.order_number === data.order_number && o.order_date === data.order_date));
      if (oIdx !== -1) {
        window.updateOrAddOnlineOrderDOM(onlineOrdersList[oIdx]);
      } else {
        renderOnlineOrders();
      }
    }
    if (allLayout && allLayout.style.display !== "none") {
      const aIdx = allOrdersList.findIndex(o => String(o.id) === String(data.id) || (o.order_number === data.order_number && o.order_date === data.order_date));
      if (aIdx !== -1) {
        window.updateOrAddAllOrderDOM(allOrdersList[aIdx]);
      } else {
        renderAllOrders();
      }
    }
    if (ridersLayout && ridersLayout.style.display !== "none") {
      renderRidersTab();
    }

    // Update count badge from server
    refreshNewOrdersBadge();
    lastNewOrdersCount = totalNewOrdersGlobalCount; // for legacy sync if any
    
    // Refresh order details modal if it's open for the updated order
    const detailOverlay = document.getElementById("order_detail_overlay");
    if (detailOverlay && detailOverlay.dataset.orderId === String(data.id)) {
      const source = detailOverlay.dataset.source;
      detailOverlay.remove();
      openOrderDetails(data.id, source);
    }
  }
}

function normalizeOrderEventName(eventName) {
  if (eventName === "order.created" || eventName === "ORDER_CREATED")
    return "NEW_ORDER";
  if (eventName === "order.updated" || eventName === "order.status_changed")
    return "ORDER_UPDATED";
  return eventName || "";
}

/**
 * Safe background refresh triggered by SYNC_COMPLETE.
 * Unlike init(), this does NOT reset cart, order type, modals, or any other UI state.
 * It only silently refreshes the underlying data (menu + orders) in the background.
 */
let _safeSyncDebounceTimer = null;
async function _safeSyncRefresh() {
  // Debounce: multiple SYNC_COMPLETE events can arrive in quick succession
  if (_safeSyncDebounceTimer) clearTimeout(_safeSyncDebounceTimer);
  _safeSyncDebounceTimer = setTimeout(async () => {
    try {
      // 1. Refresh menu data (products + categories) silently
      const [catsRes, prodsRes] = await Promise.all([
        apiFetch("/menu/categories"),
        apiFetch("/menu/products"),
      ]);
      if (catsRes.ok) {
        const catsData = await catsRes.json();
        categories = Array.isArray(catsData)
          ? catsData.filter((c) => c.is_active)
          : [];
        renderTabs();
      }
      if (prodsRes.ok) {
        const prodsData = await prodsRes.json();
        products = Array.isArray(prodsData) ? prodsData : prodsData.data || [];
        renderItems();
      }

      // 2. Refresh orders silently (no loader, no toast)
      await Promise.all([
        fetchOnlineOrdersServer(onlineOrdersCurrentPage || 1, true),
        fetchAllOrdersServer(allOrdersCurrentPage || 1, true),
        refreshNewOrdersBadge(),
      ]);

      ordersSnapshotLoaded = true;
      updateOnlineStats();

      // 3. Re-render visible tabs
      const onlineLayout = document.getElementById("online_orders_layout");
      const allLayout = document.getElementById("all_orders_layout");
      const ridersLayout = document.getElementById("riders_layout");
      if (onlineLayout && onlineLayout.style.display !== "none")
        renderOnlineOrders();
      if (allLayout && allLayout.style.display !== "none") renderAllOrders();
      if (ridersLayout && ridersLayout.style.display !== "none")
        renderRidersTab();

      console.log("✅ Safe sync refresh completed");
    } catch (err) {
      console.warn("Safe sync refresh failed (non-critical):", err);
    }
  }, 500); // 500ms debounce
}

/**
 * Refresh customer addresses in memory when a new address is synced from another device.
 * Only updates if the delivery form is currently showing this customer's data.
 */
async function _refreshCustomerAddresses(phone) {
  if (!phone) return;
  try {
    const res = await apiFetch(
      `/customers/by-phone/${encodeURIComponent(phone)}`,
    );
    if (res.ok) {
      const data = await res.json();
      if (data && Array.isArray(data.addresses)) {
        deliveryCustomerInfo.addresses = data.addresses;
        // If we had a selected address, keep it; otherwise auto-select if only one
        if (data.addresses.length === 1) {
          deliveryCustomerInfo.selectedAddressId = data.addresses[0].id;
        }
        // Re-render the address field if visible
        const addrField = document.getElementById("dcf_address_field");
        if (addrField && typeof renderAddressFieldHTML === "function") {
          addrField.innerHTML = renderAddressFieldHTML();
        }
        console.log(
          "✅ Customer addresses refreshed from sync:",
          data.addresses.length,
          "addresses",
        );
      }
    }
  } catch (err) {
    console.warn("Could not refresh customer addresses:", err);
  }
}

function isOnlineOrder(order) {
  const source = String(
    order?.source || order?.order_source || "",
  ).toLowerCase();
  return source === "online" || source === "ordersource.online";
}

function updateOnlineTabBadge(count) {
  const badge = document.getElementById("online_orders_badge");
  if (!badge) return;

  if (count > 0) {
    badge.textContent = count;
    badge.style.display = "flex";
  } else {
    badge.style.display = "none";
  }
}

function playNotificationSound() {
  if (!isNotificationSoundEnabled) return;

  try {
    // صوت تنبيه مميز (Bell)
    const audio = new Audio(
      "https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3",
    );
    audio.play().catch((e) => {
      // المتصفح قد يمنع الـ Autoplay إذا لم يحدث تفاعل
      console.warn(
        "Notification sound blocked by browser. Interaction needed.",
        e,
      );
    });
  } catch (e) {
    console.error("Error playing notification sound:", e);
  }
}

function toggleSound() {
  isNotificationSoundEnabled = !isNotificationSoundEnabled;

  const iconOn = document.getElementById("sound_icon_on");
  const iconOff = document.getElementById("sound_icon_off");
  const btn = document.getElementById("sound_toggle_btn");

  if (isNotificationSoundEnabled) {
    if (iconOn) iconOn.style.display = "block";
    if (iconOff) iconOff.style.display = "none";
    if (btn) {
      btn.style.background = "rgba(61, 158, 107, 0.2)";
      btn.style.borderColor = "var(--color-accent, #3d9e6b)";
      btn.style.color = "var(--color-accent, #3d9e6b)";
    }
    playNotificationSound();
    showToast("تم تفعيل صوت التنبيهات", "success");
  } else {
    if (iconOn) iconOn.style.display = "none";
    if (iconOff) iconOff.style.display = "block";
    if (btn) {
      btn.style.background = "rgba(201, 168, 76, 0.12)";
      btn.style.borderColor = "rgba(201, 168, 76, 0.4)";
      btn.style.color = "var(--color-primary)";
    }
    showToast("تم كتم صوت التنبيهات", "info");
  }
}

function printOrderFromOnline(orderId) {
  const order = onlineOrdersList.find((o) => o.id === orderId);
  if (!order) return;

  const cartMapped = (order.items || []).map((item) => {
    let prod = products.find((p) => p.id === item.product_id);
    let variantName = "";
    if (prod && prod.variants) {
      let v = prod.variants.find(
        (v) => parseFloat(v.price) === parseFloat(item.unit_price),
      );
      if (v && v.name !== prod.product_name) variantName = v.name + " - ";
    }
    let name = prod
      ? variantName + prod.product_name
      : `صنف #${item.product_id}`;
    return {
      qty: item.quantity,
      item: {
        name: name,
        price: parseFloat(item.unit_price),
      },
    };
  });

  const printData = {
    ...order,
    cart: cartMapped,
    customerAddress: getOrderAddressText(order),
  };
  if (typeof printReceipt === "function") {
    printReceipt(printData);
  }
}

// ===================================================
//  All Orders
// ===================================================
let allOrdersList = [];
let allOrdersFilter = "all";
let allOrdersSearchTerm = "";
let allOrdersCurrentPage = 1;
let allOrdersTotal = 0;

function setAllOrdersFilter(filter, btn) {
  allOrdersFilter = filter;
  const btns = document.querySelectorAll("#all_orders_filters .filter_btn");
  btns.forEach((b) => b.classList.remove("active"));
  if (btn) btn.classList.add("active");
  allOrdersCurrentPage = 1;
  fetchAllOrdersServer(1);
}

function handleAllOrdersSearch(term) {
  allOrdersSearchTerm = term.trim().toLowerCase();
  allOrdersCurrentPage = 1;
  renderAllOrders();
}

function renderAllOrders() {
  const grid = document.getElementById("all_orders_grid");
  if (!grid) return;

  if (!ordersSnapshotLoaded) {
    grid.innerHTML = `<p style="color:var(--color-primary);text-align:center;grid-column:1/-1;padding:40px;">جاري الاتصال بالتحديثات المباشرة...</p>`;
    return;
  }

  const term = (allOrdersSearchTerm || "").toLowerCase();
  const filteredList = allOrdersList.filter(o => {
    if (!term) return true;
    const oNum = String(o.order_number || o.id || "").toLowerCase();
    const phone = String(o.customer_phone || "").toLowerCase();
    const name = String(o.customer_name || "").toLowerCase();
    return oNum.includes(term) || phone.includes(term) || name.includes(term);
  });

  if (filteredList.length === 0) {
    grid.innerHTML = `<p style="color:var(--color-subtext);text-align:center;grid-column:1/-1;padding:40px;">لا توجد طلبات</p>`;
    return;
  }

  grid.innerHTML = "";

  const statusMap = {
    new: { label: "جديد", cls: "badge_new" },
    completed: { label: "مكتمل", cls: "badge_ready" },
    cancelled: { label: "ملغي", cls: "badge_canceled" },
    confirmed: { label: "مؤكد", cls: "badge_ready" },
    delivered: { label: "تم التوصيل", cls: "badge_ready" },
  };

  window.createAllOrderCardElement = function(order) {
    const typeLabel =
      order.order_type === "delivery"
        ? "دليفري"
        : order.order_type === "takeaway"
          ? "تيك أواي"
          : "صالة";

    let statusObj = statusMap[order.order_status] || {
      label: order.order_status,
      cls: "",
    };
    let badgeHtml = `<span class="order_status ${statusObj.cls}">${statusObj.label}</span>`;

    let timeStr = "---";
    const backendTime = order.created_at || order.order_date;
    if (backendTime) {
      let d = new Date(backendTime);
      if (!isNaN(d)) {
        const timePart = d.toLocaleTimeString("ar-EG", {
          hour: "2-digit",
          minute: "2-digit",
        });
        const datePart = d.toLocaleDateString("ar-EG");
        timeStr =
          String(backendTime).length > 10
            ? `${timePart} - ${datePart}`
            : datePart;
      } else {
        timeStr = backendTime;
      }
    }

    let actionsHtml = "";

    if (order.order_status === "confirmed") {
      const isDelivery = order.order_type === "delivery";
      const completeLabel = isDelivery ? "تم التوصيل" : "مكتمل";
      const completeStatus = isDelivery ? "delivered" : "completed";

      actionsHtml = `
          <button onclick="event.stopPropagation(); printOrderFromList(${order.id})" style="background:#5c5c5c; color:#fff; border:none; padding:5px 12px; border-radius:6px; font-family:Cairo,sans-serif; font-size:11px; font-weight:700; cursor:pointer; margin-left:6px;">طباعة</button>
          <button onclick="event.stopPropagation(); changeOrderStatus(${order.id}, '${completeStatus}')" style="background:#1d5c2b; color:#fff; border:none; padding:5px 12px; border-radius:6px; font-family:Cairo,sans-serif; font-size:11px; font-weight:700; cursor:pointer; margin-left:6px;">${completeLabel}</button>
          <button onclick="event.stopPropagation(); changeOrderStatus(${order.id}, 'cancelled')" style="background:#e40411; color:#fff; border:none; padding:5px 12px; border-radius:6px; font-family:Cairo,sans-serif; font-size:11px; font-weight:700; cursor:pointer; margin-left:6px;">إلغاء</button>
          <button onclick="event.stopPropagation(); openEditOrderModal(${order.id}, 'all')" style="background:var(--color-secondary, #2980b9); color:#fff; border:none; padding:5px 12px; border-radius:6px; font-family:Cairo,sans-serif; font-size:11px; font-weight:700; cursor:pointer;"> تعديل</button>
        `;
    } else if (order.order_status === "new") {
      actionsHtml = `
          <button onclick="event.stopPropagation(); printOrderFromList(${order.id})" style="background:#5c5c5c; color:#fff; border:none; padding:5px 12px; border-radius:6px; font-family:Cairo,sans-serif; font-size:11px; font-weight:700; cursor:pointer; margin-left:6px;">طباعة</button>
          <button onclick="event.stopPropagation(); changeOrderStatus(${order.id}, 'confirmed')" style="background:var(--color-primary); color:#000; border:none; padding:5px 12px; border-radius:6px; font-family:Cairo,sans-serif; font-size:11px; font-weight:700; cursor:pointer; margin-left:6px;">مؤكد</button>
          <button onclick="event.stopPropagation(); openEditOrderModal(${order.id}, 'all')" style="background:var(--color-secondary, #2980b9); color:#fff; border:none; padding:5px 12px; border-radius:6px; font-family:Cairo,sans-serif; font-size:11px; font-weight:700; cursor:pointer;"> تعديل</button>
        `;
    } else if (order.order_status !== "cancelled") {
      actionsHtml = `
          <button onclick="event.stopPropagation(); printOrderFromList(${order.id})" style="background:#5c5c5c; color:#fff; border:none; padding:5px 12px; border-radius:6px; font-family:Cairo,sans-serif; font-size:11px; font-weight:700; cursor:pointer;">طباعة</button>
        `;
    }

    const totalAmount = parseFloat(order.total_amount || 0).toFixed(2);

    let itemsHtml = "";
    if (order.items && order.items.length > 0) {
      let itemsList = order.items
        .map((item) => {
          let prod = products.find((p) => p.id === item.product_id);
          let variantName = "";
          if (prod && prod.variants) {
            let v = prod.variants.find(
              (v) => parseFloat(v.price) === parseFloat(item.unit_price),
            );
            if (v && v.name !== prod.product_name) variantName = v.name + " - ";
          }
          let name = prod
            ? variantName + prod.product_name
            : ` صنف #${item.product_id}`;
          return `
            <div style="display:flex; justify-content:space-between; margin-bottom:2px; font-size:11px;">
              <span style="color:var(--color-text);">- ${name}</span>
              <span style="color:var(--color-subtext);">${item.quantity}x (${parseFloat(item.unit_price).toFixed(2)} ج.م)</span>
            </div>
          `;
        })
        .join("");

      itemsHtml = `
          <div style="background:rgba(0,0,0,0.15); padding:6px; border-radius:6px; margin-top:6px;">
            ${itemsList}
          </div>
        `;
    }

    let updatedTimeStr = "";
    if (order.updated_at && order.created_at && Math.abs(new Date(order.updated_at).getTime() - new Date(order.created_at).getTime()) > 2000) {
        let du = new Date(order.updated_at);
        if (!isNaN(du)) {
            updatedTimeStr = `<span style="display:block; color:#f39c12; font-size:10px; margin-top:2px;">عدل في: ${du.toLocaleTimeString("ar-EG", {hour: "2-digit", minute: "2-digit"})} - ${du.toLocaleDateString("ar-EG")}</span>`;
        }
    }

    const card = document.createElement("div");
    card.className = "online_order_card";
    card.id = `all_order_card_${order.id}`;
    card.onclick = () => openOrderDetails(order.id, "all");
    card.style.cssText =
      "padding:12px; gap:8px; min-height:0; display:flex; flex-direction:column;";
    card.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:flex-start;">
          <div style="display:flex; align-items:center; gap:8px;">
            ${badgeHtml}
            <span style="font-size:14px; font-weight:800; color:var(--color-primary);">#${order.order_number || order.id}</span>
            <span style="font-size:11px; padding:2px 6px; background:rgba(255,255,255,0.05); border-radius:4px; color:var(--color-subtext);">${typeLabel}</span>
          </div>
          <div style="display:flex; flex-direction:column; align-items:flex-end;">
            <span style="font-size:11px; color:var(--color-subtext);">${timeStr}</span>
            ${updatedTimeStr}
          </div>
        </div>
        <div style="display:flex; justify-content:space-between; align-items:center; border-top:1px dashed rgba(201,168,76,0.3); padding-top:8px; margin-top:2px;">
          <span style="font-size:15px; font-weight:800; color:var(--color-primary);">${totalAmount} ج.م</span>
          <div style="display:flex; flex-direction:column; align-items:flex-end; gap:2px;">
            ${order.customer_phone ? `<span style="font-size:12px; color:var(--color-text);">${order.customer_phone}</span>` : ""}
            ${order.order_type === "delivery" && order.delivery_person_name ? `<span style="font-size:11px; color:var(--color-primary); font-weight:bold;">المندوب: ${order.delivery_person_name}</span>` : ""}
            <span style="font-size:11px; color:var(--color-subtext); text-align:right; max-width:200px;">
              ${
                typeof order.address === "object" && order.address !== null
                  ? order.address.address
                  : order.customer_address ||
                    order.address ||
                    "---"
              }
            </span>
          </div>
        </div>
        ${itemsHtml}
        ${
          actionsHtml
            ? `
          <div style="margin-top:auto; padding-top:8px; display:flex; justify-content:flex-end; border-top:1px solid rgba(255,255,255,0.05)">
            ${actionsHtml}
          </div>
        `
            : ""
        }
      `;
    return card;
  };

  window.updateOrAddAllOrderDOM = function(order) {
    const grid = document.getElementById("all_orders_grid");
    if (!grid) return;

    if (grid.innerHTML.includes("لا توجد طلبات") || grid.innerHTML.includes("جاري الاتصال")) {
        grid.innerHTML = "";
    }

    const newCard = createAllOrderCardElement(order);
    const existingCard = document.getElementById(`all_order_card_${order.id}`);

    if (existingCard) {
      existingCard.replaceWith(newCard);
    } else {
      // Prepend before pagination if exists
      const firstCard = grid.querySelector('.online_order_card'); // note: both use online_order_card class
      if (firstCard) {
        grid.insertBefore(newCard, firstCard);
      } else {
        grid.prepend(newCard);
      }
    }
  };

  filteredList.forEach((order) => {
    grid.appendChild(createAllOrderCardElement(order));
  });

  const pagination = renderPagination(
    allOrdersTotal,
    allOrdersCurrentPage,
    ordersPageSize,
    "changeAllOrdersPage",
  );
  if (pagination) grid.appendChild(pagination);
}

function renderPagination(totalItems, currentPage, pageSize, onPageChangeName) {
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));

  const container = document.createElement("div");
  container.className = "pagination-container";
  container.style.cssText =
    "grid-column:1/-1; display:flex; justify-content:center; align-items:center; margin-top:20px; padding:10px; gap:8px;";

  const btnPrev = document.createElement("button");
  btnPrev.textContent = "السابق";
  btnPrev.disabled = currentPage === 1;
  btnPrev.style.cssText = `padding:6px 12px; border-radius:8px; border:1px solid rgba(255,255,255,0.1); background:rgba(255,255,255,0.05); color:white; cursor:${currentPage === 1 ? "default" : "pointer"}; opacity:${currentPage === 1 ? "0.3" : "1"}; font-family:Cairo,sans-serif; font-size:12px;`;
  btnPrev.onclick = (e) => {
    e.stopPropagation();
    window[onPageChangeName](currentPage - 1);
  };
  container.appendChild(btnPrev);

  // Show page numbers
  let startPage = Math.max(1, currentPage - 2);
  let endPage = Math.min(totalPages, startPage + 4);
  if (endPage - startPage < 4) startPage = Math.max(1, endPage - 4);

  for (let i = startPage; i <= endPage; i++) {
    const pBtn = document.createElement("button");
    pBtn.textContent = i;
    const isActive = i === currentPage;
    pBtn.style.cssText = `min-width:32px; height:32px; border-radius:6px; border:none; background:${isActive ? "var(--color-primary)" : "rgba(255,255,255,0.08)"}; color:${isActive ? "#000" : "#fff"}; cursor:pointer; font-weight:bold; font-family:Cairo,sans-serif; font-size:12px;`;
    pBtn.onclick = (e) => {
      e.stopPropagation();
      window[onPageChangeName](i);
    };
    container.appendChild(pBtn);
  }

  const btnNext = document.createElement("button");
  btnNext.textContent = "التالي";
  btnNext.disabled = currentPage === totalPages;
  btnNext.style.cssText = `padding:6px 12px; border-radius:8px; border:1px solid rgba(255,255,255,0.1); background:rgba(255,255,255,0.05); color:white; cursor:${currentPage === totalPages ? "default" : "pointer"}; opacity:${currentPage === totalPages ? "0.3" : "1"}; font-family:Cairo,sans-serif; font-size:12px;`;
  btnNext.onclick = (e) => {
    e.stopPropagation();
    window[onPageChangeName](currentPage + 1);
  };
  container.appendChild(btnNext);

  return container;
}

function changeOnlinePage(newPage) {
  fetchOnlineOrdersServer(newPage);
}

function changeAllOrdersPage(newPage) {
  fetchAllOrdersServer(newPage);
}

// Expose to window for the onclick strings if any
window.changeOnlinePage = changeOnlinePage;
window.changeAllOrdersPage = changeAllOrdersPage;

function printOrderFromList(orderId) {
  const order = allOrdersList.find((o) => o.id === orderId);
  if (!order) {
    showToast("لا يمكن العثور على الطلب", "error");
    return;
  }

  const cartMapped = (order.items || []).map((item) => {
    let prod = products.find((p) => p.id === item.product_id);
    let variantName = "";
    if (prod && prod.variants) {
      let v = prod.variants.find(
        (v) => parseFloat(v.price) === parseFloat(item.unit_price),
      );
      if (v && v.name !== prod.product_name) variantName = v.name + " - ";
    }
    let name = prod
      ? variantName + prod.product_name
      : ` صنف #${item.product_id}`;
    return {
      qty: item.quantity,
      item: {
        name: name,
        price: parseFloat(item.unit_price),
      },
    };
  });

  // نمرر كائن الطلب بالكامل لضمان استخدام بيانات السيرفر (order_number, created_at, creator_name)
  const printData = {
    ...order,
    cart: cartMapped,
    customerAddress: getOrderAddressText(order),
  };

  if (typeof printReceipt === "function") {
    printReceipt(printData);
    showToast("جاري تجهيز الفاتورة للطباعة...", "success");
  } else {
    console.error("Function printReceipt not found.");
    showToast("خطأ: دالة الطباعة غير موجودة", "error");
  }
}

async function changeOrderStatus(orderId, status) {
  const statusLabels = {
    completed: "مكتمل",
    delivered: "تم التوصيل",
    cancelled: "ملغي",
    confirmed: "مؤكد",
  };
  const confirmed = await showCustomActionConfirm(
    `هل أنت متأكد من تغيير حالة الطلب إلى ${statusLabels[status] || status}؟`,
  );
  if (!confirmed) return;

  try {
    const res = await apiFetch(`/orders/${orderId}/status`, {
      method: "PATCH",
      body: JSON.stringify({
        order_status: status,
        delivery_person_id: null,
        internal_notes: null,
      }),
    });

    if (res.ok) {
      // Update in-memory lists immediately
      const updateInList = (list) => {
        const idx = list.findIndex((o) => String(o.id) === String(orderId));
        if (idx !== -1) {
          list[idx] = { ...list[idx], order_status: status };
        }
      };
      updateInList(allOrdersList);
      if (typeof onlineOrdersList !== "undefined")
        updateInList(onlineOrdersList);

      showToast("تم تحديث حالة الطلب", "success");
      const oIdx = typeof onlineOrdersList !== "undefined" ? onlineOrdersList.findIndex((o) => String(o.id) === String(orderId)) : -1;
      if (oIdx !== -1) {
        window.updateOrAddOnlineOrderDOM(onlineOrdersList[oIdx]);
      }

      const aIdx = allOrdersList.findIndex((o) => String(o.id) === String(orderId));
      if (aIdx !== -1) {
        window.updateOrAddAllOrderDOM(allOrdersList[aIdx]);
      }
      updateOnlineStats();
      refreshNewOrdersBadge();
    } else {
      const err = await res.json().catch(() => ({}));
      console.error("Change status error details:", err);
      let errMsg = "خطأ غير معروف";
      if (typeof err.detail === "string") {
        errMsg = err.detail;
      } else if (Array.isArray(err.detail)) {
        errMsg = err.detail.map((e) => e.msg).join(", ");
      }
      showToast("فشل تحديث الحالة", "error");
      showErrorModal("الخادم رفض العملية بسبب:<br><br>" + errMsg);
    }
  } catch (e) {
    console.error(e);
    showToast("خطأ في الاتصال بالخادم", "error");
  }
}

// Custom Error Modal to avoid native alert()
function showErrorModal(message) {
  const overlay = document.createElement("div");
  overlay.style.position = "fixed";
  overlay.style.inset = "0";
  overlay.style.background = "rgba(0,0,0,0.8)";
  overlay.style.backdropFilter = "blur(5px)";
  overlay.style.display = "flex";
  overlay.style.alignItems = "center";
  overlay.style.justifyContent = "center";
  overlay.style.zIndex = "9999";
  overlay.innerHTML = `
    <div style="background:var(--color-primary-light, #1a1500); border:1px solid #e40411; border-radius:12px; padding:24px; min-width:300px; max-width:90%; text-align:center; box-shadow:0 10px 30px rgba(228,4,17,0.2);">
      <svg style="width:48px;height:48px;color:#e40411;margin-bottom:16px;" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
      </svg>
      <h3 style="color:#e40411; margin-bottom:12px; font-weight:bold; font-family:'Cairo',sans-serif;">تنبيه</h3>
      <p style="color:var(--color-text, #fff); font-size:14px; margin-bottom:24px; font-family:'Cairo',sans-serif;">${message}</p>
      <button style="background:#e40411; color:#fff; border:none; padding:8px 32px; border-radius:6px; font-weight:bold; font-family:'Cairo',sans-serif; cursor:pointer; font-size:14px;" onclick="this.parentElement.parentElement.remove()">حسناً</button>
    </div>
  `;
  document.body.appendChild(overlay);
}

// Custom Confirm Modal to avoid native confirm()
function showCustomActionConfirm(message) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.style.position = "fixed";
    overlay.style.inset = "0";
    overlay.style.background = "rgba(0,0,0,0.8)";
    overlay.style.backdropFilter = "blur(5px)";
    overlay.style.display = "flex";
    overlay.style.alignItems = "center";
    overlay.style.justifyContent = "center";
    overlay.style.zIndex = "20000";
    overlay.innerHTML = `
      <div style="background:var(--color-primary-light, #1a1500); border:1px solid var(--color-primary, #c9a84c); border-radius:12px; padding:24px; min-width:300px; max-width:90%; text-align:center; box-shadow:0 10px 30px rgba(201,168,76,0.15);">
        <svg style="width:48px;height:48px;color:var(--color-primary, #c9a84c);margin-bottom:16px;" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <h3 style="color:var(--color-primary, #c9a84c); margin-bottom:12px; font-weight:bold; font-family:'Cairo',sans-serif;">تأكيد الإجراء</h3>
        <p style="color:var(--color-text, #fff); font-size:14px; margin-bottom:24px; font-family:'Cairo',sans-serif;">${message}</p>
        <div style="display:flex; justify-content:center; gap:12px;">
          <button id="btn_confirm_yes" style="background:var(--color-primary, #c9a84c); color:#000; border:none; padding:8px 24px; border-radius:6px; font-weight:bold; font-family:'Cairo',sans-serif; cursor:pointer; font-size:14px;">تأكيد</button>
          <button id="btn_confirm_no" style="background:transparent; border:1px solid rgba(255,255,255,0.2); color:#fff; padding:8px 24px; border-radius:6px; font-family:'Cairo',sans-serif; cursor:pointer; font-size:14px;">إلغاء</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    overlay.querySelector("#btn_confirm_yes").addEventListener("click", () => {
      overlay.remove();
      resolve(true);
    });

    overlay.querySelector("#btn_confirm_no").addEventListener("click", () => {
      overlay.remove();
      resolve(false);
    });
  });
}

// ===================================================
//  Logout
// ===================================================
async function logout() {
  const token = localStorage.getItem("token");
  const headers = token ? { Authorization: "Bearer " + token } : {};

  try {
    // محاوله إبلاغ السيرفر بتسجيل الخروج لإبطال التوكن
    await fetch(`${API_BASE}/auth/logout`, {
      method: "POST",
      headers: {
        ...headers,
        "Content-Type": "application/json",
      },
    });
  } catch (err) {
    console.warn("Logout API error:", err);
  } finally {
    // في كل الأحوال، مسح البيانات المحلية والتحويل لصفحة الدخول
    localStorage.removeItem("token");
    localStorage.removeItem("token_type");
    localStorage.removeItem("user_id");
    localStorage.removeItem("username");
    localStorage.removeItem("role");
    localStorage.removeItem("user");

    // التحويل لصفحة الدخول الرئيسية
    window.location.replace("../index.html");
  }
}

// ===================================================
//  Order Details Modal
// ===================================================
function openOrderDetails(orderId, source) {
  const list = source === "online" ? onlineOrdersList : allOrdersList;
  const order = list.find((o) => o.id === orderId);
  if (!order) return;

  const typeLabels = {
    delivery: "دليفري",
    takeaway: "تيك أواي",
    dine_in: "صالة",
    hall: "صالة",
  };

  const statusMap = {
    new: { label: "جديد", cls: "badge_new" },
    completed: { label: "مكتمل", cls: "badge_ready" },
    cancelled: { label: "ملغي", cls: "badge_canceled" },
    confirmed: { label: "مؤكد", cls: "badge_ready" },
    delivered: { label: "تم التوصيل", cls: "badge_ready" },
  };
  const statusObj = statusMap[order.order_status] || {
    label: order.order_status,
    cls: "",
  };

  const overlay = document.createElement("div");
  overlay.id = "order_detail_overlay";
  overlay.dataset.orderId = orderId;
  overlay.dataset.source = source;
  overlay.style.position = "fixed";
  overlay.style.inset = "0";
  overlay.style.background = "rgba(0,0,0,0.85)";
  overlay.style.backdropFilter = "blur(10px)";
  overlay.style.display = "flex";
  overlay.style.alignItems = "center";
  overlay.style.justifyContent = "center";
  overlay.style.zIndex = "10000";

  let itemsHtml = (order.items || [])
    .map((item) => {
      let prod = products.find((p) => p.id === item.product_id);
      let variantName = "";
      if (prod && prod.variants) {
        let v = prod.variants.find(
          (v) => parseFloat(v.price) === parseFloat(item.unit_price),
        );
        if (v && v.name !== prod.product_name) variantName = v.name + " - ";
      }
      let name = prod
        ? variantName + prod.product_name
        : ` صنف #${item.product_id}`;
      let subtotal = (
        parseFloat(item.unit_price) * parseInt(item.quantity)
      ).toFixed(2);
      return `
      <tr>
        <td>${name}</td>
        <td>${item.quantity}</td>
        <td>${parseFloat(item.unit_price).toFixed(2)}</td>
        <td>${subtotal} ج.م</td>
      </tr>
    `;
    })
    .join("");

  const deliveryFee = parseFloat(order.delivery_fee || 0);
  const itemsTotal = parseFloat(order.subtotal || order.total_amount || 0);

  // Compute modification date display
  let modificationHtml = "";
  if (order.updated_at && order.created_at) {
    const createdMs = new Date(order.created_at).getTime();
    const updatedMs = new Date(order.updated_at).getTime();
    if (Math.abs(updatedMs - createdMs) > 2000) {
      modificationHtml = `<div style="color:#f39c12;">
        <span style="opacity:0.8;">آخر تعديل:</span>
        <span style="font-weight:700; margin-right:4px;">${new Date(order.updated_at).toLocaleString("ar-EG")}</span>
      </div>`;
    }
  }
  const createdAtStr = order.created_at ? new Date(order.created_at).toLocaleString("ar-EG") : "---";

  // قسم تخصيص الدليفري — يظهر فقط لطلبات الأونلاين نوع delivery
  const isOnlineDelivery =
    source === "online" &&
    order.order_type === "delivery" &&
    order.order_status !== "cancelled";
  const deliveryAssignSection = isOnlineDelivery
    ? `
    <div id="od_delivery_section" style="
      margin:20px 0 4px; background:rgba(201,168,76,0.06);
      border:1px solid rgba(201,168,76,0.25); border-radius:12px; padding:16px;
    ">
      <div style="display:flex; align-items:center; gap:8px; margin-bottom:12px;">
        <svg width="16" height="16" fill="none" stroke="var(--color-primary)" stroke-width="2" viewBox="0 0 24 24">
          <rect x="1" y="3" width="15" height="13" rx="2"/><path d="M16 8h4l3 3v5h-7V8z"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/>
        </svg>
        <span style="color:var(--color-primary); font-size:14px; font-weight:700;">تخصيص الدليفري ورسوم التوصيل</span>
      </div>
      <div id="od_delivery_body">
        <p style="color:var(--color-subtext);font-size:13px;text-align:center;">جاري تحميل المناديب...</p>
      </div>
    </div>
  `
    : "";

  overlay.innerHTML = `
    <div style="background:var(--color-bg); border:1px solid var(--color-primary); border-radius:16px; width:680px; max-width:95vw; max-height:92vh; display:flex; flex-direction:column; box-shadow:0 20px 60px rgba(0,0,0,0.5); position:relative; overflow:hidden;">
      <button onclick="document.getElementById('order_detail_overlay').remove()" style="position:absolute; left:20px; top:20px; background:none; border:none; color:var(--color-subtext); font-size:24px; cursor:pointer; z-index:10;">&times;</button>
      
      <div style="padding:32px; overflow-y:auto; scrollbar-gutter:stable;">
        <div style="text-align:center; margin-bottom:24px; border-bottom:1px solid rgba(201,168,76,0.2); padding-bottom:16px;">
          <h2 style="color:var(--color-primary); margin-bottom:8px;">تفاصيل الطلب #${order.order_number || order.id}</h2>
          <span class="order_status ${statusObj.cls}">${statusObj.label}</span>
          <div style="display:flex; justify-content:center; gap:20px; margin-top:12px; font-size:12px;">
            <div style="color:var(--color-subtext);">
              <span style="opacity:0.7;">تاريخ الإنشاء:</span>
              <span style="font-weight:700; margin-right:4px;">${createdAtStr}</span>
            </div>
            ${modificationHtml}
          </div>
        </div>

        <div class="order_detail_info_grid">
          <div class="info_group">
            <h4>العميل</h4>
            <p>${order.customer_name || "عميل نقدي"}</p>
          </div>
          <div class="info_group">
            <h4>الهاتف</h4>
            <p>${order.customer_phone || "---"}</p>
          </div>
          <div class="info_group">
            <h4>نوع الطلب</h4>
            <p>${typeLabels[order.order_type] || order.order_type}</p>
          </div>
          <div class="info_group">
            <h4>العنوان</h4>
            <p>${
              typeof order.address === "object" && order.address !== null
                ? order.address.address
                : order.customer_address ||
                  order.address ||
                  "---"
            }</p>
          </div>
          ${
            order.delivery_person_name
              ? `
          <div class="info_group">
            <h4 style="color:var(--color-primary)">المندوب المخصص</h4>
            <p style="font-weight:bold; color:var(--color-primary)">${order.delivery_person_name}</p>
          </div>`
              : ""
          }
          ${
            order.customer_notes
              ? `
          <div class="info_group" style="grid-column: 1 / -1;">
            <h4>ملاحظات</h4>
            <p>${order.customer_notes}</p>
          </div>`
              : ""
          }
        </div>

        ${deliveryAssignSection}

        <table class="order_detail_table">
          <thead>
            <tr>
              <th>الصنف</th>
              <th>الكمية</th>
              <th>السعر</th>
              <th>الإجمالي</th>
            </tr>
          </thead>
          <tbody>
            ${itemsHtml}
          </tbody>
        </table>

        <div class="order_detail_summary">
          <div class="summary_row">
            <span>إجمالي الأصناف:</span>
            <span id="od_items_total">${itemsTotal.toFixed(2)} ج.م</span>
          </div>
          <div class="summary_row">
            <span>خدمة التوصيل:</span>
            <span id="od_delivery_fee">${deliveryFee.toFixed(2)} ج.م</span>
          </div>
          ${
            order.discount_amount && parseFloat(order.discount_amount) > 0
              ? `
          <div class="summary_row" style="color: #e74c3c;">
            <span>الخصم${order.discount_reason ? ` (${order.discount_reason})` : ""}:</span>
            <span>- ${parseFloat(order.discount_amount).toFixed(2)} ج.م</span>
          </div>
              `
              : ""
          }
          <div class="summary_row total">
            <span>الإجمالي الكلي:</span>
            <span id="od_grand_total">${parseFloat(order.total_amount).toFixed(2)} ج.م</span>
          </div>
        </div>
        
        ${
          order.modifications && order.modifications.length > 0
            ? `
        <div style="margin-top: 24px; padding: 16px; background: rgba(243, 156, 18, 0.05); border: 1px solid rgba(243, 156, 18, 0.2); border-radius: 8px;">
          <h4 style="color: #f39c12; margin-bottom: 12px; font-size: 14px; display: flex; align-items: center; gap: 8px;">
            <i class="fa-solid fa-clock-rotate-left"></i> سجل التعديلات
          </h4>
          <div style="display: flex; flex-direction: column; gap: 12px;">
            ${order.modifications.map(mod => `
              <div style="font-size: 12px; border-right: 2px solid #f39c12; padding-right: 12px;">
                <div style="color: var(--color-subtext); margin-bottom: 4px;">
                  <span style="font-weight: 700; color: var(--color-text);">${new Date(mod.changed_at).toLocaleString("ar-EG")}</span>
                </div>
                <ul style="margin: 0; padding-right: 16px; color: var(--color-text);">
                  ${mod.changes.map(c => `<li>${c}</li>`).join("")}
                </ul>
              </div>
            `).join("")}
          </div>
        </div>
            `
            : ""
        }



        <div style="margin-top:24px; display:flex; flex-direction:column; gap:12px;">
          <div style="display:flex; justify-content:center; gap:12px;">
            ${
              order.order_status === "new"
                ? `
              <button id="od_accept_btn" onclick="acceptOrderFromModal(${order.id}, '${source}')" style="background:var(--color-primary); color:#000; border:none; padding:6px 12px; border-radius:6px; font-weight:bold; cursor:pointer; font-family:Cairo,sans-serif; font-size:12px;"> قبول الطلب</button>
            `
                : ""
            }
            
            ${
              order.order_status !== "cancelled"
                ? `
              <button onclick="document.getElementById('order_detail_overlay').remove(); if('${source}'==='online') printOrderFromOnline(${order.id}); else printOrderFromList(${order.id});" style="background:#5c5c5c; color:#fff; border:none; padding:10px 24px; border-radius:8px; font-weight:bold; cursor:pointer; font-family:Cairo,sans-serif; font-size:13px;">🖨 طباعة</button>
            `
                : ""
            }
            
            <button onclick="document.getElementById('order_detail_overlay').remove()" style="background:rgba(255,255,255,0.08); color:var(--color-subtext); border:1px solid rgba(255,255,255,0.1); padding:10px 24px; border-radius:8px; font-weight:bold; cursor:pointer; font-family:Cairo,sans-serif; font-size:13px;">إغلاق</button>
          </div>
        </div>
      </div>
    </div>
  `;

  document.body.appendChild(overlay);
  overlay.onclick = (e) => {
    if (e.target === overlay) overlay.remove();
  };

  // إذا كان طلب أونلاين دليفري → حمّل قائمة المناديب
  if (isOnlineDelivery) {
    loadDeliveryRidersForModal(order);
  }
}

// ===================================================
//  Accept Order from Modal (new → confirmed)
// ===================================================
async function acceptOrderFromModal(orderId, source) {
  const btn = document.getElementById("od_accept_btn");
  if (!btn) return;

  // حالة تحميل
  btn.disabled = true;
  btn.style.opacity = "0.7";
  btn.style.cursor = "not-allowed";
  btn.innerHTML = `
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
      style="animation:spinLoader 0.8s linear infinite;">
      <path d="M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0" stroke-linecap="round"/>
    </svg>
    جاري القبول...
  `;

  try {
    const res = await apiFetch(`/orders/${orderId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ order_status: "confirmed" }),
    });

    if (!res.ok) throw new Error("فشل تحديث الحالة");

    // ✅ تحديث الـ badge داخل المودال
    const statusBadge = document.querySelector(
      "#order_detail_overlay .order_status",
    );
    if (statusBadge) {
      statusBadge.textContent = "مؤكد";
      statusBadge.className = "order_status badge_ready";
    }

    // ✅ استبدال زرار "قبول الطلب" برسالة نجاح
    btn.outerHTML = `
      <div style="
        width:100%; padding:14px; border-radius:10px;
        background:rgba(29,92,43,0.25); border:1px solid rgba(35,128,56,0.5);
        display:flex; align-items:center; justify-content:center; gap:10px;
        font-family:Cairo,sans-serif; font-size:15px; font-weight:700; color:#3d9e6b;
      ">
        <svg width="20" height="20" fill="none" stroke="#3d9e6b" stroke-width="2.5" viewBox="0 0 24 24">
          <polyline points="20 6 9 17 4 12"/>
        </svg>
        تم قبول الطلب بنجاح — الحالة: مؤكد
      </div>
    `;

    // ✅ Update local memory state so re-renders use fresh data
    const updateInList = (list) => {
      const idx = list.findIndex((o) => String(o.id) === String(orderId));
      if (idx !== -1) {
        list[idx] = { ...list[idx], order_status: "confirmed" };
      }
    };
    updateInList(onlineOrdersList);
    if (typeof allOrdersList !== "undefined") updateInList(allOrdersList);

    // تحديث القائمة في الخلفية
    if (source === "online") {
      updateOnlineStats();
      renderOnlineOrders();
    } else {
      renderAllOrders();
    }

    showToast("تم قبول الطلب بنجاح ✓", "success");
  } catch (err) {
    console.error(err);
    btn.disabled = false;
    btn.style.opacity = "1";
    btn.style.cursor = "pointer";
    btn.innerHTML = `
      <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
        <polyline points="20 6 9 17 4 12"/>
      </svg>
      قبول الطلب
    `;
    showToast("حدث خطأ أثناء قبول الطلب", "error");
  }
}

// ===================================================
//  Delivery Assignment (Online Orders Modal)
// ===================================================
async function loadDeliveryRidersForModal(order) {
  const body = document.getElementById("od_delivery_body");
  if (!body) return;

  try {
    let riders = _deliveryRidersCache;
    if (!riders) {
      const res = await apiFetch("/user/users/delivery", { suppress401: true });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const users = await res.json();
      riders = Array.isArray(users)
        ? users.filter((u) => u.role === "delivery" && u.is_active)
        : [];
      _deliveryRidersCache = riders;
    }
    renderRidersInModal(body, order, riders);
  } catch (err) {
    body.innerHTML = `<p style="color:#e40411;font-size:12px;text-align:center;">لا يمكن تحميل قائمة المناديب</p>`;
  }
}

function renderRidersInModal(body, order, riders) {
  // ✅ NEW: If delivery person is already assigned, show the success state immediately
  if (order.delivery_person_id) {
    const riderName = order.delivery_person_name || "تم التخصيص";
    const fee = parseFloat(order.delivery_fee || 0);

    body.innerHTML = `
      <div style="display:flex; align-items:center; gap:10px; padding:12px;
        background:rgba(29,92,43,0.15); border:1px solid rgba(35,128,56,0.3); border-radius:10px;">
        <svg width="20" height="20" fill="none" stroke="#3d9e6b" stroke-width="2.5" viewBox="0 0 24 24">
          <polyline points="20 6 9 17 4 12"/>
        </svg>
        <div>
          <p style="color:#3d9e6b; font-size:14px; font-weight:700; margin:0;">تم التخصيص مسبقاً ✓</p>
          <p style="color:var(--color-subtext); font-size:13px; margin:4px 0 0 0;">
            المندوب: <strong style="color:var(--color-text);">${riderName}</strong> —
            الرسوم: <strong style="color:var(--color-primary);">${fee.toFixed(2)} ج.م</strong>
          </p>
        </div>
        <button 
          onclick="this.parentElement.parentElement.innerHTML = \`<p style='color:var(--color-subtext);font-size:13px;text-align:center;'>جاري تحميل القائمة...</p>\`; loadDeliveryRidersForModal({...onlineOrdersList.find(o=>o.id===${order.id}), delivery_person_id: null});"
          style="margin-right:auto; background:none; border:none; color:var(--color-primary); font-size:11px; cursor:pointer; text-decoration:underline;">
          تغيير
        </button>
      </div>
    `;
    return;
  }

  if (!riders || riders.length === 0) {
    body.innerHTML = `<p style="color:var(--color-subtext);font-size:13px;text-align:center;">لا يوجد مناديب متاحين</p>`;
    return;
  }

  const orderId = order.id;
  body.innerHTML = `
    <p style="color:var(--color-subtext);font-size:12px;margin-bottom:10px;">اختر المندوب:</p>
    <div style="display:flex; flex-wrap:wrap; gap:8px;">
      ${riders
        .map(
          (r) => `
        <button
          onclick="showFeeSelectorInModal(${r.id}, '${(r.full_name || r.username).replace(/'/g, "\\'")}', ${orderId})"
          style="background:rgba(201,168,76,0.1); border:1px solid rgba(201,168,76,0.3); color:var(--color-text);
            border-radius:8px; padding:7px 14px; font-family:Cairo,sans-serif; font-size:13px; cursor:pointer;
            transition:all 0.2s;"
          onmouseover="this.style.background='rgba(201,168,76,0.25)'"
          onmouseout="this.style.background='rgba(201,168,76,0.1)'"
        >${r.full_name || r.username}</button>
      `,
        )
        .join("")}
    </div>
  `;
}

function showFeeSelectorInModal(riderId, riderName, orderId) {
  const body = document.getElementById("od_delivery_body");
  if (!body) return;

  const fees = [
    0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95,
    100,
  ];

  body.innerHTML = `
    <div style="display:flex; align-items:center; gap:8px; margin-bottom:10px;">
      <button
        onclick="loadDeliveryRidersForModal(onlineOrdersList.find(o=>o.id===${orderId}))"
        style="background:transparent; border:none; color:var(--color-subtext);
          font-family:Cairo,sans-serif; font-size:12px; cursor:pointer; padding:0;">
        ← رجوع
      </button>
      <span style="color:var(--color-primary); font-size:13px; font-weight:700;">${riderName}</span>
    </div>
    <p style="color:var(--color-subtext);font-size:12px;margin-bottom:8px;">اختر رسوم التوصيل:</p>
    <div style="display:grid; grid-template-columns:repeat(4,1fr); gap:8px;">
      ${fees
        .map(
          (fee) => `
        <button
          onclick="assignDeliveryToOnlineOrder(${orderId}, ${riderId}, '${riderName}', ${fee})"
          class="delivery_fee_btn"
          style="font-size:13px; padding:8px 4px;"
        >${fee} ج.م</button>
      `,
        )
        .join("")}
    </div>
  `;
}

async function assignDeliveryToOnlineOrder(orderId, riderId, riderName, fee) {
  const body = document.getElementById("od_delivery_body");
  if (body)
    body.innerHTML = `<p style="color:var(--color-subtext);font-size:13px;text-align:center;">جاري الحفظ...</p>`;

  try {
    const resFull = await apiFetch(`/orders/${orderId}`, {
      method: "PATCH",
      body: JSON.stringify({
        delivery_person_id: riderId,
        delivery_fee: parseFloat(fee),
      }),
    });
    if (!resFull.ok) throw new Error("فشل تحديث بيانات التوصيل");

    const resStatus = await apiFetch(`/orders/${orderId}/status`, {
      method: "PATCH",
      body: JSON.stringify({
        order_status: "confirmed",
      }),
    });
    if (!resStatus.ok) throw new Error("فشل تحديث الحالة");

    // تحديث الأرقام في السامري داخل المودال
    const feeEl = document.getElementById("od_delivery_fee");
    const itemsTotEl = document.getElementById("od_items_total");
    const grandEl = document.getElementById("od_grand_total");

    const itemsAmt = parseFloat(itemsTotEl ? itemsTotEl.textContent : 0) || 0;
    if (feeEl) feeEl.textContent = fee.toFixed(2) + " ج.م";
    if (grandEl) grandEl.textContent = (itemsAmt + fee).toFixed(2) + " ج.م";

    // ✅ Update local memory state so re-renders/re-opens use fresh data
    const updateInList = (list) => {
      const idx = list.findIndex((o) => String(o.id) === String(orderId));
      if (idx !== -1) {
        list[idx] = {
          ...list[idx],
          order_status: "confirmed",
          delivery_person_id: riderId,
          delivery_person_name: riderName,
          delivery_fee: fee,
        };
      }
    };
    updateInList(onlineOrdersList);
    if (typeof allOrdersList !== "undefined") updateInList(allOrdersList);

    // ✅ Update modal header badge to confirmed
    const statusBadge = document.querySelector(
      "#order_detail_overlay .order_status",
    );
    if (statusBadge) {
      statusBadge.textContent = "مؤكد";
      statusBadge.className = "order_status badge_ready";
    }

    if (body)
      body.innerHTML = `
      <div style="display:flex; align-items:center; gap:10px; padding:10px;
        background:rgba(29,92,43,0.2); border:1px solid rgba(35,128,56,0.4); border-radius:8px;">
        <svg width="18" height="18" fill="none" stroke="#3d9e6b" stroke-width="2.5" viewBox="0 0 24 24">
          <polyline points="20 6 9 17 4 12"/>
        </svg>
        <div>
          <p style="color:#3d9e6b; font-size:13px; font-weight:700; margin:0;">تم التخصيص بنجاح ✓</p>
          <p style="color:var(--color-subtext); font-size:12px; margin:2px 0 0 0;">
            المندوب: <strong style="color:var(--color-text);">${riderName}</strong> —
            الرسوم: <strong style="color:var(--color-primary);">${fee} ج.م</strong>
          </p>
        </div>
      </div>
    `;

    updateOnlineStats();
    const oIdx = onlineOrdersList.findIndex((o) => String(o.id) === String(orderId));
    if (oIdx !== -1) {
      window.updateOrAddOnlineOrderDOM(onlineOrdersList[oIdx]);
    }
    if (typeof allOrdersList !== "undefined") {
      const aIdx = allOrdersList.findIndex((o) => String(o.id) === String(orderId));
      if (aIdx !== -1) {
        window.updateOrAddAllOrderDOM(allOrdersList[aIdx]);
      }
    }
    showToast(`تم تخصيص ${riderName} برسوم ${fee} ج.م`, "success");
  } catch (err) {
    console.error(err);
    if (body)
      body.innerHTML = `<p style="color:#e40411;font-size:13px;text-align:center;">حدث خطأ أثناء الحفظ. حاول مرة أخرى.</p>`;
    showToast("حدث خطأ أثناء تخصيص الدليفري", "error");
  }
}

// ===================================================
//  Edit Order Details In Modal (Workaround for patches)
// ===================================================
let editModalState = {
  originalOrder: null,
  cart: [],
  activeCatId: null,
  sourceList: "",
  orderType: null,
  selectedDelivery: null,
  selectedDeliveryFee: null,
  selectedDineInFee: null,
  customerName: "",
  customerPhone: "",
  customerAddress: "",
};

function openEditOrderModal(orderId, sourceList) {
  const list = sourceList === "online" ? onlineOrdersList : allOrdersList;
  const order = list.find((o) => o.id === orderId);

  if (!order) {
    showToast("لا يمكن العثور على الطلب!", "error");
    return;
  }

  // إغلاق تفاصيل الطلب العادية إن كانت مفتوحة
  const detailOverlay = document.getElementById("order_detail_overlay");
  if (detailOverlay) detailOverlay.remove();

  editModalState.originalOrder = order;
  editModalState.activeCatId = categories.length > 0 ? categories[0].id : null;
  editModalState.sourceList = sourceList;

  // Initialize order type and fees for the "mini cashier"
  editModalState.orderType =
    order.order_type === "hall" ? "dine_in" : order.order_type;
  editModalState.selectedDelivery = order.delivery_person_id
    ? { id: order.delivery_person_id, name: order.delivery_person_name }
    : null;

  if (editModalState.orderType === "delivery") {
    editModalState.selectedDeliveryFee = parseFloat(order.delivery_fee) || 0;
    editModalState.selectedDineInFee = null;
  } else if (editModalState.orderType === "dine_in") {
    editModalState.selectedDineInFee = parseFloat(order.delivery_fee) || 0;
    editModalState.selectedDeliveryFee = null;
    editModalState.selectedDelivery = null;
  } else {
    editModalState.selectedDeliveryFee = null;
    editModalState.selectedDineInFee = null;
    editModalState.selectedDelivery = null;
  }

  // Initialize customer info for editing
  editModalState.customerName = order.customer_name || "";
  editModalState.customerPhone = normalizePhoneDigits(order.customer_phone || "");
  editModalState.customerAddress =
    typeof order.address === "object" && order.address !== null
      ? order.address.address
      : getOrderAddressText(order);

  editModalState.discountType = order.discount_type || "";
  editModalState.discountValue = parseFloat(order.discount_value) || 0;
  editModalState.discountReason = order.discount_reason || "";

  editModalState.cart = (order.items || []).map((item) => {
    let prod = products.find((p) => p.id === item.product_id);
    let name = prod ? prod.product_name : `صنف #${item.product_id}`;
    let hasVariant = false;
    if (prod && prod.variants) {
      let v = prod.variants.find(
        (v) => parseFloat(v.price) === parseFloat(item.unit_price),
      );
      if (v) {
        name = prod.product_name + " - " + v.name;
        hasVariant = true;
      }
    }
    return {
      qty: parseInt(item.quantity) || 1,
      item: {
        id: hasVariant
          ? item.product_id + "_" + Date.now() + Math.random()
          : item.product_id, // we might need variant ID strictly later if applicable, but currently variants are matched by price
        originalProductId: item.product_id,
        name: name,
        price: parseFloat(item.unit_price),
      },
    };
  });

  renderEditOrderModal();
}

function renderEditOrderModal() {
  let oldModal = document.getElementById("edit_order_modal_overlay");
  if (oldModal) oldModal.remove();

  const overlay = document.createElement("div");
  overlay.id = "edit_order_modal_overlay";
  overlay.style.cssText = `
    position:fixed; inset:0; background:rgba(0,0,0,0.4);
    display:flex; align-items:center; justify-content:center; z-index:11000; padding: 20px;
  `;

  overlay.innerHTML = `
    <div style="background:var(--color-bg); width:90vw; max-width:1150px; height:85vh; border-radius:16px; border:1px solid var(--color-primary); display:flex; flex-direction:column; overflow:hidden; position:relative; direction:rtl; box-shadow:0 10px 40px rgba(0,0,0,0.5);">
      
      <!-- Modal Navigation Header (Mirroring Navbar theme) -->
      <div style="display:flex; align-items:center; justify-content:space-between; padding:12px 32px; background:linear-gradient(180deg, #c79a4a 0%, #7a4f1a 100%); direction:rtl;">
        <div style="display:flex; align-items:center; gap:12px;">
          <img src="/assets/توب شيف 1@2x.png" style="width:40px; height:40px; object-fit:contain;" />
          <h2 style="color:var(--color-bg); margin:0; font-size:18px; font-weight:900;">تعديل الطلب #${editModalState.originalOrder.order_number || editModalState.originalOrder.id}</h2>
        </div>
        <button onclick="document.getElementById('edit_order_modal_overlay').remove()" style="background:var(--color-bg); border:none; color:var(--color-primary); width:32px; height:32px; border-radius:50%; font-size:20px; font-weight:900; cursor:pointer; display:flex; align-items:center; justify-content:center;display:flex; align-items:center; justify-content:center">&times;</button>
      </div>

      <!-- Main Layout Mirror -->
      <div class="main_layout" style="flex:1; height:auto; padding:20px; overflow:hidden; gap:16px;">
        
        <!-- Right Section: Categories & Products Grid -->
        <div class="right_section" style="flex:1; overflow:hidden; display:flex; flex-direction:column;">
          <div class="category_tabs" id="edit_modal_cat_tabs" style="margin-bottom:16px; flex-wrap:wrap; padding-bottom:4px;"></div>
          <div class="items_grid" id="edit_modal_items_grid" style="flex:1; padding:4px;"></div>
        </div>

        <!-- Left Section: Cart (Total Container) -->
        <div class="total_container" id="edit_modal_cart_container" style="height:100%; display:flex; flex-direction:column; overflow:hidden;">
          <div class="total_header" style="flex-shrink:0;">
            <h1>ملخص التعديل</h1>
          </div>
          
          <div style="flex:1; overflow-y:auto; padding:0 0 10px 0;">
            <!-- Mini Customer Info Card (Matching Cashier Style) -->
            <div id="edit_modal_customer_form" style="padding: 0 16px; margin-bottom: 12px; display: ${editModalState.orderType ? "block" : "none"};">
               <div class="delivery_customer_card" style="margin-top: 0; box-shadow: none; border: 1px solid rgba(201,168,76,0.2);">
                  <div class="dcf_title" id="edit_modal_dcf_title">
                     <div style="display:flex; align-items:center; gap:6px;">
                        <svg width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                           <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
                        </svg>
                        <span>${editModalState.orderType === "delivery" ? "تعديل بيانات عميل الديليفري" : "تعديل بيانات العميل (اختياري)"}</span>
                     </div>
                     <button class="dcf_close_btn" onclick="clearOrderTypeInEditModal()" title="إغلاق وإلغاء نوع الطلب">✕</button>
                  </div>
                  <div class="dcf_field">
                     <span class="dcf_label">📞 رقم التليفون</span>
                     <input type="tel" class="dcf_input" placeholder="01xxxxxxxxx" maxlength="11" 
                        value="${editModalState.customerPhone}" 
                        oninput="editModalState.customerPhone = normalizePhoneDigits(this.value); this.value = editModalState.customerPhone" />
                  </div>
                  <div class="dcf_field">
                     <span class="dcf_label">👤 الاسم</span>
                     <input type="text" class="dcf_input" placeholder="اسم العميل" 
                        value="${editModalState.customerName}" 
                        oninput="editModalState.customerName = this.value" />
                  </div>
                  <div class="dcf_field">
                     <span class="dcf_label">📍 العنوان</span>
                     <input type="text" class="dcf_input" placeholder="العنوان بالتفصيل" 
                        value="${editModalState.customerAddress}" 
                        oninput="editModalState.customerAddress = this.value" />
                  </div>
               </div>
            </div>
            
            <div class="total_cards" id="edit_modal_cart_list" style="padding:0 16px;"></div>

            <!-- Edit Discount Section -->
            <div id="edit_modal_discount_form" style="border-top: 1px solid rgba(201, 168, 76, 0.3); padding: 12px 14px; flex-shrink: 0; margin-bottom: 8px;">
              <div class="dcf_title" style="margin-bottom: 8px;">
                <i class="fa-solid fa-tags"></i>
                <span>تعديل الخصم</span>
              </div>
              <div class="delivery_customer_card">
                <div style="display:flex; gap:8px;">
                  <select id="edit_modal_discount_type" class="dcf_select" style="flex:1;" onchange="editModalState.discountType = this.value; updateEditModalGrandTotal()">
                    <option value="" ${!editModalState.discountType ? "selected" : ""}>بدون خصم</option>
                    <option value="fixed" ${editModalState.discountType === "fixed" ? "selected" : ""}>مبلغ ثابت</option>
                    <option value="percentage" ${editModalState.discountType === "percentage" ? "selected" : ""}>نسبة مئوية (%)</option>
                  </select>
                  <input type="number" id="edit_modal_discount_value" class="dcf_input" style="flex:1;" placeholder="القيمة" min="0" step="0.01" value="${editModalState.discountValue || ""}" oninput="editModalState.discountValue = parseFloat(this.value) || 0; updateEditModalGrandTotal()">
                </div>
                <input type="text" id="edit_modal_discount_reason" class="dcf_input" placeholder="سبب الخصم (اختياري)" value="${editModalState.discountReason || ""}" oninput="editModalState.discountReason = this.value">
              </div>
            </div>
          </div>

          <div class="total_footer" style="flex-shrink:0;">
            <!-- Badge نوع الطلب -->
            <div id="edit_modal_order_type_badge" class="order_type_badge" style="display: none; margin-bottom: 8px;"></div>

            <!-- زراير نوع الطلب -->
            <div id="edit_modal_order_type_btns" class="order_type_btns" style="margin-bottom: 8px;"></div>

            <div class="total_sum">
              <h1>إجمالي الأصناف الكاشير:</h1>
              <h2 id="edit_modal_items_total">0 ج.م</h2>
            </div>
            <div class="footer_btns">
               <button class="btn_confirm" onclick="updateEditOrderConfirm()">حفظ التعديلات</button>
               <button class="btn_cancel" onclick="document.getElementById('edit_order_modal_overlay').remove()">إلغاء</button>
            </div>
          </div>
        </div>

      </div>
      
      <!-- Sub-modal container for delivery/dine-in selection -->
      <div id="edit_modal_sub_container" class="delivery_modal_container" style="display: none; z-index: 12000; position: absolute; inset: 0;"></div>
    </div>
  `;
  document.body.appendChild(overlay);

  renderEditModalCategories();
  renderEditModalItems();
  renderEditModalCart();
  renderEditModalOrderTypeButtons();
  renderEditModalOrderTypeBadge();
}

// --------------------------- Edit Modal Mini Cashier Logic ---------------------------

function renderEditModalOrderTypeButtons() {
  const container = document.getElementById("edit_modal_order_type_btns");
  if (!container) return;
  container.innerHTML = "";

  ORDER_TYPES.forEach((t) => {
    const btn = document.createElement("button");
    const isActive = editModalState.orderType === t.key;
    btn.className = "order_type_btn" + (isActive ? " active" : "");
    btn.textContent = t.label;
    btn.onclick = () => selectOrderTypeInEditModal(t.key);
    container.appendChild(btn);
  });
}

function renderEditModalOrderTypeBadge() {
  const badge = document.getElementById("edit_modal_order_type_badge");
  if (!badge) return;

  if (!editModalState.orderType) {
    badge.style.display = "none";
    badge.innerHTML = "";
    return;
  }

  badge.style.display = "flex";

  if (
    editModalState.orderType === "delivery" &&
    editModalState.selectedDelivery &&
    hasFeeValue(editModalState.selectedDeliveryFee)
  ) {
    badge.innerHTML = `
      <span class="badge_icon"></span>
      <span class="badge_name" style="cursor:pointer" onclick="showEditModalCustomerForm()">${editModalState.selectedDelivery.name}</span>
      <span class="badge_fee">رسوم توصيل: ${formatFeeValue(editModalState.selectedDeliveryFee)}</span>
      <button class="badge_clear" onclick="clearOrderTypeInEditModal()">✕</button>
    `;
  } else if (editModalState.orderType === "takeaway") {
    badge.innerHTML = `
      <span class="badge_icon"></span>
      <span class="badge_name" style="cursor:pointer" onclick="showEditModalCustomerForm()">تيك اواي</span>
      <button class="badge_clear" onclick="clearOrderTypeInEditModal()">✕</button>
    `;
  } else if (editModalState.orderType === "dine_in") {
    badge.innerHTML = `
      <span class="badge_icon"></span>
      <span class="badge_name" style="cursor:pointer" onclick="showEditModalCustomerForm()">صالة</span>
      ${hasFeeValue(editModalState.selectedDineInFee) ? `<span class="badge_fee">رسوم خدمة: ${formatFeeValue(editModalState.selectedDineInFee)}</span>` : ""}
      <button class="badge_clear" onclick="clearOrderTypeInEditModal()">✕</button>
    `;
  } else if (editModalState.orderType === "delivery") {
    badge.innerHTML = `
      <span class="badge_icon"></span>
      <span class="badge_name" style="color:var(--color-subtext);font-size:12px;cursor:pointer" onclick="showEditModalCustomerForm()">لم يتم اختيار الدليفري بعد (اضغط للإكمال)</span>
      <button class="badge_clear" onclick="clearOrderTypeInEditModal()">✕</button>
    `;
  }
}

function clearOrderTypeInEditModal() {
  editModalState.selectedDelivery = null;
  editModalState.selectedDeliveryFee = null;
  editModalState.selectedDineInFee = null;
  editModalState.orderType = null;

  const customerForm = document.getElementById("edit_modal_customer_form");
  if (customerForm) customerForm.style.display = "none";

  renderEditModalOrderTypeBadge();
  renderEditModalOrderTypeButtons();
  renderEditModalCart();
}

function selectOrderTypeInEditModal(type) {
  const customerForm = document.getElementById("edit_modal_customer_form");
  if (customerForm) {
    customerForm.style.display = "block";
    const title = document.getElementById("edit_modal_dcf_title");
    if (title) {
      title.innerHTML = `
         <div style="display:flex; align-items:center; gap:6px;">
           <svg width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
             <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
           </svg>
           <span>${type === "delivery" ? "تعديل بيانات عميل الديليفري" : "تعديل بيانات العميل (اختياري)"}</span>
         </div>
         <button class="dcf_close_btn" onclick="hideEditModalCustomerForm()" title="إغلاق البيانات مؤقتاً">✕</button>
       `;
    }
  }

  if (type === "delivery") {
    showDeliveryModalInEditModal();
  } else if (type === "dine_in") {
    showDineInFeeSelectorInEditModal();
  } else {
    editModalState.orderType = type;
    editModalState.selectedDelivery = null;
    editModalState.selectedDeliveryFee = null;
    editModalState.selectedDineInFee = null;
    renderEditModalOrderTypeBadge();
    renderEditModalOrderTypeButtons();
    renderEditModalCart();
  }
}

async function showDeliveryModalInEditModal() {
  const container = document.getElementById("edit_modal_sub_container");
  if (!container) return;

  container.style.display = "flex";
  container.innerHTML = `
    <div class="delivery_modal">
      <div class="delivery_modal_header">
        <h2>اختر الدليفري (تعديل)</h2>
        <button class="delivery_modal_close" onclick="closeEditModalSub()">✕</button>
      </div>
      <div class="delivery_modal_body" id="edit_modal_delivery_names_list">
        <p style="color:var(--color-subtext);text-align:center;font-size:13px">جاري التحميل...</p>
      </div>
    </div>
  `;

  try {
    let riders = _deliveryRidersCache;
    if (!riders) {
      const res = await apiFetch("/user/users/delivery", { suppress401: true });
      if (!res.ok) throw new Error(`HTTP error: ${res.status}`);
      const users = await res.json();
      riders = Array.isArray(users)
        ? users.filter((u) => u.role === "delivery" && u.is_active)
        : [];
      _deliveryRidersCache = riders;
    }
    renderDeliveryNamesInEditModal(riders);
  } catch (err) {
    console.error("خطأ في جلب الدليفري:", err);
    const list = document.getElementById("edit_modal_delivery_names_list");
    if (list)
      list.innerHTML = `<p style="color:#e40411;text-align:center;font-size:12px;padding:10px">فشل تحميل المناديب</p>`;
  }
}

function renderDeliveryNamesInEditModal(riders) {
  const list = document.getElementById("edit_modal_delivery_names_list");
  if (!list) return;

  if (!riders || riders.length === 0) {
    list.innerHTML = `<p style="color:var(--color-subtext);text-align:center;font-size:13px">لا يوجد دليفري متاح</p>`;
    return;
  }

  list.innerHTML = "";
  riders.forEach((r) => {
    const btn = document.createElement("button");
    btn.className = "delivery_name_btn";
    btn.textContent = r.full_name || r.username;
    btn.onclick = () =>
      showDeliveryFeeSelectorInEditModal({
        id: r.id,
        name: r.full_name || r.username,
      });
    list.appendChild(btn);
  });
}

function showDeliveryFeeSelectorInEditModal(rider) {
  const list = document.getElementById("edit_modal_delivery_names_list");
  if (!list) return;

  const fees = [
    0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95,
    100,
  ];

  list.innerHTML = `
    <button onclick="showDeliveryModalInEditModal()" style="
      background:transparent;border:none;color:var(--color-subtext);
      font-family:Cairo,sans-serif;font-size:13px;cursor:pointer;
      display:flex;align-items:center;gap:4px;margin-bottom:8px;padding:0;
    ">← رجوع</button>
    <p style="color:var(--color-primary);font-size:14px;font-weight:700;text-align:center;margin-bottom:12px">${rider.name}</p>
    <p style="color:var(--color-subtext);font-size:12px;text-align:center;margin-bottom:10px">اختر رسوم التوصيل</p>
  `;

  const grid = document.createElement("div");
  grid.style.cssText =
    "display:grid;grid-template-columns:repeat(4,1fr);gap:8px;";

  fees.forEach((fee) => {
    const btn = document.createElement("button");
    btn.className = "delivery_fee_btn";
    btn.textContent = `${fee} ج.م`;
    btn.onclick = () => {
      editModalState.selectedDelivery = { id: rider.id, name: rider.name };
      editModalState.selectedDeliveryFee = Number(fee);
      editModalState.orderType = "delivery";
      closeEditModalSub();
      renderEditModalOrderTypeBadge();
      renderEditModalOrderTypeButtons();
      renderEditModalCart();
    };
    grid.appendChild(btn);
  });

  list.appendChild(grid);
}

function showDineInFeeSelectorInEditModal() {
  const container = document.getElementById("edit_modal_sub_container");
  if (!container) return;

  const fees = [
    0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95,
    100,
  ];

  container.style.display = "flex";
  container.innerHTML = `
    <div class="delivery_modal">
      <div class="delivery_modal_header">
        <h2>رسوم الصالة (تعديل)</h2>
        <button class="delivery_modal_close" onclick="closeEditModalSub()">✕</button>
      </div>
      <div class="delivery_modal_body">
        <p style="color:var(--color-subtext);font-size:13px;text-align:center;margin-bottom:16px">اختر قيمة رسوم الخدمة</p>
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;">
          ${fees
            .map(
              (fee) => `
            <button class="delivery_fee_btn" onclick="selectDineInFeeInEditModal(${fee})">${fee} ج.م</button>
          `,
            )
            .join("")}
          <button class="delivery_fee_btn" onclick="selectDineInFeeInEditModal(0)" style="background:rgba(255,255,255,0.05);color:var(--color-subtext)">بدون</button>
        </div>
      </div>
    </div>
  `;
}

function selectDineInFeeInEditModal(fee) {
  editModalState.selectedDineInFee = Number(fee);
  editModalState.selectedDeliveryFee = null;
  editModalState.selectedDelivery = null;
  editModalState.orderType = "dine_in";
  closeEditModalSub();
  renderEditModalOrderTypeBadge();
  renderEditModalOrderTypeButtons();
  renderEditModalCart();
}

function closeEditModalSub() {
  const container = document.getElementById("edit_modal_sub_container");
  if (container) {
    container.style.display = "none";
    container.innerHTML = "";
  }
}

function hideEditModalCustomerForm() {
  const el = document.getElementById("edit_modal_customer_form");
  if (el) el.style.display = "none";
}

function showEditModalCustomerForm() {
  const el = document.getElementById("edit_modal_customer_form");
  if (el) el.style.display = "block";
}

// --------------------------- Edit Modal Cat & Items ---------------------------
function renderEditModalCategories() {
  const container = document.getElementById("edit_modal_cat_tabs");
  if (!container) return;
  container.innerHTML = "";

  categories.forEach((cat) => {
    const btn = document.createElement("button");
    btn.className =
      "tab_btn" + (cat.id === editModalState.activeCatId ? " active" : "");
    btn.textContent = cat.cat_name;
    btn.onclick = () => {
      editModalState.activeCatId = cat.id;
      renderEditModalCategories();
      renderEditModalItems();
    };
    container.appendChild(btn);
  });
}

function renderEditModalItems() {
  const grid = document.getElementById("edit_modal_items_grid");
  if (!grid) return;
  grid.innerHTML = "";

  const catProducts = products.filter(
    (p) => p.cat_id === editModalState.activeCatId && p.is_available,
  );
  if (catProducts.length === 0) {
    grid.innerHTML = `<p style="color:var(--color-subtext);grid-column:1/-1;text-align:center;padding:30px">لا توجد أصناف في هذا التصنيف</p>`;
    return;
  }

  catProducts.forEach((product) => {
    const variants = product.variants || [];
    const price = product.price || (variants[0] ? variants[0].price : 0);
    const priceLabel =
      variants.length > 1 ? `بدءاً من ${price} ج.م` : `${price} ج.م`;

    const description =
      product.description || product.desc || product.product_desc || "";
    const descriptionHtml = description
      ? `<p style="font-size: 11px; color: var(--color-subtext); line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis; margin:0">${description}</p>`
      : "";

    const card = document.createElement("div");
    card.className = "item_card";
    card.innerHTML = `
      <h1>${product.product_name}</h1>
      ${descriptionHtml}
      <h2>${priceLabel}</h2>
    `;
    card.onclick = () => handleEditModalProductClick(product, price);
    grid.appendChild(card);
  });
}

// --------------------------- Edit Modal Cart ---------------------------
function addEditModalCartItem(itemInfo) {
  let existing = editModalState.cart.find(
    (c) => String(c.item.id) === String(itemInfo.id),
  );
  if (!existing && itemInfo.originalProductId) {
    // fallback matching by price & name if ID format differs between local added vs loaded
    existing = editModalState.cart.find(
      (c) =>
        c.item.originalProductId === itemInfo.originalProductId &&
        c.item.price === itemInfo.price,
    );
  }

  if (existing) {
    existing.qty++;
  } else {
    editModalState.cart.push({ qty: 1, item: itemInfo });
  }
  renderEditModalCart();
}

function changeEditModalCartQty(idx, delta) {
  if (editModalState.cart[idx]) {
    editModalState.cart[idx].qty += delta;
    if (editModalState.cart[idx].qty <= 0) {
      editModalState.cart.splice(idx, 1);
    }
    renderEditModalCart();
  }
}

function renderEditModalCart() {
  const list = document.getElementById("edit_modal_cart_list");
  const totalEl = document.getElementById("edit_modal_items_total");
  if (!list || !totalEl) return;

  list.innerHTML = "";
  if (editModalState.cart.length === 0) {
    list.innerHTML = `
      <div class="cart_empty">
        <svg width="40" height="40" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
          <path d="M16 11V7a4 4 0 00-8 0v4M5 9h14l1 12H4L5 9z"/>
        </svg>
        <p>لا توجد أصناف في التعديل</p>
      </div>
    `;
    totalEl.textContent = "0 ج.م";
    return;
  }

  let totalNum = 0;
  editModalState.cart.forEach((cItem, idx) => {
    let price = cItem.item.price || 0;
    let qty = cItem.qty || 1;
    totalNum += price * qty;

    const card = document.createElement("div");
    card.className = "total_card";
    card.innerHTML = `
      <div class="card_info">
        <h1>${cItem.item.name}</h1>
        <h2 class="card_price">${(price * qty).toFixed(2)} ج.م</h2>
      </div>
      <div class="card_controls">
        <div class="qty_controls">
          <button class="btn_qty" onclick="changeEditModalCartQty(${idx}, -1)">−</button>
          <span class="qty_num">${qty}</span>
          <button class="btn_qty" onclick="changeEditModalCartQty(${idx}, 1)">+</button>
        </div>
        <button class="btn_delete" onclick="removeFromEditModalCart(${idx})">
          <svg fill="none" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>
    `;
    list.appendChild(card);
  });

  updateEditModalGrandTotal();
}

function updateEditModalGrandTotal() {
  const totalEl = document.getElementById("edit_modal_items_total");
  if (!totalEl) return;

  const itemsTotal = editModalState.cart.reduce(
    (sum, c) => sum + c.item.price * c.qty,
    0,
  );
  let fee = 0;
  if (
    editModalState.orderType === "delivery" &&
    hasFeeValue(editModalState.selectedDeliveryFee)
  ) {
    fee = editModalState.selectedDeliveryFee;
  } else if (
    editModalState.orderType === "dine_in" &&
    hasFeeValue(editModalState.selectedDineInFee)
  ) {
    fee = editModalState.selectedDineInFee;
  }

  let discount = 0;
  if (editModalState.discountType === "fixed") {
    discount = editModalState.discountValue;
  } else if (editModalState.discountType === "percentage") {
    discount = itemsTotal * (editModalState.discountValue / 100);
  }

  const grandTotal = Math.max(0, itemsTotal + fee - discount);
  totalEl.textContent = grandTotal.toFixed(2) + " ج.م";
}

function removeFromEditModalCart(idx) {
  editModalState.cart.splice(idx, 1);
  renderEditModalCart();
}

function handleEditModalProductClick(product, defaultPrice) {
  const variants = product.variants || [];
  if (variants.length <= 1) {
    addEditModalCartItem({
      originalProductId: product.id,
      id: product.id,
      name: product.product_name,
      price: defaultPrice,
    });
    return;
  }

  // Reuse existing variant picker logic but targeted for edit modal
  const old = document.getElementById("variant_picker");
  if (old) old.remove();

  const overlay = document.createElement("div");
  overlay.id = "variant_picker";
  overlay.style.cssText = `position:fixed;inset:0;background:rgba(0,0,0,0.75);display:flex;align-items:center;justify-content:center;z-index:12000;`;

  const box = document.createElement("div");
  box.style.cssText = `background:rgba(15,12,6,0.97);border:1px solid var(--color-primary-border);border-radius:16px;padding:24px;min-width:280px;display:flex;flex-direction:column;gap:12px;direction:rtl;`;

  box.innerHTML = `
    <h2 style="color:var(--color-primary);font-size:16px;margin:0;text-align:center">${product.product_name}</h2>
    <p style="color:var(--color-subtext);font-size:13px;text-align:center;margin:0">اختر الحجم (تعديل)</p>
  `;

  variants.forEach((v) => {
    const btn = document.createElement("button");
    btn.style.cssText = `background:var(--color-primary-light);border:1px solid var(--color-primary-border);border-radius:10px;padding:10px 16px;color:var(--color-text);font-family:Cairo,sans-serif;font-size:14px;font-weight:700;cursor:pointer;display:flex;justify-content:space-between;align-items:center;`;
    btn.innerHTML = ` <span>${v.name}</span><span style="color:var(--color-primary)">${parseFloat(v.price)} ج.م</span>`;
    btn.onclick = () => {
      addEditModalCartItem({
        originalProductId: product.id,
        id: `${product.id}_${v.id}`,
        name: `${product.product_name} - ${v.name}`,
        price: parseFloat(v.price),
      });
      overlay.remove();
    };
    box.appendChild(btn);
  });

  const cancelBtn = document.createElement("button");
  cancelBtn.textContent = "إلغاء";
  cancelBtn.style.cssText = `background:transparent;border:1px solid var(--color-subtext);border-radius:10px;padding:8px;color:var(--color-subtext);font-family:Cairo,sans-serif;font-size:14px;cursor:pointer;margin-top:4px;`;
  cancelBtn.onclick = () => overlay.remove();
  box.appendChild(cancelBtn);
  overlay.appendChild(box);
  document.body.appendChild(overlay);
}

// --------------------------- Edit Modal API Save Call ---------------------------
async function updateEditOrderConfirm() {
  editModalState.customerPhone = normalizePhoneDigits(editModalState.customerPhone);

  if (editModalState.customerPhone && !isValidEgyptianPhone(editModalState.customerPhone)) {
    showToast("رقم التليفون يجب أن يكون 11 رقم", "error");
    return;
  }

  if (editModalState.orderType === "delivery" && !editModalState.customerPhone) {
    showToast("يرجى إدخال رقم تليفون العميل أولاً", "error");
    return;
  }

  if (editModalState.cart.length === 0) {
    showToast("الفاتورة فارغة، لا يمكن حفظ طلب فارغ!", "error");
    return;
  }

  const confirmed = await showCustomActionConfirm(
    "هل أنت متأكد من حفظ التعديلات على هذا الطلب؟",
  );
  if (!confirmed) return;

  showGlobalLoader(true);

  try {
    const orig = editModalState.originalOrder;

    // تجهيز الأصناف الجديدة (نفس منطق الكاشير الأساسي للتعامل مع الـ variants)
    const newItems = editModalState.cart.map((c) => {
      let prodId = c.item.originalProductId || c.item.id;
      if (typeof prodId === "string" && prodId.includes("_")) {
        prodId = parseInt(prodId.split("_")[0], 10);
      } else {
        prodId = parseInt(prodId, 10);
      }
      return {
        product_id: prodId,
        quantity: c.qty,
        unit_price: c.item.price,
      };
    });

    const mappedOrderType =
      editModalState.orderType === "dine_in"
        ? "hall"
        : editModalState.orderType;

    if (!mappedOrderType) {
      alert("يجب اختيار نوع الطلب أولاً");
      btn.innerHTML = originalBtnHTML;
      btn.disabled = false;
      return;
    }

    // تجهيز حمولة البيانات (Payload) للـ PATCH
    const payload = {
      customer_id: orig.customer_id,
      customer_name: editModalState.customerName,
      customer_phone: editModalState.customerPhone,
      order_type: mappedOrderType,
      customer_notes: orig.customer_notes,
      internal_notes: orig.internal_notes,
      items: newItems,
      address_id: orig.address_id,
      customer_address: editModalState.customerAddress,
      delivery_person_id: editModalState.selectedDelivery
        ? editModalState.selectedDelivery.id
        : null,
      delivery_fee:
        editModalState.orderType === "delivery"
          ? editModalState.selectedDeliveryFee
          : editModalState.orderType === "dine_in"
            ? editModalState.selectedDineInFee
            : 0,
      manual_discount_type: editModalState.discountType || null,
      manual_discount_value: editModalState.discountValue || null,
      discount_reason: editModalState.discountReason || null,
    };

    // إرسال طلب التحديث (PATCH)
    const res = await apiFetch(`/orders/${orig.id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      console.error("API Error during update:", errData);
      throw new Error("فشل تحديث الطلب في الباك إند");
    }

    const updatedOrder = await res.json();
    showToast("تم تعديل الطلب بنجاح ✓", "success");

    // إغلاق المودال بعد النجاح
    const modal = document.getElementById("edit_order_modal_overlay");
    if (modal) modal.remove();

    // Prepare fully populated local order object
    const itemsTotal = newItems.reduce(
      (sum, item) =>
        sum + parseFloat(item.unit_price) * parseInt(item.quantity),
      0,
    );
    const deliveryFee =
      (editModalState.orderType === "delivery"
        ? editModalState.selectedDeliveryFee
        : editModalState.orderType === "dine_in"
          ? editModalState.selectedDineInFee
          : 0) || 0;

    const updatedLocalOrder = {
      ...orig,
      ...updatedOrder
    };

    // تحديث القائمة المحلية فوراً لضمان ظهور التعديلات في الكارد (Card)
    if (editModalState.sourceList === "online") {
      const idx = onlineOrdersList.findIndex((o) => o.id === orig.id);
      if (idx !== -1) {
        onlineOrdersList[idx] = updatedLocalOrder;
        window.updateOrAddOnlineOrderDOM(onlineOrdersList[idx]);
      }
    } else {
      const idx = allOrdersList.findIndex((o) => o.id === orig.id);
      if (idx !== -1) {
        allOrdersList[idx] = updatedLocalOrder;
        window.updateOrAddAllOrderDOM(allOrdersList[idx]);
      }
    }

    // طباعة الفاتورة المعدلة
    if (typeof printReceipt === "function") {
      const cartMapped = (updatedLocalOrder.items || []).map((item) => {
        let prod = products.find((p) => p.id === item.product_id);
        let variantName = "";
        if (prod && prod.variants) {
          let v = prod.variants.find(
            (v) => parseFloat(v.price) === parseFloat(item.unit_price),
          );
          if (v && v.name !== prod.product_name) variantName = v.name + " - ";
        }
        let name = prod
          ? variantName + prod.product_name
          : ` صنف #${item.product_id}`;
        return {
          qty: item.quantity,
          item: {
            name: name,
            price: parseFloat(item.unit_price),
          },
        };
      });

      const printData = {
        ...updatedLocalOrder,
        cart: cartMapped,
        itemsTotal: itemsTotal,
      };

      printReceipt(printData);
    }
  } catch (err) {
    console.error(err);
    showToast("حدث خطأ أثناء الاتصال بالسيرفر لحفظ التعديلات", "error");
  } finally {
    showGlobalLoader(false);
  }
}
