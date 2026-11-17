"""打开先用上次存的数据（2026-11-18 Bowen：每次打开都要白屏 3–4 秒才能复制口味）。
- 数据读完后，页面要用的那份存进 localStorage（fb-snap:<uid>）
- 下次打开不等 Firebase：马上显示上次的数字、能复制口味；Firebase 读完后整份换成真的（一次换完）
- 换之前不让保存（免得按旧数据记账）；「复制口味」在标题右边，只在库存页出现
用编出来的小数据，旧结构 / 新结构各一遍（GitHub 上也跑）。运行：python3 tests/test_snapshot.py"""
import os, sys, json, time, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
results = []
def check(name, ok, extra=""):
    results.append(ok); print(("✅ " if ok else "❌ ") + name + (("  " + str(extra)) if extra and not ok else ""))

item = lambda sku, en, cn: (sku, {"sku": sku, "series": "One", "variant": en, "name": cn, "price_aud": 30, "cost_aud": 20, "status": "在售"})
def v1(apple_in):
    return {"items": dict([item("XF-01", "Apple", "苹果"), item("XF-02", "Mango", "芒果")]),
            "movements": {"in-1": {"type": "in", "sku": "XF-01", "name": "苹果", "qty": apple_in, "date": TODAY, "at": TODAY + "T01:00:00Z", "note": "进货"},
                          "in-2": {"type": "in", "sku": "XF-02", "name": "芒果", "qty": 2, "date": TODAY, "at": TODAY + "T01:00:00Z", "note": "进货"},
                          "o1-XF-01": {"type": "out", "sku": "XF-01", "name": "苹果", "qty": 1, "date": TODAY, "at": TODAY + "T02:00:00Z", "order_id": "o1", "note": "卖出"}},
            "orders": {"o1": {"status": "paid", "date": TODAY, "at": TODAY + "T02:00:00Z", "customer": "Valentine", "payment": "现金", "lines": [{"sku": "XF-01", "name": "苹果", "qty": 1, "unit_price": 30}], "delivery_fee": 0, "note": ""}},
            "expenses": {}, "purchases": {}, "transfers": {}, "settlements": {}, "customers": {}, "followups": {}}
tmp = pathlib.Path(tempfile.mkdtemp())
def v2(d):
    (tmp / "a.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf8")
    subprocess.run(["node", str(ROOT / "v2_seed.js"), str(tmp / "a.json"), str(tmp / "b.json")], check=True, capture_output=True)
    x = json.loads((tmp / "b.json").read_text(encoding="utf8")); x["meta"] = {"schema": {"version": 2}, "backfill": {"done": True}}; return x
A, B = v1(6), v1(9)  # 第一次打开：苹果 6−1=5、芒果 2 → 能卖 7；另一台手机后来又进了 3 根苹果 → 能卖 10

