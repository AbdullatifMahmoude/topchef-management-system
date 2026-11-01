const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("app/frontend/cashier/js/cashier.js", "utf8");
const helpers = source.slice(source.indexOf("function pendingCashierOrderStorageKey"), source.indexOf("let _confirmOrderInFlight"));
const modal = source.slice(source.indexOf("function showConfirmModal"), source.indexOf("function cancelOrder()"));
const data = new Map([["user_id", "7"]]);
const localStorage = { getItem: k => data.get(k) || null, setItem: (k,v) => data.set(k,v), removeItem: k => data.delete(k) };
const elements = new Map();
function elem(id) { if (!elements.has(id)) elements.set(id, { id, value: "", checked: false, textContent: "حفظ", style: {}, classList: { toggle() {} }, remove(){}, innerHTML:"" }); return elements.get(id); }
const document = { getElementById: elem, createElement: () => ({ style: {}, appendChild(){}, remove(){}, innerHTML:"" }), body: { appendChild() {} }, querySelectorAll: () => [] };
let calls = [], fail = true;
const context = vm.createContext({ localStorage, document, products: [{id:1, product_name:"meal"}], cart: [{item:{id:1,price:10},qty:2}],
  selectedPaymentMethod: "cash", selectedOfferCode: null, orderType: "takeaway", selectedDelivery: null,
  selectedDeliveryFee: null, selectedDineInFee: null, deliveryCustomerInfo: {phone:null, customerId:null}, console, setTimeout: () => {},
  escapeOrderText: x => String(x), showToast: () => {}, crypto: { randomUUID: () => "new-order-key" },
  apiFetch: async (_path, opts) => { calls.push(JSON.parse(opts.body)); if (fail) throw Error("network"); return {ok:true, json:async()=>({id:1,items:[],order_type:"takeaway"})}; },
  resetDeliveryCustomerInfo(){}, renderCart(){}, renderOrderTypeBadge(){}, renderOrderTypeButtons(){}, renderCashierOffersBoard(){},
  isOnlineOrder: () => false, allOrdersList: [], onlineOrdersList: [], renderAllOrders(){}, renderOnlineOrders(){}, updateOnlineStats(){} });
vm.runInContext(helpers + modal, context);
(async () => {
  context.showConfirmModal({grandTotal: 20, orderType: "takeaway"});
  await elem("btn_confirm_save").onclick();
  const saved = JSON.parse(localStorage.getItem("cashier_pending_order:7"));
  assert.equal(saved.payload.idempotency_key, "new-order-key");
  assert.deepEqual(calls[0], saved.payload);
  fail = false;
  await elem("btn_confirm_save").onclick();
  assert.deepEqual(calls[1], saved.payload);
  assert.equal(localStorage.getItem("cashier_pending_order:7"), null);
  assert.equal(context.cart.length, 0);

  // A later visit recovers the original payload without erasing a new cart.
  localStorage.setItem("cashier_pending_order:7", JSON.stringify(saved));
  context.cart = [{item:{id:1,price:10},qty:3}];
  context.showConfirmModal({grandTotal: 20, orderType: "takeaway"});
  await elem("btn_confirm_save").onclick();
  assert.deepEqual(calls[2], saved.payload);
  assert.equal(context.cart[0].qty, 3);
  assert.equal(localStorage.getItem("cashier_pending_order:7"), null);
})().catch(error => { console.error(error); process.exitCode = 1; });
