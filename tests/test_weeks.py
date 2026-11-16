"""财务「每周」（2026-11-17 Bowen：要能看每一周；改成左右滑的柱子条、有震动反馈；往下一划就是这一周每天的明细）
- 选「本周」时，时间范围下面一排柱子：一周一根（高低 = 净赚），旧的在左、本周在最右；正中间小三角指着的那一周 = 选中的
- 左右滑：每滑过一周震一下（navigator.vibrate）；停下来就把上面的净赚和「每天」换成那一周；点一根柱子 = 滑到它
- 每周净赚加起来 = 「全部」的净赚；不再有竖着的「每周」列表（不挡住每天的明细）
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
        ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="block", timezone_id="Australia/Perth", locale="zh-CN")
        ctx.add_init_script("window.__SEED = " + json.dumps(seed, ensure_ascii=False) + ";")
        pg = ctx.new_page(); pg.on("pageerror", lambda e: (print("   页面报错：", e), results.append(False)))
        pg.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.fallback())
        pg.route("**/firebase-app-compat.js", lambda r: r.fulfill(body=MOCK, content_type="text/javascript"))
        pg.route("**/firebase-auth-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.route("**/firebase-firestore-compat.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
        pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html#finance"); pg.wait_for_function("document.getElementById('f-profit').textContent !== '–'", timeout=15000); pg.wait_for_timeout(400); pg.wait_for_timeout(400)
        print("== " + mode)
        COLS = "() => [...document.querySelectorAll('#f-wkstrip .wkcol')].map((b) => ({ mon: b.dataset.mon, t: b.innerText.replace(/\\s+/g, ' ').trim(), on: b.classList.contains('on'), h: b.querySelector('.bar').offsetHeight }))"
        pg.click('#period [data-p="week"]'); pg.wait_for_timeout(400)
        cols = pg.evaluate(COLS)
        check("一周一根柱子：从有账的第一周到本周 11 根，旧的在左、本周在最右", len(cols) == 11 and cols[0]["mon"] == day(10, 0) and cols[-1]["mon"] == day(0, 0) and cols[-1]["t"].endswith("本周"), [c["t"] for c in cols])
        check("一打开选中本周、滑到正中间", cols[-1]["on"] and pg.evaluate("(() => { const s = document.getElementById('f-wkstrip'), b = s.querySelector('.wkcol.on'); return Math.abs(b.offsetLeft + b.offsetWidth / 2 - s.scrollLeft - s.clientWidth / 2) < 3; })()"))
        check("柱子写净赚、高低跟净赚走：$120 那周最高、两周前没卖写「–」", "$120" in cols[0]["t"] and cols[0]["h"] == max(c["h"] for c in cols) and cols[-3]["t"].startswith("–"), [(c["t"], c["h"]) for c in cols])
        check("没有竖着的每周列表，往下就是「每天」", pg.locator("#f-weeks").count() == 0)
        pg.evaluate("window.__vib = 0; navigator.vibrate = () => { window.__vib++; return true; }")
        pg.evaluate("document.getElementById('f-wkstrip').scrollBy({ left: -68 })"); pg.wait_for_timeout(500)
        check("往左滑一周：震一下，停下来上面换成上周 $70、写明那一周的日期", pg.evaluate("window.__vib") >= 1 and money(pg.inner_text("#f-profit")) == 70 and md(day(1, 0)) in pg.inner_text("#f-hero-k"), (pg.evaluate("window.__vib"), pg.inner_text("#f-profit")))
        check("「本周」标签还亮着、「每天」里只有那一周的 3 天（两天卖、一天费用）", pg.get_attribute('#period [data-p="week"]', "aria-pressed") == "true" and pg.locator("#f-daily details.day").count() == 3, pg.locator("#f-daily details.day").count())
        pg.evaluate("window.__vib = 0"); pg.evaluate("document.getElementById('f-wkstrip').scrollBy({ left: -68 })"); pg.wait_for_timeout(60); pg.evaluate("document.getElementById('f-wkstrip').scrollBy({ left: -68 })"); pg.wait_for_timeout(500)
        check("再一口气滑两周（中间不停）：滑过一周震一下（2 下），停下来才换，到了没卖的那周写明没有账", pg.evaluate("window.__vib") == 2 and money(pg.inner_text("#f-profit")) == 0 and not pg.is_hidden("#f-empty"), pg.evaluate("window.__vib"))
        pg.locator("#f-wkstrip .wkcol").nth(0).click(); pg.wait_for_timeout(900)
        check("点最左边那根：滑过去，上面换成那一周 $120", money(pg.inner_text("#f-profit")) == 120, pg.inner_text("#f-profit"))
        tot = 0
        for k in range(len(cols)):
            pg.locator("#f-wkstrip .wkcol").nth(k).click(); pg.wait_for_timeout(700); tot += money(pg.inner_text("#f-profit"))
        pg.click('#period [data-p="all"]'); pg.wait_for_timeout(200)
        check("一周一周加起来 = 「全部」净赚 $270", tot == 270 and money(pg.inner_text("#f-profit")) == 270, (tot, pg.inner_text("#f-profit")))
        check("选「全部」时不显示柱子条", pg.is_hidden("#f-wkpick"))
        pg.click('#period [data-p="week"]'); pg.wait_for_timeout(300); pg.locator("#f-wkstrip .wkcol").nth(9).click(); pg.wait_for_timeout(800)
        pg.reload(); pg.wait_for_selector("#f-wkstrip .wkcol", timeout=15000); pg.wait_for_timeout(400)
        check("选过以前的某一周，下次打开回到本周", money(pg.inner_text("#f-profit")) == 80 and pg.evaluate(COLS)[-1]["on"])
        ctx.close()
    br.close()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