class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Q, directory=str(PUB)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/index.html"
TOT = "(document.getElementById('sb-total') || {}).textContent || ''"

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    for mode in ("旧结构", "新结构"):
        s1 = v2(A) if mode == "新结构" else dict(A, meta={"backfill": {"done": True}})
        s2 = v2(B) if mode == "新结构" else dict(B, meta={"backfill": {"done": True}})
        cols = ["items", "customers", "followups"] + (["v2_orders", "v2_movements", "v2_purchases", "v2_transfers", "v2_settlements", "v2_expenses", "v2_batches"] if mode == "新结构" else ["orders", "movements", "expenses", "purchases", "settlements", "transfers"])
        ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN", permissions=["clipboard-read", "clipboard-write"])
        # 第一次打开正常；第二次（sessionStorage 记着）云端已经变了、而且每类记录都要 2.5 秒才读出来（手机上 Firebase 启动慢）
        ctx.add_init_script("""(() => { const n = +(sessionStorage.getItem('n') || 0) + 1; sessionStorage.setItem('n', n);
          localStorage.setItem('fb-last-user', JSON.stringify({ uid: 'u-test', email: '', displayName: '测试' }));""" +
          (f"localStorage.setItem('fb-schema', JSON.stringify({{ version: 2 }}));" if mode == "新结构" else "") +
          f"window.__SEED = n === 1 ? {json.dumps(s1, ensure_ascii=False)} : {json.dumps(s2, ensure_ascii=False)};"
          f"window.__MOCK_SLOW = n === 1 ? {{}} : n === 2 ? {json.dumps({c: 2500 for c in cols})} : {json.dumps({c: 5000 for c in cols})}; }})();")  # 第三次起慢 5 秒：机器忙的时候也来得及查
        pg = ctx.new_page(); pg.on("pageerror", lambda e: (print("   页面报错：", e), results.append(False)))
        pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
        pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
        pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        print("== " + mode)
        pg.goto(URL); pg.wait_for_function(TOT + " === '7'", timeout=10000)
        check("「复制口味」在标题右边，一打开就看得到（不用往下找）", pg.is_visible("header.top #inv-copy") and pg.evaluate("document.getElementById('inv-copy').getBoundingClientRect().top") < 120,
              pg.evaluate("document.getElementById('inv-copy').getBoundingClientRect().top"))
        check("快速下单下面那个旧的复制按钮拿掉了（只有一个）", pg.locator("button", has_text="复制口味").count() == 1)
        pg.evaluate("location.hash = '#finance'"); pg.wait_for_timeout(200)
        check("换到财务页：复制口味按钮不出现", pg.is_hidden("#inv-copy"))
        pg.evaluate("location.hash = '#inventory'"); pg.wait_for_timeout(200)
        pg.wait_for_function("Object.keys(localStorage).some((k) => k === 'fb-snap:u-test')", timeout=5000)
        snap = pg.evaluate("JSON.parse(localStorage.getItem('fb-snap:u-test'))")
        check("读完 2 秒后存了一份（口味、订单、流水……都在）", snap and len(snap["S"]["items"]) == 2 and len(snap["S"]["orders"]) == 1 and snap["schema"] == (2 if mode == "新结构" else 1), snap and {k: len(v) for k, v in snap["S"].items()})

        # 第二次打开：Firebase 要 2.5 秒才读出来
        t0 = time.time(); pg.reload(wait_until="commit"); first, seen = None, []
        while time.time() - t0 < 6:
            try: v = pg.evaluate(TOT)
            except Exception: continue
            if v not in ("", "–"):
                if first is None: first = int((time.time() - t0) * 1000)
                if not seen or seen[-1] != v: seen.append(v)
            if seen and seen[-1] == "10": break
            pg.wait_for_timeout(30)
        check(f"再打开：{first} ms 就显示上次的数字（不等 Firebase 的 2.5 秒）", first is not None and first < 1500, first)
        check("先显示上次的 7，Firebase 读完一次换成真的 10（中间没有一半的数字）", seen == ["7", "10"], seen)

        t0 = time.time(); pg.reload(wait_until="commit"); pg.wait_for_function(TOT + " === '10'", timeout=3000)
        check("先显示的是上次存的（这时还在等 Firebase）", pg.evaluate("window.__fbSnapOn && window.__fbSnapOn()") is True)
        pg.click("#inv-copy"); pg.wait_for_timeout(250)
        clip = pg.evaluate("navigator.clipboard.readText()")
        check("这时点「复制口味」：马上复制出来（不再说「还没读完」）", "Apple" in clip and "Mango" in clip, clip[:80])
        pg.click("#inv-in"); pg.wait_for_timeout(300)
        if pg.is_visible("#sheet"):
            pg.click("#sheet-save"); pg.wait_for_timeout(300)
            err = pg.inner_text("#sheet-err") if pg.is_visible("#sheet-err") else ""
            check("这时保存：拦住，写明一两秒后再点", "一两秒后再点保存" in err, err)
            pg.click("#sheet-close"); pg.wait_for_timeout(200)
        else: check("这时保存：拦住（进货弹窗没打开）", False)
        pg.wait_for_function("!window.__fbSnapOn()", timeout=9000)
        check(f"Firebase 读完后换成真的（{int((time.time() - t0) * 1000)} ms）", pg.evaluate(TOT) == "10")

        # 存的那份对不上（数据结构换了）就不用
        pg.wait_for_timeout(2500)  # 等这次读完后的那份存完
        pg.evaluate("localStorage.setItem('fb-snap:u-test', JSON.stringify(Object.assign(JSON.parse(localStorage.getItem('fb-snap:u-test')), { schema: %d })))" % (1 if mode == "新结构" else 2))
        pg.reload(wait_until="commit"); pg.wait_for_timeout(800)
        check("存的那份是另一种数据结构的：不用，照旧等 Firebase", pg.evaluate(TOT) in ("", "–") and not pg.evaluate("window.__fbSnapOn && window.__fbSnapOn()"))
        ctx.close()
    br.close()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
