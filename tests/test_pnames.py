"""合伙人名字按钮不重复（2026-11-20 Bowen：订货 / 合伙人拿货那边，选名字的那排按钮重复了两次）
- 原因：我拿货 / 他拿货两个弹窗自己加了一排名字按钮，所有合伙人输入框下面又统一加了一排 → 出现两次。拿掉自己加的那排
- 每个有合伙人名字的弹窗（订货、记往来、我拿货、他拿货、合伙人拿货·卖出）：每个名字只出现一次；点一下填上、高亮
用编出来的小数据，旧结构 / 新结构各一遍，GitHub 上也跑。运行：python3 tests/test_pnames.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
IT = lambda sku, ser, v, n, c: {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": 60, "cost_aud": c, "status": "在售"}
V1 = {"items": {"XF-01": IT("XF-01", "Bar Pro", "Banana Buzz", "香蕉", 30)},
      "movements": {"in-1": {"type": "in", "sku": "XF-01", "name": "香蕉", "qty": 40, "date": TODAY, "at": TODAY + "T00:30:00Z", "note": "进货", "cost": 1000}},
      "orders": {}, "expenses": {}, "purchases": {}, "settlements": {}, "customers": {}, "followups": {},
      "transfers": {"t-1": {"date": TODAY, "at": TODAY + "T01:00:00Z", "partner": "合伙人甲", "out": [{"sku": "XF-01", "name": "香蕉", "qty": 1, "unit_price": 30}], "in": []},
                    "t-2": {"date": TODAY, "at": TODAY + "T02:00:00Z", "partner": "合伙人乙", "out": [{"sku": "XF-01", "name": "香蕉", "qty": 1, "unit_price": 30}], "in": []}}}
for t in V1["transfers"]: V1["movements"][t + "-out-XF-01"] = {"type": "out", "sku": "XF-01", "name": "香蕉", "qty": 1, "date": TODAY, "at": V1["transfers"][t]["at"], "transfer_id": t, "partner": V1["transfers"][t]["partner"], "note": "调出"}
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

def counts(pg):
    return pg.evaluate("""(() => { const c = {}; for (const b of document.querySelectorAll('#sheet button, #sheet label.chip')) { const t = b.innerText.trim(); if (t === '合伙人甲' || t === '合伙人乙') c[t] = (c[t] || 0) + 1; } return c; })()""")
def pick(pg, name, inp):
    pg.click(f'#sheet [data-pname="{name}"]'); pg.wait_for_timeout(100)
    return pg.input_value(inp) == name and pg.get_attribute(f'#sheet [data-pname="{name}"]', "aria-pressed") == "true"

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    for mode in ("旧结构", "新结构"):
        seed = V2 if mode == "新结构" else dict(V1, meta={"backfill": {"done": True}})
        for d in ("take", "give"):
            ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
            ctx.add_init_script("window.__SEED = " + json.dumps(seed, ensure_ascii=False) + "; try { localStorage.setItem('mk-ptdir', '" + d + "'); } catch (_) {}")
            pg = ctx.new_page(); pg.set_default_timeout(8000); pg.on("pageerror", lambda e: (print("   页面报错：", e), results.append(False)))
            pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
            pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
            pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
            pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
            pg.goto(URL); pg.wait_for_function("window.__GM && window.__GM.S.loaded", timeout=15000); pg.wait_for_timeout(500)
            if d == "take":
                print("== " + mode)
                go(pg, "purchases"); pg.click("#po-new"); pg.wait_for_selector("#f-supplier", state="attached")
                c = counts(pg); check("订货：合伙人甲、乙各一个按钮", c == {"合伙人甲": 1, "合伙人乙": 1}, c)
                close(pg)
                go(pg, "finance"); pg.evaluate("document.getElementById('fin-xfer').click()"); pg.wait_for_selector("#f-xwho")
                c = counts(pg); check("记往来：合伙人甲、乙各一个按钮", c == {"合伙人甲": 1, "合伙人乙": 1}, c)
                check("记往来：点「合伙人乙」填上、高亮", pick(pg, "合伙人乙", "#f-xwho"))
                close(pg)
                go(pg, "partner"); pg.evaluate("document.getElementById('pt-new').click()"); pg.wait_for_timeout(500)
                c = counts(pg); check("合伙人拿货 · 卖出：合伙人甲、乙各最多一个按钮", all(v == 1 for v in c.values()), c)
                close(pg)
            go(pg, "partner"); pg.wait_for_timeout(300)
            pg.evaluate("""() => { const b = () => document.querySelector('#ptx-tiles [data-padd="XF-01"]'); b().click(); }"""); pg.wait_for_timeout(250)
            pg.click("#cb-go"); pg.wait_for_selector("#f-xwho")
            nm_ = "我拿货（跟谁拿的）" if d == "take" else "他拿货（谁拿的）"
            c = counts(pg); check(f"{nm_}：合伙人甲、乙各一个按钮（以前两个）", c == {"合伙人甲": 1, "合伙人乙": 1}, c)
            check(f"{nm_}：点「合伙人甲」填上、高亮", pick(pg, "合伙人甲", "#f-xwho"))
            ctx.close()
    br.close()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
