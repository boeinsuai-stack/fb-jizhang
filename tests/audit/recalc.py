"""独立重算：只读原始记录（旧样子的 fixture），不借 App 的任何函数。
算：每口味库存、每单收入/成本、每天/总计、每个合伙人应付应收（含同系列互抵）、每单结账标记。
再查几条「守恒」：货的来去、成本的来去（买进的钱 = 卖出成本 + 损耗 + 调出带走的 + 还在手上的）。
用法：python3 -I recalc.py <fixture.json> [App 算出的 golden.json]
"""
import json, sys, math
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def js_round2(x):
    # JS Math.round(n*100)/100：.5 往正无穷进
    return math.floor(x * 100 + 0.5) / 100


def num(v):
    try:
        if v is None or v == "": return 0.0
        f = float(v)
        return f if math.isfinite(f) else 0.0
    except Exception:
        return 0.0


def num_or_none(v):
    if v is None or v == "": return None
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except Exception:
        return None


def iso(at):
    if not at: return ""
    try:
        s = at.replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        if d.tzinfo is None: return ""
        d = d.astimezone(timezone.utc)
        return d.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (d.microsecond // 1000)
    except Exception:
        return ""


def load(path):
    fx = json.load(open(path, encoding="utf8"))
    out = {}
    for c, recs in fx.items():
        if not isinstance(recs, dict): continue
        out[c] = [dict(v, id=k) for k, v in sorted(recs.items())]
    return out


def recalc(D):
    items = {i.get("sku"): i for i in D.get("items", [])}
    moves, orders = D.get("movements", []), D.get("orders", [])
    series = lambda sku: (items.get(sku) or {}).get("series") or "未分类"
    R = {}

    # ---- 1. 库存：进 − 出 ± 调整
    st = defaultdict(float)
    for m in moves:
        if not m.get("sku"): continue
        q = num(m.get("qty"))
        if m.get("type") == "in": st[m["sku"]] += q
        elif m.get("type") == "out": st[m["sku"]] -= q
        elif m.get("type") == "adjust": st[m["sku"]] += q
    R["st"] = dict(st)

    # ---- 2. 成本：先进先出。随单拿的货只算给那一单
    picks = defaultdict(lambda: defaultdict(list))  # 单 -> 口味 -> [(根数, 单根价)]
    for m in moves:
        if m.get("type") == "in" and m.get("order_id") and str(m.get("batch_id") or "").endswith("-pick") and num(m.get("qty")) > 0:
            q = num(m["qty"])
            picks[m["order_id"]][m["sku"]].append([q, None if m.get("cost") is None else num(m["cost"]) / q])
    ev = []
    for m in moves:
        q = num(m.get("qty"))
        if not m.get("sku") or not q: continue
        key = (m.get("date") or "") + "|" + iso(m.get("at"))
        if m.get("type") == "in" and not m.get("order_id") and q > 0:
            ev.append((key, 0, m["sku"], q, None if m.get("cost") is None else num(m["cost"]) / q, None, None))
        elif m.get("type") == "adjust":
            kind = "xfer" if m.get("transfer_id") else "shrink"
            ev.append((key, 0 if q > 0 else 1, m["sku"], q, None, None, (kind, m) if q < 0 else None))
    for o in orders:
        if o.get("status") == "reserved": continue
        need = defaultdict(float)
        for l in o.get("lines") or []:
            if l.get("sku"): need[l["sku"]] += num(l.get("qty"))
        for sku, q in need.items():
            pk = sum(x[0] for x in picks[o["id"]].get(sku, []))
            fs = q - min(q, pk)
            if fs > 0: ev.append(((o.get("date") or "") + "|" + iso(o.get("at")), 1, sku, -fs, None, o["id"], None))
    ev = [e + (n,) for n, e in enumerate(ev)]
    ev.sort(key=lambda e: (e[0], e[1], e[7]))
    layers = defaultdict(list); OC = defaultdict(dict); shrink = []; xfer_cost = 0.0; fallback_used = []
    fb = lambda sku: num_or_none((items.get(sku) or {}).get("cost_aud"))

    def avg(ls):
        tq = sum(x[0] for x in ls)
        if tq > 0 and all(x[1] is not None for x in ls): return sum(x[0] * x[1] for x in ls) / tq
        return None
    for key, t, sku, q, unit, oid, tag, _ in ev:
        ls = layers[sku]
        if q > 0:
            u = unit
            if u is None:
                a = avg(ls); u = a if a is not None else fb(sku)
            ls.append([q, u]); continue
        need, cost, known = -q, 0.0, True
        while need > 1e-9 and ls:
            x = ls[0]; take = min(need, x[0])
            if x[1] is None: known = False
            else: cost += take * x[1]
            x[0] -= take; need -= take
            if x[0] <= 1e-9: ls.pop(0)
        if need > 1e-9:
            u = fb(sku); fallback_used.append((sku, need, oid or (tag and tag[1]["id"])))
            if u is None: known = False
            else: cost += need * u
        if oid: OC[oid][sku] = (-q, js_round2(cost), known)
        if tag and tag[0] == "shrink": shrink.append((tag[1].get("date") or "", -q, js_round2(cost), tag[1]["sku"]))
        if tag and tag[0] == "xfer": xfer_cost += cost
    unit_now = {}
    for sku, ls in layers.items():
        a = avg(ls)
        if a is not None: unit_now[sku] = a
    c, qn = defaultdict(float), defaultdict(float)
    for m in moves:
        if m.get("type") == "in" and not m.get("order_id") and m.get("cost") is not None and num(m.get("qty")) > 0:
            c[m["sku"]] += num(m["cost"]); qn[m["sku"]] += num(m["qty"])
    UC = {}
    for sku, i in items.items(): UC[sku] = c[sku] / qn[sku] if qn[sku] else num_or_none(i.get("cost_aud"))
    UC.update(unit_now)
    R["uc"] = UC; R["fallback_used"] = fallback_used; R["xfer_cost"] = xfer_cost
    held_q = defaultdict(float); held_c = 0.0
    RES = {o["id"] for o in orders if o.get("status") == "reserved"}
    for m in moves:
        if m.get("type") == "in" and m.get("order_id") in RES and num(m.get("qty")) > 0:
            held_q[m["sku"]] += num(m["qty"]); held_c += num(m.get("cost"))
    R["held_q"] = dict(held_q); R["held_cost"] = held_c
    R["stock_value"] = sum(x[0] * x[1] for ls in layers.values() for x in ls if x[1] is not None)
    R["layer_qty"] = {k: sum(x[0] for x in ls) for k, ls in layers.items()}

    # ---- 3. 每单、每天
    days = {}
    def day(d):
        return days.setdefault(d, dict(n=0, qty=0, cqty=0, costAll=0, goods=0, fee=0, rev=0, cash=0, cost=0, gross=0, opex=0, buy=0, pick=0, miss=0, unk=0, shrink=0, orders={}))
    for o in orders:
        if o.get("status") == "reserved": continue
        lines = o.get("lines") if isinstance(o.get("lines"), list) else []
        qty = sum(num(l.get("qty")) for l in lines)
        if o.get("lump_total") is not None: goods = js_round2(num(o["lump_total"]))
        elif not lines: goods = 0
        elif all(l.get("unit_price") is not None for l in lines): goods = js_round2(sum(num(l.get("qty")) * num(l["unit_price"]) for l in lines))
        else: goods = None
        fee = num(o.get("delivery_fee"))
        left = {k: [list(p) for p in v] for k, v in picks[o["id"]].items()}
        cost, known = 0.0, True
        for l in lines:
            need = num(l.get("qty")); ps = left.get(l.get("sku"), [])
            while need > 0 and ps:
                p = ps[0]; take = min(need, p[0])
                if p[1] is None: known = False
                else: cost += take * p[1]
                p[0] -= take; need -= take
                if p[0] <= 0: ps.pop(0)
            if need > 0:
                f = OC.get(o["id"], {}).get(l.get("sku"))
                if f and f[0] > 0:
                    if not f[2]: known = False
                    else: cost += f[1] * min(1, need / f[0])
                else:
                    u = UC.get(l.get("sku"))
                    if u is None: known = False
                    else: cost += need * u
        rev = None if goods is None else js_round2(goods + fee)
        b = dict(qty=qty, goods=goods, fee=fee, rev=rev, cost=js_round2(cost) if known else None, gross=js_round2(rev - cost) if rev is not None and known else None)
        d = day(o.get("date") or ""); d["orders"][o["id"]] = b; d["n"] += 1; d["qty"] += qty
        if rev is not None: d["cash"] += rev
        if b["cost"] is not None: d["costAll"] += b["cost"]
        if goods is None: d["miss"] += 1
        elif b["cost"] is None: d["unk"] += 1
        else:
            d["cqty"] += qty
            for k in ("goods", "fee", "rev", "cost", "gross"): d[k] += b[k]
    cats = defaultdict(float)
    for x in D.get("expenses", []):
        d = day(x.get("date") or ""); a = num(x.get("amount"))
        if x.get("category") == "进货成本":
            d["buy"] += a
            if str(x.get("batch_id") or "").endswith("-pick"): d["pick"] += a
        else:
            d["opex"] += a; cats[x.get("category") or "其他"] += a
    for date, q, cst, sku in shrink: day(date)["shrink"] += cst
    T = defaultdict(float)
    for d in days.values():
        for k in ("goods", "fee", "rev", "cash", "cost", "costAll", "gross", "opex", "buy", "pick", "shrink"): d[k] = js_round2(d[k])
        d["net"] = js_round2(d["gross"] - d["opex"] - d["shrink"])
        for k in ("n", "qty", "cqty", "costAll", "goods", "fee", "rev", "cash", "cost", "gross", "opex", "net", "buy", "pick", "miss", "unk", "shrink"): T[k] += d[k]
    R["days"] = days; R["T"] = {k: js_round2(v) for k, v in T.items()}

    # ---- 4. 合伙人：没结的随单拿货 + 没结的往来 + 没付的订货；同系列一根抵一根
    OB = {o["id"]: o for o in orders}
    who_from = lambda o: (o or {}).get("pick_from") or "合伙人"
    def sid_for(o, who):
        if not o: return None
        return (o.get("partner_settlements") or {}).get(who) or (o.get("partner_settlement_id") if who == who_from(o) else None) or None
    led = defaultdict(lambda: dict(ser=defaultdict(lambda: [0, 0.0, 0, 0.0]), po=0.0, tin=0.0, tout=0.0))
    for m in moves:
        if m.get("type") == "in" and m.get("order_id") and str(m.get("batch_id") or "").endswith("-pick"):
            o = OB.get(m["order_id"]); w = m.get("partner") or who_from(o)
            if sid_for(o, w): continue
            a = led[w]["ser"][series(m["sku"])]; a[0] += num(m.get("qty")); a[1] += num(m.get("cost")); led[w]["tin"] += num(m.get("cost"))
    for t in D.get("transfers", []):
        if t.get("partner_settlement_id") or t.get("closed"): continue
        w = t.get("partner") or "合伙人"
        for l in t.get("in") or []:
            a = led[w]["ser"][series(l.get("sku"))]; q = num(l.get("qty")); a[0] += q; a[1] += q * num(l.get("unit"))
        for l in t.get("out") or []:
            a = led[w]["ser"][series(l.get("sku"))]; q = num(l.get("qty")); a[2] += q; a[3] += q * num(l.get("unit"))
        led[w]["tin"] += js_round2(sum(num(l.get("qty")) * num(l.get("unit")) for l in t.get("in") or []))
        led[w]["tout"] += js_round2(sum(num(l.get("qty")) * num(l.get("unit")) for l in t.get("out") or []))
    for p in D.get("purchases", []):
        if p.get("paid") is False and not p.get("settlement_id"):
            led[(p.get("supplier") or "").strip() or "供货人（未填）"]["po"] += num(p.get("total"))
    partners = {}
    for w, x in led.items():
        inV = outV = 0.0
        for sr, (iq, iv, oq, ov) in x["ser"].items():
            q = min(iq, oq)
            if q > 0: inV += iv * q / iq; outV += ov * q / oq
        tin = js_round2(x["tin"] - js_round2(inV)); tout = js_round2(x["tout"] - js_round2(outV))
        partners[w] = js_round2(tin + js_round2(x["po"]) - tout)
    R["partners"] = partners
    R["settled"] = {o["id"]: sorted(set(filter(None, [o.get("partner_settlement_id")] + list((o.get("partner_settlements") or {}).values())))) for o in orders}
    return R


def invariants(D, R):
    """不依赖 App 算法的守恒检查。返回 [(名字, 是否通过, 说明)]"""
    out = []
    items = {i.get("sku"): i for i in D.get("items", [])}
    moves, orders = D.get("movements", []), D.get("orders", [])
    OB = {o["id"]: o for o in orders}
    # a. 卖出的单：每个口味出库根数 = 订单行根数；预定的单没有出库
    bad = []
    outq = defaultdict(lambda: defaultdict(float))
    for m in moves:
        if m.get("type") == "out" and m.get("order_id"): outq[m["order_id"]][m["sku"]] += num(m.get("qty"))
    for o in orders:
        need = defaultdict(float)
        for l in o.get("lines") or []:
            if l.get("sku"): need[l["sku"]] += num(l.get("qty"))
        got = outq.get(o["id"], {})
        if o.get("status") == "reserved":
            if got: bad.append(o["id"] + " 预定却有出库")
        elif dict(need) != {k: v for k, v in got.items() if v}: bad.append(o["id"] + " 出库≠订单行")
    for oid in outq:
        if oid not in OB: bad.append(oid + " 出库没有对应订单")
    out.append(("卖出的每一单出库根数 = 订单行", not bad, bad[:5]))
    # b. 随单拿货：流水指向的订单在；拿的根数不超过订单行
    bad = []
    pk = defaultdict(lambda: defaultdict(float))
    for m in moves:
        if m.get("type") == "in" and m.get("order_id"):
            if m["order_id"] not in OB: bad.append(m["id"] + " 拿货流水的订单不在了"); continue
            pk[m["order_id"]][m["sku"]] += num(m.get("qty"))
    for oid, by in pk.items():
        need = defaultdict(float)
        for l in OB[oid].get("lines") or []: need[l.get("sku")] += num(l.get("qty"))
        for sku, q in by.items():
            if q > need.get(sku, 0) + 1e-9: bad.append(f"{oid} {sku} 拿了 {q:g} 根，订单只要 {need.get(sku,0):g}")
    out.append(("随单拿的货不超过订单要的", not bad, bad[:5]))
    # c. 进货成本支出 = 这一批流水的 cost 合计
    bad = []
    bcost = defaultdict(float); bn = defaultdict(int)
    for m in moves:
        if m.get("type") == "in" and m.get("batch_id") and m.get("cost") is not None: bcost[m["batch_id"]] += num(m["cost"]); bn[m["batch_id"]] += 1
    seen = set()
    for x in D.get("expenses", []):
        if x.get("category") == "进货成本" and x.get("batch_id"):
            seen.add(x["batch_id"])
            if abs(bcost.get(x["batch_id"], 0) - num(x.get("amount"))) > 0.005: bad.append(f"{x['id']} 支出 {num(x.get('amount')):g} ≠ 流水 {bcost.get(x['batch_id'],0):g}")
    for b in bcost:
        if b not in seen and bcost[b]: bad.append(f"批次 {b} 有成本 {bcost[b]:g} 没有支出")
    out.append(("每批进货/拿货的支出 = 流水成本合计", not bad, bad[:8]))
    # c2. 从合伙人拿的货不能「脱单」：拿货流水没有订单了，这笔欠款就从对账单里消失
    orphan = [f"{m['id']} {m.get('sku')} ×{num(m.get('qty')):g} 成本 {num(m.get('cost')):g}" for m in moves if m.get("type") == "in" and str(m.get("batch_id") or "").endswith("-pick") and not m.get("order_id") and "已经跟合伙人结过账" not in str(m.get("note") or "") and not m.get("paid_partner")]
    out.append(("从合伙人拿的货都还挂在账上（没有脱单的拿货）", not orphan, orphan[:5]))
    # d. 往来单 ↔ 流水
    bad = []
    tq = defaultdict(lambda: defaultdict(float)); tc = defaultdict(lambda: defaultdict(float))
    for m in moves:
        if m.get("transfer_id"):
            tq[m["transfer_id"]][m["sku"]] += num(m.get("qty")) * (1 if m.get("type") in ("in", "adjust") else -1)
            if m.get("type") == "in": tc[m["transfer_id"]][m["sku"]] += num(m.get("cost"))
    TB = {t["id"]: t for t in D.get("transfers", [])}
    for t in TB.values():
        want = defaultdict(float); wc = defaultdict(float)
        for l in t.get("in") or []: want[l["sku"]] += num(l.get("qty")); wc[l["sku"]] += num(l.get("qty")) * num(l.get("unit"))
        for l in t.get("out") or []: want[l["sku"]] -= num(l.get("qty"))
        got = tq.get(t["id"], {})
        if {k: v for k, v in want.items() if v} != {k: v for k, v in got.items() if v}: bad.append(t["id"] + " 往来单的货 ≠ 流水")
        for sku, v in wc.items():
            if abs(v - tc[t["id"]].get(sku, 0)) > 0.005: bad.append(f"{t['id']} {sku} 调入单价×根数 {v:g} ≠ 流水成本 {tc[t['id']].get(sku,0):g}")
    for tid in tq:
        if tid not in TB: bad.append(tid + " 往来流水没有对应往来单")
    out.append(("往来单 = 往来流水（货和进价）", not bad, bad[:8]))
    # e. 结账 ↔ 订单/往来/订货 的指针两头一致
    bad = []
    SB = {s["id"]: s for s in D.get("settlements", [])}
    for o in orders:
        for sid in R["settled"][o["id"]]:
            if sid not in SB: bad.append(o["id"] + " 指向不存在的结账 " + sid)
            elif o["id"] not in (SB[sid].get("order_ids") or []): bad.append(o["id"] + " 说结在 " + sid + "，结账单里没有它")
    for s in SB.values():
        for oid in s.get("order_ids") or []:
            if oid not in OB: bad.append(s["id"] + " 里的订单 " + oid + " 不在了")
            elif s["id"] not in R["settled"][oid]: bad.append(s["id"] + " 列了 " + oid + "，订单上没有结账标记")
        for tid in s.get("transfer_ids") or []:
            if tid not in TB: bad.append(s["id"] + " 里的往来 " + tid + " 不在了")
            elif TB[tid].get("partner_settlement_id") != s["id"]: bad.append(s["id"] + " 列了 " + tid + "，往来单上没有结账标记")
        for pid in s.get("po_ids") or []:
            p = next((p for p in D.get("purchases", []) if p["id"] == pid), None)
            if not p: bad.append(s["id"] + " 里的订货 " + pid + " 不在了")
            elif p.get("settlement_id") != s["id"]: bad.append(s["id"] + " 列了 " + pid + "，订货单上没有结账标记")
    for t in TB.values():
        sid = t.get("partner_settlement_id")
        if sid and (sid not in SB or t["id"] not in (SB[sid].get("transfer_ids") or [])): bad.append(t["id"] + " 说结在 " + str(sid) + "，对不上")
    for p in D.get("purchases", []):
        sid = p.get("settlement_id")
        if sid and (sid not in SB or p["id"] not in (SB[sid].get("po_ids") or [])): bad.append(p["id"] + " 说结在 " + str(sid) + "，对不上")
    out.append(("结账单和订单/往来/订货的标记两头对得上", not bad, bad[:8]))
    # f. 订货到货 ↔ 订货单
    bad = []
    PB = {p["id"]: p for p in D.get("purchases", [])}
    recv = defaultdict(float)
    for m in moves:
        if m.get("po_id"):
            if m["po_id"] not in PB: bad.append(m["id"] + " 到货流水的订货单不在了")
            recv[m["po_id"]] += num(m.get("qty"))
    for p in PB.values():
        want = sum(num(l.get("qty")) for l in p.get("lines") or [])
        if recv[p["id"]] > want + 1e-9: bad.append(f"{p['id']} 到货 {recv[p['id']]:g} 根 > 订了 {want:g}")
        tot = sum(num(l.get("qty")) * num(l.get("unit_cost")) for l in p.get("lines") or [])
        if p.get("total") is not None and abs(tot - num(p["total"])) > 0.005 and all(l.get("unit_cost") is not None for l in p.get("lines") or []): bad.append(f"{p['id']} total {num(p['total']):g} ≠ 行合计 {tot:g}")
    out.append(("订货：到货不超过订的，总价 = 行合计", not bad, bad[:8]))
    # g. 成本守恒：所有进来的货的成本 = 卖出成本 + 损耗 + 调出带走的 + 还在手上的
    cin = sum(num(m.get("cost")) for m in moves if m.get("type") == "in" and m.get("cost") is not None)
    unknown_in = [m["id"] for m in moves if m.get("type") == "in" and m.get("cost") is None and num(m.get("qty")) > 0]
    cogs = sum(b["cost"] or 0 for d in R["days"].values() for b in d["orders"].values())
    shr = sum(d["shrink"] for d in R["days"].values())
    rhs = cogs + shr + R["xfer_cost"] + R["stock_value"] + R["held_cost"]
    out.append(("成本守恒：进货成本 = 卖出成本 + 损耗 + 调出 + 库存 + 预定占着的", abs(cin - rhs) < 0.5,
                f"进 {cin:.2f} | 卖出 {cogs:.2f} + 损耗 {shr:.2f} + 调出 {R['xfer_cost']:.2f} + 库存 {R['stock_value']:.2f} + 预定占着 {R['held_cost']:.2f} = {rhs:.2f}，差 {cin-rhs:+.2f}；没记成本的进货 {len(unknown_in)} 条；先进先出算不够、用口味默认成本顶的 {len(R['fallback_used'])} 次"))
    # h. 库存不为负；先进先出剩的根数 = 库存
    neg = {k: v for k, v in R["st"].items() if v < -1e-9}
    out.append(("库存没有负数", not neg, neg))
    lq = lambda k: R["layer_qty"].get(k, 0) + R["held_q"].get(k, 0)
    mis = {k: (R["st"].get(k, 0), lq(k)) for k in set(R["st"]) | set(R["layer_qty"]) | set(R["held_q"]) if abs(R["st"].get(k, 0) - lq(k)) > 1e-9}
    out.append(("成本账里剩的根数 = 库存根数", not mis, dict(list(mis.items())[:8])))
    return out


def compare(R, G):
    """跟 App 算的逐项比，返回不一致清单"""
    diff = []
    near = lambda a, b: (a is None and b is None) or (a is not None and b is not None and abs(a - b) < 0.005)
    for k in set(R["st"]) | set(G["st"]):
        if not near(R["st"].get(k, 0), G["st"].get(k, 0)): diff.append(("库存", k, R["st"].get(k, 0), G["st"].get(k, 0)))
    for k, v in G["T"].items():
        if not near(R["T"].get(k, 0), v): diff.append(("总计", k, R["T"].get(k, 0), v))
    for d in set(R["days"]) | set(G["days"]):
        a, b = R["days"].get(d), G["days"].get(d)
        if not a or not b: diff.append(("哪天有账", d, bool(a), bool(b))); continue
        for k in ("n", "qty", "cqty", "costAll", "goods", "fee", "rev", "cash", "cost", "gross", "opex", "net", "buy", "pick", "miss", "unk", "shrink"):
            if not near(a[k], b[k]): diff.append(("每天", d + "." + k, a[k], b[k]))
        for oid in set(a["orders"]) | set(b["orders"]):
            x, y = a["orders"].get(oid), b["orders"].get(oid)
            if not x or not y: diff.append(("每单", oid, bool(x), bool(y))); continue
            for k in ("qty", "goods", "fee", "rev", "cost", "gross"):
                if not near(x[k], y[k]): diff.append(("每单", oid + "." + k, x[k], y[k]))
    for w in set(R["partners"]) | set(G["partners"]):
        a, b = R["partners"].get(w, 0), (G["partners"].get(w) or {}).get("net", 0)
        if not near(a, b): diff.append(("合伙人应付", w, a, b))
    for oid, s in G["settled"].items():
        if sorted(s) != R["settled"].get(oid): diff.append(("结账标记", oid, R["settled"].get(oid), s))
    return diff


if __name__ == "__main__":
    D = load(sys.argv[1]); R = recalc(D)
    print("独立重算：单数 %d 根数 %g 收入 %g 成本 %g 净赚 %g" % (R["T"]["n"], R["T"]["qty"], R["T"]["rev"], R["T"]["cost"], R["T"]["net"]))
    print("合伙人应付(+)/应收(−):", R["partners"])
    ok = True
    for name, good, info in invariants(D, R):
        print(("✅ " if good else "❌ ") + name + ("" if good and not isinstance(info, str) else "  " + str(info)))
        ok = ok and good
    if len(sys.argv) > 2:
        G = json.load(open(sys.argv[2], encoding="utf8"))
        df = compare(R, G)
        n = len(R["st"]) + len(G["T"]) + sum(17 + 6 * len(d["orders"]) for d in R["days"].values()) + len(R["partners"]) + len(G["settled"])
        print(("✅ 跟 App 逐项一致，共 %d 项" % n) if not df else "❌ 跟 App 不一致 %d 项（共 %d 项）" % (len(df), n))
        for x in df[:25]: print("   ", x)
        ok = ok and not df
    sys.exit(0 if ok else 1)
