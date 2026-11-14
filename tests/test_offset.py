"""合伙人对账「互抵」：同一个合伙人、同一个系列，调入（随单拿的 + 往来他给我的）和调出（他拿走的）一根抵一根，不管单价。
抵掉的根数 = 两边小的那个，剩下的照原价。旧结构、新结构各跑一遍；用编出来的小数据，GitHub 上也跑。
  Ali：随单拿 3 根 @60 进，他拿走 2 根 @55 出 → 抵 2 根，剩 1 根进 = 60
  Bar Pro：往来他给 1 根 @36 进，他拿走 4 根 @30 出 → 抵 1 根，剩 3 根出 = 90
  → 应收 30（不抵的算法是应收 14）
运行：python3 tests/test_offset.py"""
import os, datetime, functools, http.server, json, subprocess, sys, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
EXPOSE = "\nwindow.__GM = { S, derive, ledgerNet, xferEff, statementText, partnerItems, openXfers, openPOs, pendingPicks };\n})();"
D = (datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date() - datetime.timedelta(days=3)).isoformat()
W = "合伙人甲"

item = lambda sku, ser, en: (sku, {"sku": sku, "series": ser, "variant": en, "name": en, "price_aud": 70, "cost_aud": 30, "status": "在售"})
mv = lambda **k: dict({"date": D, "at": D + "T01:00:00Z"}, **k)
O = "o-" + D.replace("-", "") + "-a1"
V1 = {
    "items": dict([item("XF-01", "Bar Pro", "Banana Buzz"), item("XF-02", "Bar Pro", "Grape"), item("XF-03", "Ali", "Cool Mint"), item("XF-04", "Ali", "FTP")]),
    "movements": {
        "in-1": mv(type="in", sku="XF-01", name="Banana Buzz", qty=10, cost=300, note="进货"),
        "in-4": mv(type="in", sku="XF-04", name="FTP", qty=5, cost=250, note="进货"),
        # 随单找合伙人甲拿 3 根 Ali @60（卖给客人）
        O + "-pick-XF-03": mv(type="in", sku="XF-03", name="Cool Mint", qty=3, cost=180, order_id=O, batch_id=O + "-pick", partner=W, note="按单向合伙人拿货"),
        O + "-XF-03": mv(type="out", sku="XF-03", name="Cool Mint", qty=3, order_id=O, note="卖出"),
        # 往来：他拿走 Ali 2 @55、Bar Pro 4 @30；他给我 Bar Pro 1 @36
        "t-a-out-XF-04": mv(type="adjust", sku="XF-04", name="FTP", qty=-2, transfer_id="t-a", note="合伙人往来：给 " + W),
        "t-a-out-XF-01": mv(type="adjust", sku="XF-01", name="Banana Buzz", qty=-4, transfer_id="t-a", note="合伙人往来：给 " + W),
        "t-b-in-XF-02": mv(type="in", sku="XF-02", name="Grape", qty=1, cost=36, transfer_id="t-b", note="合伙人往来：" + W + " 给的"),
    },
    "orders": {O: {"date": D, "at": D + "T02:00:00Z", "status": "sold", "customer": "客一", "payment": "现金", "lines": [{"sku": "XF-03", "name": "Cool Mint", "qty": 3, "unit_price": 70}], "total": 210, "pick_from": W, "partner_settlement_id": None}},
    "expenses": {O + "-pick-cost": {"category": "进货成本", "amount": 180, "date": D, "at": D + "T02:00:00Z", "batch_id": O + "-pick", "note": "按单拿货 Ali ×3"}},
    "transfers": {
        "t-a": {"date": D, "at": D + "T03:00:00Z", "partner": W, "out": [{"sku": "XF-04", "name": "FTP", "qty": 2, "unit": 55}, {"sku": "XF-01", "name": "Banana Buzz", "qty": 4, "unit": 30}], "in": [], "note": ""},
        "t-b": {"date": D, "at": D + "T04:00:00Z", "partner": W, "out": [], "in": [{"sku": "XF-02", "name": "Grape", "qty": 1, "unit": 36}], "note": ""},
    },
    "settlements": {}, "purchases": {}, "customers": {}, "followups": {},
    "meta": {"backfill": {"done": True}},
}
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "v1.json").write_text(json.dumps(V1, ensure_ascii=False), encoding="utf8")
subprocess.run(["node", str(ROOT / "v2_seed.js"), str(tmp / "v1.json"), str(tmp / "v2.json")], check=True, capture_output=True)
V2 = json.loads((tmp / "v2.json").read_text(encoding="utf8"))
V2["meta"] = {"schema": {"version": 2, "migrated_at": D + "T05:00:00.000Z"}, "backfill": {"done": True}}


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

