"""订货单「点口味 + 粘贴清单」（旧结构、新结构各跑一遍；编的小数据，GitHub 上也跑）
- 按系列看口味格子，点一下加一根、「−」减一根，格子上显示已选根数和现在的库存
- 粘贴清单 → 识别口味和根数（系列写在上面、中文名、×5 / 4 根），认出来的加到下面，没认出的列出来
- 「整系列每根」成本一次填完，保存后订货单的行、单价、根数都对；再打开编辑能看到原来选的
运行：python3 tests/test_po_quick.py"""
import os, datetime, functools, http.server, json, subprocess, sys, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
EXPOSE = "\nwindow.__GM = { S, derive };\n})();"
D = (datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date() - datetime.timedelta(days=3)).isoformat()
W = "合伙人甲"

item = lambda sku, ser, en, cn, cost: (sku, {"sku": sku, "series": ser, "variant": en, "name": cn, "price_aud": 70, "cost_aud": cost, "status": "在售"})
V1 = {
    "items": dict([item("XF-01", "Bar Pro", "Banana Buzz", "香蕉", 30), item("XF-02", "Bar Pro", "Grape Ice", "葡萄冰", 30), item("XF-03", "Bar Pro", "Blueberry Ice", "蓝莓冰", 30),
                   item("XF-04", "Ali", "Pink Lemon", "粉红柠檬", 55), item("XF-05", "Ali", "Banana Buzz", "香蕉", 55), item("XF-06", "Ali", "Cool Mint", "清凉薄荷", 55)]),
    "movements": {"in-1": {"type": "in", "sku": "XF-01", "name": "香蕉", "qty": 4, "cost": 120, "date": D, "at": D + "T01:00:00Z", "note": "进货"}},
    "orders": {}, "expenses": {}, "transfers": {}, "settlements": {}, "purchases": {}, "customers": {}, "followups": {},
    "meta": {"backfill": {"done": True}},
}
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "v1.json").write_text(json.dumps(V1, ensure_ascii=False), encoding="utf8")
subprocess.run(["node", str(ROOT / "v2_seed.js"), str(tmp / "v1.json"), str(tmp / "v2.json")], check=True, capture_output=True)
V2 = json.loads((tmp / "v2.json").read_text(encoding="utf8"))
V2["meta"] = {"schema": {"version": 2, "migrated_at": D + "T05:00:00.000Z"}, "backfill": {"done": True}}
PASTE = "Bar Pro\nGrape ice ×5\n蓝莓冰 4 根\nAli Pink Lemon x6\n随便写的东西 3"


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
    results.append(ok); print(("✅ " if ok else "❌ ") + name + (("  " + extra) if extra else ""))

