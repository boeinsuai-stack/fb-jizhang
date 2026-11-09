"""读不到数据时不能「当成没有」：数据结构版本、迁移、迁移后旧结构里的改动。用编出来的小数据，不要真实数据（GitHub 上也跑）。
假 Firebase 照真 SDK：没网时读不在手机本地的记录会报错，指定问云端（source:"server"）没网也报错。
运行：python3 tests/test_v2_failsafe.py"""
import os, datetime, functools, hashlib, http.server, json, re, subprocess, sys, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
OWNER = hashlib.sha256(b"test@example.com").hexdigest()
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
MIGRATED = TODAY + "T00:00:00.000Z"

item = lambda sku, en, cn: (sku, {"sku": sku, "series": "One", "variant": en, "name": cn, "price_aud": 30, "cost_aud": 20, "status": "在售"})
V1 = {
    "items": dict([item("XF-01", "Apple", "苹果"), item("XF-02", "Mango", "芒果")]),
    "movements": {
        "in-1": {"type": "in", "sku": "XF-01", "name": "苹果", "qty": 6, "date": TODAY, "at": TODAY + "T01:00:00Z", "note": "进货"},
        "in-2": {"type": "in", "sku": "XF-02", "name": "芒果", "qty": 4, "date": TODAY, "at": TODAY + "T01:00:00Z", "note": "进货"},
        "o1-XF-01": {"type": "out", "sku": "XF-01", "name": "苹果", "qty": 1, "date": TODAY, "at": TODAY + "T02:00:00Z", "order_id": "o1", "note": "卖出 · Cat"},
    },
    "orders": {"o1": {"status": "paid", "date": TODAY, "at": TODAY + "T02:00:00Z", "customer": "Cat", "payment": "现金",
                      "lines": [{"sku": "XF-01", "name": "苹果", "qty": 1, "unit_price": 30}], "delivery_fee": 0, "note": ""}},
    "expenses": {}, "purchases": {}, "transfers": {}, "settlements": {}, "customers": {}, "followups": {},
    "meta": {"backfill": {"done": True}},
}
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "v1.json").write_text(json.dumps(V1, ensure_ascii=False), encoding="utf8")
subprocess.run(["node", str(ROOT / "v2_seed.js"), str(tmp / "v1.json"), str(tmp / "v2.json")], check=True, capture_output=True)
V2 = json.loads((tmp / "v2.json").read_text(encoding="utf8"))
V2["meta"] = {"schema": {"version": 2, "migrated_at": MIGRATED}, "backfill": {"done": True}}
V2_NO_META = {k: v for k, v in V2.items() if k != "meta"}  # 手机本地数据库里还没有 meta/schema


class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.split("?")[0] == "/firebase-config.js":  # 测试账号 = 店主
            b = re.sub(r"owners:\s*\[[^\]]*\]", f'owners: ["{OWNER}"]', (PUB / "firebase-config.js").read_text(encoding="utf8")).encode("utf8")
            self.send_response(200); self.send_header("Content-Type", "text/javascript"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        return super().do_GET()


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=str(PUB)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/index.html"
results = []
def check(name, ok, extra=""):
    results.append(ok); print(("✅ " if ok else "❌ ") + name + (("  " + extra) if extra else ""))


def open_app(br, seed, offline, cache=None, remember=None):
    ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
    init = f"window.__MOCK_OFFLINE={json.dumps(offline)}; window.__SEED={json.dumps(seed, ensure_ascii=False)};"
    if cache is not None: init += f"window.__CACHE_SEED={json.dumps(cache, ensure_ascii=False)};"
    if remember is not None: init += f"localStorage.setItem('fb-schema', {json.dumps(json.dumps(remember))});"
    ctx.add_init_script(init)
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: print("   页面报错：", e))
    pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
    pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
    pg.goto(URL)
    pg.wait_for_selector("#fin-sale:not([disabled])", state="attached", timeout=10000); pg.wait_for_timeout(600)
    return ctx, pg


def sell(pg, flavour):
    pg.evaluate("location.hash = '#finance'"); pg.wait_for_timeout(300); pg.click("#fin-sale")
    pg.fill("#f-skuq-0", flavour); pg.press("#f-skuq-0", "Enter"); pg.select_option("#f-pay", "现金")
    pg.click("#sheet-save"); pg.wait_for_selector("#sheet", state="hidden", timeout=4000); pg.wait_for_timeout(400)


is_v2 = "!!window.__fbV2store"

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])

    # 1. 联网打开：云端是新结构 → 新结构，并且这台手机记住了
    ctx, pg = open_app(br, V2, offline=False)
    check("联网打开：用新结构", pg.evaluate(is_v2))
    check("联网打开：这台手机记住了「新结构」", (json.loads(pg.evaluate("localStorage.getItem('fb-schema')") or "{}")).get("version") == 2)
    ctx.close()

    # 2. 没网打开、手机本地数据库里没有 meta/schema，但这台手机上次看到的是新结构 → 照样用新结构，记的账进新结构
    #    （以前读不到就当旧结构：账记进旧集合，联网后新结构里看不见）
    ctx, pg = open_app(br, V2, offline=True, cache=V2_NO_META, remember={"version": 2, "migrated_at": MIGRATED})
    check("没网 + 读不到版本 + 记得是新结构：用新结构", pg.evaluate(is_v2))
    o0 = set(pg.evaluate("Object.keys(__dump('v2_orders'))"))
    sell(pg, "Mango")
    new = [k for k in pg.evaluate("Object.keys(__dump('v2_orders'))") if k not in o0]
    check("没网记的卖出进了新结构（v2_orders），旧集合没有", len(new) == 1 and not pg.evaluate("Object.keys(__dump('orders')).length"), str(new))

    # 3. 同一台手机（店主）：设置页查「迁移后旧结构里的新改动」—— 没网问不到云端，要说出来，不能当成「没有」
    pg.evaluate("location.hash = '#settings'"); pg.wait_for_timeout(800)
    st = pg.inner_text("#mig-status")
    check("没网时查不了旧结构改动：设置页写明「还没能检查」", "还没能检查" in st, st[-50:])
    ctx.close()

    # 4. 没网、什么都不记得 → 旧结构（迁移前的默认），照样能用
    ctx, pg = open_app(br, V1, offline=True)
    check("没网 + 从没看到过版本：用旧结构", not pg.evaluate(is_v2))

    # 5. 没网时「确认迁移」：拒绝，不写 meta/schema（以前读不到旧的新结构记录就当成没有）
    pg.evaluate("location.hash = '#settings'"); pg.wait_for_selector("#mig-sec:not([hidden])", timeout=8000)
    pg.click("#mig-check"); pg.wait_for_timeout(400)
    check("没网时也能「检查迁移」（只读本地、不写）", "全部一致" in pg.inner_text("#mig-out"), pg.inner_text("#mig-out")[:40])
    pg.click("#mig-go"); pg.click("#mig-go"); pg.wait_for_timeout(800)
    toast = pg.evaluate("[...document.querySelectorAll('.toast')].map((t) => t.textContent).join('/')")
    check("没网时「确认迁移」：提示要联网", "要联网" in toast, toast[:60])
    check("没网时「确认迁移」：没写新结构标记、没写 v2 集合", not pg.evaluate("Object.keys(__dump('meta')).includes('schema') || Object.keys(__dump('v2_orders')).length > 0") and not pg.evaluate(is_v2))
    ctx.close()
    br.close()

print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
