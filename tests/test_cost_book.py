"""其他成本账本（2026-11-21 Bowen：配送的邮费、Facebook 广告费要算进去，作为一个账本）+ 标题「地点」离「中转站待更新」太近
- 财务净赚那块：「货的成本」只算货；下面一行「其他成本 $X · 邮费 $a · 广告费 $b　账本 ›」
- 「记成本」：类别一排标签（邮费 / 广告费 / 油费 / 包装 / 其他，必须选），「上次 $X」一点就填；净赚扣掉
- 账本：跟着上面选的时间段，一共多少、按类别（点了只看这一类），点一笔改 / 删，改完回到账本；每天明细里点这笔「编辑」也是这个表
用编出来的小数据，旧结构 / 新结构各一遍，GitHub 上也跑。运行：python3 tests/test_cost_book.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
IT = lambda sku, ser, v, n, c: {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": 60, "cost_aud": c, "status": "在售"}
V1 = {"items": {"XF-01": IT("XF-01", "Bar Pro", "Banana Buzz", "香蕉", 30)},
      "movements": {"b-1-XF-01": {"type": "in", "sku": "XF-01", "name": "香蕉", "qty": 10, "date": TODAY, "at": TODAY + "T01:00:00Z", "cost": 300, "batch_id": "b-1", "note": "进货"}},
      "expenses": {"b-1-cost": {"date": TODAY, "at": TODAY + "T01:00:00Z", "amount": 300, "category": "进货成本", "note": "进货 香蕉 ×10", "batch_id": "b-1"},
                   "e-old": {"date": TODAY, "at": TODAY + "T02:00:00Z", "amount": 20, "category": "推广", "note": "以前记的"}},
      "orders": {"o-1": {"status": "paid", "date": TODAY, "at": TODAY + "T03:00:00Z", "customer": "Amy", "lines": [{"sku": "XF-01", "name": "香蕉", "qty": 2, "unit_price": 60}], "delivery_fee": 0, "payment": "现金", "note": ""}},
      "purchases": {}, "settlements": {}, "transfers": {}, "customers": {}, "followups": {}}
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
def money_(pg, sel): return float(pg.inner_text(sel).replace("$", "").replace(",", "").strip() or 0)
def exps(pg): return [x for x in S(pg, "expenses") if x.get("category") != "进货成本"]
def cost(pg, cat, amt, note="", last=False):
    pg.click("#fin-exp"); pg.wait_for_selector("#f-ccat"); pg.check(f'input[name="f-ccatr"][value="{cat}"]')
    if last: pg.click("#f-clast [data-last]")
    else: pg.fill("#f-amt", str(amt))
    pg.fill("#f-note", note); save(pg)

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    for mode in ("旧结构", "新结构"):
        seed = V2 if mode == "新结构" else dict(V1, meta={"backfill": {"done": True}})
        ctx = br.new_context(viewport={"width": 375, "height": 760}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
        ctx.add_init_script("window.__SEED = " + json.dumps(seed, ensure_ascii=False) + "; try { localStorage.setItem('mk-period', 'month'); } catch (_) {}")
        pg = ctx.new_page(); pg.set_default_timeout(8000); pg.on("pageerror", lambda e: (print("   页面报错：", e), results.append(False)))
        pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
        pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
        pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.goto(URL); pg.wait_for_function("window.__GM && window.__GM.S.loaded", timeout=15000); pg.wait_for_timeout(500)
        print("== " + mode)
        # 标题：「地点」跟右上角同步状态（「中转站待更新 ↻」能点）拉开
        go(pg, "customers")
        gap = pg.evaluate("(() => { const b = document.getElementById('sync-badge'); b.querySelector('b').textContent = '已保存到云端 14:12 · 中转站待更新 ↻'; return document.getElementById('hd-place').getBoundingClientRect().top - b.getBoundingClientRect().bottom; })()")
        check("「地点」按钮上边离同步状态那行字 ≥ 18 像素", gap >= 18, gap)

        go(pg, "finance")
        check("净赚那块：「货的成本」只算货 $60（2 根 × $30）", pg.inner_text("#f-hero").count("货的成本") == 1 and money_(pg, "#f-exp") == 60, (pg.inner_text("#f-exp")))
        oc = pg.inner_text("#f-oc")
        check("下面一行「其他成本 $20 · 推广 $20 … 账本 ›」", "其他成本 $20" in oc and "推广 $20" in oc and "账本" in oc, oc)
        net0 = money_(pg, "#f-profit")
        check("净赚 = 120 − 60 − 20 = $40", net0 == 40, net0)
        check("按钮叫「记成本」", pg.inner_text("#fin-exp") == "记成本")

        pg.click("#fin-exp"); pg.wait_for_selector("#f-ccat")
        check("类别是一排标签：邮费 / 广告费 / 油费 / 包装 / 其他", pg.evaluate("[...document.querySelectorAll('#f-ccat input')].map((x) => x.value)") == ["邮费", "广告费", "油费", "包装", "其他"])
        pg.fill("#f-amt", "12"); save(pg)
        check("没选类别：不让存", pg.is_visible("#sheet") and "选一下是什么钱" in pg.inner_text("#sheet-err"))
        pg.check('input[name="f-ccatr"][value="邮费"]')
        check("选了邮费：说明框提示「寄给谁 / 哪一单」", "寄给谁" in pg.get_attribute("#f-note", "placeholder"))
        pg.fill("#f-note", "寄给 Amy"); save(pg)
        e = [x for x in exps(pg) if x.get("category") == "邮费"]
        check("存了一笔邮费 $12（今天、写着寄给 Amy）", len(e) == 1 and e[0]["amount"] == 12 and e[0]["date"] == TODAY and e[0]["note"] == "寄给 Amy", e)
        check("净赚少了 $12", money_(pg, "#f-profit") == net0 - 12, pg.inner_text("#f-profit"))
        pg.click("#fin-exp"); pg.wait_for_selector("#f-ccat"); pg.check('input[name="f-ccatr"][value="邮费"]'); pg.wait_for_timeout(100)
        check("再记邮费：有「上次 $12」", "上次 $12" in pg.inner_text("#f-clast"), pg.inner_text("#f-clast"))
        pg.click("#f-clast [data-last]"); check("点一下就填 12", pg.input_value("#f-amt") == "12"); save(pg)
        cost(pg, "广告费", 50, "Facebook 广告")
        oc = pg.inner_text("#f-oc")
        check("其他成本 $94 · 广告费 $50 · 邮费 $24 · 推广 $20", "其他成本 $94" in oc and "广告费 $50 · 邮费 $24 · 推广 $20" in oc, oc)
        check("利润表有「减：邮费」「减：广告费」", "减：邮费" in pg.text_content("#f-stmt") and "减：广告费" in pg.text_content("#f-stmt"))

        # 账本
        pg.click("#f-oc"); pg.wait_for_selector(".cb-tot")
        check("账本：标题「其他成本 · 本月」，一共 $94，4 笔，没有进货成本", "其他成本 · 本月" in pg.inner_text("#sheet") and pg.inner_text(".cb-tot") == "$94" and pg.locator(".cb-row").count() == 4, (pg.inner_text(".cb-tot"), pg.locator(".cb-row").count()))
        pg.click('#cb-cats [data-f="邮费"]'); pg.wait_for_timeout(100)
        check("点「邮费」只看邮费（2 笔）", pg.locator(".cb-row:visible").count() == 2)
        ad = next(x for x in exps(pg) if x["category"] == "广告费")
        pg.click('#cb-cats [data-f=""]'); pg.click(f'[data-cb="{ad["id"]}"]'); pg.wait_for_selector("#f-cdel")
        check("点一笔：打开「改一笔成本」，广告费已选上", pg.is_checked('input[name="f-ccatr"][value="广告费"]') and pg.input_value("#f-amt") == "50")
        pg.fill("#f-amt", "60"); save(pg); pg.wait_for_selector(".cb-tot")
        check("改成 $60，存完回到账本（一共 $104）", next(x for x in exps(pg) if x["id"] == ad["id"])["amount"] == 60 and pg.inner_text(".cb-tot") == "$104", pg.inner_text(".cb-tot"))
        pg.click(f'[data-cb="{ad["id"]}"]'); pg.wait_for_selector("#f-cdel"); pg.click("#f-cdel"); pg.click("#f-cdel"); pg.wait_for_selector(".cb-tot")
        check("删掉这笔（点两下），回到账本（一共 $44）", not any(x["id"] == ad["id"] for x in exps(pg)) and pg.inner_text(".cb-tot") == "$44", pg.inner_text(".cb-tot"))
        pg.click("#sheet-close"); pg.wait_for_timeout(200)

        # 每天明细里点这笔「编辑」也是这个表
        pg.evaluate("() => document.querySelectorAll('#fin-view details').forEach((d) => d.open = true)"); pg.wait_for_timeout(150)
        old = next(x for x in exps(pg) if x["category"] == "推广")
        pg.locator(f'[data-edit-exp="{old["id"]}"]').first.click(); pg.wait_for_selector("#f-ccat")
        check("以前记的「推广」打开也是新的表，类别里多一个「推广」并选上", pg.is_checked('input[name="f-ccatr"][value="推广"]'))
        pg.check('input[name="f-ccatr"][value="广告费"]'); save(pg)
        check("改成广告费", next(x for x in exps(pg) if x["id"] == old["id"])["category"] == "广告费")
        pg.click('#period [data-p="last"]'); pg.wait_for_timeout(200)
        check("上月：其他成本 $0", "其他成本 $0" in pg.inner_text("#f-oc"), pg.inner_text("#f-oc"))
        pg.click("#f-oc"); pg.wait_for_timeout(200)
        check("上月账本：写「还没记其他成本」", "还没记其他成本" in pg.inner_text("#sheet"))
        close(pg)
        ctx.close()
    br.close()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
