"""对账单「价格」（2026-11-24 Bowen：核对那边加一栏，每个系列「他给我 / 我给他」统一按什么价，自己改）
- 对账单多一个「价格」：每个系列 他给我 $ / 我给他 $，空着 = 按你的进货价（框里浅色）；存在 meta/pprice（按合伙人）
- 勾「没结账的也按新价重算」：没结的往来单价、随单拿的流水成本、那单的拿货支出都按新价；预览「现在 X → 改完 Y」（跟对账单同一个算法，含互抵）
- 以后记的：他拿我的（我给他价）、我拿他的（他给我价）、换货两边、随单拿的、预定还没拿的，默认都按这个人的价；换了合伙人，没手动改过的单价跟着换
- 没填价的系列：往来按进货价，随单拿照旧按系列价格
用编出来的小数据，旧结构 / 新结构各一遍，GitHub 上也跑。运行：python3 tests/test_pprice.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
D = lambda n: (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=n)).isoformat()
IT = lambda sku, ser, v, n, c: {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": 60, "cost_aud": c, "status": "在售"}
A, B = "合伙人甲", "合伙人乙"
V1 = {"items": {"XF-01": IT("XF-01", "Bar Pro", "Banana Buzz", "香蕉", 36), "XF-02": IT("XF-02", "Bar Pro", "Grape Ice", "葡萄冰", 36), "XF-03": IT("XF-03", "Ali", "Pink Lemon", "粉柠檬", 34)},
      "movements": {
          "in-01": {"type": "in", "sku": "XF-01", "name": "香蕉", "qty": 20, "cost": 600, "date": D(20), "at": D(20) + "T01:00:00Z", "note": "进货"},     # Bar Pro 进货价 30
          "in-03": {"type": "in", "sku": "XF-03", "name": "粉柠檬", "qty": 20, "cost": 640, "date": D(20), "at": D(20) + "T01:00:00Z", "note": "进货"},   # Ali 进货价 32
          "t-a-out-XF-01": {"type": "adjust", "sku": "XF-01", "name": "香蕉", "qty": -2, "date": D(5), "at": D(5) + "T02:00:00Z", "transfer_id": "t-a", "note": "合伙人往来：给 " + A},
          "t-b-in-XF-03": {"type": "in", "sku": "XF-03", "name": "粉柠檬", "qty": 1, "cost": 34, "date": D(4), "at": D(4) + "T02:00:00Z", "transfer_id": "t-b", "note": "合伙人往来：" + B + " 给的"},
          "o-1-XF-02": {"type": "out", "sku": "XF-02", "name": "葡萄冰", "qty": 1, "date": D(3), "at": D(3) + "T03:00:00Z", "order_id": "o-1"},
          "o-1-pick-XF-02": {"type": "in", "sku": "XF-02", "name": "葡萄冰", "qty": 1, "cost": 36, "date": D(3), "at": D(3) + "T03:00:00Z", "order_id": "o-1", "batch_id": "o-1-pick", "expense_id": "o-1-pick-cost", "note": "按单向合伙人拿货"}},
      "transfers": {"t-a": {"date": D(5), "at": D(5) + "T02:00:00Z", "partner": A, "out": [{"sku": "XF-01", "name": "香蕉", "qty": 2, "unit": 30}], "in": [], "note": ""},
                    "t-b": {"date": D(4), "at": D(4) + "T02:00:00Z", "partner": B, "out": [], "in": [{"sku": "XF-03", "name": "粉柠檬", "qty": 1, "unit": 34}], "note": ""}},
      "orders": {"o-1": {"status": "paid", "date": D(3), "at": D(3) + "T03:00:00Z", "customer": "客人", "payment": "现金", "delivery_fee": 0, "note": "", "pick_from": A,
                         "lines": [{"sku": "XF-02", "name": "葡萄冰", "qty": 1, "unit_price": 60}]}},
      "expenses": {"o-1-pick-cost": {"date": D(3), "at": D(3) + "T03:00:00Z", "amount": 36, "category": "进货成本", "note": "按单拿货 葡萄冰 ×1", "batch_id": "o-1-pick"}},
      "purchases": {}, "settlements": {}, "customers": {}, "followups": {}}
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "v1.json").write_text(json.dumps(V1, ensure_ascii=False), encoding="utf8")
subprocess.run(["node", str(ROOT / "v2_seed.js"), str(tmp / "v1.json"), str(tmp / "v2.json")], check=True, capture_output=True)
V2 = json.loads((tmp / "v2.json").read_text(encoding="utf8")); V2["meta"] = {"schema": {"version": 2}, "backfill": {"done": True}}
EXPOSE = "\nwindow.__GM = { S, ledgerNet, pendingPicks };\n})();"
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
    results.append(bool(ok)); print(("✅ " if ok else "❌ ") + name + (("  " + str(extra)) if extra and not ok else ""))
go = lambda pg, h: (pg.evaluate(f"location.hash = '#{h}'"), pg.wait_for_timeout(350))
S = lambda pg, col: pg.evaluate(f"window.__GM.S.{col}")
net = lambda pg, w: pg.evaluate(f"window.__GM.ledgerNet('{w}')")
def find(pg, col, i): return next((x for x in S(pg, col) if x["id"] == i), {})
def save(pg):
    pg.wait_for_timeout(200); pg.click("#sheet-save")
    try: pg.wait_for_selector("#sheet", state="hidden", timeout=3000)
    except Exception: pass
    pg.wait_for_timeout(600)
def ledger(pg, w):
    go(pg, "partner"); pg.click(f'#ptx-bal [data-lg-open="{w}"]'); pg.wait_for_selector('#sheet [data-lg="pprice"]')
def price_form(pg, w):
    ledger(pg, w); pg.click('#sheet [data-lg="pprice"]'); pg.wait_for_selector("#sheet [data-pp]")
def pp(pg, d, sr): return f'#sheet [data-pp="{d}"][data-sr="{sr}"]'
def cart(pg, mode, skus):
    go(pg, "partner"); pg.evaluate("document.getElementById('ptx-rec').open = true"); pg.click(f'#ptx-dir [data-pd="{mode}"]'); pg.wait_for_timeout(150)
    for k in skus: pg.click(f'#ptx-tiles [data-padd="{k}"]'); pg.wait_for_timeout(80)
def clear_cart(pg):
    if pg.is_visible("#sheet"): pg.click("#sheet-close"); pg.wait_for_timeout(200)
    if pg.is_visible("#cb-clear"): pg.click("#cb-clear"); pg.click("#cb-clear"); pg.wait_for_timeout(200)

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

        # 1. 对账单里的「价格」
        check("开始：合伙人甲欠你 $30（他拿 2 根香蕉 $60，随单拿你 1 根葡萄冰 $36，同系列抵 1 根）", net(pg, A) == -30, net(pg, A))
        price_form(pg, A)
        check("价格：每个系列一行 他给我 / 我给他，空着，框里浅色写进货价（Bar Pro 30、Ali 32）", pg.get_attribute(pp(pg, "in", "Bar Pro"), "placeholder") == "30" and pg.get_attribute(pp(pg, "out", "Ali"), "placeholder") == "32" and pg.input_value(pp(pg, "in", "Bar Pro")) == "")
        check("有没结账的：「没结账的也按新价重算（1 笔往来、1 笔随单拿的）」默认勾上", pg.is_checked("#f-pp-re") and "1 笔往来、1 笔随单拿的" in pg.inner_text("#sheet"))
        pg.fill(pp(pg, "in", "Bar Pro"), "33"); pg.fill(pp(pg, "out", "Bar Pro"), "35"); pg.wait_for_timeout(150)
        sm = pg.inner_text("#f-xsum")
        check("预览：现在合伙人甲 欠你 $30 → 改完 合伙人甲 欠你 $35（Bar Pro 他给我 33、我给他 35，抵掉 1 根）", sm == "现在合伙人甲 欠你 $30 → 改完 合伙人甲 欠你 $35", sm)
        save(pg)
        lst = S(pg, "pprice")
        check("存了：meta/pprice 合伙人甲 他给我 Bar Pro 33、我给他 Bar Pro 35（Ali 空着不存）", lst == [{"who": A, "in": {"Bar Pro": 33}, "out": {"Bar Pro": 35}}], lst)
        ta, pk, ex = find(pg, "transfers", "t-a"), next((m for m in S(pg, "moves") if m.get("batch_id") == "o-1-pick"), {}), next((x for x in S(pg, "expenses") if x.get("batch_id") == "o-1-pick"), {})
        check("没结账的按新价：往来香蕉每根 35、随单拿的葡萄冰成本 33、那单拿货支出 33", ta["out"][0]["unit"] == 35 and pk.get("cost") == 33 and ex.get("amount") == 33, (ta.get("out"), pk.get("cost"), ex.get("amount")))
        check("账：合伙人甲欠你 $35；合伙人乙不受影响（你欠他 $34）", net(pg, A) == -35 and net(pg, B) == 34, (net(pg, A), net(pg, B)))
        check("存完回到对账单", pg.is_visible('#sheet [data-lg="pprice"]'))
        pg.click("#sheet-close"); pg.wait_for_timeout(200)

        # 2. 以后记的默认用这个人的价
        cart(pg, "give", ["XF-02"]); pg.click("#cb-go"); pg.wait_for_selector("#f-unit-0")
        check("我跟合伙人拿货（默认合伙人甲）：葡萄冰默认 $33（他给我价）", pg.input_value("#f-xwho") == A and pg.input_value("#f-unit-0") == "33", (pg.input_value("#f-xwho"), pg.input_value("#f-unit-0")))
        check("底下写：按对账单里跟 合伙人甲 的价格：Bar Pro 他给我 $33", "按对账单里跟 合伙人甲 的价格：Bar Pro 他给我 $33" in pg.inner_text("#f-trhint"), pg.inner_text("#f-trhint"))
        pg.click(f'#sheet [data-pname="{B}"]'); pg.wait_for_timeout(200)
        check("换成合伙人乙（没设价）：变成进货价 $30，提示跟着换", pg.input_value("#f-unit-0") == "30" and "单价默认按你的进货价" in pg.inner_text("#f-trhint"), (pg.input_value("#f-unit-0"), pg.inner_text("#f-trhint")))
        pg.fill("#f-unit-0", "31"); pg.click(f'#sheet [data-pname="{A}"]'); pg.wait_for_timeout(200)
        check("自己改过的（31）换回合伙人甲也不动", pg.input_value("#f-unit-0") == "31", pg.input_value("#f-unit-0"))
        clear_cart(pg)
        cart(pg, "take", ["XF-01", "XF-03"]); pg.click("#cb-go"); pg.wait_for_selector("#f-unit-1")
        check("合伙人拿我的货：香蕉默认 $35（我给他价）、粉柠檬 $32（Ali 没设 → 进货价）", [pg.input_value("#f-unit-0"), pg.input_value("#f-unit-1")] == ["35", "32"], [pg.input_value("#f-unit-0"), pg.input_value("#f-unit-1")])
        clear_cart(pg)
        cart(pg, "swap", ["XF-01"]); pg.click('#ptx-side [data-ps="i"]'); pg.wait_for_timeout(150); pg.click('#ptx-tiles [data-padd="XF-02"]'); pg.wait_for_timeout(100)
        pg.click("#cb-go"); pg.wait_for_selector("#f-unit-i0")
        check("换货：我给的香蕉 $35、他给的葡萄冰 $33", [pg.input_value("#f-unit-o0"), pg.input_value("#f-unit-i0")] == ["35", "33"], [pg.input_value("#f-unit-o0"), pg.input_value("#f-unit-i0")])
        clear_cart(pg)

        # 3. 随单拿、预定还没拿的
        def sale(resv, who):
            go(pg, "finance"); pg.click("#fin-sale"); pg.wait_for_selector("#f-skuq-0")
            pg.fill("#f-skuq-0", "葡萄冰"); pg.press("#f-skuq-0", "Enter"); pg.fill("#f-qty-0", "1")
            if resv: pg.check("#f-resv"); pg.fill("#f-cust", "预定客人")
            else: pg.click('#f-paychips label:has(input[value="现金"])')
            pg.fill("#f-pfrom", who); pg.dispatch_event("#f-pfrom", "input"); save(pg)
        before = {m["id"] for m in S(pg, "moves")}
        sale(False, A)
        new_pick = [m for m in S(pg, "moves") if m["id"] not in before and m.get("type") == "in" and (m.get("batch_id") or "").endswith("-pick")]
        check("记卖出、没货找合伙人甲拿：拿货成本 $33（他给我价，不是系列价格的 36）", len(new_pick) == 1 and new_pick[0].get("cost") == 33, new_pick)
        sale(True, A); sale(True, B)
        pa = pg.evaluate(f"window.__GM.pendingPicks('{A}').map((g) => g.cost)"); pb = pg.evaluate(f"window.__GM.pendingPicks('{B}').map((g) => g.cost)")
        check("预定还没拿：找合伙人甲的估 $33，找合伙人乙的（没设价）照旧按系列价格 $36", pa == [33] and pb == [36], (pa, pb))

        # 4. 不勾重算：只管以后；清空 = 回到进货价
        price_form(pg, A)
        check("再打开：填过的价都在", pg.input_value(pp(pg, "in", "Bar Pro")) == "33" and pg.input_value(pp(pg, "out", "Bar Pro")) == "35")
        pg.fill(pp(pg, "out", "Bar Pro"), "40"); pg.uncheck("#f-pp-re"); pg.wait_for_timeout(150)
        check("不勾重算：预览写「只管以后记的」", "只管以后记的" in pg.inner_text("#f-xsum"), pg.inner_text("#f-xsum"))
        save(pg)
        check("存了 40，没结账的那笔往来照旧 35", S(pg, "pprice")[0]["out"]["Bar Pro"] == 40 and find(pg, "transfers", "t-a")["out"][0]["unit"] == 35)
        pg.click("#sheet-close"); pg.wait_for_timeout(200)
        price_form(pg, A)
        for d in ("in", "out"): pg.fill(pp(pg, d, "Bar Pro"), "")
        pg.uncheck("#f-pp-re"); save(pg)
        check("清空：合伙人甲的价格拿掉", S(pg, "pprice") == [], S(pg, "pprice"))
        pg.click("#sheet-close"); pg.wait_for_timeout(200)
        cart(pg, "take", ["XF-01"]); pg.click("#cb-go"); pg.wait_for_selector("#f-unit-0")
        check("清空以后：合伙人拿我的香蕉回到进货价 $30", pg.input_value("#f-unit-0") == "30", pg.input_value("#f-unit-0"))
        clear_cart(pg)
        ctx.close()
    br.close()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
