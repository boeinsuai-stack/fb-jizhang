"""客人少给 / 多给：只记在那一单上，「下次核对」点亮了才找回（2026-11-20 Bowen：默认都不用再找回来，只要一个按钮，点亮了就是下次要跟他核对）
- 选「客人多给了」：原因换成 转多了 / 没零钱找；换回少给就换回来（11-18）
- 「下次核对」默认不亮：存 gift: true（不算谁欠谁、不提醒、客户页不标）；点亮：下次给他记单提醒收回 / 少收，卡片写「· 下次核对」
- 财务「收款」按实际收到的写（11-19 Bowen：少给 $20，现金还写 $60，应该写 $40）；收入、净赚照旧按合计
用编出来的小数据，旧结构 / 新结构各一遍，GitHub 上也跑。运行：python3 tests/test_gift.py"""
import os, sys, json, datetime, functools, http.server, subprocess, tempfile, threading, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PUB = (ROOT.parent / "public").resolve()
MOCK = (ROOT / "mockfb.js").read_text(encoding="utf8")
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
IT = lambda sku, ser, v, n, c: {"sku": sku, "series": ser, "variant": v, "name": n, "price_aud": 60, "cost_aud": c, "status": "在售"}
def RES(oid, who, n):
    return oid, {"status": "reserved", "date": TODAY, "at": TODAY + "T0%d:00:00Z" % n, "customer": who, "payment": "现金", "delivery_fee": 0, "note": "",
                 "lines": [{"sku": "XF-01", "name": "香蕉", "qty": 2, "unit_price": 30}]}
