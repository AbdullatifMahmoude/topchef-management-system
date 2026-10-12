const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const handlers = {};
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    value: "", innerHTML: "", textContent: "", disabled: false, hidden: false,
    addEventListener(event, handler) { handlers[`${id}:${event}`] = handler; },
    querySelector() { return element("expenses-tbody"); },
    reset() {}, focus() {},
  });
  return elements.get(id);
}
const requests = [];
const shifts = [{ id: 4, cashier_name: "أحمد", start_time: "2026-09-21T08:00:00+00:00" }];
const expenses = [
  { id: 10, title: "صيانة", amount: 25, target_date: "2026-09-21", shift_id: 4, shift_owner: "أحمد", recorded_by: "مدير", source: "admin" },
  { id: 11, title: "مشتريات", amount: 50, target_date: "2026-09-21", shift_id: 5, shift_owner: "علي", recorded_by: "مدير", source: "admin" },
];
const context = vm.createContext({
  document: { getElementById: element, querySelector() { return null; } },
  window: {
    apiFetch: async (path, options = {}) => {
      requests.push({ path, options });
      if (path === "/shifts/business-date") return { ok: true, json: async () => ({ business_date: "2026-09-21" }) };
      if (path.startsWith("/shifts/admin/expense-shifts")) return { ok: true, json: async () => shifts };
      if (path.startsWith("/shifts/admin/expenses?") ) return { ok: true, json: async () => ({ items: expenses }) };
      if (path === "/shifts/admin/expenses" && options.method === "POST") return { ok: true, json: async () => ({ shift_id: 4 }) };
      throw new Error(`Unexpected request: ${path}`);
    },
    refreshStableDateInput() {},
  },
  alert(message) { throw new Error(message); },
  Date, Number, String, Promise,
});
vm.runInContext(fs.readFileSync("app/frontend/js/expenses-admin.js", "utf8"), context);

(async () => {
  await context.window.refreshAdminExpenses();
  assert.match(element("adminExpensesShiftFilter").innerHTML, /أحمد/);
  assert.match(element("adminExpensesShiftFilter").innerHTML, /علي/);
  element("adminExpensesShiftFilter").value = "4";
  handlers["adminExpensesShiftFilter:change"]();
  assert.match(element("adminExpensesTable").querySelector().innerHTML, /صيانة/);
  assert.doesNotMatch(element("adminExpensesTable").querySelector().innerHTML, /مشتريات/);
  assert.equal(element("adminExpensesCount").textContent, "١");
  assert.equal(element("adminExpensesTotal").textContent, `${(25).toLocaleString("ar-EG", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ج.م`);
  element("adminExpensesShiftFilter").value = "all";
  assert.match(element("adminExpenseShift").innerHTML, /أحمد/);
  assert.match(element("adminExpenseShift").innerHTML, /شيفت #4/);
  element("adminExpenseShift").value = "4";
  element("adminExpenseTitle").value = "صيانة";
  element("adminExpenseAmount").value = "25";
  element("adminExpenseNote").value = "";
  await handlers["adminExpenseForm:submit"]({ preventDefault() {} });
  const saved = requests.find((request) => request.path === "/shifts/admin/expenses" && request.options.method === "POST");
  assert.ok(saved);
  assert.equal(JSON.parse(saved.options.body).shift_id, 4);
  assert.equal(JSON.parse(saved.options.body).target_date, "2026-09-21");
  assert.equal(element("adminExpensesShiftFilter").value, "4");
  console.log("Admin expense selects and submits the day's shift");
})().catch((error) => { console.error(error); process.exitCode = 1; });
