"""预定的货已经从合伙人那拿到，之后预定改了 / 取消了：货留作库存，没结账的照样欠他（旧结构、新结构各跑一遍）。
另：分开找两个人拿的预定，先拿到一个人的，剩下的还是找另一个人（以前又算回第一个人头上）。
以前：只把拿货流水的 order_id 清空（或直接删掉）→ 这笔欠款从对账单里消失，取消时连货也从库存消失。
现在：改记成一笔「他给我货」的往来（能在对账单里看到、结账、撤销）；已经结过账的才变成普通库存。
用编出来的小数据，GitHub 上也跑。运行：python3 tests/test_resv_release.py"""
import os, datetime, functools, http.server, json, subprocess, sys, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
EXPOSE = "\nwindow.__GM = { S, derive, ledgerNet, pendingPicks, finBook, openXfers };\n})();"
D = (datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date() - datetime.timedelta(days=3)).isoformat()
A, B = "合伙人甲", "合伙人乙"

item = lambda sku, ser, en: (sku, {"sku": sku, "series": ser, "variant": en, "name": en, "price_aud": 60, "cost_aud": 30, "status": "在售"})
V1 = {
    "items": dict([item("XF-01", "Bar Pro", "Banana Buzz"), item("XF-02", "Bar Pro", "Grape Ice"), item("XF-05", "Bar Pro", "Peach Ice")]),
    "movements": {"b-0-XF-01": {"type": "in", "sku": "XF-01", "name": "Banana Buzz", "qty": 5, "cost": 150, "date": D, "at": D + "T01:00:00Z", "batch_id": "b-0", "expense_id": "b-0-cost", "note": "进货"}},
    "expenses": {"b-0-cost": {"date": D, "at": D + "T01:00:00Z", "amount": 150, "category": "进货成本", "note": "进货", "batch_id": "b-0"}},
    "orders": {}, "settlements": {}, "transfers": {}, "purchases": {}, "customers": {}, "followups": {},
    "meta": {"backfill": {"done": True}},
}
# 以前找甲、乙各拿过一次货（已结账），「找谁拿」才有两个名字可以分
for k, w in enumerate((A, B)):
    oid, at = f"o-old-{k}", D + f"T0{k + 2}:00:00Z"
    V1["orders"][oid] = {"status": "paid", "date": D, "at": at, "lines": [{"sku": "XF-02", "name": "Grape Ice", "qty": 1, "unit_price": 60}], "delivery_fee": 0, "note": "", "payment": "现金", "pick_from": w, "partner_settlement_id": f"s-old-{k}"}
    V1["movements"][oid + "-XF-02"] = {"type": "out", "sku": "XF-02", "name": "Grape Ice", "qty": 1, "date": D, "at": at, "order_id": oid}
    V1["movements"][oid + "-pick-XF-02"] = {"type": "in", "sku": "XF-02", "name": "Grape Ice", "qty": 1, "cost": 30, "date": D, "at": at, "order_id": oid, "batch_id": oid + "-pick", "expense_id": oid + "-pick-cost", "note": "按单向合伙人拿货"}
    V1["expenses"][oid + "-pick-cost"] = {"date": D, "at": at, "amount": 30, "category": "进货成本", "note": "按单拿货 Grape Ice ×1", "batch_id": oid + "-pick"}
    V1["settlements"][f"s-old-{k}"] = {"date": D, "at": D + f"T0{k + 4}:00:00Z", "order_ids": [oid], "transfer_ids": [], "po_ids": [], "qty": {"Bar Pro": 1}, "amount": 30, "paid": 30, "partner": w, "payment": "现金", "note": ""}
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "v1.json").write_text(json.dumps(V1, ensure_ascii=False), encoding="utf8")
subprocess.run(["node", str(ROOT / "v2_seed.js"), str(tmp / "v1.json"), str(tmp / "v2.json")], check=True, capture_output=True)
V2 = json.loads((tmp / "v2.json").read_text(encoding="utf8"))
V2["meta"] = {"schema": {"version": 2, "migrated_at": D + "T05:00:00.000Z"}, "backfill": {"done": True}}


class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/index.html"):
            src = (PUB / "index.html").read_text(encoding="utf8"); i = src.rindex("})();")
            b = (src[:i] + EXPOSE + src[i + 5:]).encode("utf8")
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        return super().do_GET()


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=str(PUB)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/index.html"
results = []
def check(name, ok, extra=""):
    results.append(ok); print(("✅ " if ok else "❌ ") + name + (("  " + str(extra)) if extra and not ok else ""))


