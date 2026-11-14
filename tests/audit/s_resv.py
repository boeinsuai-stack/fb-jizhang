"""预定：拿到货以后再改 / 取消"""
from harness import *

def s1(a):
    oid = a.sale([("Grape Ice", 2)], who=A, resv=True, cust="客人一")
    a.audit("预定 Grape×2（缺货，找甲拿）", {"应付": {A: 0}, "库存": {"XF-02": 0}})
    a.picked(A, oid)
    a.audit("对账单点「已拿到」→ 欠甲 60，手上多 2 根", {"应付": {A: 60}, "库存": {"XF-02": 2}})
    a.edit_resv(oid, lambda pg: pg.fill("#f-qty-0", "1"))
    a.audit("客人改成只要 1 根 → 2 根还在手上，照样欠甲 60", {"应付": {A: 60}, "库存": {"XF-02": 2}})
    a.settle_resv(oid)
    a.audit("客人付款结算 → 卖 1 根，手上剩 1 根，欠甲 60，成本 30", {"应付": {A: 60}, "库存": {"XF-02": 1}, "收入": 60 + 120, "成本": 30 + 60})

def s2(a):
    oid = a.sale([("Grape Ice", 2)], who=A, resv=True, cust="客人二")
    a.picked(A, oid)
    a.audit("预定 + 已拿到", {"应付": {A: 60}, "库存": {"XF-02": 2}})
    a.void(oid, "customers")
    a.audit("取消预定（货已经从甲那拿回来了）→ 货留在手上，照样欠甲 60", {"应付": {A: 60}, "库存": {"XF-02": 2}})

def s3(a):
    oid = a.sale([("Grape Ice", 1)], who=A, resv=True, cust="客人三")
    a.picked(A, oid)
    def chg(pg): pg.fill("#f-skuq-0", "Peach Ice"); pg.press("#f-skuq-0", "Enter")
    a.edit_resv(oid, chg)
    a.audit("预定换口味（Grape 已拿到 → 改要 Peach）→ Grape 留在手上，照样欠甲 30", {"应付": {A: 30}, "库存": {"XF-02": 1, "XF-05": 0}})

if __name__ == "__main__":
    import sys
    f = run([("预定拿到后改少", base_seed, s1), ("预定拿到后取消", base_seed, s2), ("预定拿到后换口味", base_seed, s3)])
    sys.exit(1 if f else 0)
