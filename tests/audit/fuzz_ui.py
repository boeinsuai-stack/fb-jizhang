"""界面随机操作压力测试：每一步之后查守恒 + 独立重算跟 App 逐项比。用法：python3 fuzz_ui.py <种子> <步数> [旧|v2]"""
import random, sys
from harness import *
seed_n, steps = int(sys.argv[1]), int(sys.argv[2]); modes = tuple(sys.argv[3:]) or ("旧", "v2")
NAMES = {"XF-01": "Banana Buzz", "XF-02": "Grape Ice", "XF-05": "Peach Ice", "XF-03": "Cool Mint", "XF-04": "Lemon Tea"}

def scen(a):
    rnd = random.Random(seed_n); log = []
    def st(k): return a.stock(k)
    def orders(f): return a.ev("(f) => window.__GM.S.orders.filter((o) => f === 'r' ? o.status === 'reserved' : o.status !== 'reserved' && !o.id.startsWith('o-old')).map((o) => o.id)", f)
    def act():
        k = rnd.choice(["sale", "sale", "pick", "pick", "split", "resv", "picked", "editq", "editf", "settle_r", "cancel_r", "void", "take", "give", "swap", "settle", "settle_part", "unsettle", "po", "recv", "xprice", "void_x"])
        w = rnd.choice([A, B])
        if k == "sale":
            have = [s for s in NAMES if st(s) - a.ev("(k) => window.__GM.reservedQty()[k] || 0", s) >= 1]
            if not have: return None
            s = rnd.choice(have); a.sale([(NAMES[s], 1)]); return f"卖 {s}"
        if k == "pick":
            s = rnd.choice(list(NAMES)); q = st(s) + rnd.choice([1, 2]); a.sale([(NAMES[s], int(q))], who=w); return f"卖 {s}×{q:g} 缺货找{w}"
        if k == "split":
            s = rnd.choice(list(NAMES)); q = int(st(s) + 2)
            def sp(pg):
                if pg.is_visible("#f-split-tog"): pg.click("#f-split-tog"); pg.wait_for_timeout(100); pg.click(f'#f-split [data-si="1"][data-sw="{B if w == A else A}"]')
            a.sale([(NAMES[s], q)], who=w, split=sp); return f"卖 {s}×{q} 分开拿"
        if k == "resv":
            s = rnd.choice(list(NAMES)); q = rnd.choice([1, 2, 3]); a.sale([(NAMES[s], q)], who=w, resv=True, cust="客" + str(rnd.randint(1, 5))); return f"预定 {s}×{q} 找{w}"
        if k == "picked":
            pend = a.ev("() => window.__GM.pendingPicks().map((g) => [g.who, g.oid])")
            if not pend: return None
            who, oid = rnd.choice(pend); a.picked(who, oid); return f"已拿到 {oid} {who}"
        if k in ("editq", "editf", "settle_r", "cancel_r"):
            rs = orders("r")
            if not rs: return None
            oid = rnd.choice(rs)
            if k == "editq": q = rnd.choice([1, 2, 4]); a.edit_resv(oid, lambda pg: pg.fill("#f-qty-0", str(q))); return f"预定改数量 {oid} → {q}"
            if k == "editf":
                s = rnd.choice(list(NAMES))
                def chg(pg): pg.fill("#f-skuq-0", NAMES[s]); pg.press("#f-skuq-0", "Enter")
                a.edit_resv(oid, chg); return f"预定换口味 {oid} → {s}"
            if k == "settle_r": a.settle_resv(oid); return f"结算预定 {oid}"
            a.void(oid, "customers"); return f"取消预定 {oid}"
        if k == "void":
            os_ = orders("s")
            if not os_: return None
            oid = rnd.choice(os_); a.void(oid); return f"撤销卖出 {oid}"
        if k == "take":
            have = [s for s in NAMES if st(s) - a.ev("(k) => window.__GM.reservedQty()[k] || 0", s) >= 1]
            if not have: return None
            s = rnd.choice(have); a.xfer("take", w, out=[(NAMES[s], 1, rnd.choice([30, 36, 40, 55]))]); return f"{w} 拿走 {s}"
        if k == "give":
            s = rnd.choice(list(NAMES)); q = rnd.choice([1, 2, 3]); a.xfer("give", w, inn=[(NAMES[s], q, rnd.choice([28, 30, 34, 50]))]); return f"{w} 给我 {s}×{q}"
        if k == "swap":
            have = [s for s in NAMES if st(s) - a.ev("(k) => window.__GM.reservedQty()[k] || 0", s) >= 1]
            if not have: return None
            s = rnd.choice(have); s2 = rnd.choice(list(NAMES)); a.xfer("swap", w, out=[(NAMES[s], 1, 36)], inn=[(NAMES[s2], rnd.choice([1, 2]), 34)]); return f"跟{w} 换 {s}↔{s2}"
        if k in ("settle", "settle_part"):
            if abs(a.net(w)) < 0.01 and not a.ev("(w) => window.__GM.openXfers(w).length + window.__GM.partnerItems(w).length + window.__GM.openPOs(w).length", w): return None
            if not a.ev(f"() => !!document.querySelector('#ptx-bal [data-ptx-settle=\"{w}\"]') || (location.hash = '#partner', false)") : a.pg.wait_for_timeout(250)
            if not a.pg.locator(f'#ptx-bal [data-ptx-settle="{w}"]').count(): return None
            def part(pg):
                boxes = pg.locator("#sheet .picks input[type=checkbox]"); n = boxes.count()
                if n > 1: boxes.nth(rnd.randrange(n)).uncheck()
            a.settle_partner(w, only=part if k == "settle_part" else None); return f"跟{w} 结账" + ("（少勾一笔）" if k == "settle_part" else "")
        if k == "unsettle":
            ss = a.ev("() => window.__GM.S.settles.filter((s) => !s.id.startsWith('s-old') && s.note !== '当场付清').map((s) => s.id)")
            if not ss: return None
            sid = rnd.choice(ss); a.unsettle(sid); return f"撤销结账 {sid}"
        if k == "po":
            if len(a.ids("purchases")) >= 3: return None
            a.po_new(w, series={"Bar Pro": (5, 28)}, flav=[("Cool Mint", 2, 45)] if rnd.random() < .5 else (), paid=rnd.random() < .3); return f"找{w} 订货"
        if k == "recv":
            ps = a.ev("() => window.__GM.S.purchases.map((p) => [p.id, p.lines.filter((l) => l.sku).length])")
            ps = [x for x in ps if a.ev("(id) => { const b = document.querySelector('[data-rcv=\"' + id + '\"]'); return !!b; }", x[0]) or True]
            if not ps: return None
            pid, nf = rnd.choice(ps)
            left = a.ev("(id) => { const G = window.__GM, po = G.S.purchases.find((p) => p.id === id); const got = G.S.moves.filter((m) => m.po_id === id).reduce((a, m) => a + m.qty, 0); return po.lines.reduce((a, l) => a + l.qty, 0) - got; }", pid)
            if left <= 0: return None
            a.go("purchases"); a.pg.wait_for_timeout(150)
            if not a.pg.locator(f'[data-rcv="{pid}"]').count(): return None
            a.po_receive(pid, flav=[1] * nf, alloc={rnd.choice(["XF-01", "XF-02", "XF-05"]): 2}); return f"到货 {pid}"
        if k == "xprice":
            if not a.ev("(w) => window.__GM.openXfers(w).length", w): return None
            if not a.ev("(w) => { const x = window.__GM.ledgerOf(w); return !!x; }", w): return None
            a.go("finance"); a.pg.wait_for_timeout(150)
            if not a.pg.locator(f'#f-owe [data-lg-open="{w}"]').count(): return None
            a.xprice(w, lambda pg: pg.fill("#f-xu-0", str(rnd.choice([25, 33, 44])))); return f"改{w}往来单价"
        if k == "void_x":
            ts = a.ev("() => window.__GM.S.transfers.filter((t) => !t.partner_settlement_id).map((t) => t.id)")
            if not ts: return None
            tid = rnd.choice(ts); a.void_xfer(tid); return f"撤销往来 {tid}"
    n = 0
    while n < steps:
        try: what = act()
        except Exception as e:
            what = None; msg = str(e).split("\n")[0][:160]; print(f"   （第 {n+1} 步动作没做成：{msg}）")
            try:
                if a.pg.is_visible("#sheet"): a.pg.click("#sheet-close")
            except Exception: pass
            n += 1; continue
        if what is None: continue
        n += 1; log.append(what)
        if not a.audit(f"{n}. {what}"):
            print("      前面的动作：" + " → ".join(log[-6:]))
            if len(a.fails) >= 4: print("   问题够多了，先停"); return

sys.exit(1 if run([(f"随机{seed_n}", base_seed, scen)], modes=modes) else 0)
