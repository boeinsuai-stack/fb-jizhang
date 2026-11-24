"""预定卡片上「配送 / 自取」小标签（2026-11-18 Bowen 要的；11-20：两个按钮重复了——填了配送费就是配送，没填就是自取）
- 卡片上客人名字旁边：有配送费 = 配送，没有 = 自取；只是显示，不能点
- 记单 / 编辑预定：不再有「配送 / 自取」按钮，只填配送费
用编出来的小数据，旧结构 / 新结构各一遍，GitHub 上也跑。运行：python3 tests/test_handoff.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
IT = lambda sku, ser, v, n, c: {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": 60, "cost_aud": c, "status": "在售"}
RES = lambda oid, who, fee, note, n: (oid, {"status": "reserved", "date": TODAY, "at": TODAY + "T0%d:00:00Z" % n, "customer": who, "payment": None, "delivery_fee": fee, "note": note,
                                            "lines": [{"sku": "XF-01", "name": "香蕉", "qty": 1, "unit_price": 30}]})
V1 = {"items": {"XF-01": IT("XF-01", "Bar Pro", "Banana Buzz", "香蕉", 30)},
      "movements": {"in-1": {"type": "in", "sku": "XF-01", "name": "香蕉", "qty": 40, "date": TODAY, "at": TODAY + "T00:30:00Z", "note": "进货", "cost": 1000}},
      "orders": dict([RES("o-fee", "Amy", 10, "", 1), RES("o-self", "Bob", 0, "下午三点之后来自取", 2), RES("o-send", "Cat", 0, "晚上送到 Cockburn", 3), RES("o-unk", "Dan", 0, "下午四点", 4)]),
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

def tag(pg, oid): return pg.locator(f'#resv details:has([data-settle="{oid}"]) .tag-ho')
def order(pg, oid): return next((x for x in S(pg, "orders") if x["id"] == oid), {})
def opened(pg, oid): return pg.evaluate(f"""document.querySelector('[data-ho="{oid}"]').closest('details').open""")

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    for mode in ("旧结构", "新结构"):
        seed = V2 if mode == "新结构" else dict(V1, meta={"backfill": {"done": True}})
        ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
        ctx.add_init_script("window.__SEED = " + json.dumps(seed, ensure_ascii=False) + ";")
        pg = ctx.new_page(); pg.set_default_timeout(8000); pg.on("pageerror", lambda e: (print("   页面报错：", e), results.append(False)))
        pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
        pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
        pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.goto(URL); pg.wait_for_function("window.__GM && window.__GM.S.loaded", timeout=15000); pg.wait_for_timeout(500)
        print("== " + mode)
        go(pg, "reserve")
        got = {o: tag(pg, o).inner_text() for o in ("o-fee", "o-self", "o-send", "o-unk")}
        check("有配送费 → 配送，没有 → 自取（备注里写什么不管）", got == {"o-fee": "配送", "o-self": "自取", "o-send": "自取", "o-unk": "自取"}, got)
        check("标签在客人名字旁边，只是显示（不是按钮）", tag(pg, "o-unk").is_visible() and tag(pg, "o-unk").evaluate("(e) => e.tagName") == "SPAN")
        pg.evaluate("""() => document.querySelector('[data-edit-order="o-unk"]').click()"""); pg.wait_for_selector("#f-fee")
        check("编辑预定：没有「配送 / 自取」按钮", pg.locator('#sheet input[name="f-hor"], #f-ho').count() == 0)
        pg.fill("#f-fee", "15"); save(pg)
        check("填了配送费 $15 → 卡片变「配送」", tag(pg, "o-unk").inner_text() == "配送" and order(pg, "o-unk").get("delivery_fee") == 15)
        pg.evaluate("""() => document.querySelector('[data-edit-order="o-fee"]').click()"""); pg.wait_for_selector("#f-fee")
        pg.fill("#f-fee", ""); save(pg)
        check("配送费清掉 → 自取", tag(pg, "o-fee").inner_text() == "自取")
        ctx.close()
    br.close()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
