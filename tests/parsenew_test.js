/* 粘贴新口味识别（public/orderparse.js 的 parseNew）的测试：编的口味表，GitHub 上也跑。
   1) 各种写法逐条对答案  2) 随机 500 份清单（已有口味 6 个 + 别的系列的口味 4 个，大小写、拼错、编号、根数、价钱、表情）盲测：
      已有的必须全认成「已有」（不会重复加），别的系列的口味在这个系列里不能被当成已有（同一个口味不同拼法除外）
   用真实口味表盲测：node tests/parsenew_test.js <fixture.json>（真实数据放仓库外） */
const path = require("path");
const { parseNew } = require(path.join(__dirname, "../public/orderparse.js"));
let items = [
  ["A1", "Bar Pro", "Banana Buzz", "香蕉"], ["A2", "Bar Pro", "Blueberry Ice", "蓝莓冰"], ["A3", "Bar Pro", "Strawberry Kiwi Ice", "草莓猕猴桃冰"],
  ["A4", "Bar Pro", "Chupa Chupa Strawberry", "草莓棒棒糖"], ["A5", "Bar Pro", "Grape Ice", "葡萄冰"], ["A6", "Bar Pro", "Fruity Skittles", "彩虹糖"],
  ["B1", "Ali", "Banana Buzz", "香蕉"], ["B2", "Ali", "Pink Lemon", "粉红柠檬"], ["B3", "Ali", "Strawberry Kiwi", "草莓奇异果"], ["B4", "Ali", "FTP", "FTP 混合果味"],
  ["B5", "Ali", "Double Apple", "双苹果"], ["B6", "Ali", "Watermelon Ice", "西瓜冰"], ["B7", "Ali", "Chupa Chups Strawberry", "草莓棒棒糖"],
  ["C1", "One", "Peach Mango Watermelon", "桃子芒果西瓜"], ["C2", "One", "Kiwi Pineapple", "奇异果菠萝"], ["C3", "One", "Mixed Berry", "混合莓果"], ["C4", "One", "Cherry Monster", "樱桃怪兽"],
].map(([sku, series, variant, name]) => ({ sku, series, variant, name }));
if (process.argv[2]) items = Object.entries(require(path.resolve(process.argv[2])).items).map(([sku, i]) => ({ sku, series: i.series, variant: i.variant, name: i.name })).filter((i) => i.variant && !/partner pickup/i.test(i.variant));
let fail = 0;
const check = (name, ok, extra) => { if (!ok) fail++; console.log((ok ? "✅ " : "❌ ") + name + (extra ? "  " + extra : "")); };
const sh = (r) => r.list.map((x) => [x.series, x.variant, x.name, x.have || "", x.like || ""].join("|"));

