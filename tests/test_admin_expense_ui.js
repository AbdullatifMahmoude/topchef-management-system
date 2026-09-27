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
const context = vm.createContext({
  document: { getElementById: element, querySelector() { return null; } },
  window: {
    apiFetch: async (path, options = {}) => {
      requests.push({ path, options });
      if (path === "/shifts/business-date") return { ok: true, json: async () => ({ business_date: "2026-09-21" }) };
      if (path.startsWith("/shifts/admin/expense-shifts")) return { ok: true, json: async () => shifts };
      if (path.startsWith("/shifts/admin/expenses?") ) return { ok: true, json: async () => ({ items: [] }) };
      if (path === "/shifts/admin/expenses" && options.method === "POST") return { ok: true, json: async () => ({}) };
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
  console.log("Admin expense selects and submits the day's shift");
})().catch((error) => { console.error(error); process.exitCode = 1; });
