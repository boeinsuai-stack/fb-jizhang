"""对账单里「改单价」：改还没结账的合伙人往来的单价（旧结构、新结构各跑一遍）。用编出来的小数据，GitHub 上也跑。
- 调出（他拿走的）用「整系列每根」一次改成 36；调入（他给我的）改一根的价，那几根的进价跟着改
- 应付/应收按新价算；已经结账的往来不出现、不被改
运行：python3 tests/test_xfer_price.py"""
import os, datetime, functools, http.server, json, subprocess, sys, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
EXPOSE = "\nwindow.__GM = { S, derive, ledgerNet };\n})();"
D = (datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date() - datetime.timedelta(days=3)).isoformat()
W = "合伙人甲"

item = lambda sku, ser, en: (sku, {"sku": sku, "series": ser, "variant": en, "name": en, "price_aud": 60, "cost_aud": 30, "status": "在售"})
mv = lambda **k: dict({"date": D, "at": D + "T01:00:00Z"}, **k)
V1 = {
    "items": dict([item("XF-01", "Bar Pro", "Banana Buzz"), item("XF-02", "Bar Pro", "Grape"), item("XF-03", "Ali", "Cool Mint"), item("XF-04", "Ali", "FTP")]),
    "movements": {
        "in-1": mv(type="in", sku="XF-01", name="Banana Buzz", qty=10, cost=300, note="进货"),
        "in-2": mv(type="in", sku="XF-02", name="Grape", qty=10, cost=300, note="进货"),
        # 他拿走 Bar Pro（没结账）
        "t-a-out-XF-01": mv(type="adjust", sku="XF-01", name="Banana Buzz", qty=-2, transfer_id="t-a", note="合伙人往来：给 " + W),
        "t-a-out-XF-02": mv(type="adjust", sku="XF-02", name="Grape", qty=-1, transfer_id="t-a", note="合伙人往来：给 " + W),
        # 他给我 Ali（没结账）
        "t-b-in-XF-03": mv(type="in", sku="XF-03", name="Cool Mint", qty=2, cost=100, transfer_id="t-b", note="合伙人往来：" + W + " 给的"),
        # 已经结过账的一笔：不能出现在改单价里
        "t-c-out-XF-01": mv(type="adjust", sku="XF-01", name="Banana Buzz", qty=-1, transfer_id="t-c", note="合伙人往来：给 " + W),
    },
    "transfers": {
        "t-a": {"date": D, "at": D + "T02:00:00Z", "partner": W, "out": [{"sku": "XF-01", "name": "Banana Buzz", "qty": 2, "unit": 30}, {"sku": "XF-02", "name": "Grape", "qty": 1, "unit": 30}], "in": [], "note": ""},
        "t-b": {"date": D, "at": D + "T03:00:00Z", "partner": W, "out": [], "in": [{"sku": "XF-03", "name": "Cool Mint", "qty": 2, "unit": 50}], "note": ""},
        "t-c": {"date": D, "at": D + "T00:30:00Z", "partner": W, "out": [{"sku": "XF-01", "name": "Banana Buzz", "qty": 1, "unit": 25}], "in": [], "note": "", "partner_settlement_id": "s-old"},
    },
    "settlements": {"s-old": {"date": D, "at": D + "T00:40:00Z", "order_ids": [], "transfer_ids": ["t-c"], "qty": {}, "amount": -25, "paid": -25, "partner": W, "payment": "现金", "note": "当场付清"}},
    "orders": {}, "expenses": {}, "purchases": {}, "customers": {}, "followups": {},
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
        pg.goto(URL); pg.wait_for_function("window.__GM && window.__GM.S.transfers.length === 3", timeout=15000); pg.wait_for_timeout(600)
        check("用的是" + mode, pg.evaluate("!!window.__fbV2store") == (mode == "新结构"))
        # 调入 2×50=100，调出 3×30=90 → 应付 10
        check("改之前：应付 10", pg.evaluate(f"window.__GM.ledgerNet('{W}')") == 10)

        pg.evaluate("location.hash = '#partner'"); pg.wait_for_timeout(400)
        pg.click(f'[data-lg-open="{W}"]'); pg.wait_for_selector('[data-lg="xprice"]', timeout=4000)
        pg.click('[data-lg="xprice"]'); pg.wait_for_selector("#f-xu-0", timeout=4000)
        n_rows = pg.evaluate("document.querySelectorAll('#sheet [id^=\"f-xu-\"]').length")
        check("列出没结账的 3 行（已结账的那笔不出现）", n_rows == 3, str(n_rows))
        pg.fill('#sheet .serp[data-side="out"] input[data-sr="Bar Pro"]', "36")
        vals = pg.evaluate("[0,1].map((k) => document.getElementById('f-xu-' + k).value)")
        check("调出「Bar Pro 整系列每根」填 36 → 两行都变 36", vals == ["36", "36"], str(vals))
        pg.fill("#f-xu-2", "45")
        sm = pg.inner_text("#f-xsum")
        # 调出 3×36=108，调入 2×45=90 → 应收 18
        check("改的时候就显示改完后的账：调出 $90 → $108、应收 18", "$108" in sm and "应收" in sm and "18" in sm, sm.replace("\n", " / "))
        pg.click("#sheet-save"); pg.wait_for_timeout(1200)
        S = pg.evaluate("(() => { const S = window.__GM.S; return { t: S.transfers, m: S.moves.filter((m) => m.transfer_id) }; })()")
        t = {x["id"]: x for x in S["t"]}
        check("调出单价存成 36", [l["unit"] for l in t["t-a"]["out"]] == [36, 36])
        check("调入单价存成 45，那几根的进价 = 90", t["t-b"]["in"][0]["unit"] == 45 and next(m for m in S["m"] if m["transfer_id"] == "t-b")["cost"] == 90)
        check("已结账的那笔没动（25）", t["t-c"]["out"][0]["unit"] == 25)
        check("改完：应收 18", pg.evaluate(f"window.__GM.ledgerNet('{W}')") == -18)
        check("保存后回到对账单", pg.is_visible('[data-lg="xprice"]'))
        if mode == "新结构":
            srv_m = pg.evaluate("Object.keys(__server('v2_movements'))")
            check("新结构：往来的流水还是现算的，没存复制品", not any(k.startswith("t-") for k in srv_m), str(srv_m))
            check("新结构：改的是往来源头", pg.evaluate("__server('v2_transfers')['t-a'].out.map((l) => l.unit).join()") == "36,36")
        ctx.close()
    br.close()

print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
