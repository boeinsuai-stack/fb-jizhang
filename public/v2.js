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
          const ov = (V.out || {})[sku] || {};
          moves.push(Object.assign({ id: o0.id + "-" + sku, type: "out", sku, name: nameOf(sku, per[sku].name), qty: per[sku].qty, date: o0.date, order_id: o0.id }, pickMeta(o0), ov, { _v: "order:" + o0.id }));
        }
      }
      const P = o0.picks || [];
      if (P.length) {
        const bid = o0.id + "-pick";
        for (const p of P) {
          const m = { id: bid + "-" + p.sku + (p.key || ""), type: "in", sku: p.sku, name: nameOf(p.sku, p.name), qty: p.qty, cost: p.cost, date: p.date || o0.date, order_id: o0.id, batch_id: bid, expense_id: bid + "-cost", note: p.note || "按单向合伙人拿货" };
          if (p.who != null) m.partner = p.who;
          moves.push(Object.assign(m, pickMeta(o0), p.meta || {}, { _v: "order:" + o0.id }));
        }
        if (!V.no_pick_expense) {
          const x = { id: bid + "-cost", category: "进货成本", amount: r2(P.reduce((a, p) => a + (Number(p.cost) || 0), 0)), date: o0.date, batch_id: bid,
            note: V.pick_note != null ? V.pick_note : "按单拿货 " + P.map((p) => nm(p.sku, p.name) + " ×" + p.qty).join("、") };
          expenses.push(Object.assign(x, pickMeta(o0), V.pick_meta || {}, { _v: "order:" + o0.id }));
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
        moves.push(Object.assign(mv, pickMeta(r), (r.meta || {})[sku] || {}, { _v: "purchase:" + p0.id }));
      }
      if (!V.no_pay_expense) {
        const x = { id: p0.id + "-pay", category: "进货成本", amount: r2(p0.total), date: V.pay_date || p0.date, po_id: p0.id, note: V.pay_note != null ? V.pay_note : "订货 " + (p0.lines || []).map((l) => nameOf(l.sku, l.name) + " ×" + l.qty).join("、") };
        expenses.push(Object.assign(x, pickMeta(p0), V.pay_meta || {}, { _v: "purchase:" + p0.id }));
      }
      return p;
    });
    // 往来 → 调入（in，带成本）/ 调出（adjust，负数）
    const transfers = (v2.transfers || []).map((t0) => {
      const t = clone(t0); delete t.v2;
      const V = t0.v2 || {};
      for (const side of ["in", "out"]) for (const l of t0[side] || []) {
        const ov = (V.moves || {})[side + ":" + l.sku] || {};
        const mv = side === "in"
          ? { id: t0.id + "-in-" + l.sku, type: "in", sku: l.sku, name: nameOf(l.sku, l.name), qty: l.qty, cost: r2(l.qty * (Number(l.unit) || 0)), date: t0.date, transfer_id: t0.id, note: "合伙人往来：" + t0.partner + " 给的" }
          : { id: t0.id + "-out-" + l.sku, type: "adjust", sku: l.sku, name: nameOf(l.sku, l.name), qty: -l.qty, date: t0.date, transfer_id: t0.id, note: "合伙人往来：给 " + t0.partner };
        const m = Object.assign(mv, pickMeta(t0), ov, { _v: "transfer:" + t0.id });
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
      expenses.push(Object.assign({ id: b.id + "-cost", category: "进货成本", amount: r2(ms.reduce((a, m) => a + (Number(m.cost) || 0), 0)), date: b.date, batch_id: b.id, note: b.note }, b.meta || {}, { _v: "batch:" + b.id }));
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
      const px = E.find((x) => x.id === o.id + "-pick-cost"); if (px) usedE.add(px.id);
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
    const diffs = (a, b) => { const d = {}; for (const k of new Set(Object.keys(a).concat(Object.keys(b)))) { if (k === "_v" || k === "id" || k === "by_at") continue; if (JSON.stringify(a[k]) !== JSON.stringify(b[k])) d[k] = a[k] === undefined ? undefined : a[k]; } return d; };
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
    for (const z of orders.concat(purchases, transfers)) if (!Object.keys(z.v2).length) delete z.v2;
    return v2;
  }

  const api = { migrate, project, r2 };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.FBV2 = api;
})(typeof window !== "undefined" ? window : globalThis);