def open_app(br, seed):
    ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
    ctx.add_init_script("window.__SEED=" + json.dumps(seed, ensure_ascii=False) + ";")
    pg = ctx.new_page(); pg.set_default_timeout(8000); pg.on("pageerror", lambda e: (print("   页面报错：", e), results.append(False)))
    pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
    pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
    pg.goto(URL); pg.wait_for_function("window.__GM && window.__GM.S.items.length === 3 && window.__GM.S.loaded", timeout=15000); pg.wait_for_timeout(500)
    return ctx, pg


go = lambda pg, h: (pg.evaluate(f"location.hash = '#{h}'"), pg.wait_for_timeout(250))
net = lambda pg, w: pg.evaluate("(w) => window.__GM.ledgerNet(w)", w)          # > 0 = 应付他
stock = lambda pg, sku: pg.evaluate("(k) => window.__GM.derive().st[k] || 0", sku)
ids = lambda pg, k="orders": set(pg.evaluate(f"window.__GM.S.{k}.map((x) => x.id)"))

def save(pg):
    pg.wait_for_timeout(300); pg.click("#sheet-save")
    try: pg.wait_for_selector("#sheet", state="hidden", timeout=1500)
    except Exception:
        if pg.is_visible("#sheet-save") and not pg.is_visible("#sheet-err"): pg.click("#sheet-save")
        pg.wait_for_selector("#sheet", state="hidden", timeout=4000)
    pg.wait_for_timeout(450)

def reserve(pg, name, qty, who, split=False):
    before = ids(pg); go(pg, "finance"); pg.click("#fin-sale"); pg.wait_for_selector("#f-skuq-0")
    pg.fill("#f-skuq-0", name); pg.press("#f-skuq-0", "Enter"); pg.fill("#f-qty-0", str(qty)); pg.check("#f-resv"); pg.fill("#f-cust", "测试客人")
    pg.fill("#f-pfrom", who); pg.dispatch_event("#f-pfrom", "input")
    if split: pg.click("#f-split-tog"); pg.wait_for_timeout(150); pg.click(f'#f-split [data-si="1"][data-sw="{B if who == A else A}"]')
    if pg.is_visible("#f-lumpon") and pg.is_checked("#f-lumpon"): pg.uncheck("#f-lumpon")
    save(pg); return sorted(ids(pg) - before)[0]

def picked(pg, w, oid):
    go(pg, "finance"); pg.click(f'#f-owe [data-lg-open="{w}"]'); pg.wait_for_selector(f'#sheet [data-lg="picked"][data-id="{oid}"]')
    pg.evaluate(f"""() => {{ const b = document.querySelector('#sheet [data-lg="picked"][data-id="{oid}"]'); b.click(); b.click(); }}""")
    pg.wait_for_timeout(900)
    if pg.is_visible("#sheet"): pg.click("#sheet-close"); pg.wait_for_timeout(250)

def edit_resv(pg, oid, fn):
    go(pg, "customers"); pg.evaluate(f"""() => document.querySelector('[data-edit-order="{oid}"]').click()"""); pg.wait_for_selector("#f-skuq-0"); fn(pg); save(pg)

def cancel_resv(pg, oid):
    go(pg, "customers"); pg.evaluate(f"""() => {{ const b = document.querySelector('[data-void-order="{oid}"]'); b.click(); b.click(); }}"""); pg.wait_for_timeout(900)

def settle(pg, w):
    before = ids(pg, "settles"); go(pg, "partner"); pg.click(f'#ptx-bal [data-ptx-settle="{w}"]'); pg.wait_for_selector("#f-net"); save(pg)
    return sorted(ids(pg, "settles") - before)[0]

