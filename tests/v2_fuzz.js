/* 随机压力测试（model-based）：从一份数据出发，随机生成几千次「旧样子」的写入（模仿各种记账动作的写法），
   同时写进 ① 一份直接存旧样子的数据（= 旧版的行为）② v2 翻译层（只存源头）。
   每写一次就比较：v2 现算出来的旧样子 必须 == ①。另外统计 v2 实际存了多少条。
   用法：node tests/v2_fuzz.js <旧 fixture.json> [次数=3000] [随机种子=1] */
const fs = require("fs"), path = require("path");
const { migrate, createStore, COL } = require(path.join(__dirname, "../public/v2.js"));
const old = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const N = Number(process.argv[3] || 3000);
let seed = Number(process.argv[4] || 1);
const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
const pick = (a) => a[Math.floor(rnd() * a.length)];
const clone = (x) => JSON.parse(JSON.stringify(x));

// ① 旧样子：直接存
const V1 = {}; for (const c of ["orders", "movements", "expenses", "purchases", "transfers", "settlements"]) V1[c] = clone(old[c] || {});
const items = Object.entries(old.items || {}).map(([sku, x]) => Object.assign({ sku }, x));
// ② v2：假的数据库（内存），开始时装进迁移后的数据
const v2 = migrate(old), DB = {};
const KEY = { orders: "orders", purchases: "purchases", transfers: "transfers", movements: "movements", expenses: "expenses", batches: "batches", settlements: "settlements" };
for (const [k, c] of Object.entries(COL)) { DB[c] = {}; for (const x of v2[k] || []) { const d = clone(x); delete d.id; DB[c][x.id] = d; } }
const fakeDb = { collection: (c) => ({
  onSnapshot: (cb) => { cb({ docs: Object.entries(DB[c] || {}).map(([id, d]) => ({ id, data: () => clone(d) })) }); return () => {}; },
  doc: (id) => ({ set: (d) => { (DB[c] = DB[c] || {})[id] = clone(d); return Promise.resolve(); }, delete: () => { delete (DB[c] || {})[id]; return Promise.resolve(); } }) }) };
const store = createStore(fakeDb, () => items, () => {});

const strip = (x) => { const o = clone(x); delete o._v; delete o.id; delete o.by_at; return o; };
const VIEWK = { orders: "orders", movements: "moves", expenses: "expenses", purchases: "purchases", transfers: "transfers", settlements: "settles" };
function compare() {
  const P = store.view(), bad = [];
  for (const [c, k] of Object.entries(VIEWK)) {
    const A = V1[c], B = Object.fromEntries(P[k].map((x) => [x.id, x]));
    for (const id of new Set(Object.keys(A).concat(Object.keys(B)))) {
      const a = A[id] ? strip(Object.assign({ id }, A[id])) : null, b = B[id] ? strip(B[id]) : null;
      if (JSON.stringify(sortKeys(a)) !== JSON.stringify(sortKeys(b))) bad.push(c + "/" + id + "  不一样的字段：" + (a && b ? [...new Set(Object.keys(a).concat(Object.keys(b)))].filter((f) => JSON.stringify(a[f]) !== JSON.stringify(b[f])).map((f) => f + " 旧=" + JSON.stringify(a[f]) + " 新=" + JSON.stringify(b[f])).join("；") : a ? "新结构里没有" : "新结构多出来"));
    }
  }
  return bad;
}
const sortKeys = (x) => (x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.keys(x).sort().map((k) => [k, sortKeys(x[k])])) : Array.isArray(x) ? x.map(sortKeys) : x);

let n = 0; const LOG = [];
async function w(c, id, op, data) {
  LOG.push(op + " " + c + "/" + id + " " + (data ? JSON.stringify(data).slice(0, 140) : "")); if (LOG.length > 6) LOG.shift();
  if (op === "update" && !V1[c][id]) return;
  await store.write(c, id, op, data == null ? data : clone(data));
  if (op === "delete") delete V1[c][id];
  else if (op === "update") V1[c][id] = Object.assign({}, V1[c][id], clone(data));
  else V1[c][id] = clone(data);
  n++;
}
const ids = (c) => Object.keys(V1[c]);
const day = () => "2026-11-" + String(10 + Math.floor(rnd() * 5)).padStart(2, "0");
let k = 0; const nid = (p) => p + "-202611" + String(10 + (k % 5)).padStart(2, "0") + "-fz" + (k++).toString(36);
const skus = items.map((i) => i.sku), partners = ["合伙人甲", "合伙人乙"];

