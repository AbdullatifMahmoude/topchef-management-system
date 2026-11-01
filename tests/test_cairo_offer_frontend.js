const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const files = [
  ["app/frontend/cashier/js/cashier.js", "function getActiveOffersForProduct", "function formatProductOffer"],
  ["../menu/js/app.js", "function filterCurrentOffers", "function applyCheckoutSettings"],
];
for (const [file, first, last] of files) {
  const source = fs.readFileSync(file, "utf8");
  const start = source.indexOf("function cairoWallTimeNow()");
  const end = source.indexOf(last, source.indexOf(first));
  assert.ok(start >= 0 && end > start);
  class FixedDate extends Date { constructor() { super("2026-10-30T12:30:00Z"); } }
  const offer = { is_active: true, valid_from: "2026-10-30T14:00:00", valid_to: "2026-10-30T15:00:00", product_ids: [] };
  const context = vm.createContext({ Date: FixedDate, Intl, products: [{ id: 1 }], activeOffers: [offer] });
  vm.runInContext(source.slice(start, end), context);
  assert.equal(context.cairoWallTimeNow(), "2026-10-30T14:30:00");
  assert.equal(file.startsWith("../") ? context.filterCurrentOffers([offer]).length : context.getActiveOffersForProduct(1).length, 1);
}
