const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

function gridHarness() {
  const grid = { innerHTML: "", cards: [], appendChild(card) { this.cards.push(card); } };
  const document = {
    getElementById(id) { return id === "items_grid" ? grid : null; },
    createElement() {
      const button = { disabled: false, addEventListener(_event, handler) { this.onclick = handler; } };
      return {
        innerHTML: "", className: "", style: { setProperty() {} }, button,
        querySelector(selector) { return this.innerHTML.includes(`class="${selector.slice(1)}"`) ? button : null; },
      };
    },
  };
  return { grid, document };
}

const product = {
  id: 1, cat_id: 1, product_name: "وجبة", is_available: true,
  variants: [{ id: 10, price: 50 }], temporary_unavailable_until: null,
};
const future = new Date(Date.now() + 60_000).toISOString().replace(/Z$/, "");

{
  const source = fs.readFileSync("app/frontend/cashier/js/cashier.js", "utf8");
  const start = source.indexOf("let dailyAvailabilityRefreshTimer");
  const end = source.indexOf("//  Variant Picker", start);
  assert.ok(start >= 0 && end > start);
  const { grid, document } = gridHarness();
  let added = 0;
  const context = vm.createContext({
    document, window: {}, products: [{ ...product }], activeCatId: 1,
    Date, clearTimeout, setTimeout, showToast() {},
    getActiveOffersForProduct: () => [], handleProductClick: () => added++,
    renderPopularProducts() {},
    apiFetch: async () => ({ ok: true, json: async () => ({ ...product, temporary_unavailable_until: future }) }),
  });
  vm.runInContext(source.slice(start, end), context);
  let toggled = 0;
  context.toggleDailyProduct = () => toggled++;
  context.renderItems();
  grid.cards[0].onclick();
  assert.equal(added, 1, "normal card still adds to cart");
  let stopped = false;
  grid.cards[0].button.onclick({ stopPropagation() { stopped = true; }, currentTarget: grid.cards[0].button });
  assert.equal(stopped, true, "toggle does not trigger card addition");
  assert.equal(toggled, 1);
  assert.equal(added, 1);
  context.products = [{ ...product, temporary_unavailable_until: future }];
  grid.cards = [];
  context.renderItems();
  assert.equal(grid.cards.length, 1, "paused cashier card stays visible");
  assert.match(grid.cards[0].innerHTML, /غير متاح/);
  grid.cards[0].onclick();
  assert.equal(added, 1, "paused cashier card cannot add an order item");
  vm.runInContext("clearTimeout(dailyAvailabilityRefreshTimer)", context);
}

{
  const source = fs.readFileSync("../menu/js/app.js", "utf8");
  const start = source.indexOf("function renderItems()");
  const end = source.indexOf("//  Variant Picker & Adding to Cart", start);
  assert.ok(start >= 0 && end > start);
  const { grid, document } = gridHarness();
  let added = 0;
  const context = vm.createContext({
    document, products: [{ ...product, temporary_unavailable_until: future }], activeCatId: 1,
    scheduleAvailabilityRefresh() {}, isDailyUnavailable: item => Boolean(item?.temporary_unavailable_until),
    offersForProduct: () => [], escapeHtml: value => value,
    showToast() {}, handleProductClick: () => added++,
  });
  vm.runInContext(source.slice(start, end), context);
  context.renderItems();
  assert.equal(grid.cards.length, 1, "paused product remains visible");
  assert.match(grid.cards[0].innerHTML, /غير متاح/);
  assert.doesNotMatch(grid.cards[0].innerHTML, /class="add_btn"/);
  grid.cards[0].onclick();
  assert.equal(added, 0, "paused product cannot be added from its card");
  context.products = [{ ...product }];
  grid.cards = [];
  context.renderItems();
  assert.match(grid.cards[0].innerHTML, /class="add_btn"/);
  grid.cards[0].button.onclick({ stopPropagation() {} });
  assert.equal(added, 1, "available product keeps its add button");
}

console.log("Daily availability cards keep normal add separate from pause and hide the menu plus button");