def books_ok(pg):
    """每批拿货的支出 = 那一批流水的成本；往来单的调入 = 往来流水；没有脱单的拿货"""
    S = pg.evaluate("() => JSON.parse(JSON.stringify({ m: window.__GM.S.moves, x: window.__GM.S.expenses, t: window.__GM.S.transfers }))")
    bad = []
    for x in S["x"]:
        if x.get("category") == "进货成本" and x.get("batch_id"):
            c = sum(m.get("cost") or 0 for m in S["m"] if m.get("batch_id") == x["batch_id"] and m["type"] == "in")
            if abs(c - x["amount"]) > 0.005: bad.append(f"支出 {x['id']} {x['amount']} ≠ 流水 {c}")
    for b in {m["batch_id"] for m in S["m"] if m.get("batch_id") and m["type"] == "in" and m.get("cost")} - {x.get("batch_id") for x in S["x"]}: bad.append("有成本没支出 " + b)
    for t in S["t"]:
        for l in t.get("in") or []:
            mm = [m for m in S["m"] if m.get("transfer_id") == t["id"] and m["sku"] == l["sku"] and m["type"] == "in"]
            if sum(m["qty"] for m in mm) != l["qty"] or abs(sum(m.get("cost") or 0 for m in mm) - l["qty"] * (l.get("unit") or 0)) > 0.005: bad.append("往来 " + t["id"] + " 跟流水对不上")
    bad += ["脱单的拿货 " + m["id"] for m in S["m"] if (m.get("batch_id") or "").endswith("-pick") and not m.get("order_id") and m["batch_id"][:-5] not in pg.evaluate("window.__GM.S.settles.flatMap((s) => s.order_ids || [])")]
    return bad


