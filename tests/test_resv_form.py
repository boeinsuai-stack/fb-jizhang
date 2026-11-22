"""预定表单整理（2026-11-22 Bowen：交货那块的时间、联系很乱，整个表单太长）
- 预定时：客户、交货挪到口味下面；交货是一个小框「哪天 / 几点 / 在哪」；「几点」二选一：约好了（几点见）/ 还没定（他说几点到几点方便联系），同时只出现一个
- 付款方式收起来（「付款方式（结算时再选；已经付了点这里）」）；「按整单总价」是加一行旁边的小开关；配送费一行
- 记卖出照旧（付款方式在、没有交货、客户在配送费下面）
用编出来的小数据，旧结构 / 新结构各一遍。运行：python3 tests/test_resv_form.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
IT = lambda sku, ser, v, n, c: {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": 60, "cost_aud": c, "status": "在售"}
import datetime as _dt
DD = lambda n: (_dt.date.fromisoformat(TODAY) + _dt.timedelta(days=n)).isoformat()
V1 = {"items": {"XF-01": IT("XF-01", "Bar Pro", "Banana Buzz", "香蕉", 30)},
      "movements": {"m-in": {"type": "in", "sku": "XF-01", "name": "香蕉", "qty": 20, "date": TODAY, "at": TODAY + "T01:00:00Z", "cost": 600, "note": "进货"}},
      "orders": {"o-r": {"status": "reserved", "date": TODAY, "at": TODAY + "T02:00:00Z", "customer": "Bob", "lines": [{"sku": "XF-01", "name": "香蕉", "qty": 1, "unit_price": 60}], "delivery_fee": 0, "payment": "", "note": "", "meet_date": DD(1), "meet_time": "15:00"}},
      "expenses": {}, "purchases": {}, "settlements": {}, "transfers": {}, "customers": {}, "followups": {}}
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
def order_of(pg, who): return next(o for o in S(pg, "orders") if o.get("customer") == who)
def before(pg, a, b): return pg.evaluate("([a, b]) => !!(document.querySelector(a).compareDocumentPosition(document.querySelector(b)) & Node.DOCUMENT_POSITION_FOLLOWING)", [a, b])
def open_resv(pg, who):
    go(pg, "finance"); pg.click("#fin-sale"); pg.wait_for_selector("#f-skuq-0"); pg.check("#f-resv"); pg.wait_for_timeout(100)
    pg.fill("#f-skuq-0", "香蕉"); pg.press("#f-skuq-0", "Enter"); pg.fill("#f-cust", who)

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
        open_resv(pg, "Amy")
        check("预定：客户、交货在口味下面、配送费上面", before(pg, "#f-lines", "#f-cust") and before(pg, "#f-cust", "#f-meet") and before(pg, "#f-meet", "#f-fee"))
        check("交货框三行：哪天 / 几点 / 在哪", pg.evaluate("[...document.querySelectorAll('#f-meet .mb-k')].map((x) => x.textContent)") == ["哪天", "几点", "在哪"])
        check("哪天：默认今天，旁边写「今天」", pg.input_value("#f-mdate") == TODAY and pg.inner_text("#f-mday") == "今天")
        pg.fill("#f-mdate", DD(1)); pg.dispatch_event("#f-mdate", "change")
        check("改成明天：写「明天」", pg.inner_text("#f-mday") == "明天")
        pg.fill("#f-mdate", DD(5)); pg.dispatch_event("#f-mdate", "change"); d5 = _dt.date.fromisoformat(DD(5))
        check("再往后写「X月Y日 周Z」", pg.inner_text("#f-mday").startswith(f"{d5.month}月{d5.day}日 周"), pg.inner_text("#f-mday"))
        check("几点：默认「还没定」，只出现「他说几点到几点方便联系」", pg.get_attribute('#f-mmode [data-mm="none"]', "aria-pressed") == "true" and pg.is_visible("#f-cfrom") and not pg.is_visible("#f-mtime"))
        pg.click('#f-mmode [data-mm="set"]')
        check("点「约好了」：只出现几点见", pg.is_visible("#f-mtime") and not pg.is_visible("#f-cfrom"))
        check("付款方式收起来，只有一行「付款方式（结算时再选…）」", not pg.is_visible("#f-paychips") and pg.is_visible("#f-payshow"))
        check("「按整单总价」是加一行旁边的小开关", pg.is_visible(".addrow #f-lumpon") and not pg.is_visible("#f-lump"))
        pg.check(".addrow #f-lumpon"); check("打开 → 出现总价框", pg.is_visible("#f-lump")); pg.uncheck(".addrow #f-lumpon")
        pg.fill("#f-mtime", "16:30"); save(pg)
        a = order_of(pg, "Amy")
        check("约好了 16:30：存了几点，没有联系时间", a.get("meet_date") == DD(5) and a.get("meet_time") == "16:30" and not a.get("call_win"), {k: a.get(k) for k in ("meet_date", "meet_time", "call_win")})

        open_resv(pg, "Cat"); pg.fill("#f-cfrom", "16:00"); pg.fill("#f-cto", "18:00")
        pg.click('#f-mmode [data-mm="set"]'); pg.fill("#f-mtime", "10:00"); pg.click('#f-mmode [data-mm="none"]'); save(pg)
        c = order_of(pg, "Cat")
        check("还没定 + 他说 16–18 点：没存几点（中途填过的 10:00 不算），存了联系时间", not c.get("meet_time") and c.get("call_win") == "16:00-18:00", {k: c.get(k) for k in ("meet_time", "call_win")})

        open_resv(pg, "Dan"); pg.click("#f-payshow")
        check("点「付款方式」那行 → 出来", pg.is_visible("#f-paychips") and not pg.is_visible("#f-payshow"))
        pg.click('#f-paychips label:has(input[value="现金"])'); save(pg)
        check("预定也能选好付款方式", order_of(pg, "Dan").get("payment") == "现金")

        go(pg, "finance"); pg.click("#fin-sale"); pg.wait_for_selector("#f-skuq-0")
        check("记卖出：付款方式在、没有交货、客户在配送费下面", pg.is_visible("#f-paychips") and not pg.is_visible("#f-meet") and before(pg, "#f-fee", "#f-cust"))
        pg.check("#f-resv"); pg.wait_for_timeout(100)
        check("勾上「只是预定」→ 客户、交货挪上去，付款方式收起来", before(pg, "#f-cust", "#f-fee") and pg.is_visible("#f-meet") and not pg.is_visible("#f-paychips"))
        pg.uncheck("#f-resv"); pg.wait_for_timeout(100)
        check("取消勾 → 回到记卖出的样子", before(pg, "#f-fee", "#f-cust") and pg.is_visible("#f-paychips"))
        close(pg)

        # 编辑已有的预定（定了 15:00）→「约好了」选着
        go(pg, "customers"); card = pg.locator("#resv details.rv").filter(has=pg.locator('b:text-is("Bob")')).first
        card.locator("summary").click(); card.locator("[data-edit-order]").click(); pg.wait_for_selector("#f-mmode")
        check("编辑定了 15:00 的预定：「约好了」选着、15:00、明天", pg.get_attribute('#f-mmode [data-mm="set"]', "aria-pressed") == "true" and pg.input_value("#f-mtime") == "15:00" and pg.inner_text("#f-mday") == "明天")
        close(pg)
        ctx.close()
    br.close()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
