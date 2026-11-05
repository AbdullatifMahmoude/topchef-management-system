const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("app/frontend/cashier/js/cashier.js", "utf8");
const load = source.slice(source.indexOf("async function loadShiftExpenses()"), source.indexOf("async function deleteShiftExpense("));
const refresh = source.slice(source.indexOf("function refreshVisibleShiftExpenses()"), source.indexOf("function handleSocketEvent("));
let active = false;
let modal = null;
let requests = 0;
let rendered = 0;
const list = { innerHTML: "" };
const context = vm.createContext({
  expensesRequestSequence: 0, expensesLoadController: null, currentShiftExpenses: [], currentShiftExpensesTotal: 0,
  AbortController, console,
  document: { getElementById: id => ({
    tab_expenses: { classList: { contains: () => active } },
    shift_cash_expenses_total: modal,
    expenses_list: list,
  })[id] || null },
  apiFetch: async () => { requests++; return { ok: true, json: async () => ({ total: 75, items: [{ id: 1 }] }) }; },
  renderShiftExpenses: () => { rendered++; },
  expenseMoney: amount => `${amount} ج.م`,
});
vm.runInContext(load + refresh, context);

(async () => {
  context.refreshVisibleShiftExpenses();
  assert.equal(requests, 0);
  active = true;
  context.refreshVisibleShiftExpenses();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests, 1);
  assert.equal(rendered, 1);
  active = false;
  modal = { textContent: "old" };
  context.refreshVisibleShiftExpenses();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests, 2);
  assert.equal(modal.textContent, "75 ج.م");
  console.log("Live expense refresh tests passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
