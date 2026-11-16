"""打开 App 要快，读到一半不能显示（2026-11-16 Bowen：打开先白屏、等很久；没读完就去复制口味，复制出来的是不对的数字；客户里找不到老客人）。
用编出来的小数据（GitHub 上也跑）。
一、假 Firebase：口味先读到，订单、流水 1.5 秒后才读到（手机上几类记录先后读出来）→ 中间不能按一半的数据显示库存、客户，复制口味要拦住
二、真 Firestore SDK + 真本地数据库 + 真 Service Worker，信号很差（Google 的服务器连得上但一直不回应；不用 Playwright 拦请求，拦了会带 no-store）：
    手机里已经有全部数据 → 2.5 秒内显示出来；标题下写明「现在显示的是这台手机 … 存的数据」
运行：python3 tests/test_fast_start.py [public 目录]"""
import os, re, sys, json, time, socket, shutil, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
results = []
def check(name, ok, extra=""):
    results.append(ok); print(("✅ " if ok else "❌ ") + name + (("  " + extra) if extra else ""))

item = lambda sku, en, cn: (sku, {"sku": sku, "series": "One", "variant": en, "name": cn, "price_aud": 30, "cost_aud": 20, "status": "在售"})
V1 = {
    "items": dict([item("XF-01", "Apple", "苹果"), item("XF-02", "Mango", "芒果"), item("XF-03", "Grape", "葡萄")]),
    "movements": {
        "in-1": {"type": "in", "sku": "XF-01", "name": "苹果", "qty": 6, "date": TODAY, "at": TODAY + "T01:00:00Z", "note": "进货"},
        "in-2": {"type": "in", "sku": "XF-02", "name": "芒果", "qty": 2, "date": TODAY, "at": TODAY + "T01:00:00Z", "note": "进货"},
        "o1-XF-01": {"type": "out", "sku": "XF-01", "name": "苹果", "qty": 1, "date": TODAY, "at": TODAY + "T02:00:00Z", "order_id": "o1", "note": "卖出 · Valentine"},
        "o2-XF-02": {"type": "out", "sku": "XF-02", "name": "芒果", "qty": 2, "date": TODAY, "at": TODAY + "T03:00:00Z", "order_id": "o2", "note": "卖出 · 客人乙"},
    },
    "orders": {
        "o1": {"status": "paid", "date": TODAY, "at": TODAY + "T02:00:00Z", "customer": "Valentine", "payment": "现金", "lines": [{"sku": "XF-01", "name": "苹果", "qty": 1, "unit_price": 30}], "delivery_fee": 0, "note": ""},
        "o2": {"status": "paid", "date": TODAY, "at": TODAY + "T03:00:00Z", "customer": "客人乙", "payment": "现金", "lines": [{"sku": "XF-02", "name": "芒果", "qty": 2, "unit_price": 30}], "delivery_fee": 0, "note": ""},
    },
    "expenses": {}, "purchases": {}, "transfers": {}, "settlements": {}, "customers": {}, "followups": {},
}
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "v1.json").write_text(json.dumps(V1, ensure_ascii=False), encoding="utf8")
subprocess.run(["node", str(ROOT / "v2_seed.js"), str(tmp / "v1.json"), str(tmp / "v2.json")], check=True, capture_output=True)
V2 = json.loads((tmp / "v2.json").read_text(encoding="utf8"))
V2["meta"] = {"schema": {"version": 2}, "backfill": {"done": True}}
FINAL = "5"  # 苹果 6 − 1 = 5，芒果 2 − 2 = 0，葡萄 0

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass

# ---------- 一、假 Firebase：几类记录先后读到 ----------
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(PUB)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/index.html"
POLL = """() => { const t = document.getElementById("sb-total"), c = document.getElementById("c-list");
  return { total: t ? t.textContent.trim() : "", cust: c ? c.textContent : "", toast: (document.getElementById("toast") || {}).textContent || "" }; }"""

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    for mode in ("新结构", "旧结构"):
        seed = V2 if mode == "新结构" else dict(V1, meta={"backfill": {"done": True}})
        slow = {"v2_orders": 1500, "v2_movements": 1500, "v2_purchases": 1500} if mode == "新结构" else {"orders": 1500, "movements": 1500}
        ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
        ctx.add_init_script(f"window.__MOCK_OFFLINE=false; window.__SEED={json.dumps(seed, ensure_ascii=False)}; window.__MOCK_SLOW={json.dumps(slow)};"
                            + (f"localStorage.setItem('fb-schema', {json.dumps(json.dumps({'version': 2}))});" if mode == "新结构" else ""))
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: print("   页面报错：", e))
        pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
        pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
        pg.goto(URL)
        print(f"== 一、{mode}：口味先到，订单/流水晚 1.5 秒")
        shown, copied, t0 = [], None, time.time()
        while time.time() - t0 < 3.2:
            r = pg.evaluate(POLL)
            if r["total"] not in ("", "–"): shown.append(r["total"])
            if copied is None and time.time() - t0 > 0.6:  # 还没读完时点「复制口味」
                pg.evaluate("document.getElementById('toast').textContent = ''")
                pg.evaluate("(() => { const b = [...document.querySelectorAll('button')].find((x) => /复制口味/.test(x.textContent)); if (b) b.click(); })()")
                pg.wait_for_timeout(150); copied = pg.evaluate(POLL)["toast"]
            pg.wait_for_timeout(40)
        check(f"{mode}：没读完时库存页不显示数字，显示出来的一直是读完后的 {FINAL}", bool(shown) and set(shown) == {FINAL}, str(sorted(set(shown))))
        check(f"{mode}：没读完时点「复制口味」→ 拦住：数据还没读完", "还没读完" in (copied or ""), copied)
        pg.evaluate("location.hash = '#customers'"); pg.wait_for_timeout(300)
        check(f"{mode}：读完后客户里有 Valentine", "Valentine" in pg.evaluate(POLL)["cust"])
        ctx.close()
    br.close()

