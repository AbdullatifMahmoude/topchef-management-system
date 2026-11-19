const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    innerHTML: "", textContent: "", style: {}, setAttribute() {},
    classList: { add() {} }, addEventListener() {},
  });
  return elements.get(id);
}

const documentListeners = {};
const windowListeners = {};
const context = vm.createContext({
  document: {
    addEventListener: (type, listener) => { documentListeners[type] = listener; },
    getElementById: id => id === "shiftsDateFilter" ? null : element(id),
    querySelectorAll() { return []; }, body: { classList: { add() {}, remove() {} } },
  },
  window: { addEventListener: (type, listener) => { windowListeners[type] = listener; } },
  Date, Number, String,
});
vm.runInContext(fs.readFileSync("app/frontend/js/shifts.js", "utf8"), context);

const shift = {
  id: 135, cashier_name: "كاشير", target_date: "2026-10-27", status: "closed",
  cash_tracking_enabled: true, close_snapshot_at: "2026-10-27T14:00:00Z",
  end_time: "2026-10-27T14:00:00Z", start_time: "2026-10-27T08:00:00Z",
  opening_cash: 0, cash_sales: 385, expected_cash: 385,
  actual_closing_cash: 315, adjusted_closing_cash: 385,
  cash_difference: -70, difference_after_adjustments: 0,
  post_close_adjustments_total: 70,
  post_close_adjustments: [{ id: 1, amount: 70, reason: "نقد دليفري بعد العد", created_at: "2026-10-27T15:00:00Z" }],
};
context.inputShifts = [shift];
vm.runInContext("shiftsData = inputShifts", context);
context.openShiftDrawer(135);
const markup = element("shiftDrawerContent").innerHTML;
const money = (amount) => vm.runInContext(`shiftMoney(${amount})`, context);
assert.ok(markup.includes(`<span>عجز نقدية بالدرج</span><strong>${money(-70)}</strong>`));
assert.ok(markup.includes(`<span>الفرق بعد تسويات الإدارة المسجلة</span><strong>${money(0)}</strong>`));
assert.match(markup, /نقد دليفري بعد العد/);
shift.post_close_adjustments = [];
context.openShiftDrawer(135);
assert.doesNotMatch(element("shiftDrawerContent").innerHTML, /الفرق بعد تسويات الإدارة المسجلة/);
shift.cash_difference = -50;
shift.cash_sales = 0;
shift.cash_sales_at_close = 50;
shift.opening_cash = 300;
shift.expected_cash = 350;
shift.actual_closing_cash = 300;
shift.adjusted_closing_cash = 300;
shift.post_close_cancelled_cash_sales = 50;
context.openShiftDrawer(135);
const cancelledMarkup = element("shiftDrawerContent").innerHTML;
assert.ok(cancelledMarkup.includes(`<span>نقدية مطابقة تماماً</span><strong>${money(0)}</strong>`));
assert.ok(cancelledMarkup.includes(`<span>(+) مبيعات نقدية بالدرج (كاش)</span><strong>${money(0)}</strong>`));
assert.ok(cancelledMarkup.includes(`<span>(=) النقد المتوقع في الدرج</span><strong>${money(300)}</strong>`));
assert.doesNotMatch(cancelledMarkup, /عجز نقدية|مبيعات كاش أُلغيت|الفرق بعد/);

shift.post_close_adjustments = [{ id: 2, amount: -5, reason: "رد نقدي", created_at: "2026-10-27T15:00:00Z" }];
shift.adjusted_closing_cash = 295;
shift.difference_after_adjustments = -5;
context.openShiftDrawer(135);
const adjustedMarkup = element("shiftDrawerContent").innerHTML;
assert.ok(adjustedMarkup.includes(`<span>عجز نقدية بالدرج</span><strong>${money(-5)}</strong>`));
assert.ok(adjustedMarkup.includes(`<span>النقد الفعلي بعد التسويات</span><strong>${money(295)}</strong>`));
assert.doesNotMatch(adjustedMarkup, /الفرق بعد/);
vm.runInContext("let refreshes = 0; fetchShiftsReport = () => { refreshes++; };", context);
documentListeners.DOMContentLoaded();
const orderUpdate = status => ({ detail: { type: "ORDER_UPDATED", data: { order_status: status } } });
windowListeners["topchef:admin-live"](orderUpdate("confirmed"));
windowListeners["topchef:admin-live"](orderUpdate("cancelled"));
element("page-shifts").style.display = "none";
windowListeners["topchef:admin-live"](orderUpdate("cancelled"));
assert.equal(vm.runInContext("refreshes", context), 1);
console.log("Shift drawer applies cancellations to the existing cash difference card");