SHOT = os.environ.get("SHOT")
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    for mode, seed in (("旧结构", V1), ("新结构", V2)):
        print("== " + mode)
        ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
        ctx.add_init_script("window.__SEED=" + json.dumps(seed, ensure_ascii=False) + ";")
        pg = ctx.new_page(); pg.on("pageerror", lambda e: print("   页面报错：", e))
        pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
        pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
        pg.goto(URL); pg.wait_for_function("window.__GM && window.__GM.S.transfers.length === 2 && window.__GM.S.orders.length === 1", timeout=15000); pg.wait_for_timeout(600)
        check("用的是" + mode, pg.evaluate("!!window.__fbV2store") == (mode == "新结构"))
        check("随单拿的货算进合伙人账", pg.evaluate(f"window.__GM.partnerItems('{W}').length") == 1)
        n = pg.evaluate(f"window.__GM.ledgerNet('{W}')")
        check("对账：Ali 抵 2 根、Bar Pro 抵 1 根 → 应收 30（不抵是 14）", n == -30, str(n))

        pg.evaluate("location.hash = '#partner'"); pg.wait_for_timeout(500)
        bal = pg.inner_text("#ptx-bal")
        check("合伙人页余额 = 对账单：应收 $30", "应收" in bal and "$30" in bal, bal.replace("\n", " "))
        pg.evaluate("location.hash = '#finance'"); pg.wait_for_timeout(500)
        ow = pg.inner_text("#f-owe")
        check("财务页应付行 = 对账单：应收 $30", "应收" in ow and "$30" in ow, ow.replace("\n", " "))

        pg.evaluate("location.hash = '#partner'"); pg.wait_for_timeout(400)
        pg.click(f'#ptx-bal [data-lg-open="{W}"]'); pg.wait_for_selector(".lg-sum", timeout=4000)
        sh = pg.inner_text("#sheet")
        rows = pg.evaluate("[...document.querySelectorAll('#sheet .lg-sr')].map((e) => e.innerText.replace(/\\s+/g, ' ').trim())")
        check("对账单「按系列算」Bar Pro：调入 1 · 调出 4 · 抵 1，还要结 调出 3 根 −$90", any("Bar Pro" in r and "调入 1 · 调出 4 · 抵 1" in r and "调出 还要结 3 根 −$90" in r for r in rows), str(rows))
        check("对账单「按系列算」Ali：调入 3 · 调出 2 · 抵 2，还要结 调入 1 根 +$60", any(r.startswith("Ali") and "调入 3 · 调出 2 · 抵 2" in r and "调入 还要结 1 根 +$60" in r for r in rows), str(rows))
        tot = pg.inner_text("#sheet .lg-tot").replace("\n", " ")
        check("合计：调入 +$60、调出 −$90、应收 $30", "+$60" in tot and "−$90" in tot and "应收 " + W in tot and "$30" in tot, tot)
        check("明细只记货（调入/调出下面不写钱）", pg.evaluate("[...document.querySelectorAll('#sheet .lg-sec')].filter((e) => /调入|调出/.test(e.querySelector('.lg-k').textContent)).every((e) => !e.querySelector('.lg-sh > b').textContent)"))
        if SHOT and mode == "新结构": pg.screenshot(path=SHOT + "-对账单.png", full_page=False)
        txt = pg.evaluate(f"window.__GM.statementText(window.__GM.partnerItems('{W}'), 'T', null, window.__GM.openXfers('{W}'), window.__GM.openPOs('{W}'), window.__GM.pendingPicks('{W}'))")
        check("复制发给他的文字：按系列算 + 合计应收 $30", "【按系列算" in txt and "Ali：调入 3 · 调出 2 · 抵 2 → 还要结 调入 1 根 $60" in txt and "Bar Pro：调入 1 · 调出 4 · 抵 1 → 还要结 调出 3 根 $90" in txt and "= 应收 " + W + " $30" in txt, txt)

        # 结账（默认全选）：金额按互抵后算
        pg.click("#sheet-save"); pg.wait_for_selector("#f-net", timeout=4000); pg.wait_for_timeout(300)
        fn = pg.inner_text("#f-net").replace("\n", " ")
        check("结账弹窗：写明抵完还要结什么，= 应收 $30", "抵完还要结" in fn and "Ali 调入 1 根 $60" in fn and "Bar Pro 调出 3 根 $90" in fn and "应收" in fn and "$30" in fn, fn.replace("\n", " / "))
        if SHOT and mode == "新结构": pg.screenshot(path=SHOT + "-结账.png", full_page=False)
        pg.click("#sheet-save"); pg.wait_for_timeout(1200)
        st = pg.evaluate("window.__GM.S.settles.map((x) => x.amount)")
        check("结账记的金额 = −30（他付我 30）", st == [-30], str(st))
        check("结完账两清", pg.evaluate(f"window.__GM.ledgerNet('{W}')") == 0)

        # 当场换货：同系列同根数，价不一样 → 两清（自动关单）；不同系列照算差价
        e1 = pg.evaluate("window.__GM.xferEff({ out: [{ sku: 'XF-04', qty: 1, unit: 55 }], in: [{ sku: 'XF-03', qty: 1, unit: 60 }] })")
        e2 = pg.evaluate("window.__GM.xferEff({ out: [{ sku: 'XF-01', qty: 1, unit: 30 }], in: [{ sku: 'XF-03', qty: 1, unit: 60 }] })")
        e3 = pg.evaluate("window.__GM.xferEff({ out: [{ sku: 'XF-04', qty: 3, unit: 55 }], in: [{ sku: 'XF-03', qty: 1, unit: 60 }] })")
        check("换货：Ali 1 换 Ali 1（55 对 60）→ 两清", e1 == 0, str(e1))
        check("换货：Bar Pro 1 换 Ali 1 → 照算差价（你欠 30）", e2 == -30, str(e2))
        check("换货：Ali 3 换 Ali 1 → 抵 1 根，剩 2 根 @55 = 他欠你 110", e3 == 110, str(e3))
        if mode == "新结构":
            check("新结构：结账只存正向列表，往来流水没存复制品", not any(k.startswith("t-") for k in pg.evaluate("Object.keys(__server('v2_movements'))")))
        ctx.close()
    br.close()

print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
