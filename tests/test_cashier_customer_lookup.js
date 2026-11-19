const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("app/frontend/cashier/js/cashier.js", "utf8");
const lookup = source.slice(source.indexOf("function handlePhoneInput("), source.indexOf("function showGlobalLoader("));
const name = { value: "اسم كتبه الكاشير", readOnly: false, style: {}, classList: { add() {}, remove() {} } };
const status = { innerHTML: "", textContent: "" };
const address = {};
const state = { phone: "", name: "اسم كتبه الكاشير", customerId: null, addresses: [], selectedAddressId: null, newAddress: "" };
let fetcher;
let pendingLookup;
const context = vm.createContext({
  deliveryCustomerInfo: state, customerPhoneLookupVersion: 0,
  normalizePhoneDigits: value => value,
  _phoneSearchTimeout: null,
  setTimeout: callback => { pendingLookup = callback; },
  clearTimeout: () => { pendingLookup = null; },
  document: { getElementById: id => ({ dcf_name: name, dcf_phone_status: status, dcf_address_field: address })[id] },
  renderAddressFieldHTML: () => "addresses", console: { warn() {} },
  apiFetch: (...args) => fetcher(...args),
});
vm.runInContext(lookup, context);

(async () => {
  fetcher = async () => ({ ok: false, status: 404 });
  context.handlePhoneInput("0");
  assert.equal(name.value, "اسم كتبه الكاشير");
  context.handlePhoneInput("01000000001");
  await pendingLookup();
  assert.match(status.innerHTML, /جديد/);
  assert.equal(name.value, "اسم كتبه الكاشير");
  assert.equal(state.name, "اسم كتبه الكاشير");

  status.innerHTML = "";
  fetcher = async () => ({ ok: false, status: 503 });
  await context.lookupCustomerByPhone(state.phone);
  assert.match(status.textContent, /تعذر البحث/);
  assert.doesNotMatch(status.innerHTML, /جديد/);

  state.newAddress = "عنوان أدخله الكاشير";
  state.manualAddressMode = true;
  fetcher = async () => ({ ok: true, json: async () => ({ id: 3, name: "عميل", addresses: [{ id: 9, address: "عنوان محفوظ" }] }) });
  await context.lookupCustomerByPhone(state.phone);
  assert.equal(state.newAddress, "عنوان أدخله الكاشير");
  assert.equal(state.selectedAddressId, null);
  assert.equal(state.manualAddressMode, true);

  let resolveOld;
  fetcher = () => new Promise(resolve => { resolveOld = resolve; });
  const old = context.lookupCustomerByPhone(state.phone);
  state.phone = "01000000002";
  fetcher = async () => ({ ok: true, json: async () => ({ id: 2, name: "العميل الجديد", addresses: [] }) });
  await context.lookupCustomerByPhone(state.phone);
  resolveOld({ ok: true, json: async () => ({ id: 1, name: "العميل القديم", addresses: [] }) });
  await old;
  assert.equal(state.customerId, 2);
  assert.equal(name.value, "العميل الجديد");
  context.handlePhoneInput("0100000000");
  assert.equal(state.customerId, null);
  assert.equal(state.name, "");
  assert.equal(name.value, "");
  console.log("Customer lookup tests passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
