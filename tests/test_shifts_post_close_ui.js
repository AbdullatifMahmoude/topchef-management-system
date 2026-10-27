const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    innerHTML: "", textContent: "", setAttribute() {},
    classList: { add() {} }, addEventListener() {},
  });
  return elements.get(id);
}

const context = vm.createContext({
  document: {
    addEventListener() {}, getElementById: element,
    querySelectorAll() { return []; }, body: { classList: { add() {}, remove() {} } },
  },
  window: { addEventListener() {} },
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
assert.ok(markup.includes(`<span>فرق التسوية عند الإقفال</span><strong>${money(-70)}</strong>`));
assert.ok(markup.includes(`<span>الفرق بعد تسويات الإدارة المسجلة</span><strong>${money(0)}</strong>`));
assert.match(markup, /نقد دليفري بعد العد/);
shift.post_close_adjustments = [];
context.openShiftDrawer(135);
assert.doesNotMatch(element("shiftDrawerContent").innerHTML, /الفرق بعد تسويات الإدارة المسجلة/);
console.log("Shift drawer keeps the original difference and shows settlement result");
