"""弹出页（二级页面）：后面的页面锁住、不自动弹日期滚轮；订货日期默认今天（旧结构，编的数据，GitHub 上也跑）
- 先把一级页面往下滑一段，打开「新建订货」，在弹出页里一直往下滑：后面的页面不能跟着动；关掉后回到原来的位置
- 打开弹出页不自动聚焦日期框 / 下拉框（iPhone 上一聚焦就弹出滚轮）；订货单整页不自动聚焦（不弹键盘）
- 订货单不显示日期框，底下「订货日期：今天 · 改」；点「改」能改，保存用改过的日期
运行：python3 tests/test_sheet.py"""
import os, datetime, functools, http.server, json, subprocess, sys, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
EXPOSE = "\nwindow.__GM = { S, derive };\n})();"
D = (datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date() - datetime.timedelta(days=3)).isoformat()
W = "合伙人甲"

item = lambda k: ("XF-%02d" % k, {"sku": "XF-%02d" % k, "series": "Bar Pro" if k % 2 else "Ali", "variant": "Flavour %d" % k, "name": "口味%d" % k, "price_aud": 70, "cost_aud": 30, "status": "在售"})
V1 = {"items": dict(item(k) for k in range(1, 41)),
      "movements": {"in-%d" % k: {"type": "in", "sku": "XF-%02d" % k, "name": "口味%d" % k, "qty": 3, "cost": 90, "date": D, "at": D + "T01:00:00Z", "note": "进货"} for k in range(1, 41)},
      "orders": {}, "expenses": {}, "transfers": {}, "settlements": {}, "purchases": {}, "customers": {}, "followups": {}, "meta": {"backfill": {"done": True}}}


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

Y = "() => Math.round(window.scrollY || -parseFloat(document.body.style.top || 0))"  # 锁住时 body 被 fixed，位置记在 top 上
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    ctx = br.new_context(viewport={"width": 390, "height": 700}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN", has_touch=True)
    ctx.add_init_script("window.__SEED=" + json.dumps(V1, ensure_ascii=False) + ";")
    pg = ctx.new_page(); pg.on("pageerror", lambda e: print("   页面报错：", e))
    pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
    pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
    pg.goto(URL); pg.wait_for_function("window.__GM && window.__GM.S.items.length === 40", timeout=15000); pg.wait_for_timeout(500)

    # 库存页往下滑一段，再从这里打开一个弹出页（进货）：弹出页里一直往下滑
    pg.evaluate("window.scrollTo(0, 600)"); pg.wait_for_timeout(200)
    y0 = pg.evaluate(Y)
    check("一级页面先滑到 600", y0 >= 500, str(y0))
    pg.evaluate("document.getElementById('inv-in').click()")
    pg.wait_for_selector("#sheet:not([hidden])", timeout=4000)
    act = pg.evaluate("(() => { const a = document.activeElement; return a && a.tagName + ':' + (a.type || ''); })()")
    check("打开进货：没有自动聚焦日期框（不弹滚轮）", "date" not in act, act)
    box = pg.locator(".sheet-card").bounding_box()
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    for _ in range(25): pg.mouse.wheel(0, 400); pg.wait_for_timeout(30)
    pg.wait_for_timeout(300)
    y1 = pg.evaluate(Y)
    check("弹出页滑到底再滑：后面的页面没动", y1 == y0, f"{y0} → {y1}")
    pg.mouse.move(195, 40)  # 弹出页外面（灰色背景）上滑
    for _ in range(5): pg.mouse.wheel(0, 400); pg.wait_for_timeout(30)
    check("在弹出页外面滑：后面的页面也没动", pg.evaluate(Y) == y0)
    pg.click("#sheet-close"); pg.wait_for_timeout(200)
    check("关掉后回到原来的位置", abs(pg.evaluate("window.scrollY") - y0) <= 1 and pg.evaluate("document.body.style.position") == "", str(pg.evaluate("window.scrollY")))

    # 订货单：整页不自动聚焦；日期默认今天，可以改
    pg.evaluate("location.hash = '#purchases'"); pg.wait_for_timeout(300); pg.click("#po-new"); pg.wait_for_selector("#f-ptiles .tile", timeout=4000)
    act = pg.evaluate("(() => { const a = document.activeElement; return a ? a.tagName + '#' + a.id : ''; })()")
    check("打开新建订货：不自动聚焦任何输入框（不弹键盘、不弹日期）", not act.startswith("INPUT") and not act.startswith("TEXTAREA"), act)
    check("订货单不显示日期框，底下写「订货日期：今天」", pg.evaluate("document.getElementById('f-date').hidden") and pg.inner_text(".po-date").startswith("订货日期：今天"), pg.inner_text(".po-date"))
    pg.click('[data-padd="XF-01"]')
    pg.click("#f-date-edit")
    yday = (datetime.date.fromisoformat(D) + datetime.timedelta(days=2)).isoformat()  # D 是三天前 → 昨天
    pg.fill("#f-date", yday); pg.dispatch_event("#f-date", "change")
    check("点「改」出现日期框，改了以后显示改的日期", pg.is_visible("#f-date") and "今天" not in pg.inner_text(".po-date"), pg.inner_text(".po-date"))
    pg.click("#sheet-save"); pg.wait_for_timeout(800)
    P = pg.evaluate("window.__GM.S.purchases")
    check("保存用改过的日期", P and P[0]["date"] == yday, str(P and P[0]["date"]))
    pg.click("#po-new"); pg.wait_for_selector("#f-ptiles .tile", timeout=4000); pg.click('[data-padd="XF-03"]'); pg.click("#sheet-save"); pg.wait_for_timeout(800)
    TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
    check("不改就是今天", sorted(x["date"] for x in pg.evaluate("window.__GM.S.purchases"))[-1] == TODAY)
    # 快速下单 → 下单 / 预定、财务页记一笔：口味下拉不能自己弹出来，也不弹键盘（2026-11-15：自动聚焦跳过勾选框以后，光标落到了口味搜索框上）
    QUIET = """(() => { const a = document.activeElement, open = [...document.querySelectorAll('#sheet .pick-list')].filter((u) => !u.hidden).length;
      return (a && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) ? '光标在 ' + a.id : '') + (open ? ' 口味下拉弹出 ' + open : ''); })()"""
    for btn, name in (("#cb-go", "下单"), ("#cb-resv", "预定")):
        pg.evaluate("location.hash = '#inventory'"); pg.wait_for_timeout(300)
        if not pg.is_visible(btn): pg.click('#qo-tiles [data-add="XF-01"]')
        pg.click(btn); pg.wait_for_selector("#f-skuq-0", timeout=4000); pg.wait_for_timeout(300)
        check("快速下单点「" + name + "」：口味已经带进来，下拉不弹、光标不进输入框", pg.evaluate(QUIET) == "" and pg.input_value("#f-sku-0") == "XF-01", pg.evaluate(QUIET))
        pg.click("#f-skuq-0"); pg.wait_for_timeout(200)
        check("自己点口味框，下拉照样出来", pg.evaluate("!document.getElementById('f-pl-0').hidden"))
        pg.click("#sheet-close"); pg.wait_for_timeout(250)
    pg.evaluate("location.hash = '#finance'"); pg.wait_for_timeout(300); pg.click("#fin-sale"); pg.wait_for_selector("#f-skuq-0", timeout=4000); pg.wait_for_timeout(300)
    check("财务页「记一笔」：下拉不自己弹", pg.evaluate(QUIET) == "", pg.evaluate(QUIET))
    pg.click("#sheet-close"); pg.wait_for_timeout(250)
    br.close()

print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
