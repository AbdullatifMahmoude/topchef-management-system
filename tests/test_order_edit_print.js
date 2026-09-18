const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const cashierSource = fs.readFileSync("app/frontend/cashier/js/cashier.js", "utf8");
const addressHelper = cashierSource.slice(
  cashierSource.indexOf("function getOrderAddressText"),
  cashierSource.indexOf("// ===================================================", cashierSource.indexOf("function getOrderAddressText")),
);
const context = vm.createContext({});
vm.runInContext(addressHelper, context);

const updatedLocalOrder = {
  customerAddress: "العنوان القديم",
  customer_address: "العنوان الجديد",
};
const printData = {
  ...updatedLocalOrder,
  customerAddress: vm.runInContext(
    `getOrderAddressText(${JSON.stringify(updatedLocalOrder)})`,
    context,
  ),
};

assert.equal(printData.customerAddress, "العنوان الجديد");
console.log("Edited order print address test passed");
