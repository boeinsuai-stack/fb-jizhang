"""迁移流程端到端：旧结构的真实数据 → 设置页「检查迁移」→「确认迁移」→ 自动刷新成新结构（数字跟以前一样）
→ 在新结构下记一笔卖出 → 另一台手机（还开着旧版）往旧结构写一笔 → 「补进新结构」→ 「退回旧结构」→ 自动刷新回旧结构，
迁移后记的账都在、数字跟退回前一样。
用法：python3 tests/test_v2_migrate.py <旧 fixture.json>（真实数据放仓库外面）"""
import os, datetime, functools, hashlib, http.server, json, sys, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
FIX = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf8"))
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
EXPOSE = "\nwindow.__GM = { S, derive, finBook, partnerNames, ledgerNet };\n})();"
OWNER = hashlib.sha256(b"test@example.com").hexdigest()


class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def send_text(self, body, ct):
        b = body.encode("utf8"); self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            src = (PUB / "index.html").read_text(encoding="utf8"); i = src.rindex("})();"); return self.send_text(src[:i] + EXPOSE + src[i + 5:], "text/html; charset=utf-8")
        if path == "/firebase-config.js":  # 测试账号 = 店主
            src = (PUB / "firebase-config.js").read_text(encoding="utf8")
            import re; src = re.sub(r"owners:\s*\[[^\]]*\]", f'owners: ["{OWNER}"]', src); return self.send_text(src, "text/javascript")
        return super().do_GET()


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=str(PUB)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/index.html"
results = []
def check(name, ok, extra=""):
    results.append(ok); print(("✅ " if ok else "❌ ") + name + (("  " + extra) if extra else ""))

NUMS = """() => { const G = window.__GM, D = G.derive(), F = G.finBook(() => true), o = { stock: Object.values(D.st).reduce((a, v) => a + v, 0), n: F.T.n, rev: F.T.rev, cost: F.T.cost, net: F.T.net, buy: F.T.buy };
  for (const w of G.partnerNames()) o["p:" + w] = G.ledgerNet(w); return o; }"""


def ready(pg):
    pg.wait_for_function("window.__GM && window.__GM.S.orders.length > 50 && window.__GM.S.moves.length > 50", timeout=20000); pg.wait_for_timeout(800)


with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: print("   页面报错：", e))
    pg.add_init_script("window.__MOCK_PERSIST = true; window.__SEED = " + json.dumps(FIX, ensure_ascii=False) + ";")
    pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
    pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
    pg.goto(URL); ready(pg)
    n0 = pg.evaluate(NUMS)
    check("开始是旧结构", not pg.evaluate("!!window.__fbV2store"))

    # 检查迁移
    pg.evaluate("location.hash = '#settings'"); pg.wait_for_selector("#mig-sec:not([hidden])", timeout=8000)
    pg.click("#mig-check"); pg.wait_for_timeout(500)
    out = pg.inner_text("#mig-out")
    check("检查迁移：全部一致", "全部一致" in out, out.split("\n")[0])
    print("   " + [l for l in out.split("\n") if "存储" in l][0][:120])
    pg.screenshot(path=str(ROOT / "shots" / "mig-1-检查.png"), full_page=True)
    old_orders = pg.evaluate("Object.keys(__server('orders')).length")

    # 确认迁移（要按两下）→ 自动刷新成新结构
    pg.click("#mig-go"); pg.click("#mig-go")
    pg.wait_for_function("window.__fbV2store", timeout=15000); ready(pg)
    check("确认迁移后自动刷新成新结构", pg.evaluate("!!window.__fbV2store"))
    n1 = pg.evaluate(NUMS)
    check("新结构下：库存、单数、收入、成本、净赚、进货、合伙人账 跟迁移前一样", n1 == n0, "" if n1 == n0 else f"{n0} → {n1}")
    check("旧集合一条没动", pg.evaluate("Object.keys(__server('orders')).length") == old_orders)
    srv_m = pg.evaluate("Object.keys(__server('v2_movements')).length"); srv_e = pg.evaluate("Object.keys(__server('v2_expenses')).length")
    check(f"新结构只存了 {srv_m} 条流水、{srv_e} 条支出（都是独立的事）", srv_m < 40 and srv_e < 5)

    # 新结构下记一笔卖出（有货的口味）
    have = pg.evaluate("""() => { const st = window.__GM.derive().st; const i = window.__GM.S.items.find((i) => i.status === "在售" && i.variant && st[i.sku] >= 2); return i && i.variant; }""")
    pg.evaluate("location.hash = '#finance'"); pg.wait_for_timeout(300); pg.click("#fin-sale")
    pg.fill("#f-skuq-0", have); pg.press("#f-skuq-0", "Enter"); pg.select_option("#f-pay", "现金")
    pg.evaluate("() => document.activeElement && document.activeElement.blur()"); pg.click("#sheet-save"); pg.wait_for_selector("#sheet", state="hidden", timeout=5000)
    pg.wait_for_timeout(500)
    new_oid = pg.evaluate("window.__GM.S.orders.map((o) => o.id).sort().pop()")
    check("新结构下记账：订单只存一条源头，出库是现算的", pg.evaluate(f"!!__server('v2_orders')['{new_oid}'] && !__server('v2_movements')['{new_oid}-' + window.__GM.S.orders.find(o => o.id === '{new_oid}').lines[0].sku] && window.__GM.S.moves.some(m => m.order_id === '{new_oid}')"))

    # 另一台手机还开着旧版：往旧结构写了一笔支出 → 刷新后提示，「补进新结构」
    pg.evaluate("""() => __remoteWrite("expenses", "e-20261110-late01", { date: "2026-11-10", amount: 9.5, category: "油费", note: "旧版手机记的", by_at: new Date().toISOString() })""")
    pg.reload(); ready(pg)
    pg.evaluate("location.hash = '#settings'"); pg.wait_for_timeout(1500)
    check("迁移后旧结构里的新改动：有提示", pg.is_visible("#mig-late") and "1 条" in pg.inner_text("#mig-status"), pg.inner_text("#mig-status")[-60:])
    pg.click("#mig-late"); pg.wait_for_timeout(800)
    check("补进新结构后，这笔支出在新结构里", pg.evaluate("window.__GM.S.expenses.some((x) => x.id === 'e-20261110-late01') && !!__server('v2_expenses')['e-20261110-late01']"))
    n2 = pg.evaluate(NUMS)

    # 退回旧结构（按两下）→ 自动刷新回旧结构，迁移后记的账都在
    pg.evaluate("location.hash = '#settings'"); pg.wait_for_timeout(300)
    pg.click("#mig-back"); pg.click("#mig-back")
    pg.wait_for_function("!window.__fbV2store && window.__GM && window.__GM.S.orders.length > 50", timeout=15000); ready(pg)
    check("退回后是旧结构", not pg.evaluate("!!window.__fbV2store"))
    n3 = pg.evaluate(NUMS)
    check("退回后数字跟退回前一样（迁移后记的账都在）", n3 == n2, "" if n3 == n2 else f"{n2} → {n3}")
    check("迁移后记的卖出写回了旧集合（订单 + 出库流水）", pg.evaluate(f"!!__server('orders')['{new_oid}'] && Object.keys(__server('movements')).some(k => k.startsWith('{new_oid}-') && !__server('movements')[k]._deleted)"))
    br.close()

print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
