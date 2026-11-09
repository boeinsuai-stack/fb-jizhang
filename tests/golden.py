"""标准答案采集：用某一版 App 的计算代码，在一份数据上算出所有关键数字，存成 JSON。
v2 验收 = 旧版在真实数据上算出的数字，v2 在迁移后的数据上必须一分不差。
用法：python3 tests/golden.py <public 目录> <数据 fixture.json> <输出.json>
注意：真实数据和输出里有客户名、金额，**不要放进仓库**（公开仓库），放在仓库外面。
做法：测试服务器把 index.html 末尾临时加一行，把计算函数借出来（window.__GM），业务逻辑一个字不改。"""
import os, functools, http.server, json, sys, threading, pathlib
from playwright.sync_api import sync_playwright

PUB = pathlib.Path(sys.argv[1]).resolve()
FIX = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf8"))
OUT = pathlib.Path(sys.argv[3])
MOCK = (pathlib.Path(__file__).resolve().parent / "mockfb.js").read_text(encoding="utf8")
EXPOSE = """
window.__GM = { S, derive, finBook, stockUnitCosts, reservedQty, pickups, resvAlloc, partnerNames, ptBal, ledgerOf, ledgerNet, customerBook, oSids,
  poOweAmt, openPOs, openXfers, xferNet, partnerItems, pendingPicks, avgCost, orderTotal, isReserved };
})();"""


class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/index.html"):
            src = (PUB / "index.html").read_text(encoding="utf8")
            i = src.rindex("})();")  # 最外层那个函数的结尾
            body = (src[:i] + EXPOSE + src[i + 5:]).encode("utf8")
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            return
        return super().do_GET()


COLLECT = r"""() => {
  const G = window.__GM, r2 = (n) => Math.round(n * 100) / 100;
  // 订单、支出等对象只记 id；数字保留
  const slim = (v) => JSON.parse(JSON.stringify(v, (k, x) => (x && typeof x === "object" && !Array.isArray(x) && typeof x.id === "string" && k !== "" ? "#" + x.id : x)));
  const F = G.finBook(() => true);
  const days = {};
  for (const d of F.list) {
    const o = {};
    for (const k of ["n", "qty", "cqty", "costAll", "goods", "fee", "rev", "cash", "cost", "gross", "opex", "net", "buy", "pick", "miss", "unk", "shrink"]) o[k] = d[k];
    o.orders = Object.fromEntries(d.orders.map((x) => [x.o.id, { qty: x.b.qty, goods: x.b.goods, fee: x.b.fee, rev: x.b.rev, cost: x.b.cost, gross: x.b.gross }]));
    o.shr = d.shr.map((x) => ({ sku: x.sku, qty: x.qty, cost: x.cost }));
    days[d.date] = o;
  }
  const st = {}; const D = G.derive(); for (const k of Object.keys(D.st).sort()) st[k] = D.st[k];
  const partners = {};
  for (const w of G.partnerNames()) {
    const L = G.ledgerOf(w);
    partners[w] = { bal: G.ptBal(w), net: G.ledgerNet(w), openXfers: G.openXfers(w).map((t) => t.id).sort(), openPOs: G.openPOs(w).map((p) => p.id).sort(),
      items: slim(G.partnerItems(w)), pending: slim(G.pendingPicks(w)), ledger: L ? slim(L) : null };
  }
  const settled = {}; for (const o of G.S.orders) settled[o.id] = G.oSids(o);
  const cust = G.customerBook ? slim(G.customerBook()) : null;
  return { counts: Object.fromEntries(Object.entries(G.S).filter(([, v]) => Array.isArray(v)).map(([k, v]) => [k, v.length])),
    st, uc: G.stockUnitCosts(), T: F.T, cats: F.cats, days, partners, reserved: G.reservedQty(), pickups: slim(G.pickups()), resvAlloc: slim(G.resvAlloc()), settled, cust };
}"""

s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=str(PUB)))
threading.Thread(target=s.serve_forever, daemon=True).start()
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    ctx = b.new_context(service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.add_init_script("window.__SEED=" + json.dumps(FIX, ensure_ascii=False) + ";")
    pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
    pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
    pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
    pg.goto(f"http://127.0.0.1:{s.server_address[1]}/index.html")
    pg.wait_for_function("window.__GM && window.__GM.S.orders.length > 0 && window.__GM.S.items.length > 0", timeout=20000)
    pg.wait_for_timeout(1500)
    res = pg.evaluate(COLLECT)
    b.close()
OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf8")
print("条数:", res["counts"])
print("总计:", res["T"])
print("合伙人:", {w: (v["bal"], v["net"]) for w, v in res["partners"].items()})
print("库存口味数:", len(res["st"]), " 页面报错:", errs[:3])
