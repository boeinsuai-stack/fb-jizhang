/* 把旧数据 fixture 迁移成 v2，生成模拟数据库的种子（v2_* 集合 + meta/schema = 2）。
   用法：node tests/v2_seed.js <旧 fixture.json> <输出 v2 种子.json> */
const fs = require("fs"), path = require("path");
const { migrate, COL } = require(path.join(__dirname, "../public/v2.js"));
const old = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const v2 = migrate(old), out = {};
for (const c of ["items", "customers", "followups"]) out[c] = old[c] || {};
for (const [k, c] of Object.entries(COL)) { out[c] = {}; for (const x of v2[k] || []) { const d = Object.assign({}, x); delete d.id; out[c][x.id] = d; } }
out.meta = { schema: { version: 2 } };
fs.writeFileSync(process.argv[3], JSON.stringify(out));
console.log(Object.fromEntries(Object.entries(out).map(([c, v]) => [c, Object.keys(v).length])));
