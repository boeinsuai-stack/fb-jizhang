/* 订货清单粘贴识别（public/orderparse.js）的测试：编的口味表（几个系列有同名口味），GitHub 上也跑。
   1) 各种写法逐条对答案  2) 随机生成 300 份订单（英文/中文名、大小写、拼错一个字母、各种根数写法、系列写在上面/每行前面/不写）盲测：认错必须是 0
   用真实口味表盲测：node tests/orderparse_test.js <fixture.json>（真实数据放仓库外） */
const path = require("path");
const { parseOrder } = require(path.join(__dirname, "../public/orderparse.js"));
let items = [
  ["A1", "Bar Pro", "Banana Buzz", "香蕉"], ["A2", "Bar Pro", "Blueberry Ice", "蓝莓冰"], ["A3", "Bar Pro", "Blueberry Raspberry", "蓝莓树莓"],
  ["A4", "Bar Pro", "Blueberry Raspberry Bubble Gum", "蓝莓树莓泡泡糖"], ["A5", "Bar Pro", "Strawberry Kiwi Ice", "草莓猕猴桃冰"], ["A6", "Bar Pro", "Fruity Skittles", "果缤纷彩虹糖"],
  ["A7", "Bar Pro", "Chupa Chupa Strawberry", "草莓棒棒糖"], ["A8", "Bar Pro", "Strawberry Watermelon Ice", "草莓西瓜冰"], ["A9", "Bar Pro", "Grape Ice", "葡萄冰"],
  ["B1", "Ali", "Banana Buzz", "香蕉"], ["B2", "Ali", "Pink Lemon", "粉红柠檬"], ["B3", "Ali", "Skittles", "彩虹糖"], ["B4", "Ali", "Strawberry Kiwi", "草莓奇异果"],
  ["B5", "Ali", "Strawberry Watermelon", "草莓西瓜"], ["B6", "Ali", "Strawberry Coconut Watermelon", "草莓椰子西瓜"], ["B7", "Ali", "FTP", "FTP 混合果味"],
  ["B8", "Ali", "Chupa Chups Strawberry", "草莓棒棒糖"], ["B9", "Ali", "Double Apple", "双苹果"], ["B10", "Ali", "Grape Ice", "葡萄冰"],
  ["C1", "One", "Strawberry Kiwi", "草莓猕猴桃"], ["C2", "One", "Blueberry Raspberry", "蓝莓树莓"], ["C3", "One", "Grape Ice", "葡萄冰"], ["C4", "One", "Mixed Berry", "混合莓果"],
].map(([sku, series, variant, name]) => ({ sku, series, variant, name }));
if (process.argv[2]) items = Object.entries(require(path.resolve(process.argv[2])).items).map(([sku, i]) => ({ sku, series: i.series, variant: i.variant, name: i.name })).filter((i) => !/partner pickup/i.test(i.variant || ""));
const by = Object.fromEntries(items.map((i) => [i.sku, i]));
let fail = 0;
const check = (name, ok, extra) => { if (!ok) fail++; console.log((ok ? "✅ " : "❌ ") + name + (extra ? "  " + extra : "")); };
const got = (t, o) => { const r = parseOrder(t, items, o); return { m: Object.fromEntries(r.lines.map((l) => [l.sku, l.qty])), r }; };

