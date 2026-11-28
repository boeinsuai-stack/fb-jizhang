"""粘贴新口味（2026-11-28 Bowen：新增口味那里要一键粘贴新口味然后增加）
- 新增香型最上面「粘贴新口味 · 一次加好几个」→ 点开就读剪贴板，边打边认
- 一行一个；只写系列名的一行 = 下面都是这个系列（「Lost Mary:」= 新系列）；编号 / 根数 / 价钱 / 表情去掉；中文写成中文名
- 已经有的不加，停售的可以改回在售；只差一个词的标「很像」；售价 / 拿货价按系列最常用的先填
用编出来的小数据，旧结构 / 新结构各一遍，GitHub 上也跑。运行：python3 tests/test_paste_flavors.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
IT = lambda sku, ser, v, n, c: {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": 60, "cost_aud": c, "status": "在售"}
IT2 = lambda sku, ser, v, n, p, c, st="在售": {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": p, "cost_aud": c, "status": st, "created_at": "2026-10-01T00:00:00Z"}
V1 = {"items": {"XF-01": IT2("XF-01", "Bar Pro", "Banana Buzz", "香蕉", 70, 36), "XF-02": IT2("XF-02", "Bar Pro", "Grape Ice", "葡萄冰", 70, 36), "XF-03": IT2("XF-03", "Bar Pro", "Mango Magic", "芒果", 65, 36),
                "XF-07": IT2("XF-07", "Ali", "Watermelon Ice", "西瓜冰", 60, 34), "XF-08": IT2("XF-08", "Ali", "Double Apple", "双苹果", 60, 34), "XF-09": IT2("XF-09", "Ali", "Sour Apple", "酸苹果", 60, 34, "停售")},
      "movements": {}, "orders": {}, "expenses": {}, "purchases": {}, "transfers": {}, "settlements": {}, "customers": {}, "followups": {}}
PASTE = "Bar Pro\n1. Lemon Lime 柠檬 x10\n2. Cola Ice $70\n3. Banana buzz\n4. Grape Ice Mint 🍇\nAli\n- Sour Apple\n- Pink Lemonade 2盒\nLost Mary:\nTriple Mango"
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

def items(pg): return {x["sku"]: x for x in S(pg, "items")}
def res(pg): return pg.evaluate("document.getElementById('f-nfres').innerText")
def row(pg, name): return pg.locator("#f-nfres .nf-r").filter(has=pg.locator(f'b:text-is("{name}")')).first

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    for mode, data in (("旧结构", V1), ("新结构", V2)):
        print("==", mode)
        ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", permissions=["clipboard-read", "clipboard-write"])
        ctx.add_init_script("window.__SEED = " + json.dumps(data, ensure_ascii=False) + ";")
        pg = ctx.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
        for x in ("**/firebase-auth-compat.js", "**/firebase-firestore-compat.js"): pg.route(x, lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.goto(URL + "#inventory"); pg.wait_for_timeout(1800)

        # 1. 新增香型 → 最上面「粘贴新口味」；点开就读剪贴板
        pg.evaluate("(t) => navigator.clipboard.writeText(t)", PASTE)
        pg.click("#inv-new"); pg.wait_for_selector("#f-tonf")
        check("新增香型最上面有「粘贴新口味 · 一次加好几个」", pg.is_visible("#f-tonf") and "粘贴新口味" in pg.inner_text("#f-tonf"))
        pg.click("#f-tonf"); pg.wait_for_timeout(700)
        check("一点开就把剪贴板里的清单放进来", pg.input_value("#f-nf") == PASTE.replace("\\n", "\n"), pg.input_value("#f-nf")[:40])
        r = res(pg)
        check("认出：新口味 5 个 · 已经有的 2 个不加（Banana buzz、Sour Apple）", "新口味 5 个 · 已经有的 2 个不加" in r, r[:60])
        names = pg.evaluate("[...document.querySelectorAll('#f-nfres .nf-g:not(.nf-old) .nf-ck b')].map((b) => b.textContent)")
        check("按系列：Bar Pro Lemon Lime / Cola Ice / Grape Ice Mint，Ali Pink Lemonade，Lost Mary Triple Mango（编号、根数、价钱、表情都去掉）", names == ["Lemon Lime", "Cola Ice", "Grape Ice Mint", "Pink Lemonade", "Triple Mango"], names)
        check("中文写在中文名框里：Lemon Lime → 柠檬", row(pg, "Lemon Lime").locator(".nf-cn").input_value() == "柠檬")
        pr = pg.evaluate("[...document.querySelectorAll('[data-nfp]')].map((e) => e.dataset.nfp + ' ' + e.value + '/' + document.querySelector('[data-nfc=\"' + e.dataset.nfp + '\"]').value)")
        check("售价 / 拿货价按这个系列最常用的先填：Bar Pro 70/36、Ali 60/34，新系列 Lost Mary 空着", pr == ["Bar Pro 70/36", "Ali 60/34", "Lost Mary /"], pr)
        check("Lost Mary 标「新系列」", "新系列" in pg.inner_text("#f-nfres .nf-g:nth-child(4) .nf-gh"), pg.inner_text("#f-nfres .nf-g:nth-child(4) .nf-gh"))
        check("Grape Ice Mint 标「很像已有的 Grape Ice」，照样勾上", "很像已有的 Grape Ice" in row(pg, "Grape Ice Mint").inner_text() and row(pg, "Grape Ice Mint").locator("input[type=checkbox]").is_checked())
        old = pg.inner_text("#f-nfres .nf-old")
        check("已经有的列在最后：Banana Buzz；停售的 Sour Apple 可以「改回在售」（默认勾上）", "Bar Pro Banana Buzz · 香蕉" in old and "停售中 · 改回在售" in old and pg.locator("#f-nfres [data-nfon]").is_checked(), old)

        # 2. 改：不要 Cola Ice；Triple Mango 写中文名；Lost Mary 填价钱
        row(pg, "Cola Ice").locator("input[type=checkbox]").uncheck()
        row(pg, "Triple Mango").locator(".nf-cn").fill("三重芒果")
        pg.fill('[data-nfp="Lost Mary"]', "50"); pg.fill('[data-nfc="Lost Mary"]', "25")
        before = items(pg); save(pg)
        after = items(pg); added = {k: v for k, v in after.items() if k not in before}
        check("保存：加了 4 个（编号接着 XF-10 往下排），Cola Ice 没加", sorted(added) == ["XF-10", "XF-11", "XF-12", "XF-13"] and not any(v["variant"] == "Cola Ice" for v in added.values()), sorted((k, v["variant"]) for k, v in added.items()))
        by = {v["variant"]: v for v in added.values()}
        ok = (by.get("Lemon Lime", {}).get("series") == "Bar Pro" and by["Lemon Lime"]["name"] == "柠檬" and by["Lemon Lime"]["price_aud"] == 70 and by["Lemon Lime"]["cost_aud"] == 36 and by["Lemon Lime"]["status"] == "在售"
              and by.get("Pink Lemonade", {}).get("series") == "Ali" and by["Pink Lemonade"]["price_aud"] == 60 and by["Pink Lemonade"]["cost_aud"] == 34
              and by.get("Triple Mango", {}).get("series") == "Lost Mary" and by["Triple Mango"]["name"] == "三重芒果" and by["Triple Mango"]["price_aud"] == 50 and by["Triple Mango"]["cost_aud"] == 25)
        check("每个的系列 / 中文名 / 售价 / 拿货价 / 在售都对", ok, json.dumps(added, ensure_ascii=False)[:300])
        check("没写中文名的（Grape Ice Mint）中文名先用英文名", by.get("Grape Ice Mint", {}).get("name") == "Grape Ice Mint")
        check("停售的 Sour Apple 改回在售", after["XF-09"]["status"] == "在售")
        check("别的口味没动", all(after[k] == before[k] for k in before if k != "XF-09"))
        check("新口味的库存从 0 开始（没记流水）", not [m for m in S(pg, "moves") if m.get("sku") in added])

        # 3. 剪贴板是空的：自己粘贴（打字），边打边认；再粘一遍刚加的 → 都是已经有的
        pg.evaluate("navigator.clipboard.writeText('')"); pg.click("#inv-new"); pg.wait_for_selector("#f-tonf"); pg.click("#f-tonf"); pg.wait_for_timeout(500)
        check("剪贴板空：框是空的", pg.input_value("#f-nf") == "")
        pg.click("#sheet-save"); pg.wait_for_timeout(300)
        check("什么都没粘就保存：提示「先把新口味的清单粘贴进来」", "先把新口味的清单粘贴进来" in pg.inner_text("#sheet"))
        pg.fill("#f-nf", "Bar Pro\nLemon Lime\nlemon lime\nAli 葡萄冰"); pg.wait_for_timeout(400)
        r = res(pg)
        check("刚加的 Lemon Lime 认成已经有的；同一个写两次只算一次；「Ali 葡萄冰」= Ali 系列的新口味", "新口味 1 个 · 已经有的 1 个不加" in r and "葡萄冰" in pg.inner_text("#f-nfres .nf-g:not(.nf-old)"), r)
        pg.fill("#f-nf", "Peach Ice\nCola"); pg.wait_for_timeout(400)
        pg.select_option("#f-nfser", "Ali"); pg.wait_for_timeout(200)
        check("没写系列：算下面选的系列（换成 Ali 马上重认）", pg.evaluate("[...document.querySelectorAll('#f-nfres .nf-gh b')].map((b) => b.textContent)") == ["Ali"])
        # 4. 没写系列的算「＋ 新系列」（2026-11-28 Bowen：这里要能选新系列）
        pg.fill("#f-nf", "Peach Ice 蜜桃冰\nCola"); pg.select_option("#f-nfser", "__new"); pg.wait_for_timeout(300)
        check("选「＋ 新系列」：出来新系列名字框；没填名字先提示", pg.is_visible("#f-nfnew") and "先填上新系列的名字" in res(pg), res(pg))
        pg.fill("#f-nfnew", "elf bar"); pg.wait_for_timeout(400)
        check("填了 elf bar：两个口味都算 Elf Bar 系列，标「新系列」", pg.evaluate("[...document.querySelectorAll('#f-nfres .nf-gh')].map((b) => b.innerText.replace(/\\s+/g, ' '))") == ["Elf Bar 新系列"] and "新口味 2 个" in res(pg), res(pg))
        pg.fill('[data-nfp="Elf Bar"]', "80"); pg.fill('[data-nfc="Elf Bar"]', "40")
        before = items(pg); save(pg); after = items(pg); added = [v for k, v in after.items() if k not in before]
        check("保存：Elf Bar 系列加了 Peach Ice（蜜桃冰）、Cola，$80 / $40", sorted((v["series"], v["variant"], v["name"], v["price_aud"], v["cost_aud"]) for v in added) == [("Elf Bar", "Cola", "Cola", 80, 40), ("Elf Bar", "Peach Ice", "蜜桃冰", 80, 40)], added)
        pg.click("#inv-new"); pg.wait_for_selector("#f-tonf"); pg.click("#f-tonf"); pg.wait_for_timeout(400)
        check("再打开：下拉里有 Elf Bar 了", "Elf Bar" in pg.evaluate("[...document.querySelectorAll('#f-nfser option')].map((o) => o.value)"))
        pg.click("#sheet-close"); pg.wait_for_timeout(200)
        check("没有报错", not errs, errs)
        ctx.close()
    br.close()
srv.shutdown()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
