"""同步测试：去掉 1000 条上限后的增量同步（tests/mockfb.js 模拟「云端 + 手机本地数据库」两层，并按条计费）。
运行：python3 tests/test_sync.py [public 目录]
可选：python3 tests/test_sync.py <旧版 public 目录> --old   只跑场景 1，看旧版丢不丢记录。"""
import functools, http.server, json, sys, threading, pathlib, time
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
args = [a for a in sys.argv[1:] if not a.startswith("--")]
OLD = "--old" in sys.argv
PUB = pathlib.Path(args[0] if args else ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")

# 1100 条进货流水（b- 开头）+ 1 条合伙人调入（t- 开头，按编号排在最后）+ 300 条操作记录
N = 1100
SEED = {
    "items": {s: {"sku": s, "series": "One", "variant": v, "name": n, "price_aud": 30, "cost_aud": 20, "status": "在售"}
              for s, v, n in [("XF-01", "Apple", "苹果"), ("XF-02", "Mango", "芒果")]},
    "movements": {f"b-20261101-{i:04d}-XF-01": {"type": "in", "sku": "XF-01", "name": "苹果", "qty": 1, "date": "2026-11-01", "at": "2026-11-01T01:00:00Z"} for i in range(N)},
    "orders": {"o-20261105-a": {"status": "reserved", "date": "2026-11-05", "at": "2026-11-05T01:00:00Z", "customer": "Amy", "lines": [{"sku": "XF-01", "name": "苹果", "qty": 1, "unit_price": 30}], "delivery_fee": 0}},
    "log": {f"l-{i:04d}": {"at": f"2026-11-0{1 + i // 100}T{(i % 24):02d}:{(i % 60):02d}:00Z", "op": "新增", "col": "orders", "text": f"记录{i}"} for i in range(300)},
}
SEED["movements"]["t-20261103-x-in-XF-02"] = {"type": "in", "sku": "XF-02", "name": "芒果", "qty": 5, "date": "2026-11-03", "at": "2026-11-03T01:00:00Z", "partner": "合伙人甲"}

results = []
def check(name, ok, extra=""):
    results.append(ok); print(("✅ " if ok else "❌ ") + name + (("  " + extra) if extra else ""))


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass


def serve():
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(PUB)))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s.server_address[1]


PROBE = """async () => {
  const db = await window.claude.use("db");
  return await new Promise((res) => {
    const out = {};
    let left = 3; const done = () => { if (--left === 0) res(out); };
    db.collection("movements").limit(1000).onSnapshot((s) => { out.moves = s.size; out.xf02 = s.docs.filter((d) => d.data().sku === "XF-02").length; out.hasU = s.docs.some((d) => "_u" in d.data()); done(); });
    db.collection("orders").limit(1000).onSnapshot((s) => { out.orders = s.docs.map((d) => d.id); done(); });
    db.collection("log").orderBy("at", "desc").limit(200).onSnapshot((s) => { out.log = s.size; out.logFirst = s.docs[0] && s.docs[0].data().at; done(); });
  });
}"""


def open_app(ctx, port, server, cache=None, offline=False, extra=""):
    pg = ctx.new_page()
    init = f"window.__MOCK_OFFLINE={json.dumps(offline)};window.__SEED={json.dumps(server, ensure_ascii=False)};"
    if cache is not None: init += f"window.__CACHE_SEED={json.dumps(cache, ensure_ascii=False)};"
    pg.add_init_script(init + extra)
    pg.on("pageerror", lambda e: print("   页面报错：", e))
    pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
    pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
    pg.goto(f"http://127.0.0.1:{port}/index.html")
    pg.wait_for_function("window.__fbFirstSync", timeout=10000)
    pg.wait_for_timeout(600)
    return pg


