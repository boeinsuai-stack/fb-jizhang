"""库存页「复制口味」：带售价，价钱从低到高（2026-11-15）
- 一个系列都是一个价 → 写在标题右边「【Ali】$60」；同系列有不同价 → 每行后面写价钱
- 系列按最低价排；系列里按价钱、再按名字；没填售价的排最后、不写价
- 只列现在能卖的（库存减预定 > 0）
- 名字看不出是什么水果的：香型里填了 fruits 就写在名字后面的括号里；编辑香型能填、能清空
用编出来的小数据，GitHub 上也跑。运行：python3 tests/test_copy_flavours.py"""
import os, sys, json, datetime, functools, http.server, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
D = (datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date() - datetime.timedelta(days=2)).isoformat()
ITEMS = [  # sku, 系列, 英文名, 售价, 库存
    ("XF-01", "Bar Pro", "Grape Ice", 70, 3), ("XF-02", "Bar Pro", "Banana Buzz", 70, 1), ("XF-03", "Bar Pro", "Peach Ice", 70, 0),
    ("XF-04", "Ali", "Lemon Tea", 60, 2), ("XF-05", "Ali", "Cool Mint", 60, 5), ("XF-10", "Ali", "FTP", 60, 1),
    ("XF-06", "Star", "Mango", 110, 1), ("XF-07", "Star", "Apple", 95, 2), ("XF-08", "Star", "Kiwi", None, 1),
    ("XF-09", "One", "Cherry", 90, 2),
]
SEED = {"items": {}, "movements": {}, "expenses": {}, "orders": {}, "settlements": {}, "transfers": {}, "purchases": {}, "customers": {}, "followups": {}, "meta": {"backfill": {"done": True}}}
for sku, sr, en, price, q in ITEMS:
    SEED["items"][sku] = {"sku": sku, "series": sr, "variant": en, "name": en, "price_aud": price, "cost_aud": 30, "status": "在售"}
    if q: SEED["movements"]["b-0-" + sku] = {"type": "in", "sku": sku, "name": en, "qty": q, "cost": 30 * q, "date": D, "at": D + "T01:00:00Z", "note": "进货"}
# One 系列的 Cherry 2 根都被预定了 → 不能卖，不列
SEED["items"]["XF-10"]["fruits"] = "Blackberry Dragon Fruit"
SEED["orders"]["o-r"] = {"status": "reserved", "date": D, "at": D + "T02:00:00Z", "lines": [{"sku": "XF-09", "name": "Cherry", "qty": 2, "unit_price": 90}], "delivery_fee": 0, "note": "", "payment": ""}
WANT = "【Ali】$60\nCool Mint\nFTP (Blackberry Dragon Fruit)\nLemon Tea\n\n【Bar Pro】$70\nBanana Buzz\nGrape Ice\n\n【Star】\nApple $95\nMango $110\nKiwi"

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(type("H", (http.server.SimpleHTTPRequestHandler,), {"log_message": lambda *a: None}), directory=str(PUB)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
results = []
def check(name, ok, extra=""):
    results.append(ok); print(("✅ " if ok else "❌ ") + name + (("\n" + str(extra)) if extra and not ok else ""))

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    origin = f"http://127.0.0.1:{srv.server_address[1]}"
    ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
    ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=origin)
    ctx.add_init_script("window.__SEED = " + json.dumps(SEED, ensure_ascii=False) + ";")
    pg = ctx.new_page(); pg.on("pageerror", lambda e: (print("   页面报错：", e), results.append(False)))
    pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
    pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.goto(origin + "/index.html"); pg.wait_for_selector("#qo-tiles .tile", timeout=15000); pg.wait_for_timeout(600)
    pg.click("#inv-copy"); pg.wait_for_timeout(500)
    txt = pg.evaluate("navigator.clipboard.readText()")
    check("复制出来的文字：带售价、价钱从低到高、只列能卖的", txt == WANT, "实际：\n" + txt + "\n应该：\n" + WANT)
    check("提示复制了几个口味（8 个）", "8 个" in pg.inner_text("#toast"), pg.inner_text("#toast"))
    def edit(sku, val):
        pg.evaluate("location.hash = '#settings'"); pg.wait_for_timeout(200); pg.evaluate("location.hash = '#inventory'"); pg.wait_for_timeout(300)
        pg.evaluate(f"""() => document.querySelector('#items [data-act="edit"][data-sku="{sku}"]').click()"""); pg.wait_for_selector("#f-fruits", timeout=4000)
        pg.fill("#f-fruits", val); pg.click("#sheet-save"); pg.wait_for_selector("#sheet", state="hidden", timeout=4000); pg.wait_for_timeout(400)
    def copied():
        pg.evaluate("document.querySelectorAll('.toast').forEach((t) => t.hidden = true)"); pg.click("#inv-copy"); pg.wait_for_timeout(400); return pg.evaluate("navigator.clipboard.readText()")
    edit("XF-06", "（Mango Lime）")
    check("编辑香型填「里面是什么水果」（带括号也行）→ 复制出来写在括号里", "Mango (Mango Lime) $110" in copied(), copied())
    edit("XF-10", "")
    t2 = copied()
    check("清空 → 只写名字", "\nFTP\n" in t2 and "Dragon" not in t2, t2)
    br.close()

print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
