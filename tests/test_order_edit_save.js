const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("app/frontend/cashier/js/cashier.js", "utf8");
const addressHelper = source.slice(
  source.indexOf("function getOrderAddressText"),
  source.indexOf("// ===================================================", source.indexOf("function getOrderAddressText")),
);
const saveFunction = source.slice(source.indexOf("async function updateEditOrderConfirm()"));

async function runEdit(verifiedAddress) {
  const calls = [];
  const toasts = [];
  const prints = [];
  const originalOrder = {
    id: 42,
    customer_id: 7,
    customer_name: "Test Customer",
    customer_phone: "01000000001",
    customer_address: "Old address",
    address_id: 3,
  };
  const context = vm.createContext({
    editModalState: {
      originalOrder,
      customerName: "Test Customer",
      customerPhone: "01000000001",
      customerAddress: "New address",
      orderType: "delivery",
      cart: [{ item: { id: 1, price: 10 }, qty: 1 }],
      sourceList: "all",
    },
    allOrdersList: [originalOrder],
    onlineOrdersList: [],
    products: [],
    window: { updateOrAddAllOrderDOM() {} },
    document: { getElementById() { return null; } },
    console: { error() {} },
    normalizePhoneDigits: (phone) => phone,
    isValidEgyptianPhone: () => true,
    showCustomActionConfirm: async () => true,
    showGlobalLoader() {},
    showToast: (message, kind) => toasts.push([message, kind]),
    printReceipt: (data) => prints.push(data),
    apiFetch: async (path, options) => {
      calls.push([path, options.method || "GET"]);
      return {
        ok: true,
        json: async () => options.method === "PATCH"
          ? { ...originalOrder, customer_address: "New address" }
          : { ...originalOrder, customer_address: verifiedAddress },
      };
    },
  });
  vm.runInContext(addressHelper + saveFunction, context);
  await vm.runInContext("updateEditOrderConfirm()", context);
  return { calls, toasts, prints };
}

(async () => {
  const saved = await runEdit("New address");
  assert.deepEqual(saved.calls, [["/orders/42", "PATCH"], ["/orders/42", "GET"]]);
  assert.equal(saved.toasts.at(-1)[1], "success");
  assert.equal(saved.prints.length, 1);

  const notSaved = await runEdit("Old address");
  assert.equal(notSaved.toasts.at(-1)[1], "error");
  assert.equal(notSaved.prints.length, 0);
  console.log("Edited order save verification tests passed");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
