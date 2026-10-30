const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("app/frontend/cashier/js/cashier.js", "utf8");
const online = source.slice(source.indexOf("async function printOrderFromOnline"), source.indexOf("async function markOrderAsPrinted"));
const list = source.slice(source.indexOf("async function printOrderFromList"), source.indexOf("async function changeOrderStatus"));
let accepted = false, marks = 0;
const order = { id: 1, items: [] };
const context = vm.createContext({ onlineOrdersList: [order], allOrdersList: [order], products: [],
  getOrderAddressText: () => "", printReceipt: async () => accepted,
  markOrderAsPrinted: async () => { marks++; }, showToast: () => {}, console });
vm.runInContext(online + list, context);
(async () => {
  await context.printOrderFromOnline(1);
  await context.printOrderFromList(1);
  assert.equal(marks, 0);
  accepted = true;
  await context.printOrderFromOnline(1);
  await context.printOrderFromList(1);
  assert.equal(marks, 2);
})().catch(error => { console.error(error); process.exitCode = 1; });