with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    for mode, seed in (("旧结构", V1), ("新结构", V2)):
        print("== " + mode)
        # 1. 拿到 2 根以后，客人改成只要 1 根
        ctx, pg = open_app(br, seed)
        check("用的是" + mode, pg.evaluate("!!window.__fbV2store") == (mode == "新结构"))
        oid = reserve(pg, "Grape Ice", 2, A)
        check("预定还没拿：不算应付", net(pg, A) == 0 and stock(pg, "XF-02") == 0)
        picked(pg, A, oid)
        check("点「已拿到」：应付甲 60，库存 2", net(pg, A) == 60 and stock(pg, "XF-02") == 2, (net(pg, A), stock(pg, "XF-02")))
        edit_resv(pg, oid, lambda g: g.fill("#f-qty-0", "1"))
        check("预定改成 1 根：货还在（2 根），照样应付甲 60", net(pg, A) == 60 and stock(pg, "XF-02") == 2, (net(pg, A), stock(pg, "XF-02")))
        ts = pg.evaluate("window.__GM.S.transfers"); t = ts[0] if ts else {}
        check("改记成一笔往来：甲给我 Grape ×2 @30，没结账", len(ts) == 1 and t.get("partner") == A and t.get("in") == [{"sku": "XF-02", "name": "Grape Ice", "qty": 2, "unit": 30}] and not t.get("out") and not t.get("partner_settlement_id"), ts)
        check("预定不再要找甲拿（手上的货够）", pg.evaluate("window.__GM.pendingPicks().length") == 0)
        check("账对得上（支出 = 流水成本、往来 = 流水）", not books_ok(pg), books_ok(pg))
        if mode == "新结构":
            check("新结构：没有存复制品", not [k for k in pg.evaluate("Object.entries(__server('v2_movements')).filter(([, v]) => !v._deleted).map(([k]) => k)") if k.startswith(("o-", "t-"))])
        sid = settle(pg, A)
        check("跟甲结账 60 → 两清", net(pg, A) == 0 and pg.evaluate("(s) => window.__GM.S.settles.find((x) => x.id === s).amount", sid) == 60)
        ctx.close()

        # 2. 拿到以后换口味
        ctx, pg = open_app(br, seed)
        oid = reserve(pg, "Grape Ice", 1, A); picked(pg, A, oid)
        edit_resv(pg, oid, lambda g: (g.fill("#f-skuq-0", "Peach Ice"), g.press("#f-skuq-0", "Enter")))
        check("换口味：Grape 留在库存，照样应付甲 30；Peach 还要找甲拿", net(pg, A) == 30 and stock(pg, "XF-02") == 1 and pg.evaluate("window.__GM.pendingPicks().map((g) => g.moves.map((m) => m.sku + '×' + m.qty).join()).join()") == "XF-05×1", (net(pg, A), stock(pg, "XF-02")))
        check("账对得上", not books_ok(pg), books_ok(pg))
        ctx.close()

        # 3. 拿到以后取消预定（没结账）
        ctx, pg = open_app(br, seed)
        oid = reserve(pg, "Grape Ice", 2, A); picked(pg, A, oid); cancel_resv(pg, oid)
        check("取消预定：订单没了，货留在库存（2 根），照样应付甲 60", oid not in ids(pg) and stock(pg, "XF-02") == 2 and net(pg, A) == 60, (stock(pg, "XF-02"), net(pg, A)))
        check("提示里写明照样欠甲", "照样欠" + A in pg.inner_text("#toast"), pg.inner_text("#toast"))
        check("账对得上", not books_ok(pg), books_ok(pg))
        # 货退回给甲了 → 撤销那笔往来
        tid = pg.evaluate("window.__GM.S.transfers[0].id"); go(pg, "partner")
        pg.evaluate(f"""() => {{ const b = document.querySelector('#ptx-log [data-void-xfer="{tid}"]'); b.click(); b.click(); }}"""); pg.wait_for_timeout(900)
        check("货退回去了 → 撤销那笔往来：库存 0，不欠甲", stock(pg, "XF-02") == 0 and net(pg, A) == 0, (stock(pg, "XF-02"), net(pg, A)))
        ctx.close()

        # 4. 拿到并且已经跟甲结过账，再取消：货留作普通库存，不会又欠一次
        ctx, pg = open_app(br, seed)
        oid = reserve(pg, "Grape Ice", 2, A); picked(pg, A, oid); settle(pg, A); cancel_resv(pg, oid)
        check("已结账的预定取消：货留在库存，不欠甲，没有多出往来", stock(pg, "XF-02") == 2 and net(pg, A) == 0 and pg.evaluate("window.__GM.S.transfers.length") == 0, (stock(pg, "XF-02"), net(pg, A)))
        ctx.close()

        # 5. 一单分开找甲、乙拿，都拿到了，只跟甲结了，再取消：乙那 1 根照样欠
        ctx, pg = open_app(br, seed)
        oid = reserve(pg, "Grape Ice", 2, A, split=True)
        picked(pg, A, oid)
        check("分开拿，先拿到甲的 1 根：剩下那根还是找乙拿（以前又算回甲）", pg.evaluate("window.__GM.pendingPicks().map((g) => g.who).join()") == B, pg.evaluate("window.__GM.pendingPicks().map((g) => g.who).join()"))
        picked(pg, B, oid)
        check("分开拿：应付甲 30、乙 30", net(pg, A) == 30 and net(pg, B) == 30, (net(pg, A), net(pg, B)))
        settle(pg, A); cancel_resv(pg, oid)
        check("只跟甲结过，取消预定：不欠甲，照样应付乙 30，货 2 根都在", net(pg, A) == 0 and net(pg, B) == 30 and stock(pg, "XF-02") == 2, (net(pg, A), net(pg, B), stock(pg, "XF-02")))
        check("账对得上", not books_ok(pg), books_ok(pg))
        ctx.close()

        # 5b. 分开拿，只拿到甲的 1 根，客人就来付款结算：剩下那根记成找乙拿
        ctx, pg = open_app(br, seed)
        oid = reserve(pg, "Grape Ice", 2, A, split=True); picked(pg, A, oid)
        go(pg, "customers"); pg.evaluate(f"""() => document.querySelector('[data-settle="{oid}"]').click()"""); pg.wait_for_timeout(400)
        if pg.is_visible("#sheet"):
            if pg.locator("#sheet input[name='f-payr'][value='现金']").count(): pg.locator("#sheet input[name='f-payr'][value='现金']").check()
            elif pg.is_visible("#f-pay"): pg.select_option("#f-pay", "现金")
            save(pg)
        check("结算时剩下那根记在乙头上：应付甲 30、乙 30", net(pg, A) == 30 and net(pg, B) == 30 and stock(pg, "XF-02") == 0, (net(pg, A), net(pg, B), stock(pg, "XF-02")))
        check("账对得上", not books_ok(pg), books_ok(pg))
        ctx.close()

        # 6. 没拿到货的预定，取消照旧
        ctx, pg = open_app(br, seed)
        oid = reserve(pg, "Grape Ice", 2, A); cancel_resv(pg, oid)
        check("没拿货的预定取消：什么都不留", oid not in ids(pg) and pg.evaluate("window.__GM.S.transfers.length") == 0 and net(pg, A) == 0 and stock(pg, "XF-02") == 0)
        ctx.close()
    br.close()

print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
