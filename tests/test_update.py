"""有新版提示：主屏幕 App 不划掉就一直跑旧代码 → 切回前台时发现线上版本号变了，标题下显示「有新版 · 点一下更新」
- index.html 的 <meta name="app-version"> 必须跟 sw.js 的 CACHE 一样（发布时两处一起加一；不一样这里就不过）
- 线上版本一样：不提示；不一样：提示，点一下刷新；没网：不提示也不报错
用编出来的小数据，GitHub 上也跑。运行：python3 tests/test_update.py"""
import os, re, sys, json, functools, http.server, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
results = []
def check(name, ok, extra=""):
    results.append(ok); print(("✅ " if ok else "❌ ") + name + (("  " + str(extra)[:200]) if extra and not ok else ""))

sw = (PUB / "sw.js").read_text(encoding="utf8"); page = (PUB / "index.html").read_text(encoding="utf8")
ver_sw = re.search(r'const CACHE = "([^"]+)"', sw).group(1)
m = re.search(r'<meta name="app-version" content="([^"]+)">', page)
check("index.html 的版本号 = sw.js 的 CACHE（" + ver_sw + "）", bool(m) and m.group(1) == ver_sw, m and m.group(1))

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(type("H", (http.server.SimpleHTTPRequestHandler,), {"log_message": lambda *a: None}), directory=str(PUB)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/index.html"
SEED = {"items": {"XF-01": {"sku": "XF-01", "series": "Bar Pro", "variant": "Banana Buzz", "name": "香蕉", "price_aud": 60, "cost_aud": 30, "status": "在售"}}, "meta": {"backfill": {"done": True}}}
online = {"ver": ver_sw, "down": False}

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", locale="zh-CN")
    ctx.add_init_script("window.__SEED = " + json.dumps(SEED, ensure_ascii=False) + ";")
    pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
    pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/sw.js", lambda r: r.abort() if online["down"] else r.fulfill(body=sw.replace(ver_sw, online["ver"]), content_type="text/javascript"))
    pg.goto(URL); pg.wait_for_selector("header.top", timeout=15000); pg.wait_for_timeout(1500)
    bar = lambda: pg.locator("#update-bar").count()
    pg.evaluate("window.__fbCheckUpdate()"); pg.wait_for_timeout(400)
    check("线上版本跟这一页一样：不提示", bar() == 0)
    online["down"] = True
    pg.evaluate("window.__fbCheckUpdate()"); pg.wait_for_timeout(400)
    check("读不到线上版本（没网）：不提示，也不报错", bar() == 0 and not errs, errs)
    online["down"] = False; online["ver"] = "fb-app-v999"
    pg.evaluate("document.dispatchEvent(new Event('visibilitychange'))"); pg.wait_for_timeout(400)
    check("5 分钟内切回来不重复查", bar() == 0)
    pg.evaluate("window.__fbCheckUpdate()"); pg.wait_for_timeout(400)
    check("线上有新版：标题下面出现「有新版 · 点一下更新」", bar() == 1 and pg.inner_text("#update-bar") == "有新版 · 点一下更新" and pg.evaluate("document.querySelector('header.top').nextElementSibling.id") == "update-bar")
    pg.evaluate("window.__fbCheckUpdate()"); pg.wait_for_timeout(300)
    check("不会出现两条", bar() == 1)
    pg.evaluate("window.__mark = 1"); online["ver"] = ver_sw
    pg.click("#update-bar"); pg.wait_for_function("!window.__mark && !!window.__fbCheckUpdate", timeout=10000); pg.wait_for_timeout(1500)
    pg.evaluate("window.__fbCheckUpdate()"); pg.wait_for_timeout(400)
    check("点一下：页面刷新，刷新后是新版就不再提示", bar() == 0)
    br.close()

print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
