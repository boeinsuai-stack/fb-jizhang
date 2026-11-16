"""财务「每周」（2026-11-17 Bowen：要能看每一周；一点开就是本周总数，往下就是每天每一单，不要多出来的条）
- 不加新的一行：选「本周」时，净赚那一块右上角 ‹ ›；在这一块上左右滑也能换（往左滑 = 下一周），换的时候震一下
- 本周不能再往后；那一周的净赚、每天都换成那一周的；欠合伙人的一行写完
- 一周一周加起来 = 「全部」的净赚；选过以前的某一周，下次打开回到本周
用编出来的小数据，旧结构 / 新结构各一遍，GitHub 上也跑。运行：python3 tests/test_weeks.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib, re
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
T0 = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date()
MON = T0 - datetime.timedelta(days=T0.weekday())
day = lambda wk, wd: (MON - datetime.timedelta(weeks=wk) + datetime.timedelta(days=wd)).isoformat()  # 第几周前、周几（0 = 周一）
V1 = {"items": {"XF-01": {"sku": "XF-01", "series": "Ali", "variant": "Apple", "name": "Apple", "price_aud": 60, "cost_aud": 20, "status": "在售"}},
      "movements": {"in-1": {"type": "in", "sku": "XF-01", "name": "Apple", "qty": 100, "date": day(12, 0), "at": day(12, 0) + "T01:00:00Z", "note": "进货", "cost": 2000}},
      "orders": {}, "expenses": {}, "purchases": {}, "transfers": {}, "settlements": {}, "customers": {}, "followups": {}}
# 本周 1 单 2 根；上周 2 单（周一、周日）各 1 根；两周前没卖；10 周前 1 单 3 根 → 一共 11 周
SALES = [("a", 0, 0, 2), ("b", 1, 0, 1), ("c", 1, 6, 1), ("d", 10, 2, 3)]
for oid, wk, wd, q in SALES:
    d = day(wk, wd)
    V1["orders"][oid] = {"status": "paid", "date": d, "at": d + "T02:00:00Z", "customer": "", "payment": "现金", "lines": [{"sku": "XF-01", "name": "Apple", "qty": q, "unit_price": 60}], "delivery_fee": 0, "note": ""}
    V1["movements"][oid + "-XF-01"] = {"type": "out", "sku": "XF-01", "name": "Apple", "qty": q, "date": d, "at": d + "T02:00:00Z", "order_id": oid, "note": "卖出"}
V1["expenses"]["e1"] = {"date": day(1, 3), "at": day(1, 3) + "T05:00:00Z", "category": "其他", "amount": 10, "note": "停车"}  # 上周一笔费用
NET = {0: 80, 1: 70, 10: 120}  # 每根赚 40；上周 80 − 10
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "v1.json").write_text(json.dumps(V1, ensure_ascii=False), encoding="utf8")
subprocess.run(["node", str(ROOT / "v2_seed.js"), str(tmp / "v1.json"), str(tmp / "v2.json")], check=True, capture_output=True)
V2 = json.loads((tmp / "v2.json").read_text(encoding="utf8")); V2["meta"] = {"schema": {"version": 2}, "backfill": {"done": True}}

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(type("H", (http.server.SimpleHTTPRequestHandler,), {"log_message": lambda *a: None}), directory=str(PUB)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
results = []
def check(name, ok, extra=""):
    results.append(ok); print(("✅ " if ok else "❌ ") + name + (("  " + str(extra)) if extra and not ok else ""))
md = lambda s: f"{int(s[5:7])}月{int(s[8:])}日"
money = lambda s: float(re.sub(r"[^\d.\-]", "", s) or 0)

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
    for mode in ("旧结构", "新结构"):
        seed = V2 if mode == "新结构" else dict(V1, meta={"backfill": {"done": True}})
        ctx = br.new_context(viewport={"width": 390, "height": 844}, has_touch=True, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
        ctx.add_init_script("window.__SEED = " + json.dumps(seed, ensure_ascii=False) + ";")
        pg = ctx.new_page(); pg.on("pageerror", lambda e: (print("   页面报错：", e), results.append(False)))
        pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
        pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
        pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html#finance"); pg.wait_for_function("document.getElementById('f-profit').textContent !== '–'", timeout=15000); pg.wait_for_timeout(400); pg.wait_for_timeout(400)
        print("== " + mode)
        SWIPE = """(dx) => { const h = document.getElementById('f-hero'), r = h.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + 60;
          const t = (cx) => new Touch({ identifier: 1, target: h, clientX: cx, clientY: y });
          h.dispatchEvent(new TouchEvent('touchstart', { touches: [t(x)], changedTouches: [t(x)], bubbles: true }));
          h.dispatchEvent(new TouchEvent('touchend', { touches: [], changedTouches: [t(x + dx)], bubbles: true })); }"""
        pg.click('#period [data-p="week"]'); pg.wait_for_timeout(300)
        check("一点开：本周净赚 $80，右上角 ‹ ›，本周不能再往后（› 灰着）", money(pg.inner_text("#f-profit")) == 80 and pg.is_visible("#f-wkarr") and pg.is_disabled('#f-wkarr [data-wk="1"]') and not pg.is_disabled('#f-wkarr [data-wk="-1"]'))
        check("没有另外多出来的一行（时间范围下面直接是净赚那一块）", pg.locator("#f-wkpick, #f-wkstrip, #f-weeks, #f-wknav").count() == 0)
        check("「每天」在第一屏就看得到", pg.evaluate("document.getElementById('f-daily').getBoundingClientRect().top < innerHeight - 60"), pg.evaluate("document.getElementById('f-daily').getBoundingClientRect().top"))
        pg.evaluate("window.__vib = 0; navigator.vibrate = () => { window.__vib++; return true; }; 0")  # 末尾 0：不然 evaluate 会把这个函数当成要执行的
        pg.click('#f-wkarr [data-wk="-1"]'); pg.wait_for_timeout(250)
        check("点 ‹：上周 $70、写明日期、震一下", money(pg.inner_text("#f-profit")) == 70 and md(day(1, 0)) in pg.inner_text("#f-hero-k") and pg.evaluate("window.__vib") == 1, (pg.inner_text("#f-hero-k"), pg.evaluate("window.__vib")))
        check("「本周」标签还亮着、「每天」里只有那一周的 3 天（两天卖、一天费用）", pg.get_attribute('#period [data-p="week"]', "aria-pressed") == "true" and pg.locator("#f-daily details.day").count() == 3, pg.locator("#f-daily details.day").count())
        pg.evaluate(SWIPE, 140); pg.wait_for_timeout(250)
        check("在净赚那一块往右滑：再往前一周（没卖，写明没有账），震一下", money(pg.inner_text("#f-profit")) == 0 and md(day(2, 0)) in pg.inner_text("#f-hero-k") and pg.evaluate("window.__vib") == 2 and not pg.is_hidden("#f-empty"))
        pg.evaluate(SWIPE, -140); pg.evaluate(SWIPE, -140); pg.wait_for_timeout(250)
        check("往左滑两下：回到本周 $80", money(pg.inner_text("#f-profit")) == 80 and pg.is_disabled('#f-wkarr [data-wk="1"]'))
        pg.evaluate(SWIPE, -140); pg.wait_for_timeout(200)
        check("本周再往左滑：不动、不震", money(pg.inner_text("#f-profit")) == 80 and pg.evaluate("window.__vib") == 4, pg.evaluate("window.__vib"))
        pg.evaluate(SWIPE, 30); pg.wait_for_timeout(200)
        check("手指只动一点（30 像素）：不算滑", money(pg.inner_text("#f-profit")) == 80)
        tot = 0
        for k in range(11):
            tot += money(pg.inner_text("#f-profit")); pg.click('#f-wkarr [data-wk="-1"]'); pg.wait_for_timeout(120)
        pg.click('#period [data-p="all"]'); pg.wait_for_timeout(200)
        check("一周一周往前加起来 = 「全部」净赚 $270", tot == 270 and money(pg.inner_text("#f-profit")) == 270, (tot, pg.inner_text("#f-profit")))
        check("选「全部」时没有 ‹ ›，左右滑也不换", pg.is_hidden("#f-wkarr") and (pg.evaluate(SWIPE, 140) or True) and money(pg.inner_text("#f-profit")) == 270)
        check("欠合伙人的那一块：不超过一行高", pg.evaluate("(() => { const o = document.getElementById('f-owe'); return o.hidden || o.getBoundingClientRect().height < 60; })()"))
        pg.click('#period [data-p="week"]'); pg.click('#f-wkarr [data-wk="-1"]'); pg.wait_for_timeout(200)
        pg.reload(); pg.wait_for_function("document.getElementById('f-profit').textContent !== '–'", timeout=15000); pg.wait_for_timeout(400)
        check("选过以前的某一周，下次打开回到本周", money(pg.inner_text("#f-profit")) == 80 and pg.get_attribute('#period [data-p="week"]', "aria-pressed") == "true")
        ctx.close()
    br.close()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
