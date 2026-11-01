const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("app/frontend/cashier/js/cashier.js", "utf8");
const start = source.indexOf("async function logout(");
const end = source.indexOf("//  Order Details Modal", start);
assert.ok(start >= 0 && end > start);
const requests = [];
const removed = [];
let destination;
const context = vm.createContext({
  API_BASE: "",
  localStorage: { getItem: () => "token", removeItem: (key) => removed.push(key) },
  fetch: async (url) => {
    requests.push(url);
    return requests.length === 1 ? { status: 400, ok: false } : { status: 200, ok: true };
  },
  showCustomActionConfirm: async () => true,
  showToast: () => assert.fail("unexpected error"),
  window: { location: { replace: (url) => { destination = url; } } },
  console: { warn() {} },
});
vm.runInContext(source.slice(start, end), context);
context.logout().then(() => {
  assert.deepEqual(requests, ["/auth/logout", "/auth/logout?close_shift=false"]);
  assert.ok(removed.includes("token"));
  assert.equal(destination, "../index.html");
  console.log("Cashier can log out while the shift remains open");
}).catch((error) => { console.error(error); process.exitCode = 1; });