V1 = {"items": {"XF-01": IT("XF-01", "Bar Pro", "Banana Buzz", "香蕉", 30)},
      "movements": {"in-1": {"type": "in", "sku": "XF-01", "name": "香蕉", "qty": 40, "date": TODAY, "at": TODAY + "T00:30:00Z", "note": "进货", "cost": 1000}},
      "orders": dict([RES("r-amy", "Amy", 1), RES("r-bob", "Bob", 2), RES("r-cat", "Cat", 3), RES("r-dan", "Dan", 4)]),
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
def card(pg, oid): return pg.evaluate(f"""document.querySelector('[data-settle="{oid}"]').closest('details').innerText""")
def vis(pg, sel): return pg.evaluate(f"""(() => {{ const e = document.querySelector('{sel}'); return !!e && !e.hidden && e.offsetParent !== null; }})()""")
def edit(pg, oid): go(pg, "customers"); pg.evaluate(f"""() => document.querySelector('[data-edit-order="{oid}"]').click()"""); pg.wait_for_selector("#f-diff-open", state="attached"); pg.wait_for_timeout(200)
def settle(pg, oid): go(pg, "customers"); pg.evaluate(f"""() => document.querySelector('[data-settle="{oid}"]').click()"""); pg.wait_for_timeout(600); save(pg)
def new_sale(pg, who):
    go(pg, "finance"); pg.click("#fin-sale"); pg.wait_for_selector("#f-skuq-0")
    pg.fill("#f-skuq-0", "香蕉"); pg.press("#f-skuq-0", "Enter"); pg.fill("#f-qty-0", "1"); pg.locator("#f-cust").press_sequentially(who); pg.wait_for_timeout(200)

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
        edit(pg, "r-amy"); pg.click("#f-diff-open")
        check("打开时少给 / 多给都没选", not pg.evaluate("!!document.querySelector('input[name=f-diffk]:checked')"))
        pg.click('#f-diff label:has(input[value="-1"])'); pg.wait_for_timeout(100)
        check("选「客人多给了」：原因换成「转多了 / 没零钱找」，不再是配送费没给", vis(pg, '#f-diff [data-for="-1"]') and not vis(pg, '#f-diff [data-for="1"]') and "转多了" in pg.inner_text('#f-diff [data-for="-1"]') and pg.get_attribute("#f-diffwhy", "placeholder") == "比如：转多了")
        check("只有一个「下次核对」按钮，默认不亮", vis(pg, "#f-track") is not None and pg.locator("#f-diff #f-track").count() == 1 and not pg.is_checked("#f-track") and pg.locator('input[name="f-gift"]').count() == 0)
        pg.click('#f-diff label:has(input[value="1"])'); pg.wait_for_timeout(100)
        check("换回「少给了」：原因换回配送费没给…", vis(pg, '#f-diff [data-for="1"]') and "配送费没给" in pg.inner_text('#f-diff [data-for="1"]'))
        pg.click('#f-diff label:has(input[value="-1"])'); pg.fill("#f-diffamt", "10"); pg.wait_for_timeout(100)
        check("合计下面写这次实际收 $70（合计 $60 + 多给的 $10）", "这次实际收 $70" in pg.inner_text("#f-baltot"), pg.inner_text("#f-baltot"))
        save(pg)
        b = (order(pg, "r-amy").get("bal") or [{}])[0]
        check("存了：多给 $10、gift = true", b.get("amt") == -10 and b.get("gift") is True and b.get("kind") == "diff", b)
        check("预定卡片写「这单多给 $10」，不写下次核对", "这单多给 $10" in card(pg, "r-amy") and "下次核对" not in card(pg, "r-amy"), card(pg, "r-amy"))
        edit(pg, "r-amy")
        check("再打开编辑：多给、$10 还在，下次核对没亮", pg.is_checked('#f-diff input[value="-1"]') and pg.input_value("#f-diffamt") == "10" and not pg.is_checked("#f-track") and vis(pg, '#f-diff [data-for="-1"]'))
        close(pg)
        settle(pg, "r-amy")
        check("结算了：送你的还记在那一单上", order(pg, "r-amy").get("status") == "paid" and (order(pg, "r-amy").get("bal") or [{}])[0].get("gift") is True)
        new_sale(pg, "Amy")
        check("下次给 Amy 记单：不提醒「上次多给」", pg.is_hidden("#f-balold"))
        close(pg)
        go(pg, "customers"); pg.fill("#cq", "amy"); pg.wait_for_timeout(250)
        check("客户页 Amy 那行不标「多给了」", "多给了" not in pg.inner_text("#c-list"))
        pg.evaluate("""() => { const b = [...document.querySelectorAll('[data-cu]')].find((x) => /Amy/.test(x.innerText)); b.click(); }"""); pg.wait_for_timeout(250)
        check("点开 Amy：买过什么里写「多给 $10」", "多给 $10" in pg.inner_text("#c-list") and "下次核对" not in pg.inner_text("#c-list"))
        pg.fill("#cq", ""); pg.wait_for_timeout(200)

        # 点亮「下次核对」：照旧提醒
        edit(pg, "r-bob"); pg.click("#f-diff-open"); pg.click('#f-diff label:has(input[value="-1"])'); pg.fill("#f-diffamt", "5"); pg.click('#f-diff [data-for="-1"] [data-diffwhy="转多了"]'); pg.check("#f-track"); save(pg)
        b = (order(pg, "r-bob").get("bal") or [{}])[0]
        check("Bob 多给 $5「转多了」、点亮下次核对：没有 gift", b.get("amt") == -5 and not b.get("gift") and b.get("why") == "转多了", b)
        check("卡片写「这单多给 $5 · 下次核对」", "这单多给 $5 · 下次核对" in card(pg, "r-bob"), card(pg, "r-bob"))
        settle(pg, "r-bob"); new_sale(pg, "Bob")
        check("下次给 Bob 记单：提醒「上次多给了你 $5」", "上次多给了你 $5" in pg.inner_text("#f-balold"), pg.inner_text("#f-balold") if pg.locator("#f-balold").count() else "")
        close(pg)

        # 少给：点亮「下次核对」才收回
        edit(pg, "r-cat"); pg.click("#f-diff-open"); pg.click('#f-diff label:has(input[value="1"])'); pg.wait_for_timeout(100)
        check("选「客人少给了」：同一个「下次核对」，默认不亮", not pg.is_checked("#f-track"))
        pg.fill("#f-diffamt", "20"); pg.check("#f-track"); save(pg); settle(pg, "r-cat")
        check("Cat 少给 $20、点亮下次核对：Cat 欠你 $20", not (order(pg, "r-cat").get("bal") or [{}])[0].get("gift") and order(pg, "r-cat").get("status") == "paid")
        edit(pg, "r-dan"); pg.click("#f-diff-open"); pg.click('#f-diff label:has(input[value="1"])'); pg.fill("#f-diffamt", "20"); pg.fill("#f-diffwhy", "上次多收了他 $20")
        save(pg)
        check("Dan 少给 $20、没点下次核对：卡片写「这单少给 $20」，gift = true", "这单少给 $20" in card(pg, "r-dan") and (order(pg, "r-dan").get("bal") or [{}])[0].get("gift") is True, card(pg, "r-dan"))
        settle(pg, "r-dan"); new_sale(pg, "Dan")
        check("下次给 Dan 记单：不提醒收回", pg.is_hidden("#f-balold"))
        close(pg)
        new_sale(pg, "Cat")
        check("下次给 Cat 记单：提醒「上次少给你 $20」", "上次少给你 $20" in pg.inner_text("#f-balold"))
        close(pg)

        # 财务：收款按实际收到的，收入按合计
        go(pg, "finance"); pg.wait_for_timeout(300)
        paysum = pg.inner_text("#f-paysum")
        check("财务「收款」：现金 $215（Amy 多给 10 → 70、Bob 多给 5 → 65、Cat 少给 20 → 40、Dan 少给 20 → 40）", "现金 $215" in paysum, paysum)
        # 2026-11-23 Bowen：不追的钱算进收入 → 合计 $240 + Amy 多给送你的 $10 − Dan 少给不用收的 $20；Bob、Cat 点了下次核对的不算
        check("收入：合计 $240 + 送你的 $10 − 不用收的 $20 = $230", "$230" in pg.inner_text("#f-inc"), pg.inner_text("#f-inc"))
        pg.evaluate("document.querySelectorAll('details.day').forEach((d) => { d.open = true; })"); pg.wait_for_timeout(150)
        day = pg.inner_text("body")
        check("那一单写「现金 $40」", "现金 $40" in day, day[:300])
        ctx.close()
    br.close()
print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