// 各种动作的写法
const ACTIONS = {
  // 卖出：订单 → 出库 → （缺货）找谁拿 → 拿货流水 → 拿货支出
  async sale() {
    const oid = nid("o"), at = day() + "T02:00:00.000Z", date = at.slice(0, 10);
    const ls = [...new Set([pick(skus), pick(skus)])].map((sku) => ({ sku, name: "n" + sku, qty: 1 + Math.floor(rnd() * 3), unit_price: 30 + Math.floor(rnd() * 40) }));
    const resv = rnd() < 0.3;
    await w("orders", oid, "set", { status: resv ? "reserved" : "paid", date, at, lines: ls, delivery_fee: rnd() < 0.3 ? 5 : 0, note: "", payment: resv ? null : "现金", by: "u", created_by: "u" });
    if (!resv) for (const l of ls) await w("movements", oid + "-" + l.sku, "set", { type: "out", sku: l.sku, name: l.name, qty: l.qty, date, at, order_id: oid });
    if (rnd() < 0.6) {
      const who = pick(partners); await w("orders", oid, "update", { pick_from: who });
      let tot = 0; const bid = oid + "-pick";
      for (const l of ls) { const c = 20 * l.qty; tot += c; const m = { type: "in", sku: l.sku, name: l.name, qty: l.qty, date, at, order_id: oid, batch_id: bid, cost: c, expense_id: bid + "-cost", note: "按单向合伙人拿货" }; if (rnd() < 0.3) m.partner = pick(partners); await w("movements", bid + "-" + l.sku, "set", m); }
      if (rnd() < 0.9) await w("expenses", bid + "-cost", "set", { date, at, amount: tot, category: "进货成本", note: "按单拿货 x", batch_id: bid });
    }
  },
  // 改订单（价格、备注、日期、客户）
  async editOrder() { const id = pick(ids("orders")); await w("orders", id, "update", pick([{ note: "改" + k++ }, { delivery_fee: 10 }, { customer: "客" + k++ }, { date: day() }, { lines: (V1.orders[id].lines || []).map((l) => Object.assign({}, l, { unit_price: (l.unit_price || 0) + 1 })) }])); },
  // 撤销订单：先删流水、支出，再删订单（或反过来）
  async voidOrder() {
    const id = pick(ids("orders")), rev = rnd() < 0.5;
    if (rev) await w("orders", id, "delete");
    for (const m of ids("movements")) if (V1.movements[m] && V1.movements[m].order_id === id) await w("movements", m, "delete");
    for (const x of ids("expenses")) if (V1.expenses[x] && V1.expenses[x].batch_id === id + "-pick") await w("expenses", x, "delete");
    if (!rev && V1.orders[id]) await w("orders", id, "delete");
  },
  // 改拿货：成本、找谁拿、数量；或者把拿到的货从订单上拿下来（留作库存）
  async editPick() {
    const ms = ids("movements").filter((m) => /-pick-/.test(m) && V1.movements[m].order_id); if (!ms.length) return;
    const id = pick(ms); await w("movements", id, "update", pick([{ cost: 25 }, { partner: pick(partners) }, { qty: 2 }, { order_id: null, note: "预定改了，拿到的货留作库存" }, { date: day() }]));
    const bid = V1.movements[id] && V1.movements[id].batch_id; if (bid && V1.expenses[bid + "-cost"] && rnd() < 0.5) await w("expenses", bid + "-cost", "update", { amount: 99 });
  },
  // 改出库数量（编辑已卖订单不让改数量，但防万一）
  async editOut() { const ms = ids("movements").filter((m) => V1.movements[m].type === "out"); if (ms.length) await w("movements", pick(ms), "update", pick([{ date: day() }, { qty: 3 }])); },
  // 合伙人往来：往来单 → 调入/调出流水；撤销
  async xfer() {
    const tid = nid("t"), date = day(), who = pick(partners), i = [{ sku: pick(skus), qty: 2, unit: 30 }], o = rnd() < 0.5 ? [{ sku: pick(skus), qty: 1, unit: 30 }] : [];
    await w("transfers", tid, "set", { date, partner: who, in: i, out: o, note: "" });
    for (const l of i) await w("movements", tid + "-in-" + l.sku, "set", { type: "in", sku: l.sku, qty: l.qty, cost: l.qty * l.unit, date, transfer_id: tid, note: "合伙人往来：" + who + " 给的" });
    for (const l of o) await w("movements", tid + "-out-" + l.sku, "set", { type: "adjust", sku: l.sku, qty: -l.qty, date, transfer_id: tid, note: "合伙人往来：给 " + who });
  },
  async voidXfer() { const id = pick(ids("transfers")); for (const m of ids("movements")) if (V1.movements[m] && V1.movements[m].transfer_id === id) await w("movements", m, "delete"); await w("transfers", id, "delete"); },
  // 订货：订货单 → 付款支出；到货：到货流水；撤销到货
  async po() {
    const pid = nid("p"), date = day(), ls = [{ sku: pick(skus), qty: 5, unit_cost: 20, series: "One" }];
    // 一半的订货单再加一行「只订系列、到货时才分口味」（sku 为 null）；2026-11-07 真实数据里第一次出现，之前没测到
    if (rnd() < 0.5) ls.push({ series: pick(["One", "Bar"]), sku: null, name: "系列（口味到货再分）", qty: 10, unit_cost: 55 });
    await w("purchases", pid, "set", { date, supplier: pick(partners), lines: ls, total: 100, paid: rnd() < 0.5, paid_date: date, payment: "现金", note: "" });
    await w("expenses", pid + "-pay", "set", { date, amount: 100, category: "进货成本", note: "订货 x", po_id: pid });
  },
  async receive() {
    const ps = ids("purchases"); if (!ps.length) return; const pid = pick(ps), p = V1.purchases[pid], rc = "r" + (k++).toString(36);
    for (const l of p.lines || []) if (l.sku) await w("movements", pid + "-" + rc + "-" + l.sku, "set", { type: "in", sku: l.sku, qty: 2, cost: 2 * (l.unit_cost || 0), date: day(), po_id: pid, po_line: l.sku, receipt_id: rc, note: "订货到货" });
    // 系列行：到货时分到 1–2 个口味，编号多一个 -s-；有时故意跟指定口味的行撞同一个口味
    for (const l of p.lines || []) if (!l.sku && l.series) {
      const fixed = (p.lines.find((x) => x.sku) || {}).sku, ss = [rnd() < 0.3 && fixed ? fixed : pick(skus), pick(skus)].filter((x, i, a) => a.indexOf(x) === i).slice(0, 1 + Math.floor(rnd() * 2));
      for (const sku of ss) { const it = items.find((i) => i.sku === sku); await w("movements", pid + "-" + rc + "-s-" + sku, "set", { type: "in", sku, name: (it && it.name) || sku, qty: 3, date: day(), po_id: pid, po_line: "series:" + l.series, receipt_id: rc, cost: 3 * l.unit_cost, note: "订货到货" }); }
    }
  },
  async voidReceipt() { const ms = ids("movements").filter((m) => V1.movements[m].receipt_id); if (!ms.length) return; const r = V1.movements[pick(ms)]; for (const m of ids("movements")) if (V1.movements[m] && V1.movements[m].receipt_id === r.receipt_id && V1.movements[m].po_id === r.po_id) await w("movements", m, "delete"); },
  async poPay() { const ps = ids("purchases"); if (ps.length) await w("purchases", pick(ps), "update", { paid: true, paid_date: day(), payment: "PayID" }); },
  // 结账：结账单 + 每张单上的反向指针；撤销结账
  async settle() {
    const who = pick(partners), sid = nid("s");
    const os = ids("orders").filter((o) => V1.orders[o].pick_from && !V1.orders[o].partner_settlement_id && !V1.orders[o].pick_split).slice(0, 3);
    const ts = ids("transfers").filter((t) => !V1.transfers[t].partner_settlement_id).slice(0, 2);
    if (!os.length && !ts.length) return;
    await w("settlements", sid, "set", { date: day(), partner: who, order_ids: os, transfer_ids: ts, amount: 50, paid: 50, payment: "现金", qty: {}, note: "" });
    for (const o of os) await w("orders", o, "update", { partner_settlement_id: sid });
    for (const t of ts) await w("transfers", t, "update", { partner_settlement_id: sid });
  },
  async unsettle() {
    const ss = ids("settlements"); if (!ss.length) return; const sid = pick(ss), s = V1.settlements[sid];
    // 跟 App 的 unsettle() 一样的写法：改成 null、分开拿的单从 partner_settlements 里删掉这次结账（可能剩下空的 {}）、订货改回未付
    for (const o of ids("orders")) if (V1.orders[o].partner_settlement_id === sid) await w("orders", o, "update", { partner_settlement_id: null });
    for (const o of ids("orders")) if (Object.values(V1.orders[o].partner_settlements || {}).includes(sid)) { const mp = Object.assign({}, V1.orders[o].partner_settlements); for (const k of Object.keys(mp)) if (mp[k] === sid) delete mp[k]; await w("orders", o, "update", { partner_settlements: mp }); }
    for (const t of ids("transfers")) if (V1.transfers[t].partner_settlement_id === sid) await w("transfers", t, "update", { partner_settlement_id: null });
    for (const p of ids("purchases")) if (V1.purchases[p].settlement_id === sid) await w("purchases", p, "update", { paid: false, paid_date: null, settlement_id: null });
    await w("settlements", sid, "delete");
  },
  // 独立的：盘点调整、手动支出、早期整批进货改成本
  async adjust() { await w("movements", nid("m"), "set", { type: "adjust", sku: pick(skus), qty: rnd() < 0.5 ? -1 : 1, date: day(), note: "盘点" }); },
  async expense() { await w("expenses", nid("e"), "set", { date: day(), amount: 12.5, category: pick(["油费", "广告", "进货成本"]), note: "x" }); },
  async batchCost() { const ms = ids("movements").filter((m) => m.startsWith("b-")); if (!ms.length) return; const id = pick(ms); await w("movements", id, "update", { cost: 33 }); const b = V1.movements[id].batch_id; if (V1.expenses[b + "-cost"]) await w("expenses", b + "-cost", "update", { amount: 777 }); },
  async delMove() { const id = pick(ids("movements")); await w("movements", id, "delete"); },
  async delExpense() { const xs = ids("expenses"); if (xs.length) await w("expenses", pick(xs), "delete"); },
};
const W = Object.entries({ sale: 8, editOrder: 3, voidOrder: 2, editPick: 3, editOut: 1, xfer: 2, voidXfer: 1, po: 1, receive: 2, voidReceipt: 1, poPay: 1, settle: 2, unsettle: 1, adjust: 1, expense: 2, batchCost: 1, delMove: 1, delExpense: 1 });
const tot = W.reduce((a, [, x]) => a + x, 0);
const choose = () => { let r = rnd() * tot; for (const [a, x] of W) { if ((r -= x) < 0) return a; } return W[0][0]; };

