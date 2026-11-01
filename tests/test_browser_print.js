const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const cashierSource = fs.readFileSync("app/frontend/cashier/js/cashier.js", "utf8");
const bridge = cashierSource.slice(cashierSource.indexOf("const TOPCHEF_PRINT_AGENT_URL"), cashierSource.indexOf("// End Print Agent bridge."));
const mark = cashierSource.slice(cashierSource.indexOf("async function markOrderAsPrinted"), cashierSource.indexOf("// ===================================================", cashierSource.indexOf("async function markOrderAsPrinted")));
const calls = [];
let printOk = true, markOk = true;
const order = { id: 77, orderNumber: "T1-0077", cart: [{ item: { name: "وجبة", price: 75 }, qty: 1 }], grandTotal: 75 };
const context = vm.createContext({ API_BASE: "", AbortController, console, setTimeout, clearTimeout,
  showToast: () => {}, allOrdersList: [order], onlineOrdersList: [], allOrdersFilter: "all", window: {},
  apiFetch: async () => ({ ok: markOk }),
  fetch: async (url, options) => {
    calls.push({ url, options });
    if (url.endsWith("/settings/menu-checkout")) return { ok: true, json: async () => ({ wallet_number: "01009515031" }) };
    if (!printOk) throw new Error("offline");
    return { ok: true };
  },
});
vm.runInContext(bridge + mark, context);
(async () => {
  assert.equal(await context.printReceipt(order), true);
  assert.equal(calls[0].url, "http://127.0.0.1:8199/api/print");
  assert.equal(calls[0].options.targetAddressSpace, "loopback");
  assert.deepEqual(JSON.parse(calls[0].options.body), { order, receipt_type: "customer" });
  assert.equal(await context.printReceipt({ ...order, payment_method: "wallet" }), true);
  assert.equal(JSON.parse(calls[2].options.body).order.payment_destination, "01009515031");
  printOk = false;
  assert.equal(await context.printReceipt(order), false);
  markOk = false;
  assert.equal(await context.markOrderAsPrinted(77), false);
  assert.notEqual(order.is_printed, true);
  markOk = true;
  assert.equal(await context.markOrderAsPrinted(77), true);
  assert.equal(order.is_printed, true);
})().catch(error => { console.error(error); process.exitCode = 1; });
