"""合伙人：缺货拿货、分开拿、互抵、改单价、结账/撤销结账、订货"""
from harness import *

def s4(a):
    oid = a.sale([("Banana Buzz", 2)])
    a.audit("卖 2 根（有货）", {"库存": {"XF-01": 8}, "收入": 120 + 120, "成本": 60 + 60})
    a.void(oid)
    a.audit("撤销卖出 → 一切回到原样", {"库存": {"XF-01": 10}, "收入": 120, "成本": 60, "应付": {A: 0, B: 0}})

def s5(a):
    oid = a.sale([("Grape Ice", 2), ("Banana Buzz", 1)], who=A)
    a.audit("卖 Grape×2（缺货找甲拿）+ Banana×1", {"应付": {A: 60}, "库存": {"XF-02": 0, "XF-01": 9}, "收入": 120 + 180, "成本": 60 + 90})
    sid, txt = a.settle_partner(A)
    a.audit("跟甲结账 60", {"应付": {A: 0}})
    assert a.ev("(s) => window.__GM.S.settles.find((x) => x.id === s).amount", sid) == 60, "结账金额不是 60"
    a.void(oid); a.audit("拿货已结账的单不能撤销（要先撤销结账）", {"应付": {A: 0}, "库存": {"XF-01": 9}})
    a.unsettle(sid); a.audit("撤销结账 → 又欠甲 60", {"应付": {A: 60}})
    a.void(oid); a.audit("撤销卖出 → 拿的货、欠的钱都没了", {"应付": {A: 0}, "库存": {"XF-02": 0, "XF-01": 10}, "收入": 120, "成本": 60})

def split_ab(pg):
    pg.click("#f-split-tog"); pg.wait_for_timeout(150)
    pg.click(f'#f-split [data-si="1"][data-sw="{B}"]')

def s6(a):
    oid = a.sale([("Grape Ice", 2)], who=A, split=split_ab)
    a.audit("一单 Grape×2：甲 1 根、乙 1 根", {"应付": {A: 30, B: 30}, "库存": {"XF-02": 0}})
    sid, _ = a.settle_partner(A)
    a.audit("只跟甲结 → 甲 0，乙还欠 30", {"应付": {A: 0, B: 30}})
    sid2, _ = a.settle_partner(B)
    a.audit("再跟乙结 → 都两清", {"应付": {A: 0, B: 0}})
    a.unsettle(sid); a.audit("撤销跟甲的结账 → 甲 30，乙 0", {"应付": {A: 30, B: 0}})
    a.unsettle(sid2); a.audit("撤销跟乙的结账 → 各 30", {"应付": {A: 30, B: 30}})
    a.void(oid); a.audit("撤销这一单", {"应付": {A: 0, B: 0}, "库存": {"XF-02": 0}})

def s7(a):
    # 互抵：甲那拿 Bar Pro 2 根 @30（随单），甲从我这拿走 Bar Pro 1 根 @36、Ali 1 根 @50
    a.sale([("Grape Ice", 2)], who=A)
    tid, _ = a.xfer("take", A, out=[("Banana Buzz", 1, 36), ("Cool Mint", 1, 50)])
    # Bar Pro：调入 2（60）调出 1（36）→ 抵 1，剩调入 1 根 30；Ali：调出 1 根 50 → 应收 20
    a.audit("同系列一根抵一根：应付 30 − 应收 50 = 应收 20", {"应付": {A: -20}, "库存": {"XF-01": 9, "XF-03": 3}})
    a.xprice(A, lambda pg: pg.fill("#f-xu-0", "40"))
    a.audit("调出 Banana 改成 40 → 抵掉的不算钱，应收还是 20", {"应付": {A: -20}})
    sid, txt = a.settle_partner(A)
    amt = a.ev("(s) => window.__GM.S.settles.find((x) => x.id === s).amount", sid)
    a.audit("结账 → 两清", {"应付": {A: 0}})
    assert amt == -20, f"结账金额应该是 −20，实际 {amt}"
    a.unsettle(sid); a.audit("撤销结账 → 应收 20", {"应付": {A: -20}})
    a.void_xfer(tid); a.audit("撤销往来 → 货回来，欠甲 60", {"应付": {A: 60}, "库存": {"XF-01": 10, "XF-03": 4}})

