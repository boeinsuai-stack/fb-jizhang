/* FB 记账 v2 数据结构：每件事只记一次。
   - migrate(old)：旧数据（v1 各集合）→ v2 各集合。只做一次（迁移时）。
   - project(v2)：v2 → App 原来用的样子（流水、支出、结账反向指针），在内存里现算，不存。
     App 的计算和页面代码照旧读这些，所以报表跟以前一样；存储里每件事只有一个家。
   v2 里谁是源头：
   - 订单 orders：lines（卖了什么）+ picks（这单找合伙人拿的货：sku、qty、cost、who、at…）。出库流水、拿货流水、拿货支出都从它算。
   - 订货 purchases：lines + receipts（每次到货：id、date、at、lines{sku: qty}）。到货流水、付款支出从它算。
   - 往来 transfers：in / out（qty、unit）。调入调出流水从它算。
   - 流水 movements：只剩独立发生的事（盘点调整、早期整批进货、算不出来的老记录）。
   - 支出 expenses：只剩真正的开销（不是进货成本的）。早期整批进货的支出从它的流水算。
   - 结账 settlements：结了哪些单（order_ids、transfer_ids、po_ids）。单据上不再反向记。
   每条算出来的记录带 _v = 来源（"order:o-…"），方便以后写入时找到源头。 */