if (!process.argv[2]) {
  const cases = [
    ["一行一个，系列写在上面；编号 / 根数 / 价钱 / 表情去掉；中文写成中文名", "One\n1. Peach Ice 蜜桃冰 x10\n2) Grape Bubblegum $90\n- Sour apple 🍏 2盒", ["One|Peach Ice|蜜桃冰||", "One|Grape Bubblegum|||", "One|Sour Apple|||"]],
    ["已有的标出来（拼错两个字母打反、Lemonade/Lemon 也算），不重复加", "Ali\nwatermelon ice\nDoubel Apple\nPink Lemonade", ["Ali|Watermelon Ice||B6|", "Ali|Doubel Apple||B5|", "Ali|Pink Lemonade||B2|"]],
    ["只差一个词 = 很像（提醒），不算已有", "Bar Pro\nStrawberry Kiwi\nGrape Ice Mint", ["Bar Pro|Strawberry Kiwi|||A3", "Bar Pro|Grape Ice Mint|||A5"]],
    ["只差 Ice 这种弱词也不算有；只共用一个词不算很像", "One\nMixed Berry Ice\nGrape Bubblegum", ["One|Mixed Berry Ice|||C3", "One|Grape Bubblegum|||"]],
    ["逗号 / 顿号分开；同一个写两次只留一个", "Bar Pro: Lemon Lime, lemon lime、Cola Ice", ["Bar Pro|Lemon Lime|||", "Bar Pro|Cola Ice|||"]],
    ["新系列：末尾带冒号的一行", "Lost Mary:\nTriple Mango\nBlue Razz Ice", ["Lost Mary|Triple Mango|||", "Lost Mary|Blue Razz Ice|||"]],
    ["新口味 / New / 新品 这种字去掉", "One 新口味\nNEW Kiwi Pineapple\n新品 Lychee Ice", ["One|Kiwi Pineapple||C2|", "One|Lychee Ice|||"]],
    ["只有中文名也行", "Ali\n葡萄冰\n西瓜冰", ["Ali||葡萄冰||", "Ali||西瓜冰|B6|"]],
    ["全大写的缩写保留（FTP、WTF）", "Ali\nFTP\nWTF", ["Ali|FTP||B4|", "Ali|WTF|||"]],
  ];
  for (const [name, text, want] of cases) { const r = sh(parseNew(text, items)); check(name, JSON.stringify(r) === JSON.stringify(want), JSON.stringify(r)); }
  const r1 = parseNew("Mango Peach\nCola", items);
  check("没写系列又没给默认系列：先不认，列在 skipped", !r1.list.length && r1.skipped.length === 2, JSON.stringify(r1));
  const r2 = parseNew("Mango Peach\nCola", items, { series: "One" });
  check("给了默认系列（界面上选的）：算这个系列", JSON.stringify(sh(r2)) === JSON.stringify(["One|Mango Peach|||C1", "One|Cola|||"]), JSON.stringify(sh(r2)));
}

// 随机盲测
const sers = [...new Set(items.map((i) => i.series))];
let seed = 11; const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648, pick = (a) => a[Math.floor(rnd() * a.length)];
const typo = (w) => { if (w.length < 6 || rnd() < 0.6) return w; const i = 1 + Math.floor(rnd() * (w.length - 3)); return w.slice(0, i) + w[i + 1] + w[i] + w.slice(i + 2); };
const noise = (n) => pick(["", "", "1. ", "- ", "• "]) + pick([n, n, n.toLowerCase(), n.toUpperCase()]).split(" ").map(typo).join(" ") + pick(["", "", " x10", " 2盒", " $70", " 🥭"]);
// 同一个口味的不同拼法（Chupa Chups / Chuppa Chuppa / Chupa Chupa）算同一个
const same = (a, b) => { const k = (s) => (s.toLowerCase().match(/[a-z0-9]+/g) || []).map((t) => (/^chup+[aps]*$/.test(t) ? "chupa" : t)).join(" "); return k(a) === k(b); };
let missOld = 0, wrongHave = 0, nOld = 0, nNew = 0, likeN = 0; const bad = [];
for (let k = 0; k < 500; k++) {
  const sr = pick(sers), pool = items.filter((i) => i.series === sr);
  const old = Array.from({ length: 6 }, () => pick(pool));
  const other = items.filter((i) => i.series !== sr && !pool.some((p) => same(p.variant, i.variant)));
  if (!other.length) continue;
  const nw = Array.from({ length: 4 }, () => pick(other));
  const r = parseNew(sr + "\n" + old.map((i) => noise(i.variant)).concat(nw.map((i) => noise(i.variant))).join("\n"), items);
  for (const i of old) { nOld++; if (!r.list.some((x) => x.have === i.sku)) { missOld++; bad.push("漏认已有 " + sr + " " + i.variant); } }
  for (const i of nw) { nNew++; const x = r.list.find((x) => x.variant && same(x.variant, i.variant)); if (x && x.have) { wrongHave++; bad.push("新的当成已有 " + sr + " " + i.variant + " → " + x.have); } if (x && x.like) likeN++; }
}
check("盲测 500 份：已有的 " + nOld + " 个全认成已有（不会重复加）", missOld === 0, bad.slice(0, 5).join("；"));
check("盲测 500 份：新的 " + nNew + " 个没有被当成已有", wrongHave === 0, bad.slice(0, 5).join("；"));
console.log("   （新的里标「很像」的 " + likeN + " 个，照样勾上，只是提醒）");
console.log(fail ? "\n有 " + fail + " 项没过" : "\n全部通过");
process.exit(fail ? 1 : 0);
