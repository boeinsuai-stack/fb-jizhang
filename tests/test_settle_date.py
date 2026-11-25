"""结算那天 = 卖出那天（2026-11-25 Bowen：昨天记的预定、交货点「明天」，今天结算却记成昨天卖的）
- 一点结算、「客人怎么付的？」结算：订单 date、扣库存流水、按单拿货的流水和支出都是今天（以前是记预定那天）
用编出来的小数据，旧结构 / 新结构各一遍，GitHub 上也跑。运行：python3 tests/test_settle_date.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
IT = lambda sku, ser, v, n, c: {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": 60, "cost_aud": c, "status": "在售"}
YDAY = (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=1)).isoformat()
# 昨天记的预定、交货点了「明天」（= 今天）
RES = lambda oid, who, pay, qty, n: (oid, {"status": "reserved", "date": YDAY, "at": YDAY + "T0%d:00:00Z" % n, "customer": who, "payment": pay, "delivery_fee": 0, "note": "",
                                          "meet_date": TODAY, "lines": [{"sku": "XF-01", "name": "香蕉", "qty": qty, "unit_price": 30}]})
V1 = {"items": {"XF-01": IT("XF-01", "Bar Pro", "Banana Buzz", "香蕉", 30)},
      "movements": {"in-1": {"type": "in", "sku": "XF-01", "name": "香蕉", "qty": 40, "date": YDAY, "at": YDAY + "T00:30:00Z", "note": "进货", "cost": 1000}},
      "orders": dict([RES("o-quick", "Amy", "现金", 2, 1), RES("o-pick", "Bob", None, 3, 2), RES("o-more", "Cat", "转账", 50, 3)]),  # Cat 要 50 根、只有 40 → 差的按单拿货
      "expenses": {}, "purchases": {}, "transfers": {}, "settlements": {}, "customers": {}, "followups": {}}
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "v1.json").write_text(json.dumps(V1, ensure_ascii=False), encoding="utf8")
subprocess.run(["node", str(ROOT / "v2_seed.js"), str(tmp / "v1.json"), str(tmp / "v2.json")], check=True, capture_output=True)
V2 = json.loads((tmp / "v2.json").read_text(encoding="utf8")); V2["meta"] = {"schema": {"version": 2}, "backfill": {"done": True}}
EXPOSE = "\nwindow.__GM = { S };\n})();"
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
    results.append(ok); print(("✅ " if ok else "❌ ") + name + (("  " + str(extra)) if extra and not ok else ""))

go = lambda pg, h: (pg.evaluate(f"location.hash = '#{h}'"), pg.wait_for_timeout(300))
S = lambda pg, col: pg.evaluate(f"window.__GM.S.{col}")
def save(pg):
    pg.wait_for_timeout(200); pg.click("#sheet-save")
    try: pg.wait_for_selector("#sheet", state="hidden", timeout=3000)
    except Exception: pass
    pg.wait_for_timeout(450)
def close(pg): pg.click("#sheet-close"); pg.wait_for_timeout(250)
def chips_ok(pg):  # 付款方式是一排小标签、有现金+转账、没有下拉框
    return pg.locator("#sheet #f-paychips input[name=f-payr]").count() == 5 and pg.locator('#sheet #f-paychips input[value="现金+转账"]').count() == 1 and pg.locator("#sheet select#f-pay").count() == 0
def mix(pg, cash, other=None):
    pg.click('#f-paychips label:has(input[value="现金+转账"])'); pg.wait_for_timeout(120)
    pg.fill("#f-paycash", str(cash))
    if other: pg.select_option("#f-payother", other)
    pg.wait_for_timeout(150)

def order(pg, oid): return next((x for x in S(pg, "orders") if x["id"] == oid), {})
def moves(pg, oid): return [m for m in S(pg, "moves") if m.get("order_id") == oid]
def settle_btn(pg, oid): pg.evaluate(f"""document.querySelector('[data-settle="{oid}"]').click()"""); pg.wait_for_timeout(250)

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    for mode, data in (("旧结构", V1), ("新结构", V2)):
        print("==", mode)
        ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth")
        ctx.add_init_script("window.__SEED = " + json.dumps(data, ensure_ascii=False) + ";")
        pg = ctx.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
        for x in ("**/firebase-auth-compat.js", "**/firebase-firestore-compat.js"): pg.route(x, lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.goto(URL + "#reserve"); pg.wait_for_timeout(1800)

        # 1. 一点结算（记了付款方式）：点两下
        settle_btn(pg, "o-quick"); settle_btn(pg, "o-quick"); pg.wait_for_timeout(600)
        o = order(pg, "o-quick")
        check("一点结算：昨天记的预定，今天结算 → 卖出日期是今天", o.get("status") == "paid" and o.get("date") == TODAY, (o.get("status"), o.get("date")))
        ms = moves(pg, "o-quick")
        check("扣库存的流水也是今天", ms and all(m["date"] == TODAY for m in ms), [(m.get("type"), m.get("date")) for m in ms])

        # 2. 没记付款方式 → 弹出「客人怎么付的？」
        settle_btn(pg, "o-pick"); pg.wait_for_selector("#sheet-form input[name=f-payr]")
        pg.click('#sheet-form label:has(input[value="现金"])'); save(pg)
        o = order(pg, "o-pick")
        check("「客人怎么付的？」结算：卖出日期是今天", o.get("status") == "paid" and o.get("date") == TODAY, (o.get("status"), o.get("date")))

        # 3. 库存不够、按单拿货：拿货流水和拿货支出也是今天
        settle_btn(pg, "o-more"); settle_btn(pg, "o-more"); pg.wait_for_timeout(600)
        if pg.is_visible("#sheet"):  # 要先选找谁拿 → 走结算表单（表单本来就默认今天）
            save(pg)
        o = order(pg, "o-more"); ms = moves(pg, "o-more")
        ex = [e for e in S(pg, "expenses") if str(e.get("batch_id", "")).startswith("o-more")]
        check("按单拿货：订单、流水、拿货支出都是今天", o.get("date") == TODAY and ms and all(m["date"] == TODAY for m in ms) and all(e["date"] == TODAY for e in ex), (o.get("date"), [m.get("date") for m in ms], [e.get("date") for e in ex]))

        # 4. 财务：今天的卖出里有这三单
        go(pg, "finance")
        sold = pg.evaluate("window.__GM.S.orders.filter((o) => o.status === 'paid' && o.date === '" + TODAY + "').length")
        check("三单都算今天卖出", sold == 3, sold)
        check("没有报错", not errs, errs)
        ctx.close()
    br.close()
srv.shutdown()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