def s8(a):
    # 互抵 + 分两次结账：一次全结 vs 分开结，钱应该一样
    a.sale([("Grape Ice", 3)], who=A)                       # 调入 Bar Pro 3 @30 = 90
    a.xfer("take", A, out=[("Banana Buzz", 2, 40)])          # 调出 Bar Pro 2 @40 = 80
    a.audit("调入 3 调出 2 → 抵 2，还欠甲 1 根 30", {"应付": {A: 30}})
    def only_pick(pg): pg.uncheck("#f-x-0")
    sid, txt = a.settle_partner(A, only=only_pick)
    amt1 = a.ev("(s) => window.__GM.S.settles.find((x) => x.id === s).amount", sid)
    print("      只勾随单拿货结账，记的金额", amt1, "| 之后余额", a.net(A))
    sid2, _ = a.settle_partner(A)
    amt2 = a.ev("(s) => window.__GM.S.settles.find((x) => x.id === s).amount", sid2)
    print("      再结剩下的往来，记的金额", amt2, "| 两次合计付", amt1 + amt2, "（一次全结是 30）")
    a.audit("分两次结完 → 两清", {"应付": {A: 0}})
    if abs(amt1 + amt2 - 30) > 0.005: a.fails.append(("分开结账合计 ≠ 一次全结", [f"分开结 {amt1} + {amt2} = {amt1+amt2}，一次全结 30"])); print("❌ 分开结账合计 ≠ 一次全结：", amt1, amt2)

def s9(a):
    pid = a.po_new(A, series={"Bar Pro": (10, 28)}, flav=[("Cool Mint", 4, 45)], paid=False)
    a.audit("订货（没付）：Bar Pro 10 根 @28 + Cool Mint 4 根 @45 = 460 → 欠甲 460，库存不变", {"应付": {A: 460}, "库存": {"XF-01": 10, "XF-03": 4}})
    a.po_receive(pid, flav=[2], alloc={"XF-02": 3, "XF-05": 2})
    a.audit("部分到货：Cool Mint 2、Grape 3、Peach 2", {"应付": {A: 460}, "库存": {"XF-03": 6, "XF-02": 3, "XF-05": 2}})
    oid = a.sale([("Grape Ice", 2), ("Cool Mint", 5)])
    # Grape 成本 28×2；Cool Mint 先进先出：4 根 @50 + 1 根 @45
    a.audit("卖 Grape 2（@28）+ Cool Mint 5（4 根旧的 @50 + 1 根新的 @45）", {"库存": {"XF-02": 1, "XF-03": 1}, "成本": 60 + 56 + 245, "收入": 120 + 120 + 450})
    a.po_receive(pid, flav=[2], alloc={"XF-02": 5})
    a.audit("第二次到货：到齐", {"库存": {"XF-03": 3, "XF-02": 6, "XF-05": 2}, "应付": {A: 460}})
    sid, _ = a.settle_partner(A)
    a.audit("跟甲结账（订货 460）", {"应付": {A: 0}})
    a.unsettle(sid); a.audit("撤销结账 → 订货回到没付", {"应付": {A: 460}})

if __name__ == "__main__":
    import sys
    ALL = [("撤销卖出", base_seed, s4), ("拿货结账撤销", base_seed, s5), ("分开找两人拿", base_seed, s6), ("互抵改单价结账", base_seed, s7), ("互抵分两次结", base_seed, s8), ("订货分批到货", base_seed, s9)]
    f = run([x for x in ALL if len(sys.argv) < 2 or x[0] in sys.argv[1:]])
    sys.exit(1 if f else 0)