(function (root) {
  "use strict";
  const r2 = (n) => Math.round((Number(n) || 0) * 100) / 100;
  const META = ["at", "by", "by_at", "created_by", "created_at", "last_updated"];
  const pickMeta = (x) => { const o = {}; for (const k of META) if (x && x[k] != null) o[k] = x[k]; return o; };
  const clone = (x) => JSON.parse(JSON.stringify(x));
  const isPickId = (id) => /-pick-/.test(id);
  // 补丁里「这个字段旧记录没有」用 NONE 表示（undefined 存不进数据库）
  const NONE = "\u2205无";
  const ov = (target, patch) => { for (const [k, v] of Object.entries(patch || {})) { if (v === NONE) delete target[k]; else target[k] = v; } return target; };

  // ---------- 现算：v2 → App 原来的样子 ----------
  function project(v2) {
    const moves = [], expenses = [];
    const items = v2.items || [], byS = {};
    for (const i of items) byS[i.sku] = i;
    const nameOf = (sku, fb) => fb || (byS[sku] && byS[sku].name) || sku;
    const nm = (sku, fb) => { const i = byS[sku]; return (i && (i.variant || i.name)) || fb || sku; }; // 跟 App 的 nm() 一样：英文名优先
    // 订单 → 出库 + 拿货 + 拿货支出
    const orders = (v2.orders || []).map((o0) => {
      const o = clone(o0); delete o.picks; delete o.v2;
      const V = o0.v2 || {};
      if (o0.status !== "reserved" || V.out_reserved) {
        const per = {}, order = [];
        for (const l of o0.lines || []) { if (!l.sku) continue; if (!(l.sku in per)) { per[l.sku] = { qty: 0, name: l.name }; order.push(l.sku); } per[l.sku].qty += Number(l.qty) || 0; }
        const skip = V.no_out || [];
        for (const sku of order) {
          if (skip.includes(sku)) continue;
          const o = (V.out || {})[sku] || {};
          moves.push(Object.assign(ov(Object.assign({ id: o0.id + "-" + sku, type: "out", sku, name: nameOf(sku, per[sku].name), qty: per[sku].qty, date: o0.date, order_id: o0.id }, pickMeta(o0)), o), { _v: "order:" + o0.id }));
        }
      }
      const P = o0.picks || [];
      if (P.length) {
        const bid = o0.id + "-pick";
        for (const p of P) {
          const m = { id: bid + "-" + p.sku + (p.key || ""), type: "in", sku: p.sku, name: nameOf(p.sku, p.name), qty: p.qty, cost: p.cost, date: p.date || o0.date, order_id: o0.id, batch_id: bid, expense_id: bid + "-cost", note: p.note || "按单向合伙人拿货" };
          if (p.who != null) m.partner = p.who;
          moves.push(Object.assign(ov(Object.assign(m, pickMeta(o0)), p.meta), { _v: "order:" + o0.id }));
        }
        if (!V.no_pick_expense) {
          const x = { id: bid + "-cost", category: "进货成本", amount: r2(P.reduce((a, p) => a + (Number(p.cost) || 0), 0)), date: o0.date, batch_id: bid,
            note: V.pick_note != null ? V.pick_note : "按单拿货 " + P.map((p) => nm(p.sku, p.name) + " ×" + p.qty).join("、") };
          expenses.push(Object.assign(ov(Object.assign(x, pickMeta(o0)), V.pick_meta), { _v: "order:" + o0.id }));
        }
      }
      return o;
    });
    // 订货 → 到货 + 付款支出
    const purchases = (v2.purchases || []).map((p0) => {
      const p = clone(p0); delete p.receipts; delete p.v2;
      const V = p0.v2 || {};
      for (const r of p0.receipts || []) for (const [sku, qty] of Object.entries(r.lines || {})) {
        const l = (p0.lines || []).find((x) => x.sku === sku) || {};
        const mv = { id: p0.id + "-" + r.id + "-" + sku, type: "in", sku, name: nameOf(sku, l.name), qty, cost: r2(qty * (Number(l.unit_cost) || 0)), date: r.date, po_id: p0.id, po_line: sku, receipt_id: r.id, note: "订货到货" };
        moves.push(Object.assign(ov(Object.assign(mv, pickMeta(r)), (r.meta || {})[sku]), { _v: "purchase:" + p0.id }));
      }
      if (!V.no_pay_expense) {
        const x = { id: p0.id + "-pay", category: "进货成本", amount: r2(p0.total), date: V.pay_date || p0.date, po_id: p0.id, note: V.pay_note != null ? V.pay_note : "订货 " + (p0.lines || []).map((l) => nameOf(l.sku, l.name) + " ×" + l.qty).join("、") };
        expenses.push(Object.assign(ov(Object.assign(x, pickMeta(p0)), V.pay_meta), { _v: "purchase:" + p0.id }));
      }
      return p;
    });
    // 往来 → 调入（in，带成本）/ 调出（adjust，负数）
    const transfers = (v2.transfers || []).map((t0) => {
      const t = clone(t0); delete t.v2;
      const V = t0.v2 || {};
      for (const side of ["in", "out"]) for (const l of t0[side] || []) {
        const o = (V.moves || {})[side + ":" + l.sku] || {};
        const mv = side === "in"
          ? { id: t0.id + "-in-" + l.sku, type: "in", sku: l.sku, name: nameOf(l.sku, l.name), qty: l.qty, cost: r2(l.qty * (Number(l.unit) || 0)), date: t0.date, transfer_id: t0.id, note: "合伙人往来：" + t0.partner + " 给的" }
          : { id: t0.id + "-out-" + l.sku, type: "adjust", sku: l.sku, name: nameOf(l.sku, l.name), qty: -l.qty, date: t0.date, transfer_id: t0.id, note: "合伙人往来：给 " + t0.partner };
        const m = Object.assign(ov(Object.assign(mv, pickMeta(t0)), o), { _v: "transfer:" + t0.id });
        for (const k of Object.keys(m)) if (m[k] === undefined) delete m[k];
        moves.push(m);
      }
      return t;
    });
    // 独立的流水、支出
    for (const m of v2.movements || []) moves.push(clone(m));
    for (const x of v2.expenses || []) expenses.push(clone(x));
    // 早期整批进货：支出 = 这批流水的成本合计
    for (const b of v2.batches || []) {
      const ms = moves.filter((m) => m.batch_id === b.id);
      expenses.push(Object.assign(ov({ id: b.id + "-cost", category: "进货成本", amount: r2(ms.reduce((a, m) => a + (Number(m.cost) || 0), 0)), date: b.date, batch_id: b.id, note: b.note }, b.meta), { _v: "batch:" + b.id }));
    }
    // 结账 → 单据上的反向指针
    const settles = (v2.settlements || []).map(clone);
    const oBy = {}, tBy = {}, pBy = {};
    for (const o of orders) oBy[o.id] = o;
    for (const t of transfers) tBy[t.id] = t;
    for (const p of purchases) pBy[p.id] = p;
    for (const s of settles) {
      for (const oid of s.order_ids || []) { const o = oBy[oid]; if (!o) continue; if (o.pick_split || o.partner_settlements) { (o.partner_settlements = o.partner_settlements || {})[s.partner] = s.id; } else o.partner_settlement_id = s.id; }
      for (const tid of s.transfer_ids || []) if (tBy[tid]) tBy[tid].partner_settlement_id = s.id;
      for (const pid of s.po_ids || []) if (pBy[pid]) pBy[pid].settlement_id = s.id;
    }
    // 源头标了「这几条旧数据里没有」的（比如撤销往来时先删了流水、往来单还在），不算出来
    const skip = new Set();
    for (const z of (v2.orders || []).concat(v2.purchases || [], v2.transfers || [])) for (const id of (z.v2 && z.v2.skip) || []) skip.add(id);
    if (skip.size) { for (const a of [moves, expenses]) for (let i = a.length - 1; i >= 0; i--) if (a[i]._v && skip.has(a[i].id)) a.splice(i, 1); }
    // 跟 Firebase 一样按编号排序（App 有些列表靠这个顺序）
    const byId = (a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
    for (const a of [orders, purchases, transfers, moves, expenses, settles]) a.sort(byId);
    return { items: (v2.items || []).map(clone), orders, purchases, transfers, moves, expenses, settles, customers: (v2.customers || []).map(clone), followups: (v2.followups || []).map(clone) };
  }

  // ---------- 迁移：旧数据 → v2 ----------
  // 做法：先按规则把复制品「收回」到源头，再用 project() 算一遍，跟旧数据逐字段比；
  // 不一样的字段（多半是老记录的备注、时间）记成源头上的小补丁（v2 字段），保证算出来跟旧数据一模一样。
  // 规则管不了的老记录原样留在 movements / expenses（它们本来就是独立的事）。
  function migrate(old) {
    const L = (c) => Object.entries(old[c] || {}).map(([id, x]) => Object.assign({ id }, x));
    const M = L("movements"), E = L("expenses");
    const used = new Set(), usedE = new Set();
    const orders = L("orders").map((o) => {
      const n = clone(o); delete n.partner_settlement_id; delete n.partner_settlements; n.v2 = {};
      if (!o.partner_settlements) delete n.partner_settlements;
      const picks = [];
      for (const m of M) if (m.order_id === o.id && isPickId(m.id) && m.type === "in") {
        const key = m.id.slice((o.id + "-pick-" + m.sku).length);
        const p = { sku: m.sku, qty: m.qty, cost: m.cost, key: key || undefined, meta: pickMeta(m) };
        if (m.partner != null) p.who = m.partner;
        if (m.note !== "按单向合伙人拿货") p.note = m.note;
        if (m.date !== o.date) p.date = m.date;
        if (m.name) p.name = m.name;
        picks.push(p); used.add(m.id);
      }
      if (picks.length) n.picks = picks.map((p) => { for (const k of Object.keys(p)) if (p[k] === undefined) delete p[k]; return p; });
      for (const m of M) if (m.order_id === o.id && m.type === "out" && m.id === o.id + "-" + m.sku) used.add(m.id);
      // 拿货支出归订单管，前提是订单上有拿货；没有拿货了（货留作库存），这笔支出就是独立的
      const px = E.find((x) => x.id === o.id + "-pick-cost"); if (px && picks.length) usedE.add(px.id);
      return n;
    });
    const purchases = L("purchases").map((p) => {
      const n = clone(p); delete n.settlement_id; n.v2 = {};
      const rs = {};
      for (const m of M) if (m.po_id === p.id && m.receipt_id) { const r = rs[m.receipt_id] || (rs[m.receipt_id] = { id: m.receipt_id, date: m.date, lines: {}, meta: {} }); r.lines[m.sku] = m.qty; r.meta[m.sku] = pickMeta(m); used.add(m.id); }
      n.receipts = Object.values(rs);
      const x = E.find((e) => e.po_id === p.id); if (x) usedE.add(x.id); else n.v2.no_pay_expense = true;
      return n;
    });
    const transfers = L("transfers").map((t) => {
      const n = clone(t); delete n.partner_settlement_id; n.v2 = {};
      for (const m of M) if (m.transfer_id === t.id) {
        used.add(m.id);
        const side = m.type === "in" ? "in" : "out";
        if (m.id !== t.id + "-" + side + "-" + m.sku) ((n.v2.moves = n.v2.moves || {})[side + ":" + m.sku] = n.v2.moves[side + ":" + m.sku] || {}).id = m.id; // 早期的编号写法
      }
      return n;
    });
    const batches = [];
    for (const x of E) if ((x.batch_id || "").startsWith("b-") && x.id === x.batch_id + "-cost") { batches.push({ id: x.batch_id, date: x.date, note: x.note, meta: pickMeta(x) }); usedE.add(x.id); }
    const settlements = L("settlements");
    const v2 = { items: L("items"), customers: L("customers"), followups: L("followups"), orders, purchases, transfers, batches, settlements,
      movements: M.filter((m) => !used.has(m.id)), expenses: E.filter((x) => !usedE.has(x.id)) };
    // 补丁：逐字段对齐
    const P = project(v2);
    const oldM = {}, oldE = {}; for (const m of M) oldM[m.id] = m; for (const x of E) oldE[x.id] = x;
    const newM = {}, newE = {}; for (const m of P.moves) newM[m.id] = m; for (const x of P.expenses) newE[x.id] = x;
    const src = (v) => { const [k, id] = v.split(/:(.*)/); return (k === "order" ? orders : k === "purchase" ? purchases : k === "transfer" ? transfers : []).find((z) => z.id === id); };
    const diffs = (a, b) => { const d = {}; for (const k of new Set(Object.keys(a).concat(Object.keys(b)))) { if (k === "_v" || k === "id" || k === "by_at") continue; if (JSON.stringify(a[k]) !== JSON.stringify(b[k])) d[k] = a[k] === undefined ? NONE : a[k]; } return d; };
    for (const id of Object.keys(newM)) {
      const nm = newM[id], om = oldM[id]; if (!om) continue;
      const d = diffs(om, nm); if (!Object.keys(d).length) continue;
      const s = src(nm._v), [k] = nm._v.split(":");
      if (k === "order" && nm.type === "out") (s.v2.out = s.v2.out || {})[nm.sku] = d;
      else if (k === "order") { const p = s.picks.find((p) => id === s.id + "-pick-" + p.sku + (p.key || "")); p.meta = Object.assign(p.meta || {}, d); }
      else if (k === "transfer") (s.v2.moves = s.v2.moves || {})[(nm.type === "in" ? "in:" : "out:") + nm.sku] = d;
      else if (k === "purchase") { const r = s.receipts.find((r) => r.id === nm.receipt_id); r.meta[nm.sku] = Object.assign(r.meta[nm.sku] || {}, d); }
    }
    for (const id of Object.keys(newE)) {
      const nx = newE[id], ox = oldE[id]; if (!ox || !nx._v) continue;
      const d = diffs(ox, nx); if (!Object.keys(d).length) continue;
      const [k] = nx._v.split(":"), s = k === "batch" ? batches.find((b) => b.id === nx.batch_id) : src(nx._v);
      if (k === "order") { if ("note" in d) { s.v2.pick_note = d.note; delete d.note; } if (Object.keys(d).length) s.v2.pick_meta = d; }
      else if (k === "purchase") { if ("note" in d) { s.v2.pay_note = d.note; delete d.note; } if ("date" in d) { s.v2.pay_date = d.date; delete d.date; } if (Object.keys(d).length) s.v2.pay_meta = d; }
      else if (k === "batch") s.meta = Object.assign(s.meta || {}, d);
    }
    // 订单里「旧数据没有这条出库」（比如预定单、代送单）也要记下来
    for (const o of orders) {
      const want = P.moves.filter((m) => m._v === "order:" + o.id && m.type === "out").map((m) => m.sku);
      const miss = want.filter((sku) => !oldM[o.id + "-" + sku]); if (miss.length) o.v2.no_out = miss;
      if (o.status === "reserved" && M.some((m) => m.order_id === o.id && m.type === "out")) o.v2.out_reserved = true;
      if (o.picks && !oldE[o.id + "-pick-cost"]) o.v2.no_pick_expense = true;
    }
    {
      const P2 = project(v2);
      for (const z of orders.concat(purchases, transfers)) {
        const tag = (orders.includes(z) ? "order:" : purchases.includes(z) ? "purchase:" : "transfer:") + z.id;
        const extra = P2.moves.filter((m) => m._v === tag && !oldM[m.id]).map((m) => m.id).concat(P2.expenses.filter((x) => x._v === tag && !oldE[x.id]).map((x) => x.id));
        if (extra.length) z.v2.skip = extra;
      }
    }
    for (const z of orders.concat(purchases, transfers)) if (!Object.keys(z.v2).length) delete z.v2;
    return v2;
  }

  // ---------- App 里用：读 v2、写 v2（翻译层） ----------
  // 业务代码照旧按「旧样子」读写（订单、流水、支出……）。这里：
  //  读：订阅 v2_* 集合 → project() → 旧样子交给页面。
  //  写：业务代码对旧样子某条记录的 set/update/delete → 找到它的源头（哪张订单/订货/往来/批次，或者它本身就是独立的事）
  //      → 在源头这一组上应用这次写入 → 用 migrate() 重新生成源头 → 只写源头那一条（加上真正独立的流水/支出）。
  //  流水、支出这些复制品从不落库。
  const V1 = ["orders", "movements", "expenses", "purchases", "transfers", "settlements"];
  const COL = { orders: "v2_orders", purchases: "v2_purchases", transfers: "v2_transfers", movements: "v2_movements", expenses: "v2_expenses", batches: "v2_batches", settlements: "v2_settlements" };
  const OWNER_COL = { order: "orders", purchase: "purchases", transfer: "transfers", batch: "batches" };
  function createStore(db, getItems, onChange) {
    const R = { orders: {}, purchases: {}, transfers: {}, movements: {}, expenses: {}, batches: {}, settlements: {} };
    const got = new Set(); let P = null, queued = false;
    const vals = (m) => Object.values(m);
    const recompute = () => { P = project({ items: getItems(), orders: vals(R.orders), purchases: vals(R.purchases), transfers: vals(R.transfers), movements: vals(R.movements), expenses: vals(R.expenses), batches: vals(R.batches), settlements: vals(R.settlements) }); return P; };
    const kick = () => { if (queued) return; queued = true; Promise.resolve().then(() => { queued = false; recompute(); onChange(P, got.size === Object.keys(COL).length); }); };
    // 本机刚写的记录先「挂着」：手机本地数据库的通知是异步的，可能晚到一拍、还是写之前的样子；
    // 写入完成之后再收到一次通知，才确定通知里已经有它，才放下。否则旧通知会把刚写的盖掉。
    const pend = {}, snapN = {};
    for (const k of Object.keys(COL)) { pend[k] = {}; snapN[k] = 0; }
    const unsubs = Object.entries(COL).map(([k, c]) => db.collection(c).onSnapshot((s) => {
      snapN[k]++;
      const m = {}; for (const d of s.docs) m[d.id] = Object.assign({ id: d.id }, d.data());
      for (const [id, w] of Object.entries(pend[k])) {
        if (w.doneAt != null && snapN[k] > w.doneAt) { delete pend[k][id]; continue; }
        if (w.doc) m[id] = Object.assign({ id }, w.doc); else delete m[id];
      }
      R[k] = m; got.add(k); kick();
    }, (e) => console.warn("v2 读取出错", c, e)));
    // 当前「旧样子」，按集合 id 索引
    const view = () => { const p = P || recompute(); const ix = (a) => { const o = {}; for (const x of a) o[x.id] = x; return o; }; return { orders: ix(p.orders), purchases: ix(p.purchases), transfers: ix(p.transfers), movements: ix(p.moves), expenses: ix(p.expenses), settlements: ix(p.settles) }; };
    // 这条旧样子的记录归谁：order:/purchase:/transfer:/batch: 或 null（独立）
    function ownerAfter(c, id, d, cur) {
      if (c === "orders") return "order:" + id;
      if (c === "purchases") return "purchase:" + id;
      if (c === "transfers") return "transfer:" + id;
      if (c === "movements") {
        if (d.order_id && (cur.orders[d.order_id] || d.order_id === pendingOwner)) {
          if (d.type === "out" && id === d.order_id + "-" + d.sku) return "order:" + d.order_id;
          if (d.type === "in" && id.startsWith(d.order_id + "-pick-")) return "order:" + d.order_id;
        }
        if (d.po_id && d.receipt_id) return "purchase:" + d.po_id;
        if (d.transfer_id) return "transfer:" + d.transfer_id;
        if ((d.batch_id || "").startsWith("b-")) return "batch:" + d.batch_id;
        return null;
      }
      if (c === "expenses") {
        if (/-pick$/.test(d.batch_id || "") && id === d.batch_id + "-cost") return "order:" + d.batch_id.slice(0, -5);
        if (d.po_id) return "purchase:" + d.po_id;
        if ((d.batch_id || "").startsWith("b-") && id === d.batch_id + "-cost") return "batch:" + d.batch_id;
        return null;
      }
      return null;
    }
    let pendingOwner = null;
    const ownerBefore = (c, id, d) => (d && d._v ? d._v : null) || (c === "orders" ? "order:" + id : c === "purchases" ? "purchase:" + id : c === "transfers" ? "transfer:" + id : (c === "movements" || c === "expenses") && d && (d.batch_id || "").startsWith("b-") ? "batch:" + d.batch_id : null);
    const clean = (d) => { if (!d) return d; const x = clone(d); delete x._v; delete x.id; for (const k of Object.keys(x)) if (x[k] === undefined) delete x[k]; return x; };
    // 在内存里先改好，再写库（写库本身在手机里马上完成）
    const ops = [];
    const put = (k, id, doc) => {
      if (!doc && !R[k][id]) return;
      const w = { doc: doc || null, doneAt: null }; pend[k][id] = w;
      if (doc) R[k][id] = Object.assign({ id }, doc); else delete R[k][id];
      const p = doc ? db.collection(COL[k]).doc(id).set(doc) : db.collection(COL[k]).doc(id).delete();
      ops.push(p.then(() => { if (pend[k][id] === w) w.doneAt = snapN[k]; }));
    };
    function write(c, id, op, data) {
      if (!V1.includes(c)) throw new Error("v2 不认识的集合 " + c);
      const cur = view();
      const before = cur[c][id] ? clone(cur[c][id]) : null;
      let after = op === "delete" ? null : op === "update" ? Object.assign({}, before || {}, clean(data)) : clean(data);
      if (op === "update" && !before) return Promise.reject(new Error("要修改的记录不存在：" + c + "/" + id));
      if (after) delete after._v;
      if (c === "settlements") { put("settlements", id, after ? clean(after) : null); recompute(); return flush(); }
      if (c === "orders") pendingOwner = id;
      const oB = ownerBefore(c, id, before), oA = after ? ownerAfter(c, id, after, cur) : null;
      pendingOwner = null;
      const owners = [...new Set([oB, oA].filter(Boolean))];
      // 独立的流水/支出：直接写
      if (!owners.length) { put(c, id, after ? clean(after) : null); recompute(); return flush(); }
      if (!oA && oB) put(c, id, after ? clean(after) : null); // 从某个源头里拿出来，变成独立的
      for (const own of owners) {
        const [k, oid] = own.split(/:(.*)/), oc = OWNER_COL[k];
        // 这一组的旧样子：源头本身 + 归它的流水、支出
        const old = { items: {}, orders: {}, purchases: {}, transfers: {}, movements: {}, expenses: {}, settlements: {} };
        for (const it of getItems()) old.items[it.sku] = it;
        if (k !== "batch") { const src = cur[oc][oid]; if (src) old[oc][oid] = clean(src); }
        const mine = (x) => x._v === own || (k === "batch" && x.batch_id === oid);
        for (const m of Object.values(cur.movements)) if (mine(m)) old.movements[m.id] = clean(m);
        for (const x of Object.values(cur.expenses)) if (mine(x)) old.expenses[x.id] = clean(x);
        // 应用这次写入
        if (c === oc && id === oid) { if (after) old[oc][oid] = clean(after); else delete old[oc][oid]; }
        else if (c === "movements" || c === "expenses") { if (oA === own && after) old[c][id] = clean(after); else if (oB === own) delete old[c][id]; }
        const v = migrate(old);
        // 源头
        if (k === "batch") { const b = v.batches.find((x) => x.id === oid); put("batches", oid, b ? clean(b) : null); }
        else { const src = (v[oc] || []).find((x) => x.id === oid); put(oc, oid, src ? clean(src) : null); }
        // 这一组里没被源头收回的 = 独立的流水/支出
        const idsM = new Set(Object.keys(old.movements).concat(Object.values(cur.movements).filter(mine).map((m) => m.id)));
        const idsE = new Set(Object.keys(old.expenses).concat(Object.values(cur.expenses).filter(mine).map((x) => x.id)));
        if (oA !== own) { if (c === "movements") idsM.delete(id); if (c === "expenses") idsE.delete(id); } // 刚写的这条已经归别处（或独立）了，这一组不管它
        const freeM = {}, freeE = {}; for (const m of v.movements) freeM[m.id] = m; for (const x of v.expenses) freeE[x.id] = x;
        for (const mid of idsM) put("movements", mid, freeM[mid] ? clean(freeM[mid]) : null);
        for (const xid of idsE) put("expenses", xid, freeE[xid] ? clean(freeE[xid]) : null);
      }
      recompute();
      return flush();
    }
    function flush() { const all = ops.splice(0); kick(); return Promise.all(all).then(() => undefined); }
    return { write, view: () => P || recompute(), refresh: kick, ready: () => got.size === Object.keys(COL).length, R, stop: () => unsubs.forEach((u) => u && u()) };
  }

  const api = { migrate, project, createStore, COL, V1, r2 };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.FBV2 = api;
})(typeof window !== "undefined" ? window : globalThis);
