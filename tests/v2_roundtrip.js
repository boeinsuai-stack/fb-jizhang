/* 往返测试：旧数据 → migrate → project，必须跟旧数据逐条、逐字段一样。
   用法：node tests/v2_roundtrip.js <fixture.json>（真实数据放仓库外面） */
const fs = require("fs"), path = require("path");
const { migrate, project } = require(path.join(__dirname, "../public/v2.js"));
const old = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const v2 = migrate(old), P = project(v2);
const asMap = (arr) => Object.fromEntries(arr.map((x) => [x.id, x]));
// by_at = 最后写入的时间（毫秒级），不是账目事实，不比
const strip = (x) => { const o = Object.assign({}, x); delete o._v; delete o.id; delete o.by_at; return o; };
const norm = (x) => JSON.stringify(x, Object.keys(x).sort());
let bad = 0;
function cmp(name, oldObj, newArr) {
  const N = asMap(newArr), ids = new Set(Object.keys(oldObj).concat(Object.keys(N)));
  let same = 0; const diff = [];
  for (const id of ids) {
    const a = oldObj[id], b = N[id];
    if (!a || !b) { diff.push([id, a ? "新结构里没有" : "新结构多出来"]); continue; }
    const A = strip(a), B = strip(b), keys = new Set(Object.keys(A).concat(Object.keys(B))), d = [];
    for (const k of keys) if (JSON.stringify(A[k]) !== JSON.stringify(B[k])) d.push(k + ": " + JSON.stringify(A[k]) + " → " + JSON.stringify(B[k]));
    if (d.length) diff.push([id, d.join("; ")]); else same++;
  }
  bad += diff.length;
  console.log((diff.length ? "❌ " : "✅ ") + name + "：" + same + "/" + ids.size + " 条完全一样");
  for (const [id, d] of diff.slice(0, 8)) console.log("    " + id + "  " + d);
}
cmp("流水（现算）", old.movements, P.moves);
cmp("支出（现算）", old.expenses, P.expenses);
cmp("订单（含结账反向指针）", old.orders, P.orders);
cmp("订货（含结账反向指针）", old.purchases, P.purchases);
cmp("往来（含结账反向指针）", old.transfers, P.transfers);
cmp("结账", old.settlements, P.settles);
const n = (o) => Object.values(o || {}).length;
const oldN = ["orders", "movements", "expenses", "purchases", "transfers", "settlements"].reduce((a, c) => a + n(old[c]), 0);
const newN = ["orders", "movements", "expenses", "purchases", "transfers", "settlements", "batches"].reduce((a, c) => a + (v2[c] || []).length, 0);
console.log(`\n存储：旧结构 ${oldN} 条 → 新结构 ${newN} 条（流水 ${n(old.movements)} → ${v2.movements.length}，支出 ${n(old.expenses)} → ${v2.expenses.length}）`);
const patches = v2.orders.concat(v2.purchases, v2.transfers).filter((z) => z.v2);
console.log(`对齐老记录用的小补丁：${patches.length} 处`, patches.slice(0, 6).map((z) => z.id + " " + JSON.stringify(z.v2).slice(0, 120)));
console.log("留在流水里的独立记录：", v2.movements.map((m) => m.id).join(", "));
if (process.argv[3]) fs.writeFileSync(process.argv[3], JSON.stringify(v2, null, 1));
process.exit(bad ? 1 : 0);