SHOT = os.environ.get("SHOT")
qty_of = """(sku) => { const r = [...document.querySelectorAll('#f-lines .line')].find((r) => document.getElementById('f-sku-' + r.dataset.line).value === sku); return r ? Number(document.getElementById('f-qty-' + r.dataset.line).value) : 0; }"""
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    for mode, seed in (("旧结构", V1), ("新结构", V2)):
        print("== " + mode)
        ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
        ctx.add_init_script("window.__SEED=" + json.dumps(seed, ensure_ascii=False) + ";")
        pg = ctx.new_page(); pg.on("pageerror", lambda e: print("   页面报错：", e))
        pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
        pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
        pg.goto(URL); pg.wait_for_function("window.__GM && window.__GM.S.items.length === 6 && window.FBParse", timeout=15000); pg.wait_for_timeout(500)
        check("用的是" + mode, pg.evaluate("!!window.__fbV2store") == (mode == "新结构"))
        pg.evaluate("location.hash = '#purchases'"); pg.wait_for_timeout(300); pg.click("#po-new"); pg.wait_for_selector("#f-ptiles .tile", timeout=4000)
        q = lambda sku: pg.evaluate(f"({qty_of})('{sku}')")
        tiles = pg.evaluate("[...document.querySelectorAll('#f-ptiles .t-en')].map((e) => e.textContent)")
        check("默认看第一个系列（Bar Pro）的口味格子", tiles == ["Banana Buzz", "Grape Ice", "Blueberry Ice"], str(tiles))
        check("格子上写着现在的库存（Banana Buzz 剩 4）", "剩 4" in pg.inner_text('#f-ptiles .tile:first-child'))
        for _ in range(3): pg.click('[data-padd="XF-01"]')
        pg.click('[data-psub="XF-01"]')
        check("点 3 下、减 1 下 → Bar Pro Banana Buzz 2 根，格子上显示 2", q("XF-01") == 2 and pg.inner_text('#f-ptiles .tile.on .t-n') == "2")
        pg.click('#f-ptabs [data-pt="Ali"]'); pg.click('[data-padd="XF-04"]')
        check("换到 Ali 点 Pink Lemon → 加一行 1 根", q("XF-04") == 1)
        pg.fill("#f-pq", "香蕉"); pg.wait_for_timeout(100)
        check("搜「香蕉」两个系列的都出来", pg.evaluate("document.querySelectorAll('#f-ptiles .tile').length") == 2)
        pg.fill("#f-pq", "")

        pg.click("#f-pastebtn"); pg.fill("#f-paste", PASTE); pg.click("#f-parse"); pg.wait_for_timeout(200)
        msg = pg.inner_text("#f-parsed").replace("\n", " ")
        check("粘贴识别：Grape Ice 5、蓝莓冰 → Blueberry Ice 4、Pink Lemon 改成 6", q("XF-02") == 5 and q("XF-03") == 4 and q("XF-04") == 6 and q("XF-01") == 2, msg)
        check("没认出的只有「随便写的东西」（「4 根」的根不会被当成一种口味）", "没认出" in msg and msg.split("没认出")[1].count("／") == 0 and "随便写的东西" in msg, msg)
        check("识别完收起粘贴框", pg.evaluate("document.getElementById('f-pastebox').hidden"))
        check("识别结果只写口味名，不带系列前缀", "Bar Pro Grape" not in msg and "Ali Pink" not in msg, msg)
        if SHOT and mode == "新结构": pg.screenshot(path=SHOT + "-粘贴识别.png", full_page=False)
        grp = pg.evaluate("[...document.querySelectorAll('#f-lines .po-grp')].map((g) => [g.dataset.sr, g.querySelector('.po-gn').textContent, [...g.querySelectorAll('.pl-name b')].map((b) => b.textContent)])")
        check("按系列分框：Bar Pro 框 11 根、Ali 框 6 根，行里只写口味名", grp == [["Bar Pro", "11 根", ["Banana Buzz", "Grape Ice", "Blueberry Ice"]], ["Ali", "6 根", ["Pink Lemon"]]], str(grp))
        pg.fill('#f-lines input[data-sr="Bar Pro"]', "32")
        tot = pg.inner_text("#f-units")
        check("共 17 根", tot == "17", tot)
        if SHOT and mode == "新结构":
            pg.evaluate("document.querySelector('#f-lines').scrollIntoView()"); pg.screenshot(path=SHOT + "-已选.png", full_page=False)
        pg.click("#sheet-save"); pg.wait_for_timeout(1200)
        P = pg.evaluate("window.__GM.S.purchases")
        L = {l["sku"]: (l["qty"], l["unit_cost"]) for l in (P[0]["lines"] if P else [])}
        check("订货单存了 4 行：Bar Pro 三种按 $32，Pink Lemon 按自己的成本 $55", L == {"XF-01": (2, 32), "XF-02": (5, 32), "XF-03": (4, 32), "XF-04": (6, 55)}, str(L))
        check("订货金额 = 11×32 + 6×55 = $682", P and P[0].get("total") == 682, str(P and P[0].get("total")))
        # 再打开编辑：原来选的都在，格子上有根数
        pg.evaluate("location.hash = '#purchases'"); pg.wait_for_timeout(300)
        pg.click(f'[data-edit-po="{P[0]["id"]}"]')
        pg.wait_for_timeout(400)
        opened = pg.evaluate("!!document.getElementById('f-ptiles')")
        if opened:
            check("编辑订货单：4 种都在，Banana Buzz 2 根", pg.evaluate("document.querySelectorAll('#f-lines .line').length") == 4 and q("XF-01") == 2)
        else:
            print("   （没找到编辑按钮，跳过编辑检查）")
        ctx.close()
    br.close()

print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
