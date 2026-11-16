"""财务「每周」（2026-11-17 Bowen：财务要能看每一周，不只是本周）
- 每周一行（周一到周日）：几单 · 几根、净赚、收入；从本周往回排到有账的第一周，没卖的周写「没卖」；多于 8 周折叠
- 点一周 = 上面的净赚/收入/每天都换成那一周；「‹ 上一周 / 下一周 ›」一周一周翻，本周不能再往后
- 每周净赚加起来 = 「全部」的净赚；那一周的数字 = 选那一周时上面显示的
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
ROWS = "() => [...document.querySelectorAll('#f-weeks .wkrow')].map((r) => r.innerText.replace(/\\s+/g, ' ').trim())"
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
        pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html#finance"); pg.wait_for_selector("#f-weeks .wkrow", timeout=15000); pg.wait_for_timeout(400)
        print("== " + mode)
        rows = pg.evaluate(ROWS)
        check("从本周往回排到有账的第一周：11 周，多于 8 周先显示 8 周", len(rows) == 8 and pg.inner_text("#wk-more") == "看更早的 3 周", (len(rows), rows[:2]))
        check("本周：「本周 · 周一–周日」、1 单 · 2 根、净赚 $80", rows[0].startswith("本周 · " + md(day(0, 0))) and "1 单 · 2 根" in rows[0] and "$80" in rows[0], rows[0])
        check("上周：2 单 · 2 根（周一、周日都算这一周）、净赚 $70（扣掉 $10 停车费）、收入 $120", "2 单 · 2 根" in rows[1] and "$70" in rows[1] and "收入 $120" in rows[1], rows[1])
        check("两周前没卖：写「没卖」", "没卖" in rows[2], rows[2])
        pg.click("#wk-more"); pg.wait_for_timeout(150); rows = pg.evaluate(ROWS)
        check("展开后 11 周，最后一周 1 单 · 3 根 · $120", len(rows) == 11 and "1 单 · 3 根" in rows[10] and "$120" in rows[10], rows[-1:])
        tot = sum(money(re.search(r"\$-?[\d.]+", r.split("收入")[0]).group(0)) for r in rows if "$" in r.split("收入")[0])
        pg.click('#period [data-p="all"]'); pg.wait_for_timeout(200)
        check("每周净赚加起来 = 「全部」净赚 $270", tot == 270 and money(pg.inner_text("#f-profit")) == 270, (tot, pg.inner_text("#f-profit")))
        check("选「全部」时不显示一周一周翻", pg.is_hidden("#f-wknav"))
        pg.locator("#f-weeks .wkrow").nth(1).click(); pg.wait_for_timeout(250)
        check("点上周那一行：上面净赚 $70、写明那一周的日期", money(pg.inner_text("#f-profit")) == 70 and md(day(1, 0)) in pg.inner_text("#f-hero-k"), pg.inner_text("#f-hero-k"))
        check("「本周」标签亮着、那一行高亮、每天里只有那一周的 3 天（两天卖、一天费用）", pg.get_attribute('#period [data-p="week"]', "aria-pressed") == "true" and pg.locator('#f-weeks .wkrow[aria-current="true"]').count() == 1
              and pg.locator("#f-daily details.day").count() == 3, pg.locator("#f-daily details.day").count())
        pg.click('#f-wknav [data-wk="-1"]'); pg.wait_for_timeout(200)
        check("‹ 上一周：两周前，没有账（写明以前的账都还在）", money(pg.inner_text("#f-profit")) == 0 and not pg.is_hidden("#f-empty"), pg.inner_text("#f-profit"))
        pg.click('#f-wknav [data-wk="1"]'); pg.click('#f-wknav [data-wk="1"]'); pg.wait_for_timeout(200)
        check("下一周 › 翻回本周：$80，「下一周」不能再点", money(pg.inner_text("#f-profit")) == 80 and "本周" in pg.inner_text("#f-wknav") and pg.is_disabled('#f-wknav [data-wk="1"]'))
        pg.locator("#f-weeks .wkrow").nth(1).click(); pg.wait_for_timeout(200)
        pg.reload(); pg.wait_for_selector("#f-weeks .wkrow", timeout=15000); pg.wait_for_timeout(300)
        check("选过以前的某一周，下次打开回到本周（不会停在旧的一周）", money(pg.inner_text("#f-profit")) == 80 and pg.get_attribute('#period [data-p="week"]', "aria-pressed") == "true")
        ctx.close()
    br.close()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