with sync_playwright() as p:
    port = serve()
    browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, service_workers="block", locale="zh-CN", timezone_id="Australia/Perth")

    # 场景 1：新手机（本地数据库是空的），云端有 1101 条流水
    pg = open_app(ctx, port, SEED, cache={})
    pg.wait_for_timeout(800)
    r = pg.evaluate(PROBE)
    reads1 = pg.evaluate("__reads")
    print(f"   新手机：流水 {r['moves']} 条，合伙人调入 {r['xf02']} 条，第一次读取计费 {reads1} 条")
    if OLD:
        check("旧版：1101 条流水只显示 1000 条，合伙人调入（t- 开头）被丢掉", r["moves"] == 1000 and r["xf02"] == 0, f"{r['moves']} 条 / 调入 {r['xf02']}")
        browser.close(); print(f"\n{sum(results)}/{len(results)}"); sys.exit(0)
    check("新手机：1101 条流水全部显示（超过 1000 条不丢）", r["moves"] == N + 1)
    check("按编号排在最后的合伙人调入也在", r["xf02"] == 1)
    check("操作记录只显示最新 200 条，最新的在最上面", r["log"] == 200 and r["logFirst"] >= "2026-11-03T23", f"{r['log']} 条，第一条 {r['logFirst']}")
    check("App 里看不到内部字段 _u", not r["hasU"])
    pg.screenshot(path=str(ROOT / "shots" / "sync-1-新手机.png"))
    server1, cache1 = pg.evaluate("({ m: __server('movements'), o: __server('orders'), l: __server('log'), i: __server('items') })"), pg.evaluate("__dumpCache()")
    server1 = {"movements": server1["m"], "orders": server1["o"], "log": server1["l"], "items": server1["i"]}
    pg.close()

    # 场景 2：同一台手机过一会儿再打开（本地数据库还在、同步进度还在）
    pg = open_app(ctx, port, server1, cache=cache1)
    pg.wait_for_timeout(800)
    r = pg.evaluate(PROBE); reads2 = pg.evaluate("__reads")
    check("再次打开：照样 1101 条", r["moves"] == N + 1)
    check(f"再次打开：读取计费从 {reads1} 条降到 {reads2} 条", reads2 < 20, f"{reads2} 条")

    # 场景 3：另一台手机新记一条、删一张预定（删除 = 留已删除标记）
    pg.evaluate("""() => { __remoteWrite("movements", "o-20261109-zz-XF-02", { type: "out", sku: "XF-02", name: "芒果", qty: 2, date: "2026-11-09", at: "2026-11-09T01:00:00Z" });
                           __remoteWrite("orders", "o-20261105-a", { _deleted: true }); }""")
    pg.wait_for_timeout(500)
    r = pg.evaluate(PROBE); reads3 = pg.evaluate("__reads") - reads2
    check("另一台手机新记的流水同步过来了", r["moves"] == N + 2)
    check("另一台手机删掉的预定在这台也消失了", "o-20261105-a" not in r["orders"])
    check(f"同步这 2 条改动只读了 {reads3} 条", reads3 <= 4, f"{reads3} 条")

    # 场景 4：本机删除 → 云端留已删除标记，App 里看不到
    pg.evaluate("""async () => { const db = await window.claude.use("db"); await db.collection("movements").doc("o-20261109-zz-XF-02").delete(); }""")
    pg.wait_for_timeout(300)
    r = pg.evaluate(PROBE); srv = pg.evaluate("__server('movements')['o-20261109-zz-XF-02']")
    check("本机删除后 App 里看不到", r["moves"] == N + 1)
    check("云端留的是已删除标记（另一台手机能同步到）", bool(srv) and srv.get("_deleted") is True and "_u" in srv, json.dumps(srv)[:80])

    # 场景 5：本机新记一条 → 云端带上时间戳 _u
    pg.evaluate("""async () => { const db = await window.claude.use("db"); await db.collection("movements").doc("o-20261109-yy-XF-01").set({ type: "out", sku: "XF-01", qty: 1, date: "2026-11-09" }); }""")
    pg.wait_for_timeout(300)
    srv = pg.evaluate("__server('movements')['o-20261109-yy-XF-01']")
    check("本机新记的流水在云端带时间戳 _u", bool(srv) and isinstance(srv.get("_u"), dict) and "__ts" in srv["_u"])
    upd = pg.evaluate("""async () => { const db = await window.claude.use("db"); await db.collection("movements").doc("o-20261109-yy-XF-01").update({ qty: 3 }); await new Promise((r) => setTimeout(r, 300)); return __server('movements')['o-20261109-yy-XF-01']; }""")
    check("修改也带时间戳", upd.get("qty") == 3 and "__ts" in (upd.get("_u") or {}))
    server5, cache5 = {c: pg.evaluate(f"__server('{c}')") for c in ["movements", "orders", "log", "items"]}, pg.evaluate("__dumpCache()")
    pg.close()

    # 场景 6：隔了一天再打开 → 整份对一次账
    pg = open_app(ctx, port, server5, cache=cache5, extra="""for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k && k.startsWith("fb-sync:")) { const v = JSON.parse(localStorage.getItem(k)); v.full = Date.now() - 25 * 3600e3; localStorage.setItem(k, JSON.stringify(v)); } }""")
    pg.wait_for_timeout(800)
    r = pg.evaluate(PROBE); reads6 = pg.evaluate("__reads")
    check(f"隔一天打开：整份对账一次（读 {reads6} 条），数据正确", reads6 > N and r["moves"] == N + 2)
    pg.close()

    # 场景 7：没网打开（本地数据库有数据）
    pg = open_app(ctx, port, server5, cache=cache5, offline=True)
    r = pg.evaluate(PROBE)
    check("没网打开：从本地数据库显示全部记录", r["moves"] == N + 2)
    pg.close()

    # 场景 8：手机不支持本地数据库（隐私模式）→ 直接读云端，也不限 1000 条
    pg = open_app(ctx, port, server5, cache={}, extra="window.__NO_PERSIST = true;")
    pg.wait_for_timeout(800)
    r = pg.evaluate(PROBE)
    check("没有本地数据库时：直接读云端，也是全部记录", r["moves"] == N + 2 and r["log"] == 200)
    pg.close()

    # 场景 9：业务代码照常工作（打开 App、记一笔卖出）
    pg = open_app(ctx, port, server5, cache=cache5)
    pg.evaluate("location.hash = '#finance'"); pg.wait_for_timeout(300)
    pg.click("#fin-sale"); pg.fill("#f-skuq-0", "Mango"); pg.press("#f-skuq-0", "Enter"); pg.select_option("#f-pay", "现金")
    pg.click("#sheet-save"); pg.wait_for_selector("#sheet", state="hidden", timeout=3000)
    pg.wait_for_timeout(300)
    srv = pg.evaluate("Object.values(__server('movements')).filter(m => m.type === 'out' && m.sku === 'XF-02' && !m._deleted).length")
    check("记一笔卖出：出库进了云端", srv >= 1)
    pg.screenshot(path=str(ROOT / "shots" / "sync-9-记账后.png"))
    browser.close()

print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