if (!process.argv[2]) {
  const cases = [
    ["App 复制出来的格式（系列 + 名字 ×数）", "11月14日\n  Ali Pink Lemon ×2\n  Ali Banana Buzz ×2\n  Ali FTP ×3", { B2: 2, B1: 2, B7: 3 }],
    ["系列写在上面一行，下面几行都算这个系列", "Bar Pro:\nBanana buzz 5\nchupa chups strawberry 2\nfruity skittles x4", { A1: 5, A7: 2, A6: 4 }],
    ["中文名、逗号分开、10根 / 2 支", "Ali 粉柠檬 5，香蕉 3，双苹果10根，FTP 2 支", { B2: 5, B1: 3, B9: 10, B7: 2 }],
    ["一行几种（名字 数字 名字 数字）", "bar pro grape ice 5 blueberry ice 3", { A9: 5, A2: 3 }],
    ["「4 根」的根不会被当成一种口味", "Bar Pro\n蓝莓冰 4 根 葡萄冰 2 支", { A2: 4, A9: 2 }],
    ["根数写在前面", "Bar Pro\n2 x Blueberry Raspberry Bubble Gum\n3 blueberry raspberry", { A4: 2, A3: 3 }],
    ["长的名字优先（Strawberry Kiwi Ice 不当成 Strawberry Kiwi）", "Bar Pro Strawberry Kiwi Ice 4\nOne Strawberry Kiwi 2\nAli Strawberry Kiwi 1", { A5: 4, C1: 2, B4: 1 }],
    ["拼错一个字母、两个字母打反", "Ali\nStrawerry Ccoonut Watermelon 9\nDoubel Apple ×4", { B6: 9, B9: 4 }],
    ["$36、合计行不算", "Bar Pro\nBanana Buzz 5 $36\n合计 5 根", { A1: 5 }],
  ];
  for (const [name, text, want] of cases) { const { m, r } = got(text); check(name, JSON.stringify(m) === JSON.stringify(want), JSON.stringify(m) + (r.unknown.length ? " 没认出 " + JSON.stringify(r.unknown) : "")); }
  { const { r } = got("pink lemon\nfruity skittles 3"); check("没写根数按 1，标出来", r.lines.find((l) => l.sku === "B2").noQty && r.lines.find((l) => l.sku === "B2").qty === 1); }
  { const { m, r } = got("FTP 2\nskittles 3\nbanana buzz 1"); check("没写系列：按这段文字里多数口味的系列定（Ali），并标「猜的」", m.B3 === 3 && m.B1 === 1 && r.lines.find((l) => l.sku === "B1").assumed, JSON.stringify(m)); }
  { const { r } = got("banana buzz 5"); check("同名口味几个系列都有、什么线索都没有 → 认不出（不乱猜）", r.lines.length === 0 && r.unknown.length === 1); }
  { const { m } = got("banana buzz 5", { series: "Ali" }); check("…界面给了当前系列就用它", m.B1 === 5); }
  { const { r } = got("Bar Pro\nPink Lemon 3"); check("上面写了 Bar Pro、这行在 Bar Pro 里没有 → 认不出（不跑去别的系列）", r.lines.length === 0 && r.unknown.length === 1); }
  { const { r } = got("Ali\nStrawberry Zzzz Watermelon 2"); check("有词对不上、又有更长的名字包含其它词 → 认不出（不猜成短的）", r.lines.length === 0); }
  // 盒（2026-11-23）：一盒 10 根
  const box = [
    ["「2盒」「x3盒」「1 box」「2 boxes」「盒 x2」都按盒", "Ali\nPink Lemon 2盒\nFTP x3盒\nBanana Buzz 1 box\nDouble Apple 2 boxes\nSkittles 盒 x2", { B2: 20, B7: 30, B1: 10, B9: 20, B3: 20 }],
    ["中文数字：一盒、两盒、十盒", "Ali\n粉红柠檬 一盒\n香蕉 两盒\n双苹果 十盒", { B2: 10, B1: 20, B9: 100 }],
    ["写了「盒」的清单里没写单位的也按盒", "Ali\nPink Lemon 2盒\nFTP 3\nDouble Apple x1", { B2: 20, B7: 30, B9: 10 }],
    ["盒和根混着写：没写单位的按根", "Ali\nPink Lemon 2盒\nFTP 3根\nDouble Apple 4", { B2: 20, B7: 3, B9: 4 }],
    ["一行几种带盒", "Ali pink lemon 2盒 banana buzz 1盒", { B2: 20, B1: 10 }],
    ["「十二支」中文数字按根", "Ali 粉红柠檬 十二支", { B2: 12 }],
  ];
  for (const [name, text, want] of box) { const { m, r } = got(text); check(name, JSON.stringify(m) === JSON.stringify(want), JSON.stringify(m) + (r.unknown.length ? " 没认出 " + JSON.stringify(r.unknown) : "")); }
  { const r = parseOrder("Ali\nPink Lemon 2盒\nFTP 3", items); check("结果告诉界面：没写单位的按盒算（unit box、有 bare）", r.unit === "box" && r.bare === true && r.lines.find((l) => l.sku === "B2").boxes === 2); }
  { const { m } = got("Ali\nPink Lemon 2盒\nFTP 3", { unit: "pc" }); check("界面切成「按根」：没写单位的 3 → 3 根，写了盒的照样 20", m.B2 === 20 && m.B7 === 3); }
  { const { m } = got("Ali\nPink Lemon 2\nFTP 3", { unit: "box" }); check("界面切成「按盒」：都没写单位的 2、3 → 20、30", m.B2 === 20 && m.B7 === 30); }
  { const { m } = got("Ali\nPink Lemon 2盒", { box: 12 }); check("一盒几根可以改（opts.box）", m.B2 === 24); }
}

