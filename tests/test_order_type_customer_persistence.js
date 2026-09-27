const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("app/frontend/cashier/js/cashier.js", "utf8");
const take = (start, end) => source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
const functions = [
  take("function clearOrderType()", "// ==================================================="),
  take("function selectDineInFee(fee)", "// ==================================================="),
  take("function showDeliveryFeeSelector(rider)", "let _deliveryRidersCache"),
].join("\n");

const customer = {
  phone: "01000000001",
  name: "عميل تجريبي",
  customerId: 7,
  addresses: [{ id: 9, address: "عنوان محفوظ" }],
  selectedAddressId: 9,
  newAddress: "عنوان جديد",
  manualAddressMode: true,
};
const form = { style: {}, innerHTML: "" };
const list = { innerHTML: "", children: [], appendChild(child) { this.children.push(child); } };
const context = vm.createContext({
  deliveryCustomerInfo: customer,
  orderType: "takeaway",
  selectedDelivery: null,
  selectedDeliveryFee: null,
  selectedDineInFee: null,
  document: {
    getElementById(id) { return id === "delivery_customer_form" ? form : id === "delivery_names_list" ? list : null; },
    createElement() { return { style: {}, children: [], appendChild(child) { this.children.push(child); } }; },
  },
  resetDeliveryCustomerInfo() { throw new Error("Changing order type must not reset customer details"); },
  closeDeliveryModal() {},
  renderOrderTypeBadge() {},
  renderOrderTypeButtons() {},
  renderCart() {},
  renderDeliveryCustomerForm() {},
});
vm.runInContext(functions, context);

vm.runInContext("clearOrderType()", context);
assert.equal(context.orderType, null);
assert.strictEqual(context.deliveryCustomerInfo, customer);

vm.runInContext("selectOrderType('takeaway')", context);
assert.equal(context.orderType, "takeaway");
vm.runInContext("selectDineInFee(10)", context);
assert.equal(context.orderType, "dine_in");

vm.runInContext("showDeliveryFeeSelector({ id: 4, name: 'Rider' })", context);
list.children[0].children[1].onclick(); // 5 جنيه
assert.equal(context.orderType, "delivery");
assert.equal(context.selectedDelivery.id, 4);
assert.strictEqual(context.deliveryCustomerInfo, customer);
assert.equal(customer.name, "عميل تجريبي");
assert.equal(customer.phone, "01000000001");
assert.equal(customer.newAddress, "عنوان جديد");
assert.equal(customer.selectedAddressId, 9);
console.log("Customer details persist across order type changes");
