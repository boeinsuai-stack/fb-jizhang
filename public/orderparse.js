/* 订货清单粘贴识别：把一段文字（微信消息、App 复制出来的清单……）认成 [{口味, 根数}]。
   - 每行、逗号/顿号分开的每一段 = 一种口味；「Pink Lemon 2 Banana 3」这种一行几种也能拆开
   - 根数：×2 / x2 / *2 / 2支 / 2根 / 2pcs / 末尾的数字；$36、36刀、11月14日 这类不算根数；没写根数按 1（标出来）
   - 系列：一行只写「Ali」「Bar Pro:」= 后面几行都是这个系列；一段里带系列名就用它
   - 口味：英文名逐词比（允许拼错一两个字母、Chups/Chupa 这种），中文名包含或差一个字也算；
     几个口味都对得上时取对上词最多的（Strawberry Kiwi Ice 不会被认成 Strawberry Kiwi）
   - 同名口味在几个系列都有、又没写系列：先看上文的系列，再看这段文字里别的口味大多是哪个系列，再看 opts.series；
     这样定的标 assumed，界面上提醒确认；还是定不了的放 unknown
   parseOrder(text, items, opts) → { lines: [{ sku, qty, noQty, assumed, seg }], unknown: [原文片段] }
   items = [{ sku, series, variant, name }]（不要放「合伙人拿货」这种占位口味） */
