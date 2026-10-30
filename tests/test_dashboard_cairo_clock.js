const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app/frontend/js/orders_dashboard.js', 'utf8');
const start = source.indexOf('    const clock = () => {');
const end = source.indexOf('    clock();', start);
assert.ok(start >= 0 && end > start);
const elements = { ops_current_time: {}, ops_business_date: {} };
class FixedDate extends Date {
  constructor() { super('2026-10-30T12:00:00Z'); }
}
const context = vm.createContext({ Date: FixedDate, document: { getElementById: id => elements[id] } });
vm.runInContext(source.slice(start, end) + 'clock();', context);
const expectedTime = new Date('2026-10-30T12:00:00Z').toLocaleTimeString('ar-EG', { timeZone: 'Africa/Cairo', hour: '2-digit', minute: '2-digit' });
const expectedDate = new Date('2026-10-30T12:00:00Z').toLocaleDateString('ar-EG', { timeZone: 'Africa/Cairo', weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
assert.equal(elements.ops_current_time.textContent, expectedTime);
assert.equal(elements.ops_business_date.textContent, expectedDate);
