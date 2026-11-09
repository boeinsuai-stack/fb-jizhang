"""页面测试：没网时记账 + 编辑预定改口味。用假 Firebase（tests/mockfb.js），手机尺寸。
运行：python3 tests/test_offline_resv.py [public 目录]   需要 playwright 和 Chrome。"""
import functools, http.server, json, sys, threading, datetime, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ROOT.parent / "public").resolve()
SHOTS = ROOT / "shots"; SHOTS.mkdir(exist_ok=True)
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()

item = lambda sku, en, cn, price=30, cost=20: (sku, {"sku": sku, "series": "One", "variant": en, "name": cn, "price_aud": price, "cost_aud": cost, "status": "在售"})
SEED = {
    "items": dict([item("XF-01", "Apple", "苹果"), item("XF-02", "Mango", "芒果"), item("XF-03", "Grape", "葡萄")]),
    "movements": {
        "in-1": {"type": "in", "sku": "XF-01", "name": "苹果", "qty": 5, "date": TODAY, "at": TODAY + "T01:00:00Z"},
        "in-3": {"type": "in", "sku": "XF-03", "name": "葡萄", "qty": 3, "date": TODAY, "at": TODAY + "T01:00:00Z"},
        # r2 这单已经从合伙人那拿到 1 根芒果
        "r2-pick-XF-02": {"type": "in", "sku": "XF-02", "name": "芒果", "qty": 1, "date": TODAY, "at": TODAY + "T02:00:00Z", "order_id": "r2", "batch_id": "r2-pick", "cost": 20},
    },
    "orders": {
        "r1": {"status": "reserved", "date": TODAY, "at": TODAY + "T03:00:00Z", "customer": "Amy", "suburb": "Baldivis", "pick_from": "合伙人甲", "payment": None,
               "lines": [{"sku": "XF-02", "name": "芒果", "qty": 2, "unit_price": 30}], "delivery_fee": 5, "note": "周六送"},
        "r2": {"status": "reserved", "date": TODAY, "at": TODAY + "T04:00:00Z", "customer": "Ben", "pick_from": "合伙人乙",
               "lines": [{"sku": "XF-02", "name": "芒果", "qty": 1, "unit_price": 30}], "delivery_fee": 0, "note": ""},
        "p1": {"status": "paid", "date": TODAY, "at": TODAY + "T05:00:00Z", "customer": "Cat", "payment": "现金",
               "lines": [{"sku": "XF-01", "name": "苹果", "qty": 1, "unit_price": 30}], "delivery_fee": 0, "note": ""},
    },
    "expenses": {"r2-pick-cost": {"date": TODAY, "at": TODAY + "T02:00:00Z", "amount": 20, "category": "进货成本", "batch_id": "r2-pick"}},
}

results = []
def check(name, ok, extra=""):
    results.append(ok); print(("✅ " if ok else "❌ ") + name + (("  " + extra) if extra else ""))


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass


def serve():
    h = functools.partial(Quiet, directory=str(PUB))
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s.server_address[1]


def open_app(browser, port, offline=True, auth_never=False, last_user=None):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, timezone_id="Australia/Perth", service_workers="block", locale="zh-CN")
    init = f"window.__MOCK_OFFLINE={json.dumps(offline)};window.__AUTH_NEVER={json.dumps(auth_never)};window.__SEED={json.dumps(SEED, ensure_ascii=False)};"
    if last_user: init += f"localStorage.setItem('fb-last-user', {json.dumps(json.dumps(last_user))});"
    ctx.add_init_script(init)
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: print("   页面报错：", e))
    pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
    pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
    pg.goto(f"http://127.0.0.1:{port}/index.html")
    return ctx, pg


def pick(pg, k, text):
    pg.fill(f"#f-skuq-{k}", text); pg.press(f"#f-skuq-{k}", "Enter")


def open_resv(pg, oid):
    """客户页顶部的预定卡：先点开那一单，再点「编辑」"""
    pg.evaluate("location.hash = '#customers'"); pg.wait_for_timeout(300)
    btn = pg.locator(f'#cu-view details.rv:has([data-edit-order="{oid}"])').first
    btn.locator("summary").click()
    btn.locator(f'[data-edit-order="{oid}"]').click()


def save(pg, timeout=3000):
    pg.click("#sheet-save")
    try:
        pg.wait_for_selector("#sheet", state="hidden", timeout=timeout); return True
    except Exception:
        return False


