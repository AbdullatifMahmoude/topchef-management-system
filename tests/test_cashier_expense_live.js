const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("app/frontend/cashier/js/cashier.js", "utf8");
const start = source.indexOf("function refreshVisibleShiftExpenses()");
const end = source.indexOf('  if (payload.type === "SETTING_UPDATED")', start);
assert.ok(start >= 0 && end > start);

let active = true;
let refreshes = 0;
const context = vm.createContext({
  document: { getElementById: () => ({ classList: { contains: () => active } }) },
  loadShiftExpenses: () => { refreshes += 1; },
});
vm.runInContext(`${source.slice(start, end)}\n}`, context);
context.handleSocketEvent({ type: "EXPENSE_UPDATED", data: { shift_id: 4 } });
assert.equal(refreshes, 1);
active = false;
context.handleSocketEvent({ type: "EXPENSE_UPDATED", data: { shift_id: 4 } });
assert.equal(refreshes, 1);
context.handleSocketEvent({ type: "HEARTBEAT" });
assert.equal(refreshes, 1);
console.log("Expense updates refresh the open cashier expenses tab");
