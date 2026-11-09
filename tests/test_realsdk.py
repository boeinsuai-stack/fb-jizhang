"""真 Firebase SDK 测试：用 App 自带的 Firestore SDK（public/vendor）+ Chrome 真的本地数据库（IndexedDB），断网运行。
只把登录换成假的（登录要联网）。验证：超过 1000 条全部显示、删除留标记且看不到、关掉重开从本地数据库读回来。
运行：python3 tests/test_realsdk.py [public 目录]"""
import functools, http.server, sys, threading, pathlib, tempfile
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ROOT.parent / "public").resolve()
AUTH_STUB = "firebase.auth = () => ({ onAuthStateChanged() {}, currentUser: null, signOut: () => Promise.resolve() });"
results = []
def check(name, ok, extra=""):
    results.append(ok); print(("✅ " if ok else "❌ ") + name + (("  " + extra) if extra else ""))


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass


s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(PUB)))
threading.Thread(target=s.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{s.server_address[1]}/index.html"

COUNT = """async () => { const db = await window.claude.use("db");
  return await new Promise((res) => db.collection("movements").limit(1000).onSnapshot((s) => res({ n: s.size, u: s.docs.some((d) => "_u" in d.data()), del: s.docs.some((d) => d.id === "m-0007") }))); }"""

with sync_playwright() as p, tempfile.TemporaryDirectory() as prof:
    def launch():
        ctx = p.chromium.launch_persistent_context(prof, executable_path="/usr/bin/google-chrome", args=["--no-sandbox"], service_workers="block", viewport={"width": 390, "height": 844})
        ctx.add_init_script("localStorage.setItem('fb-last-user', JSON.stringify({ uid: 'u-test', email: '', displayName: '测试' }));")
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.on("pageerror", lambda e: print("   页面报错：", e))
        pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body=AUTH_STUB, content_type="text/javascript"))
        pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())  # 断网：Google 的服务器都连不上
        pg.goto(URL)
        pg.wait_for_function("window.__fbFirstSync", timeout=15000)
        return ctx, pg

    ctx, pg = launch()
    # 没网时写进 1200 条流水（分 3 批，每批 400 条）
    pg.evaluate("""async () => { const db = await window.claude.use("db");
      for (let b = 0; b < 3; b++) { const wb = db.batch();
        for (let i = b * 400; i < (b + 1) * 400; i++) wb.set(db.collection("movements").doc("m-" + String(i).padStart(4, "0")), { type: "in", sku: "XF-01", qty: 1, date: "2026-11-09" });
        await wb.commit(); } }""")
    r = pg.evaluate(COUNT)
    check("真 SDK、没网：写进 1200 条，App 里显示 1200 条（不再卡 1000）", r["n"] == 1200, str(r["n"]))
    check("App 里看不到内部字段 _u", not r["u"])
    pg.evaluate("""async () => { const db = await window.claude.use("db"); await db.collection("movements").doc("m-0007").delete(); }""")
    r = pg.evaluate(COUNT)
    check("删除一条：App 里看不到，剩 1199 条", r["n"] == 1199 and not r["del"], str(r["n"]))
    raw = pg.evaluate("""() => firebase.firestore().doc("movements/m-0007").get({ source: "cache" }).then((s) => s.exists ? s.data() : null)""")
    check("本地数据库里留的是已删除标记（等有网传到云端）", bool(raw) and raw.get("_deleted") is True and "qty" not in raw, str(raw)[:60])
    ctx.close()

    # 关掉 App 再打开（同一个浏览器资料夹 = 同一台手机），还是没网
    ctx, pg = launch()
    r = pg.evaluate(COUNT)
    check("关掉重开、没网：从手机本地数据库读回 1199 条", r["n"] == 1199, str(r["n"]))
    ctx.close()

print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
