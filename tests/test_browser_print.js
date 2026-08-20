const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const cashierSource = fs.readFileSync("app/frontend/cashier/js/cashier.js", "utf8");
const source = cashierSource.slice(
  cashierSource.indexOf("const TOPCHEF_PRINT_AGENT_URL"),
  cashierSource.indexOf("// End Print Agent bridge.")
);
const calls = [];
const context = vm.createContext({
  AbortController,
  console,
  setTimeout,
  clearTimeout,
  fetch: async (url, options) => {
    calls.push({ url, options });
    return { ok: true };
  },
});

vm.runInContext(source, context);
context.order = {
  id: 77,
  orderNumber: "T1-0077",
  cart: [{ item: { name: "وجبة", price: 75 }, qty: 1 }],
  grandTotal: 75,
};
vm.runInContext("printReceipt(order)", context);

setTimeout(() => {
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "http://127.0.0.1:8199/api/print");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.headers["Content-Type"], "application/json");
  assert.equal(calls[0].options.targetAddressSpace, "loopback");
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    order: context.order,
    receipt_type: "customer",
  });
  console.log("Browser print bridge test passed");
}, 0);