# ---------- 二、真 SDK + 真本地数据库 + 真 Service Worker，信号很差 ----------
PUB2 = tmp / "pub"; shutil.copytree(PUB, PUB2)
h = (PUB2 / "index.html").read_text(encoding="utf8"); h = re.sub(r'<link[^>]+fonts\.(googleapis|gstatic)[^>]*>', "", h)  # 手机上字体早就存过了
(PUB2 / "index.html").write_text(h, encoding="utf8")
(PUB2 / "vendor/firebasejs/10.12.2/firebase-auth-compat.js").write_text("firebase.auth = () => ({ onAuthStateChanged() {}, currentUser: null, signOut: () => Promise.resolve() });")  # 登录要联网：换成假的
HANG = {"on": False}
class H2(Quiet):
    def do_GET(self):
        if HANG["on"]: time.sleep(30); return  # 网站也连得上但不回应
        return super().do_GET()
srv2 = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H2, directory=str(PUB2)))
threading.Thread(target=srv2.serve_forever, daemon=True).start()
URL2 = f"http://127.0.0.1:{srv2.server_address[1]}/index.html"
hs = socket.socket(); hs.bind(("127.0.0.1", 0)); hs.listen(100); HP = hs.getsockname()[1]; keep = []
threading.Thread(target=lambda: [keep.append(hs.accept()) for _ in iter(int, 1)], daemon=True).start()
rs = socket.socket(); rs.bind(("127.0.0.1", 0)); RP = rs.getsockname()[1]; rs.close()
COLS = [c for c in V2 if c != "meta"] + ["log", "movements", "orders", "expenses", "purchases", "settlements", "transfers"]
def presync(ago_ms):  # 用过的手机：每类记录跟云端对过账，记得是新结构
    return ("if (!sessionStorage.getItem('ps')) { sessionStorage.setItem('ps', 1); const t = Date.now() - %d; localStorage.setItem('fb-last-user', JSON.stringify({ uid: 'u-test', email: '', displayName: '测试' }));"
            "localStorage.setItem('fb-schema', JSON.stringify({ version: 2 })); localStorage.setItem('fb-synced:u-test', String(t));" % ago_ms
            + "".join(f"localStorage.setItem('fb-sync:u-test:{c}', JSON.stringify({{ since: t, full: t, n: {len(V2.get(c, {}))} }}));" for c in COLS) + "}")

with sync_playwright() as p, tempfile.TemporaryDirectory() as prof:
    def launch(port, init=""):
        rules = f"MAP *.googleapis.com 127.0.0.1:{port}, MAP *.google.com 127.0.0.1:{port}, MAP *.gstatic.com 127.0.0.1:{port}"
        ctx = p.chromium.launch_persistent_context(prof, executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox", "--host-resolver-rules=" + rules], viewport={"width": 390, "height": 844})
        ctx.add_init_script("localStorage.setItem('fb-last-user', JSON.stringify({ uid: 'u-test', email: '', displayName: '测试' }));" + init)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        return ctx, pg
    # 第一次：网站正常（装好 Service Worker），没网，把数据写进手机本地数据库
    ctx, pg = launch(RP)
    pg.goto(URL2); pg.wait_for_function("window.__fbFirstSync", timeout=15000); pg.wait_for_timeout(1500)
    try:
        pg.evaluate("""(seed) => { const fs = firebase.firestore(); const b = fs.batch();
          for (const [c, m] of Object.entries(seed)) for (const [id, d] of Object.entries(m)) b.set(fs.doc(c + "/" + id), d); b.commit(); return fs.doc("meta/schema").get({ source: "cache" }).then(() => 1); }""", V2)
    except Exception: pass  # 写完 meta/schema App 会自己刷新
    pg.wait_for_timeout(2500)
    sw = pg.evaluate("caches.keys()"); ctx.close()
    print("== 二、真 SDK，信号很差（手机里有全部数据，Service Worker：" + ",".join(sw) + "）")
    for label, ago, want_bar in (("上次跟云端对上是 1 小时前", 3600e3, True), ("上次跟云端对上是 2 分钟前", 120e3, False)):
        HANG["on"] = True
        ctx, pg = launch(HP, presync(int(ago)))
        t0 = time.time(); pg.goto(URL2, wait_until="commit"); seen_ms, partial = None, set()
        while time.time() - t0 < 6:
            try: tt = pg.evaluate("(document.getElementById('sb-total') || {}).textContent || ''")
            except Exception: continue
            if tt not in ("", "–"):
                partial.add(tt)
                if seen_ms is None: seen_ms = int((time.time() - t0) * 1000)
            if seen_ms is not None and time.time() - t0 > 2.5: break
            pg.wait_for_timeout(50)
        bar = pg.evaluate("(document.getElementById('stale-bar') || {}).textContent || ''")
        check(f"信号很差、{label}：{seen_ms} ms 显示出库存（要求 2.5 秒内；以前要 5 秒以上，等云端的部分最长 10 秒）", seen_ms is not None and seen_ms < 2500)
        check(f"信号很差、{label}：显示出来的就是读完的数字 {FINAL}", partial == {FINAL}, str(partial))
        if want_bar: check(f"{label}、还没对上：标题下写明「现在显示的是这台手机 … 存的数据」", "现在显示的是这台手机" in bar and "存的数据" in bar, bar)
        else: check(f"{label}：不显示「还没对上」那一行（刚对过，不吓人）", not bar, bar)
        ctx.close(); HANG["on"] = False

print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
