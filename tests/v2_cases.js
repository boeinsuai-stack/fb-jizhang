/* v2 边角情况（编的小数据，不含真实信息，GitHub 上也跑）：
   ① 按系列订货、到货时才分口味（编号多一个 -s-，po_line = "series:系列"），而且同一次到货里跟「指定口味」的行撞同一个口味
   ② 认不出编号写法的到货流水：必须原样留下当独立的事，不能丢
   ③ 撤销结账留下的空指针（null、空的 {}）
   然后在这份数据上跑 往返测试 + 随机写入压力测试（3 个种子）。
   2026-11-10：真实数据第一次出现 ①，旧代码迁移检查算出库存 96 → 21（14 条到货被当成多余丢掉），被「检查迁移」拦下。
   用法：node tests/v2_cases.js */
const fs = require("fs"), os = require("os"), path = require("path"), { execFileSync } = require("child_process");
const { migrate, project } = require(path.join(__dirname, "../public/v2.js"));
const A = "合伙人甲", B = "合伙人乙", at = (d) => d + "T02:00:00.000Z";
const items = {};
["XF-01", "XF-02", "XF-03"].forEach((s, i) => { items[s] = { sku: s, series: "One", variant: "One " + i, name: "一号" + i, price_aud: 60, cost_aud: 55, status: "在售" }; });
["XF-04", "XF-05", "XF-06"].forEach((s, i) => { items[s] = { sku: s, series: "Bar", variant: "Bar " + i, name: "二号" + i, price_aud: 50, cost_aud: 40, status: "在售" }; });
const P1 = "p-20261102-ser1", R1 = "rcase1", R2 = "rcase2";
const fx = {
  items,
  orders: {
    // 撤销过结账：partner_settlement_id 留下 null
    "o-20261101-a1": { date: "2026-11-01", at: at("2026-11-01"), status: "sold", customer: "客一", lines: [{ sku: "XF-01", name: "一号0", qty: 2, unit_price: 60 }], total: 120, pick_from: A, partner_settlement_id: null },
    // 分开拿、撤销过结账：partner_settlements 剩下空的 {}
    "o-20261101-a2": { date: "2026-11-01", at: at("2026-11-01"), status: "sold", customer: "客二", lines: [{ sku: "XF-04", name: "二号0", qty: 2, unit_price: 50 }], total: 100, pick_from: A, pick_split: {}, partner_settlements: {} },
    "o-20261103-a3": { date: "2026-11-03", at: at("2026-11-03"), status: "sold", customer: "客三", lines: [{ sku: "XF-03", name: "一号2", qty: 1, unit_price: 60 }], total: 60 },
  },
  movements: {
    "o-20261101-a1-XF-01": { type: "out", sku: "XF-01", name: "一号0", qty: 2, date: "2026-11-01", at: at("2026-11-01"), order_id: "o-20261101-a1" },
    "o-20261101-a1-pick-XF-01": { type: "in", sku: "XF-01", name: "一号0", qty: 2, cost: 110, date: "2026-11-01", order_id: "o-20261101-a1", note: "按单向合伙人拿货" },
    "o-20261101-a2-XF-04": { type: "out", sku: "XF-04", name: "二号0", qty: 2, date: "2026-11-01", at: at("2026-11-01"), order_id: "o-20261101-a2" },
    "o-20261101-a2-pick-XF-04": { type: "in", sku: "XF-04", name: "二号0", qty: 1, cost: 40, date: "2026-11-01", order_id: "o-20261101-a2", partner: A, note: "按单向合伙人拿货" },
    "o-20261101-a2-pick-XF-04-k2": { type: "in", sku: "XF-04", name: "二号0", qty: 1, cost: 40, date: "2026-11-01", order_id: "o-20261101-a2", partner: B, note: "按单向合伙人拿货" },
    "o-20261103-a3-XF-03": { type: "out", sku: "XF-03", name: "一号2", qty: 1, date: "2026-11-03", at: at("2026-11-03"), order_id: "o-20261103-a3" },
    // ① 同一次到货：指定口味 XF-02 ×5，系列 One 分到 XF-02 ×3（撞口味）、XF-03 ×7
    [P1 + "-" + R1 + "-XF-02"]: { type: "in", sku: "XF-02", name: "一号1", qty: 5, date: "2026-11-04", at: at("2026-11-04"), po_id: P1, po_line: "XF-02", receipt_id: R1, cost: 100, note: "订货到货" },
    [P1 + "-" + R1 + "-s-XF-02"]: { type: "in", sku: "XF-02", name: "一号1", qty: 3, date: "2026-11-04", at: at("2026-11-04"), po_id: P1, po_line: "series:One", receipt_id: R1, cost: 165, note: "订货到货" },
    [P1 + "-" + R1 + "-s-XF-03"]: { type: "in", sku: "XF-03", name: "一号2", qty: 7, date: "2026-11-04", at: at("2026-11-04"), po_id: P1, po_line: "series:One", receipt_id: R1, cost: 385, note: "订货到货" },
    // ② 认不出的编号写法
    [P1 + "-" + R2 + "-x-XF-01"]: { type: "in", sku: "XF-01", name: "一号0", qty: 4, date: "2026-11-05", po_id: P1, po_line: "XF-01", receipt_id: R2, cost: 1, note: "订货到货" },
    "m-20261105-adj1": { type: "adjust", sku: "XF-05", qty: 3, date: "2026-11-05", note: "盘点" },
  },
  expenses: {
    "o-20261101-a1-pick-cost": { category: "进货成本", amount: 110, date: "2026-11-01", batch_id: "o-20261101-a1-pick", note: "按单拿货 One 0 ×2" },
    "o-20261101-a2-pick-cost": { category: "进货成本", amount: 80, date: "2026-11-01", batch_id: "o-20261101-a2-pick", note: "按单拿货 Bar 0 ×2" },
    [P1 + "-pay"]: { category: "进货成本", amount: 650, date: "2026-11-02", po_id: P1, note: "订货 一号1 ×5、One（口味到货再分） ×10" },
    "e-20261105-oil": { category: "油费", amount: 20, date: "2026-11-05", note: "油" },
  },
  purchases: {
    // ③ 撤销过结账的订货：settlement_id 留下 null
    [P1]: { date: "2026-11-02", at: at("2026-11-02"), supplier: A, lines: [{ sku: "XF-02", name: "一号1", qty: 5, unit_cost: 20 }, { series: "One", sku: null, name: "One（口味到货再分）", qty: 10, unit_cost: 55 }], total: 650, paid: false, paid_date: null, settlement_id: null, note: "" },
  },
  transfers: {},
  settlements: {
    "s-20261106-x1": { date: "2026-11-06", partner: A, order_ids: ["o-20261101-a1"], transfer_ids: [], po_ids: [], amount: 110, paid: 110, payment: "现金", qty: {}, note: "" },
  },
  customers: {}, followups: {},
};
// 结账 x1 结了 a1 → a1 上的指针应该是 x1（这条用来确认「空指针补丁」不会盖掉真的指针）
fx.orders["o-20261101-a1"].partner_settlement_id = "s-20261106-x1";
fx.orders["o-20261103-a3"].partner_settlement_id = null;

