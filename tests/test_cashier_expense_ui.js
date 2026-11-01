const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("app/frontend/cashier/js/cashier.js", "utf8");
const start = source.indexOf("function expenseMoney(");
const end = source.indexOf("async function loadShiftExpenses()", start);
assert.ok(start >= 0 && end > start);

const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    innerHTML: "", textContent: "", offsetWidth: 0,
    classList: { add() {}, remove() {} },
  });
  return elements.get(id);
}
const context = vm.createContext({
  document: { getElementById: element },
  Date, Number, String,
});
vm.runInContext(source.slice(start, end), context);
vm.runInContext(`currentShiftExpenses = [
  { id: 1, title: "إدارة", amount: 25, created_at: "2026-09-21T08:00:00Z", can_delete: false },
  { id: 2, title: "كاشير", amount: 10, created_at: "2026-09-21T09:00:00Z", can_delete: true },
]; currentShiftExpensesTotal = 35; renderShiftExpenses();`, context);
const html = element("expenses_list").innerHTML;
assert.match(html, /مصروف أضافته الإدارة/);
assert.doesNotMatch(html, /deleteShiftExpense\(1\)/);
assert.match(html, /deleteShiftExpense\(2\)/);
console.log("Cashier cannot delete an admin-recorded shift expense");
