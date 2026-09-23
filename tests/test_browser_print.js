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
  API_BASE: "",
  AbortController,
  console,
  setTimeout,
  clearTimeout,
  fetch: async (url, options) => {
    calls.push({ url, options });
    if (url.endsWith("/settings/menu-checkout")) {
      return { ok: true, json: async () => ({ wallet_number: "01009515031" }) };
    }
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
const cashOrder = context.order;
context.order = { ...cashOrder, id: 78, payment_method: "wallet" };
vm.runInContext("printReceipt(order)", context);

setTimeout(() => {
  assert.equal(calls.length, 3);
  assert.equal(calls[0].url, "http://127.0.0.1:8199/api/print");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.headers["Content-Type"], "application/json");
  assert.equal(calls[0].options.targetAddressSpace, "loopback");
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    order: cashOrder,
    receipt_type: "customer",
  });
  assert.equal(calls[1].url, "/settings/menu-checkout");
  assert.equal(calls[2].url, "http://127.0.0.1:8199/api/print");
  assert.equal(JSON.parse(calls[2].options.body).order.payment_destination, "01009515031");
  console.log("Browser print bridge test passed");
}, 0);
