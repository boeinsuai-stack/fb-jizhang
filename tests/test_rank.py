"""口味排行 + 客户名字候选（2026-11-16）
一、库存页「口味排行」：一段时间里每个口味被几单买过、一共几根；默认按单数排，可改按根数；7/14/30 天；按系列；
    只算已卖出的（预定不算）；一单占了一半以上根数的标出来；右边写现在还剩几根
二、下单表的客户名字：打几个字，输入框上面列出以前的客人（名字里包含就算，不分大小写），点一下填上并显示「回头客」
用编出来的小数据，旧结构 / 新结构各一遍，GitHub 上也跑。运行：python3 tests/test_rank.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
T0 = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date()
day = lambda n: (T0 - datetime.timedelta(days=n)).isoformat()
ITEMS = [("XF-01", "Ali", "Apple", 5), ("XF-02", "Ali", "Berry", 11), ("XF-03", "Ali", "Cherry", 10), ("XF-04", "Bar Pro", "Date", 4)]  # sku, 系列, 名字, 进货根数
ORDERS = [  # id, 几天前, 客户, 行, 预定?
    ("o1", 1, "Anna Lee", [("XF-01", 1), ("XF-02", 1)], False),
    ("o2", 2, "Ben", [("XF-01", 1)], False),
    ("o3", 3, "Rob", [("XF-02", 10)], False),          # 一个大单：按根数排会把 Berry 顶到第一
    ("o4", 10, "anna lee", [("XF-03", 2), ("XF-04", 1)], False),
    ("o5", 20, "Valentine", [("XF-04", 3)], False),    # 14 天以外
    ("o6", 0, "Zed", [("XF-03", 5)], True),            # 预定：不算卖出，但占着库存
    ("o7", 4, "Cara", [("XF-01", 1)], False),
]
V1 = {"items": {}, "movements": {}, "orders": {}, "expenses": {}, "purchases": {}, "transfers": {}, "settlements": {}, "customers": {}, "followups": {}}
NAME = {}
for sku, sr, en, q in ITEMS:
    NAME[sku] = en
    V1["items"][sku] = {"sku": sku, "series": sr, "variant": en, "name": en, "price_aud": 60, "cost_aud": 30, "status": "在售"}
    V1["movements"]["in-" + sku] = {"type": "in", "sku": sku, "name": en, "qty": q, "date": day(25), "at": day(25) + "T01:00:00Z", "note": "进货"}
for oid, ago, who, lines, resv in ORDERS:
    V1["orders"][oid] = {"status": "reserved" if resv else "paid", "date": day(ago), "at": day(ago) + "T02:00:00Z", "customer": who, "payment": "" if resv else "现金",
                         "lines": [{"sku": s, "name": NAME[s], "qty": q, "unit_price": 60} for s, q in lines], "delivery_fee": 0, "note": ""}
    if not resv:
        for s, q in lines: V1["movements"][oid + "-" + s] = {"type": "out", "sku": s, "name": NAME[s], "qty": q, "date": day(ago), "at": day(ago) + "T02:00:00Z", "order_id": oid, "note": "卖出"}
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "v1.json").write_text(json.dumps(V1, ensure_ascii=False), encoding="utf8")
subprocess.run(["node", str(ROOT / "v2_seed.js"), str(tmp / "v1.json"), str(tmp / "v2.json")], check=True, capture_output=True)
V2 = json.loads((tmp / "v2.json").read_text(encoding="utf8")); V2["meta"] = {"schema": {"version": 2}, "backfill": {"done": True}}

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(type("H", (http.server.SimpleHTTPRequestHandler,), {"log_message": lambda *a: None}), directory=str(PUB)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
results = []
def check(name, ok, extra=""):
    results.append(ok); print(("✅ " if ok else "❌ ") + name + (("  " + str(extra)) if extra and not ok else ""))

ROWS = """() => [...document.querySelectorAll('#rk-list .rk-row')].map((r) => r.innerText.replace(/\\s+/g, ' ').trim())"""
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    for mode in ("旧结构", "新结构"):
        seed = V2 if mode == "新结构" else dict(V1, meta={"backfill": {"done": True}})
        ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
        ctx.add_init_script("window.__SEED = " + json.dumps(seed, ensure_ascii=False) + ";")
        pg = ctx.new_page(); pg.on("pageerror", lambda e: (print("   页面报错：", e), results.append(False)))
        pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
        pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
        pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html"); pg.wait_for_selector("#qo-tiles .tile", timeout=15000); pg.wait_for_timeout(600)
        print("== " + mode)
        pg.evaluate("document.querySelector('#rk-sec summary').click()"); pg.wait_for_timeout(200)
        rows = pg.evaluate(ROWS); basis = pg.inner_text("#rk-basis").replace("\n", " ")
        check("默认近 14 天、全部系列、按单数排：5 单 · 17 根 · 4 款", "5 单 · 17 根 · 4 款" in basis and "按单数排" in basis, basis)
        check("按单数：Apple 3 单 3 根 → Berry 2 单 11 根 → Cherry 1 单 2 根 → Date 1 单 1 根",
              len(rows) == 4 and rows[0].startswith("1 Apple") and "3 单 · 3 根" in rows[0] and rows[1].startswith("2 Berry") and "2 单 · 11 根" in rows[1]
              and rows[2].startswith("3 Cherry") and "1 单 · 2 根" in rows[2] and rows[3].startswith("4 Date") and "1 单 · 1 根" in rows[3], rows)
        check("大单标出来：Berry「其中一单 10 根（Rob）」，别的不标", "其中一单 10 根（Rob）" in rows[1] and not any("其中一单" in r for r in rows[:1] + rows[2:]), rows)
        check("右边写现在的库存：Apple 剩 2、Berry 没货、Cherry 剩 3（扣掉预定的 5 根）、Date 没货", "剩 2" in rows[0] and "没货" in rows[1] and "剩 3" in rows[2] and "没货" in rows[3], rows)
        check("预定的那单（Zed）不算卖出", not any("Zed" in r for r in rows) and "1 单 · 2 根" in rows[2])
        pg.click("#rk-by"); pg.wait_for_timeout(150); rows = pg.evaluate(ROWS)
        check("改按根数：Berry 排第一，Apple 第二", rows[0].startswith("1 Berry") and rows[1].startswith("2 Apple") and "按根数排" in pg.inner_text("#rk-basis"), rows)
        pg.click("#rk-by"); pg.click('[data-rk-days="30"]'); pg.wait_for_timeout(150); rows = pg.evaluate(ROWS)
        check("30 天：把 20 天前那单也算上，Date 变成 2 单 4 根、排第三", len(rows) == 4 and rows[2].startswith("3 Date") and "2 单 · 4 根" in rows[2] and "6 单 · 20 根" in pg.inner_text("#rk-basis"), rows)
        pg.click('[data-rk-days="14"]'); pg.click('[data-rk-ser="Bar Pro"]'); pg.wait_for_timeout(150); rows = pg.evaluate(ROWS)
        check("只看 Bar Pro：1 单 · 1 根 · 1 款，行里不再写系列", len(rows) == 1 and rows[0].startswith("1 Date") and "Bar Pro" not in rows[0] and "1 单 · 1 根 · 1 款" in pg.inner_text("#rk-basis"), rows)
        pg.click('[data-rk-days="7"]'); pg.wait_for_timeout(150)
        check("7 天里 Bar Pro 没卖：写明这段时间没有卖出", "没有卖出" in pg.inner_text("#rk-list"))
        pg.reload(); pg.wait_for_selector("#qo-tiles .tile", timeout=15000); pg.wait_for_timeout(500)
        check("选的天数、系列下次打开还在", pg.get_attribute('[data-rk-days="7"]', "aria-pressed") == "true" and pg.get_attribute('[data-rk-ser="Bar Pro"]', "aria-pressed") == "true")

        # 二、客户名字候选
        pg.evaluate("location.hash = '#finance'"); pg.wait_for_timeout(300); pg.click("#fin-sale"); pg.wait_for_selector("#f-cust", timeout=5000)
        sug = lambda: pg.evaluate("(() => { const b = document.getElementById('f-cust-sug'); return !b || b.hidden ? [] : [...b.querySelectorAll('.chip')].map((c) => c.innerText.replace(/\\s+/g, ' ').trim()); })()")
        check("没打字：不列候选", sug() == [])
        pg.locator("#f-cust").press_sequentially("an"); pg.wait_for_timeout(150)
        check("打「an」：列出 Anna Lee（大小写不同的两单算一个人，2 次）", len(sug()) == 1 and sug()[0].startswith("Anna Lee") and "2 次" in sug()[0], sug())
        pg.fill("#f-cust", ""); pg.locator("#f-cust").press_sequentially("LEN"); pg.wait_for_timeout(150)
        check("打「LEN」（名字中间的字、大写）：找到 Valentine", len(sug()) == 1 and sug()[0].startswith("Valentine") and "1 次" in sug()[0], sug())
        check("候选在输入框上面（iPhone 键盘不会挡住）", pg.evaluate("document.getElementById('f-cust-sug').getBoundingClientRect().bottom <= document.getElementById('f-cust').getBoundingClientRect().top + 1"))
        pg.click("#f-cust-sug .chip"); pg.wait_for_timeout(200)
        check("点一下：填上名字、候选收起、显示「回头客」", pg.input_value("#f-cust") == "Valentine" and sug() == [] and "回头客" in pg.inner_text("#f-cust-hint"), pg.input_value("#f-cust"))
        pg.fill("#f-cust", ""); pg.locator("#f-cust").press_sequentially("ze"); pg.wait_for_timeout(150)
        check("只有预定、还没买过的客人也能找到（Zed · 有预定）", len(sug()) == 1 and "Zed" in sug()[0] and "有预定" in sug()[0], sug())
        pg.fill("#f-cust", ""); pg.locator("#f-cust").press_sequentially("Ben"); pg.wait_for_timeout(150)
        check("名字已经打全（Ben）：不再列他自己", sug() == [])
        pg.fill("#f-cust", ""); pg.locator("#f-cust").press_sequentially("qq"); pg.wait_for_timeout(150)
        check("没有这个人：不列", sug() == [])
        check("不再用浏览器自带的下拉候选（iPhone 上常常不显示）", pg.get_attribute("#f-cust", "list") is None)
        ctx.close()
    br.close()

print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
