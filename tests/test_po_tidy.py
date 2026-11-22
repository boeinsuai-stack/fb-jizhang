"""订货整理（2026-11-23 Bowen）
- 粘贴清单认「几盒」：2盒 / 1 box / 两盒 → × 10 根；没写单位的跟着清单里写的（有写盒就按盒），识别结果里能切「盒 / 根」
- 订货单表单：按系列一行「每种几根 + 每根 $」（以前是全部一起「每种都订 N 根」）；系列框头写几盒
- 订货单卡片：标题「Bar Pro 2 盒 · Ali 5 根」；口味按系列从上往下排，每种「× N 盒」，有没有到齐写在右边；最后「合计」；到货记录一笔一行
用编出来的小数据，旧结构 / 新结构各一遍。运行：python3 tests/test_po_tidy.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
IT = lambda sku, ser, v, n, c: {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": 60, "cost_aud": c, "status": "在售"}
IT2 = lambda sku, ser, v, n, c: (sku, IT(sku, ser, v, n, c))
V1 = {"items": dict([IT2("XF-01", "Bar Pro", "Banana Buzz", "香蕉", 30), IT2("XF-02", "Bar Pro", "Grape Ice", "葡萄冰", 30), IT2("XF-03", "Bar Pro", "Mango Ice", "芒果冰", 30), IT2("XF-04", "Ali", "Pink Lemon", "粉柠檬", 25)]),
      "movements": {"p-1-r1-XF-01": {"type": "in", "sku": "XF-01", "name": "香蕉", "qty": 4, "date": TODAY, "at": TODAY + "T02:00:00Z", "po_id": "p-1", "po_line": "XF-01", "receipt_id": "r1", "cost": 120, "note": "订货到货"}},
      "purchases": {"p-1": {"date": TODAY, "at": TODAY + "T01:00:00Z", "note": "", "supplier": "合伙人甲", "paid": True, "paid_date": TODAY, "total": 725,
                            "lines": [{"sku": "XF-01", "name": "香蕉", "series": "Bar Pro", "qty": 10, "unit_cost": 30}, {"sku": "XF-02", "name": "葡萄冰", "series": "Bar Pro", "qty": 10, "unit_cost": 30},
                                      {"series": "Ali", "sku": None, "name": "Ali（口味到货再分）", "qty": 5, "unit_cost": 25}]}},
      "expenses": {"p-1-pay": {"date": TODAY, "at": TODAY + "T01:00:00Z", "amount": 725, "category": "进货成本", "note": "订货", "po_id": "p-1"}},
      "orders": {}, "settlements": {}, "transfers": {}, "customers": {}, "followups": {}}
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
        # 卡片（种子里的订货单：香蕉 10（到了 4）、葡萄冰 10、Ali 系列 5）
        go(pg, "purchases"); card = pg.locator("#po-list article.po").first
        check("标题是每个系列几盒：Bar Pro 2 盒 · Ali 5 根", card.locator(".po-title").inner_text() == "Bar Pro 2 盒 · Ali 5 根", card.locator(".po-title").inner_text())
        its = card.evaluate("(c) => [...c.querySelectorAll('.po-sg')].map((g) => [g.querySelector('.po-sgh b').textContent, [...g.querySelectorAll('.po-it')].map((i) => i.querySelector('.po-n').firstChild.textContent + ' | ' + i.querySelector('.po-q').innerText.replace(/\\n/g, ' '))])")
        check("按系列往下排：Bar Pro（香蕉 × 1 盒 已到 4 差 6、葡萄冰 × 1 盒）、Ali（口味到货再分 × 5 根）", its == [["Bar Pro", ["Banana Buzz | × 1 盒 已到 4 · 差 6", "Grape Ice | × 1 盒"]], ["Ali", ["口味到货再分 | × 5 根"]]], its)
        check("最后合计：Bar Pro 2 盒 · Ali 5 根　共 25 根", "合计" in card.locator(".po-tot").inner_text() and "Bar Pro 2 盒 · Ali 5 根" in card.locator(".po-tot").inner_text() and "25 根" in card.locator(".po-tot").inner_text(), card.locator(".po-tot").inner_text())
        rc = card.locator(".po-rc li").first.inner_text()
        check("到货记录一行：「X月X日 到货 4 根」+ 撤销（口味收起来）", "到货 4 根" in rc and "撤销" in rc and "Banana" not in rc.split("撤销")[0].split("\n")[0], rc)
        check("没有旧的大表格、没有重复的「现金 · 现金」", card.locator("table").count() == 0 and "现金 · 现金" not in card.inner_text())

        # 新建：粘贴按盒写的清单
        pg.click("text=新建订货"); pg.wait_for_selector("#f-pastebtn"); pg.click("#f-pastebtn")
        pg.fill("#f-paste", "Bar Pro\n香蕉 2盒\nGrape Ice 3\nMango Ice 1 box\nAli\n粉红柠檬 两盒"); pg.click("#f-parse"); pg.wait_for_timeout(300)
        q = lambda: pg.evaluate("Object.fromEntries([...document.querySelectorAll('#f-lines .line')].map((r) => [document.getElementById('f-sku-' + r.dataset.line).value, Number(document.getElementById('f-qty-' + r.dataset.line).value)]))")
        check("2盒 / 1 box / 两盒 → 20 / 10 / 20 根；没写单位的 3 跟着按盒 = 30", q() == {"XF-01": 20, "XF-02": 30, "XF-03": 10, "XF-04": 20}, q())
        check("识别结果写「共 8 盒（80 根）」，有「盒 / 根」可以切", "8</b> 盒" in pg.inner_html("#f-parsed") and pg.get_attribute('#f-parsed [data-pu="box"]', "aria-pressed") == "true", pg.inner_text("#f-parsed"))
        pg.click('#f-parsed [data-pu="pc"]'); pg.wait_for_timeout(200)
        check("切成「根」：没写单位的 3 → 3 根，写了盒的不变（不会重复加）", q() == {"XF-01": 20, "XF-02": 3, "XF-03": 10, "XF-04": 20}, q())
        pg.click('#f-parsed [data-pu="box"]'); pg.wait_for_timeout(200)
        check("再切回「盒」：30", q() == {"XF-01": 20, "XF-02": 30, "XF-03": 10, "XF-04": 20}, q())
        gn = pg.evaluate("[...document.querySelectorAll('#f-lines .po-grp')].map((g) => [g.dataset.sr, g.querySelector('.po-gn').textContent])")
        check("系列框头写几盒：Bar Pro 6 盒、Ali 2 盒", gn == [["Bar Pro", "6 盒"], ["Ali", "2 盒"]], gn)
        check("按系列一起改：只有 Bar Pro 一行（每种几根、每根 $）", pg.evaluate("[...document.querySelectorAll('#f-serp .po-sr b')].map((b) => b.textContent)") == ["Bar Pro"])
        pg.fill('#f-serp input[data-srq="Bar Pro"]', "10"); pg.fill('#f-serp input[data-sr="Bar Pro"]', "28"); pg.wait_for_timeout(150)
        check("Bar Pro 每种 10 根：三种都 10，Ali 不动", q() == {"XF-01": 10, "XF-02": 10, "XF-03": 10, "XF-04": 20}, q())
        save(pg)
        po = next(x for x in S(pg, "purchases") if x["id"] != "p-1")
        L = {l["sku"]: (l["qty"], l.get("unit_cost")) for l in po["lines"]}
        check("存了：Bar Pro 三种各 10 根 $28、粉红柠檬 20 根", L == {"XF-01": (10, 28), "XF-02": (10, 28), "XF-03": (10, 28), "XF-04": (20, 25)}, L)
        go(pg, "purchases"); c2 = pg.locator("#po-list article.po").filter(has=pg.locator('.po-title:text-is("Bar Pro 3 盒 · Ali 2 盒")'))
        check("新订货单卡片标题「Bar Pro 3 盒 · Ali 2 盒」，合计共 5 盒", c2.count() == 1 and "共 5 盒" in c2.locator(".po-tot").inner_text(), [t for t in pg.locator("#po-list .po-title").all_inner_texts()])
        ctx.close()
    br.close()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