// 盲测
let seed = 7; const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
const pick = (a) => a[Math.floor(rnd() * a.length)];
const typo = (w) => { if (w.length < 6) return w; const i = 1 + Math.floor(rnd() * (w.length - 2)), k = rnd(); return k < 0.33 ? w.slice(0, i) + w.slice(i + 1) : k < 0.66 ? w.slice(0, i) + w[i + 1] + w[i] + w.slice(i + 2) : w.slice(0, i) + "e" + w.slice(i + 1); };
const sers = [...new Set(items.map((i) => i.series))];
let ok = 0, wrong = 0, miss = 0, total = 0; const ex = [];
for (let n = 0; n < 300; n++) {
  const sr = pick(sers), pool = items.filter((i) => i.series === sr).sort(() => rnd() - 0.5).slice(0, 2 + Math.floor(rnd() * 5));
  const mode = pick(["header", "prefix", "none"]), lines = mode === "header" ? [pick([sr, sr + ":", "【" + sr + "】"])] : [], want = {};
  for (const it of pool) {
    const q = 1 + Math.floor(rnd() * 12); want[it.sku] = q;
    let name = rnd() < 0.3 ? it.name : it.variant;
    if (name === it.variant) { if (rnd() < 0.5) name = name.toLowerCase(); if (rnd() < 0.25) name = name.split(" ").map((w, k) => (k === 0 ? typo(w) : w)).join(" "); }
    const fmt = pick(["×" + q, "x" + q, String(q), q + "根", q + " 支", "*" + q]);
    lines.push((mode === "prefix" ? sr + " " : "") + name + " " + fmt);
  }
  const r = parseOrder(rnd() < 0.2 ? lines.join("，") : lines.join("\n"), items, { series: mode === "none" ? sr : undefined });
  const m = Object.fromEntries(r.lines.map((l) => [l.sku, l.qty]));
  for (const [sku, q] of Object.entries(want)) { total++; if (m[sku] === q) ok++; else if (m[sku] == null) miss++; else wrong++; }
  for (const sku of Object.keys(m)) if (!(sku in want)) { wrong++; if (ex.length < 5) ex.push(by[sku].series + " " + by[sku].variant + " ← " + JSON.stringify(lines)); }
}
check(`盲测 300 份订单 ${total} 行：认对 ${ok}、认不出 ${miss}、认错 ${wrong}（认错必须是 0，认不出 ≤ 2%）`, wrong === 0 && miss <= total * 0.02, ex.join(" | "));
// 盲测 2：按盒写（2盒 / x2盒 / 2 box / 两盒 / 没写单位但别的行写了盒）→ 根数 = 盒 × 10
{
  const CNN = ["", "一", "两", "三", "四", "五", "六", "七", "八", "九", "十"];
  let ok2 = 0, wrong2 = 0, miss2 = 0, tot2 = 0; const ex2 = [];
  for (let n = 0; n < 300; n++) {
    const sr = pick(sers), pool = items.filter((i) => i.series === sr).sort(() => rnd() - 0.5).slice(0, 2 + Math.floor(rnd() * 5));
    const lines = [sr], want = {};
    pool.forEach((it, k) => {
      const b = 1 + Math.floor(rnd() * 10); want[it.sku] = b * 10;
      const name = rnd() < 0.3 ? it.name : it.variant;
      const f = k === 0 ? pick([b + "盒", b + " 盒", "x" + b + "盒", b + " box", b + " boxes", CNN[b] + "盒"]) : pick([b + "盒", "×" + b + "盒", b + " box", CNN[b] + "盒", String(b), "x" + b]);
      lines.push(name + " " + f);
    });
    const r = parseOrder(lines.join("\n"), items);
    const m = Object.fromEntries(r.lines.map((l) => [l.sku, l.qty]));
    for (const [sku, q] of Object.entries(want)) { tot2++; if (m[sku] === q) ok2++; else if (m[sku] == null) miss2++; else { wrong2++; if (ex2.length < 5) ex2.push(sku + " " + m[sku] + "≠" + q + " ← " + JSON.stringify(lines)); } }
    for (const sku of Object.keys(m)) if (!(sku in want)) wrong2++;
  }
  check(`盲测 300 份按盒写的订单 ${tot2} 行：认对 ${ok2}、认不出 ${miss2}、认错 ${wrong2}（认错必须是 0）`, wrong2 === 0 && miss2 <= tot2 * 0.02, ex2.join(" | "));
}
console.log(fail ? `\n${fail} 项没通过` : "\n全部通过");
process.exit(fail ? 1 : 0);