(function (root) {
  const CJK = /[㐀-鿿]/;
  const WEAK = new Set(["ice", "iced", "blast", "mist", "bliss", "magic", "soda", "tea", "surge", "rush"]);
  const lower = (s) => String(s || "").toLowerCase().replace(/[’'`]/g, "");
  const enToks = (s) => (lower(s).match(/[a-z0-9]+/g) || []);
  const cjkOf = (s) => (String(s || "").match(/[㐀-鿿]+/g) || []).join("");
  function ed(a, b) { // 编辑距离（相邻两个字母打反也只算一处）
    if (Math.abs(a.length - b.length) > 2) return 9;
    const d = Array.from({ length: a.length + 1 }, (_, i) => [i]);
    for (let j = 1; j <= b.length; j++) d[0][j] = j;
    for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++)
      { d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
        if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) d[i][j] = Math.min(d[i][j], d[i - 2][j - 2] + 1); }
    return d[a.length][b.length];
  }
  const near = (a, b) => a === b || (Math.min(a.length, b.length) >= 4 && (a.startsWith(b) || b.startsWith(a)) && Math.abs(a.length - b.length) <= 3) ||
    (Math.min(a.length, b.length) >= 5 && ed(a, b) <= 1) || (Math.min(a.length, b.length) >= 8 && ed(a, b) <= 2);

  /* 一段文字对一个口味的分数：[覆盖率, 对上的分量, −多出来的词, 能不能算, 拼写完全一样的词数, 对上的词]，越大越好 */
  function score(seg, it) {
    let best = [0, 0, 0, false, 0, []];
    const vt = enToks(it.variant || ""), st = seg.toks;
    if (vt.length) {
      const used = new Set(); let m = 0, strong = false, ex = 0; const hit = [];
      for (const t of vt) { let k = st.findIndex((s, i) => !used.has(i) && s === t); if (k >= 0) ex++; else k = st.findIndex((s, i) => !used.has(i) && near(s, t));
        if (k >= 0) { used.add(k); m++; hit.push(t); if (!WEAK.has(t)) strong = true; } }
      const extra = st.length - used.size;
      // 只对上一部分（比如 Pink Lemon 只对上 lemon）时，多出来的词不能比对上的多，不然宁可认不出
      if (m) best = [m / vt.length, m, -extra, strong && (m === vt.length || extra <= 1), ex, hit];
    }
    const cn = cjkOf(it.name);
    if (cn && seg.cjk) {
      let c = 0, cov;
      if (seg.cjk.includes(cn)) { c = cn.length; cov = 1; }
      else { let p = 0; for (const ch of cn) { const q = seg.cjk.indexOf(ch, p); if (q >= 0) { c++; p = q + 1; } } cov = c / cn.length; }
      const extra = -(seg.cjk.length - c);
      const s = [cov, c / 2, extra, cov >= 0.75, cov === 1 ? 1 : 0, []];
      if (cmp(s, best) > 0) best = s;
    }
    return best;
  }
  const cmp = (a, b) => (a[0] - b[0]) || (a[1] - b[1]) || (a[2] - b[2]) || (a[4] - b[4]);
  const ok = (s) => s[3] && (s[0] === 1 || s[0] >= 0.5);

  function qtyOf(raw) {
    let s = raw.replace(/[$￥¥]\s*\d+(?:\.\d+)?/g, " ").replace(/\d+(?:\.\d+)?\s*(?:刀|元|块|澳币|aud)/gi, " ")
      .replace(/\d{1,2}\s*月\s*\d{1,2}\s*[日号]?/g, " ").replace(/\b\d{1,2}\/\d{1,2}(?:\/\d{2,4})?\b/g, " ");
    const pats = [/[x×*＊]\s*(\d+)/i, /(\d+)\s*(?:支|根|个|條|条|盒|只|pcs?\b)/i, /(\d+)\s*[x×*＊]/i, /(?:^|[^a-z0-9])(\d+)(?=[^a-z0-9]*$)/i, /^\s*(\d+)\b/];
    for (const p of pats) { const m = s.match(p); if (m) return { qty: Number(m[1]), rest: s.replace(m[0], " ") }; }
    return { qty: null, rest: s };
  }

  function parseOrder(text, items, opts) {
    opts = opts || {};
    const sers = [...new Set(items.map((i) => i.series).filter(Boolean))].map((sr) => ({ sr, t: enToks(sr) })).sort((a, b) => b.t.length - a.t.length);
    const findSer = (toks) => { for (const s of sers) for (let i = 0; i + s.t.length <= toks.length; i++) if (s.t.every((t, j) => toks[i + j] === t)) return { sr: s.sr, at: i, n: s.t.length }; return null; };
    const segs = [], unknown = [];
    let ctx = null, carry = null;
    const lines = String(text || "").replace(/\r/g, "").split("\n");
    for (const line of lines) {
      if (/合计|总计|共计|小计|总共|^\s*【.*】\s*$/.test(line)) continue;
      // 一行几段：逗号/顿号/分号；「名字 数字 名字 数字」在数字后面拆开
      const pieces = line.split(/[,，、;；|]/).flatMap((p) => p.replace(/((?:[x×*＊]\s*)?\d+(?:\s*(?:支|根|个|條|条|盒|只|pcs?\b))?)\s+(?=(?![支根个條条盒只])(?!pcs?\b)[A-Za-z㐀-鿿])/gi, "$1\u0001").split("\u0001"));
      for (const raw of pieces) {
        if (!raw.trim()) continue;
        const { qty, rest } = qtyOf(raw);
        let toks = enToks(rest);
        const cj = cjkOf(rest);
        const sh = findSer(toks);
        let sr = null;
        if (sh) { sr = sh.sr; toks = toks.slice(0, sh.at).concat(toks.slice(sh.at + sh.n)); }
        if (!toks.length && !cj) { // 只有系列名 = 下面几行的系列；只有数字 = 下一段的根数
          if (sr) ctx = sr; else if (qty != null) carry = qty;
          continue;
        }
        if (sr) ctx = sr;
        const q = qty != null ? qty : carry; carry = null;
        segs.push({ seg: { toks, cjk: cj }, sr, ctx, qty: q, raw: raw.trim() });
      }
    }
    // 在一组口味里找：分数够、第一名唯一（同一个口味名在几个系列并列算唯一）
    const match = (seg, pool) => {
      const sc = pool.map((it) => ({ it, s: score(seg, it) })).filter((x) => ok(x.s)).sort((a, b) => cmp(b.s, a.s));
      if (!sc.length) return null;
      const top = sc.filter((x) => cmp(x.s, sc[0].s) === 0);
      if (new Set(top.map((x) => lower(x.it.variant || x.it.name))).size > 1) return "tie";
      // 有词没对上、又有更长的口味名包含对上的这几个词（Strawberry ? Watermelon vs Strawberry Coconut Watermelon）→ 不猜
      const b = sc[0].s;
      if (b[2] < 0 && b[5].length && pool.some((it) => { const vt = enToks(it.variant || ""); return vt.length > b[5].length && b[5].every((t) => vt.includes(t)); })) return "tie";
      return top.map((x) => x.it);
    };
    const inSer = (sr) => items.filter((i) => i.series === sr);
    // 第一遍：写了系列 / 有上文系列的在那个系列里找，其余在全部里找；数一数这段文字主要是哪个系列
    // 上文写了系列：只在这个系列里找（对不上宁可认不出，不跑去别的系列）
    const first = segs.map((g) => { const sr = g.sr || g.ctx; return sr ? match(g.seg, inSer(sr)) : match(g.seg, items); });
    const cnt = {}; first.forEach((m) => { if (m && m !== "tie" && m.length === 1) cnt[m[0].series] = (cnt[m[0].series] || 0) + 1; });
    const major = (Object.entries(cnt).sort((a, b) => b[1] - a[1])[0] || [])[0] || null;
    const res = {}, order = [];
    segs.forEach((g, k) => {
      let m = first[k], assumed = false;
      // 没写系列、上文也没有：先在这段文字的主要系列里找（Bar Pro 清单里的「skittles」= Fruity Skittles）
      if (!g.sr && !g.ctx && major) { const mm = match(g.seg, inSer(major)); if (mm && mm !== "tie") { assumed = !(m && m !== "tie" && m.length === 1 && m[0].series === major); m = mm; } }
      if (!m || m === "tie") { unknown.push(g.raw); return; }
      let it = m[0];
      if (m.length > 1) { it = m.find((c) => c.series === (g.sr || g.ctx)) || m.find((c) => c.series === major) || m.find((c) => c.series === opts.series) || null; assumed = true; }
      if (!it) { unknown.push(g.raw); return; }
      const noQty = g.qty == null, qty = noQty ? 1 : g.qty;
      if (!res[it.sku]) { res[it.sku] = { sku: it.sku, qty: 0, noQty: false, assumed: false, seg: g.raw }; order.push(it.sku); }
      res[it.sku].qty += qty; res[it.sku].noQty = res[it.sku].noQty || noQty; res[it.sku].assumed = res[it.sku].assumed || assumed;
    });
    return { lines: order.map((k) => res[k]).filter((l) => l.qty > 0), unknown };
  }

  const api = { parseOrder };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.FBParse = api;
})(typeof window !== "undefined" ? window : globalThis);
