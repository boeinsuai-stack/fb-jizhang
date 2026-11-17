"""付款方式统一 + 订货单「一起改」放在下面（2026-11-17 Bowen）
- 「结款的时候为什么没有一部分现金、一部分转账」：订货结款以前是下拉框，只有 现金/银行转账/PayID/其他。
  现在所有收钱/付钱的弹窗都用同一排小标签 + 「现金+转账」（订货结款、代送费、改已卖出的单、结算要填价的预定、合伙人拿货卖出、记往来当场付、合伙人拿货/我拿货当场付）
- 订货单：「整系列每根 $」以前在每个系列框的上面、「选中的每种都订 N 根」在下面 → 两个一起放到所有口味下面「选中的一起改」
用编出来的小数据，旧结构 / 新结构各一遍，GitHub 上也跑。运行：python3 tests/test_pay_mix.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
IT = lambda sku, ser, v, n, c: {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": 60, "cost_aud": c, "status": "在售"}
V1 = {"items": {"XF-01": IT("XF-01", "Bar Pro", "Banana Buzz", "香蕉", 30), "XF-02": IT("XF-02", "Bar Pro", "Grape Ice", "葡萄冰", 30), "XF-03": IT("XF-03", "Bar Pro", "Blueberry Ice", "蓝莓冰", 30),
                "XF-04": IT("XF-04", "Ali", "Pink Lemon", "粉柠檬", 25)},
      "movements": {f"in-{k}": {"type": "in", "sku": k, "name": k, "qty": 20, "date": TODAY, "at": TODAY + "T01:00:00Z", "note": "进货", "cost": 400} for k in ("XF-01", "XF-02", "XF-03", "XF-04")},
      "orders": {"o-sold": {"status": "paid", "date": TODAY, "at": TODAY + "T02:00:00Z", "lines": [{"sku": "XF-01", "name": "香蕉", "qty": 1, "unit_price": 60}], "delivery_fee": 0, "payment": "现金", "customer": "Amy"},
                 "o-resv": {"status": "reserved", "date": TODAY, "at": TODAY + "T03:00:00Z", "lines": [{"sku": "XF-02", "name": "葡萄冰", "qty": 2, "unit_price": None}], "delivery_fee": 0, "payment": None}},
      "expenses": {"p-1-pay": {"date": TODAY, "at": TODAY + "T00:00:00Z", "amount": 300, "category": "进货成本", "note": "订货", "po_id": "p-1"}},
      "purchases": {"p-1": {"date": TODAY, "at": TODAY + "T00:00:00Z", "note": "", "supplier": "合伙人甲", "paid": False, "paid_date": None, "total": 300,
                            "lines": [{"sku": "XF-01", "name": "香蕉", "series": "Bar Pro", "qty": 10, "unit_cost": 30}]}},
      "transfers": {}, "settlements": {}, "customers": {}, "followups": {}}
for k in ("XF-01", "XF-02", "XF-03", "XF-04"): V1["movements"][f"in-{k}"]["name"] = V1["items"][k]["name"]
V1["movements"]["o-sold-XF-01"] = {"type": "out", "sku": "XF-01", "name": "香蕉", "qty": 1, "date": TODAY, "at": TODAY + "T02:00:00Z", "order_id": "o-sold"}
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "v1.json").write_text(json.dumps(V1, ensure_ascii=False), encoding="utf8")
subprocess.run(["node", str(ROOT / "v2_seed.js"), str(tmp / "v1.json"), str(tmp / "v2.json")], check=True, capture_output=True)
V2 = json.loads((tmp / "v2.json").read_text(encoding="utf8")); V2["meta"] = {"schema": {"version": 2}, "backfill": {"done": True}}

EXPOSE = "\nwindow.__GM = { S };\n})();"
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

go = lambda pg, h: (pg.evaluate(f"location.hash = '#{h}'"), pg.wait_for_timeout(300))
S = lambda pg, col: pg.evaluate(f"window.__GM.S.{col}")
def save(pg):
    pg.wait_for_timeout(200); pg.click("#sheet-save")
    try: pg.wait_for_selector("#sheet", state="hidden", timeout=3000)
    except Exception: pass
    pg.wait_for_timeout(450)
def close(pg): pg.click("#sheet-close"); pg.wait_for_timeout(250)
def chips_ok(pg):  # 付款方式是一排小标签、有现金+转账、没有下拉框
    return pg.locator("#sheet #f-paychips input[name=f-payr]").count() == 5 and pg.locator('#sheet #f-paychips input[value="现金+转账"]').count() == 1 and pg.locator("#sheet select#f-pay").count() == 0
def mix(pg, cash, other=None):
    pg.click('#f-paychips label:has(input[value="现金+转账"])'); pg.wait_for_timeout(120)
    pg.fill("#f-paycash", str(cash))
    if other: pg.select_option("#f-payother", other)
    pg.wait_for_timeout(150)

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    for mode in ("旧结构", "新结构"):
        seed = V2 if mode == "新结构" else dict(V1, meta={"backfill": {"done": True}})
        ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
        ctx.add_init_script("window.__SEED = " + json.dumps(seed, ensure_ascii=False) + "; try { localStorage.setItem('mk-ptdir', 'take'); } catch (_) {}")
        pg = ctx.new_page(); pg.set_default_timeout(8000); pg.on("pageerror", lambda e: (print("   页面报错：", e), results.append(False)))
        pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
        pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
        pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.goto(URL); pg.wait_for_function("window.__GM && window.__GM.S.loaded", timeout=15000); pg.wait_for_timeout(500)
        print("== " + mode)

        # 1. 订货结款：现金+转账
        go(pg, "purchases"); pg.click('[data-pay-po="p-1"]'); pg.wait_for_selector("#f-paychips")
        check("订货结款：付款方式是一排小标签，有「现金+转账」，没有下拉框", chips_ok(pg))
        mix(pg, 100)
        h = pg.inner_text("#f-mixhint") if pg.is_visible("#f-mixhint") else ""
        check("填现金 $100 → 写「现金 $100 + PayID $200」（订货 $300）", h == "现金 $100 + PayID $200", h)
        pg.fill("#f-paycash", "400"); pg.click("#sheet-save"); pg.wait_for_timeout(400)
        check("现金比订货金额还多：不让存", pg.is_visible("#sheet") and "现金" in pg.inner_text("#sheet-err"))
        pg.fill("#f-paycash", "100"); save(pg)
        po = [x for x in S(pg, "purchases") if x["id"] == "p-1"][0]
        check("存了：已付、现金 $100 + PayID", po.get("paid") is True and po.get("payment") == "现金+转账" and po.get("pay_cash") == 100 and po.get("pay_other") == "PayID", {k: po.get(k) for k in ("paid", "payment", "pay_cash", "pay_other")})
        go(pg, "purchases")
        check("订货列表上写「已付 … · 现金 $100 + PayID $200」", "现金 $100 + PayID $200" in pg.inner_text("#view-purchases") if pg.locator("#view-purchases").count() else "现金 $100 + PayID $200" in pg.inner_text("body"))

        # 2. 订货单：一起改根数、一起改每根成本都在下面
        pg.click("#po-new"); pg.wait_for_selector("#f-ptiles")
        pg.click('[data-padd="XF-01"]'); pg.wait_for_timeout(100)
        check("只选一种口味：下面「选中的一起改」不出现", pg.is_hidden("#f-bulk"))
        check("系列框头上不再有价钱框", pg.locator("#f-lines .po-gh input").count() == 0)
        pg.click('[data-padd="XF-02"]'); pg.click('[data-padd="XF-03"]'); pg.click('#f-ptabs [data-pt="Ali"]'); pg.click('[data-padd="XF-04"]'); pg.wait_for_timeout(150)
        order = pg.evaluate("(() => { const a = [...document.querySelectorAll('#f-lines .line, #f-bulk')]; return a.map((x) => x.id || 'line'); })()")
        check("「选中的一起改」在所有口味下面", order[-1] == "f-bulk" and order.count("line") == 4, order)
        srp = pg.evaluate("[...document.querySelectorAll('#f-serp input')].map((i) => i.dataset.sr)")
        check("里面：每种都订 N 根 + Bar Pro 每根 $（Ali 只有一种，不用一起改）", pg.is_visible("#f-allq") and srp == ["Bar Pro"], srp)
        pg.fill('#f-bulk input[data-sr="Bar Pro"]', "28"); pg.fill("#f-allq", "5"); pg.wait_for_timeout(150)
        rows = pg.evaluate("[...document.querySelectorAll('#f-lines .line')].map((r) => [r.querySelector('[id^=f-qty-]').value, r.querySelector('[id^=f-ucost-]').value])")
        check("Bar Pro 三种都变 $28，四种都 5 根；Ali 保持自己的成本", rows == [["5", "28"], ["5", "28"], ["5", "28"], ["5", "25"]], rows)
        pg.click('#f-ptabs [data-pt="Ali"]'); pg.click('[data-padd="XF-04"]'); pg.wait_for_timeout(100)
        check("改根数时价钱框不会被重画（填的 $28 还在）", pg.input_value('#f-bulk input[data-sr="Bar Pro"]') == "28")
        n0 = len(S(pg, "purchases")); save(pg)
        P = [x for x in S(pg, "purchases") if x["id"] != "p-1"]
        L = {l["sku"]: (l["qty"], l["unit_cost"]) for l in (P[0]["lines"] if P else [])}
        check("存的订货单：Bar Pro 3×5 根 $28、Pink Lemon 6 根 $25", L == {"XF-01": (5, 28), "XF-02": (5, 28), "XF-03": (5, 28), "XF-04": (6, 25)}, L)

        # 3. 代送费：现金+转账
        go(pg, "finance"); pg.click("#fin-fee"); pg.wait_for_selector("#f-paychips")
        check("代送费：小标签 + 现金+转账", chips_ok(pg))
        pg.fill("#f-fee", "15"); mix(pg, 5, "银行转账"); save(pg)
        d = [o for o in S(pg, "orders") if o.get("kind") == "delivery"]
        check("代送费存了：现金 $5 + 银行转账", len(d) == 1 and d[0].get("payment") == "现金+转账" and d[0].get("pay_cash") == 5 and d[0].get("pay_other") == "银行转账", d and {k: d[0].get(k) for k in ("payment", "pay_cash", "pay_other")})

        # 4. 改已卖出的单：小标签，原来的「现金」选着，可以改成现金+转账
        go(pg, "finance"); pg.evaluate("""() => document.querySelector('[data-edit-order="o-sold"]').click()"""); pg.wait_for_selector("#f-paychips")
        check("改已卖出的单：小标签，原来选的「现金」还选着", chips_ok(pg) and pg.is_checked('#f-paychips input[value="现金"]'))
        mix(pg, 20); save(pg)
        o = [x for x in S(pg, "orders") if x["id"] == "o-sold"][0]
        check("改成 现金 $20 + PayID", o.get("payment") == "现金+转账" and o.get("pay_cash") == 20, {k: o.get(k) for k in ("payment", "pay_cash", "pay_other")})

        # 5. 结算要填价的预定：小标签
        go(pg, "customers"); pg.evaluate("""() => document.querySelector('[data-settle="o-resv"]').click()"""); pg.wait_for_timeout(500)
        check("结算还没填价的预定：小标签 + 现金+转账", chips_ok(pg))
        pg.fill("#f-price-0", "60"); mix(pg, 50); save(pg)
        o = [x for x in S(pg, "orders") if x["id"] == "o-resv"][0]
        check("结算了：现金 $50 + PayID（合计 $120）", o.get("status") == "paid" and o.get("payment") == "现金+转账" and o.get("pay_cash") == 50, {k: o.get(k) for k in ("status", "payment", "pay_cash")})

        # 6. 合伙人拿货 · 卖出
        go(pg, "partner"); pg.evaluate("document.getElementById('pt-new').click()"); pg.wait_for_selector("#f-paychips")
        check("合伙人拿货 · 卖出：小标签 + 现金+转账", chips_ok(pg))
        close(pg)

        # 7. 记往来（他拿我的货，当场付了）：勾上才出现小标签
        go(pg, "finance"); pg.evaluate("document.getElementById('fin-xfer').click()"); pg.wait_for_selector("#f-xpaid")
        check("记往来：没勾「当场付了」看不到付款方式", pg.is_hidden("#f-xpaywrap"))
        pg.check("#f-xpaid"); pg.wait_for_timeout(150)
        check("勾上：小标签 + 现金+转账", pg.is_visible("#f-paychips") and chips_ok(pg))
        close(pg)

        # 8. 合伙人页购物车 → 合伙人拿货当场付：现金+转账存进结账记录
        go(pg, "partner"); pg.wait_for_timeout(300)
        pg.evaluate("""() => { const b = () => document.querySelector('#ptx-tiles [data-padd="XF-03"]'); b().click(); b().click(); }"""); pg.wait_for_timeout(250)
        pg.click("#cb-go"); pg.wait_for_selector("#f-xpaid")
        pg.fill("#f-xwho", "合伙人甲"); pg.fill("#f-unit-0", "30"); pg.check("#f-xpaid"); pg.wait_for_timeout(150)
        check("合伙人拿货当场付：小标签 + 现金+转账", chips_ok(pg))
        mix(pg, 20)
        h = pg.inner_text("#f-mixhint") if pg.is_visible("#f-mixhint") else ""
        check("拿 2 根 × $30：写「现金 $20 + PayID $40」", h == "现金 $20 + PayID $40", h)
        save(pg)
        st = [x for x in S(pg, "settles") if x.get("note") == "当场付清"]
        check("结账记录：现金 $20 + PayID、当场付清", len(st) == 1 and st[0].get("payment") == "现金+转账" and st[0].get("pay_cash") == 20 and st[0].get("pay_other") == "PayID", st and {k: st[0].get(k) for k in ("payment", "pay_cash", "pay_other", "paid")})

        # 9. 新结构：订货单上的 pay_cash / pay_other 迁移成新结构再算回来一字不差
        if mode == "新结构":
            olds = pg.evaluate("Object.fromEntries(window.__GM.S.purchases.map((o) => { const x = Object.assign({}, o); delete x.id; delete x._v; return [o.id, x]; }))")
            (tmp / "rt.json").write_text(json.dumps(dict(V1, purchases=olds), ensure_ascii=False), encoding="utf8")
            out = subprocess.run(["node", "-e", "const {migrate,project}=require(process.argv[1]);const d=JSON.parse(require('fs').readFileSync(process.argv[2],'utf8'));const P=project(migrate(d));console.log(JSON.stringify(Object.fromEntries(P.purchases.map(o=>[o.id,[o.payment||null,o.pay_cash??null,o.pay_other||null]]))))",
                                  str(PUB / "v2.js"), str(tmp / "rt.json")], capture_output=True, text=True)
            got = json.loads(out.stdout or "{}"); want = {k: [v.get("payment"), v.get("pay_cash"), v.get("pay_other")] for k, v in olds.items()}
            check("新结构存得住订货单的 现金+转账（迁移再算回来一样）", got == want, (got, want, out.stderr[:200]))
        ctx.close()
    br.close()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
