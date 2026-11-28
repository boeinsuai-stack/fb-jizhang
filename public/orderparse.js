/* 订货清单粘贴识别：把一段文字（微信消息、App 复制出来的清单……）认成 [{口味, 根数}]。
   - 每行、逗号/顿号分开的每一段 = 一种口味；「Pink Lemon 2 Banana 3」这种一行几种也能拆开
   - 根数：×2 / x2 / *2 / 2支 / 2根 / 2pcs / 末尾的数字；$36、36刀、11月14日 这类不算根数；没写根数按 1（标出来）
   - 盒（2026-11-23）：2盒 / x2盒 / 2 box(es) / 2bx / 盒 x2 / 一盒、两盒、十盒 → × opts.box（默认 10 根一盒）；
     没写单位的数字：opts.unit（"box" / "pc"）；没给就看这段文字——有写「盒」、没有写「根 / 支」的，按盒；不然按根。结果里 unit 告诉界面按什么算的
   - 系列：一行只写「Ali」「Bar Pro:」= 后面几行都是这个系列；一段里带系列名就用它
   - 口味：英文名逐词比（允许拼错一两个字母、Chups/Chupa 这种），中文名包含或差一个字也算；
     几个口味都对得上时取对上词最多的（Strawberry Kiwi Ice 不会被认成 Strawberry Kiwi）
   - 同名口味在几个系列都有、又没写系列：先看上文的系列，再看这段文字里别的口味大多是哪个系列，再看 opts.series；
     这样定的标 assumed，界面上提醒确认；还是定不了的放 unknown
   parseOrder(text, items, opts) → { lines: [{ sku, qty, noQty, assumed, seg, boxes }], unknown: [原文片段], unit: "box"|"pc", bare: 有没有没写单位的数字 }
   （qty 一律是根数；boxes = 按盒写的那部分是几盒）
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

  /* 中文数字：一盒、两根、十二盒、二十支 → 1 盒、2 根… */
  const CN = { 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 };
  const cnNum = (t) => { if (t === "十") return 10; const m = /^([一二两三四五六七八九])?十([一二三四五六七八九])?$/.exec(t); if (m) return (m[1] ? CN[m[1]] : 1) * 10 + (m[2] ? CN[m[2]] : 0); return t.length === 1 ? CN[t] : null; };
  const cnDigits = (s) => s.replace(/([一二两三四五六七八九十]{1,3})\s*(?=盒|根|支|个|條|条|只)/g, (m0, t) => { const n = cnNum(t); return n == null ? m0 : String(n); });
  const BOX = "盒|boxes|box|bx", PC = "支|根|个|條|条|只|pcs|pc";
  const unitOf = (u) => (!u ? null : new RegExp("^(?:" + BOX + ")$", "i").test(u) ? "box" : "pc");
  function qtyOf(raw) {
    let s = cnDigits(raw).replace(/[$￥¥]\s*\d+(?:\.\d+)?/g, " ").replace(/\d+(?:\.\d+)?\s*(?:刀|元|块|澳币|aud)/gi, " ")
      .replace(/\d{1,2}\s*月\s*\d{1,2}\s*[日号]?/g, " ").replace(/\b\d{1,2}\/\d{1,2}(?:\/\d{2,4})?\b/g, " ");
    const U = "(" + BOX + "|" + PC + ")(?![a-z])", UO = "(?:" + U + ")?";
    const pats = [[new RegExp("(" + BOX + ")\\s*[x×*＊]\\s*(\\d+)", "i"), 2, 1], [new RegExp("[x×*＊]\\s*(\\d+)\\s*" + UO, "i"), 1, 2], [new RegExp("(\\d+)\\s*" + U, "i"), 1, 2],
      [/(\d+)\s*[x×*＊]/i, 1, 0], [/(?:^|[^a-z0-9])(\d+)(?=[^a-z0-9]*$)/i, 1, 0], [/^\s*(\d+)\b/, 1, 0]];
    for (const [p, qi, ui] of pats) { const m = s.match(p); if (m) return { qty: Number(m[qi]), unit: ui ? unitOf(m[ui]) : null, rest: s.replace(m[0], " ") }; }
    return { qty: null, unit: null, rest: s };
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
      const pieces = cnDigits(line).split(/[,，、;；|]/).flatMap((p) => p.replace(/((?:[x×*＊]\s*)?\d+(?:\s*(?:支|根|个|條|条|盒|只|pcs?\b|boxes\b|box\b|bx\b))?)\s+(?=(?![支根个條条盒只])(?!pcs?\b)(?!box(?:es)?\b)(?!bx\b)[A-Za-z㐀-鿿])/gi, "$1\u0001").split("\u0001"));
      for (const raw of pieces) {
        if (!raw.trim()) continue;
        const { qty, unit, rest } = qtyOf(raw);
        let toks = enToks(rest);
        const cj = cjkOf(rest);
        const sh = findSer(toks);
        let sr = null;
        if (sh) { sr = sh.sr; toks = toks.slice(0, sh.at).concat(toks.slice(sh.at + sh.n)); }
        if (!toks.length && !cj) { // 只有系列名 = 下面几行的系列；只有数字 = 下一段的根数
          if (sr) ctx = sr; else if (qty != null) carry = { qty, unit };
          continue;
        }
        if (sr) ctx = sr;
        const q = qty != null ? { qty, unit } : carry; carry = null;
        segs.push({ seg: { toks, cjk: cj }, sr, ctx, qty: q ? q.qty : null, unit: q ? q.unit : null, raw: raw.trim() });
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
    /* 没写单位的数字按什么算 */
    const hasBox = segs.some((g) => g.unit === "box"), hasPc = segs.some((g) => g.unit === "pc"), bare = segs.some((g) => !g.unit);
    const unit = opts.unit === "box" || opts.unit === "pc" ? opts.unit : hasBox && !hasPc ? "box" : "pc", per = Number(opts.box) || 10;
    const res = {}, order = [];
    segs.forEach((g, k) => {
      let m = first[k], assumed = false;
      // 没写系列、上文也没有：先在这段文字的主要系列里找（Bar Pro 清单里的「skittles」= Fruity Skittles）
      if (!g.sr && !g.ctx && major) { const mm = match(g.seg, inSer(major)); if (mm && mm !== "tie") { assumed = !(m && m !== "tie" && m.length === 1 && m[0].series === major); m = mm; } }
      if (!m || m === "tie") { unknown.push(g.raw); return; }
      let it = m[0];
      if (m.length > 1) { it = m.find((c) => c.series === (g.sr || g.ctx)) || m.find((c) => c.series === major) || m.find((c) => c.series === opts.series) || null; assumed = true; }
      if (!it) { unknown.push(g.raw); return; }
      const noQty = g.qty == null, n = noQty ? 1 : g.qty, byBox = (g.unit || unit) === "box", qty = byBox ? n * per : n;
      if (!res[it.sku]) { res[it.sku] = { sku: it.sku, qty: 0, noQty: false, assumed: false, seg: g.raw, boxes: 0 }; order.push(it.sku); }
      res[it.sku].qty += qty; if (byBox) res[it.sku].boxes += n; res[it.sku].noQty = res[it.sku].noQty || noQty; res[it.sku].assumed = res[it.sku].assumed || assumed;
    });
    return { lines: order.map((k) => res[k]).filter((l) => l.qty > 0), unknown, unit, bare };
  }

  /* 粘贴新口味（2026-11-28）：一段文字 → 要新增的口味 [{ series, variant, name, raw, have, like }]
     - 每行（或逗号/顿号分开的每一段）= 一个口味；根数、盒数、价钱、前面的编号 / 符号都去掉
     - 只写系列名的一行（已有的系列，或末尾带冒号的「Lost Mary:」）= 下面几行的系列；没有就用 opts.series
     - 英文写在 variant（首字母大写），中文写在 name
     - have = 这个系列里已经有的口味（逐词比，允许拼错一两个字母；多一个词、少一个词都不算有）
       like = 不是已经有的，但很像某个已有的（只多一个词 / 少一个词），界面上提醒（照样勾上）
     - 同一段里重复的只留一个 */
  function parseNew(text, items, opts) {
    opts = opts || {};
    const sers = [...new Set(items.map((i) => i.series).filter(Boolean))].map((sr) => ({ sr, t: enToks(sr) })).sort((a, b) => b.t.length - a.t.length);
    const serOf = (toks) => { const k = toks.join(" "); const h = sers.find((s) => s.t.join(" ") === k); return h ? h.sr : null; };
    const title = (t) => t.replace(/\s+/g, " ").trim().split(" ").map((w) => (w.length > 1 && w === w.toUpperCase() && /[A-Z]/.test(w) ? w : w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())).join(" ");
    let ctx = opts.series || null;
    const out = [], seen = new Set(), skipped = [];
    for (const line of String(text || "").replace(/\r/g, "").split("\n")) {
      if (/合计|总计|共计|小计|总共/.test(line)) continue;
      const head = line.replace(/^[\s\-–—•·*#>]+/, "").trim();
      // 「Lost Mary:」「新系列：One」这种：系列
      const hm = /^(?:系列|series)?\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9 .'&+-]*?)\s*[:：]\s*$/i.exec(head);
      if (hm && !cjkOf(head)) { ctx = serOf(enToks(hm[1])) || title(hm[1]); continue; }
      for (const piece of cnDigits(line).split(/[,，、;；|\/]/)) {
        let rest = qtyOf(piece).rest;
        rest = rest.replace(/\$\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?\s*(?:刀|块|元|aud\b)/gi, " ")         // 价钱
          .replace(/^[\s\-–—•·*#>]*(?:\d{1,3}\s*[.)、．:：]\s*)?/, " ")                                   // 1. / 2) / - / •
          .replace(/[\u{1F300}-\u{1FAFF}☀-➿️✅❌✔️]/gu, " ")                             // 表情
          .replace(/\b(?:new|新品|新款|新口味|上新)\b|新品|新款|新口味|上新/gi, " ")
          .replace(/[()（）\[\]【】"“”]/g, " ").replace(/\s+/g, " ").trim();
        if (!rest) continue;
        const cj = cjkOf(rest), en = rest.replace(/[㐀-鿿]+/g, " ").replace(/[^A-Za-z0-9 .'&+-]/g, " ").replace(/\s+/g, " ").trim().replace(/^[.'&+-]+|[.'&+-]+$/g, "").trim();
        let toks = enToks(en), enTxt = en;
        if (!toks.length && !cj) continue;
        // 只有系列名 = 下面几行的系列（「Bar Pro 2盒」这种也算系列）
        const sr0 = serOf(toks);
        if (sr0 && !cj) { ctx = sr0; continue; }
        // 开头是系列名（「Bar Pro: Lemon Lime」「Ali 葡萄冰」）：这个系列，后面是口味
        const pre = sers.find((x) => x.t.length <= toks.length && x.t.every((t, j) => toks[j] === t));
        if (pre) { ctx = pre.sr; toks = toks.slice(pre.t.length); enTxt = en.split(/\s+/).slice(pre.t.length).join(" ").replace(/^[\s:：.-]+/, ""); if (!toks.length && !cj) continue; }
        if (!ctx) { skipped.push(piece.trim()); continue; }
        const key = ctx + "|" + (toks.join(" ") || cj);
        if (seen.has(key)) continue; seen.add(key);
        const seg = { toks, cjk: cj };
        const pool = items.filter((i) => i.series === ctx);
        let have = null, like = null;
        for (const it of pool) {
          const sc = score(seg, it);
          const vt = enToks(it.variant || "");
          if (toks.length && vt.length) {
            if (sc[0] === 1 && sc[2] === 0 && sc[5].length === vt.length && vt.length === toks.length) { have = it; break; }
            // 很像：只差一个词（Strawberry Kiwi ↔ Strawberry Kiwi Ice），而且对上的不只是 ice / mist 这种
            if (!like && Math.abs(vt.length - toks.length) === 1 && sc[5].length === Math.min(vt.length, toks.length) && sc[5].some((t) => !WEAK.has(t))) like = it;
          } else if (!toks.length && cj && it.name && (it.name === cj)) { have = it; break; }
        }
        out.push({ series: ctx, variant: toks.length ? title(enTxt) : "", name: cj, raw: piece.trim(), have: have ? have.sku : null, like: !have && like ? like.sku : null });
      }
    }
    return { list: out, skipped };
  }
  const api = { parseOrder, parseNew };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.FBParse = api;
})(typeof window !== "undefined" ? window : globalThis);