(async () => {
  const b0 = compare();
  console.log(b0.length ? "❌ 开始就不一致 " + b0.length : "✅ 开始：一致");
  const cnt = {};
  for (let i = 0; i < N; i++) {
    const a = choose(); cnt[a] = (cnt[a] || 0) + 1;
    const before = n;
    try { await ACTIONS[a](); } catch (e) { console.log("❌ 第 " + i + " 个动作 " + a + " 出错：", e.message); process.exit(1); }
    if (n === before) continue;
    const bad = compare();
    if (bad.length) { console.log("❌ 第 " + i + " 个动作「" + a + "」之后不一致（" + bad.length + " 处）："); bad.slice(0, 4).forEach((x) => console.log("   " + x)); console.log("   最后几次写入："); LOG.forEach((x) => console.log("     " + x)); process.exit(1); }
  }
  const stored = Object.fromEntries(Object.entries(DB).map(([c, m]) => [c, Object.keys(m).length]));
  const v1n = Object.values(V1).reduce((a, m) => a + Object.keys(m).length, 0), v2n = Object.values(stored).reduce((a, x) => a + x, 0);
  const dupM = Object.keys(DB.v2_movements).filter((id) => { const m = DB.v2_movements[id]; return (m.order_id && V1.orders[m.order_id] && (/-pick-/.test(id) || m.type === "out")) || (m.transfer_id && V1.transfers[m.transfer_id]) || (m.po_id && V1.purchases[m.po_id]); });
  console.log(`✅ ${N} 个随机动作（共 ${n} 次写入）之后，新版现算出来的跟旧版直接存的完全一样`);
  console.log("   动作次数：", JSON.stringify(cnt));
  console.log(`   存储：旧样子 ${v1n} 条，v2 实际存 ${v2n} 条`, JSON.stringify(stored));
  console.log(dupM.length ? `❌ v2 存了 ${dupM.length} 条本该归源头的流水：${dupM.slice(0, 5)}` : "✅ v2 没有存任何归源头的流水");
  process.exit(dupM.length ? 1 : 0);
})();