with sync_playwright() as p:
    port = serve()
    browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])

    # 1. 没网：记一笔卖出
    ctx, pg = open_app(browser, port, offline=True)
    pg.wait_for_selector('[data-edit-order="r1"]', state="attached", timeout=8000)
    pg.evaluate("location.hash = '#finance'"); pg.wait_for_timeout(300)
    pg.click("#fin-sale")
    pick(pg, 0, "Apple"); pg.select_option("#f-pay", "现金")
    closed = save(pg)
    moves = pg.evaluate("__dump('movements')")
    out = [m for m in moves.values() if m.get("type") == "out" and m.get("sku") == "XF-01"]
    check("没网时点保存，弹窗 3 秒内关掉", closed)
    check("没网时卖出的出库也写进去了（不是半单）", len(out) == 1, f"出库 {len(out)} 条")
    pg.screenshot(path=str(SHOTS / "1-没网记账后.png"))

    # 2. 编辑预定：芒果×2 → 葡萄×2 + 苹果×1
    open_resv(pg, "r1")
    check("预定打开的是「编辑预定」", pg.inner_text("#sheet-title") == "编辑预定")
    check("原来的口味、客户、配送费、备注都带上了",
          "Mango" in pg.input_value("#f-skuq-0") and pg.input_value("#f-cust") == "Amy" and pg.input_value("#f-fee") == "5" and pg.input_value("#f-note") == "周六送")
    pick(pg, 0, "Grape")
    pg.click("#f-addline"); pick(pg, 1, "Apple")
    pg.wait_for_timeout(200)
    pg.screenshot(path=str(SHOTS / "2-编辑预定.png"), full_page=False)
    pg.locator("#sheet .sheet-card").screenshot(path=str(SHOTS / "2-编辑预定-整张表.png"))
    ok = save(pg)
    r1 = pg.evaluate("__dump('orders')")["r1"]
    lines = [(l["sku"], l["qty"], l.get("unit_price")) for l in r1["lines"]]
    check("保存后预定变成 葡萄×2 + 苹果×1", ok and lines == [("XF-03", 2, 30), ("XF-01", 1, 30)], str(lines))
    check("还是预定、客户和备注没丢", r1["status"] == "reserved" and r1["customer"] == "Amy" and r1["note"] == "周六送" and r1["suburb"] == "Baldivis")
    check("库存没被扣（预定不出库）", not any(m.get("order_id") == "r1" for m in pg.evaluate("__dump('movements')").values()))
    pg.wait_for_timeout(300)
    pg.screenshot(path=str(SHOTS / "3-客户页预定卡.png"))

    # 3. 已经拿到货的预定：芒果 → 葡萄，拿到的那根芒果留在库存
    open_resv(pg, "r2"); pick(pg, 0, "Grape"); ok = save(pg)
    mv = pg.evaluate("__dump('movements')")["r2-pick-XF-02"]
    check("换掉口味后，已经拿到的芒果留作库存", ok and mv.get("order_id") is None and "留作库存" in (mv.get("note") or ""))
    check("拿货支出还在（还欠合伙人）", "r2-pick-cost" in pg.evaluate("__dump('expenses')"))

    # 4. 已经卖出的单：还是原来的编辑表（数量锁住）
    pg.evaluate("location.hash = '#finance'"); pg.wait_for_timeout(300)
    pg.locator('[data-edit-order="p1"]:visible').first.click()
    check("已卖出的单仍是「编辑订单」、数量锁住", pg.inner_text("#sheet-title") == "编辑订单" and "数量改不了" in pg.inner_text("#sheet-form"))
    ctx.close()

    # 5. 登录确认一直等不到（信号很差）：1.5 秒后用上次登录的人打开
    ctx, pg = open_app(browser, port, offline=True, auth_never=True, last_user={"uid": "u-test", "email": "test@example.com", "displayName": "测试"})
    try:
        pg.wait_for_selector('[data-edit-order="r1"]', state="attached", timeout=4000); opened = True
    except Exception:
        opened = False
    check("信号差、登录确认不回来时，App 照样打开", opened)
    ctx.close()

    # 6. 有网时：照常保存
    ctx, pg = open_app(browser, port, offline=False)
    pg.wait_for_selector('[data-edit-order="r1"]', state="attached", timeout=8000)
    pg.evaluate("location.hash = '#finance'"); pg.wait_for_timeout(300)
    pg.click("#fin-sale"); pick(pg, 0, "Grape"); pg.select_option("#f-pay", "现金")
    check("有网时照常保存", save(pg))
    ctx.close()
    browser.close()

print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
