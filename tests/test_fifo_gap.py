"""成本账不再「漂」：卖出那天账上的货不够（补记、撤销让卖出排到了进货前面）→ 不够的先欠着，下一批到货补上、按那批的价算。
以前当场按口味默认成本算，后到的那批永远剩在成本账里：利润少算一根的成本，库存货值多一根。
纯计算，编的数据（旧结构），GitHub 上也跑。运行：python3 tests/test_fifo_gap.py"""
import os, sys, json, datetime, functools, http.server, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
EXPOSE = "\nwindow.__GM = { S, derive, finBook, fifoBook, stockUnitCosts };\n})();"
day = lambda n: (datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date() - datetime.timedelta(days=n)).isoformat()
item = lambda sku, en, cost: (sku, {"sku": sku, "series": "Bar Pro", "variant": en, "name": en, "price_aud": 60, "cost_aud": cost, "status": "在售"})
def order(oid, d, sku, qty):
    return {oid: {"status": "paid", "date": d, "at": d + "T03:00:00Z", "lines": [{"sku": sku, "name": sku, "qty": qty, "unit_price": 60}], "delivery_fee": 0, "note": "", "payment": "现金"}}, \
           {oid + "-" + sku: {"type": "out", "sku": sku, "name": sku, "qty": qty, "date": d, "at": d + "T03:00:00Z", "order_id": oid}}
def stock_in(mid, d, sku, qty, cost):
    return {mid: {"type": "in", "sku": sku, "name": sku, "qty": qty, "cost": cost, "date": d, "at": d + "T01:00:00Z", "note": "进货"}}
O, M = {}, {}
def add(pair): O.update(pair[0]); M.update(pair[1])
# XF-01（默认成本 30）：4 天前卖 1 根，那天账上没货；3 天前才记进货 2 根 @20；今天再卖 1 根
add(order("o-a1", day(4), "XF-01", 1)); M.update(stock_in("in-a", day(3), "XF-01", 2, 40)); add(order("o-a2", day(0), "XF-01", 1))
# XF-02（默认成本 30）：卖 1 根，从来没有进货记录 → 只能按默认成本
add(order("o-b1", day(2), "XF-02", 1))
# XF-03（默认成本 30）：正常的先进先出：先进 1 根 @10，再进 1 根 @25，卖 2 根 → 10 + 25；再进 1 根 @28 还在手上
M.update(stock_in("in-c1", day(5), "XF-03", 1, 10)); M.update(stock_in("in-c2", day(4), "XF-03", 1, 25)); add(order("o-c1", day(3), "XF-03", 2)); M.update(stock_in("in-c3", day(1), "XF-03", 1, 28))
# XF-04（默认成本 30）：卖 3 根时账上只有 1 根 @12；后来到 1 根 @15、再到 2 根 @18 → 12 + 15 + 18，剩 1 根 @18
M.update(stock_in("in-d1", day(6), "XF-04", 1, 12)); add(order("o-d1", day(5), "XF-04", 3)); M.update(stock_in("in-d2", day(4), "XF-04", 1, 15)); M.update(stock_in("in-d3", day(2), "XF-04", 2, 36))
SEED = {"items": dict([item("XF-01", "A", 30), item("XF-02", "B", 30), item("XF-03", "C", 30), item("XF-04", "D", 30)]), "movements": M, "orders": O,
        "expenses": {}, "transfers": {}, "settlements": {}, "purchases": {}, "customers": {}, "followups": {}, "meta": {"backfill": {"done": True}}}

class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/index.html"):
            src = (PUB / "index.html").read_text(encoding="utf8"); i = src.rindex("})();"); b = (src[:i] + EXPOSE + src[i + 5:]).encode("utf8")
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        return super().do_GET()
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=str(PUB))); threading.Thread(target=srv.serve_forever, daemon=True).start()
results = []
def check(name, ok, extra=""):
    results.append(ok); print(("✅ " if ok else "❌ ") + name + (("  " + str(extra)[:200]) if extra and not ok else ""))

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    ctx = br.new_context(service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
    ctx.add_init_script("window.__SEED = " + json.dumps(SEED, ensure_ascii=False) + ";")
    pg = ctx.new_page(); pg.on("pageerror", lambda e: (print("   页面报错：", e), results.append(False)))
    pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
    pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
    pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html"); pg.wait_for_function("window.__GM && window.__GM.S.loaded && window.__GM.S.orders.length === 5", timeout=15000); pg.wait_for_timeout(400)
    R = pg.evaluate("""() => { const G = window.__GM, F = G.finBook(() => true), B = G.fifoBook(), st = G.derive().st, cost = {};
      for (const d of F.list) for (const x of d.orders) cost[x.o.id] = x.b.cost;
      return { cost, T: F.T, unitNow: B.unitNow, st }; }""")
    c = R["cost"]
    check("卖出早于进货：按后来那批的价 20（以前按默认成本 30）", c["o-a1"] == 20, c["o-a1"])
    check("之后再卖 1 根：也是 20，账上不剩「多出来的一根」", c["o-a2"] == 20 and R["st"].get("XF-01", 0) == 0 and "XF-01" not in R["unitNow"], (c["o-a2"], R["st"].get("XF-01"), R["unitNow"].get("XF-01")))
    check("从来没有进货记录的：还是按口味默认成本 30", c["o-b1"] == 30, c["o-b1"])
    check("正常的先进先出不变：10 + 25 = 35，手上那根 @28", c["o-c1"] == 35 and R["unitNow"].get("XF-03") == 28, (c["o-c1"], R["unitNow"].get("XF-03")))
    check("卖 3 根账上只有 1 根：12 + 15 + 18 = 45，手上剩 1 根 @18", c["o-d1"] == 45 and R["st"].get("XF-04") == 1 and R["unitNow"].get("XF-04") == 18, (c["o-d1"], R["unitNow"].get("XF-04")))
    cin = sum(m["cost"] for m in M.values() if m["type"] == "in"); onhand = sum(R["st"].get(k, 0) * v for k, v in R["unitNow"].items())
    check("成本守恒：进货 %g = 卖出成本 %g + 手上 %g − 没进货记录按默认成本顶的 30" % (cin, R["T"]["cost"], onhand), abs(cin - (R["T"]["cost"] + onhand - 30)) < 0.005)
    br.close()

print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