let fail = 0;
const ok = (c, msg) => { console.log((c ? "✅ " : "❌ ") + msg); if (!c) fail++; };
const v2 = migrate(JSON.parse(JSON.stringify(fx))), P = project(v2);
const mv = Object.fromEntries(P.moves.map((m) => [m.id, m]));
ok(!v2.movements.some((m) => m.id.includes("-s-")), "系列到货归到订货单上（不留在独立流水里）");
ok(v2.movements.some((m) => m.id === P1 + "-" + R2 + "-x-XF-01"), "认不出的到货流水原样留下当独立的事");
const s2 = mv[P1 + "-" + R1 + "-s-XF-02"], f2 = mv[P1 + "-" + R1 + "-XF-02"];
ok(s2 && s2.qty === 3 && s2.po_line === "series:One" && s2.cost === 165 && f2 && f2.qty === 5 && f2.cost === 100, "同一次到货里 指定口味 / 系列 撞同一个口味，两条都算得出来、互不覆盖");
const stock = (moves) => { const st = {}; for (const m of moves) st[m.sku] = (st[m.sku] || 0) + (m.type === "out" ? -m.qty : m.qty); return st; };
ok(JSON.stringify(stock(Object.values(fx.movements))) === JSON.stringify(stock(P.moves.slice().sort((a, b) => (a.id < b.id ? -1 : 1)))) || JSON.stringify(Object.entries(stock(Object.values(fx.movements))).sort()) === JSON.stringify(Object.entries(stock(P.moves)).sort()), "每个口味的进出合计 新旧一样");
const o3 = P.orders.find((o) => o.id === "o-20261103-a3"), o2 = P.orders.find((o) => o.id === "o-20261101-a2"), o1 = P.orders.find((o) => o.id === "o-20261101-a1"), p1 = P.purchases.find((p) => p.id === P1);
ok(o3.partner_settlement_id === null && JSON.stringify(o2.partner_settlements) === "{}" && p1.settlement_id === null && o1.partner_settlement_id === "s-20261106-x1", "撤销结账留下的 null / {} 照原样算出来，真的结账指针不受影响");

const tmp = path.join(os.tmpdir(), "fbjz-v2-cases.json");
fs.writeFileSync(tmp, JSON.stringify(fx));
const run = (args) => { try { execFileSync("node", args, { stdio: "pipe" }); return true; } catch (e) { console.log(String(e.stdout || "").split("\n").filter((l) => /❌|新结构|字段/.test(l)).slice(0, 6).join("\n")); return false; } };
ok(run([path.join(__dirname, "v2_roundtrip.js"), tmp]), "往返：迁移再算回来，逐条逐字段一样");
for (const seed of [1, 2, 3]) ok(run([path.join(__dirname, "v2_fuzz.js"), tmp, "1500", String(seed)]), "随机写入压力测试 1500 步 · 种子 " + seed + "（含系列订货、跟 App 一样写法的撤销结账）");
console.log(fail ? fail + " 项没通过" : "全部通过");
process.exit(fail ? 1 : 0);
