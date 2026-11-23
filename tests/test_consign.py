"""代销（2026-11-23 Bowen：合伙人 / 供货商把货放这里代卖，卖了再付；先到的先卖；欠的钱并进对账单）
- 订货单「付款」多一个「代销（卖了再付）」：必须写供货人；不记进货支出
- 卖出按到货先后（FIFO）算卖掉的是哪一批：卖掉代销那批里的几根 = 欠他几根的钱（单价 = 代销单上的）
- 订货卡片：到货 / 卖出 / 退回 / 在你这；还欠多少（卖出还没结的几根）；每种「卖了 x · 剩 y」；「去对账单结」「退回给他」
- 对账单 / 结账：多「代销卖出 · 还没付」，结账记 consign_settles（结了卖出的那几根），撤销结账跟着撤；之后再卖的再欠
- 退回给他：只能退在你这的，记 adjust + ret_po，不算损耗、不欠钱；能撤销
用编出来的小数据，旧结构 / 新结构各一遍。运行：python3 tests/test_consign.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
IT = lambda sku, ser, v, n, c: {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": 60, "cost_aud": c, "status": "在售"}
import datetime as _dt
D = lambda n: (_dt.date.fromisoformat(TODAY) + _dt.timedelta(days=n)).isoformat()
def SALE(oid, sku, q, d): return (oid, {"status": "paid", "date": D(d), "at": D(d) + "T05:00:00Z", "customer": "Amy", "lines": [{"sku": sku, "name": sku, "qty": q, "unit_price": 60}], "delivery_fee": 0, "payment": "现金", "note": ""})
V1 = {"items": {"XF-01": IT("XF-01", "Bar Pro", "Banana Buzz", "香蕉", 30), "XF-02": IT("XF-02", "Bar Pro", "Grape Ice", "葡萄冰", 30), "XF-03": IT("XF-03", "Bar Pro", "Mint", "薄荷", 30)},
      "movements": {"b-own-XF-01": {"type": "in", "sku": "XF-01", "name": "香蕉", "qty": 5, "date": D(-10), "at": D(-10) + "T01:00:00Z", "cost": 150, "batch_id": "b-own", "expense_id": "b-own-cost", "note": "进货"},
                    "p-c-r1-XF-01": {"type": "in", "sku": "XF-01", "name": "香蕉", "qty": 10, "date": D(-5), "at": D(-5) + "T02:00:00Z", "po_id": "p-c", "po_line": "XF-01", "receipt_id": "r1", "cost": 280, "note": "订货到货"},
                    "p-c-r1-XF-02": {"type": "in", "sku": "XF-02", "name": "葡萄冰", "qty": 10, "date": D(-5), "at": D(-5) + "T02:00:00Z", "po_id": "p-c", "po_line": "XF-02", "receipt_id": "r1", "cost": 280, "note": "订货到货"},
                    "o-1-XF-01": {"type": "out", "sku": "XF-01", "name": "香蕉", "qty": 7, "date": D(-3), "at": D(-3) + "T05:00:00Z", "order_id": "o-1"},
                    "o-2-XF-02": {"type": "out", "sku": "XF-02", "name": "葡萄冰", "qty": 3, "date": D(-2), "at": D(-2) + "T05:00:00Z", "order_id": "o-2"},
                    "p-n-r1-XF-03": {"type": "in", "sku": "XF-03", "name": "薄荷", "qty": 5, "date": D(-4), "at": D(-4) + "T02:00:00Z", "po_id": "p-n", "po_line": "XF-03", "receipt_id": "r1", "cost": None, "note": "订货到货"},
                    "o-3-XF-03": {"type": "out", "sku": "XF-03", "name": "薄荷", "qty": 2, "date": D(-1), "at": D(-1) + "T05:00:00Z", "order_id": "o-3"}},
      "expenses": {"b-own-cost": {"date": D(-10), "at": D(-10) + "T01:00:00Z", "amount": 150, "category": "进货成本", "note": "进货", "batch_id": "b-own"}},
      "purchases": {"p-c": {"date": D(-6), "at": D(-6) + "T01:00:00Z", "note": "", "supplier": "合伙人甲", "paid": False, "paid_date": None, "consign": True, "total": 560,
                            "lines": [{"sku": "XF-01", "name": "香蕉", "series": "Bar Pro", "qty": 10, "unit_cost": 28}, {"sku": "XF-02", "name": "葡萄冰", "series": "Bar Pro", "qty": 10, "unit_cost": 28}]},
                    "p-n": {"date": D(-4), "at": D(-4) + "T01:00:00Z", "note": "", "supplier": "合伙人乙", "paid": False, "paid_date": None, "consign": True, "total": 0,
                            "lines": [{"sku": "XF-03", "name": "薄荷", "series": "Bar Pro", "qty": 5, "unit_cost": None}]}},
      "orders": dict([SALE("o-1", "XF-01", 7, -3), SALE("o-2", "XF-02", 3, -2), SALE("o-3", "XF-03", 2, -1)]), "settlements": {}, "transfers": {}, "customers": {}, "followups": {}}
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
def po(pg, pid="p-c"): return next(x for x in S(pg, "purchases") if x["id"] == pid)
def card(pg, pid="p-c"): return pg.locator("#po-list article.po").filter(has=pg.locator(f'[data-edit-po="{pid}"]')).first
def money_(t): return float(str(t).replace("$", "").replace(",", ""))

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    for mode in ("旧结构", "新结构"):
        seed = V2 if mode == "新结构" else dict(V1, meta={"backfill": {"done": True}})
        ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
        ctx.add_init_script("window.__SEED = " + json.dumps(seed, ensure_ascii=False) + ";")
        pg = ctx.new_page(); pg.set_default_timeout(8000); pg.on("pageerror", lambda e: (print("   页面报错：", e), results.append(False)))
        pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
        pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
        pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.goto(URL); pg.wait_for_function("window.__GM && window.__GM.S.loaded", timeout=15000); pg.wait_for_timeout(500)
        print("== " + mode)
        go(pg, "purchases"); pg.click('#po-filter [data-pf="all"]') if pg.locator('#po-filter [data-pf="all"]').count() else None
        t = card(pg).inner_text()
        check("卡片：代销；到货 20 · 卖出 5（香蕉先卖掉自己先到的 5 根，再卖代销 2 根；葡萄冰 3）· 在你这 15", "代销" in t and "到货 20 根 · 卖出 5 根 · 在你这 15 根" in t, t[:300])
        check("还欠 $140（卖出还没结的 5 根 × $28）", "还欠 $140（卖出还没结的 5 根）" in t, t[:300])
        check("每种写「卖了 2 · 剩 8」「卖了 3 · 剩 7」", "卖了 2 · 剩 8" in t and "卖了 3 · 剩 7" in t)
        check("代销不记进货支出", not [x for x in S(pg, "expenses") if x.get("po_id") == "p-c"])
        go(pg, "partner"); pg.wait_for_timeout(200)
        bal = pg.inner_text("#ptx-bal")
        check("合伙人页：你欠 合伙人甲 $140", "你欠 合伙人甲 $140" in bal, bal)
        pg.click('[data-lg-open="合伙人甲"]'); pg.wait_for_timeout(300)
        lg = pg.inner_text("#sheet")
        check("对账单：「代销卖出」香蕉 ×2、葡萄冰 ×3，你欠他 · 代销卖出 $140", "代销卖出 Bar Pro Banana Buzz" in lg and "代销卖出 Bar Pro Grape Ice" in lg and "你欠他 · 代销卖出" in lg, lg[:500])
        check("对账单里代销那一项没有「结款」（那是整张单标成付清）", pg.locator('#sheet [data-lg="po-pay"]').count() == 0)
        close(pg)
        lg = pg.inner_text("#ptx-log")
        check("往来记录：标「代销」，写货值 $560 · 卖出 5 根（还没结 5 根）· 在你这 15 根", "代销" in lg and "货值 $560 · 卖出 5 根（还没结 5 根） · 在你这 15 根" in lg, lg[:400])
        pg.evaluate("document.querySelector('#ptx-log') && 0")
        go(pg, "finance"); fc = pg.evaluate("document.getElementById('f-cash').textContent")
        check("财务「现有库存」下面分出：其中代销 18 根 · $420（合伙人乙那 3 根没单价）", "其中代销（他的货，卖了才付）" in fc and "18 根 · $420" in fc, fc)
        # 没填单价的代销单
        go(pg, "purchases"); t = card(pg, "p-n").inner_text()
        check("没填单价：卡片提示「2 根卖出了但没填单价」，不写「都结清了」", "2 根卖出了但没填单价" in t and "结清" not in t, t[:300])
        go(pg, "partner"); check("没填单价的不进对账单（合伙人乙不欠钱）", "合伙人乙" not in pg.inner_text("#ptx-bal"), pg.inner_text("#ptx-bal"))

        # 结账：结卖出的那 5 根
        pg.click('[data-ptx-settle="合伙人甲"]'); pg.wait_for_selector("#f-po-0")
        check("结账里：「代销卖出 · 还没付」代销卖出 5 根 · $140", "代销卖出 · 还没付" in pg.inner_text("#sheet") and "代销卖出 5 根 · $140" in pg.inner_text("#sheet"))
        if pg.locator("#f-paychips").count() and pg.is_visible("#f-paychips"): pg.click('#f-paychips label:has(input[value="现金"])')
        save(pg)
        P = po(pg); cs = P.get("consign_settles") or []
        check("结账记了一笔：$140、香蕉 2 根、葡萄冰 3 根；代销单没变成「已付」", len(cs) == 1 and cs[0]["amt"] == 140 and cs[0]["qty"] == {"XF-01": 2, "XF-02": 3} and not P.get("settlement_id") and P.get("paid") is False, (cs, P.get("settlement_id")))
        go(pg, "purchases"); t = card(pg).inner_text()
        check("卡片：卖出的都结清了 · 已结 $140", "卖出的都结清了 · 已结 $140" in t, t[:300])
        go(pg, "partner"); check("合伙人页：两清", "你欠 合伙人甲" not in pg.inner_text("#ptx-bal"), pg.inner_text("#ptx-bal"))

        # 之后再卖 4 根葡萄冰 → 再欠 $112
        pg.evaluate("""() => { window.__remoteWrite && 0; }""")
        go(pg, "finance"); pg.click("#fin-sale"); pg.wait_for_selector("#f-skuq-0"); pg.fill("#f-skuq-0", "葡萄冰"); pg.press("#f-skuq-0", "Enter"); pg.fill("#f-qty-0", "4"); pg.fill("#f-price-0", "60")
        pg.click('#f-paychips label:has(input[value="现金"])'); save(pg)
        go(pg, "purchases"); t = card(pg).inner_text()
        check("再卖 4 根葡萄冰：还欠 $112（4 根），已结 $140", "还欠 $112（卖出还没结的 4 根）" in t and "已结 $140" in t, t[:300])

        # 退回给他：香蕉退 3 根
        card(pg).locator("[data-cs-ret]").click(); pg.wait_for_selector(".cs-rq")
        ks = pg.evaluate("[...document.querySelectorAll('.cs-rq')].map((i) => [i.dataset.k, i.dataset.max])")
        check("退回：只列在你这的（香蕉 8、葡萄冰 3）", ks == [["XF-01", "8"], ["XF-02", "3"]], ks)
        pg.fill('.cs-rq[data-k="XF-01"]', "9"); save(pg)
        check("退的比在你这的多：不让存", pg.is_visible("#sheet") and "只有 8 根" in pg.inner_text("#sheet-err"))
        pg.fill('.cs-rq[data-k="XF-01"]', "3"); save(pg)
        rm = [m for m in S(pg, "moves") if m.get("ret_po") == "p-c"]
        check("记了退回：adjust −3、ret_po", len(rm) == 1 and rm[0]["type"] == "adjust" and rm[0]["qty"] == -3 and rm[0]["sku"] == "XF-01", rm)
        t = card(pg).inner_text()
        check("卡片：退回 3 根 · 在你这 8 根；欠的钱不变（$112）；香蕉「卖了 2 · 退 3 · 剩 5」", "退回 3 根 · 在你这 8 根" in t and "还欠 $112" in t and "卖了 2 · 退 3 · 剩 5" in t, t[:400])
        check("库存香蕉 = 5 + 10 − 7 − 3 = 5", pg.evaluate("window.__GM.S.moves.filter((m) => m.sku === 'XF-01').reduce((a, m) => a + (m.type === 'out' ? -m.qty : m.qty), 0)") == 5)
        go(pg, "finance"); fin = pg.inner_text("#fin-view") if pg.locator("#fin-view").count() else ""
        check("退回不算损耗（财务里没有「损耗」）", "损耗" not in fin or "损耗 $0" in fin)
        go(pg, "purchases"); card(pg).locator("[data-void-ret]").click(); card(pg).locator("[data-void-ret]").click(); pg.wait_for_timeout(500)
        check("撤销退回：货算回来（在你这 11 根）", not [m for m in S(pg, "moves") if m.get("ret_po") == "p-c"] and "在你这 11 根" in card(pg).inner_text())

        # 撤销结账：那 5 根的钱又欠回来（5 + 4 = 9 根 $252）
        sid = po(pg)["consign_settles"][0]["sid"]
        check("结账记录里写「代销卖出」", pg.evaluate("(sid) => !!(window.__GM.S.settles.find((x) => x.id === sid) || {}).consign_ids", sid))
        pg.evaluate("(sid) => { const b = [...document.querySelectorAll('[data-unsettle]')].find((x) => x.dataset.unsettle === sid); b.click(); b.click(); }", sid); pg.wait_for_timeout(600)
        check("撤销结账：代销单上的结账记号拿掉，又欠 9 根 $252", not po(pg).get("consign_settles") and "还欠 $252（卖出还没结的 9 根）" in card(pg).inner_text(), (po(pg).get("consign_settles"), card(pg).inner_text()[:200]))

        # 新建一张代销单（表单）
        pg.click("text=新建订货"); pg.wait_for_selector("#f-paidseg")
        pg.click('#f-paidseg [data-paid="c"]')
        check("选「代销（卖了再付）」出说明；底下写「货值」；供货人框提示要写", pg.is_visible("#f-conshint") and pg.inner_text("#f-totlbl") == "货值" and pg.get_attribute("#f-supplier", "placeholder") == "代销要写是谁的货")
        pg.click('#f-ptiles [data-padd="XF-01"]'); pg.fill('#f-lines input[id^="f-qty-"]', "10"); save(pg)
        check("没写供货人：不让存", pg.is_visible("#sheet") and "代销要写是谁的货" in pg.inner_text("#sheet-err"))
        pg.fill("#f-supplier", "合伙人乙"); save(pg)
        np_ = next(x for x in S(pg, "purchases") if x["id"] not in ("p-c", "p-n"))
        check("存了：consign、供货人合伙人乙、没付；没有进货支出", np_.get("consign") is True and np_.get("supplier") == "合伙人乙" and np_.get("paid") is False and not [x for x in S(pg, "expenses") if x.get("po_id") == np_["id"]], np_)
        check("还没到货：合伙人乙不欠钱", "合伙人乙" not in (go(pg, "partner") or pg.inner_text("#ptx-bal")))
        go(pg, "purchases"); card(pg, "p-n").locator('[data-edit-po="p-n"]').click(); pg.wait_for_selector("#f-ucost-0")
        pg.fill("#f-ucost-0", "25"); save(pg)
        t = card(pg, "p-n").inner_text()
        check("填上单价 $25：还欠 $50（2 根）", "还欠 $50（卖出还没结的 2 根）" in t and "没填单价" not in t, t[:300])
        ctx.close()
    br.close()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
