"""库存页「能卖」那块：零库存的口味也要看得到（2026-11-29 Bowen：就算是零个库存的东西，也应该能在库存页面看到）
- 每个系列有货的在上面，没货的（不含停售）灰着排在下面写 0；合计照旧只算有货的
用编出来的小数据，旧结构 / 新结构各一遍，GitHub 上也跑。运行：python3 tests/test_stock_zero.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
IT = lambda sku, ser, v, n, c: {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": 60, "cost_aud": c, "status": "在售"}
IT2 = lambda sku, ser, v, n, st="在售": {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": 90, "cost_aud": 30, "status": st}
MV = lambda k, sku, q, t="in": ("m-%s" % k, {"type": t, "sku": sku, "name": sku, "qty": q, "date": TODAY, "at": TODAY + "T01:00:00Z", "note": "进货", "cost": 30 * q})
V1 = {"items": {"S-1": IT2("S-1", "Storm", "Cola Ice", "可乐冰"), "S-2": IT2("S-2", "Storm", "Berry Bliss", "缤纷莓果"), "S-3": IT2("S-3", "Storm", "Fresh Mint", "清新薄荷"),
                "S-4": IT2("S-4", "Storm", "Red Energy", "红牛风味"), "S-5": IT2("S-5", "Storm", "Old Flavour", "旧口味", "停售"), "S-6": IT2("S-6", "Storm", "Grape Ice", "葡萄冰")},
      "movements": dict([MV(1, "S-1", 5), MV(2, "S-2", 1), MV(3, "S-6", 2), MV(4, "S-6", 2, "out")]),
      "orders": {"o-r": {"status": "reserved", "date": TODAY, "at": TODAY + "T02:00:00Z", "customer": "Amy", "payment": None, "lines": [{"sku": "S-4", "name": "Red Energy", "qty": 2, "unit_price": 90}]}},
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
        pg.goto(URL + "#inventory"); pg.wait_for_timeout(1800)
        col = pg.evaluate("""(() => { const c = [...document.querySelectorAll('.sb-col')].find((c) => /Storm/.test(c.querySelector('h3').textContent));
          return { h: c.querySelector('h3').innerText.replace(/\\s+/g, ' '), li: [...c.querySelectorAll('li')].map((l) => [l.className, l.innerText.replace(/\\s+/g, ' ')]) }; })()""")
        li = col["li"]
        check("有货的在上面（按名字）：Berry Bliss 1、Cola Ice 5", li[:2] == [["low", "Berry Bliss 1"], ["", "Cola Ice 5"]], li)
        check("没货的灰着排在下面写 0：Fresh Mint、Grape Ice（卖完了）、Red Energy（被预定 2 根也写 0 · 订2）", [x[0] for x in li[2:]] == ["zero"] * 3 and [x[1] for x in li[2:]] == ["Fresh Mint 0", "Grape Ice 0", "Red Energy 0订2"], li)
        check("停售的不列", not any("Old Flavour" in x[1] for x in li), li)
        check("系列合计、能卖总数照旧只算有货的：Storm 6 根", col["h"] == "Storm 6 根" and pg.inner_text("#sb-total") == "6", (col["h"], pg.inner_text("#sb-total")))
        check("没有报错", not errs, errs)
        ctx.close()
    br.close()
srv.shutdown()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
